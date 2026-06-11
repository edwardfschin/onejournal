#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/journal/oms_cli.py

Version: 0.1.4 (Schwab OMS CLI: list / place / replace / cancel / trigger-OCO)
Updated: 2026-01-08 (SGT)

What this version adds/fixes
----------------------------
1) Blocks replace on staged child orders (AWAITING_PARENT_ORDER / depth>0)
   - Prints a clear message: replace the ROOT strategy order instead (replace-root)

2) Adds: place-trigger-oco
   - Places a TRIGGER entry order with an embedded OCO (profit LIMIT + stop STOP/STOP_LIMIT)
   - So you don’t need a python one-liner anymore.

Safety
------
Broker-mutating actions are DRY-RUN by default. Add --submit to actually send.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import subprocess
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ----------------------------
# Repo root bootstrap
# ----------------------------
# This file is: <repo>/scripts/journal/oms_cli.py  -> repo root is parents[2]
CODE_DIR = Path(__file__).resolve().parents[2]
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

import duckdb  # noqa: E402

from client.schwab_admin import AuthClient, TokenStore  # noqa: E402
from client.schwab_api import RestClient, RestSession  # noqa: E402

DEFAULT_DB = os.environ.get(
    "TGPS_JOURNAL_DB",
    os.path.expanduser("~/tgps-project/data/journal/tgps_trades.duckdb"),
)

SGT = timezone(timedelta(hours=8))


def _eprint(msg: str) -> None:
    print(msg, file=sys.stderr)


def _as_decimal(x: Optional[str]) -> Optional[float]:
    if x is None:
        return None
    s = str(x).strip()
    if not s:
        return None
    try:
        return float(Decimal(s))
    except (InvalidOperation, ValueError):
        raise SystemExit(f"Invalid numeric value: {x!r}")


def _is_probably_hash(s: str) -> bool:
    s = s.strip()
    if len(s) != 64:
        return False
    return all(c in "0123456789abcdefABCDEF" for c in s)


def _db_connect(db_path: str, *, read_only: bool = True) -> duckdb.DuckDBPyConnection:
    # read_only=True reduces the chance of holding a write lock while we spawn
    # a refresh subprocess (fetch_orders_live) that needs to write.
    return duckdb.connect(os.path.expanduser(db_path), read_only=read_only)


def _has_relation(con: duckdb.DuckDBPyConnection, schema: str, name: str) -> bool:
    if con.execute(
        """
        select 1 from information_schema.tables
        where table_schema=? and table_name=?
        limit 1
        """,
        [schema, name],
    ).fetchone():
        return True

    return bool(
        con.execute(
            """
            select 1 from information_schema.views
            where table_schema=? and table_name=?
            limit 1
            """,
            [schema, name],
        ).fetchone()
    )


def _has_view(con: duckdb.DuckDBPyConnection, schema: str, name: str) -> bool:
    return bool(
        con.execute(
            """
            select 1 from information_schema.views
            where table_schema=? and table_name=?
            limit 1
            """,
            [schema, name],
        ).fetchone()
    )


def _pick_account_from_db(con: duckdb.DuckDBPyConnection) -> Optional[Tuple[str, str]]:
    if not _has_relation(con, "journal", "accounts"):
        return None
    rows = con.execute(
        "select account_hash, account_number from journal.accounts order by account_number"
    ).fetchall()
    if len(rows) == 1:
        return str(rows[0][0]), str(rows[0][1])
    return None


def _resolve_account_hash(
    con: duckdb.DuckDBPyConnection,
    *,
    account: Optional[str],
) -> Tuple[str, str]:
    if account and _is_probably_hash(account):
        acct_hash = account.strip()
        acct_num = ""
        if _has_relation(con, "journal", "accounts"):
            r = con.execute(
                "select account_number from journal.accounts where account_hash=? limit 1",
                [acct_hash],
            ).fetchone()
            if r:
                acct_num = str(r[0])
        return acct_hash, acct_num

    if account:
        acct_num = str(account).strip()
        if _has_relation(con, "journal", "accounts"):
            r = con.execute(
                "select account_hash from journal.accounts where account_number=? limit 1",
                [acct_num],
            ).fetchone()
            if r:
                return str(r[0]), acct_num

        store = TokenStore()
        auth = AuthClient(store)
        from client.schwab_admin import AdminClient  # lazy import

        admin = AdminClient(auth)
        data = admin.account_numbers()
        for row in data or []:
            if str(row.get("accountNumber")) == acct_num:
                return str(row.get("hashValue")), acct_num
        raise SystemExit(f"Account number not found at Schwab: {acct_num}")

    picked = _pick_account_from_db(con)
    if picked:
        return picked[0], picked[1]

    raise SystemExit(
        "No account specified and unable to auto-pick. "
        "Pass --account <accountNumber> (e.g. 41472449) or --account <accountHash>."
    )


def _load_order_id_links(con: duckdb.DuckDBPyConnection, account_number: str) -> Dict[str, str]:
    if not _has_relation(con, "journal", "order_id_links"):
        return {}
    rows = con.execute(
        """
        select old_order_id, new_order_id
        from journal.order_id_links
        where account=?
        """,
        [account_number],
    ).fetchall()
    out: Dict[str, str] = {}
    for old_id, new_id in rows:
        if old_id and new_id:
            out[str(old_id)] = str(new_id)
    return out


def _resolve_latest_order_id(links: Dict[str, str], order_id: str, max_hops: int = 10) -> Tuple[str, int]:
    cur = str(order_id)
    hops = 0
    seen = set()
    while hops < max_hops:
        if cur in seen:
            break
        seen.add(cur)
        nxt = links.get(cur)
        if not nxt:
            break
        cur = nxt
        hops += 1
    return cur, hops


def _make_rest_client() -> RestClient:
    store = TokenStore()
    auth = AuthClient(store)
    session = RestSession(auth)
    return RestClient(session)


def _json_pretty(x: Any) -> str:
    return json.dumps(x, ensure_ascii=False, indent=2)


def _today_sgt_date() -> str:
    return datetime.now(SGT).date().isoformat()


def _date_days_ago_sgt(days: int) -> str:
    d = datetime.now(SGT).date() - timedelta(days=int(days))
    return d.isoformat()


