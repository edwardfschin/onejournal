#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/tgps_user/fills_normalize.py
Version: 0.1.3 (2026-01-15, SGT)

Changes in 0.1.3
----------------
• Make fills_deleted count accurate in logs (DuckDB rowcount may return -1).

Purpose
-------
Step 7: Normalize Schwab TRADE transactions (from fills_mgt cache tables) into an OMS fills table,
then optionally update local order_submissions statuses to PARTIAL / FILLED.

Reads (produced by fills_mgt.py)
--------------------------------
- ledger.lcl.broker_transactions_latest   (preferred)
- ledger.lcl.broker_transactions_raw      (fallback; latest snapshot per txn_id)

Writes
------
- ledger.lcl.oms_fills
  One row per *security* transferItem in a Schwab TRADE transaction.

Fees / net amounts (important)
------------------------------
Schwab fees_total and net_amount are transaction-level values.
To prevent overcounting when aggregating by summing legs:
- fees_total_txn, net_amount_txn store the txn-level totals (do NOT sum across legs)
- fees_total, net_amount store *per-leg allocated* values (safe to sum across legs)
  Allocation method: equal split across security legs in the transaction.

Optionally updates
------------------
- ledger.lcl.order_submissions
  Adds (if missing): filled_qty, avg_fill_price, filled_at
  Updates status to PARTIAL/FILLED based on fills matched by (broker_order_id, option_symbol).

Reliability (lock)
------------------
- All ledger writes are protected by a single-writer file lock:
    tgps-user/ledger/tgps_ledger_write.lock
- This command is DB-heavy (no network calls), so we hold the lock for the duration
  of normalize + optional update-orders to prevent concurrent writers from corrupting state.

Notes
-----
- This script assumes fills_mgt sync has already populated broker_transactions_* tables.
- Matching logic for updating order_submissions is conservative:
    match order_submissions.broker_order_id == oms_fills.order_id
    AND order_submissions.option_symbol == oms_fills.leg_symbol
    AND oms_fills.position_effect == 'OPENING'
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import duckdb
import yaml

# ---- Repo root bootstrap ----
CODE_DIR = Path(__file__).resolve().parents[2]
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from client.schwab_admin import AuthClient, TokenStore  # noqa: E402

# ---- Single-writer lock helper ----
try:
    from ._lock import LockHeldError, ledger_write_lock  # type: ignore
except Exception:
    from scripts.tgps_user._lock import LockHeldError, ledger_write_lock  # type: ignore


# ----------------------------
# Paths / config
# ----------------------------
def _repo_root() -> Path:
    here = Path.cwd().resolve()
    if (here / "tgps-user").exists():
        return here
    for p in [here] + list(here.parents):
        if (p / "tgps-user").exists():
            return p
    raise SystemExit("❌ Could not find repo root (expected 'tgps-user' folder). Run from TradersGPS repo.")


def _user_root(repo: Path) -> Path:
    return repo / "tgps-user"


def _cfg_path(user_root: Path) -> Path:
    return user_root / "config" / "lcl.user.yml"


def _ledger_path(user_root: Path) -> Path:
    return user_root / "ledger" / "lcl.ledger.duckdb"


def _load_user_yml(p: Path) -> dict:
    if not p.exists():
        return {}
    return yaml.safe_load(p.read_text()) or {}


def _journal_db_default() -> str:
    return os.environ.get(
        "TGPS_JOURNAL_DB",
        os.path.expanduser("~/tgps-project/data/journal/tgps_trades.duckdb"),
    )


# ----------------------------
# Account resolution (same behavior as fills_mgt / order_mgt)
# ----------------------------
def _is_probably_hash(s: str) -> bool:
    s = (s or "").strip()
    return len(s) == 64 and all(c in "0123456789abcdefABCDEF" for c in s)


