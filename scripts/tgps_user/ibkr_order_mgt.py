#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/tgps_user/ibkr_order_mgt.py
Version: 0.1.0 (2026-01-22, SGT)

Purpose
-------
IBKR open-order + status management CLI for tgps-user.

This is the IBKR analog of Schwab order management tooling:
- Pull open orders (reqAllOpenOrders or reqOpenOrders)
- Cache snapshots in DuckDB
- Cancel by orderId

Tables
------
Writes:
- ledger.lcl.broker_orders_raw
- ledger.lcl.broker_orders_latest

Account identity
----------------
account_hash = sha256("IBKR:<account>")

Run from repo root:
  cd ~/.../TradersGPS
  python -m scripts.tgps_user.ibkr_order_mgt sync --write-mode upsert --also-raw
  python -m scripts.tgps_user.ibkr_order_mgt orders --source latest
  python -m scripts.tgps_user.ibkr_order_mgt cancel --order-id 12345
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
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

from ibapi.client import EClient  # type: ignore
from ibapi.wrapper import EWrapper  # type: ignore


# ----------------------------
# Helpers
# ----------------------------
def _utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _ibkr_account_hash(account: str) -> str:
    return _sha256(f"IBKR:{(account or '').strip()}")


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
    return (broker.get("ibkr", {}) or cfg.get("ibkr", {}) or {})


def _connect_attached(ledger: Path) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(":memory:")
    con.execute(f"ATTACH '{ledger.as_posix()}' AS ledger;")
    con.execute("CREATE SCHEMA IF NOT EXISTS ledger.lcl;")
    return con


def _validate_write_mode(s: str) -> str:
    m = (s or "append").strip().lower()
    if m not in ("append", "override", "upsert"):
        raise SystemExit("Invalid --write-mode. Use: append | override | upsert")
    return m


def _validate_source(s: str) -> str:
    m = (s or "latest").strip().lower()
    if m not in ("raw", "latest"):
        raise SystemExit("Invalid --source. Use: raw | latest")
    return m


# ----------------------------
# DuckDB schema
# ----------------------------
def _ensure_broker_orders_raw(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS ledger.lcl.broker_orders_raw (
          account_hash  VARCHAR,
          order_id      VARCHAR,
          fetched_at    TIMESTAMP,
          status        VARCHAR,
          symbol        VARCHAR,
          qty           DOUBLE,
          price         DOUBLE,
          order_json    VARCHAR
        );
        """
    )
    try:
        con.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_broker_orders_raw ON ledger.lcl.broker_orders_raw(account_hash, order_id, fetched_at);"
        )
    except Exception:
        pass


def _ensure_broker_orders_latest(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS ledger.lcl.broker_orders_latest (
          account_hash     VARCHAR,
          order_id         VARCHAR,
          last_fetched_at  TIMESTAMP,
          status           VARCHAR,
          symbol           VARCHAR,
          qty              DOUBLE,
          price            DOUBLE,
          order_json       VARCHAR
        );
        """
    )
    try:
        con.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_broker_orders_latest ON ledger.lcl.broker_orders_latest(account_hash, order_id);"
        )
    except Exception:
        pass