def _run_fetch_orders_live(*, from_date: str, to_date: str, db_path: str, debug: bool = False) -> None:
    """
    Minimal moving parts: run the existing module as a subprocess.
    Use cwd=repo root so -m scripts.... resolves consistently.
    Force the same DuckDB path via TGPS_JOURNAL_DB.
    """
    cmd = [
        sys.executable,
        "-m",
        "scripts.journal.fetch_orders_live",
        "--from",
        from_date,
        "--to",
        to_date,
    ]
    if debug:
        cmd.append("--debug")

    env = os.environ.copy()
    env["TGPS_JOURNAL_DB"] = os.path.expanduser(db_path)

    _eprint(f"[catchup] running: {' '.join(cmd)} (cwd={CODE_DIR})")
    try:
        subprocess.run(cmd, check=True, cwd=str(CODE_DIR), env=env)
    except subprocess.CalledProcessError as e:
        _eprint(f"[catchup] fetch_orders_live failed (exit {e.returncode})")
        raise


def _norm_status(s: str) -> str:
    return (s or "").strip().upper().replace(" ", "_")


def _upper(s: str) -> str:
    return (s or "").strip().upper()


def _derive_close_instruction(entry_instruction: str) -> str:
    """
    For options/equities:
      BUY_TO_OPEN  -> SELL_TO_CLOSE
      SELL_TO_OPEN -> BUY_TO_CLOSE
    """
    ei = _upper(entry_instruction)
    if ei == "BUY_TO_OPEN":
        return "SELL_TO_CLOSE"
    if ei == "SELL_TO_OPEN":
        return "BUY_TO_CLOSE"
    return ""


@dataclass
class OpenOrderRow:
    account_hash: str
    account_number: str
    ticker: str
    order_id: str
    status: str
    order_type: str
    instruction: str
    quantity: float
    price: Optional[float]
    stop_price: Optional[float]
    entered_time: str
    parent_order_id: Optional[int]
    root_order_id: Optional[int]
    depth: int
    raw_json: Optional[str]


def _find_open_order(con: duckdb.DuckDBPyConnection, *, ticker: str, order_id: str) -> OpenOrderRow:
    if not _has_relation(con, "journal", "open_orders_live"):
        raise SystemExit("Missing table: journal.open_orders_live (run fetch_orders_live first)")

    def _query_open_orders_live(oid: str) -> Optional[Tuple[Any, ...]]:
        params: List[Any] = [str(oid)]
        where = "where cast(o.order_id as varchar)=?"
        if ticker:
            where += " and o.underlying=?"
            params.append(ticker.strip().upper())

        return con.execute(
            f"""
            select
              o.account_hash,
              coalesce(a.account_number, '') as account_number,
              o.underlying as ticker,
              cast(o.order_id as varchar) as order_id,
              coalesce(o.status,'') as status,
              coalesce(o.order_type,'') as order_type,
              coalesce(o.instruction,'') as instruction,
              coalesce(o.quantity,0) as quantity,
              o.price,
              o.stop_price,
              cast(o.entered_time as varchar) as entered_time,
              o.parent_order_id,
              o.root_order_id,
              coalesce(o.depth,0) as depth,
              o.raw_json
            from journal.open_orders_live o
            left join journal.accounts a on a.account_hash=o.account_hash
            {where}
            order by o.entered_time desc
            limit 1
            """,
            params,
        ).fetchone()

    row = _query_open_orders_live(order_id)

    # If not found, try one-hop lookup old->new (helps when user passes old id)
    if not row and _has_relation(con, "journal", "order_id_links"):
        r2 = con.execute(
            """
            select new_order_id
            from journal.order_id_links
            where old_order_id=?
            order by linked_at desc
            limit 1
            """,
            [str(order_id)],
        ).fetchone()
        if r2 and r2[0]:
            row = _query_open_orders_live(str(r2[0]))

    if not row:
        raise SystemExit(
            f"Open order not found in DuckDB for ticker={ticker or '(any)'} order_id={order_id}. "
            f"Run: python -m scripts.journal.fetch_orders_live --from <date> --to <date>"
        )

    return OpenOrderRow(
        account_hash=str(row[0]),
        account_number=str(row[1]),
        ticker=str(row[2]),
        order_id=str(row[3]),
        status=str(row[4]),
        order_type=str(row[5]),
        instruction=str(row[6]),
        quantity=float(row[7]),
        price=None if row[8] is None else float(row[8]),
        stop_price=None if row[9] is None else float(row[9]),
        entered_time=str(row[10]),
        parent_order_id=None if row[11] is None else int(row[11]),
        root_order_id=None if row[12] is None else int(row[12]),
        depth=0 if row[13] is None else int(row[13]),
        raw_json=None if row[14] is None else str(row[14]),
    )


