#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/tgps_user/ibkr_sellput_queue.py
Version: 0.3.1
Updated: 2026-01-22 (SGT)

Purpose
-------
Place/cancel IBKR sell-put orders for rows where:
  - User Action == EXECUTE
  - Submit == YES   (unless --ignore-submit)

Key design (prevents duplicates across regenerated queue_edit.xlsx)
------------------------------------------------------------------
We use 3 identities:

1) base_key   (broker-agnostic, stable "find/cancel" identity)
   MODULE|TICKER|EXPIRY|RIGHT|STRIKE

2) intent_key (your rule: qty is part of "new order" identity)
   base_key + qty

3) payload_hash (exact order parameters identity)
   qty + entry limit + tif + exits + stop/tp + etc (broker-agnostic plan params)

IBKR orderRef encodes:
  TGPS:{base_id}:{payload_id}
where:
  base_id    = sha256(acct|base_key)[:12]     (account-scoped)
  payload_id = payload_hash[:8]              (exact params)

Cancel & Replace rule
---------------------
If broker has open orders for base_id:
  - if payload_id matches: skip (already open)
  - else: cancel all open for base_id then submit new bracket

Anti-tamper (key columns)
-------------------------
If queue_edit contains base_key / intent_key / payload_hash and they do NOT match
recomputed values from the row (Ticker/Expiry/Strike/Qty + plan fields) -> BLOCK.

Plan mode behavior
------------------
By default, "plan" does NOT connect to IBKR (prevents hanging on dry-run).
Use --connect-on-plan if you want broker open-order replace/skip decisions shown.

Commands
--------
Dry run (no IBKR connect):
  python -m scripts.tgps_user.ibkr_sellput_queue plan

Dry run + connect (show would-replace/skip decisions):
  python -m scripts.tgps_user.ibkr_sellput_queue plan --connect-on-plan

Execute (cancel & replace automatically if needed):
  python -m scripts.tgps_user.ibkr_sellput_queue plan --execute

Cancel matching orders (from current eligible queue rows):
  python -m scripts.tgps_user.ibkr_sellput_queue cancel

Unblock stale ledger rows (safe: only if broker has no open for base_id):
  python -m scripts.tgps_user.ibkr_sellput_queue unblock
  python -m scripts.tgps_user.ibkr_sellput_queue unblock --apply
