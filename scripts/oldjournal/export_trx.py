#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/journal/export_trx.py
Version: 1.0.4 (LOCKED)
Updated: 2025-12-21 (SGT)

Purpose
-------
Export Schwab TRANSACTIONS into DuckDB (journal schema), with NO DUPLICATES:

- ALWAYS persist raw transactions payloads into journal.transactions_raw
  (source of truth; used by canonical views).
- Normalize and load journal.transaction_items idempotently.
- Append journal.run_log safely (never dies on sequence drift).

LOCKED invariants (do not “optimize”)
-------------------------------------
1) Authoritative activity_id list comes from tx_df (drives cleanup even if zero legs).
2) Leg keys normalized + de-duped BEFORE write:
   - activity_id -> int64, leg_index -> int32
   - drop_duplicates on (account_hash, activity_id, leg_index)
3) Write order is fixed:
   - executemany(INSERT OR REPLACE ...) for legs
   - cleanup stale/orphan legs using aids_df + keys_df
4) Post-write duplicate scan is not required (unique index enforces it).

Idempotency rules
-----------------
transactions_raw:
  - keep exactly ONE row per (account_hash, from_iso, to_iso) via delete-then-insert.

transaction_items:
  - unique key is (account_hash, activity_id, leg_index)
  - incoming df is normalized + de-duped by that key
  - load uses INSERT OR REPLACE (safe even if delete misses due to dtype drift)

Why duplicate-key errors happened
--------------------------------
Schwab sometimes repeats an activityId inside the same window (or across re-runs).
If you process the same activityId twice, leg_index restarts at 1 and collides.

Env
---
export SCHWAB_BASE="https://api.schwabapi.com"
export SCHWAB_RESOURCE_VERSION="1"
export SCHWAB_CLIENT_CORRELID="tgps-journal"
export TOKEN_PATH="$HOME/tgps-project/data/schwab/schwab_tokens.json"
export JOURNAL_DB="$HOME/tgps-project/data/journal/tgps_trades.duckdb"
export SCHWAB_RAW_DIR="$HOME/tgps-project/data/schwab_raw"

CLI
---
python -m scripts.journal.export_trx \
  --db "$HOME/tgps-project/data/journal/tgps_trades.duckdb" \
  --from 2025-11-17 \
  --to   2025-11-19 \
  --debug