def _list_open_orders(
    con: duckdb.DuckDBPyConnection,
    *,
    tickers: Optional[List[str]],
    status: Optional[str],
    limit: int,
) -> List[Dict[str, Any]]:
    if not _has_relation(con, "journal", "open_orders_live"):
        raise SystemExit("Missing table: journal.open_orders_live (run fetch_orders_live first)")

    # Prefer the simplifying view if it exists (consistent across scripts)
    if _has_view(con, "journal", "v_open_orders_live_latest"):
        conds: List[str] = []
        params: List[Any] = []

        if tickers:
            conds.append("v.underlying in (" + ",".join(["?"] * len(tickers)) + ")")
            params.extend([t.upper() for t in tickers])

        if status:
            conds.append("upper(coalesce(v.status,''))=upper(?)")
            params.append(status)

        where = ("where " + " and ".join(conds)) if conds else ""

        rows = con.execute(
            f"""
            select
              coalesce(a.account_number,'') as account_number,
              v.underlying as ticker,
              cast(v.order_id as varchar) as order_id,
              coalesce(v.resolved_order_id, cast(v.order_id as varchar)) as resolved_order_id,
              coalesce(v.resolved_order_hops, 0) as hops,

              t.parent_order_id as parent_order_id,
              t.root_order_id as root_order_id,
              t.depth as depth,

              coalesce(v.status,'') as status,
              coalesce(v.order_type,'') as order_type,
              coalesce(v.instruction,'') as instruction,
              coalesce(v.quantity,0) as qty,
              v.price,
              v.stop_price,
              cast(v.entered_time as varchar) as entered_time
            from journal.v_open_orders_live_latest v
            left join journal.accounts a on a.account_hash=v.account_hash
            left join (
              select
                account_hash,
                order_id,
                min(parent_order_id) as parent_order_id,
                min(root_order_id) as root_order_id,
                min(depth) as depth
              from journal.open_orders_live
              group by 1,2
            ) t on t.account_hash=v.account_hash and t.order_id=v.order_id
            {where}
            order by v.entered_time desc
            limit {int(limit)}
            """,
            params,
        ).fetchall()

        return [
            dict(
                account=str(r[0] or ""),
                ticker=str(r[1]),
                order_id=str(r[2]),
                resolved_order_id=str(r[3]),
                hops=int(r[4]),
                parent_order_id=None if r[5] is None else int(r[5]),
                root_order_id=None if r[6] is None else int(r[6]),
                depth=0 if r[7] is None else int(r[7]),
                status=str(r[8]),
                order_type=str(r[9]),
                instruction=str(r[10]),
                qty=float(r[11]),
                price=r[12],
                stop_price=r[13],
                entered_time=str(r[14]),
            )
            for r in rows
        ]

    # Fallback: direct table
    conds2: List[str] = []
    params2: List[Any] = []

    if tickers:
        conds2.append("o.underlying in (" + ",".join(["?"] * len(tickers)) + ")")
        params2.extend([t.upper() for t in tickers])

    if status:
        conds2.append("upper(coalesce(o.status,''))=upper(?)")
        params2.append(status)

    where2 = ("where " + " and ".join(conds2)) if conds2 else ""

    rows2 = con.execute(
        f"""
        select
          coalesce(a.account_number,'') as account_number,
          o.underlying as ticker,
          cast(o.order_id as varchar) as order_id,

          o.parent_order_id,
          o.root_order_id,
          o.depth,

          coalesce(o.status,'') as status,
          coalesce(o.order_type,'') as order_type,
          coalesce(o.instruction,'') as instruction,
          coalesce(o.quantity,0) as qty,
          o.price,
          o.stop_price,
          cast(o.entered_time as varchar) as entered_time
        from journal.open_orders_live o
        left join journal.accounts a on a.account_hash=o.account_hash
        {where2}
        order by o.entered_time desc
        limit {int(limit)}
        """,
        params2,
    ).fetchall()

    return [
        dict(
            account=str(acct_num or ""),
            ticker=str(ticker),
            order_id=str(oid),
            resolved_order_id=str(oid),
            hops=0,
            parent_order_id=None if parent_id is None else int(parent_id),
            root_order_id=None if root_id is None else int(root_id),
            depth=0 if depth is None else int(depth),
            status=str(st),
            order_type=str(ot),
            instruction=str(instr),
            qty=float(qty),
            price=pr,
            stop_price=spr,
            entered_time=str(et),
        )
        for acct_num, ticker, oid, parent_id, root_id, depth, st, ot, instr, qty, pr, spr, et in rows2
    ]


def _print_table(rows: List[Dict[str, Any]], cols: List[str]) -> None:
    if not rows:
        print("(no rows)")
        return
    widths = {c: len(c) for c in cols}
    for r in rows:
        for c in cols:
            s = "" if r.get(c) is None else str(r.get(c))
            widths[c] = max(widths[c], len(s))
    print("  ".join(c.ljust(widths[c]) for c in cols))
    print("  ".join("-" * widths[c] for c in cols))
    for r in rows:
        print("  ".join(("" if r.get(c) is None else str(r.get(c))).ljust(widths[c]) for c in cols))


def _build_single_order_payload(
    *,
    order_type: str,
    session: str,
    duration: str,
    price: Optional[float],
    stop_price: Optional[float],
    instruction: str,
    qty: float,
    symbol: str,
    asset_type: str,
) -> Dict[str, Any]:
    ot = _upper(order_type)
    payload: Dict[str, Any] = {
        "orderStrategyType": "SINGLE",
        "orderType": ot,
        "session": session,
        "duration": duration,
        "orderLegCollection": [
            {
                "instruction": instruction,
                "quantity": qty,
                "instrument": {"symbol": symbol, "assetType": asset_type},
            }
        ],
    }

    if ot in ("LIMIT", "STOP_LIMIT"):
        if price is None:
            raise SystemExit(f"{ot} requires --price")
        payload["price"] = float(price)

    if ot in ("STOP", "STOP_LIMIT"):
        if stop_price is None:
            raise SystemExit(f"{ot} requires --stop-price")
        payload["stopPrice"] = float(stop_price)

    return payload


def _build_oco_bracket_payload(
    *,
    session: str,
    duration: str,
    profit_price: float,
    stop_price: float,
    stop_limit_price: Optional[float],
    instruction: str,
    qty: float,
    symbol: str,
    asset_type: str,
) -> Dict[str, Any]:
    profit = _build_single_order_payload(
        order_type="LIMIT",
        session=session,
        duration=duration,
        price=profit_price,
        stop_price=None,
        instruction=instruction,
        qty=qty,
        symbol=symbol,
        asset_type=asset_type,
    )

    if stop_limit_price is None:
        stop_leg = _build_single_order_payload(
            order_type="STOP",
            session=session,
            duration=duration,
            price=None,
            stop_price=stop_price,
            instruction=instruction,
            qty=qty,
            symbol=symbol,
            asset_type=asset_type,
        )
    else:
        stop_leg = _build_single_order_payload(
            order_type="STOP_LIMIT",
            session=session,
            duration=duration,
            price=stop_limit_price,
            stop_price=stop_price,
            instruction=instruction,
            qty=qty,
            symbol=symbol,
            asset_type=asset_type,
        )

    return {"orderStrategyType": "OCO", "childOrderStrategies": [profit, stop_leg]}


