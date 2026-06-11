#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/tgps_user/fills_mgt.py
Version: 0.3.4 (2026-01-15, SGT)

Changes in 0.3.4
----------------
• Replace deprecated datetime.utcnow() with a UTC helper (no behavior change; still stores naive UTC timestamps).

Purpose
-------
Fills / transactions + account snapshot management CLI for tgps-user:
- sync: pull Schwab account transactions (fills/activity) in small date chunks and store raw snapshots locally
- txns: list cached transactions (latest snapshot per txn_id) from raw or latest table
- show: view cached transaction JSON (raw or latest)
- snapshot: pull Schwab account snapshot (balances + positions) and store raw + normalized positions
- positions: list latest cached positions (from snapshots)
- pnl: quick P&L view from snapshot deltas + (optional) external cashflows from transactions
- types: print distinct txn_type values observed in your local cache (so you can tune cashflow-types)

Why this exists
---------------
Your RestClient wrapper may not expose `.transactions`. This script uses RestSession.request()
directly so we don't need to modify client/schwab_api.py to get moving.

Critical Schwab quirks
----------------------
- Transactions endpoint expects startDate/endDate as full ISO-8601 UTC timestamps with Z:
    2026-01-13T00:00:00.000Z
  NOT just YYYY-MM-DD.
- Transactions endpoint requires `types`.
- IMPORTANT: Schwab expects `types` as a comma-separated string (NOT repeated query params).

Notes
-----
- Many Schwab API implementations constrain transactions lookback to ~60-120 days (varies).
  This script caps --days unless you pass --force.
- All DB writes go into: tgps-user/ledger/lcl.ledger.duckdb under schema ledger.lcl.*

Write modes
----------
sync --write-mode:
- append   : (default) append into broker_transactions_raw (audit trail; grows)
- override : delete cached rows for the requested date window + types (+ optional symbol), then insert fresh into raw
- upsert   : upsert into broker_transactions_latest (one row per txn_id), optional --also-raw to keep audit log too

Reliability (B pass)
--------------------
- DB writes in `sync` and `snapshot` are protected by a single-writer file lock:
    tgps-user/ledger/tgps_ledger_write.lock
- Network calls happen OUTSIDE the lock; lock is held only during DB writes.
- Override mode delete+insert happens in one DB transaction (commit/rollback).
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

from client.schwab_admin import AuthClient, TokenStore  # noqa: E402
from client.schwab_api import RestSession  # noqa: E402

# ---- Single-writer lock helper ----
try:
    # When invoked as module: python -m scripts.tgps_user.fills_mgt
    from ._lock import LockHeldError, ledger_write_lock  # type: ignore
except Exception:
    # Fallback for direct execution / unusual sys.path contexts
    from scripts.tgps_user._lock import LockHeldError, ledger_write_lock  # type: ignore




# ----------------------------
# Time helpers
# ----------------------------
def _utc_now_naive() -> datetime:
    """UTC now as *naive* datetime.

    DuckDB tables here use TIMESTAMP (no tz). We still avoid _utc_now_naive()
    deprecation warnings by generating an aware UTC timestamp, then stripping tzinfo.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


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
# Account resolution helpers (same behavior as order_mgt)
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


def _make_session() -> RestSession:
    store = TokenStore()
    auth = AuthClient(store)
    return RestSession(auth)


# ----------------------------
# DuckDB helpers
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


def _ensure_broker_account_snapshot_table(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS ledger.lcl.broker_account_snapshots_raw (
          account_hash      VARCHAR,
          fetched_at        TIMESTAMP,
          liquidation_value DOUBLE,
          cash_balance      DOUBLE,
          buying_power      DOUBLE,
          snapshot_json     VARCHAR
        );
        """
    )
    try:
        con.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_broker_acct_snap_raw ON ledger.lcl.broker_account_snapshots_raw(account_hash, fetched_at);"
        )
    except Exception:
        pass