"""

import argparse
import hashlib
import json
import os
import time
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import pandas as pd
import yaml

from ibapi.client import EClient
from ibapi.wrapper import EWrapper
from ibapi.contract import Contract
from ibapi.order import Order

try:
    from ibapi.order_cancel import OrderCancel  # newer ibapi
except Exception:
    OrderCancel = None

from common.duckdb_ledger import connect_ledger, ensure_schema
from common.order_keys import compute_base_key, compute_intent_key, compute_payload_hash, payload_id_from_payload_hash


# ----------------------------
# Repo + config
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


def _load_user_yml(p: Path) -> Dict[str, Any]:
    if not p.exists():
        raise SystemExit(f"❌ Missing config: {p}")
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise SystemExit(f"❌ Config must parse to a mapping/dict: {p}")
    return data


def _deep_get(d: Dict[str, Any], keys: List[str], default: Any = None) -> Any:
    cur: Any = d
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
    return default if cur is None else cur


def _queue_dir_and_glob(cfg: Dict[str, Any], module: str) -> Tuple[Path, str]:
    qdir = _deep_get(cfg, ["modules", module, "paths", "queue_dir"], "")
    glob_pat = _deep_get(cfg, ["modules", module, "paths", "queue_edit_glob"], "")

    if not glob_pat:
        glob_pat = "*_sellput_queue_edit.xlsx"

    repo = _repo_root()
    user_root = _user_root(repo)
    default_dir = user_root / "output" / "sellput"

    qdir_path = Path(str(qdir)).expanduser() if str(qdir).strip() else default_dir
    return qdir_path, str(glob_pat)


def _latest_file(folder: Path, glob_pat: str) -> Path:
    if not folder.exists():
        raise SystemExit(f"❌ queue_dir not found: {folder}")
    cands = []
    for p in folder.glob(glob_pat):
        if p.name.startswith("~$"):
            continue
        if p.is_file():
            cands.append(p)
    cands.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    if not cands:
        raise SystemExit(f"❌ No files matched {glob_pat} in: {folder}")
    return cands[0]


def _ibkr_defaults(cfg: Dict[str, Any]) -> Dict[str, Any]:
    b = cfg.get("broker") or {}
    ib = b.get("ibkr") or {}

    env = str(ib.get("env") or "paper").strip().lower()
    if env not in ("paper", "live"):
        env = "paper"

    host = str(ib.get("host") or "127.0.0.1").strip() or "127.0.0.1"

    ports = ib.get("ports") or {}
    port = ib.get("port")
    if port is None:
        try:
            port = int(ports.get(env)) if isinstance(ports, dict) and ports.get(env) is not None else None
        except Exception:
            port = None
    try:
        port = int(port) if port is not None else (4002 if env == "paper" else 4001)
    except Exception:
        port = 4002 if env == "paper" else 4001

    try:
        client_id = int(ib.get("client_id") or 7)
    except Exception:
        client_id = 7

    return {"env": env, "host": host, "port": port, "client_id": client_id}


def _ledger_db_path(cfg: Dict[str, Any], user_root: Path) -> Path:
    p = _deep_get(cfg, ["ledger", "db_path"], "")
    if str(p).strip():
        return Path(str(p)).expanduser().resolve()
    return (user_root / "ledger" / "lcl.ledger.duckdb").resolve()


# ----------------------------
# Parsing helpers
# ----------------------------
def _parse_expiry_yyyymmdd(x) -> str:
    ts = pd.to_datetime(x)
    return ts.strftime("%Y%m%d")


def _parse_expiry_iso(x) -> str:
    ts = pd.to_datetime(x)
    return ts.strftime("%Y-%m-%d")


def _tif_from_duration(x: str) -> str:
    s = str(x or "").strip().upper()
    if s in ("GOOD_TILL_CANCEL", "GTC"):
        return "GTC"
    if s in ("DAY",):
        return "DAY"
    return "GTC"


def _float_or_none(v):
    try:
        if pd.isna(v):
            return None
    except Exception:
        pass
    try:
        if v in ("", None):
            return None
    except Exception:
        pass
    try:
        return float(v)
    except Exception:
        return None


def _sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _short_id(hex_sha: str, n: int) -> str:
    return str(hex_sha)[:n]


def _col_get(r: pd.Series, *names: str, default: str = "") -> str:
    for n in names:
        if n in r.index:
            return _cell_text(r.get(n))
    return default



def _base_id_for_account(acct: str, base_key: str, n: int = 12) -> str:
    acct_norm = str(acct or "").strip()
    return _short_id(_sha256_text(f"{acct_norm}|{base_key}"), n)

def _cell_text(v) -> str:
    if v is None:
        return ""
    try:
        if pd.isna(v):
            return ""
    except Exception:
        pass
    s = str(v).strip()
    return "" if s.lower() == "nan" else s

# ----------------------------
# Keying (queue-compatible)
# ----------------------------
def _plan_params_from_row(r: pd.Series, *, module: str, ticker: str, expiry_iso: str, right: str, strike: float, qty: int) -> Dict[str, Any]:
    return {
        "module": module,
        "ticker": ticker,
        "expiry": expiry_iso,
        "right": right,
        "strike": float(strike),
        "qty": int(qty),
        "entry_order_type": str(r.get("Entry Order Type") or "LIMIT").strip().upper(),
        "entry_limit": _float_or_none(r.get("Limit Price Override")),
        "duration": str(r.get("Duration") or "").strip().upper(),
        "attach_exit": str(r.get("Attach Exit") or "").strip().upper(),
        "exit_mode": str(r.get("Exit Mode") or "").strip().upper(),
        "tp_limit": _float_or_none(r.get("TP Limit")),
        "stop_type": str(r.get("Stop Type") or "").strip().upper(),
        "stop_price": _float_or_none(r.get("Stop Price")),
        "stop_limit_price": _float_or_none(r.get("Stop Limit Price")),
    }


def _ensure_and_validate_key_cols(df_elig: pd.DataFrame, *, module: str, right: str = "P") -> pd.DataFrame:
    df = df_elig.copy()

    for c in ("base_key", "intent_key", "payload_hash"):
        if c not in df.columns:
            df[c] = ""

    for i, r in df.iterrows():
        ticker = _cell_text(r.get("Ticker")).upper()
        expiry_iso = _parse_expiry_iso(r.get("Expiry"))
        strike = float(r.get("Strike Found"))

        qty_raw = r.get("Qty", 1)
        try:
            qty = int(float(qty_raw)) if qty_raw not in (None, "") else 1
        except Exception:
            qty = 1
        qty = max(qty, 1)

        expected_base = compute_base_key(module=module, ticker=ticker, expiry_iso=expiry_iso, right=right, strike=strike)
        expected_intent = compute_intent_key(base_key=expected_base, qty=qty)

        pp = _plan_params_from_row(r, module=module, ticker=ticker, expiry_iso=expiry_iso, right=right, strike=strike, qty=qty)
        expected_ph = compute_payload_hash(pp)

        file_base = _cell_text(r.get("base_key"))
        file_intent = _cell_text(r.get("intent_key"))
        file_ph = _cell_text(r.get("payload_hash"))

        if file_base and file_base != expected_base:
            print(f"[WARN] base_key differs; overwriting. ticker={ticker} file={file_base} exp={expected_base}", flush=True)
        if file_intent and file_intent != expected_intent:
            print(f"[WARN] intent_key differs; overwriting. ticker={ticker}", flush=True)
        if file_ph and file_ph != expected_ph:
            print(f"[WARN] payload_hash differs; overwriting. ticker={ticker}", flush=True)

        df.at[i, "base_key"] = expected_base
        df.at[i, "intent_key"] = expected_intent
        df.at[i, "payload_hash"] = expected_ph

    return df



# ----------------------------
# IBKR contract + orders
# ----------------------------
def mk_put_contract(symbol: str, expiry_yyyymmdd: str, strike: float) -> Contract:
    c = Contract()
    c.symbol = symbol.upper()
    c.secType = "OPT"
    c.exchange = "SMART"
    c.currency = "USD"
    c.lastTradeDateOrContractMonth = expiry_yyyymmdd
    c.strike = float(strike)
    c.right = "P"
    c.multiplier = "100"
    return c


def mk_order_sell_lmt(qty: int, limit: float, tif: str, order_ref: str, transmit: bool) -> Order:
    o = Order()
    o.action = "SELL"
    o.orderType = "LMT"
    o.totalQuantity = int(qty)
    o.lmtPrice = float(limit)
    o.tif = tif
    o.orderRef = order_ref
    o.transmit = transmit
    return o


def mk_order_buy_lmt(qty: int, limit: float, tif: str, parent_id: int, oca: str, order_ref: str, transmit: bool) -> Order:
    o = Order()
    o.action = "BUY"
    o.orderType = "LMT"
    o.totalQuantity = int(qty)
    o.lmtPrice = float(limit)
    o.tif = tif
    o.parentId = int(parent_id)
    o.ocaGroup = oca
    o.ocaType = 1
    o.orderRef = order_ref
    o.transmit = transmit
    return o


def mk_order_buy_stp_mkt(qty: int, stop_price: float, tif: str, parent_id: int, oca: str, order_ref: str, transmit: bool) -> Order:
    o = Order()
    o.action = "BUY"
    o.orderType = "STP"
    o.totalQuantity = int(qty)
    o.auxPrice = float(stop_price)
    o.tif = tif
    o.parentId = int(parent_id)
    o.ocaGroup = oca
    o.ocaType = 1
    o.orderRef = order_ref
    o.transmit = transmit
    return o


def mk_order_buy_stp_lmt(qty: int, stop_price: float, stop_lmt_price: float, tif: str, parent_id: int, oca: str, order_ref: str, transmit: bool) -> Order:
    o = Order()
    o.action = "BUY"
    o.orderType = "STP LMT"
    o.totalQuantity = int(qty)
    o.auxPrice = float(stop_price)
    o.lmtPrice = float(stop_lmt_price)
    o.tif = tif
    o.parentId = int(parent_id)
    o.ocaGroup = oca
    o.ocaType = 1
    o.orderRef = order_ref
    o.transmit = transmit
    return o


def mk_order_ref(base_id: str, payload_id: str) -> str:
    return f"TGPS:{base_id}:{payload_id}"


def parse_order_ref(order_ref: str) -> Tuple[str, str]:
    s = str(order_ref or "").strip()
    if not s.startswith("TGPS:"):
        return ("", "")
    parts = s.split(":")
    if len(parts) >= 3:
        return (parts[1], parts[2])
    if len(parts) == 2:
        return (parts[1], "")
    return ("", "")


def print_plan_table(df_elig: pd.DataFrame, *, will_execute: bool) -> None:
    show_cols = []
    for c in [
        "Ticker", "Expiry", "Strike Found", "Qty",
        "Entry Order Type", "Duration",
        "Limit Price Override", "Bid", "Ask", "Mid", "Last",
        "Attach Exit", "Exit Mode", "TP Limit", "Stop Type", "Stop Price", "Stop Limit Price",
        "Submit", "row_hash",
        "base_key", "intent_key", "payload_hash",
    ]:
        if c in df_elig.columns:
            show_cols.append(c)

    out = df_elig[show_cols].copy() if show_cols else df_elig.copy()
    out.insert(0, "n", range(1, len(out) + 1))
    hdr = "[ORDER PLAN — WILL EXECUTE]" if will_execute else "[ORDER PLAN — DRY RUN]"
    print("\n" + hdr, flush=True)
    print(out.to_string(index=False), flush=True)


# ----------------------------
# IBKR app state
# ----------------------------
@dataclass
class OpenOrderRow:
    orderId: int
    orderRef: str
    status: str
    symbol: str
    secType: str
    permId: int = 0


@dataclass
class StatusRow:
    orderId: int
    status: str
    permId: int


@dataclass
class State:
    next_order_id: Optional[int] = None
    managed_accounts: str = ""
    errors: List[Tuple[int, int, str]] = field(default_factory=list)
    open_orders: List[OpenOrderRow] = field(default_factory=list)
    status_by_id: Dict[int, StatusRow] = field(default_factory=dict)


class IBQueueApp(EWrapper, EClient):
    def __init__(self, verbose: bool):
        EClient.__init__(self, self)
        self.verbose = verbose
        self.st = State()
        self.ev_nextid = threading.Event()
        self.ev_accounts = threading.Event()
        self.ev_openorders_end = threading.Event()
        self.ev_status = threading.Event()

    def _p(self, msg: str):
        print(msg, flush=True)

    def log(self, msg: str):
        if self.verbose:
            self._p(msg)

    def error(self, reqId: int, *args):
        errorTime = None
        errorCode = None
        errorString = ""
        advanced = ""

        if len(args) == 2:
            errorCode, errorString = args
        elif len(args) == 3:
            errorCode, errorString, advanced = args
        elif len(args) == 4:
            errorTime, errorCode, errorString, advanced = args
        else:
            errorString = f"Unexpected error() args: {args}"

        try:
            ec_int = int(errorCode) if errorCode is not None else -1
        except Exception:
            ec_int = -1

        msg = str(errorString)
        self.st.errors.append((reqId, ec_int, msg))
        self._p(f"[IBKR:error] reqId={reqId} time={errorTime} code={errorCode} msg={msg}")
        if advanced:
            self._p(f"[IBKR:error] advancedOrderRejectJson={advanced}")

    def managedAccounts(self, accountsList: str):
        self.st.managed_accounts = accountsList
        self.ev_accounts.set()
        self.log(f"[IBKR:managedAccounts] {accountsList}")

    def nextValidId(self, orderId: int):
        self.st.next_order_id = int(orderId)
        self.ev_nextid.set()
        self.log(f"[IBKR:nextValidId] {orderId}")

    def openOrder(self, orderId: int, contract: Contract, order: Order, orderState):
        ref = getattr(order, "orderRef", "") or ""
        status = getattr(orderState, "status", "") or ""
        perm_id = int(getattr(orderState, "permId", 0) or 0)
        self.st.open_orders.append(
            OpenOrderRow(
                orderId=int(orderId),
                orderRef=str(ref),
                status=str(status),
                symbol=str(getattr(contract, "symbol", "")),
                secType=str(getattr(contract, "secType", "")),
                permId=perm_id,
            )
        )
        self.log(f"[IBKR:openOrder] id={orderId} {contract.symbol} {contract.secType} ref={ref} status={status} permId={perm_id}")

    def openOrderEnd(self):
        self.ev_openorders_end.set()
        self.log("[IBKR:openOrderEnd]")

    def orderStatus(
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
    ):
        st = str(status or "")
        pid = int(permId or 0)
        self.st.status_by_id[int(orderId)] = StatusRow(orderId=int(orderId), status=st, permId=pid)
        self.ev_status.set()
        self.log(f"[IBKR:orderStatus] orderId={orderId} status={st} permId={pid} filled={filled} remaining={remaining}")

    def _cancel_order(self, order_id: int) -> None:
        if OrderCancel is not None:
            try:
                self.cancelOrder(int(order_id), OrderCancel())
                return
            except TypeError:
                pass
        self.cancelOrder(int(order_id))

    def await_status(self, order_ids: List[int], timeout: float = 8.0) -> List[StatusRow]:
        want = set(int(x) for x in order_ids)
        t0 = time.time()
        while time.time() - t0 < timeout:
            have = set(self.st.status_by_id.keys())
            if want.issubset(have):
                break
            self.ev_status.wait(timeout=0.5)
            self.ev_status.clear()
        out: List[StatusRow] = []
        for oid in order_ids:
            s = self.st.status_by_id.get(int(oid))
            if s:
                out.append(s)
        return out


# ----------------------------
# Queue loading
# ----------------------------
def load_eligible_rows(xlsx_path: str, sheet: str, *, ignore_submit: bool) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = pd.read_excel(xlsx_path, sheet_name=sheet)
    df.columns = [str(c).strip() for c in df.columns]

    if "User Action" not in df.columns:
        raise SystemExit("❌ Missing required column: 'User Action'")
    if "Ticker" not in df.columns or "Expiry" not in df.columns or "Strike Found" not in df.columns:
        raise SystemExit("❌ Missing required columns: Ticker / Expiry / Strike Found")

    df["User Action"] = df["User Action"].astype(str).str.upper().str.strip()

    if "Submit" not in df.columns:
        df["Submit"] = ""
    df["Submit"] = df["Submit"].astype(str).str.upper().str.strip()

    eligible = (df["User Action"] == "EXECUTE")
    if not ignore_submit:
        eligible = eligible & (df["Submit"] == "YES")

    elig_df = df[eligible].copy()
    return df, elig_df


def print_eligibility_report(df_all: pd.DataFrame, df_elig: pd.DataFrame, *, ignore_submit: bool) -> None:
    total = len(df_all)
    exec_cnt = int((df_all["User Action"] == "EXECUTE").sum())
    sub_yes = int(((df_all["User Action"] == "EXECUTE") & (df_all["Submit"] == "YES")).sum())

    print("[eligibility]", flush=True)
    print(f"  rows_total:            {total}", flush=True)
    print(f"  rows_action=EXECUTE:   {exec_cnt}", flush=True)
    if ignore_submit:
        print("  submit_filter:         IGNORED (--ignore-submit)", flush=True)
        print(f"  rows_eligible:         {len(df_elig)}", flush=True)
    else:
        print("  submit_filter:         Submit must be YES", flush=True)
        print(f"  rows_execute_submitYES:{sub_yes}", flush=True)
        print(f"  rows_eligible:         {len(df_elig)}", flush=True)

    if len(df_elig) == 0:
        ua = df_all["User Action"].value_counts(dropna=False).head(10)
        sb = df_all["Submit"].value_counts(dropna=False).head(10)
        print("\n[why none eligible]", flush=True)
        print("  User Action counts:", dict(ua), flush=True)
        print("  Submit counts:", dict(sb), flush=True)


def _resolve_queue_path(args) -> Path:
    if args.queue:
        p = Path(args.queue).expanduser().resolve()
        if not p.exists():
            raise SystemExit(f"❌ Queue not found: {p}")
        return p

    repo = _repo_root()
    user_root = _user_root(repo)
    cfg = _load_user_yml(Path(args.user_yml).expanduser().resolve()) if args.user_yml else _load_user_yml(_cfg_path(user_root))
    qdir, glob_pat = _queue_dir_and_glob(cfg, args.module)
    return _latest_file(qdir, glob_pat)


def _effective_conn(args, cfg: Dict[str, Any]) -> Dict[str, Any]:
    d = _ibkr_defaults(cfg)

    env = (args.env or d["env"]).strip().lower()
    if env not in ("paper", "live"):
        env = d["env"]

    host = args.host or d["host"]
    port = int(args.port) if args.port else d["port"]
    client_id = int(args.client_id) if args.client_id is not None else d["client_id"]

    return {"env": env, "host": host, "port": port, "client_id": client_id}


def _enforce_live_safety(conn: Dict[str, Any], args) -> None:
    if conn["env"] == "live" and not args.live:
        raise SystemExit("❌ IBKR env=live selected. You must pass --live to proceed (safety guard).")


# ----------------------------
# Ledger helpers (IBKR)
# ----------------------------
FINAL_STATUSES = {"FILLED", "CANCELLED", "REJECTED", "ERROR"}


def _ensure_order_submissions_table(con) -> None:
    ensure_schema(con, schema="lcl", catalog="ledger")
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS ledger.lcl.order_submissions (
          submission_id         VARCHAR,
          submitted_at          TIMESTAMP,
          module                VARCHAR,
          broker                VARCHAR,
          account               VARCHAR,

          base_key              VARCHAR,
          intent_key            VARCHAR,
          payload_hash          VARCHAR,
          base_id               VARCHAR,
          payload_id            VARCHAR,

          ticker                VARCHAR,
          expiry                VARCHAR,
          strike_found          DOUBLE,
          qty                   INTEGER,

          entry_order_type      VARCHAR,
          entry_limit           DOUBLE,
          duration              VARCHAR,

          exit_mode             VARCHAR,
          attach_exit           BOOLEAN,
          tp_limit              DOUBLE,
          stop_type             VARCHAR,
          stop_price            DOUBLE,
          stop_limit_price      DOUBLE,

          option_symbol         VARCHAR,

          status                VARCHAR,
          broker_order_id       VARCHAR,
          perm_ids_json         VARCHAR,
          broker_response_json  VARCHAR,

          filled_qty            DOUBLE,
          avg_fill_price        DOUBLE,
          filled_at             TIMESTAMP,

          payload_json          VARCHAR,
          run_id                VARCHAR
        )
        """
    )

    need_cols = [
        ("base_key", "VARCHAR"),
        ("intent_key", "VARCHAR"),
        ("payload_hash", "VARCHAR"),
        ("base_id", "VARCHAR"),
        ("payload_id", "VARCHAR"),
        ("perm_ids_json", "VARCHAR"),
    ]
    for col, typ in need_cols:
        try:
            con.execute(f"ALTER TABLE ledger.lcl.order_submissions ADD COLUMN {col} {typ}")
        except Exception:
            pass


