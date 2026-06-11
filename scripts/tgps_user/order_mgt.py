#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/tgps_user/order_mgt.py
Version: 0.1.4 (2026-01-15, SGT)

Purpose
-------
Order management CLI for tgps-user:
- submissions: view what submit_orders recorded (local ledger)
- sync: pull Schwab orders (open + recent closed) and store raw snapshots locally
        optionally: --reconcile to update local order_submissions statuses
- reconcile: update local order_submissions.status based on cached broker snapshots
- orders: list cached broker orders (latest snapshot per order_id)
- show: view cached broker order JSON
- cancel: cancel by order_id (dry-run default; use --submit to execute)
- cancel --latest-batch: cancel latest submissions batch (approx 15-min burst)
- amend: replace (via Schwab replace endpoint when available; conservative support)

Notes
-----
- Broker is source of truth. Manual UI cancels are reconciled by `sync --reconcile`
  or by running `reconcile`.
- Schwab orders list API expects fromEnteredTime/toEnteredTime as full ISO-8601 UTC
  timestamps (e.g. 2026-01-12T00:00:00.000Z), not just YYYY-MM-DD.
- DuckDB QUERIES: In DuckDB, QUALIFY comes AFTER WHERE. (Your earlier CLI example
  failed because WHERE was placed after QUALIFY.)

Reliability (lock)
------------------
- All ledger writes are protected by a single-writer file lock:
    tgps-user/ledger/tgps_ledger_write.lock
- Network calls happen OUTSIDE the lock; lock is held only during DB writes.
- DB writes are wrapped in one DuckDB transaction per command phase.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import duckdb
import yaml

# ---- Repo root bootstrap ----
CODE_DIR = Path(__file__).resolve().parents[2]
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from client.schwab_admin import AuthClient, TokenStore  # noqa: E402
from client.schwab_api import RestClient, RestSession  # noqa: E402

# ---- Single-writer lock helper ----
try:
    # When invoked as module: python -m scripts.tgps_user.order_mgt
    from ._lock import LockHeldError, ledger_write_lock  # type: ignore
except Exception:
    # Fallback for direct execution / unusual sys.path contexts
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
# Account resolution helpers
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
        # treat as account number; resolve via Schwab admin API
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


def _make_rest_client() -> RestClient:
    store = TokenStore()
    auth = AuthClient(store)
    session = RestSession(auth)
    return RestClient(session)


def _call_orders(rest: RestClient, names: List[str], *args: Any, **kwargs: Any) -> Any:
    """
    Tries multiple method names for compatibility across RestClient versions.
    """
    orders = getattr(rest, "orders", None)
    if orders is None:
        raise SystemExit("RestClient has no .orders attribute")
    for n in names:
        fn = getattr(orders, n, None)
        if callable(fn):
            return fn(*args, **kwargs)
    raise SystemExit(f"RestClient.orders missing methods: {names}")


def _extract_location_order_id(location: str) -> str:
    """
    Location examples often end with /orders/{orderId}
    """
    if not location:
        return ""
    m = re.search(r"/orders/([^/?#]+)", str(location))
    return (m.group(1) if m else "").strip()


def _extract_order_id(resp: Any) -> str:
    """
    Best-effort extraction from SDK-style response:
      { ..., "order_id": "...", "headers": {...} }
    """
    if isinstance(resp, dict):
        if str(resp.get("order_id") or "").strip():
            return str(resp["order_id"]).strip()

        headers = resp.get("headers") or {}
        if isinstance(headers, dict):
            loc = headers.get("Location") or headers.get("location") or ""
            oid = _extract_location_order_id(str(loc))
            if oid:
                return oid

        oid2 = resp.get("orderId") or resp.get("id") or ""
        return str(oid2).strip()

    return ""


# ----------------------------
# Ledger tables
# ----------------------------
def _connect_attached(ledger: Path) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(":memory:")
    con.execute(f"ATTACH '{ledger.as_posix()}' AS ledger;")
    con.execute("CREATE SCHEMA IF NOT EXISTS ledger.lcl;")
    return con


