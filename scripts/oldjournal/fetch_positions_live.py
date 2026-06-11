#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/journal/fetch_positions_live.py
Version: 0.6.0 (correct JSON path + full debug logging)

Purpose
-------
Fetch LIVE positions directly from Schwab Trader API using the correct
endpoint:

    GET /trader/v1/accounts/{hashValue}?fields=positions

Stores results in journal.positions_live.
Adds debug logs + saves raw JSON for inspection.
"""

from __future__ import annotations
import os
import json
import requests
import duckdb
from datetime import datetime, date
from typing import Any, Dict, List, Tuple
from pathlib import Path

from client.schwab_admin import (
    TokenStore,
    AuthClient,
    SCHWAB_BASE,
    CLIENT_CORRELID,
    RESOURCE_VERSION,
)


# ---------------------------------------------------------------------------
# Path / Config
# ---------------------------------------------------------------------------

def get_db_path() -> str:
    default = os.path.expanduser("~/tgps-project/data/journal/tgps_trades.duckdb")
    return os.environ.get("TGPS_JOURNAL_DB", default)


def get_trader_base() -> str:
    return f"{SCHWAB_BASE.rstrip('/')}/trader/v1"


def ensure_debug_dir() -> Path:
    p = Path(os.path.expanduser("~/tgps-project/data/schwab/debug_positions"))
    p.mkdir(parents=True, exist_ok=True)
    return p


def save_debug_json(account_hash: str, payload: Dict[str, Any]) -> None:
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    debug_dir = ensure_debug_dir()
    path = debug_dir / f"positions_{account_hash[:8]}_{ts}.json"
    path.write_text(json.dumps(payload, indent=2))
    print(f"[DEBUG] Raw Schwab payload saved → {path}")


# ---------------------------------------------------------------------------
# OCC parsing (unchanged)
# ---------------------------------------------------------------------------

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
        expiry = date(2000 + int(date6[0:2]), int(date6[2:4]), int(date6[4:6]))
    except Exception:
        expiry = None

    try:
        strike = int(strike8) / 1000.0
    except Exception:
        strike = None

    put_call = "CALL" if cp.upper() == "C" else ("PUT" if cp.upper() == "P" else None)
    return underlying, expiry, strike, put_call


# ---------------------------------------------------------------------------
# DB setup
# ---------------------------------------------------------------------------

def ensure_tables(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS journal.positions_live (
            account_hash    VARCHAR NOT NULL,
            account_id      VARCHAR,
            account_name    VARCHAR,
            asset_type      VARCHAR NOT NULL,
            symbol          VARCHAR NOT NULL,
            underlying      VARCHAR,
            expiry          DATE,
            strike          DOUBLE,
            put_call        VARCHAR,
            qty             DOUBLE NOT NULL,
            long_qty        DOUBLE,
            short_qty       DOUBLE,
            avg_price       DOUBLE,
            market_value    DOUBLE,
            open_pnl        DOUBLE,
            updated_at      TIMESTAMP NOT NULL,
            source          VARCHAR NOT NULL
        );
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS journal.accounts (
            account_hash VARCHAR NOT NULL,
            account_number VARCHAR NOT NULL
        );
        """
    )


# ---------------------------------------------------------------------------
# Account discovery
# ---------------------------------------------------------------------------

def fetch_accounts(con, session, trader_base) -> List[Dict[str, Any]]:
    rows = con.execute("SELECT account_hash, account_number FROM journal.accounts;").fetchall()
    if rows:
        return [{"account_hash": r[0], "account_number": r[1]} for r in rows]

    print("[fetch_positions_live] No accounts in DB → calling /accounts/accountNumbers")

    url = f"{trader_base}/accounts/accountNumbers"
    print(f"[DEBUG] GET {url}")

    resp = session.get(url)
    resp.raise_for_status()
    data = resp.json() or []

    accounts = []
    for acc in data:
        hv = acc.get("hashValue")
        num = acc.get("accountNumber")
        if hv and num:
            accounts.append({"account_hash": hv, "account_number": num})

    con.execute("DELETE FROM journal.accounts;")
    if accounts:
        con.executemany(
            "INSERT INTO journal.accounts VALUES (?, ?);",
            [(a["account_hash"], a["account_number"]) for a in accounts]
        )
        print(f"[fetch_positions_live] Saved {len(accounts)} account(s).")

    return accounts