"""

from __future__ import annotations

import os
import sys
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import duckdb
import pandas as pd
import requests

from client.schwab_admin import TokenStore, AuthClient


# ---------------------------------------------------------------------------
# Config & endpoints
# ---------------------------------------------------------------------------

SCHWAB_BASE = os.environ.get("SCHWAB_BASE", "https://api.schwabapi.com")
TRADER_V1 = f"{SCHWAB_BASE}/trader/v1"

ACCOUNT_NUMBERS_URL = f"{TRADER_V1}/accounts/accountNumbers"
TRANSACTIONS_URL_FMT = f"{TRADER_V1}/accounts/{{hash}}/transactions"

DEFAULT_DB = os.path.expanduser(
    os.environ.get("JOURNAL_DB", "~/tgps-project/data/journal/tgps_trades.duckdb")
)

RAW_DIR = Path(
    os.path.expanduser(
        os.environ.get("SCHWAB_RAW_DIR", "~/tgps-project/data/schwab_raw")
    )
)


# ---------------------------------------------------------------------------
# Helpers: time & parsing
# ---------------------------------------------------------------------------


def to_utc_day_start(date_str: str) -> str:
    return f"{date_str}T00:00:00.000Z"


def to_utc_day_end(date_str: str) -> str:
    return f"{date_str}T23:59:59.000Z"


def _safe_datetime(s: Optional[str]) -> Optional[pd.Timestamp]:
    if not s:
        return None
    dt = pd.to_datetime([s], errors="coerce", utc=True)[0]
    if dt is None or pd.isna(dt):
        return None
    if getattr(dt, "year", 1970) < 1970:
        return None
    try:
        return dt.tz_convert("UTC")
    except Exception:
        return dt


def _safe_date_ymd(s: Optional[str]):
    dt = _safe_datetime(s)
    return dt.date() if dt is not None else None


def _dbg(enabled: bool, msg: str):
    if enabled:
        print(msg, flush=True)


# ---------------------------------------------------------------------------
# HTTP wrapper (Schwab + shared AuthClient)
# ---------------------------------------------------------------------------


@dataclass
class SchwabHttp:
    session: requests.Session
    auth: AuthClient
    timeout: int = 90

    def _build_headers(self, access_token: str) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "Schwab-Resource-Version": os.environ.get("SCHWAB_RESOURCE_VERSION", "1"),
            "Schwab-Client-CorrelId": os.environ.get(
                "SCHWAB_CLIENT_CORRELID", "tgps-journal"
            ),
        }

    def _request_once(
        self, url: str, params: Dict[str, Any], access_token: str
    ) -> requests.Response:
        headers = self._build_headers(access_token)
        try:
            return self.session.get(
                url, params=params, headers=headers, timeout=self.timeout
            )
        except requests.exceptions.ReadTimeout as e:
            raise RuntimeError(
                f"Read timeout from {url} (timeout={self.timeout}s, params={params})"
            ) from e
        except requests.RequestException as e:
            raise RuntimeError(f"HTTP request error to {url}: {e}") from e

    def get(self, url: str, params: Dict[str, Any]) -> Any:
        token = self.auth.get_access_token()
        resp = self._request_once(url, params, token)

        if getattr(resp, "status_code", None) == 401:
            self.auth.force_refresh()
            token = self.auth.get_access_token()
            resp = self._request_once(url, params, token)

        status = getattr(resp, "status_code", None)
        if status is None or not (200 <= status < 300):
            text = getattr(resp, "text", "")
            raise RuntimeError(f"HTTP {status} from {url} — {text[:400]}")

        try:
            return resp.json()
        except Exception:
            text = getattr(resp, "text", "")
            raise RuntimeError(f"Non-JSON response from {url}: {status} {text[:400]}")


# ---------------------------------------------------------------------------
# DuckDB schema/table ensure
# ---------------------------------------------------------------------------


def _table_exists(conn: duckdb.DuckDBPyConnection, schema: str, name: str) -> bool:
    q = """
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = ? AND table_name = ?
    LIMIT 1
    """
    return conn.execute(q, [schema, name]).fetchone() is not None


def _table_columns(
    conn: duckdb.DuckDBPyConnection, schema: str, name: str
) -> List[str]:
    q = """
    SELECT column_name
    FROM information_schema.columns
    WHERE table_schema = ? AND table_name = ?
    ORDER BY ordinal_position
    """
    rows = conn.execute(q, [schema, name]).fetchall()
    return [r[0] for r in rows]


def _ensure_schema_tables(conn: duckdb.DuckDBPyConnection, debug: bool = False) -> None:
    conn.execute("CREATE SCHEMA IF NOT EXISTS journal;")

    # Create both sequence names (some DBs reference unqualified; others qualified)
    for seq_sql in [
        "CREATE SEQUENCE IF NOT EXISTS journal_run_id_seq;",
        "CREATE SEQUENCE IF NOT EXISTS journal.journal_run_id_seq;",
    ]:
        try:
            conn.execute(seq_sql)
        except Exception as e:
            _dbg(debug, f"[ENSURE] sequence create skipped: {e}")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS journal.transactions_raw (
          account_hash VARCHAR NOT NULL,
          fetched_at   TIMESTAMP NOT NULL DEFAULT now(),
          from_iso     VARCHAR NOT NULL,
          to_iso       VARCHAR NOT NULL,
          payload      JSON NOT NULL
        );
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS journal.transaction_items (
          account_hash    VARCHAR NOT NULL,
          activity_id     BIGINT  NOT NULL,
          leg_index       INTEGER NOT NULL,
          symbol          VARCHAR,
          asset_type      VARCHAR,
          position_effect VARCHAR,
          price           DOUBLE,
          amount          DOUBLE,
          fee_type        VARCHAR,
          put_call        VARCHAR,
          strike          DOUBLE,
          expiry          DATE,
          extras          JSON
        );
        """
    )

    # IMPORTANT: full run_log schema (matches your existing DB + other exporters)
    # NOTE: IF NOT EXISTS won't alter an existing table; it only ensures fresh DBs match.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS journal.run_log (
          run_id                BIGINT PRIMARY KEY DEFAULT(nextval('journal_run_id_seq')),
          run_started_at        TIMESTAMP NOT NULL,
          run_ended_at          TIMESTAMP NOT NULL,
          from_date             DATE NOT NULL,
          to_date               DATE NOT NULL,
          row_trades            BIGINT NOT NULL DEFAULT 0,
          row_transactions      BIGINT NOT NULL DEFAULT 0,
          row_transaction_items BIGINT NOT NULL DEFAULT 0,
          row_open_orders       BIGINT NOT NULL DEFAULT 0,
          notes                 VARCHAR
        );
        """
    )

    # Unique indexes (may fail if legacy data already contains duplicates)
    try:
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS ux_transactions_raw_window
              ON journal.transactions_raw(account_hash, from_iso, to_iso);
            """
        )
    except Exception as e:
        _dbg(
            debug,
            f"[WARN] could not create ux_transactions_raw_window (existing dupes?): {e}",
        )

    try:
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS ux_transaction_items_key
              ON journal.transaction_items(account_hash, activity_id, leg_index);
            """
        )
    except Exception as e:
        _dbg(
            debug,
            f"[WARN] could not create ux_transaction_items_key (existing dupes?): {e}",
        )


# ---------------------------------------------------------------------------
# Raw persistence (source of truth)
# ---------------------------------------------------------------------------


def _write_raw_file(
    kind: str, account_hash: str, f_iso: str, t_iso: str, payload: Any
) -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    part = pd.Timestamp.utcnow().strftime("%Y-%m-%d")
    folder = RAW_DIR / part / kind
    folder.mkdir(parents=True, exist_ok=True)
    fn = folder / f"{account_hash}__{f_iso[:10]}__{t_iso[:10]}.json"
    fn.write_text(json.dumps(payload, ensure_ascii=False, indent=2))


def write_transactions_raw_window(
    conn: duckdb.DuckDBPyConnection,
    account_hash: str,
    f_iso: str,
    t_iso: str,
    tx_payload: Any,
    debug: bool = False,
) -> None:
    """
    Writes ONE row per (account_hash, from_iso, to_iso) window snapshot.

    Prefers INSERT OR REPLACE (requires a UNIQUE index/constraint on the key).
    Falls back to DELETE+INSERT if OR REPLACE can't match a key.
    """
    if not _table_exists(conn, "journal", "transactions_raw"):
        _write_raw_file("transactions", account_hash, f_iso, t_iso, tx_payload)
        return

    payload_json = json.dumps(tx_payload, ensure_ascii=False)

    _dbg(
        debug,
        "[DEBUG] raw upsert: transactions_raw by (account_hash, from_iso, to_iso)",
    )

    # Best path: OR REPLACE (uses your unique index ux_transactions_raw_window)
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO journal.transactions_raw
              (account_hash, fetched_at, from_iso, to_iso, payload)
            VALUES (?, now(), ?, ?, CAST(? AS JSON))
            """,
            [account_hash, f_iso, t_iso, payload_json],
        )
        return
    except Exception as e:
        # If OR REPLACE can't find a unique/PK to target, fallback to delete+insert.
        if debug:
            print(
                f"[WARN] transactions_raw OR REPLACE failed, fallback to DELETE+INSERT: {e}",
                flush=True,
            )

    conn.execute(
        """
        DELETE FROM journal.transactions_raw
        WHERE account_hash = ? AND from_iso = ? AND to_iso = ?
        """,
        [account_hash, f_iso, t_iso],
    )
    conn.execute(
        """
        INSERT INTO journal.transactions_raw
          (account_hash, fetched_at, from_iso, to_iso, payload)
        VALUES (?, now(), ?, ?, CAST(? AS JSON))
        """,
        [account_hash, f_iso, t_iso, payload_json],
    )