def _ensure_broker_orders_table(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS ledger.lcl.broker_orders_raw (
          account_hash   VARCHAR,
          order_id       VARCHAR,
          fetched_at     TIMESTAMP,
          status         VARCHAR,
          entered_time   TIMESTAMP,
          close_time     TIMESTAMP,
          order_json     VARCHAR
        );
        """
    )
    # Index helps reads; also acts as a duplicate guard (can raise on conflict)
    try:
        con.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_broker_orders_raw ON ledger.lcl.broker_orders_raw(account_hash, order_id, fetched_at);"
        )
    except Exception:
        pass


def _ensure_sync_state_table(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS ledger.lcl.broker_sync_state (
          account_hash VARCHAR PRIMARY KEY,
          last_sync_at TIMESTAMP
        );
        """
    )


def _parse_iso_ts(s: Any) -> Optional[datetime]:
    """
    Parse ISO timestamps from Schwab (often with Z). Return naive UTC datetime for DuckDB TIMESTAMP.
    """
    if s is None:
        return None
    txt = str(s).strip()
    if not txt:
        return None

    txt = txt.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(txt)
    except Exception:
        return None

    # Normalize to UTC and drop tzinfo for DuckDB TIMESTAMP
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _iso_z(dt_utc: datetime) -> str:
    """
    Format UTC datetime to Schwab-friendly ISO with .000Z
    Example: 2026-01-12T16:35:10.000Z
    """
    if dt_utc.tzinfo is None:
        dt_utc = dt_utc.replace(tzinfo=timezone.utc)
    dt_utc = dt_utc.astimezone(timezone.utc)
    return dt_utc.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _ensure_submissions_table_exists(con: duckdb.DuckDBPyConnection) -> bool:
    """
    Returns True if ledger.lcl.order_submissions exists.
    (We don't create it here; submit_orders creates it.)
    """
    r = con.execute(
        """
        SELECT count(*)
        FROM information_schema.tables
        WHERE table_catalog='ledger' AND table_schema='lcl' AND table_name='order_submissions'
        """
    ).fetchone()
    return bool(r and int(r[0]) > 0)


# ----------------------------
# Reconcile logic
# ----------------------------
_FINAL_TO_BROKER_EQUIV = {
    "CANCELED": "CANCELED",
    "CANCELLED": "CANCELED",
    "FILLED": "FILLED",
    "REJECTED": "REJECTED",
    "EXPIRED": "EXPIRED",
}


def _canonical_status(s: Any) -> str:
    x = ("" if s is None else str(s)).strip().upper()
    return _FINAL_TO_BROKER_EQUIV.get(x, x)


def _load_latest_broker_status_map(
    con: duckdb.DuckDBPyConnection,
    *,
    account_hash: str,
    lookback_days: int = 30,
) -> Dict[str, str]:
    """
    Returns dict: broker_order_id -> latest broker status (from cached broker_orders_raw)
    """
    days = int(lookback_days or 30)
    if days <= 0:
        days = 30
    cutoff = datetime.now() - timedelta(days=days)

    rows = con.execute(
        """
        SELECT order_id, status
        FROM ledger.lcl.broker_orders_raw
        WHERE account_hash = ?
          AND fetched_at >= ?
        QUALIFY row_number() OVER (PARTITION BY order_id ORDER BY fetched_at DESC) = 1
        """,
        [account_hash, cutoff],
    ).fetchall()

    out: Dict[str, str] = {}
    for oid, st in rows:
        if oid is None:
            continue
        out[str(oid).strip()] = _canonical_status(st)
    return out


