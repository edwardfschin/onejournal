#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/journal/fetch_orders_live.py
Version: 0.3.3
Updated: 2026-01-07 (SGT)

Purpose
-------
Fetch LIVE open orders from Schwab Trader API and store:
  1) the latest snapshot (per account) in journal.open_orders_live
  2) a lightweight append-only history of open orders in journal.open_orders_snapshots
  3) the raw Schwab payload (source of truth) per API call in journal.orders_raw

Notes
-----
- Schwab "orders by account" requires fromEnteredTime and toEnteredTime.
- Status filter is OPTIONAL. If omitted, Schwab returns orders across statuses
  for the window; we then filter what we consider "open" for open_orders_live.

- journal.open_orders_live is intended to be "actionable" open orders only.
  Anything not open-status (CANCELED/REPLACED/FILLED/etc.) stays in orders_raw
  (raw truth), not in open_orders_live.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple
from zoneinfo import ZoneInfo

import duckdb
import requests

from client.schwab_admin import (
    AuthClient,
    CLIENT_CORRELID,
    RESOURCE_VERSION,
    SCHWAB_BASE,
    TokenStore,
)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

OPEN_STATUSES = {
    "WORKING",
    "PENDING_ACTIVATION",
    "QUEUED",
    "AWAITING_PARENT_ORDER",   # <-- needed for Trigger->OCO child legs
}


DEFAULT_LOOKBACK_DAYS = int(os.environ.get("TGPS_ORDERS_LOOKBACK_DAYS", "60"))
MAX_LOOKBACK_DAYS = 60
DEFAULT_MAX_RESULTS = int(os.environ.get("TGPS_ORDERS_MAX_RESULTS", "3000"))

FORCE_STATUS = os.environ.get("TGPS_ORDERS_STATUS", "").strip() or None
WRITE_LIVE = os.environ.get("TGPS_ORDERS_WRITE_LIVE", "1").strip() != "0"

ET = ZoneInfo("America/New_York")

# ---------------------------------------------------------------------------
# CLI (was missing -> NameError)
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Fetch Schwab orders into DuckDB (live open snapshot).")
    ap.add_argument("--from", dest="from_date", default=None, help="From date in YYYY-MM-DD (ET). Optional.")
    ap.add_argument("--to", dest="to_date", default=None, help="To date in YYYY-MM-DD (ET). Optional.")
    ap.add_argument(
        "--lookback-days",
        dest="lookback_days",
        type=int,
        default=DEFAULT_LOOKBACK_DAYS,
        help=f"Lookback days if --from not given (default {DEFAULT_LOOKBACK_DAYS}).",
    )
    ap.add_argument("--debug", action="store_true", help="Verbose debug prints.")
    return ap.parse_args()