def _build_trigger_oco_payload(
    *,
    complex_type: str,
    session: str,
    duration: str,
    entry_type: str,
    entry_price: Optional[float],
    entry_stop_price: Optional[float],
    entry_instruction: str,
    exit_instruction: str,
    qty: float,
    symbol: str,
    asset_type: str,
    profit_price: float,
    stop_price: float,
    stop_limit_price: Optional[float],
) -> Dict[str, Any]:
    et = _upper(entry_type)
    if et not in ("MARKET", "LIMIT", "STOP", "STOP_LIMIT"):
        raise SystemExit("entry-type must be MARKET|LIMIT|STOP|STOP_LIMIT")

    if not exit_instruction:
        raise SystemExit("Could not derive exit instruction. Pass --exit-instruction explicitly.")

    oco = _build_oco_bracket_payload(
        session=session,
        duration=duration,
        profit_price=profit_price,
        stop_price=stop_price,
        stop_limit_price=stop_limit_price,
        instruction=exit_instruction,
        qty=qty,
        symbol=symbol,
        asset_type=asset_type,
    )

    payload: Dict[str, Any] = {
        "orderStrategyType": "TRIGGER",
        "complexOrderStrategyType": complex_type or "NONE",
        "orderType": et,
        "session": session,
        "duration": duration,
        "orderLegCollection": [
            {
                "instruction": entry_instruction,
                "quantity": qty,
                "instrument": {"symbol": symbol, "assetType": asset_type},
            }
        ],
        "childOrderStrategies": [oco],
    }

    if et in ("LIMIT", "STOP_LIMIT"):
        if entry_price is None:
            raise SystemExit("Entry LIMIT/STOP_LIMIT requires --entry-price")
        payload["price"] = float(entry_price)

    if et in ("STOP", "STOP_LIMIT"):
        if entry_stop_price is None:
            raise SystemExit("Entry STOP/STOP_LIMIT requires --entry-stop-price")
        payload["stopPrice"] = float(entry_stop_price)

    return payload


def _extract_replace_meta(raw_json: str) -> Dict[str, Any]:
    try:
        ord_obj = json.loads(raw_json)
    except Exception:
        return {}

    order_type = (ord_obj.get("orderType") or "").upper()
    session = ord_obj.get("session") or ""
    duration = ord_obj.get("duration") or ""

    legs = ord_obj.get("orderLegCollection") or []
    leg0 = (legs[0] if legs else {}) or {}
    instruction = leg0.get("instruction") or ""
    qty = leg0.get("quantity")

    inst = leg0.get("instrument") or {}
    symbol = inst.get("symbol") or ""
    asset_type = inst.get("assetType") or ""

    meta = {
        "orderStrategyType": (ord_obj.get("orderStrategyType") or "SINGLE").upper(),
        "orderType": order_type,
        "session": session,
        "duration": duration,
        "symbol": symbol,
        "assetType": asset_type,
        "instruction": instruction,
        "qty": qty,
        "currentPrice": ord_obj.get("price"),
        "currentStopPrice": ord_obj.get("stopPrice"),
        "hasChildren": bool(ord_obj.get("childOrderStrategies")),
    }
    return meta


def _build_replace_from_raw_json(
    raw_json: str,
    *,
    new_price: Optional[float],
    new_stop_price: Optional[float],
) -> Dict[str, Any]:
    """
    Build a SINGLE-order replace payload from raw_json.
    (We intentionally do NOT support TRIGGER/OCO here; use replace-root.)
    """
    try:
        ord_obj = json.loads(raw_json)
    except Exception as e:
        raise SystemExit(f"raw_json is not valid JSON: {e}")

    if (ord_obj.get("orderStrategyType") or "SINGLE").upper() != "SINGLE" or ord_obj.get("childOrderStrategies"):
        raise SystemExit(
            "This order is not a simple SINGLE order (it has a strategy/children). "
            "Use: replace-root (edits the ROOT TRIGGER/OCO legs)."
        )

    order_type = (ord_obj.get("orderType") or "").upper()
    session = ord_obj.get("session") or "NORMAL"
    duration = ord_obj.get("duration") or "GOOD_TILL_CANCEL"

    legs = ord_obj.get("orderLegCollection") or []
    if not legs:
        raise SystemExit("Cannot build replace payload: missing orderLegCollection in raw_json")

    leg0 = legs[0] or {}
    instruction = leg0.get("instruction") or ""
    qty = leg0.get("quantity")
    inst = leg0.get("instrument") or {}
    symbol = inst.get("symbol")
    asset_type = inst.get("assetType") or "OPTION"

    if not symbol or qty is None:
        raise SystemExit("Cannot build replace payload: missing symbol/quantity in raw_json")

    cur_price = ord_obj.get("price")
    cur_stop = ord_obj.get("stopPrice")
    price = new_price if new_price is not None else cur_price
    stop_price = new_stop_price if new_stop_price is not None else cur_stop

    return _build_single_order_payload(
        order_type=order_type,
        session=session,
        duration=duration,
        price=price,
        stop_price=stop_price,
        instruction=str(instruction),
        qty=float(qty),
        symbol=str(symbol),
        asset_type=str(asset_type),
    )


def _first_leg(order_obj: Dict[str, Any]) -> Tuple[str, str, float, str, str]:
    """
    Return: (instruction, symbol, qty, assetType, orderType)
    """
    legs = order_obj.get("orderLegCollection") or []
    if not legs:
        raise SystemExit("Expected orderLegCollection in order JSON (cannot build payload).")
    leg0 = legs[0] or {}
    inst = leg0.get("instrument") or {}
    instruction = str(leg0.get("instruction") or "")
    symbol = str(inst.get("symbol") or "")
    asset_type = str(inst.get("assetType") or "")
    qty = leg0.get("quantity")
    if not symbol or qty is None:
        raise SystemExit("Missing symbol/quantity in orderLegCollection.")
    order_type = str(order_obj.get("orderType") or "").upper()
    return instruction, symbol, float(qty), asset_type, order_type