def _pick_account_from_journal(db_path: str) -> Optional[Tuple[str, str]]:
    p = os.path.expanduser(db_path)
    if not Path(p).exists():
        return None
    try:
        con = duckdb.connect(p, read_only=True)
        r = con.execute(
            """
            select account_hash, account_number
            from journal.accounts
            where account_hash is not null
            order by account_number
            """
        ).fetchall()
        con.close()
    except Exception:
        return None
    if len(r) == 1:
        return str(r[0][0]), str(r[0][1])
    return None


def _resolve_account_hash(account: Optional[str], cfg_account: Optional[str], journal_db: str) -> Tuple[str, str]:
    """
    Returns (account_hash, account_number_or_empty)
    """
    if account:
        a = str(account).strip()
        if _is_probably_hash(a):
            return a, ""
        from client.schwab_admin import AdminClient  # lazy import

        store = TokenStore()
        auth = AuthClient(store)
        admin = AdminClient(auth)
        data = admin.account_numbers() or []
        for row in data:
            if str(row.get("accountNumber")) == a:
                return str(row.get("hashValue")), a
        raise SystemExit(f"Account number not found at Schwab: {a}")

    if cfg_account and str(cfg_account).strip():
        return _resolve_account_hash(str(cfg_account).strip(), None, journal_db)

    picked = _pick_account_from_journal(journal_db)
    if picked:
        return picked[0], picked[1]

    raise SystemExit(
        "No account specified and unable to auto-pick.\n"
        "Use --account <accountNumber> (e.g. 41472449) or fill broker.account in tgps-user/config/lcl.user.yml."
    )


# ----------------------------
# DuckDB helpers
# ----------------------------
def _connect_attached(ledger: Path) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(":memory:")
    con.execute(f"ATTACH '{ledger.as_posix()}' AS ledger;")
    con.execute("CREATE SCHEMA IF NOT EXISTS ledger.lcl;")
    return con