# ---------------------------------------------------------------------------
# Account discovery + fetchers
# ---------------------------------------------------------------------------


def resolve_account_hashes(http: SchwabHttp) -> List[Dict[str, str]]:
    data = http.get(ACCOUNT_NUMBERS_URL, params={})
    if not isinstance(data, list):
        raise RuntimeError("accounts/accountNumbers did not return a list.")
    out: List[Dict[str, str]] = []
    for row in data:
        acct = str(row.get("accountNumber", "")).strip()
        hv = str(row.get("hashValue", "")).strip()
        if acct and hv:
            out.append({"accountNumber": acct, "hashValue": hv})
    if not out:
        raise RuntimeError("No accounts returned (check auth/entitlements).")
    return out


def fetch_transactions_for_account(
    http: SchwabHttp,
    hash_value: str,
    start_iso: str,
    end_iso: str,
    types: Optional[str] = None,
) -> List[Dict[str, Any]]:
    params: Dict[str, Any] = {"startDate": start_iso, "endDate": end_iso}
    if types:
        params["types"] = types
    data = http.get(TRANSACTIONS_URL_FMT.format(hash=hash_value), params=params)
    if not isinstance(data, list):
        raise RuntimeError("transactions endpoint did not return list.")
    return data


# ---------------------------------------------------------------------------
# Normalizer
# ---------------------------------------------------------------------------