def _build_replace_root_trigger_oco_payload(
    root_raw_json: str,
    *,
    new_entry_price: Optional[float],
    new_profit_price: Optional[float],
    new_stop_price: Optional[float],
    new_stop_limit_price: Optional[float],
) -> Dict[str, Any]:
    """
    Build a replace payload for a ROOT TRIGGER order with an embedded OCO.
    """
    try:
        root = json.loads(root_raw_json)
    except Exception as e:
        raise SystemExit(f"root raw_json is not valid JSON: {e}")

    strat = (root.get("orderStrategyType") or "SINGLE").upper()
    if strat not in ("TRIGGER", "OCO"):
        raise SystemExit(
            f"ROOT orderStrategyType={strat} is not supported by replace-root. "
            "Supported: TRIGGER (entry + child OCO) or OCO."
        )

    session = root.get("session") or "NORMAL"
    duration = root.get("duration") or "GOOD_TILL_CANCEL"
    complex_type = root.get("complexOrderStrategyType") or "NONE"

    if strat == "OCO":
        oco_node = root
        entry_node = None
    else:
        entry_node = root
        children = root.get("childOrderStrategies") or []
        oco_node = next((c for c in children if (c.get("orderStrategyType") or "").upper() == "OCO"), None)
        if oco_node is None:
            raise SystemExit("TRIGGER root has no child OCO. Cannot use replace-root.")

    oco_children = oco_node.get("childOrderStrategies") or []
    if len(oco_children) < 2:
        raise SystemExit("OCO node missing childOrderStrategies (expected profit + stop legs).")

    limit_leg_obj = next((c for c in oco_children if (c.get("orderType") or "").upper() == "LIMIT"), None)
    stop_leg_obj = next((c for c in oco_children if (c.get("orderType") or "").upper() in ("STOP", "STOP_LIMIT")), None)
    if limit_leg_obj is None or stop_leg_obj is None:
        raise SystemExit("Could not identify LIMIT leg and STOP/STOP_LIMIT leg inside OCO.")

    # Profit leg
    p_instr, p_sym, p_qty, p_asset, _ = _first_leg(limit_leg_obj)
    cur_profit = limit_leg_obj.get("price")
    profit_price = float(new_profit_price) if new_profit_price is not None else (float(cur_profit) if cur_profit is not None else None)
    if profit_price is None:
        raise SystemExit("Cannot determine profit LIMIT price.")

    profit_payload = _build_single_order_payload(
        order_type="LIMIT",
        session=(limit_leg_obj.get("session") or session),
        duration=(limit_leg_obj.get("duration") or duration),
        price=profit_price,
        stop_price=None,
        instruction=p_instr,
        qty=p_qty,
        symbol=p_sym,
        asset_type=p_asset,
    )

    # Stop leg
    s_instr, s_sym, s_qty, s_asset, s_ot = _first_leg(stop_leg_obj)
    cur_stop = stop_leg_obj.get("stopPrice")
    cur_stop_limit = stop_leg_obj.get("price")

    stop_price = float(new_stop_price) if new_stop_price is not None else (float(cur_stop) if cur_stop is not None else None)
    if stop_price is None:
        raise SystemExit("Cannot determine stop stopPrice.")

    if s_ot == "STOP":
        if new_stop_limit_price is None:
            stop_payload = _build_single_order_payload(
                order_type="STOP",
                session=(stop_leg_obj.get("session") or session),
                duration=(stop_leg_obj.get("duration") or duration),
                price=None,
                stop_price=stop_price,
                instruction=s_instr,
                qty=s_qty,
                symbol=s_sym,
                asset_type=s_asset,
            )
        else:
            stop_payload = _build_single_order_payload(
                order_type="STOP_LIMIT",
                session=(stop_leg_obj.get("session") or session),
                duration=(stop_leg_obj.get("duration") or duration),
                price=float(new_stop_limit_price),
                stop_price=stop_price,
                instruction=s_instr,
                qty=s_qty,
                symbol=s_sym,
                asset_type=s_asset,
            )
    else:
        stop_limit_price = float(new_stop_limit_price) if new_stop_limit_price is not None else (
            float(cur_stop_limit) if cur_stop_limit is not None else None
        )
        if stop_limit_price is None:
            raise SystemExit("STOP_LIMIT leg requires a limit price (price). Cannot determine it.")
        stop_payload = _build_single_order_payload(
            order_type="STOP_LIMIT",
            session=(stop_leg_obj.get("session") or session),
            duration=(stop_leg_obj.get("duration") or duration),
            price=stop_limit_price,
            stop_price=stop_price,
            instruction=s_instr,
            qty=s_qty,
            symbol=s_sym,
            asset_type=s_asset,
        )

    oco_payload = {"orderStrategyType": "OCO", "childOrderStrategies": [profit_payload, stop_payload]}

    if strat == "OCO":
        oco_payload["complexOrderStrategyType"] = complex_type
        return oco_payload

    # Entry node (TRIGGER root)
    e_instr, e_sym, e_qty, e_asset, e_ot = _first_leg(entry_node)

    cur_entry_price = entry_node.get("price")
    cur_entry_stop = entry_node.get("stopPrice")

    entry_price = float(new_entry_price) if new_entry_price is not None else (float(cur_entry_price) if cur_entry_price is not None else None)
    entry_stop = float(cur_entry_stop) if cur_entry_stop is not None else None

    payload: Dict[str, Any] = {
        "orderStrategyType": "TRIGGER",
        "complexOrderStrategyType": complex_type,
        "orderType": (entry_node.get("orderType") or e_ot or "LIMIT").upper(),
        "session": session,
        "duration": duration,
        "orderLegCollection": [
            {
                "instruction": e_instr,
                "quantity": e_qty,
                "instrument": {"symbol": e_sym, "assetType": e_asset},
            }
        ],
        "childOrderStrategies": [oco_payload],
    }

    if payload["orderType"] in ("LIMIT", "STOP_LIMIT"):
        if entry_price is None:
            raise SystemExit("Entry order requires a price but none is available.")
        payload["price"] = float(entry_price)
    if payload["orderType"] in ("STOP", "STOP_LIMIT"):
        if entry_stop is None:
            raise SystemExit("Entry order requires stopPrice but none is available.")
        payload["stopPrice"] = float(entry_stop)

    return payload