def _colset(con: duckdb.DuckDBPyConnection, table_name: str) -> set[str]:
    rows = con.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_catalog='ledger' AND table_schema='lcl' AND table_name=?
        """,
        [table_name],
    ).fetchall()
    return {r[0] for r in rows}


def _table_exists(con: duckdb.DuckDBPyConnection, qualified: str) -> bool:
    try:
        con.execute(f"SELECT 1 FROM {qualified} LIMIT 1;")
        return True
    except Exception:
        return False


# ----------------------------
# Parsing helpers (Schwab timestamps / fields)
# ----------------------------
def _as_float(x: Any) -> Optional[float]:
    if x is None:
        return None
    try:
        return float(x)
    except Exception:
        return None


def _parse_dt_any(s: Any) -> Optional[datetime]:
    """
    Schwab examples:
      2025-07-17T13:41:10+0000
      2025-07-17T13:41:10+00:00
      2025-07-17T13:41:10Z
      2025-07-17
    Returns: UTC naive datetime (for DuckDB TIMESTAMP).
    """
    if s is None:
        return None
    txt = str(s).strip()
    if not txt:
        return None

    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"

    fmts = [
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%d",
    ]

    try:
        dt = datetime.fromisoformat(txt)
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    except Exception:
        pass

    for f in fmts:
        try:
            dt = datetime.strptime(txt, f)
            if dt.tzinfo is not None:
                dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
            return dt
        except Exception:
            continue

    try:
        if len(txt) >= 5 and (txt[-5] in ("+", "-")) and txt[-2:].isdigit() and txt[-4:-2].isdigit():
            txt2 = txt[:-2] + ":" + txt[-2:]
            dt = datetime.fromisoformat(txt2)
            if dt.tzinfo is not None:
                dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
            return dt
    except Exception:
        pass

    return None


def _pick_trade_ts(o: Dict[str, Any]) -> Optional[datetime]:
    for k in ("tradeDate", "time", "transactionDate", "postedDate", "activityDate", "date"):
        if k in o:
            dt = _parse_dt_any(o.get(k))
            if dt is not None:
                return dt
    return None


def _pick_order_id(o: Dict[str, Any]) -> str:
    for k in ("orderId", "orderID", "order_id"):
        v = o.get(k)
        if v is not None and str(v).strip():
            return str(v).strip()
    return ""


def _pick_txn_type(o: Dict[str, Any]) -> str:
    v = o.get("type") or o.get("transactionType") or o.get("activityType") or ""
    return str(v).strip().upper()


def _pick_txn_id(o: Dict[str, Any]) -> str:
    for k in ("transactionId", "txnId", "id", "activityId", "tradeId"):
        v = o.get(k)
        if v is not None and str(v).strip():
            return str(v).strip()
    return ""


def _fee_total(o: Dict[str, Any]) -> float:
    items = o.get("transferItems")
    if not isinstance(items, list):
        return 0.0
    total = 0.0
    for it in items:
        if not isinstance(it, dict):
            continue
        if it.get("feeType"):
            c = _as_float(it.get("cost"))
            if c is None:
                continue
            total += (-c) if c < 0 else c
    return float(total)


def _security_items(o: Dict[str, Any]) -> List[Dict[str, Any]]:
    items = o.get("transferItems")
    if not isinstance(items, list):
        return []
    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        inst = it.get("instrument")
        if not isinstance(inst, dict):
            continue
        at = str(inst.get("assetType") or "").strip().upper()
        if at and at != "CURRENCY":
            out.append(it)
    return out


def _infer_instruction(asset_type: str, signed_qty: float, position_effect: str) -> str:
    pe = (position_effect or "").strip().upper()
    at = (asset_type or "").strip().upper()

    side = "BUY" if signed_qty > 0 else "SELL"
    if at == "OPTION":
        if pe == "OPENING":
            return "BUY_TO_OPEN" if side == "BUY" else "SELL_TO_OPEN"
        if pe == "CLOSING":
            return "BUY_TO_CLOSE" if side == "BUY" else "SELL_TO_CLOSE"
    return side


def _instrument_symbol(it: Dict[str, Any]) -> str:
    inst = it.get("instrument")
    if isinstance(inst, dict):
        sym = inst.get("symbol") or ""
        return str(sym).strip().upper()
    return ""


def _instrument_asset_type(it: Dict[str, Any]) -> str:
    inst = it.get("instrument")
    if isinstance(inst, dict):
        at = inst.get("assetType") or inst.get("type") or ""
        return str(at).strip().upper()
    return ""


def _option_fields(it: Dict[str, Any]) -> Dict[str, Any]:
    inst = it.get("instrument")
    if not isinstance(inst, dict):
        return {}
    if str(inst.get("assetType") or "").strip().upper() != "OPTION":
        return {}
    exp = _parse_dt_any(inst.get("expirationDate"))
    return {
        "underlying": (str(inst.get("underlyingSymbol") or "").strip().upper() or None),
        "expiry": (exp.date() if exp else None),
        "strike": _as_float(inst.get("strikePrice")),
        "put_call": (str(inst.get("putCall") or "").strip().upper() or None),
        "multiplier": _as_float(inst.get("optionPremiumMultiplier")) or 100.0,
    }


def _infer_price(it: Dict[str, Any], multiplier: float) -> Optional[float]:
    px = _as_float(it.get("price"))
    if px is not None:
        return px
    amt = _as_float(it.get("amount"))
    cst = _as_float(it.get("cost"))
    if amt is None or cst is None or amt == 0:
        return None
    return abs(float(cst)) / (abs(float(amt)) * float(multiplier or 1.0))


# ----------------------------
# Schema
# ----------------------------
def _ensure_oms_fills(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS ledger.lcl.oms_fills (
          account_hash      VARCHAR,
          txn_id            VARCHAR,
          leg_no            INTEGER,

          trade_ts          TIMESTAMP,
          trade_date        DATE,
          fetched_at        TIMESTAMP,

          order_id          VARCHAR,
          position_id       VARCHAR,
          txn_type          VARCHAR,

          leg_symbol        VARCHAR,
          asset_type        VARCHAR,
          instruction       VARCHAR,
          position_effect   VARCHAR,

          underlying        VARCHAR,
          expiry            DATE,
          strike            DOUBLE,
          put_call          VARCHAR,
          multiplier        DOUBLE,

          signed_qty        DOUBLE,
          abs_qty           DOUBLE,
          price             DOUBLE,

          gross             DOUBLE,

          fees_total        DOUBLE,   -- per-leg allocated (safe to sum)
          net_amount        DOUBLE,   -- per-leg allocated (safe to sum)

          fees_total_txn    DOUBLE,   -- txn-level total (do NOT sum across legs)
          net_amount_txn    DOUBLE,   -- txn-level total (do NOT sum across legs)

          leg_json          VARCHAR,
          txn_json          VARCHAR
        );
        """
    )
    try:
        con.execute("CREATE INDEX IF NOT EXISTS ix_oms_fills_order ON ledger.lcl.oms_fills(account_hash, order_id);")
    except Exception:
        pass
    try:
        con.execute("CREATE INDEX IF NOT EXISTS ix_oms_fills_txn ON ledger.lcl.oms_fills(account_hash, txn_id);")
    except Exception:
        pass

    cols = _colset(con, "oms_fills")
    if "fees_total_txn" not in cols:
        con.execute("ALTER TABLE ledger.lcl.oms_fills ADD COLUMN fees_total_txn DOUBLE;")
    if "net_amount_txn" not in cols:
        con.execute("ALTER TABLE ledger.lcl.oms_fills ADD COLUMN net_amount_txn DOUBLE;")