def _latest_submission(con, *, broker: str, account: str, base_key: str) -> Optional[Tuple[str, str, str, datetime]]:
    rows = con.execute(
        """
        SELECT submission_id, status, payload_hash, submitted_at
        FROM ledger.lcl.order_submissions
        WHERE broker = ?
          AND account = ?
          AND base_key = ?
        ORDER BY submitted_at DESC
        LIMIT 1
        """,
        [broker, account, base_key],
    ).fetchall()
    if not rows:
        return None
    sid, st, ph, ts = rows[0]
    return (str(sid), str(st or ""), str(ph or ""), ts)


def _mark_latest_final(con, *, broker: str, account: str, base_key: str, status: str, note_json: str = "") -> int:
    try:
        con.execute(
            """
            WITH latest AS (
              SELECT submission_id
              FROM ledger.lcl.order_submissions
              WHERE broker = ?
                AND account = ?
                AND base_key = ?
              ORDER BY submitted_at DESC
              LIMIT 1
            )
            UPDATE ledger.lcl.order_submissions
              SET status = ?,
                  broker_response_json = CASE
                    WHEN ? = '' THEN broker_response_json
                    ELSE ?
                  END
            WHERE submission_id IN (SELECT submission_id FROM latest)
            """,
            [broker, account, base_key, status, note_json, note_json],
        )
        return 1
    except Exception:
        return 0


