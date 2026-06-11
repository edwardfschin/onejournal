#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/tgps_user/ibkr_fills_mgt.py
Version: 0.3.0 (2026-01-22, SGT)

Purpose
-------
IBKR executions (fills) + optional positions snapshot management CLI for tgps-user.

This is the IBKR analog of:
- scripts/tgps_user/fills_mgt.py (Schwab)

Key design
----------
- We pull executions via reqExecutions() and store them into the SAME generic cache tables:
    ledger.lcl.broker_transactions_raw
    ledger.lcl.broker_transactions_latest
  BUT using a stable IBKR-derived account_hash = sha256("IBKR:<account>").

- txn_json is a JSON payload we control, containing:
    { broker, account, contract, execution, commission }

Why your current run crashed
----------------------------
IBKR changed EWrapper.error() signatures across API versions:
- newer versions include errorTime (and may include advancedOrderRejectJson)
Your wrapper must accept both forms, otherwise:
  TypeError: error() ... 6 were given
(IBKR notes errorTime was added in newer API versions.)  See IBKR Campus docs.

Notes
-----
- reqExecutions is not a full-accounting "transactions" history endpoint.
  It's executions/fills. IBKR may limit how far back you can query depending
  on settings/session. This is still the correct building block for "fills".

CLI
---
Run from the TradersGPS repo root (so `scripts.*` is importable):
  cd ~/.../TradersGPS

Sync last 14 days into latest + also append raw audit:
  python -m scripts.tgps_user.ibkr_fills_mgt sync --days 14 --write-mode upsert --also-raw

If you ran from ~ and got "No module named scripts", you were not in repo root.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import threading
import time
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
# IBKR (ibapi)
# ----------------------------
from ibapi.client import EClient  # type: ignore
from ibapi.wrapper import EWrapper  # type: ignore
from ibapi.execution import ExecutionFilter  # type: ignore

# Json Helper
from decimal import Decimal
from datetime import date, datetime

def _json_default(o):
    if isinstance(o, Decimal):
        return float(o)
    if isinstance(o, (datetime, date)):
        return o.isoformat()
    # IBKR objects often serialize fine via __dict__
    d = getattr(o, "__dict__", None)
    if isinstance(d, dict) and d:
        return d
    return str(o)

def _json_dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=_json_default)

# ----------------------------
# Time helpers
# ----------------------------
def _utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _ibkr_filter_time(dt: datetime) -> str:
    # IBKR expects: "YYYYMMDD HH:MM:SS"
    return dt.strftime("%Y%m%d %H:%M:%S")


def _parse_ibkr_exec_time(s: Any) -> Optional[datetime]:
    """
    IBKR execution.time often looks like:
      "20260122  09:31:02"
      "20260122 09:31:02"
    It may include timezone suffix in some environments.
    We parse best-effort and return UTC-naive timestamp for DuckDB.
    """
    if s is None:
        return None
    txt = str(s).strip()
    if not txt:
        return None

    # Normalize double spaces
    while "  " in txt:
        txt = txt.replace("  ", " ")

    # Drop trailing timezone token if present (best-effort)
    parts = txt.split(" ")
    if len(parts) >= 3 and len(parts[0]) == 8 and ":" in parts[1]:
        txt2 = parts[0] + " " + parts[1]
    else:
        txt2 = txt

    for fmt in ("%Y%m%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y%m%d"):
        try:
            dt = datetime.strptime(txt2, fmt)
            return dt  # naive
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
    raise SystemExit("❌ Could not find repo root (expected 'tgps-user' folder). Run from TradersGPS repo root.")


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
    # support either:
    #   broker: { ibkr: {...} }
    # or older flat layouts:
    #   ibkr: {...}
    return (broker.get("ibkr", {}) or cfg.get("ibkr", {}) or {})


def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _ibkr_account_hash(account: str) -> str:
    return _sha256(f"IBKR:{(account or '').strip()}")