def _maybe_catchup(args: argparse.Namespace) -> None:
    if not getattr(args, "refresh_after", False):
        return
    lookback = int(getattr(args, "refresh_lookback_days", 7) or 7)
    from_date = _date_days_ago_sgt(lookback)
    to_date = _today_sgt_date()
    _run_fetch_orders_live(
        from_date=from_date,
        to_date=to_date,
        db_path=args.db,
        debug=bool(getattr(args, "refresh_debug", False)),
    )


def _is_staged_child(row: OpenOrderRow) -> bool:
    st = _norm_status(row.status)
    if st == "AWAITING_PARENT_ORDER":
        return True
    if (row.depth or 0) > 0 and row.root_order_id is not None:
        return True
    return False


def cmd_list_open(args: argparse.Namespace) -> None:
    con = _db_connect(args.db, read_only=True)
    try:
        tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()] if args.tickers else None
        rows = _list_open_orders(con, tickers=tickers, status=args.status or None, limit=args.limit)
    finally:
        con.close()

    _print_table(
        rows,
        cols=[
            "account", "ticker", "order_id", "resolved_order_id", "hops",
            "parent_order_id", "root_order_id", "depth",
            "status", "order_type", "instruction", "qty", "price", "stop_price", "entered_time",
        ],
    )


def cmd_cancel(args: argparse.Namespace) -> None:
    con = _db_connect(args.db, read_only=True)
    try:
        row = _find_open_order(con, ticker=args.ticker or "", order_id=str(args.order_id))
        links = _load_order_id_links(con, row.account_number) if row.account_number else {}
        resolved_id, hops = _resolve_latest_order_id(links, row.order_id) if links else (row.order_id, 0)
    finally:
        con.close()

    print(f"[cancel] {row.ticker} order_id={row.order_id} resolved={resolved_id} hops={hops} status={row.status}")
    if not args.submit:
        print("[cancel] DRY-RUN (add --submit to send cancel to Schwab)")
        return

    rest = _make_rest_client()
    out = rest.orders.cancel(row.account_hash, resolved_id)
    print(_json_pretty(out))

    _maybe_catchup(args)


def cmd_replace(args: argparse.Namespace) -> None:
    con = _db_connect(args.db, read_only=True)
    try:
        row = _find_open_order(con, ticker=args.ticker or "", order_id=str(args.order_id))
        links = _load_order_id_links(con, row.account_number) if row.account_number else {}
        resolved_id, hops = _resolve_latest_order_id(links, row.order_id) if links else (row.order_id, 0)
    finally:
        con.close()

    if _is_staged_child(row):
        root = row.root_order_id
        parent = row.parent_order_id
        msg = (
            "This is a staged child order (AWAITING_PARENT_ORDER / depth>0).\n"
            "Schwab UI edits this by replacing the parent/root strategy order, "
            "but the API usually rejects PUT-replace on the child order_id.\n\n"
            f"Child order_id={row.order_id} | parent_order_id={parent} | root_order_id={root}\n\n"
            "Use replace-root instead, for example:\n"
            f"  python -m scripts.journal.oms_cli replace-root --ticker {row.ticker} --order-id {row.order_id} "
            "--profit-price <NEW_PROFIT> --stop-price <NEW_STOP> [--stop-limit-price <NEW_STOP_LIMIT>] --submit\n"
        )
        raise SystemExit(msg)

    if not row.raw_json:
        raise SystemExit("open_orders_live.raw_json is empty; cannot build replace payload.")

    meta = _extract_replace_meta(row.raw_json)
    payload = _build_replace_from_raw_json(
        row.raw_json,
        new_price=_as_decimal(args.price),
        new_stop_price=_as_decimal(args.stop_price),
    )

    print(f"[replace] {row.ticker} order_id={row.order_id} resolved={resolved_id} hops={hops}")
    if meta:
        print(
            "[replace] extracted:"
            f" strategy={meta.get('orderStrategyType')}"
            f" type={meta.get('orderType')}"
            f" symbol={meta.get('symbol')}"
            f" instr={meta.get('instruction')}"
            f" qty={meta.get('qty')}"
        )
        print(
            f"[replace] current: price={meta.get('currentPrice')} stop={meta.get('currentStopPrice')}"
            f" | new: price={payload.get('price', None)} stop={payload.get('stopPrice', None)}"
        )

    print("[replace] payload:\n" + _json_pretty(payload))

    if not args.submit:
        print("[replace] DRY-RUN (add --submit to send replace to Schwab)")
        return

    rest = _make_rest_client()
    out = rest.orders.replace(row.account_hash, resolved_id, payload)
    print(_json_pretty(out))

    _maybe_catchup(args)


def cmd_replace_root(args: argparse.Namespace) -> None:
    """
    Replace the ROOT TRIGGER/OCO order (edits embedded OCO legs).
    You can pass a child order-id; we'll resolve to its root_order_id automatically.
    """
    con = _db_connect(args.db, read_only=True)
    try:
        any_row = _find_open_order(con, ticker=args.ticker or "", order_id=str(args.order_id))
        root_id = str(any_row.root_order_id) if any_row.root_order_id is not None else any_row.order_id

        root_row = _find_open_order(con, ticker=args.ticker or "", order_id=root_id)

        links = _load_order_id_links(con, root_row.account_number) if root_row.account_number else {}
        resolved_root_id, hops = _resolve_latest_order_id(links, root_row.order_id) if links else (root_row.order_id, 0)
    finally:
        con.close()

    if not root_row.raw_json:
        raise SystemExit("ROOT open_orders_live.raw_json is empty; cannot build replace-root payload.")

    payload = _build_replace_root_trigger_oco_payload(
        root_row.raw_json,
        new_entry_price=_as_decimal(args.entry_price),
        new_profit_price=_as_decimal(args.profit_price),
        new_stop_price=_as_decimal(args.stop_price),
        new_stop_limit_price=_as_decimal(args.stop_limit_price),
    )

    print(
        f"[replace-root] {root_row.ticker} root_order_id={root_row.order_id} resolved={resolved_root_id} hops={hops} "
        f"status={root_row.status}"
    )
    print("[replace-root] payload:\n" + _json_pretty(payload))

    if not args.submit:
        print("[replace-root] DRY-RUN (add --submit to send replace-root to Schwab)")
        return

    rest = _make_rest_client()
    out = rest.orders.replace(root_row.account_hash, resolved_root_id, payload)
    print(_json_pretty(out))

    _maybe_catchup(args)