def _reconcile_submissions(
    con: duckdb.DuckDBPyConnection,
    *,
    account_hash: str,
    dry_run: bool = False,
    lookback_days: int = 30,
    only_when_final: bool = True,
) -> Dict[str, int]:
    """
    Update ledger.lcl.order_submissions.status for rows where broker_order_id is present,
    using the latest cached broker status.

    - only_when_final=True: only overwrite local status if broker status is a "final" state
      (CANCELED/FILLED/REJECTED/EXPIRED). This prevents accidental downgrade of
      SUBMITTED -> WORKING etc, unless you want that behavior.
    """
    if not _ensure_submissions_table_exists(con):
        raise SystemExit("ledger.lcl.order_submissions not found. Run submit_orders at least once.")

    broker_map = _load_latest_broker_status_map(con, account_hash=account_hash, lookback_days=lookback_days)

    if not broker_map:
        return {"seen": 0, "matched": 0, "updated": 0, "skipped_nonfinal": 0}

    # Pull candidate submissions with broker_order_id
    cutoff = datetime.now() - timedelta(days=int(lookback_days or 30))
    subs = con.execute(
        """
        SELECT submission_id, broker_order_id, status
        FROM ledger.lcl.order_submissions
        WHERE dry_run = FALSE
          AND broker_order_id IS NOT NULL
          AND length(trim(broker_order_id)) > 0
          AND submitted_at >= ?
        """,
        [cutoff],
    ).fetchall()

    updated = 0
    matched = 0
    skipped_nonfinal = 0

    for submission_id, broker_order_id, local_status in subs:
        oid = str(broker_order_id).strip()
        if not oid:
            continue
        if oid not in broker_map:
            continue

        matched += 1
        bstat = broker_map[oid]
        lstat = _canonical_status(local_status)

        # Decide if we should update
        if only_when_final:
            if bstat not in ("CANCELED", "FILLED", "REJECTED", "EXPIRED"):
                skipped_nonfinal += 1
                continue

        if bstat and bstat != lstat:
            if not dry_run:
                con.execute(
                    """
                    UPDATE ledger.lcl.order_submissions
                    SET status = ?
                    WHERE submission_id = ?
                    """,
                    [bstat, str(submission_id)],
                )
            updated += 1

    return {
        "seen": len(subs),
        "matched": matched,
        "updated": updated,
        "skipped_nonfinal": skipped_nonfinal,
    }


# ----------------------------
# Commands
# ----------------------------
def cmd_submissions(args: argparse.Namespace) -> int:
    repo = _repo_root()
    user_root = _user_root(repo)
    ledger = _ledger_path(user_root)
    if not ledger.exists():
        raise SystemExit(f"❌ Ledger not found: {ledger}")

    con = _connect_attached(ledger)
    try:
        days = int(args.days or 0)
        where = []
        params: List[Any] = []
        if days > 0:
            where.append("submitted_at >= ?")
            params.append(datetime.now() - timedelta(days=days))
        if args.status:
            where.append("upper(status) = upper(?)")
            params.append(args.status)
        wsql = ("WHERE " + " AND ".join(where)) if where else ""
        sql = f"""
        SELECT submitted_at, module, ticker, expiry, strike_found, qty,
               dry_run, status, broker_order_id, payload_sha256
        FROM ledger.lcl.order_submissions
        {wsql}
        ORDER BY submitted_at DESC
        LIMIT ?
        """
        params.append(int(args.limit))
        rows = con.execute(sql, params).fetchall()

        print(f"[submissions] rows={len(rows)}")
        for r in rows:
            print(" -", " | ".join("" if v is None else str(v) for v in r))
        return 0
    finally:
        con.close()