def _compute_window_et(*, from_date: Optional[str], to_date: Optional[str], lookback_days: int) -> Tuple[str, str]:
    """
    Convert date window (ET) -> ISO timestamps in UTC w/ offset, suitable for Schwab params.

    Rules:
    - If to_date is omitted: use 'today' in ET.
    - If from_date is omitted: use (to_date - lookback_days).
    - from timestamp is start-of-day ET (00:00:00)
    - to timestamp is end-of-day ET (23:59:59)
    """
    def _parse_ymd(s: str) -> date:
        return date.fromisoformat(s)

    if to_date:
        to_d = _parse_ymd(to_date)
    else:
        to_d = datetime.now(ET).date()

    if from_date:
        from_d = _parse_ymd(from_date)
    else:
        from_d = to_d - timedelta(days=int(lookback_days))

    start_et = datetime.combine(from_d, time(0, 0, 0), tzinfo=ET)
    end_et = datetime.combine(to_d, time(23, 59, 59), tzinfo=ET)

    start_utc = start_et.astimezone(timezone.utc)
    end_utc = end_et.astimezone(timezone.utc)

    return start_utc.isoformat(), end_utc.isoformat()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def iter_order_tree(
    orders: Iterable[Dict[str, Any]],
) -> Iterator[Tuple[Dict[str, Any], Optional[int], Optional[int], int]]:
    """
    Yield: (order_obj, parent_order_id, root_order_id, depth)
    """

    def walk(
        ord_obj: Dict[str, Any],
        parent_id: Optional[int],
        root_id: Optional[int],
        depth: int,
    ) -> Iterator[Tuple[Dict[str, Any], Optional[int], Optional[int], int]]:
        oid = ord_obj.get("orderId")
        try:
            oid_int = int(oid) if oid is not None else None
        except Exception:
            oid_int = None

        if root_id is None:
            root_id = oid_int

        yield ord_obj, parent_id, root_id, depth

        children = ord_obj.get("childOrderStrategies") or []
        if isinstance(children, list) and children:
            for ch in children:
                if isinstance(ch, dict):
                    yield from walk(ch, oid_int, root_id, depth + 1)

    for top in orders:
        if not isinstance(top, dict):
            continue
        top_oid = top.get("orderId")
        try:
            top_oid_int = int(top_oid) if top_oid is not None else None
        except Exception:
            top_oid_int = None
        yield from walk(top, None, top_oid_int, 0)


def get_db_path() -> str:
    default = os.path.expanduser("~/tgps-project/data/journal/tgps_trades.duckdb")
    return os.environ.get("TGPS_JOURNAL_DB", default)


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def iso_to_dt(value: str | None) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        v = value.strip()
        if v.endswith("Z"):
            v = v[:-1] + "+00:00"
        if len(v) >= 5 and (v[-5] in ["+", "-"]) and v[-3] != ":":
            v = v[:-2] + ":" + v[-2:]
        dt = datetime.fromisoformat(v)
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    except Exception:
        return None


def parse_occ(symbol: str) -> Tuple[str | None, date | None, float | None, str | None]:
    if not symbol or not isinstance(symbol, str):
        return None, None, None, None

    s = symbol
    underlying = s[:6].strip() or None
    tail = s[6:].strip()
    if len(tail) < 15:
        return underlying, None, None, None

    date6 = tail[:6]
    cp = tail[6]
    strike8 = tail[7:15]

    try:
        yy = int(date6[0:2])
        mm = int(date6[2:4])
        dd = int(date6[4:6])
        expiry = date(2000 + yy, mm, dd)
    except Exception:
        expiry = None

    try:
        strike = int(strike8) / 1000.0
    except Exception:
        strike = None

    put_call = "CALL" if cp.upper() == "C" else ("PUT" if cp.upper() == "P" else None)
    return underlying, expiry, strike, put_call


# ---------------------------------------------------------------------------
# DB setup (idempotent)
# ---------------------------------------------------------------------------