def transactions_to_frames(
    account_hash: str, txns: List[Dict[str, Any]]
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    IMPORTANT: de-dupe Schwab tx list by activityId (Schwab can repeat it).
    """
    tx_rows: List[Dict[str, Any]] = []
    it_rows: List[Dict[str, Any]] = []

    seen_activity_ids: set[int] = set()

    for t in txns or []:
        aid = t.get("activityId")
        if aid is None:
            continue
        if aid in seen_activity_ids:
            continue
        seen_activity_ids.add(aid)

        tx_rows.append(
            {
                "account_hash": account_hash,
                "activity_id": aid,
                "time": _safe_datetime(t.get("time")),
                "type": t.get("type"),
                "status": t.get("status"),
                "sub_account": t.get("subAccount"),
                "trade_date": _safe_date_ymd(t.get("tradeDate")),
                "settlement_date": _safe_date_ymd(t.get("settlementDate")),
                "order_id": t.get("orderId"),
                "net_amount": t.get("netAmount"),
                "description": t.get("description"),
                "extras": t,
            }
        )

        items = (t.get("transferItems") or []) + (t.get("tradeFees") or [])
        for leg_index, i in enumerate(items, start=1):
            it_rows.append(
                {
                    "account_hash": account_hash,
                    "activity_id": aid,
                    "leg_index": leg_index,
                    "symbol": i.get("symbol"),
                    "asset_type": i.get("assetType"),
                    "position_effect": i.get("positionEffect"),
                    "price": i.get("price"),
                    "amount": i.get("amount"),
                    "fee_type": i.get("feeType"),
                    "put_call": i.get("putCall"),
                    "strike": i.get("strikePrice"),
                    "expiry": _safe_date_ymd(i.get("expirationDate")),
                    "extras": i,
                }
            )

    tx_df = pd.DataFrame(
        tx_rows,
        columns=[
            "account_hash",
            "activity_id",
            "time",
            "type",
            "status",
            "sub_account",
            "trade_date",
            "settlement_date",
            "order_id",
            "net_amount",
            "description",
            "extras",
        ],
    )

    it_df = pd.DataFrame(
        it_rows,
        columns=[
            "account_hash",
            "activity_id",
            "leg_index",
            "symbol",
            "asset_type",
            "position_effect",
            "price",
            "amount",
            "fee_type",
            "put_call",
            "strike",
            "expiry",
            "extras",
        ],
    )

    return tx_df, it_df


# ---------------------------------------------------------------------------
# run_log sequence guard
# ---------------------------------------------------------------------------


def _ensure_runlog_sequence_ok(
    conn: duckdb.DuckDBPyConnection, debug: bool = False
) -> None:
    if not _table_exists(conn, "journal", "run_log"):
        return
    cols = _table_columns(conn, "journal", "run_log")
    if "run_id" not in cols:
        return

    try:
        next_id = int(
            conn.execute(
                "SELECT COALESCE(MAX(run_id),0)+1 FROM journal.run_log;"
            ).fetchone()[0]
        )
    except Exception as e:
        _dbg(debug, f"[WARN] cannot compute next run_id: {e}")
        return

    for seq in [
        "journal_run_id_seq",
        "main.journal_run_id_seq",
        "journal.journal_run_id_seq",
    ]:
        try:
            conn.execute(f"ALTER SEQUENCE {seq} RESTART WITH {next_id};")
            _dbg(debug, f"[ENSURE] sequence exists: {seq}")
        except Exception as e:
            _dbg(debug, f"[DEBUG] sequence bump skipped for {seq}: {e}")


def write_run_log_outside_txn(
    db_path: str,
    started_at: pd.Timestamp,
    ended_at: pd.Timestamp,
    from_date: str,
    to_date: str,
    row_transactions: int,
    row_items: int,
    notes: str,
    debug: bool = False,
    row_trades: int = 0,
    row_open_orders: int = 0,
) -> None:
    """
    Best-effort run_log write using a separate connection (autocommit).
    Schema-aware: works whether run_log has trx-only columns or the full set
    (row_trades, row_open_orders, etc.). Avoids sequences entirely by using MAX+1.
    """
    conn2 = None
    try:
        conn2 = duckdb.connect(db_path)
        conn2.execute("CREATE SCHEMA IF NOT EXISTS journal;")

        # If run_log doesn't exist at all, create a "full" version that can serve both exporters.
        conn2.execute(
            """
            CREATE TABLE IF NOT EXISTS journal.run_log (
              run_id                BIGINT PRIMARY KEY,
              run_started_at        TIMESTAMP NOT NULL,
              run_ended_at          TIMESTAMP NOT NULL,
              from_date             DATE NOT NULL,
              to_date               DATE NOT NULL,
              row_trades            BIGINT NOT NULL DEFAULT 0,
              row_transactions      BIGINT NOT NULL,
              row_transaction_items BIGINT NOT NULL,
              row_open_orders       BIGINT NOT NULL DEFAULT 0,
              notes                 VARCHAR
            );
            """
        )

        # Discover actual columns (because IF NOT EXISTS won't change an existing table)
        cols = [
            r[0]
            for r in conn2.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema='journal' AND table_name='run_log'
                ORDER BY ordinal_position
                """
            ).fetchall()
        ]
        colset = set(cols)

        # Build an INSERT that matches the existing schema
        insert_cols = ["run_id"]
        select_exprs = ["COALESCE(MAX(run_id), 0) + 1"]
        params = []

        def add(col: str, expr: str, param=None):
            insert_cols.append(col)
            select_exprs.append(expr)
            if param is not None:
                params.append(param)

        if "run_started_at" in colset:
            add("run_started_at", "?", started_at)
        if "run_ended_at" in colset:
            add("run_ended_at", "?", ended_at)
        if "from_date" in colset:
            add("from_date", "?", from_date)
        if "to_date" in colset:
            add("to_date", "?", to_date)

        # Full-schema fields (your current table has these)
        if "row_trades" in colset:
            add("row_trades", "?", int(row_trades))
        if "row_transactions" in colset:
            add("row_transactions", "?", int(row_transactions))
        if "row_transaction_items" in colset:
            add("row_transaction_items", "?", int(row_items))
        if "row_open_orders" in colset:
            add("row_open_orders", "?", int(row_open_orders))

        if "notes" in colset:
            add("notes", "?", notes)

        sql = f"""
        INSERT INTO journal.run_log ({", ".join(insert_cols)})
        SELECT {", ".join(select_exprs)}
        FROM journal.run_log
        """

        conn2.execute(sql, params)

    except Exception as e:
        if debug:
            print(f"[WARN] run_log insert skipped (non-fatal): {e}", flush=True)
    finally:
        try:
            if conn2 is not None:
                conn2.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------