def cmd_sync(args: argparse.Namespace) -> int:
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

    rest = _make_rest_client()

    # ---- Phase 1: pull orders from Schwab (NO LOCK) ----
    days = int(args.days or 7)
    now_utc = datetime.now(timezone.utc)
    from_utc = now_utc - timedelta(days=days)

    from_ts = _iso_z(from_utc)
    to_ts = _iso_z(now_utc)

    statuses: List[Optional[str]]
    if args.status and str(args.status).strip():
        statuses = [s.strip() for s in str(args.status).split(",") if s.strip()]
    else:
        statuses = [None]

    max_results = int(args.max_results)
    if max_results <= 0:
        max_results = 3000

    pulled: List[dict] = []
    for st in statuses:
        resp = _call_orders(
            rest,
            ["get_orders", "get_account_orders"],
            acct_hash,
            from_entered_time=from_ts,
            to_entered_time=to_ts,
            status=(st or None),
            max_results=max_results,
        )
        data = resp.get("data") if isinstance(resp, dict) and "data" in resp else resp
        if not isinstance(data, list):
            raise SystemExit(f"Unexpected orders response type: {type(data)}")
        for o in data:
            if isinstance(o, dict):
                pulled.append(o)

    # de-dupe by orderId (keep first occurrence)
    seen_ids = set()
    data2: List[dict] = []
    for o in pulled:
        oid = str(o.get("orderId") or o.get("id") or "").strip()
        if not oid:
            continue
        if oid in seen_ids:
            continue
        seen_ids.add(oid)
        data2.append(o)

    # ---- Phase 2: DB write under single-writer lock ----
    run_id = os.getenv("TGPS_RUN_ID", "")
    step = "order_mgt.sync"
    try:
        with ledger_write_lock(str(ledger), run_id=run_id, step=step):
            con = _connect_attached(ledger)
            try:
                _ensure_broker_orders_table(con)
                _ensure_sync_state_table(con)

                now_ts_local = datetime.now()  # local timestamp for "fetched_at" ledger display

                con.execute("BEGIN TRANSACTION;")
                inserted = 0
                skipped_dupes = 0
                try:
                    for o in data2:
                        oid = str(o.get("orderId") or o.get("id") or "").strip()
                        if not oid:
                            continue
                        st = str(o.get("status") or "").strip()
                        entered = _parse_iso_ts(o.get("enteredTime"))
                        closed = _parse_iso_ts(o.get("closeTime"))

                        try:
                            con.execute(
                                """
                                INSERT INTO ledger.lcl.broker_orders_raw
                                  (account_hash, order_id, fetched_at, status, entered_time, close_time, order_json)
                                VALUES (?, ?, ?, ?, ?, ?, ?)
                                """,
                                [
                                    acct_hash,
                                    oid,
                                    now_ts_local,
                                    st,
                                    entered,
                                    closed,
                                    json.dumps(o, ensure_ascii=False),
                                ],
                            )
                            inserted += 1
                        except Exception as e:
                            msg = str(e).lower()
                            if "duplicate" in msg or "constraint" in msg or "unique" in msg:
                                skipped_dupes += 1
                                continue
                            raise

                    con.execute(
                        """
                        INSERT INTO ledger.lcl.broker_sync_state(account_hash, last_sync_at)
                        VALUES (?, ?)
                        ON CONFLICT(account_hash) DO UPDATE SET last_sync_at=excluded.last_sync_at
                        """,
                        [acct_hash, now_ts_local],
                    )

                    recon_stats = None
                    if bool(getattr(args, "reconcile", False)):
                        recon_stats = _reconcile_submissions(
                            con,
                            account_hash=acct_hash,
                            dry_run=bool(getattr(args, "dry_run", False)),
                            lookback_days=int(getattr(args, "reconcile_days", 30) or 30),
                            only_when_final=(not bool(getattr(args, "reconcile_all", False))),
                        )

                    con.execute("COMMIT;")

                except Exception:
                    try:
                        con.execute("ROLLBACK;")
                    except Exception:
                        pass
                    raise

                st_label = (",".join([s for s in statuses if s]) if any(statuses) else "ALL")
                print(
                    f"[sync] run_id={run_id or '-'} step={step} "
                    f"account={acct_label} window_days={days} status={st_label} "
                    f"pulled={len(data2)} snapshots_written={inserted} skipped_dupes={skipped_dupes}"
                )
                if recon_stats is not None:
                    print(
                        "[reconcile@sync] "
                        f"seen={recon_stats['seen']} matched={recon_stats['matched']} updated={recon_stats['updated']} "
                        f"skipped_nonfinal={recon_stats['skipped_nonfinal']} "
                        f"dry_run={bool(getattr(args, 'dry_run', False))} "
                        f"mode={'FINAL_ONLY' if (not bool(getattr(args, 'reconcile_all', False))) else 'ALL_STATUSES'}"
                    )
                return 0
            finally:
                con.close()
    except LockHeldError as e:
        raise SystemExit(f"❌ Ledger write lock is held. {e}") from e