# ----------------------------
# DuckDB helpers (reuse same generic cache tables as Schwab)
# ----------------------------
def _connect_attached(ledger: Path) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(":memory:")
    con.execute(f"ATTACH '{ledger.as_posix()}' AS ledger;")
    con.execute("CREATE SCHEMA IF NOT EXISTS ledger.lcl;")
    return con


def _ensure_broker_transactions_table(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS ledger.lcl.broker_transactions_raw (
          account_hash  VARCHAR,
          txn_id        VARCHAR,
          fetched_at    TIMESTAMP,
          txn_date      DATE,
          txn_type      VARCHAR,
          symbol        VARCHAR,
          amount        DOUBLE,
          quantity      DOUBLE,
          price         DOUBLE,
          txn_json      VARCHAR
        );
        """
    )
    try:
        con.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_broker_txn_raw ON ledger.lcl.broker_transactions_raw(account_hash, txn_id, fetched_at);"
        )
    except Exception:
        pass


def _ensure_broker_transactions_latest_table(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS ledger.lcl.broker_transactions_latest (
          account_hash     VARCHAR,
          txn_id           VARCHAR,
          last_fetched_at  TIMESTAMP,
          txn_date         DATE,
          txn_type         VARCHAR,
          symbol           VARCHAR,
          amount           DOUBLE,
          quantity         DOUBLE,
          price            DOUBLE,
          txn_json         VARCHAR
        );
        """
    )
    try:
        con.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_broker_txn_latest ON ledger.lcl.broker_transactions_latest(account_hash, txn_id);"
        )
    except Exception:
        pass


def _validate_write_mode(s: str) -> str:
    m = (s or "append").strip().lower()
    if m not in ("append", "override", "upsert"):
        raise SystemExit("Invalid --write-mode. Use: append | override | upsert")
    return m