def _insert_submission(con, row: Dict[str, Any]) -> None:
    cols = list(row.keys())
    vals = [row.get(c) for c in cols]
    con.execute(
        f"INSERT INTO ledger.lcl.order_submissions ({','.join(cols)}) VALUES ({','.join(['?']*len(cols))})",
        vals,
    )


# ----------------------------
# Broker open-orders helpers
# ----------------------------
def fetch_open_orders(app: IBQueueApp, timeout: float = 8.0) -> List[OpenOrderRow]:
    app.st.open_orders = []
    app.ev_openorders_end.clear()
    app.reqOpenOrders()
    try:
        app.reqAllOpenOrders()
    except Exception:
        pass
    app.ev_openorders_end.wait(timeout=timeout)
    return list(app.st.open_orders)


def index_open_orders_by_base_id(open_orders: List[OpenOrderRow]) -> Dict[str, List[OpenOrderRow]]:
    out: Dict[str, List[OpenOrderRow]] = {}
    for oo in open_orders:
        base_id, _payload_id = parse_order_ref(oo.orderRef)
        if not base_id:
            continue
        out.setdefault(base_id, []).append(oo)
    return out


# ----------------------------
# Commands
# ----------------------------
def cmd_place(args) -> int:
    queue_path = _resolve_queue_path(args)

    repo = _repo_root()
    user_root = _user_root(repo)
    cfg = _load_user_yml(Path(args.user_yml).expanduser().resolve()) if args.user_yml else _load_user_yml(_cfg_path(user_root))

    module = str(args.module or "sellput").strip()
    right = "P"

    conn = _effective_conn(args, cfg)
    _enforce_live_safety(conn, args)

    df_all, df_elig = load_eligible_rows(str(queue_path), args.sheet, ignore_submit=bool(args.ignore_submit))
    print_eligibility_report(df_all, df_elig, ignore_submit=bool(args.ignore_submit))

    if df_elig.empty:
        print("No eligible rows found (need User Action=EXECUTE and Submit=YES).", flush=True)
        return 0

    # Ensure keys exist + anti-tamper validation (works even in dry-run)
    df_elig = _ensure_and_validate_key_cols(df_elig, module=module, right=right)

    print_plan_table(df_elig, will_execute=bool(args.execute))

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S") + f"_ibkr_{os.getpid()}"

    # Dry-run default: do NOT connect (prevents hang)
    if not args.execute and not args.connect_on_plan:
        print(f"[place] queue={queue_path} sheet={args.sheet} rows={len(df_elig)} execute=False run_id={run_id}", flush=True)
        return 0

    app = IBQueueApp(verbose=bool(args.verbose))
    con = None
    t = None

    try:
        # IBKR connect
        app.connect(conn["host"], conn["port"], clientId=conn["client_id"])
        t = threading.Thread(target=app.run, daemon=True)
        t.start()

        if not app.ev_nextid.wait(timeout=10):
            print("FAIL: did not receive nextValidId", flush=True)
            return 2

        app.ev_accounts.wait(timeout=5)
        acct = (app.st.managed_accounts.split(",")[0].strip() if app.st.managed_accounts else "") or "UNKNOWN"
        print(f"[ibkr] connected env={conn['env']} host={conn['host']} port={conn['port']} clientId={conn['client_id']} acct={acct}", flush=True)

        # Ledger
        db_path = _ledger_db_path(cfg, user_root)
        con = connect_ledger(db_path)
        _ensure_order_submissions_table(con)

        base_order_id = int(app.st.next_order_id or 1)

        # Snapshot broker open orders at start
        open_orders = fetch_open_orders(app, timeout=8.0)
        open_by_base = index_open_orders_by_base_id(open_orders)

        print(
            f"[place] queue={queue_path} sheet={args.sheet} rows={len(df_elig)} execute={bool(args.execute)} run_id={run_id}",
            flush=True,
        )

        for _, r in df_elig.iterrows():
            ticker = str(r.get("Ticker") or "").strip().upper()
            expiry_iso = _parse_expiry_iso(r.get("Expiry"))
            expiry_yyyymmdd = _parse_expiry_yyyymmdd(r.get("Expiry"))
            strike = float(r.get("Strike Found"))
            qty_raw = r.get("Qty", 1)
            try:
                qty = int(float(qty_raw)) if qty_raw not in (None, "") else 1
            except Exception:
                qty = 1
            qty = max(qty, 1)

            limit = _float_or_none(r.get("Limit Price Override"))
            if limit is None:
                limit = _float_or_none(r.get("Mid")) or _float_or_none(r.get("Bid")) or _float_or_none(r.get("Last"))
            if limit is None:
                raise SystemExit(f"❌ Missing limit price for {ticker} {expiry_iso} {right}{strike:g}")

            tif = _tif_from_duration(r.get("Duration"))
            attach_exit = str(r.get("Attach Exit") or "").strip().upper() == "YES"
            tp = _float_or_none(r.get("TP Limit"))
            stop_type = str(r.get("Stop Type") or "").strip().upper()
            stop_price = _float_or_none(r.get("Stop Price"))
            stop_lmt = _float_or_none(r.get("Stop Limit Price"))
            exit_mode = str(r.get("Exit Mode") or "").strip()

            # Recompute queue-compatible keys
            base_key = compute_base_key(module=module, ticker=ticker, expiry_iso=expiry_iso, right=right, strike=strike)
            intent_key = compute_intent_key(base_key=base_key, qty=qty)
            pp = _plan_params_from_row(r, module=module, ticker=ticker, expiry_iso=expiry_iso, right=right, strike=strike, qty=qty)
            payload_hash = compute_payload_hash(pp)
            payload_id = payload_id_from_payload_hash(payload_hash, n=8)

            # Account-scoped base_id for broker orderRef de-dupe
            base_id = _base_id_for_account(acct, base_key, n=12)

            # Anti-tamper (if columns present)
            # q_base = _col_get(r, "base_key", "Base Key", default="").strip()
            #q_intent = _col_get(r, "intent_key", "Intent Key", default="").strip()
            #q_ph = _col_get(r, "payload_hash", "Payload Hash", default="").strip()
            #if q_base and q_base != base_key:
            #    raise SystemExit(f"❌ base_key mismatch in queue_edit for {ticker} {expiry_iso} {right}{strike:g}.")
            #if q_intent and q_intent != intent_key:
            #    raise SystemExit(f"❌ intent_key mismatch in queue_edit for {ticker} {expiry_iso} {right}{strike:g}.")
            #if q_ph and q_ph != payload_hash:
            #    raise SystemExit(f"❌ payload_hash mismatch in queue_edit for {ticker} {expiry_iso} {right}{strike:g}.")

            # Broker-side: cancel & replace by base_id
            existing = open_by_base.get(base_id, [])
            existing_payload_ids = sorted({parse_order_ref(x.orderRef)[1] for x in existing if parse_order_ref(x.orderRef)[1]})
            if existing:
                if payload_id in existing_payload_ids:
                    print(f"[skip-broker-same] {ticker} {expiry_iso} {right}{strike:g} base_id={base_id} payload_id={payload_id}", flush=True)
                    continue
                if args.execute:
                    print(f"[replace] {ticker} {expiry_iso} {right}{strike:g} base_id={base_id} cancelling {len(existing)} open order(s) payloads={existing_payload_ids}", flush=True)
                    for oo in existing:
                        print(f"  cancel orderId={oo.orderId} ref={oo.orderRef} status={oo.status}", flush=True)
                        app._cancel_order(oo.orderId)
                        time.sleep(0.15)
                    time.sleep(1.0)
                    open_orders = fetch_open_orders(app, timeout=6.0)
                    open_by_base = index_open_orders_by_base_id(open_orders)
                else:
                    print(f"[would-replace] {ticker} {expiry_iso} {right}{strike:g} base_id={base_id} would cancel {len(existing)} then submit payload_id={payload_id}", flush=True)

            # Ledger: if stale non-final exists but broker has no open -> auto-finalize old row to ERROR
            latest = _latest_submission(con, broker="IBKR", account=acct, base_key=base_key)
            if latest:
                _sid, latest_status, _latest_ph, latest_ts = latest
                st_up = latest_status.upper().strip()
                if st_up and st_up not in FINAL_STATUSES:
                    if not open_by_base.get(base_id):
                        note = json.dumps({"stale_ledger": True, "auto_marked": "ERROR", "prev_status": latest_status, "prev_submitted_at": str(latest_ts)})
                        _mark_latest_final(con, broker="IBKR", account=acct, base_key=base_key, status="ERROR", note_json=note)
                        print(f"[stale-ledger] auto-marked ERROR for base_id={base_id} prev_status={latest_status} at={latest_ts}", flush=True)

            order_ref = mk_order_ref(base_id, payload_id)
            contract = mk_put_contract(ticker, expiry_yyyymmdd, strike)

            parent_id = base_order_id
            oca_group = f"OCA:{base_id}"

            parent = mk_order_sell_lmt(qty=qty, limit=limit, tif=tif, order_ref=order_ref, transmit=(not attach_exit))
            orders: List[Tuple[int, Contract, Order]] = [(parent_id, contract, parent)]
            next_id = parent_id + 1

            if attach_exit:
                if tp is not None:
                    tp_order = mk_order_buy_lmt(
                        qty=qty, limit=tp, tif=tif, parent_id=parent_id,
                        oca=oca_group, order_ref=order_ref, transmit=False
                    )
                    orders.append((next_id, contract, tp_order))
                    next_id += 1

                if stop_price is not None:
                    if stop_type == "STOP_LIMIT":
                        if stop_lmt is None:
                            raise SystemExit(f"❌ {ticker}: STOP_LIMIT requires Stop Limit Price")
                        stp = mk_order_buy_stp_lmt(
                            qty=qty, stop_price=stop_price, stop_lmt_price=stop_lmt, tif=tif,
                            parent_id=parent_id, oca=oca_group, order_ref=order_ref, transmit=True
                        )
                    else:
                        stp = mk_order_buy_stp_mkt(
                            qty=qty, stop_price=stop_price, tif=tif,
                            parent_id=parent_id, oca=oca_group, order_ref=order_ref, transmit=True
                        )
                    orders.append((next_id, contract, stp))
                    next_id += 1
                else:
                    if len(orders) >= 2:
                        orders[-1][2].transmit = True
                    else:
                        orders[0][2].transmit = True

            print(f"\n[{ticker}] SELL PUT {expiry_iso} {right}{strike:g} qty={qty} limit={limit} tif={tif} ref={order_ref}", flush=True)
            print(f"  keys: base_key={base_key} base_id={base_id} payload_id={payload_id}", flush=True)
            if attach_exit:
                print(f"  exits: OCO tp={tp} stop_type={stop_type} stop={stop_price} stop_lmt={stop_lmt}", flush=True)

            if not args.execute:
                base_order_id = next_id
                continue

            # Place orders
            order_ids = [oid for oid, _, _ in orders]
            for oid, c, o in orders:
                try:
                    o.account = acct
                except Exception:
                    pass
                app.log(f"[IBKR:placeOrder] id={oid} action={o.action} type={o.orderType} tif={getattr(o,'tif','')} ref={getattr(o,'orderRef','')}")
                app.placeOrder(int(oid), c, o)
                time.sleep(0.2)

            # Wait for IBKR ACK
            ack = app.await_status(order_ids, timeout=float(args.ack_timeout))
            ack_json = [{"orderId": a.orderId, "status": a.status, "permId": a.permId} for a in ack]
            print(f"[IBKR:ACK] ref={order_ref} ids={ack_json}", flush=True)

            parent_ack = next((a for a in ack if a.orderId == parent_id), None)
            accepted = bool(parent_ack and parent_ack.permId > 0 and str(parent_ack.status or "").strip() != "")

            status_norm = (str(parent_ack.status).upper().strip() if parent_ack else "").replace(" ", "")
            if status_norm == "PRESUBMITTED":
                status_norm = "PRESUBMITTED"
            elif status_norm == "SUBMITTED":
                status_norm = "SUBMITTED"
            elif status_norm == "FILLED":
                status_norm = "FILLED"
            elif status_norm.startswith("REJECT"):
                status_norm = "REJECTED"
            elif not status_norm:
                status_norm = "ERROR"

            if not accepted:
                status_norm = "ERROR"

            perm_ids = sorted({int(a.permId) for a in ack if int(a.permId or 0) > 0})
            perm_ids_json = json.dumps(perm_ids)

            payload_json = json.dumps(
                {
                    "broker": "IBKR",
                    "env": conn["env"],
                    "account": acct,
                    "plan_params": pp,
                    "tif": tif,
                    "exit_mode": exit_mode,
                },
                sort_keys=True,
            )

            row = {
                "submission_id": uuid.uuid4().hex,
                "submitted_at": datetime.now(),
                "module": module,
                "broker": "IBKR",
                "account": acct,

                "base_key": base_key,
                "intent_key": intent_key,
                "payload_hash": payload_hash,
                "base_id": base_id,
                "payload_id": payload_id,

                "ticker": ticker,
                "expiry": expiry_iso,
                "strike_found": float(strike),
                "qty": int(qty),

                "entry_order_type": "LIMIT",
                "entry_limit": float(limit),
                "duration": str(r.get("Duration") or ""),

                "exit_mode": exit_mode,
                "attach_exit": bool(attach_exit),
                "tp_limit": tp,
                "stop_type": stop_type,
                "stop_price": stop_price,
                "stop_limit_price": stop_lmt,

                "option_symbol": f"{ticker} {expiry_iso} {right}{strike:g}",
                "status": status_norm,
                "broker_order_id": str(parent_id),
                "perm_ids_json": perm_ids_json,
                "broker_response_json": json.dumps({"ack": ack_json, "errors": app.st.errors[-10:]}),

                "filled_qty": None,
                "avg_fill_price": None,
                "filled_at": None,

                "payload_json": payload_json,
                "run_id": run_id,
            }
            _insert_submission(con, row)

            base_order_id = next_id

        return 0

    finally:
        try:
            if con is not None:
                con.close()
        except Exception:
            pass
        try:
            app.disconnect()
        except Exception:
            pass
        try:
            time.sleep(0.3)
        except Exception:
            pass