# ---------------------------------------------------------------------------
# Correct Schwab positions endpoint
# ---------------------------------------------------------------------------

def fetch_positions_for_account(session, account_hash: str) -> Dict[str, Any]:
    url = f"{get_trader_base()}/accounts/{account_hash}?fields=positions"
    print(f"[DEBUG] GET {url}")

    resp = session.get(url)
    print(f"[DEBUG] Status {resp.status_code}")
    resp.raise_for_status()

    payload = resp.json()
    save_debug_json(account_hash, payload)
    return payload


# ---------------------------------------------------------------------------
# Flatten positions (FIXED JSON path)
# ---------------------------------------------------------------------------

def flatten_positions(account_hash, account_id, account_name, payload, ts) -> List[Tuple]:
    acct = payload.get("securitiesAccount", {})
    positions = acct.get("positions", []) or []

    print(f"[DEBUG] positions count: {len(positions)}")

    rows = []

    for pos in positions:
        instr = pos.get("instrument", {}) or {}
        asset_type = instr.get("assetType") or instr.get("type") or "UNKNOWN"
        symbol = instr.get("symbol") or ""

        long_qty = float(pos.get("longQuantity") or 0)
        short_qty = float(pos.get("shortQuantity") or 0)
        qty = long_qty - short_qty

        avg_price = (
            pos.get("averagePrice")
            or pos.get("averageLongPrice")
            or pos.get("averageShortPrice")
        )

        market_value = pos.get("marketValue")
        open_pnl = (
            pos.get("openProfitLoss")
            or pos.get("longOpenProfitLoss")
            or pos.get("shortOpenProfitLoss")
        )

        underlying = None
        expiry = None
        strike = None
        put_call = None

        if asset_type.upper() == "OPTION":
            put_call = instr.get("putCall")
            strike = instr.get("strikePrice")
            exp_raw = instr.get("expirationDate")
            if isinstance(exp_raw, str) and len(exp_raw) >= 10:
                try:
                    y, m, d = map(int, exp_raw[:10].split("-"))
                    expiry = date(y, m, d)
                except Exception:
                    expiry = None

            occ_under, occ_exp, occ_strike, occ_pc = parse_occ(symbol)
            underlying = instr.get("underlyingSymbol") or occ_under

            if expiry is None: expiry = occ_exp
            if strike is None: strike = occ_strike
            if put_call is None: put_call = occ_pc
        else:
            underlying = symbol

        rows.append(
            (
                account_hash, account_id, account_name, asset_type, symbol,
                underlying, expiry, strike, put_call, qty,
                long_qty, short_qty, avg_price, market_value,
                open_pnl, ts, "schwab_api"
            )
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

    session = requests.Session()
    session.headers.update(
        {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Schwab-Resource-Version": RESOURCE_VERSION,
            "Schwab-Client-CorrelId": CLIENT_CORRELID,
        }
    )

    trader_base = get_trader_base()
    accounts = fetch_accounts(con, session, trader_base)

    if not accounts:
        print("[fetch_positions_live] ❌ No Schwab accounts available.")
        return

    snapshot_ts = datetime.utcnow()
    total = 0

    for acct in accounts:
        acc_hash = acct["account_hash"]
        acc_id = acct["account_number"]

        print(f"[fetch_positions_live] Fetching positions for {acc_id} ({acc_hash[:8]}…)")

        try:
            payload = fetch_positions_for_account(session, acc_hash)
        except Exception as e:
            print(f"[ERROR] Failed fetching {acc_id}: {e}")
            continue

        rows = flatten_positions(acc_hash, acc_id, acc_id, payload, snapshot_ts)

        con.execute("DELETE FROM journal.positions_live WHERE account_hash = ?;", [acc_hash])

        if rows:
            con.executemany(
                "INSERT INTO journal.positions_live VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?);",
                rows,
            )
            print(f"[fetch_positions_live] Inserted {len(rows)} positions.")
            total += len(rows)
        else:
            print(f"[fetch_positions_live] No positions found for {acc_id}.")

    final = con.execute("SELECT COUNT(*) FROM journal.positions_live;").fetchone()[0]
    print(f"[fetch_positions_live] DONE. Inserted this run: {total},  total rows: {final}")


if __name__ == "__main__":
    main()