# ----------------------------
# IBKR Client App
# ----------------------------
class IBKRApp(EWrapper, EClient):
    def __init__(self, *, verbose: bool = False):
        EClient.__init__(self, self)
        self.verbose = verbose

        self._ready = threading.Event()
        self._exec_end = threading.Event()

        self.errors: List[Dict[str, Any]] = []
        self.exec_rows: List[Dict[str, Any]] = []
        self.commissions_by_execid: Dict[str, Dict[str, Any]] = {}

        self._next_valid_id: Optional[int] = None

    # ---- Connection lifecycle ----
    def nextValidId(self, orderId: int) -> None:  # noqa: N802
        self._next_valid_id = int(orderId)
        if self.verbose:
            print(f"[ibkr] nextValidId={orderId}")
        self._ready.set()

    def managedAccounts(self, accountsList: str) -> None:  # noqa: N802
        if self.verbose:
            print(f"[ibkr] managedAccounts={accountsList}")

    # ---- Error callback (supports multiple API signatures) ----
    def error(self, reqId: int, *args):
        """
        IBKR API has multiple error() signatures across versions:
        - error(reqId, errorCode, errorString)
        - error(reqId, errorCode, errorString, advancedOrderRejectJson)
        - error(reqId, errorTime, errorCode, errorString, advancedOrderRejectJson)
        We accept them all so the reader thread never dies.
        """
        errorTime = None
        errorCode = None
        errorString = ""
        advanced = ""

        if len(args) == 2:
            # (errorCode, errorString)
            errorCode, errorString = args
        elif len(args) == 3:
            # (errorCode, errorString, advanced)
            errorCode, errorString, advanced = args
        elif len(args) == 4:
            # (errorTime, errorCode, errorString, advanced)
            errorTime, errorCode, errorString, advanced = args
        else:
            # unknown shape — don't crash
            errorString = " ".join(str(a) for a in args)

        # normalize types
        try:
            errorCode = int(errorCode) if errorCode is not None else None
        except Exception:
            pass

        msg = f"[ibkr:error] reqId={reqId} code={errorCode} msg={errorString}"
        if errorTime is not None:
            msg += f" time={errorTime}"
        if advanced:
            msg += f" advanced={advanced}"
        print(msg)


    # ---- Executions ----
    def execDetails(self, reqId: int, contract: Any, execution: Any) -> None:  # noqa: N802
        c = {
            "symbol": getattr(contract, "symbol", None),
            "secType": getattr(contract, "secType", None),
            "exchange": getattr(contract, "exchange", None),
            "currency": getattr(contract, "currency", None),
            "localSymbol": getattr(contract, "localSymbol", None),
            "multiplier": getattr(contract, "multiplier", None),
            "lastTradeDateOrContractMonth": getattr(contract, "lastTradeDateOrContractMonth", None),
            "strike": getattr(contract, "strike", None),
            "right": getattr(contract, "right", None),
            "conId": getattr(contract, "conId", None),
        }
        e = {
            "execId": getattr(execution, "execId", None),
            "time": getattr(execution, "time", None),
            "acctNumber": getattr(execution, "acctNumber", None),
            "exchange": getattr(execution, "exchange", None),
            "side": getattr(execution, "side", None),
            "shares": getattr(execution, "shares", None),
            "price": getattr(execution, "price", None),
            "permId": getattr(execution, "permId", None),
            "clientId": getattr(execution, "clientId", None),
            "orderId": getattr(execution, "orderId", None),
            "liquidation": getattr(execution, "liquidation", None),
            "cumQty": getattr(execution, "cumQty", None),
            "avgPrice": getattr(execution, "avgPrice", None),
            "lastLiquidity": getattr(execution, "lastLiquidity", None),
        }
        self.exec_rows.append({"contract": c, "execution": e})

        if self.verbose:
            print(f"[ibkr] execDetails execId={e.get('execId')} sym={c.get('localSymbol') or c.get('symbol')}")

    def execDetailsEnd(self, reqId: int) -> None:  # noqa: N802
        if self.verbose:
            print(f"[ibkr] execDetailsEnd reqId={reqId} rows={len(self.exec_rows)}")
        self._exec_end.set()

    # ---- Commission reports (class name/module varies; treat as Any) ----
    def commissionReport(self, commissionReport: Any) -> None:  # noqa: N802
        # commissionReport.execId is the join key
        execId = getattr(commissionReport, "execId", None)
        if execId is None:
            return
        rec = {
            "execId": execId,
            "commission": getattr(commissionReport, "commission", None),
            "currency": getattr(commissionReport, "currency", None),
            "realizedPNL": getattr(commissionReport, "realizedPNL", None),
            "yield": getattr(commissionReport, "yield_", None) if hasattr(commissionReport, "yield_") else getattr(commissionReport, "yield", None),
            "yieldRedemptionDate": getattr(commissionReport, "yieldRedemptionDate", None),
        }
        self.commissions_by_execid[str(execId)] = rec
        if self.verbose:
            print(f"[ibkr] commissionReport execId={execId} commission={rec.get('commission')}")

    # ---- Wait helpers ----
    def wait_ready(self, timeout: float) -> bool:
        return self._ready.wait(timeout)

    def wait_exec_end(self, timeout: float) -> bool:
        return self._exec_end.wait(timeout)


# ----------------------------
# Normalization helpers
# ----------------------------
def _as_float(x: Any) -> Optional[float]:
    if x is None:
        return None
    try:
        return float(x)
    except Exception:
        return None


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


def _best_symbol(contract: Dict[str, Any]) -> str:
    return str(contract.get("localSymbol") or contract.get("symbol") or "").strip().upper()