def cmd_cancel(args) -> int:
    queue_path = _resolve_queue_path(args)

    repo = _repo_root()
    user_root = _user_root(repo)
    cfg = _load_user_yml(Path(args.user_yml).expanduser().resolve()) if args.user_yml else _load_user_yml(_cfg_path(user_root))

    module = str(args.module or "sellput").strip()
    right = "P"

    conn = _effective_conn(args, cfg)
    _enforce_live_safety(conn, args)

    df_all, df_elig = load_eligible_rows(str(queue_path), args.sheet, ignore_submit=bool(args.ignore_submit))
    print_eligibility_report(df_all, df_elig, ignore_submit=bool(args.ignore_submit))

    if df_elig.empty:
        print("No eligible rows found (need User Action=EXECUTE and Submit=YES).", flush=True)
        return 0

    df_elig = _ensure_and_validate_key_cols(df_elig, module=module, right=right)

    app = IBQueueApp(verbose=bool(args.verbose))
    con = None
    try:
        app.connect(conn["host"], conn["port"], clientId=conn["client_id"])
        t = threading.Thread(target=app.run, daemon=True)
        t.start()

        if not app.ev_nextid.wait(timeout=10):
            print("FAIL: did not receive nextValidId", flush=True)
            return 2

        app.ev_accounts.wait(timeout=5)
        acct = (app.st.managed_accounts.split(",")[0].strip() if app.st.managed_accounts else "") or "UNKNOWN"
        print(f"[ibkr] connected env={conn['env']} host={conn['host']} port={conn['port']} clientId={conn['client_id']} acct={acct}", flush=True)

        target_base_ids: Set[str] = set()
        for _, r in df_elig.iterrows():
            ticker = str(r.get("Ticker") or "").strip().upper()
            expiry_iso = _parse_expiry_iso(r.get("Expiry"))
            strike = float(r.get("Strike Found"))
            base_key = compute_base_key(module=module, ticker=ticker, expiry_iso=expiry_iso, right=right, strike=strike)
            base_id = _base_id_for_account(acct, base_key, n=12)
            target_base_ids.add(base_id)

        open_orders = fetch_open_orders(app, timeout=8.0)
        targets = [oo for oo in open_orders if parse_order_ref(oo.orderRef)[0] in target_base_ids]

        print(
            f"[cancel] queue={queue_path} sheet={args.sheet} base_ids={len(target_base_ids)} open_orders_seen={len(open_orders)} targets={len(targets)}",
            flush=True,
        )

        db_path = _ledger_db_path(cfg, user_root)
        con = connect_ledger(db_path)
        _ensure_order_submissions_table(con)

        for oo in targets:
            print(f"  cancel orderId={oo.orderId} {oo.symbol} {oo.secType} ref={oo.orderRef} status={oo.status}", flush=True)
            app._cancel_order(oo.orderId)
            time.sleep(0.2)

            base_id, _pid = parse_order_ref(oo.orderRef)
            try:
                con.execute(
                    """
                    UPDATE ledger.lcl.order_submissions
                      SET status = 'CANCEL_REQUESTED'
                    WHERE broker='IBKR'
                      AND account=?
                      AND base_id=?
                      AND submitted_at = (
                        SELECT MAX(submitted_at)
                        FROM ledger.lcl.order_submissions
                        WHERE broker='IBKR' AND account=? AND base_id=?
                      )
                    """,
                    [acct, base_id, acct, base_id],
                )
            except Exception:
                pass

        return 0

    finally:
        try:
            if con is not None:
                con.close()
        except Exception:
            pass
        try:
            app.disconnect()
        except Exception:
            pass
        try:
            time.sleep(0.3)
        except Exception:
            pass