# ----------------------------
# IBKR app
# ----------------------------
class IBKROrderApp(EWrapper, EClient):
    def __init__(self, *, verbose: bool = False):
        EClient.__init__(self, self)
        self.verbose = verbose

        self._ready = threading.Event()
        self._open_end = threading.Event()

        self.errors: List[Dict[str, Any]] = []
        self.orders: Dict[int, Dict[str, Any]] = {}
        self.status_by_orderid: Dict[int, Dict[str, Any]] = {}

    def nextValidId(self, orderId: int) -> None:  # noqa: N802
        if self.verbose:
            print(f"[ibkr] nextValidId={orderId}")
        self._ready.set()

    def error(self, reqId: int, *args: Any) -> None:  # noqa: N802
        # Accept multiple signatures across API versions.
        errorTime = None
        errorCode = None
        errorMsg = None
        advanced = None

        if len(args) == 2:
            errorCode, errorMsg = args[0], args[1]
        elif len(args) == 3:
            a0, a1, a2 = args
            if isinstance(a1, int) or (isinstance(a1, str) and str(a1).isdigit()):
                errorTime, errorCode, errorMsg = a0, a1, a2
            else:
                errorCode, errorMsg, advanced = a0, a1, a2
        elif len(args) >= 4:
            errorTime, errorCode, errorMsg = args[0], args[1], args[2]
            advanced = args[3]

        rec = {
            "reqId": reqId,
            "errorTime": errorTime,
            "errorCode": errorCode,
            "errorMsg": errorMsg,
            "advancedOrderRejectJson": advanced,
        }
        self.errors.append(rec)
        if self.verbose:
            print(f"[ibkr:error] {rec}")

    def openOrder(self, orderId: int, contract: Any, order: Any, orderState: Any) -> None:  # noqa: N802
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
        o = {
            "action": getattr(order, "action", None),
            "totalQuantity": getattr(order, "totalQuantity", None),
            "orderType": getattr(order, "orderType", None),
            "lmtPrice": getattr(order, "lmtPrice", None),
            "auxPrice": getattr(order, "auxPrice", None),
            "tif": getattr(order, "tif", None),
            "account": getattr(order, "account", None),
            "permId": getattr(order, "permId", None),
            "clientId": getattr(order, "clientId", None),
        }
        st = {
            "status": getattr(orderState, "status", None),
            "warningText": getattr(orderState, "warningText", None),
        }
        payload = {"contract": c, "order": o, "orderState": st}
        self.orders[int(orderId)] = payload
        if self.verbose:
            sym = (c.get("localSymbol") or c.get("symbol") or "")
            print(f"[ibkr] openOrder orderId={orderId} sym={sym} status={st.get('status')}")

    def orderStatus(  # noqa: N802
        self,
        orderId: int,
        status: str,
        filled: float,
        remaining: float,
        avgFillPrice: float,
        permId: int,
        parentId: int,
        lastFillPrice: float,
        clientId: int,
        whyHeld: str,
        mktCapPrice: float,
    ) -> None:
        self.status_by_orderid[int(orderId)] = {
            "status": status,
            "filled": filled,
            "remaining": remaining,
            "avgFillPrice": avgFillPrice,
            "lastFillPrice": lastFillPrice,
            "permId": permId,
            "clientId": clientId,
            "whyHeld": whyHeld,
            "mktCapPrice": mktCapPrice,
        }
        if self.verbose:
            print(f"[ibkr] orderStatus orderId={orderId} status={status} filled={filled} remaining={remaining}")

    def openOrderEnd(self) -> None:  # noqa: N802
        if self.verbose:
            print(f"[ibkr] openOrderEnd orders={len(self.orders)}")
        self._open_end.set()

    def wait_ready(self, timeout: float) -> bool:
        return self._ready.wait(timeout)

    def wait_open_end(self, timeout: float) -> bool:
        return self._open_end.wait(timeout)


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

    verbose = bool(args.verbose)
    all_open = bool(args.all_open)

    write_mode = _validate_write_mode(getattr(args, "write_mode", "append"))
    also_raw = bool(getattr(args, "also_raw", False))

    app = IBKROrderApp(verbose=verbose)
    app.connect(host, port, clientId)
    t = threading.Thread(target=app.run, daemon=True)
    t.start()

    if not app.wait_ready(timeout=float(args.timeout_ready)):
        try:
            app.disconnect()
        except Exception:
            pass
        raise SystemExit("❌ IBKR API not ready (nextValidId not received). Check Gateway/TWS + API settings.")

    # request open orders
    try:
        if all_open:
            app.reqAllOpenOrders()
        else:
            app.reqOpenOrders()
    except Exception as e:
        try:
            app.disconnect()
        except Exception:
            pass
        raise SystemExit(f"❌ reqOpenOrders failed: {e}")

    app.wait_open_end(timeout=float(args.timeout_open_end))
    time.sleep(0.25)

    try:
        app.disconnect()
    except Exception:
        pass

    acct_hash = _ibkr_account_hash(account)
    fetched_at = _utc_now_naive()

    # normalize rows
    norm: List[Tuple[Any, ...]] = []
    for oid, payload in app.orders.items():
        c = payload.get("contract") or {}
        o = payload.get("order") or {}
        st = payload.get("orderState") or {}
        st2 = app.status_by_orderid.get(int(oid), {}) or {}

        sym = str(c.get("localSymbol") or c.get("symbol") or "").strip().upper()
        qty = None
        try:
            qty = float(o.get("totalQuantity")) if o.get("totalQuantity") is not None else None
        except Exception:
            qty = None

        # price: prefer lmtPrice if set
        px = None
        try:
            lp = o.get("lmtPrice")
            px = float(lp) if lp is not None and float(lp) > 0 else None
        except Exception:
            px = None

        status = str(st2.get("status") or st.get("status") or "").strip().upper()

        full_payload = {
            "broker": "IBKR",
            "account": account,
            "orderId": oid,
            "contract": c,
            "order": o,
            "orderState": st,
            "orderStatus": st2,
        }

        norm.append(
            (
                acct_hash,
                str(oid),
                fetched_at,
                status,
                sym,
                qty,
                px,
                _json_dumps(full_payload),

            )
        )

    run_id = os.getenv("TGPS_RUN_ID", "")
    step = "ibkr_order_mgt.sync"

    try:
        with ledger_write_lock(str(ledger), run_id=run_id, step=step):
            con = _connect_attached(ledger)
            try:
                _ensure_broker_orders_raw(con)
                _ensure_broker_orders_latest(con)

                con.execute("BEGIN TRANSACTION;")
                try:
                    deleted = 0
                    if write_mode == "override":
                        deleted = con.execute(
                            "DELETE FROM ledger.lcl.broker_orders_raw WHERE account_hash = ?",
                            [acct_hash],
                        ).rowcount or 0

                    raw_written = 0
                    latest_upserts = 0

                    write_raw = (write_mode in ("append", "override")) or (write_mode == "upsert" and also_raw)
                    if write_raw and norm:
                        con.executemany(
                            """
                            INSERT INTO ledger.lcl.broker_orders_raw
                              (account_hash, order_id, fetched_at, status, symbol, qty, price, order_json)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            norm,
                        )
                        raw_written = len(norm)

                    if write_mode == "upsert" and norm:
                        con.executemany(
                            """
                            INSERT INTO ledger.lcl.broker_orders_latest
                              (account_hash, order_id, last_fetched_at, status, symbol, qty, price, order_json)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            ON CONFLICT (account_hash, order_id) DO UPDATE SET
                              last_fetched_at = excluded.last_fetched_at,
                              status          = excluded.status,
                              symbol          = excluded.symbol,
                              qty             = excluded.qty,
                              price           = excluded.price,
                              order_json      = excluded.order_json
                            """,
                            [(r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7]) for r in norm],
                        )
                        latest_upserts = len(norm)

                    con.execute("COMMIT;")
                except Exception:
                    try:
                        con.execute("ROLLBACK;")
                    except Exception:
                        pass
                    raise

                print(
                    f"[sync:IBKR:orders] account={account} host={host} port={port} clientId={clientId} "
                    f"all_open={all_open} write_mode={write_mode} also_raw={also_raw} "
                    f"orders_from_api={len(app.orders)} raw_written={raw_written} latest_upserts={latest_upserts}"
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

    cfg = _load_user_yml(_cfg_path(user_root))
    ib = _get_ibkr_cfg(cfg)
    account = str(args.account or ib.get("account") or "").strip()
    if not account:
        raise SystemExit("❌ Missing IBKR account. Use --account DUxxxx or set broker.ibkr.account in tgps-user/config/lcl.user.yml")

    acct_hash = _ibkr_account_hash(account)
    source = _validate_source(str(args.source or "latest"))

    con = _connect_attached(ledger)
    try:
        if source == "latest":
            _ensure_broker_orders_latest(con)
            rows = con.execute(
                """
                SELECT last_fetched_at, order_id, status, symbol, qty, price
                FROM ledger.lcl.broker_orders_latest
                WHERE account_hash = ?
                ORDER BY last_fetched_at DESC
                LIMIT ?
                """,
                [acct_hash, int(args.limit)],
            ).fetchall()
            print(f"[orders:IBKR] source=latest account={account} rows={len(rows)}")
        else:
            _ensure_broker_orders_raw(con)
            cutoff = _utc_now_naive() - timedelta(days=int(args.days))
            rows = con.execute(
                """
                SELECT fetched_at, order_id, status, symbol, qty, price
                FROM ledger.lcl.broker_orders_raw
                WHERE account_hash = ?
                  AND fetched_at >= ?
                QUALIFY row_number() OVER (PARTITION BY order_id ORDER BY fetched_at DESC) = 1
                ORDER BY fetched_at DESC
                LIMIT ?
                """,
                [acct_hash, cutoff, int(args.limit)],
            ).fetchall()
            print(f"[orders:IBKR] source=raw account={account} rows={len(rows)} (latest snapshot per order_id)")

        for r in rows:
            print(" -", " | ".join("" if v is None else str(v) for v in r))
        return 0
    finally:
        con.close()


def cmd_cancel(args: argparse.Namespace) -> int:
    cfg = _load_user_yml(_cfg_path(_user_root(_repo_root())))
    ib = _get_ibkr_cfg(cfg)

    account = str(args.account or ib.get("account") or "").strip()
    if not account:
        raise SystemExit("❌ Missing IBKR account. Use --account DUxxxx or set broker.ibkr.account in tgps-user/config/lcl.user.yml")

    host = str(args.host or ib.get("host") or "127.0.0.1").strip()
    port = int(args.port or ib.get("port") or 4002)
    clientId = int(args.clientId or ib.get("clientId") or 7)

    order_id = int(args.order_id)

    app = IBKROrderApp(verbose=bool(args.verbose))
    app.connect(host, port, clientId)
    t = threading.Thread(target=app.run, daemon=True)
    t.start()

    if not app.wait_ready(timeout=float(args.timeout_ready)):
        try:
            app.disconnect()
        except Exception:
            pass
        raise SystemExit("❌ IBKR API not ready (nextValidId not received).")

    try:
        app.cancelOrder(order_id)
        time.sleep(float(args.cancel_grace))
    finally:
        try:
            app.disconnect()
        except Exception:
            pass

    print(f"[cancel:IBKR] account={account} order_id={order_id} sent=True host={host} port={port} clientId={clientId}")
    return 0


# ----------------------------
# CLI
# ----------------------------
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="tgps-user IBKR order management (sync/orders/cancel)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("sync", help="Pull IBKR open orders and cache into DuckDB")
    p.add_argument("--write-mode", default="append", choices=["append", "override", "upsert"], help="append|override|upsert (default append)")
    p.add_argument("--also-raw", action="store_true", help="Only for --write-mode upsert: also append to raw audit table")
    p.add_argument("--all-open", action="store_true", help="Use reqAllOpenOrders (includes other clientIds). Default false -> reqOpenOrders only.")
    p.add_argument("--account", default="", help="IBKR account (DUxxxx). If empty, uses config.")
    p.add_argument("--host", default="", help="Host (default 127.0.0.1 or config)")
    p.add_argument("--port", type=int, default=0, help="Port (default 4002 or config)")
    p.add_argument("--clientId", type=int, default=0, help="clientId (default 7 or config)")
    p.add_argument("--timeout-ready", type=float, default=5.0, help="Seconds to wait for nextValidId (default 5)")
    p.add_argument("--timeout-open-end", type=float, default=10.0, help="Seconds to wait for openOrderEnd (default 10)")
    p.add_argument("--verbose", action="store_true", help="Verbose IBKR callbacks/logs")
    p.set_defaults(func=cmd_sync)

    p = sub.add_parser("orders", help="List cached orders")
    p.add_argument("--account", default="", help="IBKR account (DUxxxx). If empty, uses config.")
    p.add_argument("--source", default="latest", choices=["latest", "raw"], help="Read from latest (default) or raw")
    p.add_argument("--days", type=int, default=7, help="(raw only) lookback days (default 7)")
    p.add_argument("--limit", type=int, default=200, help="Max rows (default 200)")
    p.set_defaults(func=cmd_orders)

    p = sub.add_parser("cancel", help="Cancel an order by orderId")
    p.add_argument("--order-id", required=True, help="IBKR orderId (integer)")
    p.add_argument("--account", default="", help="IBKR account (DUxxxx). If empty, uses config.")
    p.add_argument("--host", default="", help="Host (default 127.0.0.1 or config)")
    p.add_argument("--port", type=int, default=0, help="Port (default 4002 or config)")
    p.add_argument("--clientId", type=int, default=0, help="clientId (default 7 or config)")
    p.add_argument("--timeout-ready", type=float, default=5.0, help="Seconds to wait for nextValidId (default 5)")
    p.add_argument("--cancel-grace", type=float, default=0.5, help="Seconds to wait after cancelOrder (default 0.5)")
    p.add_argument("--verbose", action="store_true", help="Verbose IBKR callbacks/logs")
    p.set_defaults(func=cmd_cancel)

    return ap


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