def cmd_reconcile(args: argparse.Namespace) -> int:
    """
    Update local order_submissions.status using cached broker order snapshots.
    (You should run `order_mgt sync` first to refresh snapshots.)
    """
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

    run_id = os.getenv("TGPS_RUN_ID", "")
    step = "order_mgt.reconcile"
    try:
        with ledger_write_lock(str(ledger), run_id=run_id, step=step):
            con = _connect_attached(ledger)
            try:
                con.execute("BEGIN TRANSACTION;")
                try:
                    stats = _reconcile_submissions(
                        con,
                        account_hash=acct_hash,
                        dry_run=bool(getattr(args, "dry_run", False)),
                        lookback_days=int(getattr(args, "days", 30) or 30),
                        only_when_final=(not bool(getattr(args, "all", False))),
                    )
                    con.execute("COMMIT;")
                except Exception:
                    try:
                        con.execute("ROLLBACK;")
                    except Exception:
                        pass
                    raise

                print(
                    f"[reconcile] run_id={run_id or '-'} step={step} "
                    f"account={acct_label} "
                    f"seen={stats['seen']} matched={stats['matched']} updated={stats['updated']} skipped_nonfinal={stats['skipped_nonfinal']} "
                    f"dry_run={bool(getattr(args, 'dry_run', False))} "
                    f"mode={'FINAL_ONLY' if (not bool(getattr(args, 'all', False))) else 'ALL_STATUSES'}"
                )
                return 0
            finally:
                con.close()
    except LockHeldError as e:
        raise SystemExit(f"❌ Ledger write lock is held. {e}") from e


def cmd_orders(args: argparse.Namespace) -> int:
    repo = _repo_root()
    user_root = _user_root(repo)
    ledger = _ledger_path(user_root)
    if not ledger.exists():
        raise SystemExit(f"❌ Ledger not found: {ledger}")

    con = _connect_attached(ledger)
    try:
        where = []
        params: List[Any] = []

        days = int(args.days or 7)
        where.append("fetched_at >= ?")
        params.append(datetime.now() - timedelta(days=days))

        if args.open:
            where.append(
                "upper(status) IN ("
                "'WORKING','QUEUED','PENDING_ACTIVATION','PENDING_CANCEL','PENDING_REPLACE',"
                "'AWAITING_MANUAL_REVIEW','ACCEPTED','NEW'"
                ")"
            )
        if args.status:
            sts = [s.strip().upper() for s in args.status.split(",") if s.strip()]
            where.append("upper(status) IN (" + ",".join(["?"] * len(sts)) + ")")
            params.extend(sts)

        wsql = "WHERE " + " AND ".join(where) if where else ""
        sql = f"""
        SELECT fetched_at, order_id, status, entered_time, close_time
        FROM ledger.lcl.broker_orders_raw
        {wsql}
        QUALIFY row_number() OVER (PARTITION BY order_id ORDER BY fetched_at DESC) = 1
        ORDER BY fetched_at DESC
        LIMIT ?
        """
        params.append(int(args.limit))
        rows = con.execute(sql, params).fetchall()

        print(f"[orders] rows={len(rows)} (latest snapshot per order_id)")
        for r in rows:
            print(" -", " | ".join("" if v is None else str(v) for v in r))
        return 0
    finally:
        con.close()


def cmd_show(args: argparse.Namespace) -> int:
    repo = _repo_root()
    user_root = _user_root(repo)
    ledger = _ledger_path(user_root)
    if not ledger.exists():
        raise SystemExit(f"❌ Ledger not found: {ledger}")

    con = _connect_attached(ledger)
    try:
        r = con.execute(
            """
            SELECT order_json
            FROM ledger.lcl.broker_orders_raw
            WHERE order_id=?
            ORDER BY fetched_at DESC
            LIMIT 1
            """,
            [str(args.order_id)],
        ).fetchone()
        if not r:
            raise SystemExit(f"Order not found in broker cache: {args.order_id}. Run: order_mgt sync")
        print(r[0])
        return 0
    finally:
        con.close()