def cmd_unblock(args) -> int:
    queue_path = _resolve_queue_path(args)

    repo = _repo_root()
    user_root = _user_root(repo)
    cfg = _load_user_yml(Path(args.user_yml).expanduser().resolve()) if args.user_yml else _load_user_yml(_cfg_path(user_root))

    module = str(args.module or "sellput").strip()
    right = "P"

    conn = _effective_conn(args, cfg)
    _enforce_live_safety(conn, args)

    df_all, df_elig = load_eligible_rows(str(queue_path), args.sheet, ignore_submit=bool(args.ignore_submit))
    print_eligibility_report(df_all, df_elig, ignore_submit=bool(args.ignore_submit))

    if df_elig.empty:
        print("No eligible rows found (need User Action=EXECUTE and Submit=YES).", flush=True)
        return 0

    df_elig = _ensure_and_validate_key_cols(df_elig, module=module, right=right)

    app = IBQueueApp(verbose=bool(args.verbose))
    con = None
    try:
        app.connect(conn["host"], conn["port"], clientId=conn["client_id"])
        t = threading.Thread(target=app.run, daemon=True)
        t.start()

        if not app.ev_nextid.wait(timeout=10):
            print("FAIL: did not receive nextValidId", flush=True)
            return 2

        app.ev_accounts.wait(timeout=5)
        acct = (app.st.managed_accounts.split(",")[0].strip() if app.st.managed_accounts else "") or "UNKNOWN"
        print(f"[ibkr] connected env={conn['env']} host={conn['host']} port={conn['port']} clientId={conn['client_id']} acct={acct}", flush=True)

        open_orders = fetch_open_orders(app, timeout=8.0)
        open_by_base = index_open_orders_by_base_id(open_orders)

        db_path = _ledger_db_path(cfg, user_root)
        con = connect_ledger(db_path)
        _ensure_order_submissions_table(con)

        updates = 0
        for _, r in df_elig.iterrows():
            ticker = str(r.get("Ticker") or "").strip().upper()
            expiry_iso = _parse_expiry_iso(r.get("Expiry"))
            strike = float(r.get("Strike Found"))

            base_key = compute_base_key(module=module, ticker=ticker, expiry_iso=expiry_iso, right=right, strike=strike)
            base_id = _base_id_for_account(acct, base_key, n=12)

            if open_by_base.get(base_id):
                print(f"[unblock-skip] broker still has open order(s) for {ticker} {expiry_iso} P{strike:g} base_id={base_id}", flush=True)
                continue

            latest = _latest_submission(con, broker="IBKR", account=acct, base_key=base_key)
            if not latest:
                print(f"[unblock] no ledger row for {ticker} {expiry_iso} P{strike:g} base_id={base_id}", flush=True)
                continue

            sid, st, ph, ts = latest
            st_up = st.upper().strip()
            if st_up in FINAL_STATUSES:
                print(f"[unblock] already final {ticker} {expiry_iso} P{strike:g} status={st_up} at={ts}", flush=True)
                continue

            note = json.dumps({"unblock": True, "prev_status": st, "prev_payload_hash": ph, "prev_submitted_at": str(ts)})
            if args.apply:
                _mark_latest_final(con, broker="IBKR", account=acct, base_key=base_key, status="ERROR", note_json=note)
                print(f"[unblock] applied: marked ERROR {ticker} {expiry_iso} P{strike:g} base_id={base_id} submission_id={sid}", flush=True)
                updates += 1
            else:
                print(f"[unblock] would mark ERROR {ticker} {expiry_iso} P{strike:g} status={st_up} at={ts} submission_id={sid}", flush=True)

        if not args.apply:
            print("[unblock] dry-run only. Re-run with --apply to commit.", flush=True)
        else:
            print(f"[unblock] applied: {updates} row(s) marked ERROR (final).", flush=True)

        return 0

    finally:
        try:
            if con is not None:
                con.close()
        except Exception:
            pass
        try:
            app.disconnect()
        except Exception:
            pass
        try:
            time.sleep(0.3)
        except Exception:
            pass