def _ensure_broker_positions_snapshot_table(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS ledger.lcl.broker_positions_snapshots (
          account_hash   VARCHAR,
          fetched_at     TIMESTAMP,
          symbol         VARCHAR,
          asset_type     VARCHAR,
          long_qty       DOUBLE,
          short_qty      DOUBLE,
          net_qty        DOUBLE,
          avg_price      DOUBLE,
          market_value   DOUBLE,
          day_pl         DOUBLE,
          open_pl        DOUBLE,
          pos_json       VARCHAR
        );
        """
    )
    try:
        con.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_broker_pos_snap ON ledger.lcl.broker_positions_snapshots(account_hash, fetched_at, symbol, asset_type);"
        )
    except Exception:
        pass


def _table_exists(con: duckdb.DuckDBPyConnection, qualified: str) -> bool:
    try:
        con.execute(f"SELECT 1 FROM {qualified} LIMIT 1;")
        return True
    except Exception:
        return False


# ----------------------------
# Schwab transaction type presets
# ----------------------------
ALL_TXN_TYPES: List[str] = [
    "TRADE",
    "RECEIVE_AND_DELIVER",
    "DIVIDEND_OR_INTEREST",
    "ACH_RECEIPT",
    "ACH_DISBURSEMENT",
    "CASH_RECEIPT",
    "CASH_DISBURSEMENT",
    "ELECTRONIC_FUND",
    "WIRE_OUT",
    "WIRE_IN",
    "JOURNAL",
    "MEMORANDUM",
    "MARGIN_CALL",
    "MONEY_MARKET",
    "SMA_ADJUSTMENT",
]

DEFAULT_CASHFLOW_TYPES: List[str] = [
    "ACH_RECEIPT",
    "ACH_DISBURSEMENT",
    "CASH_RECEIPT",
    "CASH_DISBURSEMENT",
    "ELECTRONIC_FUND",
    "WIRE_IN",
    "WIRE_OUT",
]


# ----------------------------
# Schwab URLs
# ----------------------------
def _transactions_url(account_hash: str) -> str:
    return f"https://api.schwabapi.com/trader/v1/accounts/{account_hash}/transactions"


def _account_url(account_hash: str) -> str:
    return f"https://api.schwabapi.com/trader/v1/accounts/{account_hash}"


# ----------------------------
# Small helpers
# ----------------------------
def _as_float(x: Any) -> Optional[float]:
    if x is None:
        return None
    try:
        return float(x)
    except Exception:
        return None


def _iso_z_from_date(d: date, *, end_of_day: bool) -> str:
    """
    Schwab wants: yyyy-MM-dd'T'HH:mm:ss.SSSZ (UTC).
    We send "...000Z" at start and "...999Z" at end-of-day.
    """
    if end_of_day:
        dt = datetime(d.year, d.month, d.day, 23, 59, 59, 999000, tzinfo=timezone.utc)
    else:
        dt = datetime(d.year, d.month, d.day, 0, 0, 0, 0, tzinfo=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _split_csv(s: str) -> List[str]:
    return [x.strip() for x in (s or "").split(",") if x.strip()]


def _expand_types(types_csv: str) -> List[str]:
    s = (types_csv or "").strip().upper()
    if s in ("ALL", "*"):
        return ALL_TXN_TYPES[:]
    out = [t.strip().upper() for t in _split_csv(types_csv)]
    return out or ["TRADE"]


def _sha256_json(obj: Any) -> str:
    txt = json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(txt.encode("utf-8")).hexdigest()


def _pick_txn_id(o: Dict[str, Any]) -> str:
    for k in ("transactionId", "txnId", "id", "activityId", "tradeId"):
        v = o.get(k)
        if v is not None and str(v).strip():
            return str(v).strip()
    # stable fallback
    return _sha256_json(o)


def _pick_symbol(o: Dict[str, Any]) -> str:
    for k in ("symbol", "underlyingSymbol", "ticker"):
        v = o.get(k)
        if v is not None and str(v).strip():
            return str(v).strip().upper()
    inst = o.get("instrument")
    if isinstance(inst, dict):
        v = inst.get("symbol")
        if v:
            return str(v).strip().upper()
    return ""


def _parse_dt_any(s: Any) -> Optional[datetime]:
    """
    Schwab examples:
      2025-07-17T13:41:10+0000
      2025-07-17T13:41:10+00:00
      2025-07-17T13:41:10Z
      2025-07-17
    Returns: UTC-aware datetime where possible.
    """
    if s is None:
        return None
    txt = str(s).strip()
    if not txt:
        return None

    # Normalize trailing Z
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"

    # Normalize +0000 -> +00:00
    try:
        if len(txt) >= 5 and (txt[-5] in ("+", "-")) and txt[-2:].isdigit() and txt[-4:-2].isdigit() and txt[-3] != ":":
            txt = txt[:-2] + ":" + txt[-2:]
    except Exception:
        pass

    # Try fromisoformat first
    try:
        dt = datetime.fromisoformat(txt)
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc)
        return dt
    except Exception:
        pass

    # Fallback formats
    for f in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(txt, f)
            if dt.tzinfo is not None:
                dt = dt.astimezone(timezone.utc)
            return dt
        except Exception:
            continue

    return None


def _pick_date(o: Dict[str, Any]) -> Optional[date]:
    for k in ("tradeDate", "transactionDate", "date", "postedDate", "activityDate"):
        v = o.get(k)
        if v is None:
            continue
        dt = _parse_dt_any(v)
        if dt is not None:
            return dt.date()
    return None


def _pick_type(o: Dict[str, Any]) -> str:
    for k in ("type", "transactionType", "activityType"):
        v = o.get(k)
        if v is not None and str(v).strip():
            return str(v).strip().upper()
    return ""


def _extract_securities_account(payload: Any) -> Dict[str, Any]:
    """
    Schwab account detail responses sometimes look like:
      {"securitiesAccount": {...}}
    or
      {"accounts":[{"securitiesAccount":{...}}]}
    or
      [{"securitiesAccount":{...}}]
    We normalize to the inner securitiesAccount dict when possible.
    """
    if isinstance(payload, dict):
        if isinstance(payload.get("securitiesAccount"), dict):
            return payload["securitiesAccount"]

        for k in ("accounts", "account", "items", "results"):
            v = payload.get(k)
            if isinstance(v, list) and v:
                first = v[0]
                if isinstance(first, dict) and isinstance(first.get("securitiesAccount"), dict):
                    return first["securitiesAccount"]
                if isinstance(first, dict):
                    return first
        return payload

    if isinstance(payload, list) and payload:
        first = payload[0]
        if isinstance(first, dict) and isinstance(first.get("securitiesAccount"), dict):
            return first["securitiesAccount"]
        if isinstance(first, dict):
            return first

    return {}


def _validate_write_mode(s: str) -> str:
    m = (s or "append").strip().lower()
    if m not in ("append", "override", "upsert"):
        raise SystemExit("Invalid --write-mode. Use: append | override | upsert")
    return m


def _validate_source(s: str) -> str:
    m = (s or "raw").strip().lower()
    if m not in ("raw", "latest", "auto"):
        raise SystemExit("Invalid source. Use: raw | latest | auto")
    return m


# ----------------------------
# Schwab calls
# ----------------------------
def _call_transactions(
    session: RestSession,
    *,
    account_hash: str,
    start_d: date,
    end_d: date,
    symbol: str = "",
    types_csv: str = "TRADE",
    debug: bool = False,
) -> List[Dict[str, Any]]:
    """
    Calls Schwab transactions endpoint.

    - startDate/endDate MUST be ISO-8601 UTC with Z.
    - types is REQUIRED.
    - Schwab expects 'types' as a comma-separated string (NOT repeated params).
    """
    types_list = [t.strip().upper() for t in _split_csv(types_csv)] or ["TRADE"]

    params: Dict[str, Any] = {
        "startDate": _iso_z_from_date(start_d, end_of_day=False),
        "endDate": _iso_z_from_date(end_d, end_of_day=True),
        "types": ",".join(types_list),
    }
    if symbol.strip():
        params["symbol"] = symbol.strip().upper()

    url = _transactions_url(account_hash)
    if debug:
        print(f"[debug] GET {url} params={params}")

    resp = session.request("GET", url, params=params)

    try:
        payload = resp.json()
    except Exception:
        payload = None

    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]

    if isinstance(payload, dict):
        for k in ("transactions", "items", "results"):
            v = payload.get(k)
            if isinstance(v, list):
                return [x for x in v if isinstance(x, dict)]
        if any(k in payload for k in ("transactionId", "activityId", "type", "transactionType")):
            return [payload]

    return []


def _call_account_snapshot(
    session: RestSession,
    *,
    account_hash: str,
    fields_csv: str = "positions",
    debug: bool = False,
) -> Dict[str, Any]:
    fields_list = _split_csv(fields_csv) or ["positions"]
    params = {"fields": ",".join(fields_list)}
    url = _account_url(account_hash)
    if debug:
        print(f"[debug] GET {url} params={params}")
    resp = session.request("GET", url, params=params)

    try:
        payload = resp.json()
    except Exception:
        payload = {}
    return payload if isinstance(payload, dict) else {"data": payload}


# ----------------------------
# Snapshot parsing
# ----------------------------
def _parse_balances(acct: Dict[str, Any]) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    cb = acct.get("currentBalances") if isinstance(acct.get("currentBalances"), dict) else {}
    ib = acct.get("initialBalances") if isinstance(acct.get("initialBalances"), dict) else {}
    pv = acct.get("projectedBalances") if isinstance(acct.get("projectedBalances"), dict) else {}

    liquidation = _as_float(cb.get("liquidationValue")) or _as_float(pv.get("liquidationValue")) or _as_float(acct.get("liquidationValue"))
    cash = (
        _as_float(cb.get("cashBalance"))
        or _as_float(cb.get("cashAvailableForTrading"))
        or _as_float(cb.get("cashAvailableForWithdrawal"))
        or _as_float(acct.get("cashBalance"))
    )
    buying_power = _as_float(cb.get("buyingPower")) or _as_float(cb.get("dayTradingBuyingPower")) or _as_float(ib.get("buyingPower")) or _as_float(acct.get("buyingPower"))
    return liquidation, cash, buying_power


def _parse_positions(acct: Dict[str, Any]) -> List[Dict[str, Any]]:
    pos = acct.get("positions")
    if isinstance(pos, list):
        return [p for p in pos if isinstance(p, dict)]
    return []


def _pos_symbol(p: Dict[str, Any]) -> str:
    inst = p.get("instrument")
    if isinstance(inst, dict):
        sym = inst.get("symbol") or inst.get("underlyingSymbol") or ""
        if sym:
            return str(sym).strip().upper()
    sym2 = p.get("symbol") or ""
    return str(sym2).strip().upper()


def _pos_asset_type(p: Dict[str, Any]) -> str:
    inst = p.get("instrument")
    if isinstance(inst, dict):
        at = inst.get("assetType") or inst.get("type") or ""
        if at:
            return str(at).strip().upper()
    return ""


def _pos_qtys(p: Dict[str, Any]) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    lq = _as_float(p.get("longQuantity"))
    sq = _as_float(p.get("shortQuantity"))
    if lq is None and sq is None:
        q = _as_float(p.get("quantity"))
        if q is not None:
            return (q if q > 0 else 0.0), (abs(q) if q < 0 else 0.0), q
        return None, None, None
    lq2 = lq or 0.0
    sq2 = sq or 0.0
    net = lq2 - sq2
    return lq2, sq2, net


def _pos_avg_price(p: Dict[str, Any]) -> Optional[float]:
    return _as_float(p.get("averagePrice")) or _as_float(p.get("avgPrice"))


def _pos_market_value(p: Dict[str, Any]) -> Optional[float]:
    return _as_float(p.get("marketValue"))


def _pos_day_pl(p: Dict[str, Any]) -> Optional[float]:
    return _as_float(p.get("currentDayProfitLoss"))


def _pos_open_pl(p: Dict[str, Any]) -> Optional[float]:
    return _as_float(p.get("longOpenProfitLoss")) or _as_float(p.get("shortOpenProfitLoss")) or _as_float(p.get("openProfitLoss"))


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
    cfg_acct = ((cfg.get("broker", {}) or {}).get("account") or "").strip()
    journal_db = args.journal_db or _journal_db_default()
    acct_hash, acct_num = _resolve_account_hash(args.account, cfg_acct, journal_db)
    acct_label = acct_num or (acct_hash[:8] + "…")

    days = int(args.days or 14)
    if days <= 0:
        days = 14

    if days > 180 and not bool(args.force):
        print(f"[sync] NOTE: capping days {days} -> 180 (use --force to override)")
        days = 180

    chunk_days = int(args.chunk_days or 3)
    if chunk_days <= 0:
        chunk_days = 3

    end_d = date.today()
    start_d = end_d - timedelta(days=days)

    types_csv = str(args.types or "").strip()
    types_list = _expand_types(types_csv)

    write_mode = _validate_write_mode(getattr(args, "write_mode", "append"))
    also_raw = bool(getattr(args, "also_raw", False))
    symbol_filter = str(args.symbol or "").strip().upper()

    session = _make_session()

    # ---- Phase 1: fetch from Schwab (no lock held) ----
    total_rows = 0
    cur = start_d
    fetched_rows: List[Dict[str, Any]] = []

    while cur <= end_d:
        chunk_end = min(end_d, cur + timedelta(days=chunk_days - 1))
        if bool(args.debug):
            print(f"\n[sync] chunk {cur.isoformat()} -> {chunk_end.isoformat()}")

        try:
            rows = _call_transactions(
                session,
                account_hash=acct_hash,
                start_d=cur,
                end_d=chunk_end,
                symbol=symbol_filter,
                types_csv=",".join(types_list),
                debug=bool(args.debug),
            )
        except Exception as e:
            print(f"[sync] ERROR chunk {cur} -> {chunk_end}: {e}")
            cur = chunk_end + timedelta(days=1)
            continue

        total_rows += len(rows)
        fetched_rows.extend(rows)
        cur = chunk_end + timedelta(days=1)

    # Normalize rows once (still no lock held)
    fetched_at = _utc_now_naive()
    norm: List[Tuple[Any, ...]] = []
    for o in fetched_rows:
        txn_id = _pick_txn_id(o)
        txn_date = _pick_date(o)
        txn_type = _pick_type(o)
        symbol = _pick_symbol(o)

        amount = _as_float(o.get("amount") or o.get("netAmount"))
        quantity = _as_float(o.get("quantity") or o.get("qty"))
        price = _as_float(o.get("price"))

        norm.append(
            (
                acct_hash,
                str(txn_id),
                fetched_at,
                txn_date,
                txn_type,
                symbol,
                amount,
                quantity,
                price,
                json.dumps(o, ensure_ascii=False),
            )
        )

    write_raw = (write_mode in ("append", "override")) or (write_mode == "upsert" and also_raw)
    write_latest = (write_mode == "upsert")

    run_id = os.getenv("TGPS_RUN_ID", "")
    try:
        with ledger_write_lock(str(ledger), run_id=run_id, step="fills_mgt.sync"):
            con = _connect_attached(ledger)
            try:
                _ensure_broker_transactions_table(con)
                if write_latest:
                    _ensure_broker_transactions_latest_table(con)

                con.execute("BEGIN TRANSACTION;")
                deleted = 0
                try:
                    if write_mode == "override":
                        q = """
                        DELETE FROM ledger.lcl.broker_transactions_raw
                        WHERE account_hash = ?
                          AND txn_date BETWEEN ? AND ?
                          AND upper(txn_type) IN ({types})
                        """.format(types=",".join(["?"] * len(types_list)))
                        params: List[Any] = [acct_hash, start_d, end_d] + [t.upper() for t in types_list]
                        if symbol_filter:
                            q += " AND upper(symbol) = ?"
                            params.append(symbol_filter)

                        try:
                            deleted = con.execute(q, params).rowcount
                        except Exception:
                            deleted = 0

                        print(
                            f"[sync] write_mode=override deleted_rows={deleted} window={start_d}..{end_d} "
                            f"types={','.join(types_list)} symbol={symbol_filter or '(any)'}"
                        )

                    raw_written = 0
                    latest_upserts = 0

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

                    if write_latest and norm:
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
                            [
                                (r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8], r[9])
                                for r in norm
                            ],
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
                    f"[sync] account={acct_label} days={days} chunk_days={chunk_days} types={','.join(types_list)} "
                    f"write_mode={write_mode} also_raw={also_raw} rows_from_api={total_rows} "
                    f"raw_written={raw_written if write_raw else 0} latest_upserts={latest_upserts if write_latest else 0}"
                )
                return 0
            finally:
                con.close()

    except LockHeldError as e:
        raise SystemExit(f"❌ Ledger write lock is held. {e}") from e


def cmd_txns(args: argparse.Namespace) -> int:
    repo = _repo_root()
    user_root = _user_root(repo)
    ledger = _ledger_path(user_root)
    if not ledger.exists():
        raise SystemExit(f"❌ Ledger not found: {ledger}")

    source = _validate_source(getattr(args, "source", "raw"))

    con = _connect_attached(ledger)
    try:
        days = int(args.days or 30)
        if days <= 0:
            days = 30
        cutoff = _utc_now_naive() - timedelta(days=days)

        if source == "latest":
            _ensure_broker_transactions_latest_table(con)
            rows = con.execute(
                """
                SELECT last_fetched_at, txn_id, txn_date, txn_type, symbol, amount, quantity, price
                FROM ledger.lcl.broker_transactions_latest
                WHERE last_fetched_at >= ?
                ORDER BY last_fetched_at DESC
                LIMIT ?
                """,
                [cutoff, int(args.limit)],
            ).fetchall()
            print(f"[txns] source=latest rows={len(rows)}")
        else:
            _ensure_broker_transactions_table(con)
            rows = con.execute(
                """
                SELECT fetched_at, txn_id, txn_date, txn_type, symbol, amount, quantity, price
                FROM ledger.lcl.broker_transactions_raw
                WHERE fetched_at >= ?
                QUALIFY row_number() OVER (PARTITION BY txn_id ORDER BY fetched_at DESC) = 1
                ORDER BY fetched_at DESC
                LIMIT ?
                """,
                [cutoff, int(args.limit)],
            ).fetchall()
            print(f"[txns] source=raw rows={len(rows)} (latest snapshot per txn_id)")

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

    source = _validate_source(getattr(args, "source", "raw"))
    txn_id = str(args.txn_id)

    con = _connect_attached(ledger)
    try:
        if source == "latest":
            _ensure_broker_transactions_latest_table(con)
            r = con.execute(
                """
                SELECT txn_json
                FROM ledger.lcl.broker_transactions_latest
                WHERE txn_id=?
                LIMIT 1
                """,
                [txn_id],
            ).fetchone()
        else:
            _ensure_broker_transactions_table(con)
            r = con.execute(
                """
                SELECT txn_json
                FROM ledger.lcl.broker_transactions_raw
                WHERE txn_id=?
                ORDER BY fetched_at DESC
                LIMIT 1
                """,
                [txn_id],
            ).fetchone()

        if not r:
            raise SystemExit(f"Transaction not found in cache: {txn_id}. Run: fills_mgt sync")
        print(r[0])
        return 0
    finally:
        con.close()


def cmd_snapshot(args: argparse.Namespace) -> int:
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

    session = _make_session()
    fetched_at = _utc_now_naive()

    payload = _call_account_snapshot(
        session,
        account_hash=acct_hash,
        fields_csv=str(args.fields or "positions"),
        debug=bool(args.debug),
    )

    acct = _extract_securities_account(payload)
    liquidation, cash, buying_power = _parse_balances(acct)
    positions = _parse_positions(acct)

    run_id = os.getenv("TGPS_RUN_ID", "")
    try:
        with ledger_write_lock(str(ledger), run_id=run_id, step="fills_mgt.snapshot"):
            con = _connect_attached(ledger)
            try:
                _ensure_broker_account_snapshot_table(con)
                _ensure_broker_positions_snapshot_table(con)

                con.execute("BEGIN TRANSACTION;")
                try:
                    con.execute(
                        """
                        INSERT INTO ledger.lcl.broker_account_snapshots_raw
                          (account_hash, fetched_at, liquidation_value, cash_balance, buying_power, snapshot_json)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        [
                            acct_hash,
                            fetched_at,
                            liquidation,
                            cash,
                            buying_power,
                            json.dumps(payload, ensure_ascii=False),
                        ],
                    )

                    wrote_pos = 0
                    for p in positions:
                        sym = _pos_symbol(p)
                        at = _pos_asset_type(p)
                        lq, sq, net = _pos_qtys(p)
                        ap = _pos_avg_price(p)
                        mv = _pos_market_value(p)
                        dpl = _pos_day_pl(p)
                        opl = _pos_open_pl(p)

                        if not sym:
                            continue

                        con.execute(
                            """
                            INSERT INTO ledger.lcl.broker_positions_snapshots
                              (account_hash, fetched_at, symbol, asset_type, long_qty, short_qty, net_qty,
                               avg_price, market_value, day_pl, open_pl, pos_json)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            [
                                acct_hash,
                                fetched_at,
                                sym,
                                at,
                                lq,
                                sq,
                                net,
                                ap,
                                mv,
                                dpl,
                                opl,
                                json.dumps(p, ensure_ascii=False),
                            ],
                        )
                        wrote_pos += 1

                    con.execute("COMMIT;")
                except Exception:
                    try:
                        con.execute("ROLLBACK;")
                    except Exception:
                        pass
                    raise

                print(
                    f"[snapshot] account={acct_label} fetched_at={fetched_at} "
                    f"liq={liquidation} cash={cash} bp={buying_power} positions_written={wrote_pos}"
                )
                return 0
            finally:
                con.close()

    except LockHeldError as e:
        raise SystemExit(f"❌ Ledger write lock is held. {e}") from e


def cmd_positions(args: argparse.Namespace) -> int:
    repo = _repo_root()
    user_root = _user_root(repo)
    ledger = _ledger_path(user_root)
    if not ledger.exists():
        raise SystemExit(f"❌ Ledger not found: {ledger}")

    con = _connect_attached(ledger)
    try:
        days = int(args.days or 7)
        if days <= 0:
            days = 7
        cutoff = _utc_now_naive() - timedelta(days=days)

        rows = con.execute(
            """
            SELECT fetched_at, symbol, asset_type, net_qty, avg_price, market_value, day_pl, open_pl
            FROM ledger.lcl.broker_positions_snapshots
            WHERE fetched_at >= ?
            QUALIFY row_number() OVER (PARTITION BY symbol, asset_type ORDER BY fetched_at DESC) = 1
            ORDER BY market_value DESC NULLS LAST
            LIMIT ?
            """,
            [cutoff, int(args.limit)],
        ).fetchall()

        print(f"[positions] rows={len(rows)} (latest snapshot per symbol)")
        for r in rows:
            print(" -", " | ".join("" if v is None else str(v) for v in r))
        return 0
    finally:
        con.close()


def cmd_pnl(args: argparse.Namespace) -> int:
    repo = _repo_root()
    user_root = _user_root(repo)
    ledger = _ledger_path(user_root)
    if not ledger.exists():
        raise SystemExit(f"❌ Ledger not found: {ledger}")

    days = int(args.days or 30)
    if days <= 0:
        days = 30
    cutoff = _utc_now_naive() - timedelta(days=days)

    con = _connect_attached(ledger)
    try:
        snaps = con.execute(
            """
            SELECT fetched_at, liquidation_value, cash_balance
            FROM ledger.lcl.broker_account_snapshots_raw
            WHERE fetched_at >= ?
            ORDER BY fetched_at ASC
            """,
            [cutoff],
        ).fetchall()

        if len(snaps) < 2:
            raise SystemExit("[pnl] Need at least 2 account snapshots in the lookback window. Run: fills_mgt snapshot daily (or twice).")

        t0, liq0, cash0 = snaps[0]
        t1, liq1, cash1 = snaps[-1]

        delta_liq = (liq1 - liq0) if (liq0 is not None and liq1 is not None) else None
        delta_cash = (cash1 - cash0) if (cash0 is not None and cash1 is not None) else None

        cf_types = _split_csv(str(args.cashflow_types or "").strip())
        net_external = None

        txn_source = _validate_source(getattr(args, "txn_source", "auto"))
        if txn_source == "auto":
            _ensure_broker_transactions_table(con)
            cnt_raw = con.execute(
                "SELECT count(*) FROM ledger.lcl.broker_transactions_raw WHERE fetched_at >= ?",
                [cutoff],
            ).fetchone()[0]
            txn_source = "raw" if int(cnt_raw or 0) > 0 else "latest"

        if cf_types:
            cf_types_u = [t.upper() for t in cf_types]
            if txn_source == "latest":
                _ensure_broker_transactions_latest_table(con)
                q = (
                    "SELECT sum(amount) "
                    "FROM ledger.lcl.broker_transactions_latest "
                    "WHERE last_fetched_at >= ? AND upper(txn_type) IN (" + ",".join(["?"] * len(cf_types_u)) + ")"
                )
                r = con.execute(q, [cutoff] + cf_types_u).fetchone()
            else:
                _ensure_broker_transactions_table(con)
                q = (
                    "SELECT sum(amount) "
                    "FROM ledger.lcl.broker_transactions_raw "
                    "WHERE fetched_at >= ? AND upper(txn_type) IN (" + ",".join(["?"] * len(cf_types_u)) + ")"
                )
                r = con.execute(q, [cutoff] + cf_types_u).fetchone()

            net_external = _as_float(r[0] if r else None)

        perf = None
        if delta_liq is not None:
            perf = delta_liq - (net_external or 0.0) if net_external is not None else delta_liq

        pos_r = con.execute(
            """
            SELECT
              max(fetched_at) AS t,
              sum(open_pl) AS open_pl,
              sum(day_pl) AS day_pl,
              sum(market_value) AS mkt
            FROM ledger.lcl.broker_positions_snapshots
            WHERE fetched_at >= ?
            """,
            [cutoff],
        ).fetchone()
        pos_t, open_pl, day_pl, mkt = (pos_r if pos_r else (None, None, None, None))

        print("[pnl]")
        print(f"  window_days={days}")
        print(f"  snapshot_start={t0}  liq={liq0}  cash={cash0}")
        print(f"  snapshot_end  ={t1}  liq={liq1}  cash={cash1}")
        print(f"  delta_liq={delta_liq}  delta_cash={delta_cash}")

        if cf_types:
            print(f"  txn_source={txn_source}")
            print(f"  external_cashflow_types={','.join(cf_types)}  net_external={net_external}")
            print(f"  performance_estimate=(delta_liq - net_external)={perf}")
        else:
            print("  external_cashflow_types=(none)  (tip: run fills_mgt sync with types that include deposits/withdrawals and pass --cashflow-types)")
            print(f"  performance_estimate=(delta_liq)={perf}")

        if pos_t is not None:
            print(f"  positions_snapshot={pos_t}  market_value_sum={mkt}  open_pl_sum={open_pl}  day_pl_sum={day_pl}")
        else:
            print("  positions_snapshot=(none in window)  (run: fills_mgt snapshot)")
        return 0
    finally:
        con.close()


def cmd_types(args: argparse.Namespace) -> int:
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

    days = int(args.days or 180)
    if days <= 0:
        days = 180
    cutoff = _utc_now_naive() - timedelta(days=days)

    source = _validate_source(getattr(args, "source", "auto"))

    con = _connect_attached(ledger)
    try:
        chosen = source
        if source == "auto":
            have_latest = _table_exists(con, "ledger.lcl.broker_transactions_latest")
            have_raw = _table_exists(con, "ledger.lcl.broker_transactions_raw")
            if have_latest:
                cnt = con.execute(
                    "SELECT count(*) FROM ledger.lcl.broker_transactions_latest WHERE account_hash=? AND last_fetched_at >= ?",
                    [acct_hash, cutoff],
                ).fetchone()[0]
                if int(cnt or 0) > 0:
                    chosen = "latest"
                else:
                    chosen = "raw" if have_raw else "latest"
            else:
                chosen = "raw"

        min_count = int(getattr(args, "min_count", 1) or 1)
        if min_count < 1:
            min_count = 1

        if chosen == "latest":
            _ensure_broker_transactions_latest_table(con)
            rows = con.execute(
                """
                SELECT
                  upper(txn_type) AS txn_type,
                  count(*)         AS txns,
                  min(coalesce(txn_date, cast(last_fetched_at as date))) AS min_date,
                  max(coalesce(txn_date, cast(last_fetched_at as date))) AS max_date,
                  max(last_fetched_at) AS last_fetched_at
                FROM ledger.lcl.broker_transactions_latest
                WHERE account_hash = ?
                  AND last_fetched_at >= ?
                GROUP BY 1
                HAVING count(*) >= ?
                ORDER BY txns DESC, txn_type ASC
                """,
                [acct_hash, cutoff, min_count],
            ).fetchall()
        else:
            _ensure_broker_transactions_table(con)
            rows = con.execute(
                """
                SELECT
                  upper(txn_type) AS txn_type,
                  count(distinct txn_id) AS txns,
                  count(*)              AS rows,
                  min(coalesce(txn_date, cast(fetched_at as date))) AS min_date,
                  max(coalesce(txn_date, cast(fetched_at as date))) AS max_date,
                  max(fetched_at)       AS last_fetched_at
                FROM ledger.lcl.broker_transactions_raw
                WHERE account_hash = ?
                  AND fetched_at >= ?
                GROUP BY 1
                HAVING count(distinct txn_id) >= ?
                ORDER BY txns DESC, txn_type ASC
                """,
                [acct_hash, cutoff, min_count],
            ).fetchall()

        print(f"[types] account={acct_label} source={chosen} lookback_days={days} cutoff={cutoff}")

        if not rows:
            print("[types] No transactions found in cache for this window/source.")
            print("        Tip: run sync broadly, e.g.:")
            print("        python -m scripts.tgps_user.fills_mgt sync --days 60 --types ALL --write-mode upsert --also-raw")
            return 0

        if chosen == "latest":
            for (tt, txns, d0, d1, lf) in rows:
                print(f" - {tt} | txns={txns} | range={d0}..{d1} | last_fetched_at={lf}")
        else:
            for (tt, txns, nrows, d0, d1, lf) in rows:
                print(f" - {tt} | txns={txns} | rows={nrows} | range={d0}..{d1} | last_fetched_at={lf}")

        observed = [r[0] for r in rows if r and r[0]]
        candidates = []
        for t in observed:
            u = str(t).upper()
            if any(x in u for x in ("ACH_", "WIRE_", "CASH_", "ELECTRONIC", "JOURNAL")):
                candidates.append(u)

        seen = set()
        candidates2 = []
        for t in candidates:
            if t not in seen:
                candidates2.append(t)
                seen.add(t)

        if candidates2:
            print("[types] cashflow-like candidates observed:")
            print("        " + ",".join(candidates2))
            print("[types] (baseline defaults you can start with):")
            print("        " + ",".join(DEFAULT_CASHFLOW_TYPES))
        else:
            print("[types] No obvious cashflow-like types observed in this window.")
            print("        Baseline defaults:")
            print("        " + ",".join(DEFAULT_CASHFLOW_TYPES))

        preset = set(ALL_TXN_TYPES)
        unknown = sorted([t for t in set(observed) if t not in preset])
        if unknown:
            print("[types] NOTE: types observed but not in ALL_TXN_TYPES preset:")
            print("        " + ",".join(unknown))

        return 0
    finally:
        con.close()


# ----------------------------
# CLI
# ----------------------------
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="tgps-user Fills/Transactions + Snapshot (sync/txns/show/snapshot/positions/pnl/types)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("sync", help="Pull Schwab account transactions and store snapshots locally")
    p.add_argument("--days", type=int, default=14, help="Lookback days (default 14; capped unless --force)")
    p.add_argument("--chunk-days", type=int, default=3, help="Chunk size in days (default 3)")
    p.add_argument("--symbol", default="", help="Optional symbol filter (if Schwab supports it)")
    p.add_argument(
        "--types",
        default="TRADE,RECEIVE_AND_DELIVER,DIVIDEND_OR_INTEREST,ACH_RECEIPT,ACH_DISBURSEMENT,CASH_RECEIPT,CASH_DISBURSEMENT,ELECTRONIC_FUND,WIRE_OUT,WIRE_IN,JOURNAL,MEMORANDUM,MARGIN_CALL,MONEY_MARKET,SMA_ADJUSTMENT",
        help="Transaction types (comma-separated). REQUIRED by Schwab. Use ALL for preset list.",
    )
    p.add_argument("--write-mode", default="append", choices=["append", "override", "upsert"], help="append|override|upsert (default append)")
    p.add_argument("--also-raw", action="store_true", help="Only for --write-mode upsert: also append to raw audit table")
    p.add_argument("--account", default=None, help="Account number (e.g. 41472449) or account hash")
    p.add_argument("--journal-db", default="", help=f"Journal DuckDB path (default: {_journal_db_default()})")
    p.add_argument("--force", action="store_true", help="Allow longer requests (may fail/time out)")
    p.add_argument("--debug", action="store_true", help="Debug prints (URLs/params)")
    p.set_defaults(func=cmd_sync)

    p = sub.add_parser("txns", help="List cached transactions")
    p.add_argument("--days", type=int, default=30, help="Lookback days in local cache (default 30)")
    p.add_argument("--limit", type=int, default=200, help="Max rows (default 200)")
    p.add_argument("--source", default="raw", choices=["raw", "latest"], help="Read from raw (default) or latest (upsert table)")
    p.set_defaults(func=cmd_txns)

    p = sub.add_parser("show", help="Show cached raw JSON for a transaction")
    p.add_argument("--txn-id", required=True, help="Transaction id")
    p.add_argument("--source", default="raw", choices=["raw", "latest"], help="Read from raw (default) or latest (upsert table)")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("snapshot", help="Pull Schwab account snapshot (balances + positions) and store it")
    p.add_argument("--fields", default="positions", help="fields query param (default: positions)")
    p.add_argument("--account", default=None, help="Account number (e.g. 41472449) or account hash")
    p.add_argument("--journal-db", default="", help=f"Journal DuckDB path (default: {_journal_db_default()})")
    p.add_argument("--debug", action="store_true", help="Debug prints (URLs/params)")
    p.set_defaults(func=cmd_snapshot)

    p = sub.add_parser("positions", help="List latest cached positions (from account snapshots)")
    p.add_argument("--days", type=int, default=7, help="Lookback days for snapshots (default 7)")
    p.add_argument("--limit", type=int, default=200, help="Max rows (default 200)")
    p.set_defaults(func=cmd_positions)

    p = sub.add_parser("pnl", help="Quick P&L view using account snapshots (+ optional external cashflows)")
    p.add_argument("--days", type=int, default=30, help="Lookback days (default 30)")
    p.add_argument(
        "--cashflow-types",
        default="",
        help="Comma-separated txn types to treat as external cashflows (deposit/withdraw). Example: ACH_RECEIPT,ACH_DISBURSEMENT,WIRE_IN,WIRE_OUT",
    )
    p.add_argument("--txn-source", default="auto", choices=["auto", "raw", "latest"], help="Which transaction table to use for cashflow calc (default auto)")
    p.set_defaults(func=cmd_pnl)

    p = sub.add_parser("types", help="Show distinct txn_type values observed in your local cache")
    p.add_argument("--days", type=int, default=180, help="Lookback days in local cache (default 180)")
    p.add_argument("--source", default="auto", choices=["auto", "raw", "latest"], help="Read from raw/latest (default auto)")
    p.add_argument("--min-count", type=int, default=1, help="Only show types with at least this many txns (default 1)")
    p.add_argument("--account", default=None, help="Account number (e.g. 41472449) or account hash")
    p.add_argument("--journal-db", default="", help=f"Journal DuckDB path (default: {_journal_db_default()})")
    p.set_defaults(func=cmd_types)

    return ap


def main() -> int:
    args = build_parser().parse_args()
    if getattr(args, "journal_db", "") == "":
        args.journal_db = _journal_db_default()
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