def _latest_batch_order_ids(con: duckdb.DuckDBPyConnection, *, minutes: int = 15) -> List[str]:
    """
    Approximate "latest batch" as submissions within [max(submitted_at)-minutes, max(submitted_at)].
    """
    if not _ensure_submissions_table_exists(con):
        return []

    r = con.execute(
        """
        SELECT max(submitted_at)
        FROM ledger.lcl.order_submissions
        WHERE dry_run=FALSE
        """
    ).fetchone()
    if not r or r[0] is None:
        return []
    tmax = r[0]
    tmin = tmax - timedelta(minutes=int(minutes))

    rows = con.execute(
        """
        SELECT broker_order_id
        FROM ledger.lcl.order_submissions
        WHERE dry_run=FALSE
          AND submitted_at >= ?
          AND broker_order_id IS NOT NULL
          AND length(trim(broker_order_id)) > 0
        ORDER BY submitted_at DESC
        """,
        [tmin],
    ).fetchall()

    order_ids = [str(oid).strip() for (oid,) in rows if oid and str(oid).strip()]

    # de-dupe, keep order
    seen = set()
    out = []
    for x in order_ids:
        if x in seen:
            continue
        seen.add(x)
        out.append(x)
    return out


# ---- Cancel helpers ----

_FINAL_STATUSES = {"FILLED", "CANCELED", "CANCELLED", "REJECTED", "EXPIRED"}
# Broker may report cancel-in-flight; treat as not-cancellable.
_NONCANCELLABLE_WORKING = {"PENDING_CANCEL"}


def _norm_status(s: Any) -> str:
    return str(s or "").strip().upper()


def _latest_submission_statuses(
    con: duckdb.DuckDBPyConnection, order_ids: List[str]
) -> Dict[str, str]:
    """Return latest local submission status per broker_order_id."""
    if not order_ids:
        return {}
    ph = ",".join(["?"] * len(order_ids))
    rows = con.execute(
        f"""
        SELECT broker_order_id, status
        FROM ledger.lcl.order_submissions
        WHERE broker_order_id IN ({ph})
        QUALIFY row_number() OVER (PARTITION BY broker_order_id ORDER BY submitted_at DESC) = 1
        """,
        order_ids,
    ).fetchall()
    return {str(oid).strip(): _norm_status(st) for (oid, st) in rows if oid}


def _latest_broker_statuses(
    con: duckdb.DuckDBPyConnection, order_ids: List[str]
) -> Dict[str, str]:
    """Return latest cached broker status per order_id (if present)."""
    if not order_ids:
        return {}
    ph = ",".join(["?"] * len(order_ids))
    rows = con.execute(
        f"""
        SELECT order_id, status
        FROM ledger.lcl.broker_orders_raw
        WHERE order_id IN ({ph})
        QUALIFY row_number() OVER (PARTITION BY order_id ORDER BY fetched_at DESC) = 1
        """,
        order_ids,
    ).fetchall()
    return {str(oid).strip(): _norm_status(st) for (oid, st) in rows if oid}


def _is_final(st: str) -> bool:
    return _norm_status(st) in _FINAL_STATUSES