def main() -> int:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--user-yml", default="", help="Optional path to tgps-user/config/lcl.user.yml (default: auto)")
    common.add_argument("--module", default="sellput", help="Module name for config lookup (default: sellput)")
    common.add_argument("--env", default="", help="Override IBKR env: paper|live (default from YAML)")
    common.add_argument("--live", action="store_true", help="Required safety flag when env=live")
    common.add_argument("--host", default="", help="Override host (default from YAML)")
    common.add_argument("--port", type=int, default=0, help="Override port (default from YAML)")
    common.add_argument("--client-id", type=int, default=None, help="Override client id (default from YAML)")
    common.add_argument("--queue", default="", help="Optional explicit queue_edit path (default: latest from queue_dir)")
    common.add_argument("--sheet", default="ALL")
    common.add_argument("--ignore-submit", action="store_true", help="Ignore Submit=YES filter (diagnostics only)")
    common.add_argument("--verbose", action="store_true")
    common.add_argument("--ack-timeout", type=float, default=8.0, help="Seconds to wait for IBKR orderStatus ACK (default 8)")

    ap = argparse.ArgumentParser(
        "Plan/cancel/unblock IBKR sell-put orders for EXECUTE rows in queue_edit.xlsx",
        parents=[common],
    )

    sub = ap.add_subparsers(dest="cmd", required=True)

    p_plan = sub.add_parser("plan", help="Plan eligible rows (dry-run by default)", parents=[common])
    p_plan.add_argument("--execute", action="store_true", help="Place orders on IBKR (otherwise dry-run)")
    p_plan.add_argument("--connect-on-plan", action="store_true", help="In dry-run plan, connect to IBKR to show would-replace/skip decisions")

    sub.add_parser("cancel", help="Cancel broker open orders matching eligible rows (by base_id in orderRef)", parents=[common])

    p_unblock = sub.add_parser("unblock", help="Mark stale ledger rows as ERROR (final) if broker has no open orders", parents=[common])
    p_unblock.add_argument("--apply", action="store_true", help="Commit unblock changes (default is dry-run)")

    args = ap.parse_args()

    print(f"[ibkr_sellput_queue] file={__file__}", flush=True)

    if args.cmd == "plan":
        return cmd_place(args)
    if args.cmd == "cancel":
        return cmd_cancel(args)
    if args.cmd == "unblock":
        return cmd_unblock(args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