def cmd_place(args: argparse.Namespace) -> None:
    con = _db_connect(args.db, read_only=True)
    try:
        acct_hash, acct_num = _resolve_account_hash(con, account=args.account)
    finally:
        con.close()

    payload = _build_single_order_payload(
        order_type=args.type,
        session=args.session,
        duration=args.duration,
        price=_as_decimal(args.price),
        stop_price=_as_decimal(args.stop_price),
        instruction=args.instruction,
        qty=float(args.qty),
        symbol=args.symbol,
        asset_type=args.asset_type.upper(),
    )

    print(f"[place] account={acct_num or acct_hash[:8]+'…'} type={_upper(args.type)} symbol={args.symbol} qty={args.qty}")
    print("[place] payload:\n" + _json_pretty(payload))

    if not args.submit:
        print("[place] DRY-RUN (add --submit to send order to Schwab)")
        return

    rest = _make_rest_client()
    out = rest.orders.place(acct_hash, payload)
    print(_json_pretty(out))

    _maybe_catchup(args)


def cmd_place_bracket(args: argparse.Namespace) -> None:
    con = _db_connect(args.db, read_only=True)
    try:
        acct_hash, acct_num = _resolve_account_hash(con, account=args.account)
    finally:
        con.close()

    profit_price = _as_decimal(args.profit_price)
    stop_price = _as_decimal(args.stop_price)
    if profit_price is None or stop_price is None:
        raise SystemExit("--profit-price and --stop-price are required and must be numeric")

    payload = _build_oco_bracket_payload(
        session=args.session,
        duration=args.duration,
        profit_price=float(profit_price),
        stop_price=float(stop_price),
        stop_limit_price=_as_decimal(args.stop_limit_price),
        instruction=args.instruction,
        qty=float(args.qty),
        symbol=args.symbol,
        asset_type=args.asset_type.upper(),
    )

    print(f"[place-bracket] account={acct_num or acct_hash[:8]+'…'} symbol={args.symbol} qty={args.qty}")
    print("[place-bracket] payload:\n" + _json_pretty(payload))

    if not args.submit:
        print("[place-bracket] DRY-RUN (add --submit to send OCO to Schwab)")
        return

    rest = _make_rest_client()
    out = rest.orders.place(acct_hash, payload)
    print(_json_pretty(out))

    _maybe_catchup(args)