def cmd_cancel(args: argparse.Namespace) -> int:
    """
    Cancel either:
      - a single --order-id
      - --latest-batch (all broker_order_id from most recent submissions burst)
    """
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

    con = _connect_attached(ledger)
    try:
        if args.latest_batch:
            order_ids = _latest_batch_order_ids(con, minutes=15)
        else:
            if not args.order_id:
                raise SystemExit("Provide --order-id or use --latest-batch")
            order_ids = [str(args.order_id).strip()]

        if not order_ids:
            print("[cancel] nothing to cancel (no broker_order_id found)")
            return 0

        # Filter out orders that are already final (locally or per latest broker snapshot)
        sub_status = _latest_submission_statuses(con, order_ids)
        broker_status = _latest_broker_statuses(con, order_ids)

        to_cancel: List[str] = []
        skipped: List[Tuple[str, str]] = []

        for oid in order_ids:
            st_b = broker_status.get(oid, "")
            st_s = sub_status.get(oid, "")
            st = st_b or st_s  # prefer broker snapshot if we have it
            stn = _norm_status(st)

            if stn in _FINAL_STATUSES:
                skipped.append((oid, stn or "FINAL"))
                continue
            if stn in _NONCANCELLABLE_WORKING:
                skipped.append((oid, stn))
                continue

            to_cancel.append(oid)

        print(
            f"[cancel] account={acct_label} total={len(order_ids)} "
            f"attempt={len(to_cancel)} skipped={len(skipped)} submit={bool(args.submit)}"
        )

        if skipped:
            print("[cancel] skipped (already final / not cancellable):")
            for oid, st in skipped:
                print(f" - {oid} (status={st})")

        if not to_cancel:
            print("[cancel] nothing to cancel after filtering.")
            return 0

        print("[cancel] to cancel:")
        for oid in to_cancel:
            st = broker_status.get(oid) or sub_status.get(oid) or ""
            stn = _norm_status(st) or "UNKNOWN"
            print(f" - {oid} (status={stn})")

        if not args.submit:
            print("DRY-RUN: add --submit to actually cancel at Schwab.")
            return 0

        rest = _make_rest_client()
        ok = 0
        failed = 0
        for oid in to_cancel:
            try:
                resp = _call_orders(rest, ["cancel_order", "cancel"], acct_hash, oid)
                got = _extract_order_id(resp) or oid
                print(f"[CANCELLED?] order_id={got}")
                ok += 1
            except Exception as e:
                # Schwab returns 400 for orders already final / not cancellable; don't abort the batch
                resp = getattr(e, "response", None)
                sc = getattr(resp, "status_code", None)
                if sc in (400, 404):
                    print(f"[cancel] skip order_id={oid} http={sc} (likely already final/not cancellable)")
                    failed += 1
                    continue
                raise

        print(f"[cancel] done. ok={ok} failed={failed} attempted={len(to_cancel)}")
        return 0
    finally:
        con.close()


def cmd_amend(args: argparse.Namespace) -> int:
    """
    Amend = replace (implemented via Schwab replace endpoint).
    Minimal support: change LIMIT price and/or qty for a SIMPLE order.
    """
    if not args.order_id:
        raise SystemExit("Provide --order-id")

    if args.new_price is None and args.new_qty is None:
        raise SystemExit("Provide --new-price and/or --new-qty")

    repo = _repo_root()
    user_root = _user_root(repo)

    cfg = _load_user_yml(_cfg_path(user_root))
    cfg_acct = ((cfg.get("broker", {}) or {}).get("account") or "").strip()
    journal_db = args.journal_db or _journal_db_default()
    acct_hash, acct_num = _resolve_account_hash(args.account, cfg_acct, journal_db)
    acct_label = acct_num or (acct_hash[:8] + "…")

    rest = _make_rest_client()

    # Pull the existing order details from Schwab
    o = _call_orders(rest, ["get_order", "get_order_by_id"], acct_hash, str(args.order_id))
    od = o.get("data") if isinstance(o, dict) and "data" in o else o
    if not isinstance(od, dict):
        raise SystemExit("Unexpected get_order response")

    # Very conservative: only allow SINGLE orders with one leg
    if str(od.get("orderStrategyType") or "").upper() != "SINGLE":
        raise SystemExit("amend currently supports only SINGLE orders (not TRIGGER/OCO).")

    legs = od.get("orderLegCollection") or []
    if not isinstance(legs, list) or len(legs) != 1:
        raise SystemExit("amend currently supports only 1-leg orders.")

    payload = {
        "orderStrategyType": "SINGLE",
        "orderType": od.get("orderType"),
        "session": od.get("session", "NORMAL"),
        "duration": od.get("duration"),
        "orderLegCollection": legs,
    }

    if args.new_qty is not None:
        legs[0]["quantity"] = int(args.new_qty)

    if args.new_price is not None:
        payload["price"] = float(args.new_price)

    print(f"[amend] account={acct_label} order_id={args.order_id} submit={bool(args.submit)}")
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))

    if not args.submit:
        print("DRY-RUN: add --submit to actually replace at Schwab.")
        return 0

    resp = _call_orders(rest, ["replace_order", "replace"], acct_hash, str(args.order_id), payload)
    new_id = _extract_order_id(resp)
    print(f"[REPLACED?] old={args.order_id} new={new_id or '(check response)'}")
    return 0