def ensure_tables(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("CREATE SCHEMA IF NOT EXISTS journal;")

    con.execute(
        """
        CREATE TABLE IF NOT EXISTS journal.open_orders_live (
            account_hash     VARCHAR NOT NULL,
            account_id       VARCHAR,
            order_id         BIGINT  NOT NULL,
            leg_index        INTEGER NOT NULL,

            status           VARCHAR,
            entered_time     TIMESTAMP,
            close_time       TIMESTAMP,
            order_type       VARCHAR,
            order_strategy   VARCHAR,
            complex_strategy VARCHAR,
            duration         VARCHAR,
            session          VARCHAR,

            instruction      VARCHAR,
            quantity         DOUBLE,
            filled_quantity  DOUBLE,
            remaining_qty    DOUBLE,
            price            DOUBLE,
            stop_price       DOUBLE,

            symbol           VARCHAR,
            asset_type       VARCHAR,
            underlying       VARCHAR,
            expiry           DATE,
            strike           DOUBLE,
            put_call         VARCHAR,

            raw_json         JSON,
            updated_at       TIMESTAMP NOT NULL,
            source           VARCHAR NOT NULL,

            parent_order_id  BIGINT,
            client_order_id  VARCHAR,
            order_tag        VARCHAR,

            leg_id           BIGINT,
            instrument_id    BIGINT,
            tag              VARCHAR,
            cancelable       BOOLEAN,
            editable         BOOLEAN,
            root_order_id    BIGINT,
            depth            INTEGER
        );
        """
    )

    con.execute(
        """
        CREATE TABLE IF NOT EXISTS journal.open_orders_snapshots (
            snapshot_ts      TIMESTAMP NOT NULL,
            account_hash     VARCHAR   NOT NULL,
            account_id       VARCHAR,
            order_id         BIGINT    NOT NULL,
            leg_index        INTEGER   NOT NULL,

            leg_id           BIGINT,
            instrument_id    BIGINT,

            status           VARCHAR,
            entered_time     TIMESTAMP,
            close_time       TIMESTAMP,
            order_type       VARCHAR,
            order_strategy   VARCHAR,
            complex_strategy VARCHAR,
            duration         VARCHAR,
            session          VARCHAR,

            instruction      VARCHAR,
            quantity         DOUBLE,
            filled_quantity  DOUBLE,
            remaining_qty    DOUBLE,
            price            DOUBLE,
            stop_price       DOUBLE,

            symbol           VARCHAR,
            asset_type       VARCHAR,
            underlying       VARCHAR,
            expiry           DATE,
            strike           DOUBLE,
            put_call         VARCHAR,

            tag              VARCHAR,
            cancelable       BOOLEAN,
            editable         BOOLEAN,

            orders_payload_sha256 VARCHAR,
            source           VARCHAR NOT NULL,
            parent_order_id  BIGINT,
            root_order_id    BIGINT,
            depth            INTEGER
        );
        """
    )

    con.execute(
        """
        CREATE TABLE IF NOT EXISTS journal.accounts (
            account_hash    VARCHAR NOT NULL,
            account_number  VARCHAR NOT NULL
        );
        """
    )

    con.execute(
        """
        CREATE TABLE IF NOT EXISTS journal.orders_raw (
            account_hash    VARCHAR   NOT NULL,
            fetched_at      TIMESTAMP NOT NULL DEFAULT now(),
            from_iso        VARCHAR   NOT NULL,
            to_iso          VARCHAR   NOT NULL,
            payload         JSON      NOT NULL,

            endpoint        VARCHAR,
            status_filter   VARCHAR,
            http_status     INTEGER,
            payload_sha256  VARCHAR,
            source          VARCHAR
        );
        """
    )

    def _existing_cols(table_name: str) -> set[str]:
        rows = con.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema='journal' AND table_name=?
            """,
            [table_name],
        ).fetchall()
        return {r[0] for r in rows}

    def _ensure_cols(table_name: str, wanted: dict[str, str]) -> None:
        cols = _existing_cols(table_name)
        for col, typ in wanted.items():
            if col not in cols:
                con.execute(f"ALTER TABLE journal.{table_name} ADD COLUMN {col} {typ};")

    _ensure_cols(
        "open_orders_live",
        {
            "parent_order_id": "BIGINT",
            "client_order_id": "VARCHAR",
            "order_tag": "VARCHAR",
            "leg_id": "BIGINT",
            "instrument_id": "BIGINT",
            "tag": "VARCHAR",
            "cancelable": "BOOLEAN",
            "editable": "BOOLEAN",
            "root_order_id": "BIGINT",
            "depth": "INTEGER",
        },
    )

    _ensure_cols(
        "open_orders_snapshots",
        {
            "leg_id": "BIGINT",
            "instrument_id": "BIGINT",
            "tag": "VARCHAR",
            "cancelable": "BOOLEAN",
            "editable": "BOOLEAN",
            "orders_payload_sha256": "VARCHAR",
            "parent_order_id": "BIGINT",
            "root_order_id": "BIGINT",
            "depth": "INTEGER",
        },
    )

    _ensure_cols(
        "orders_raw",
        {
            "endpoint": "VARCHAR",
            "status_filter": "VARCHAR",
            "http_status": "INTEGER",
            "payload_sha256": "VARCHAR",
            "source": "VARCHAR",
        },
    )

    con.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS ux_orders_raw_dedupe
        ON journal.orders_raw(account_hash, from_iso, to_iso, payload_sha256);
        """
    )
    con.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS ux_open_orders_live_leg
        ON journal.open_orders_live(account_hash, order_id, leg_index);
        """
    )
    con.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS ux_open_orders_live_legid
        ON journal.open_orders_live(account_hash, leg_id);
        """
    )
    con.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS ux_open_orders_snapshots
        ON journal.open_orders_snapshots(snapshot_ts, account_hash, order_id, leg_index);
        """
    )


# ---------------------------------------------------------------------------
# Account discovery
# ---------------------------------------------------------------------------


def fetch_accounts(con: duckdb.DuckDBPyConnection, session: requests.Session) -> List[Dict[str, Any]]:
    rows = con.execute(
        """
        SELECT account_hash, account_number
        FROM journal.accounts
        ORDER BY account_hash;
        """
    ).fetchall()
    cols = [d[0] for d in con.description]
    db_accounts = [dict(zip(cols, r)) for r in rows]

    if db_accounts:
        return db_accounts

    print("[fetch_orders_live] No accounts in journal.accounts, calling /accounts/accountNumbers …")
    base = SCHWAB_BASE.rstrip("/")
    url = f"{base}/trader/v1/accounts/accountNumbers"
    resp = session.get(url, timeout=20)
    resp.raise_for_status()
    data = resp.json() or []

    accounts: List[Dict[str, Any]] = []
    for acc in data:
        plain = acc.get("accountNumber")
        hv = acc.get("hashValue")
        if plain and hv:
            accounts.append({"account_hash": hv, "account_number": plain})

    if not accounts:
        print("[fetch_orders_live] /accounts/accountNumbers returned no usable accounts.")
        return []

    con.execute("DELETE FROM journal.accounts;")
    con.executemany(
        """
        INSERT INTO journal.accounts (account_hash, account_number)
        VALUES (?, ?);
        """,
        [(a["account_hash"], a["account_number"]) for a in accounts],
    )
    print(f"[fetch_orders_live] Saved {len(accounts)} account(s) into journal.accounts.")
    return accounts


# ---------------------------------------------------------------------------
# Schwab orders fetch
# ---------------------------------------------------------------------------


def fetch_orders_for_account(
    session: requests.Session,
    auth: AuthClient,
    account_hash: str,
    from_entered: str,
    to_entered: str,
    status: str | None = None,
    max_results: int | None = None,
) -> list[dict]:
    base = SCHWAB_BASE.rstrip("/")
    url = f"{base}/trader/v1/accounts/{account_hash}/orders"

    params: dict[str, Any] = {
        "fromEnteredTime": from_entered,
        "toEnteredTime": to_entered,
    }
    if status:
        params["status"] = status
    if max_results and max_results > 0:
        params["maxResults"] = max(1, min(int(max_results), 3000))

    def _do_request() -> requests.Response:
        st = params.get("status", "")
        mr = params.get("maxResults", "")
        print(f"[DEBUG] GET {url} status='{st}' maxResults='{mr}' from='{from_entered}' to='{to_entered}'")
        return session.get(url, params=params, timeout=30)

    resp = _do_request()

    if resp.status_code == 401:
        print("[fetch_orders_live] 401 Unauthorized – refreshing token …")
        auth.force_refresh()
        new_token = auth.get_access_token()
        session.headers["Authorization"] = f"Bearer {new_token}"
        resp = _do_request()

    resp.raise_for_status()
    data = resp.json() or []
    if isinstance(data, dict):
        return data.get("orders", [])
    return data


def save_debug_payload(account_hash: str, payload: Any) -> None:
    debug_dir = Path(os.path.expanduser("~/tgps-project/data/schwab/debug_orders"))
    ensure_dir(debug_dir)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    short = account_hash[:8]
    path = debug_dir / f"orders_{short}_{ts}.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    print(f"[DEBUG] Raw Schwab orders saved → {path}")


def flatten_orders(
    account_hash: str,
    account_id: str | None,
    orders: List[Dict[str, Any]],
    snapshot_ts: datetime,
) -> List[Tuple]:
    rows: List[Tuple] = []

    for ord_obj, parent_id, root_id, depth in iter_order_tree(orders):
        order_id = ord_obj.get("orderId")
        status = ord_obj.get("status")
        entered_time = iso_to_dt(ord_obj.get("enteredTime"))
        close_time = iso_to_dt(ord_obj.get("closeTime"))

        order_type = ord_obj.get("orderType")
        order_strategy = ord_obj.get("orderStrategyType")
        complex_strategy = ord_obj.get("complexOrderStrategyType")
        duration = ord_obj.get("duration")
        session = ord_obj.get("session")

        price = ord_obj.get("price")
        stop_price = ord_obj.get("stopPrice")

        filled_quantity = ord_obj.get("filledQuantity")
        remaining_qty = ord_obj.get("remainingQuantity")

        parent_order_id = parent_id
        root_order_id = root_id

        client_order_id = ord_obj.get("clientOrderId")
        order_tag = ord_obj.get("orderTag")

        tag = ord_obj.get("tag")
        cancelable = ord_obj.get("cancelable")
        editable = ord_obj.get("editable")

        legs = ord_obj.get("orderLegCollection") or []

        def _append_row(
            leg_index: int,
            instruction: str | None,
            quantity: Any,
            symbol: str | None,
            asset_type: str | None,
            underlying: str | None,
            expiry: date | None,
            strike: Any,
            put_call: str | None,
            leg_id: Any,
            instrument_id: Any,
        ) -> None:
            rows.append(
                (
                    account_hash,
                    account_id,
                    int(order_id) if order_id is not None else None,
                    int(leg_index),
                    status,
                    entered_time,
                    close_time,
                    order_type,
                    order_strategy,
                    complex_strategy,
                    duration,
                    session,
                    instruction,
                    quantity,
                    filled_quantity,
                    remaining_qty,
                    price,
                    stop_price,
                    symbol,
                    asset_type,
                    underlying,
                    expiry,
                    strike,
                    put_call,
                    json.dumps(ord_obj, ensure_ascii=False),
                    snapshot_ts,
                    "schwab_api",
                    int(parent_order_id) if parent_order_id is not None else None,
                    int(root_order_id) if root_order_id is not None else None,
                    int(depth) if depth is not None else None,
                    str(client_order_id) if client_order_id is not None else None,
                    str(order_tag) if order_tag is not None else None,
                    int(leg_id) if leg_id is not None else None,
                    int(instrument_id) if instrument_id is not None else None,
                    str(tag) if tag is not None else None,
                    bool(cancelable) if cancelable is not None else None,
                    bool(editable) if editable is not None else None,
                )
            )

        if not legs:
            continue

        for idx, leg in enumerate(legs):
            leg_id = leg.get("legId")
            instruction = leg.get("instruction")
            quantity = leg.get("quantity")

            instrument = leg.get("instrument", {}) or {}
            instrument_id = instrument.get("instrumentId")
            symbol = instrument.get("symbol")
            asset_type = instrument.get("assetType") or instrument.get("asset_type")

            underlying = None
            expiry = None
            strike = None
            put_call = None

            if asset_type and str(asset_type).upper() == "OPTION":
                put_call = instrument.get("putCall")
                strike = instrument.get("strikePrice") or instrument.get("strike")
                exp_raw = instrument.get("expirationDate")
                if isinstance(exp_raw, str) and len(exp_raw) >= 10:
                    try:
                        y, m, d = map(int, exp_raw[:10].split("-"))
                        expiry = date(y, m, d)
                    except Exception:
                        expiry = None

                occ_under, occ_exp, occ_strike, occ_pc = parse_occ(symbol or "")
                underlying = instrument.get("underlyingSymbol") or occ_under
                if expiry is None:
                    expiry = occ_exp
                if strike is None:
                    strike = occ_strike
                if put_call is None:
                    put_call = occ_pc
            else:
                underlying = symbol

            _append_row(
                leg_index=idx,
                instruction=instruction,
                quantity=quantity,
                symbol=symbol,
                asset_type=asset_type,
                underlying=underlying,
                expiry=expiry,
                strike=strike,
                put_call=put_call,
                leg_id=leg_id,
                instrument_id=instrument_id,
            )

    return rows


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    db_path = get_db_path()

    con = duckdb.connect(db_path)
    ensure_tables(con)

    store = TokenStore()
    auth = AuthClient(store)
    token = auth.get_access_token()

    correl = CLIENT_CORRELID or "tgps-cli"
    session = requests.Session()
    session.headers.update(
        {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Schwab-Resource-Version": RESOURCE_VERSION,
            "Schwab-Client-CorrelId": correl,
        }
    )

    accounts = fetch_accounts(con, session)
    if not accounts:
        print("[fetch_orders_live] No accounts available (DB+API both empty).")
        return

    snapshot_ts = datetime.now(timezone.utc).replace(tzinfo=None)
    total_rows = 0

    args = _parse_args()

    lookback = max(1, min(int(args.lookback_days), MAX_LOOKBACK_DAYS))
    from_entered, to_entered = _compute_window_et(
        from_date=args.from_date, to_date=args.to_date, lookback_days=lookback
    )
    if args.debug:
        print(
            f"[fetch_orders_live] window (ET): from={args.from_date or '(auto)'} to={args.to_date or '(auto)'} lookback={lookback}d"
        )
        print(f"[fetch_orders_live] window (UTC): from={from_entered} to={to_entered}")

    for acct in accounts:
        account_hash = acct["account_hash"]
        account_id = acct.get("account_number")

        print(f"[fetch_orders_live] Fetching orders for {account_id} ({account_hash[:8]}…)")

        try:
            orders = fetch_orders_for_account(
                session=session,
                auth=auth,
                account_hash=account_hash,
                from_entered=from_entered,
                to_entered=to_entered,
                status=FORCE_STATUS,
                max_results=DEFAULT_MAX_RESULTS,
            )

            payload_json = json.dumps(orders, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            payload_sha = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
            status_filter = FORCE_STATUS or "ALL"

            try:
                con.execute(
                    """
                    INSERT INTO journal.orders_raw
                    (account_hash, fetched_at, from_iso, to_iso, payload,
                     endpoint, status_filter, http_status, payload_sha256, source)
                    VALUES
                    (?, now(), ?, ?, CAST(? AS JSON),
                     ?, ?, ?, ?, ?);
                    """,
                    [
                        account_hash,
                        from_entered,
                        to_entered,
                        payload_json,
                        "/trader/v1/accounts/{hash}/orders",
                        status_filter,
                        200,
                        payload_sha,
                        "schwab/trader",
                    ],
                )
            except duckdb.ConstraintException:
                print("[fetch_orders_live] orders_raw duplicate (same payload/window) → ignored")

        except Exception as e:
            print(f"[fetch_orders_live] ERROR fetching orders for {account_id}: {e}")
            continue

        save_debug_payload(account_hash, orders)

        rows_all = flatten_orders(
            account_hash=account_hash,
            account_id=account_id,
            orders=orders,
            snapshot_ts=snapshot_ts,
        )

        def _safe_float(x: Any) -> float | None:
            try:
                if x is None:
                    return None
                return float(x)
            except Exception:
                return None

        def _qty_ok(remaining_qty: Any, qty: Any) -> bool:
            rq = _safe_float(remaining_qty)
            q = _safe_float(qty)
            v = rq if rq is not None else q
            return (v is not None) and (v > 0)


        rows_live = [
            r
            for r in rows_all
            if (r[4] in OPEN_STATUSES)          # status
            and (r[6] is None)                  # close_time
            and _qty_ok(r[15], r[13])           # remaining_qty else quantity
            and (r[18] is not None)             # symbol
        ]


        if args.debug:
            print(f"[DEBUG] flattened rows (all): {len(rows_all)} | live(open): {len(rows_live)}")

        if WRITE_LIVE:
            con.execute("DELETE FROM journal.open_orders_live WHERE account_hash = ?;", [account_hash])

            if rows_live:
                con.executemany(
                    """
                    INSERT INTO journal.open_orders_live (
                        account_hash, account_id, order_id, leg_index,
                        status, entered_time, close_time,
                        order_type, order_strategy, complex_strategy,
                        duration, session,
                        instruction, quantity, filled_quantity, remaining_qty,
                        price, stop_price,
                        symbol, asset_type, underlying, expiry, strike, put_call,
                        raw_json, updated_at, source,
                        parent_order_id, root_order_id, depth,
                        client_order_id, order_tag,
                        leg_id, instrument_id,
                        tag, cancelable, editable
                    )
                    VALUES (
                        ?, ?, ?, ?,
                        ?, ?, ?,
                        ?, ?, ?,
                        ?, ?,
                        ?, ?, ?, ?,
                        ?, ?,
                        ?, ?, ?, ?, ?, ?,
                        ?, ?, ?,
                        ?, ?, ?,
                        ?, ?,
                        ?, ?,
                        ?, ?, ?
                    );
                    """,
                    rows_live,
                )

                try:
                    con.execute(
                        """
                        INSERT INTO journal.open_orders_snapshots (
                            snapshot_ts,
                            account_hash, account_id, order_id, leg_index,
                            leg_id, instrument_id,
                            status, entered_time, close_time,
                            order_type, order_strategy, complex_strategy,
                            duration, session,
                            instruction, quantity, filled_quantity, remaining_qty,
                            price, stop_price,
                            symbol, asset_type, underlying, expiry, strike, put_call,
                            tag, cancelable, editable,
                            parent_order_id, root_order_id, depth,
                            orders_payload_sha256,
                            source
                        )
                        SELECT
                            updated_at AS snapshot_ts,
                            account_hash, account_id, order_id, leg_index,
                            leg_id, instrument_id,
                            status, entered_time, close_time,
                            order_type, order_strategy, complex_strategy,
                            duration, session,
                            instruction, quantity, filled_quantity, remaining_qty,
                            price, stop_price,
                            symbol, asset_type, underlying, expiry, strike, put_call,
                            tag, cancelable, editable,
                            parent_order_id, root_order_id, depth,
                            ? AS orders_payload_sha256,
                            source
                        FROM journal.open_orders_live
                        WHERE account_hash = ? AND updated_at = ?;
                        """,
                        [payload_sha, account_hash, snapshot_ts],
                    )
                except duckdb.ConstraintException:
                    print("[fetch_orders_live] snapshots duplicate (same snapshot_ts) → ignored")

                print(f"[fetch_orders_live] Live open rows: {len(rows_live)} for {account_id}.")
                total_rows += len(rows_live)
            else:
                print(f"[fetch_orders_live] No OPEN orders for {account_id} (statuses={sorted(OPEN_STATUSES)}).")
        else:
            print("[fetch_orders_live] WRITE_LIVE=0 → skipping open_orders_live + snapshots (orders_raw only).")

    count_all = con.execute("SELECT COUNT(*) FROM journal.open_orders_live;").fetchone()[0]
    print(f"[fetch_orders_live] DONE. Inserted this run: {total_rows}, total in open_orders_live: {count_all}")


if __name__ == "__main__":
    main()