def _ensure_order_submission_fill_cols(con: duckdb.DuckDBPyConnection) -> None:
    if not _table_exists(con, "ledger.lcl.order_submissions"):
        return

    cols = _colset(con, "order_submissions")
    wanted: Dict[str, str] = {
        "filled_qty": "DOUBLE",
        "avg_fill_price": "DOUBLE",
        "filled_at": "TIMESTAMP",
    }
    for c, typ in wanted.items():
        if c not in cols:
            con.execute(f"ALTER TABLE ledger.lcl.order_submissions ADD COLUMN {c} {typ};")


# ----------------------------
# Read source txns from cache
# ----------------------------
def _choose_source(con: duckdb.DuckDBPyConnection, source: str) -> str:
    s = (source or "auto").strip().lower()
    if s in ("latest", "raw"):
        return s
    have_latest = _table_exists(con, "ledger.lcl.broker_transactions_latest")
    if have_latest:
        return "latest"
    return "raw"


def _fetch_trade_txns(
    con: duckdb.DuckDBPyConnection,
    *,
    account_hash: str,
    source: str,
    d0: date,
    d1: date,
    limit: int = 0,
) -> List[Dict[str, Any]]:
    lim = int(limit or 0)
    lim_sql = f"LIMIT {lim}" if lim > 0 else ""

    if source == "latest":
        if not _table_exists(con, "ledger.lcl.broker_transactions_latest"):
            raise SystemExit("Missing ledger.lcl.broker_transactions_latest. Run fills_mgt sync with --write-mode upsert first.")
        rows = con.execute(
            f"""
            SELECT txn_id, txn_type, coalesce(txn_date, cast(last_fetched_at as date)) as txn_date,
                   last_fetched_at, txn_json
            FROM ledger.lcl.broker_transactions_latest
            WHERE account_hash = ?
              AND upper(txn_type) = 'TRADE'
              AND coalesce(txn_date, cast(last_fetched_at as date)) BETWEEN ? AND ?
            ORDER BY last_fetched_at DESC
            {lim_sql}
            """,
            [account_hash, d0, d1],
        ).fetchall()
        out = []
        for txn_id, txn_type, txn_date, last_fetched_at, txn_json in rows:
            out.append(
                {
                    "txn_id": str(txn_id),
                    "txn_type": str(txn_type),
                    "txn_date": txn_date,
                    "fetched_at": last_fetched_at,
                    "txn_json": txn_json,
                }
            )
        return out

    if not _table_exists(con, "ledger.lcl.broker_transactions_raw"):
        raise SystemExit("Missing ledger.lcl.broker_transactions_raw. Run fills_mgt sync first.")
    rows = con.execute(
        f"""
        SELECT txn_id, txn_type, coalesce(txn_date, cast(fetched_at as date)) as txn_date,
               fetched_at, txn_json
        FROM ledger.lcl.broker_transactions_raw
        WHERE account_hash = ?
          AND upper(txn_type) = 'TRADE'
          AND coalesce(txn_date, cast(fetched_at as date)) BETWEEN ? AND ?
        QUALIFY row_number() OVER (PARTITION BY txn_id ORDER BY fetched_at DESC) = 1
        ORDER BY fetched_at DESC
        {lim_sql}
        """,
        [account_hash, d0, d1],
    ).fetchall()

    out = []
    for txn_id, txn_type, txn_date, fetched_at, txn_json in rows:
        out.append(
            {
                "txn_id": str(txn_id),
                "txn_type": str(txn_type),
                "txn_date": txn_date,
                "fetched_at": fetched_at,
                "txn_json": txn_json,
            }
        )
    return out