# ----------------------------
# CLI
# ----------------------------
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="tgps-user Order Management (submissions/sync/reconcile/orders/show/cancel/amend)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("submissions", help="Show recent local order_submissions rows")
    p.add_argument("--days", type=int, default=7, help="Lookback days (default 7)")
    p.add_argument("--status", default="", help="Optional status filter (e.g. SUBMITTED)")
    p.add_argument("--limit", type=int, default=20, help="Max rows (default 20)")
    p.set_defaults(func=cmd_submissions)

    p = sub.add_parser("sync", help="Pull Schwab orders and store raw snapshots locally")
    p.add_argument("--days", type=int, default=7, help="Lookback days (default 7)")
    p.add_argument("--status", default="", help="Optional status filter (comma-separated; we merge calls)")
    p.add_argument("--max-results", type=int, default=3000, help="Max results (default 3000)")
    p.add_argument("--account", default=None, help="Account number (e.g. 41472449) or account hash")
    p.add_argument("--journal-db", default="", help=f"Journal DuckDB path (default: {_journal_db_default()})")
    p.add_argument("--reconcile", action="store_true", help="After sync, update order_submissions.status from cached broker snapshots")
    p.add_argument("--reconcile-days", type=int, default=30, help="Reconcile lookback days (default 30)")
    p.add_argument("--reconcile-all", action="store_true", help="Reconcile using ALL broker statuses (default is FINAL-only)")
    p.add_argument("--dry-run", action="store_true", help="Reconcile dry-run (no DB updates)")
    p.set_defaults(func=cmd_sync)

    p = sub.add_parser("reconcile", help="Update order_submissions.status using cached broker snapshots (run sync first)")
    p.add_argument("--days", type=int, default=30, help="Lookback days for submissions & snapshots (default 30)")
    p.add_argument("--all", action="store_true", help="Update using ALL broker statuses (default is FINAL-only)")
    p.add_argument("--dry-run", action="store_true", help="Dry-run (no DB updates)")
    p.add_argument("--account", default=None, help="Account number (e.g. 41472449) or account hash")
    p.add_argument("--journal-db", default="", help=f"Journal DuckDB path (default: {_journal_db_default()})")
    p.set_defaults(func=cmd_reconcile)

    p = sub.add_parser("orders", help="List cached broker orders (from sync snapshots)")
    p.add_argument("--days", type=int, default=7, help="Lookback days (default 7)")
    p.add_argument("--open", action="store_true", help="Only open-ish statuses")
    p.add_argument("--status", default="", help="Optional status filter (comma-separated)")
    p.add_argument("--limit", type=int, default=50, help="Max rows (default 50)")
    p.set_defaults(func=cmd_orders)

    p = sub.add_parser("show", help="Show cached raw JSON for a broker order_id")
    p.add_argument("--order-id", required=True, help="Broker order id")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("cancel", help="Cancel an order (dry-run default)")
    p.add_argument("--order-id", default="", help="Broker order id")
    p.add_argument("--latest-batch", action="store_true", help="Cancel latest batch from submissions table (approx 15-min burst)")
    p.add_argument("--account", default=None, help="Account number (e.g. 41472449) or account hash")
    p.add_argument("--journal-db", default="", help=f"Journal DuckDB path (default: {_journal_db_default()})")
    p.add_argument("--submit", action="store_true", help="Actually cancel at Schwab")
    p.set_defaults(func=cmd_cancel)

    p = sub.add_parser("amend", help="Replace order (dry-run default)")
    p.add_argument("--order-id", required=True, help="Broker order id")
    p.add_argument("--new-price", type=float, default=None, help="New LIMIT price")
    p.add_argument("--new-qty", type=float, default=None, help="New quantity")
    p.add_argument("--account", default=None, help="Account number (e.g. 41472449) or account hash")
    p.add_argument("--journal-db", default="", help=f"Journal DuckDB path (default: {_journal_db_default()})")
    p.add_argument("--submit", action="store_true", help="Actually replace at Schwab")
    p.set_defaults(func=cmd_amend)

    return ap


def main() -> int:
    args = build_parser().parse_args()
    if getattr(args, "journal_db", "") == "":
        args.journal_db = _journal_db_default()
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