def run_export(db_path: str, date_from: str, date_to: str, debug: bool = False) -> None:
    f_iso = to_utc_day_start(date_from)
    t_iso = to_utc_day_end(date_to)

    _dbg(debug, f"[DEBUG] Window UTC: {f_iso} → {t_iso}")

    conn = duckdb.connect(db_path)
    try:
        _ensure_schema_tables(conn, debug=debug)
        conn.execute("SET schema 'journal';")

        # Optional: warn loudly if the unique index is missing (debug only)
        if debug:
            try:
                has_idx = int(
                    conn.execute(
                        """
                        SELECT COUNT(*)::INT
                        FROM duckdb_indexes()
                        WHERE schema_name='journal'
                          AND table_name='transaction_items'
                          AND index_name='ux_transaction_items_key'
                          AND is_unique
                        """
                    ).fetchone()[0]
                )
                if has_idx == 0:
                    _dbg(
                        debug,
                        "[WARN] ux_transaction_items_key (UNIQUE) is missing. "
                        "Reruns may accumulate duplicates if writes change away from OR REPLACE.",
                    )
            except Exception as e:
                _dbg(debug, f"[DEBUG] index-exists check skipped: {e}")

        store = TokenStore()
        auth = AuthClient(store)
        http = SchwabHttp(session=requests.Session(), auth=auth)

        accounts = resolve_account_hashes(http)
        _dbg(debug, f"[DEBUG] accounts: {len(accounts)}")

        started_at = pd.Timestamp.utcnow()
        total_tx = 0
        total_items = 0

        conn.execute("BEGIN TRANSACTION;")

        for acct in accounts:
            hv = acct["hashValue"]
            _dbg(debug, f"[DEBUG] account hv: {hv}")

            txns = fetch_transactions_for_account(http, hv, f_iso, t_iso, types=None)
            tx_df, it_df = transactions_to_frames(hv, txns)

            _dbg(debug, f"[DEBUG] tx={len(tx_df)} items={len(it_df)}")

            # 1) Raw snapshot (ONE row per window)
            write_transactions_raw_window(conn, hv, f_iso, t_iso, txns, debug=debug)

            # Normalize extras to JSON strings for DuckDB JSON columns
            if not tx_df.empty:
                tx_df = tx_df.copy()
                tx_df["extras"] = tx_df["extras"].apply(
                    lambda v: (
                        json.dumps(v, ensure_ascii=False)
                        if v is not None and not isinstance(v, str)
                        else v
                    )
                )
            if not it_df.empty:
                it_df = it_df.copy()
                it_df["extras"] = it_df["extras"].apply(
                    lambda v: (
                        json.dumps(v, ensure_ascii=False)
                        if v is not None and not isinstance(v, str)
                        else v
                    )
                )

            # ---- LOCKED #1: authoritative activity ids from tx_df (drives cleanup) ----
            aids_df = pd.DataFrame(columns=["account_hash", "activity_id"])
            if not tx_df.empty:
                tx_df = tx_df.copy()
                tx_df["activity_id"] = pd.to_numeric(
                    tx_df["activity_id"], errors="coerce"
                )
                tx_df = tx_df.dropna(subset=["account_hash", "activity_id"])
                if not tx_df.empty:
                    tx_df["activity_id"] = tx_df["activity_id"].astype("int64")
                    aids_df = tx_df[["account_hash", "activity_id"]].drop_duplicates()

            # ---- LOCKED #2: normalize + dedupe legs by table key BEFORE writing ----
            keys_df = pd.DataFrame(columns=["account_hash", "activity_id", "leg_index"])
            if not it_df.empty:
                it_df = it_df.copy()

                it_df["activity_id"] = pd.to_numeric(
                    it_df["activity_id"], errors="coerce"
                )
                it_df["leg_index"] = pd.to_numeric(it_df["leg_index"], errors="coerce")
                it_df = it_df.dropna(
                    subset=["account_hash", "activity_id", "leg_index"]
                )

                if not it_df.empty:
                    it_df["activity_id"] = it_df["activity_id"].astype("int64")
                    it_df["leg_index"] = it_df["leg_index"].astype("int32")

                    if debug:
                        dup_before = int(
                            it_df.duplicated(
                                subset=["account_hash", "activity_id", "leg_index"]
                            ).sum()
                        )
                        _dbg(
                            debug,
                            f"[DEBUG] it_df dup keys before drop_duplicates: {dup_before}",
                        )

                    it_df = it_df.drop_duplicates(
                        subset=["account_hash", "activity_id", "leg_index"],
                        keep="first",
                    )

                    if debug:
                        dup_after = int(
                            it_df.duplicated(
                                subset=["account_hash", "activity_id", "leg_index"]
                            ).sum()
                        )
                        _dbg(
                            debug,
                            f"[DEBUG] it_df dup keys after drop_duplicates: {dup_after}",
                        )

                    keys_df = it_df[
                        ["account_hash", "activity_id", "leg_index"]
                    ].drop_duplicates()

                    # ---- LOCKED #3: UPSERT legs (reliable reruns) ----
                    rows = []
                    for r in it_df.itertuples(index=False):
                        extras = r.extras
                        if isinstance(extras, float) and pd.isna(extras):
                            extras = None
                        rows.append(
                            (
                                r.account_hash,
                                int(r.activity_id),
                                int(r.leg_index),
                                r.symbol,
                                r.asset_type,
                                r.position_effect,
                                r.price,
                                r.amount,
                                r.fee_type,
                                r.put_call,
                                r.strike,
                                r.expiry,
                                extras,
                            )
                        )

                    if rows:
                        conn.executemany(
                            """
                            INSERT OR REPLACE INTO journal.transaction_items (
                              account_hash,
                              activity_id,
                              leg_index,
                              symbol,
                              asset_type,
                              position_effect,
                              price,
                              amount,
                              fee_type,
                              put_call,
                              strike,
                              expiry,
                              extras
                            )
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CAST(? AS JSON))
                            """,
                            rows,
                        )

            # ---- Cleanup stale/orphan legs AFTER upsert ----
            # For Schwab activity_ids returned in this window (aids_df), delete any legs not in keys_df.
            if not aids_df.empty:
                conn.register("df_aids", aids_df)

                if not keys_df.empty:
                    conn.register("df_keys", keys_df)
                    conn.execute(
                        """
                        DELETE FROM journal.transaction_items t
                        WHERE EXISTS (
                          SELECT 1
                          FROM df_aids a
                          WHERE a.account_hash = t.account_hash
                            AND a.activity_id  = t.activity_id
                        )
                        AND NOT EXISTS (
                          SELECT 1
                          FROM df_keys k
                          WHERE k.account_hash = t.account_hash
                            AND k.activity_id  = t.activity_id
                            AND k.leg_index    = t.leg_index
                        )
                        """
                    )
                    conn.unregister("df_keys")
                else:
                    # No keys at all => delete all legs for these activities (handles 0-item activities)
                    conn.execute(
                        """
                        DELETE FROM journal.transaction_items t
                        WHERE EXISTS (
                          SELECT 1
                          FROM df_aids a
                          WHERE a.account_hash = t.account_hash
                            AND a.activity_id  = t.activity_id
                        )
                        """
                    )

                conn.unregister("df_aids")

                if debug:
                    _dbg(
                        debug,
                        f"[DEBUG] cleanup complete for activity_ids: {len(aids_df)}",
                    )

            total_tx += int(len(tx_df)) if tx_df is not None else 0
            total_items += int(len(it_df)) if it_df is not None else 0

        ended_at = pd.Timestamp.utcnow()

        conn.execute("COMMIT;")

        write_run_log_outside_txn(
            db_path=db_path,
            started_at=started_at,
            ended_at=ended_at,
            from_date=date_from,
            to_date=date_to,
            row_transactions=total_tx,
            row_items=total_items,
            notes="export_trx",
            debug=debug,
        )

        if debug:
            _dbg(debug, f"[OK] committed: tx={total_tx} items={total_items}")

    except Exception:
        try:
            conn.execute("ROLLBACK;")
        except Exception:
            pass
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: List[str]):
    import argparse

    p = argparse.ArgumentParser(
        description="Export Schwab transactions into DuckDB (raw + items, idempotent)."
    )
    p.add_argument("--from", dest="from_date", required=True, help="YYYY-MM-DD")
    p.add_argument("--to", dest="to_date", required=True, help="YYYY-MM-DD")
    p.add_argument(
        "--db", default=DEFAULT_DB, help=f"Path to DuckDB (default: {DEFAULT_DB})"
    )
    p.add_argument("--debug", action="store_true")
    return p.parse_args(argv)


def main():
    args = parse_args(sys.argv[1:])
    run_export(
        db_path=args.db,
        date_from=args.from_date,
        date_to=args.to_date,
        debug=args.debug,
    )


if __name__ == "__main__":
    main()
