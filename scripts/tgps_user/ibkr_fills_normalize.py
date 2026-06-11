#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/tgps_user/ibkr_fills_normalize.py
Version: 0.1.0 (2026-01-22, SGT)

Purpose
-------
Normalize IBKR executions (stored by ibkr_fills_mgt.py into broker_transactions_*)
into the shared OMS fills table:
  ledger.lcl.oms_fills

Optional:
- Update ledger.lcl.order_submissions fill fields (filled_qty, avg_fill_price, filled_at, status)
  when broker_order_id matches execution.orderId and option_symbol matches leg_symbol.

Notes
-----
- IBKR executions don't reliably tell OPENING vs CLOSING, so position_effect is left NULL.
- instruction is BUY/SELL derived from execution.side (BOT/SLD).

Run
---
  python -m scripts.tgps_user.ibkr_fills_normalize normalize --days 30 --source latest --update-orders
"""

from __future__ import annotations

import argparse
import hashlib
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

# ---- Single-writer lock helper ----
try:
    from ._lock import LockHeldError, ledger_write_lock  # type: ignore
except Exception:
    from scripts.tgps_user._lock import LockHeldError, ledger_write_lock  # type: ignore


# ----------------------------
# Time helpers
# ----------------------------
def _utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _ibkr_account_hash(account: str) -> str:
    return _sha256(f"IBKR:{(account or '').strip()}")


def _parse_ibkr_exec_time(s: Any) -> Optional[datetime]:
    if s is None:
        return None
    txt = str(s).strip()
    if not txt:
        return None
    while "  " in txt:
        txt = txt.replace("  ", " ")
    parts = txt.split(" ")
    if len(parts) >= 3 and len(parts[0]) == 8 and ":" in parts[1]:
        txt2 = parts[0] + " " + parts[1]
    else:
        txt2 = txt
    for fmt in ("%Y%m%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y%m%d"):
        try:
            return datetime.strptime(txt2, fmt)
        except Exception:
            continue
    return None


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


def _get_ibkr_cfg(cfg: dict) -> dict:
    broker = cfg.get("broker", {}) or {}
    return (broker.get("ibkr", {}) or cfg.get("ibkr", {}) or {})


# ----------------------------
# DuckDB helpers
# ----------------------------
def _connect_attached(ledger: Path) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(":memory:")
    con.execute(f"ATTACH '{ledger.as_posix()}' AS ledger;")
    con.execute("CREATE SCHEMA IF NOT EXISTS ledger.lcl;")
    return con


def _table_exists(con: duckdb.DuckDBPyConnection, qualified: str) -> bool:
    try:
        con.execute(f"SELECT 1 FROM {qualified} LIMIT 1;")
        return True
    except Exception:
        return False


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

          fees_total        DOUBLE,
          net_amount        DOUBLE,

          fees_total_txn    DOUBLE,
          net_amount_txn    DOUBLE,

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
    for c, typ in {
        "filled_qty": "DOUBLE",
        "avg_fill_price": "DOUBLE",
        "filled_at": "TIMESTAMP",
    }.items():
        if c not in cols:
            con.execute(f"ALTER TABLE ledger.lcl.order_submissions ADD COLUMN {c} {typ};")


# ----------------------------
# Parsing helpers
# ----------------------------
def _as_float(x: Any) -> Optional[float]:
    if x is None:
        return None
    try:
        return float(x)
    except Exception:
        return None


def _parse_expiry(lastTradeDateOrContractMonth: Any) -> Optional[date]:
    if lastTradeDateOrContractMonth is None:
        return None
    s = str(lastTradeDateOrContractMonth).strip()
    if not s:
        return None
    # common: "YYYYMMDD"
    digits = "".join([c for c in s if c.isdigit()])
    if len(digits) >= 8:
        try:
            return date(int(digits[0:4]), int(digits[4:6]), int(digits[6:8]))
        except Exception:
            return None
    return None


def _secType_to_asset_type(secType: str) -> str:
    st = (secType or "").strip().upper()
    if st in ("OPT", "OPTION"):
        return "OPTION"
    if st in ("STK", "STOCK"):
        return "EQUITY"
    return st or ""


def _instruction_from_side(side: str, asset_type: str) -> str:
    s = (side or "").strip().upper()
    if s in ("BOT", "BUY"):
        return "BUY"
    if s in ("SLD", "SELL"):
        return "SELL"
    return s or ""


def _best_leg_symbol(contract: Dict[str, Any]) -> str:
    return str(contract.get("localSymbol") or contract.get("symbol") or "").strip().upper()


def _multiplier(contract: Dict[str, Any]) -> float:
    m = contract.get("multiplier")
    try:
        if m is None:
            return 1.0
        if isinstance(m, (int, float)):
            return float(m)
        ms = str(m).strip()
        return float(ms) if ms else 1.0
    except Exception:
        return 1.0


def _signed_qty(side: str, shares: Any) -> Optional[float]:
    q = _as_float(shares)
    if q is None:
        return None
    s = (side or "").strip().upper()
    if s in ("BOT", "BUY"):
        return abs(q)
    if s in ("SLD", "SELL"):
        return -abs(q)
    return q


# ----------------------------
# Source reads
# ----------------------------
def _choose_source(con: duckdb.DuckDBPyConnection, source: str) -> str:
    s = (source or "auto").strip().lower()
    if s in ("latest", "raw"):
        return s
    have_latest = _table_exists(con, "ledger.lcl.broker_transactions_latest")
    return "latest" if have_latest else "raw"


def _fetch_ibkr_trade_txns(
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
            raise SystemExit("Missing ledger.lcl.broker_transactions_latest. Run ibkr_fills_mgt sync --write-mode upsert first.")
        rows = con.execute(
            f"""
            SELECT txn_id, coalesce(txn_date, cast(last_fetched_at as date)) as txn_date,
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
        return [{"txn_id": str(a), "txn_date": b, "fetched_at": c, "txn_json": d} for (a, b, c, d) in rows]

    if not _table_exists(con, "ledger.lcl.broker_transactions_raw"):
        raise SystemExit("Missing ledger.lcl.broker_transactions_raw. Run ibkr_fills_mgt sync first.")
    rows = con.execute(
        f"""
        SELECT txn_id, coalesce(txn_date, cast(fetched_at as date)) as txn_date,
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
    return [{"txn_id": str(a), "txn_date": b, "fetched_at": c, "txn_json": d} for (a, b, c, d) in rows]


# ----------------------------
# Normalize
# ----------------------------
def cmd_normalize(args: argparse.Namespace) -> int:
    repo = _repo_root()
    user_root = _user_root(repo)
    ledger = _ledger_path(user_root)
    if not ledger.exists():
        raise SystemExit(f"❌ Ledger not found: {ledger}")

    cfg = _load_user_yml(_cfg_path(user_root))
    ib = _get_ibkr_cfg(cfg)

    account = str(args.account or ib.get("account") or "").strip()
    if not account:
        raise SystemExit("❌ Missing IBKR account. Use --account DUxxxx or set broker.ibkr.account in tgps-user/config/lcl.user.yml")

    acct_hash = _ibkr_account_hash(account)

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
    step = "ibkr_fills_normalize.normalize"

    try:
        with ledger_write_lock(str(ledger), run_id=run_id, step=step):
            con = _connect_attached(ledger)
            try:
                _ensure_oms_fills(con)
                if bool(args.update_orders):
                    _ensure_order_submission_fill_cols(con)

                source = _choose_source(con, str(args.source or "auto"))
                txns = _fetch_ibkr_trade_txns(
                    con,
                    account_hash=acct_hash,
                    source=source,
                    d0=d0,
                    d1=d1,
                    limit=int(args.limit or 0),
                )

                if not txns:
                    print(f"[normalize:IBKR] account={account} source={source} window={d0}..{d1} trades=0 (nothing to do)")
                    return 0

                deletes = 0
                inserts = 0
                parsed = 0
                bad_json = 0

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
                            bad_json += 1
                            continue

                        if not isinstance(payload, dict) or payload.get("broker") != "IBKR":
                            bad_json += 1
                            continue

                        contract = payload.get("contract") or {}
                        execu = payload.get("execution") or {}
                        comm = payload.get("commission") or {}

                        trade_ts = _parse_ibkr_exec_time(execu.get("time"))
                        trade_date = trade_ts.date() if trade_ts else None
                        fetched_at = t.get("fetched_at") or _utc_now_naive()

                        order_id = str(execu.get("orderId") or "").strip() or None
                        leg_symbol = _best_leg_symbol(contract)
                        asset_type = _secType_to_asset_type(str(contract.get("secType") or ""))
                        instruction = _instruction_from_side(str(execu.get("side") or ""), asset_type)

                        mult = _multiplier(contract)
                        px = _as_float(execu.get("price"))
                        q_signed = _signed_qty(str(execu.get("side") or ""), execu.get("shares")) or 0.0
                        abs_qty = abs(float(q_signed))

                        # gross cashflow: BUY -> negative, SELL -> positive
                        gross = None
                        if px is not None:
                            gross = -float(q_signed) * float(px) * float(mult)

                        fee = _as_float(comm.get("commission"))
                        fee_abs = abs(float(fee)) if fee is not None else 0.0

                        # net cashflow after commission
                        net_amount = None if gross is None else float(gross) - float(fee_abs)

                        underlying = str(contract.get("symbol") or "").strip().upper() or None
                        expiry = _parse_expiry(contract.get("lastTradeDateOrContractMonth"))
                        strike = _as_float(contract.get("strike"))
                        put_call = str(contract.get("right") or "").strip().upper() or None

                        # delete+insert per txn_id
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

                        con.execute(
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
                            [
                                acct_hash,
                                txn_id,
                                1,
                                trade_ts,
                                trade_date,
                                fetched_at,
                                order_id,
                                None,
                                "TRADE",
                                leg_symbol,
                                asset_type,
                                instruction,
                                None,  # position_effect unknown for IBKR executions
                                underlying,
                                expiry,
                                strike,
                                put_call,
                                mult,
                                float(q_signed),
                                float(abs_qty),
                                px,
                                gross,
                                float(fee_abs),
                                net_amount,
                                float(fee_abs),
                                net_amount,
                                json.dumps({"contract": contract, "execution": execu, "commission": comm}, ensure_ascii=False),
                                json.dumps(payload, ensure_ascii=False),
                            ],
                        )
                        inserts += 1
                        parsed += 1

                    stats = {"matched": 0, "updated": 0, "filled": 0, "partial": 0, "skipped_final": 0}
                    if bool(args.update_orders):
                        stats = _update_orders_from_fills(con, account_hash=acct_hash, days=int(args.orders_days or 365))

                    con.execute("COMMIT;")
                except Exception:
                    try:
                        con.execute("ROLLBACK;")
                    except Exception:
                        pass
                    raise

                print(
                    f"[normalize:IBKR] account={account} source={source} window={d0}..{d1} "
                    f"trade_txns={len(txns)} parsed={parsed} fills_inserted={inserts} fills_deleted={deletes} bad_json={bad_json}"
                )
                if bool(args.update_orders):
                    print(
                        "[update-orders:IBKR] "
                        f"matched={stats['matched']} updated={stats['updated']} filled={stats['filled']} partial={stats['partial']} skipped_final={stats['skipped_final']}"
                    )
                return 0
            finally:
                con.close()

    except LockHeldError as e:
        raise SystemExit(f"❌ Ledger write lock is held. {e}") from e


def _update_orders_from_fills(con: duckdb.DuckDBPyConnection, *, account_hash: str, days: int = 365) -> Dict[str, int]:
    if not _table_exists(con, "ledger.lcl.order_submissions"):
        return {"matched": 0, "updated": 0, "filled": 0, "partial": 0, "skipped_final": 0}

    cutoff_ts = datetime.now() - timedelta(days=int(days or 365))
    cols = _colset(con, "order_submissions")
    has_broker = "broker" in cols

    # Aggregate fills by order_id + leg_symbol
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
          AND order_id IS NOT NULL AND length(trim(order_id)) > 0
          AND leg_symbol IS NOT NULL AND length(trim(leg_symbol)) > 0
        GROUP BY 1,2,3
        """,
        [account_hash],
    )

    broker_filter_sql = " AND upper(coalesce(os.broker,'')) = 'IBKR' " if has_broker else ""

    matched = con.execute(
        f"""
        SELECT count(*)
        FROM ledger.lcl.order_submissions os
        JOIN tmp_fill_agg fa
          ON os.broker_order_id = fa.order_id
         AND os.option_symbol = fa.leg_symbol
        WHERE os.dry_run = FALSE
          AND os.submitted_at >= ?
          {broker_filter_sql}
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
          {broker_filter_sql}
        """,
        list(final_set) + [cutoff_ts],
    ).rowcount

    filled = con.execute(
        f"""
        SELECT count(*)
        FROM ledger.lcl.order_submissions
        WHERE dry_run=FALSE
          AND submitted_at >= ?
          {("AND upper(coalesce(broker,''))='IBKR'" if has_broker else "")}
          AND upper(status) = 'FILLED'
        """,
        [cutoff_ts],
    ).fetchone()[0]

    partial = con.execute(
        f"""
        SELECT count(*)
        FROM ledger.lcl.order_submissions
        WHERE dry_run=FALSE
          AND submitted_at >= ?
          {("AND upper(coalesce(broker,''))='IBKR'" if has_broker else "")}
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
          {broker_filter_sql}
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
    ap = argparse.ArgumentParser(description="Normalize IBKR executions into ledger.lcl.oms_fills (+ optional update order_submissions)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("normalize", help="Build ledger.lcl.oms_fills from IBKR TRADE rows in broker_transactions_*")
    p.add_argument("--days", type=int, default=180, help="Lookback days (default 180). Ignored if --since is used.")
    p.add_argument("--since", default="", help="Start date YYYY-MM-DD (preferred for backfills).")
    p.add_argument("--until", default="", help="End date YYYY-MM-DD (default today).")
    p.add_argument("--source", default="auto", choices=["auto", "latest", "raw"], help="Read from broker_transactions_latest/raw (default auto)")
    p.add_argument("--limit", type=int, default=0, help="Optional cap on number of txns to process (0 = all)")
    p.add_argument("--update-orders", action="store_true", help="Also update order_submissions filled_qty/avg_fill_price/status")
    p.add_argument("--orders-days", type=int, default=365, help="When updating orders, only touch submissions within this many days (default 365)")
    p.add_argument("--account", default="", help="IBKR account (DUxxxx). If empty, uses lcl.user.yml broker.ibkr.account")
    p.set_defaults(func=cmd_normalize)

    return ap


def main() -> int:
    args = build_parser().parse_args()
    if getattr(args, "since", ""):
        args.since = str(args.since).strip()
        if getattr(args, "until", ""):
            args.until = str(args.until).strip()
        else:
            args.until = ""
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