def cmd_place_trigger_oco(args: argparse.Namespace) -> None:
    """
    Place a TRIGGER entry order that, once filled, activates an OCO exit (profit + stop).
    """
    con = _db_connect(args.db, read_only=True)
    try:
        acct_hash, acct_num = _resolve_account_hash(con, account=args.account)
    finally:
        con.close()

    qty = float(args.qty)
    entry_instruction = _upper(args.entry_instruction)
    exit_instruction = _upper(args.exit_instruction) if args.exit_instruction else _derive_close_instruction(entry_instruction)

    profit_price = _as_decimal(args.profit_price)
    stop_price = _as_decimal(args.stop_price)
    if profit_price is None or stop_price is None:
        raise SystemExit("--profit-price and --stop-price are required and must be numeric")

    payload = _build_trigger_oco_payload(
        complex_type=args.complex_type,
        session=args.session,
        duration=args.duration,
        entry_type=args.entry_type,
        entry_price=_as_decimal(args.entry_price),
        entry_stop_price=_as_decimal(args.entry_stop_price),
        entry_instruction=entry_instruction,
        exit_instruction=exit_instruction,
        qty=qty,
        symbol=args.symbol,
        asset_type=args.asset_type.upper(),
        profit_price=float(profit_price),
        stop_price=float(stop_price),
        stop_limit_price=_as_decimal(args.stop_limit_price),
    )

    print(
        f"[place-trigger-oco] account={acct_num or acct_hash[:8]+'…'} "
        f"entry={entry_instruction} {args.symbol} qty={qty} entryType={_upper(args.entry_type)} "
        f"exit={exit_instruction}"
    )
    print("[place-trigger-oco] payload:\n" + _json_pretty(payload))

    if not args.submit:
        print("[place-trigger-oco] DRY-RUN (add --submit to send to Schwab)")
        return

    rest = _make_rest_client()
    out = rest.orders.place(acct_hash, payload)
    print(_json_pretty(out))

    _maybe_catchup(args)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="TGPS OMS CLI (Schwab)")
    ap.add_argument("--db", default=DEFAULT_DB, help=f"DuckDB path (default: {DEFAULT_DB})")

    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("list-open", help="List open orders from DuckDB")
    p.add_argument("--tickers", default="", help="Comma-separated tickers (underlying)")
    p.add_argument("--status", default="", help="Filter by status (e.g. WORKING, PENDING_ACTIVATION)")
    p.add_argument("--limit", type=int, default=50)
    p.set_defaults(func=cmd_list_open)

    def add_catchup_flags(x: argparse.ArgumentParser) -> None:
        x.add_argument("--refresh-after", action="store_true", help="After --submit, run fetch_orders_live once")
        x.add_argument("--refresh-lookback-days", type=int, default=7, help="Catch-up lookback days (default 7)")
        x.add_argument("--refresh-debug", action="store_true", help="Pass --debug to fetch_orders_live")

    p = sub.add_parser("cancel", help="Cancel an order (resolves old->new ids if available)")
    p.add_argument("--ticker", default="", help="Underlying ticker (optional but recommended)")
    p.add_argument("--order-id", required=True, help="Order ID as shown in open_orders_live")
    p.add_argument("--submit", action="store_true", help="Actually send cancel to Schwab")
    add_catchup_flags(p)
    p.set_defaults(func=cmd_cancel)

    p = sub.add_parser("replace", help="Replace (edit) a simple SINGLE order (LIMIT/STOP/STOP_LIMIT)")
    p.add_argument("--ticker", default="", help="Underlying ticker (optional but recommended)")
    p.add_argument("--order-id", required=True, help="Order ID as shown in open_orders_live")
    p.add_argument("--price", default=None, help="New LIMIT price (for LIMIT/STOP_LIMIT). Omit to keep current.")
    p.add_argument("--stop-price", default=None, help="New stop price (for STOP/STOP_LIMIT). Omit to keep current.")
    p.add_argument("--submit", action="store_true", help="Actually send replace to Schwab")
    add_catchup_flags(p)
    p.set_defaults(func=cmd_replace)

    p = sub.add_parser("replace-root", help="Replace the ROOT TRIGGER/OCO order (edit embedded OCO legs)")
    p.add_argument("--ticker", default="", help="Underlying ticker (recommended)")
    p.add_argument("--order-id", required=True, help="Any order id in the chain (child or root)")
    p.add_argument("--entry-price", default=None, help="Optional: new entry price (if entry is LIMIT/STOP_LIMIT)")
    p.add_argument("--profit-price", default=None, help="Optional: new OCO profit LIMIT price")
    p.add_argument("--stop-price", default=None, help="Optional: new OCO stop trigger (stopPrice)")
    p.add_argument("--stop-limit-price", default=None, help="Optional: new OCO stop-limit price (for STOP_LIMIT legs)")
    p.add_argument("--submit", action="store_true", help="Actually send replace-root to Schwab")
    add_catchup_flags(p)
    p.set_defaults(func=cmd_replace_root)

    p = sub.add_parser("place", help="Place a single-leg order (OPTIONS by default)")
    p.add_argument("--account", default=None, help="Account number (e.g. 41472449) or account hash")
    p.add_argument("--type", required=True, help="MARKET | LIMIT | STOP | STOP_LIMIT")
    p.add_argument("--symbol", required=True, help='Option symbol (e.g. "TTMI  260320C00080000")')
    p.add_argument("--asset-type", default="OPTION", help="OPTION | EQUITY")
    p.add_argument("--instruction", required=True, help="BUY_TO_OPEN | SELL_TO_OPEN | BUY_TO_CLOSE | SELL_TO_CLOSE")
    p.add_argument("--qty", required=True, type=float, help="Contracts (or shares)")
    p.add_argument("--price", default=None, help="Required for LIMIT/STOP_LIMIT")
    p.add_argument("--stop-price", default=None, help="Required for STOP/STOP_LIMIT")
    p.add_argument("--session", default="NORMAL", help="NORMAL (default) | AM | PM | SEAMLESS")
    p.add_argument("--duration", default="GOOD_TILL_CANCEL", help="DAY | GOOD_TILL_CANCEL")
    p.add_argument("--submit", action="store_true", help="Actually send order to Schwab")
    add_catchup_flags(p)
    p.set_defaults(func=cmd_place)

    p = sub.add_parser("place-bracket", help="Place a simple OCO bracket (profit LIMIT + stop leg)")
    p.add_argument("--account", default=None, help="Account number (e.g. 41472449) or account hash")
    p.add_argument("--symbol", required=True, help='Option symbol (e.g. "TTMI  260320C00080000")')
    p.add_argument("--asset-type", default="OPTION", help="OPTION | EQUITY")
    p.add_argument("--instruction", required=True, help="SELL_TO_CLOSE (long) or BUY_TO_CLOSE (short)")
    p.add_argument("--qty", required=True, type=float, help="Contracts (or shares)")
    p.add_argument("--profit-price", required=True, help="Profit target LIMIT price")
    p.add_argument("--stop-price", required=True, help="Stop trigger price")
    p.add_argument("--stop-limit-price", default=None, help="Optional STOP_LIMIT limit price (omit → STOP)")
    p.add_argument("--session", default="NORMAL", help="NORMAL (default) | AM | PM | SEAMLESS")
    p.add_argument("--duration", default="GOOD_TILL_CANCEL", help="DAY | GOOD_TILL_CANCEL")
    p.add_argument("--submit", action="store_true", help="Actually send OCO to Schwab")
    add_catchup_flags(p)
    p.set_defaults(func=cmd_place_bracket)

    p = sub.add_parser("place-trigger-oco", help="Place TRIGGER entry + OCO exits (profit + stop)")
    p.add_argument("--account", default=None, help="Account number (e.g. 41472449) or account hash")
    p.add_argument("--symbol", required=True, help='Option symbol (e.g. "KTOS  260116C00092500")')
    p.add_argument("--asset-type", default="OPTION", help="OPTION | EQUITY")
    p.add_argument("--qty", required=True, type=float, help="Contracts (or shares)")
    p.add_argument("--entry-instruction", required=True, help="BUY_TO_OPEN | SELL_TO_OPEN")
    p.add_argument("--exit-instruction", default="", help="Optional override. Default derived from entry.")
    p.add_argument("--entry-type", default="LIMIT", help="MARKET | LIMIT | STOP | STOP_LIMIT (default LIMIT)")
    p.add_argument("--entry-price", default=None, help="Required for entry LIMIT/STOP_LIMIT")
    p.add_argument("--entry-stop-price", default=None, help="Required for entry STOP/STOP_LIMIT")
    p.add_argument("--profit-price", required=True, help="OCO profit LIMIT price")
    p.add_argument("--stop-price", required=True, help="OCO stop trigger (stopPrice)")
    p.add_argument("--stop-limit-price", default=None, help="Optional OCO STOP_LIMIT limit price (omit → STOP)")
    p.add_argument("--complex-type", default="NONE", help="complexOrderStrategyType (default NONE)")
    p.add_argument("--session", default="NORMAL", help="NORMAL (default) | AM | PM | SEAMLESS")
    p.add_argument("--duration", default="GOOD_TILL_CANCEL", help="DAY | GOOD_TILL_CANCEL")
    p.add_argument("--submit", action="store_true", help="Actually send TRIGGER+OCO to Schwab")
    add_catchup_flags(p)
    p.set_defaults(func=cmd_place_trigger_oco)

    return ap


def main() -> None:
    args = build_parser().parse_args()

    if hasattr(args, "ticker"):
        args.ticker = (args.ticker or "").strip().upper()

    try:
        args.func(args)
    except RuntimeError as e:
        msg = str(e)
        if "unsupported_token_type" in msg or "refresh failed" in msg:
            _eprint("[error] Token refresh failed. Run: python -m client.schwab_admin login")
        raise


if __name__ == "__main__":
    main()