# ----------------------------
# Normalize
# ----------------------------
def _normalize_one(txn_payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    fees_total_txn = float(_fee_total(txn_payload))
    net_amount_txn = _as_float(txn_payload.get("netAmount") or txn_payload.get("amount"))
    order_id = _pick_order_id(txn_payload)
    position_id = str(txn_payload.get("positionId") or "").strip() or None
    trade_ts = _pick_trade_ts(txn_payload)
    trade_date = trade_ts.date() if trade_ts else None
    txn_type = _pick_txn_type(txn_payload) or "TRADE"

    sec_items = _security_items(txn_payload)
    leg_count = max(len(sec_items), 1)
    fees_leg = fees_total_txn / leg_count
    net_leg = (net_amount_txn / leg_count) if net_amount_txn is not None else None

    fills: List[Dict[str, Any]] = []
    for idx, it in enumerate(sec_items, start=1):
        leg_symbol = _instrument_symbol(it)
        asset_type = _instrument_asset_type(it)
        pos_eff = str(it.get("positionEffect") or "").strip().upper() or None

        signed_qty = _as_float(it.get("amount")) or 0.0
        abs_qty = abs(float(signed_qty))

        opt = _option_fields(it)
        multiplier = float(opt.get("multiplier") or 1.0)

        price = _infer_price(it, multiplier)
        gross = _as_float(it.get("cost"))

        instruction = _infer_instruction(asset_type, signed_qty, pos_eff or "")

        fills.append(
            {
                "leg_no": idx,
                "trade_ts": trade_ts,
                "trade_date": trade_date,
                "order_id": order_id,
                "position_id": position_id,
                "txn_type": txn_type,
                "leg_symbol": leg_symbol,
                "asset_type": asset_type,
                "instruction": instruction,
                "position_effect": pos_eff,
                "underlying": opt.get("underlying"),
                "expiry": opt.get("expiry"),
                "strike": opt.get("strike"),
                "put_call": opt.get("put_call"),
                "multiplier": multiplier,
                "signed_qty": float(signed_qty),
                "abs_qty": float(abs_qty),
                "price": price,
                "gross": gross,
                "fees_total": float(fees_leg),
                "net_amount": net_leg,
                "fees_total_txn": float(fees_total_txn),
                "net_amount_txn": net_amount_txn,
                "leg_json": json.dumps(it, ensure_ascii=False),
                "txn_json": json.dumps(txn_payload, ensure_ascii=False),
            }
        )

    return fills


def cmd_normalize(args: argparse.Namespace) -> int:
    repo = _repo_root()
    user_root = _user_root(repo)
    ledger = _ledger_path(user_root)
    if not ledger.exists():
        raise SystemExit(f"❌ Ledger not found: {ledger}")

    cfg = _load_user_yml(_cfg_path(user_root))
    cfg_acct = ((cfg.get("broker", {}) or {}).get("account") or "").strip()
    journal_db = args.journal_db or _journal_db_default()
    acct_hash, acct_num = _resolve_account_hash(args.account, cfg_acct, journal_db)
    acct_label = acct_num or (acct_hash[:8] + "…")

    today = date.today()
    if args.since:
        d0 = date.fromisoformat(str(args.since))
        d1 = date.fromisoformat(str(args.until)) if args.until else today
    else:
        days = int(args.days or 180)
        if days <= 0:
            days = 180
        d1 = today
        d0 = d1 - timedelta(days=days)

    run_id = os.getenv("TGPS_RUN_ID", "")
    step = "fills_normalize.normalize"
    try:
        with ledger_write_lock(str(ledger), run_id=run_id, step=step):
            con = _connect_attached(ledger)
            try:
                _ensure_oms_fills(con)
                if bool(args.update_orders):
                    _ensure_order_submission_fill_cols(con)

                source = _choose_source(con, str(args.source or "auto"))
                txns = _fetch_trade_txns(
                    con,
                    account_hash=acct_hash,
                    source=source,
                    d0=d0,
                    d1=d1,
                    limit=int(args.limit or 0),
                )

                if not txns:
                    print(f"[normalize] run_id={run_id or '-'} step={step} account={acct_label} source={source} window={d0}..{d1} trades=0 (nothing to do)")
                    return 0

                deletes = 0
                inserts = 0
                parsed = 0
                skipped_bad_json = 0

                con.execute("BEGIN TRANSACTION;")
                try:
                    for t in txns:
                        txn_id = str(t.get("txn_id") or "").strip()
                        if not txn_id:
                            continue

                        raw = t.get("txn_json")
                        try:
                            payload = json.loads(raw) if isinstance(raw, str) else (raw if isinstance(raw, dict) else {})
                        except Exception:
                            skipped_bad_json += 1
                            continue

                        if not isinstance(payload, dict):
                            skipped_bad_json += 1
                            continue

                        if not _pick_txn_id(payload):
                            payload["transactionId"] = txn_id

                        fills = _normalize_one(payload)
                        parsed += 1
                        try:
                            n_del = con.execute(
                                "SELECT COUNT(*) FROM ledger.lcl.oms_fills WHERE account_hash=? AND txn_id=?",
                                [acct_hash, txn_id],
                            ).fetchone()[0]
                            con.execute(
                                "DELETE FROM ledger.lcl.oms_fills WHERE account_hash=? AND txn_id=?",
                                [acct_hash, txn_id],
                            )
                            deletes += int(n_del or 0)
                        except Exception:
                            pass

                        fetched_at = t.get("fetched_at") or datetime.now()

                        if fills:
                            params_rows: List[List[Any]] = []
                            for f in fills:
                                params_rows.append(
                                    [
                                        acct_hash,
                                        txn_id,
                                        int(f.get("leg_no") or 0),
                                        f.get("trade_ts"),
                                        f.get("trade_date"),
                                        fetched_at,
                                        f.get("order_id"),
                                        f.get("position_id"),
                                        f.get("txn_type"),
                                        f.get("leg_symbol"),
                                        f.get("asset_type"),
                                        f.get("instruction"),
                                        f.get("position_effect"),
                                        f.get("underlying"),
                                        f.get("expiry"),
                                        f.get("strike"),
                                        f.get("put_call"),
                                        f.get("multiplier"),
                                        f.get("signed_qty"),
                                        f.get("abs_qty"),
                                        f.get("price"),
                                        f.get("gross"),
                                        f.get("fees_total"),
                                        f.get("net_amount"),
                                        f.get("fees_total_txn"),
                                        f.get("net_amount_txn"),
                                        f.get("leg_json"),
                                        f.get("txn_json"),
                                    ]
                                )

                            con.executemany(
                                """
                                INSERT INTO ledger.lcl.oms_fills (
                                  account_hash, txn_id, leg_no,
                                  trade_ts, trade_date, fetched_at,
                                  order_id, position_id, txn_type,
                                  leg_symbol, asset_type, instruction, position_effect,
                                  underlying, expiry, strike, put_call, multiplier,
                                  signed_qty, abs_qty, price,
                                  gross,
                                  fees_total, net_amount,
                                  fees_total_txn, net_amount_txn,
                                  leg_json, txn_json
                                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                """,
                                params_rows,
                            )
                            inserts += len(params_rows)

                    stats: Dict[str, int] = {"matched": 0, "updated": 0, "filled": 0, "partial": 0, "skipped_final": 0}
                    if bool(args.update_orders):
                        stats = _update_orders_from_fills(
                            con,
                            account_hash=acct_hash,
                            d0=d0,
                            d1=d1,
                            days=int(args.orders_days or 365),
                        )

                    con.execute("COMMIT;")

                except Exception:
                    try:
                        con.execute("ROLLBACK;")
                    except Exception:
                        pass
                    raise

                print(
                    f"[normalize] run_id={run_id or '-'} step={step} "
                    f"account={acct_label} source={source} window={d0}..{d1} "
                    f"trade_txns={len(txns)} parsed={parsed} fills_inserted={inserts} "
                    f"fills_deleted={deletes} bad_json={skipped_bad_json}"
                )

                if bool(args.update_orders):
                    print(
                        "[update-orders] "
                        f"matched={stats['matched']} updated={stats['updated']} filled={stats['filled']} partial={stats['partial']} skipped_final={stats['skipped_final']}"
                    )

                return 0
            finally:
                con.close()

    except LockHeldError as e:
        raise SystemExit(f"❌ Ledger write lock is held. {e}") from e


def _update_orders_from_fills(
    con: duckdb.DuckDBPyConnection,
    *,
    account_hash: str,
    d0: date,
    d1: date,
    days: int = 365,
) -> Dict[str, int]:
    if not _table_exists(con, "ledger.lcl.order_submissions"):
        return {"matched": 0, "updated": 0, "filled": 0, "partial": 0, "skipped_final": 0}

    cutoff_ts = datetime.now() - timedelta(days=int(days or 365))

    con.execute(
        """
        CREATE TEMP TABLE tmp_fill_agg AS
        SELECT
          account_hash,
          order_id,
          leg_symbol,
          sum(abs_qty) AS filled_qty,
          sum(abs_qty * coalesce(price, 0)) / nullif(sum(abs_qty), 0) AS avg_fill_price,
          max(trade_ts) AS filled_at
        FROM ledger.lcl.oms_fills
        WHERE account_hash = ?
          AND trade_date BETWEEN ? AND ?
          AND upper(coalesce(position_effect,'')) = 'OPENING'
          AND order_id IS NOT NULL AND length(trim(order_id)) > 0
          AND leg_symbol IS NOT NULL AND length(trim(leg_symbol)) > 0
        GROUP BY 1,2,3
        """,
        [account_hash, d0, d1],
    )

    matched = con.execute(
        """
        SELECT count(*)
        FROM ledger.lcl.order_submissions os
        JOIN tmp_fill_agg fa
          ON os.broker_order_id = fa.order_id
         AND os.option_symbol = fa.leg_symbol
        WHERE os.dry_run = FALSE
          AND os.submitted_at >= ?
        """,
        [cutoff_ts],
    ).fetchone()[0]

    final_set = ("CANCELED", "CANCELLED", "REJECTED", "EXPIRED", "FILLED")

    updated = con.execute(
        f"""
        UPDATE ledger.lcl.order_submissions os
        SET
          filled_qty = fa.filled_qty,
          avg_fill_price = fa.avg_fill_price,
          filled_at = fa.filled_at,
          status = CASE
            WHEN upper(coalesce(os.status,'')) IN ({",".join(["?"] * len(final_set))}) THEN os.status
            WHEN fa.filled_qty IS NULL OR fa.filled_qty = 0 THEN os.status
            WHEN fa.filled_qty >= coalesce(os.qty, 0) AND fa.filled_qty > 0 THEN 'FILLED'
            WHEN fa.filled_qty > 0 AND fa.filled_qty < coalesce(os.qty, 0) THEN 'PARTIAL'
            ELSE os.status
          END
        FROM tmp_fill_agg fa
        WHERE os.dry_run = FALSE
          AND os.broker_order_id = fa.order_id
          AND os.option_symbol = fa.leg_symbol
          AND os.submitted_at >= ?
        """,
        list(final_set) + [cutoff_ts],
    ).rowcount

    filled = con.execute(
        """
        SELECT count(*)
        FROM ledger.lcl.order_submissions
        WHERE dry_run=FALSE
          AND submitted_at >= ?
          AND upper(status) = 'FILLED'
        """,
        [cutoff_ts],
    ).fetchone()[0]

    partial = con.execute(
        """
        SELECT count(*)
        FROM ledger.lcl.order_submissions
        WHERE dry_run=FALSE
          AND submitted_at >= ?
          AND upper(status) = 'PARTIAL'
        """,
        [cutoff_ts],
    ).fetchone()[0]

    skipped_final = con.execute(
        f"""
        SELECT count(*)
        FROM ledger.lcl.order_submissions os
        JOIN tmp_fill_agg fa
          ON os.broker_order_id = fa.order_id
         AND os.option_symbol = fa.leg_symbol
        WHERE os.dry_run=FALSE
          AND os.submitted_at >= ?
          AND upper(coalesce(os.status,'')) IN ({",".join(["?"] * len(final_set))})
        """,
        [cutoff_ts] + list(final_set),
    ).fetchone()[0]

    try:
        con.execute("DROP TABLE tmp_fill_agg;")
    except Exception:
        pass

    return {
        "matched": int(matched or 0),
        "updated": int(updated or 0),
        "filled": int(filled or 0),
        "partial": int(partial or 0),
        "skipped_final": int(skipped_final or 0),
    }


# ----------------------------
# CLI
# ----------------------------
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Step 7: Normalize Schwab TRADE txns into OMS fills + update order_submissions")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("normalize", help="Build ledger.lcl.oms_fills from cached TRADE transactions")
    p.add_argument("--days", type=int, default=180, help="Lookback days (default 180). Ignored if --since is used.")
    p.add_argument("--since", default="", help="Start date YYYY-MM-DD (preferred for backfills).")
    p.add_argument("--until", default="", help="End date YYYY-MM-DD (default today).")
    p.add_argument("--source", default="auto", choices=["auto", "latest", "raw"], help="Read from broker_transactions_latest/raw (default auto)")
    p.add_argument("--limit", type=int, default=0, help="Optional cap on number of TRADE txns to process (0 = all)")
    p.add_argument("--update-orders", action="store_true", help="Also update order_submissions filled_qty/avg_fill_price/status")
    p.add_argument("--orders-days", type=int, default=365, help="When updating orders, only touch submissions within this many days (default 365)")
    p.add_argument("--account", default=None, help="Account number (e.g. 41472449) or account hash")
    p.add_argument("--journal-db", default="", help=f"Journal DuckDB path (default: {_journal_db_default()})")
    p.set_defaults(func=cmd_normalize)

    return ap


def main() -> int:
    args = build_parser().parse_args()
    if getattr(args, "journal_db", "") == "":
        args.journal_db = _journal_db_default()

    if getattr(args, "since", ""):
        args.since = str(args.since).strip()
        if getattr(args, "until", ""):
            args.until = str(args.until).strip()
        else:
            args.until = ""

    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