# ----------------------------
# Commands
# ----------------------------
def cmd_sync(args: argparse.Namespace) -> int:
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

    host = str(args.host or ib.get("host") or "127.0.0.1").strip()
    port = int(args.port or ib.get("port") or 4002)
    clientId = int(args.clientId or ib.get("clientId") or 7)

    days = int(args.days or 14)
    if days <= 0:
        days = 14

    write_mode = _validate_write_mode(getattr(args, "write_mode", "append"))
    also_raw = bool(getattr(args, "also_raw", False))
    verbose = bool(getattr(args, "verbose", False))

    # ---- Connect ----
    app = IBKRApp(verbose=verbose)
    app.connect(host, port, clientId)

    t = threading.Thread(target=app.run, daemon=True)
    t.start()

    if not app.wait_ready(timeout=float(args.timeout_ready)):
        try:
            app.disconnect()
        except Exception:
            pass
        raise SystemExit("❌ IBKR API not ready (nextValidId not received). Check Gateway/TWS, host/port, and API settings.")

    # ---- Request executions since N days ago ----
    since_dt = datetime.now() - timedelta(days=days)
    flt = ExecutionFilter()
    flt.acctCode = account
    flt.time = _ibkr_filter_time(since_dt)

    if verbose:
        print(f"[sync:IBKR] requesting executions acct={account} since={flt.time}")

    try:
        app.reqExecutions(1, flt)
    except Exception as e:
        try:
            app.disconnect()
        except Exception:
            pass
        raise SystemExit(f"❌ reqExecutions failed: {e}")

    # wait for end
    app.wait_exec_end(timeout=float(args.timeout_exec_end))

    # give a short grace window for late commission reports
    time.sleep(float(args.commission_grace))

    try:
        app.disconnect()
    except Exception:
        pass

    # ---- Normalize rows for DuckDB ----
    acct_hash = _ibkr_account_hash(account)
    fetched_at = _utc_now_naive()

    norm: List[Tuple[Any, ...]] = []
    for row in app.exec_rows:
        contract = row.get("contract") or {}
        execu = row.get("execution") or {}
        execId = str(execu.get("execId") or "").strip()
        if not execId:
            continue

        comm = app.commissions_by_execid.get(execId)

        sym = _best_symbol(contract)
        px = _as_float(execu.get("price"))
        side = str(execu.get("side") or "")
        q_signed = _signed_qty(side, execu.get("shares"))
        q = q_signed

        # amount = cashflow sign: BUY -> negative, SELL -> positive
        mult = _multiplier(contract)
        amount = None
        if q is not None and px is not None:
            amount = -float(q) * float(px) * float(mult)

        # txn_date from execution time
        trade_ts = _parse_ibkr_exec_time(execu.get("time"))
        txn_date = trade_ts.date() if trade_ts else None

        payload = {
            "broker": "IBKR",
            "account": account,
            "contract": contract,
            "execution": execu,
            "commission": comm,
        }

        norm.append(
            (
                acct_hash,
                execId,
                fetched_at,
                txn_date,
                "TRADE",
                sym,
                amount,
                q,
                px,
                json.dumps(payload, ensure_ascii=False),
            )
        )

    # ---- Write to ledger (lock protected) ----
    run_id = os.getenv("TGPS_RUN_ID", "")
    step = "ibkr_fills_mgt.sync"
    try:
        with ledger_write_lock(str(ledger), run_id=run_id, step=step):
            con = _connect_attached(ledger)
            try:
                _ensure_broker_transactions_table(con)
                _ensure_broker_transactions_latest_table(con)

                con.execute("BEGIN TRANSACTION;")
                try:
                    # override only affects RAW table window by fetched_at date range
                    deleted = 0
                    if write_mode == "override":
                        d1 = date.today()
                        d0 = d1 - timedelta(days=days)
                        deleted = con.execute(
                            """
                            DELETE FROM ledger.lcl.broker_transactions_raw
                            WHERE account_hash = ?
                              AND txn_type = 'TRADE'
                              AND coalesce(txn_date, cast(fetched_at as date)) BETWEEN ? AND ?
                            """,
                            [acct_hash, d0, d1],
                        ).rowcount or 0
                        if verbose:
                            print(f"[sync:IBKR] override deleted_rows={deleted} window={d0}..{d1}")

                    raw_written = 0
                    latest_upserts = 0

                    write_raw = (write_mode in ("append", "override")) or (write_mode == "upsert" and also_raw)
                    if write_raw and norm:
                        con.executemany(
                            """
                            INSERT INTO ledger.lcl.broker_transactions_raw
                              (account_hash, txn_id, fetched_at, txn_date, txn_type, symbol, amount, quantity, price, txn_json)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            norm,
                        )
                        raw_written = len(norm)

                    if write_mode == "upsert" and norm:
                        con.executemany(
                            """
                            INSERT INTO ledger.lcl.broker_transactions_latest
                              (account_hash, txn_id, last_fetched_at, txn_date, txn_type, symbol, amount, quantity, price, txn_json)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            ON CONFLICT (account_hash, txn_id) DO UPDATE SET
                              last_fetched_at = excluded.last_fetched_at,
                              txn_date        = excluded.txn_date,
                              txn_type        = excluded.txn_type,
                              symbol          = excluded.symbol,
                              amount          = excluded.amount,
                              quantity        = excluded.quantity,
                              price           = excluded.price,
                              txn_json        = excluded.txn_json
                            """,
                            [(r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8], r[9]) for r in norm],
                        )
                        latest_upserts = len(norm)

                    con.execute("COMMIT;")
                except Exception:
                    try:
                        con.execute("ROLLBACK;")
                    except Exception:
                        pass
                    raise

                # print summary (always)
                print(
                    f"[sync:IBKR] account={account} host={host} port={port} clientId={clientId} "
                    f"days={days} write_mode={write_mode} also_raw={also_raw} "
                    f"execs_from_api={len(app.exec_rows)} raw_written={raw_written} latest_upserts={latest_upserts}"
                )

                # show a compact error tail if present
                if app.errors and verbose:
                    tail = app.errors[-5:]
                    print(f"[sync:IBKR] errors_tail(last {len(tail)}):")
                    for e in tail:
                        print("  -", e)

                return 0
            finally:
                con.close()

    except LockHeldError as e:
        raise SystemExit(f"❌ Ledger write lock is held. {e}") from e


# ----------------------------
# CLI
# ----------------------------
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="tgps-user IBKR executions (fills) cache: sync")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("sync", help="Pull IBKR executions via reqExecutions and store into broker_transactions_* tables")
    p.add_argument("--days", type=int, default=14, help="Lookback days for execution filter time (default 14)")
    p.add_argument("--write-mode", default="append", choices=["append", "override", "upsert"], help="append|override|upsert (default append)")
    p.add_argument("--also-raw", action="store_true", help="Only for --write-mode upsert: also append to raw audit table")

    p.add_argument("--account", default="", help="IBKR account code (e.g. DU2679715). If empty, uses lcl.user.yml broker.ibkr.account")
    p.add_argument("--host", default="", help="IBKR Gateway/TWS host (default 127.0.0.1 or config)")
    p.add_argument("--port", type=int, default=0, help="IBKR Gateway/TWS port (default 4002 or config)")
    p.add_argument("--clientId", type=int, default=0, help="IBKR clientId (default 7 or config)")

    p.add_argument("--timeout-ready", type=float, default=5.0, help="Seconds to wait for nextValidId (default 5)")
    p.add_argument("--timeout-exec-end", type=float, default=10.0, help="Seconds to wait for execDetailsEnd (default 10)")
    p.add_argument("--commission-grace", type=float, default=0.5, help="Seconds to wait after execDetailsEnd for late commission reports (default 0.5)")
    p.add_argument("--verbose", action="store_true", help="Verbose IBKR callbacks/logs")
    p.set_defaults(func=cmd_sync)

    return ap


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
