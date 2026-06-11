#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/tgps_user/exec_plan.py
Version: 0.2.0 (2026-01-14, SGT)

Dry-run (default)
  python -m scripts.tgps_user.exec_plan
  python -m scripts.tgps_user.exec_plan preview --module sellput --account 41472449

Submit
  export TGPS_RUN_ID="$(date +%Y%m%d_%H%M%S)"
  python -m scripts.tgps_user.exec_plan submit --module sellput --account 41472449

Key change vs older submit_orders:
- payload de-dupe is scoped to run_id to avoid permanent blocking after CANCELLED/REJECTED.
  Unique index: (run_id, payload_sha256, dry_run)

Step boundary:
- Primary validation should happen in actions_capture validate/import (Step 7).
- exec_plan remains last-line safety before broker calls (Step 8).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import duckdb
import yaml

from common.order_keys import compute_base_key, compute_intent_key, compute_payload_hash, base_id_from_base_key, payload_id_from_payload_hash

# ---- Repo root bootstrap ----
CODE_DIR = Path(__file__).resolve().parents[2]
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from client.schwab_admin import AuthClient, TokenStore  # noqa: E402
from client.schwab_api import RestClient, RestSession  # noqa: E402

VALID_ENTRY_TYPES = {"LIMIT", "MARKET"}
VALID_DURATIONS = {"DAY", "GTC", "GOOD_TILL_CANCEL"}
VALID_EXIT_MODES = {"NONE", "TP_ONLY", "STOP_ONLY", "OCO"}
VALID_STOP_TYPES = {"STOP_MARKET", "STOP_LIMIT"}
VALID_ATTACH_EXIT = {"NO", "YES"}

# Block statuses where we should NOT re-submit (unless --force)
DEDUP_BLOCK_STATUSES = {
    "PENDING",
    "SUBMITTED",
    "SUBMITTED_NO_ID",
    "WORKING",
    "OPEN",
    "ACCEPTED",
    "QUEUED",
    "HELD",
    "PARTIALLY_FILLED",
    "FILLED",
    "REPLACED",
    "ERROR",  # keep blocked by default (safer)
}

# Statuses that are safe to retry (Policy B)
DEDUP_ALLOW_RESUBMIT_STATUSES = {
    "CANCELED",
    "CANCELLED",
    "REJECTED",
    "EXPIRED",
}


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


def _run_id() -> str:
    rid = (os.environ.get("TGPS_RUN_ID") or "").strip()
    if rid:
        return rid
    return datetime.now().strftime("%Y%m%d_%H%M%S")


# ----------------------------
# Helpers
# ----------------------------
def _as_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, str) and v.strip() == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).strip().replace("%", ""))
    except Exception:
        return None


def _upper(s: Any) -> str:
    return ("" if s is None else str(s)).strip().upper()


def _norm_duration(d: str) -> str:
    du = _upper(d) or "DAY"
    if du in ("GTC", "GOOD_TILL_CANCEL"):
        return "GOOD_TILL_CANCEL"
    return "DAY"


def _is_probably_hash(s: str) -> bool:
    s = s.strip()
    if len(s) != 64:
        return False
    return all(c in "0123456789abcdefABCDEF" for c in s)


def _json_dumps_sorted(x: Any) -> str:
    return json.dumps(x, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _sanitize_underlying(sym: str) -> str:
    s = _upper(sym)
    s = re.sub(r"[^A-Z0-9]", "", s)
    return s


def _occ_option_symbol(underlying: str, expiry: date, right: str, strike: float) -> str:
    root = _sanitize_underlying(underlying)
    root = (root[:6]).ljust(6)
    yymmdd = expiry.strftime("%y%m%d")
    r = right.upper()
    if r not in ("P", "C"):
        raise ValueError(f"Invalid right: {right}")
    strike_i = int(round(float(strike) * 1000.0))
    return f"{root}{yymmdd}{r}{strike_i:08d}"


def _derive_close_instruction(entry_instruction: str) -> str:
    ei = _upper(entry_instruction)
    if ei == "BUY_TO_OPEN":
        return "SELL_TO_CLOSE"
    if ei == "SELL_TO_OPEN":
        return "BUY_TO_CLOSE"
    return ""


def _extract_location_order_id(location: str) -> str:
    if not location:
        return ""
    m = re.search(r"/orders/([^/?#]+)", str(location))
    return (m.group(1) if m else "").strip()


def _extract_order_id_from_response(resp: Any) -> str:
    if isinstance(resp, dict):
        oid = str(resp.get("order_id") or "").strip()
        if oid:
            return oid

        headers = resp.get("headers") or {}
        if isinstance(headers, dict):
            loc = headers.get("Location") or headers.get("location") or ""
            oid2 = _extract_location_order_id(str(loc))
            if oid2:
                return oid2

        oid3 = str(resp.get("orderId") or resp.get("id") or "").strip()
        return oid3
    return ""

def _right_for_module(module: str) -> str:
    m = (module or "").strip().lower()
    # conservative default: sellput => Put
    if "sellcall" in m or "coveredcall" in m or "call" in m:
        return "C"
    return "P"


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


def _cols(con: duckdb.DuckDBPyConnection, table_name: str) -> Dict[str, str]:
    rows = con.execute(
        """
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_catalog='ledger' AND table_schema='lcl' AND table_name=?
        ORDER BY ordinal_position
        """,
        [table_name],
    ).fetchall()
    return {r[0]: r[1] for r in rows}


# ----------------------------
# Ledger read (actions)
# ----------------------------
def _fetch_latest_execute_actions(
    con: duckdb.DuckDBPyConnection,
    module: str,
    run_id: str = "",
) -> List[dict]:
    """
    IMPORTANT:
    Rank the latest action per idea_key FIRST (any action),
    then only keep rows where that latest action is EXECUTE.

    Additionally:
    If ledger.lcl.actions has a run_id column and a run_id is provided,
    we *prefer* actions from that run_id (so old EXECUTE actions don't haunt planning).
    If no rows exist for that run_id, we fall back to the legacy behavior.
    """
    a_cols = _cols(con, "actions")

    def has(c: str) -> bool:
        return c in a_cols

    notes_expr = "COALESCE(a.user_notes, a.notes)" if (has("user_notes") and has("notes")) else (
        "a.user_notes" if has("user_notes") else ("a.notes" if has("notes") else "NULL")
    )

    strike_expr = "CAST(a.strike_found AS DOUBLE)" if has("strike_found") else (
        "CAST(a.strike AS DOUBLE)" if has("strike") else "CAST(NULL AS DOUBLE)"
    )
    expiry_expr = "CAST(a.expiry AS DATE)" if has("expiry") else "CAST(NULL AS DATE)"

    ts_expr = "CAST(a.action_ts AS TIMESTAMP)" if has("action_ts") else (
        "CAST(a.updated_at AS TIMESTAMP)" if has("updated_at") else (
            "CAST(a.created_at AS TIMESTAMP)" if has("created_at") else "CAST(NULL AS TIMESTAMP)"
        )
    )

    base_key_expr = (
        f"COALESCE(a.ticker,'') || '|' "
        f"|| COALESCE(CAST({expiry_expr} AS VARCHAR),'') || '|' "
        f"|| COALESCE(CAST({strike_expr} AS VARCHAR),'')"
    )
    idea_key_expr = f"COALESCE(a.idea_id, {base_key_expr})" if has("idea_id") else base_key_expr

    entry_order_type_expr = "a.entry_order_type" if has("entry_order_type") else "'LIMIT'"
    duration_expr = "a.duration" if has("duration") else "'DAY'"
    attach_exit_expr = "a.attach_exit" if has("attach_exit") else "'NO'"
    exit_mode_expr = "a.exit_mode" if has("exit_mode") else "'NONE'"
    tp_limit_expr = "CAST(a.tp_limit AS DOUBLE)" if has("tp_limit") else "CAST(NULL AS DOUBLE)"
    stop_type_expr = "a.stop_type" if has("stop_type") else "'STOP_MARKET'"
    stop_price_expr = "CAST(a.stop_price AS DOUBLE)" if has("stop_price") else "CAST(NULL AS DOUBLE)"
    stop_limit_expr = "CAST(a.stop_limit_price AS DOUBLE)" if has("stop_limit_price") else "CAST(NULL AS DOUBLE)"
    qty_expr = "CAST(a.qty_override AS DOUBLE)" if has("qty_override") else "CAST(NULL AS DOUBLE)"
    limit_override_expr = "CAST(a.limit_price_override AS DOUBLE)" if has("limit_price_override") else "CAST(NULL AS DOUBLE)"

    def run_query(use_run_id: bool) -> List[tuple]:
        run_clause = " AND a.run_id = ? " if (use_run_id and has("run_id") and run_id.strip()) else ""
        params = [module] + ([run_id.strip()] if ("a.run_id = ?" in run_clause) else [])

        sql = f"""
        WITH ranked AS (
          SELECT
            a.module AS module,
            a.ticker AS ticker,
            {expiry_expr} AS expiry,
            {strike_expr} AS strike_found,
            a.action AS action,
            {ts_expr} AS action_ts,
            {qty_expr} AS qty_override,
            {limit_override_expr} AS limit_price_override,
            {notes_expr} AS user_notes,
            {entry_order_type_expr} AS entry_order_type,
            {duration_expr} AS duration,
            {attach_exit_expr} AS attach_exit,
            {exit_mode_expr} AS exit_mode,
            {tp_limit_expr} AS tp_limit,
            {stop_type_expr} AS stop_type,
            {stop_price_expr} AS stop_price,
            {stop_limit_expr} AS stop_limit_price,
            {idea_key_expr} AS idea_key,
            row_number() OVER (
              PARTITION BY {idea_key_expr}
              ORDER BY {ts_expr} DESC NULLS LAST
            ) AS rn
          FROM ledger.lcl.actions a
          WHERE a.module = ?
          {run_clause}
        )
        SELECT
          module, ticker, expiry, strike_found, action, action_ts,
          qty_override, limit_price_override, user_notes,
          entry_order_type, duration, attach_exit,
          exit_mode, tp_limit, stop_type, stop_price, stop_limit_price,
          idea_key
        FROM ranked
        WHERE rn = 1
          AND upper(COALESCE(action,'')) = 'EXECUTE'
        ORDER BY action_ts DESC NULLS LAST
        """
        return con.execute(sql, params).fetchall()

    # Prefer run_id-scoped actions if possible; fallback if none found.
    use_run_id = bool(run_id.strip()) and has("run_id")
    rows = run_query(use_run_id=True) if use_run_id else run_query(use_run_id=False)
    if use_run_id and not rows:
        rows = run_query(use_run_id=False)

    cols_out = [
        "module", "ticker", "expiry", "strike_found", "action", "action_ts",
        "qty_override", "limit_price_override", "user_notes",
        "entry_order_type", "duration", "attach_exit",
        "exit_mode", "tp_limit", "stop_type", "stop_price", "stop_limit_price",
        "idea_key",
    ]
    return [{cols_out[i]: r[i] for i in range(len(cols_out))} for r in rows]



# ----------------------------
# Planning / validation (last-line safety)
# ----------------------------
def _plan_entry_limit(entry_type: str, limit_override: Optional[float]) -> Tuple[Optional[float], List[str]]:
    blockers: List[str] = []
    if entry_type == "MARKET":
        if limit_override is not None:
            blockers.append("MARKET entry cannot have Limit Price Override (must be blank).")
        return None, blockers
    if limit_override is not None:
        return float(limit_override), blockers
    blockers.append("Missing entry price: LIMIT order requires Limit Price Override.")
    return None, blockers


def _exit_blockers(
    attach_exit: str,
    exit_mode: str,
    tp_limit: Optional[float],
    stop_type: str,
    stop_price: Optional[float],
    stop_limit: Optional[float],
) -> List[str]:
    blockers: List[str] = []
    ax = (attach_exit or "NO").upper()
    mode = (exit_mode or "NONE").upper()
    st = (stop_type or "STOP_MARKET").upper()

    if ax not in VALID_ATTACH_EXIT:
        blockers.append(f"Invalid Attach Exit: {ax}")
        ax = "NO"

    if ax == "NO":
        # If exits provided, block (should not happen if Step 7 worked)
        if tp_limit is not None or stop_price is not None or stop_limit is not None:
            blockers.append("Attach Exit is NO but exit prices were provided.")
        return blockers

    if mode not in VALID_EXIT_MODES:
        blockers.append(f"Invalid Exit Mode: {mode}")
        return blockers

    if mode == "NONE":
        if tp_limit is not None or stop_price is not None or stop_limit is not None:
            blockers.append("Exit Mode NONE but TP/Stop provided.")
        return blockers

    if mode in ("TP_ONLY", "OCO") and tp_limit is None:
        blockers.append("Exit Mode requires TP Limit but it is empty")

    if mode in ("STOP_ONLY", "OCO"):
        if stop_price is None:
            blockers.append("Exit Mode requires Stop Price but it is empty")
        if st not in VALID_STOP_TYPES:
            blockers.append(f"Invalid Stop Type: {st}")
        elif st == "STOP_LIMIT":
            if stop_limit is None:
                blockers.append("STOP_LIMIT requires Stop Limit Price but it is empty")
            elif stop_price is not None and stop_limit < stop_price:
                blockers.append("STOP_LIMIT safety: Stop Limit Price must be >= Stop Price (buy-to-close)")

    if mode == "STOP_ONLY" and tp_limit is not None:
        blockers.append("STOP_ONLY does not allow TP Limit (must be empty).")

    if mode == "TP_ONLY" and (stop_price is not None or stop_limit is not None):
        blockers.append("TP_ONLY does not allow stop fields.")

    return blockers


@dataclass
class PlannedOrder:
    plan_status: str
    blockers: List[str]
    module: str
    idea_key: str

    ticker: str
    expiry: date
    strike_found: float
    qty: int

    entry_order_type: str
    entry_limit: Optional[float]
    duration: str

    attach_exit: str
    exit_mode: str
    tp_limit: Optional[float]
    stop_type: str
    stop_price: Optional[float]
    stop_limit_price: Optional[float]

    option_symbol: str
    user_notes: Optional[str]

    # New: stable keys (broker-agnostic)
    base_key: str
    intent_key: str
    payload_hash: str
    base_id: str
    payload_id: str



def _build_plans(rows: List[dict], *, module: str) -> List[PlannedOrder]:
    planned: List[PlannedOrder] = []
    right = _right_for_module(module)

    for r in rows:
        ticker = _upper(r.get("ticker"))
        expiry = r.get("expiry")
        if not isinstance(expiry, date):
            raise SystemExit(f"Invalid expiry in ledger for {ticker}: {expiry!r}")

        strike = float(r.get("strike_found"))
        qty = int(_as_float(r.get("qty_override")) or 1)
        if qty <= 0:
            qty = 1

        # ---- parse/normalize plan fields first ----
        entry_type = _upper(r.get("entry_order_type") or "LIMIT")
        if entry_type not in VALID_ENTRY_TYPES:
            entry_type = "LIMIT"

        duration_in = _upper(r.get("duration") or "DAY")
        if duration_in not in VALID_DURATIONS:
            duration_in = "DAY"
        duration = _norm_duration(duration_in)

        attach_exit = _upper(r.get("attach_exit") or "NO")
        if attach_exit not in VALID_ATTACH_EXIT:
            attach_exit = "NO"

        exit_mode = _upper(r.get("exit_mode") or "NONE")
        tp_limit = _as_float(r.get("tp_limit"))

        stop_type = _upper(r.get("stop_type") or "STOP_MARKET")
        stop_price = _as_float(r.get("stop_price"))
        stop_limit = _as_float(r.get("stop_limit_price"))

        blockers: List[str] = []

        entry_limit, b1 = _plan_entry_limit(entry_type, _as_float(r.get("limit_price_override")))
        blockers += b1
        blockers += _exit_blockers(attach_exit, exit_mode, tp_limit, stop_type, stop_price, stop_limit)

        try:
            opt_symbol = _occ_option_symbol(ticker, expiry, right, strike)
        except Exception as e:
            blockers.append(f"Cannot build option symbol: {e}")
            opt_symbol = ""

        # ---- stable keys AFTER final plan fields are known ----
        exp_iso = expiry.isoformat()

        base_key = compute_base_key(
            module=module,
            ticker=ticker,
            expiry_iso=exp_iso,
            right=right,
            strike=float(strike),
        )
        intent_key = compute_intent_key(base_key=base_key, qty=int(qty))

        plan_params = {
            "module": module,
            "ticker": ticker,
            "expiry": exp_iso,
            "right": right,
            "strike": float(strike),
            "qty": int(qty),
            "entry_order_type": entry_type,
            "entry_limit": (None if entry_limit is None else float(entry_limit)),
            "duration": duration,
            "attach_exit": attach_exit,
            "exit_mode": exit_mode,
            "tp_limit": (None if tp_limit is None else float(tp_limit)),
            "stop_type": stop_type,
            "stop_price": (None if stop_price is None else float(stop_price)),
            "stop_limit_price": (None if stop_limit is None else float(stop_limit)),
        }
        payload_hash = compute_payload_hash(plan_params)

        base_id = base_id_from_base_key(base_key)
        payload_id = payload_id_from_payload_hash(payload_hash)

        planned.append(
            PlannedOrder(
                plan_status=("OK" if not blockers else "BLOCKED"),
                blockers=blockers,
                module=module,
                idea_key=str(r.get("idea_key") or ""),

                ticker=ticker,
                expiry=expiry,
                strike_found=strike,
                qty=qty,

                entry_order_type=entry_type,
                entry_limit=entry_limit,
                duration=duration,

                attach_exit=attach_exit,
                exit_mode=exit_mode,
                tp_limit=tp_limit,
                stop_type=stop_type,
                stop_price=stop_price,
                stop_limit_price=stop_limit,

                option_symbol=opt_symbol,
                user_notes=(None if r.get("user_notes") is None else str(r.get("user_notes"))),

                base_key=base_key,
                intent_key=intent_key,
                payload_hash=payload_hash,
                base_id=base_id,
                payload_id=payload_id,
            )
        )

    return planned



# ----------------------------
# Schwab payload builders
# ----------------------------
def _single_order_payload(
    *,
    order_type: str,
    session: str,
    duration: str,
    price: Optional[float],
    stop_price: Optional[float],
    instruction: str,
    qty: int,
    symbol: str,
    asset_type: str = "OPTION",
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
                "quantity": int(qty),
                "instrument": {"symbol": symbol, "assetType": asset_type},
            }
        ],
    }

    if ot in ("LIMIT", "STOP_LIMIT"):
        if price is None:
            raise SystemExit(f"{ot} requires a price")
        payload["price"] = float(price)

    if ot in ("STOP", "STOP_LIMIT"):
        if stop_price is None:
            raise SystemExit(f"{ot} requires stopPrice")
        payload["stopPrice"] = float(stop_price)

    return payload


def _oco_payload(
    *,
    session: str,
    duration: str,
    instruction: str,
    qty: int,
    symbol: str,
    profit_price: float,
    stop_type: str,
    stop_price: float,
    stop_limit_price: Optional[float],
) -> Dict[str, Any]:
    profit = _single_order_payload(
        order_type="LIMIT",
        session=session,
        duration=duration,
        price=profit_price,
        stop_price=None,
        instruction=instruction,
        qty=int(qty),
        symbol=symbol,
    )

    st = _upper(stop_type)
    if st == "STOP_MARKET":
        stop_leg = _single_order_payload(
            order_type="STOP",
            session=session,
            duration=duration,
            price=None,
            stop_price=stop_price,
            instruction=instruction,
            qty=int(qty),
            symbol=symbol,
        )
    else:
        if stop_limit_price is None:
            raise SystemExit("STOP_LIMIT requires stop_limit_price")
        stop_leg = _single_order_payload(
            order_type="STOP_LIMIT",
            session=session,
            duration=duration,
            price=stop_limit_price,
            stop_price=stop_price,
            instruction=instruction,
            qty=int(qty),
            symbol=symbol,
        )

    return {"orderStrategyType": "OCO", "childOrderStrategies": [profit, stop_leg]}


def _trigger_payload(
    *,
    session: str,
    duration: str,
    entry_type: str,
    entry_price: Optional[float],
    entry_instruction: str,
    qty: int,
    symbol: str,
    child_strategy: Dict[str, Any],
    complex_type: str = "NONE",
) -> Dict[str, Any]:
    et = _upper(entry_type)
    if et not in ("MARKET", "LIMIT", "STOP", "STOP_LIMIT"):
        raise SystemExit("entry_type must be MARKET|LIMIT|STOP|STOP_LIMIT")

    payload: Dict[str, Any] = {
        "orderStrategyType": "TRIGGER",
        "complexOrderStrategyType": complex_type,
        "orderType": et,
        "session": session,
        "duration": duration,
        "orderLegCollection": [
            {
                "instruction": entry_instruction,
                "quantity": int(qty),
                "instrument": {"symbol": symbol, "assetType": "OPTION"},
            }
        ],
        "childOrderStrategies": [child_strategy],
    }

    if et in ("LIMIT", "STOP_LIMIT"):
        if entry_price is None:
            raise SystemExit("Entry LIMIT/STOP_LIMIT requires entry_price")
        payload["price"] = float(entry_price)

    return payload


def _payload_for_plan(p: PlannedOrder) -> Dict[str, Any]:
    session = "NORMAL"
    entry_instr = "SELL_TO_OPEN"
    exit_instr = _derive_close_instruction(entry_instr) or "BUY_TO_CLOSE"

    if p.attach_exit == "NO" or p.exit_mode == "NONE":
        return _single_order_payload(
            order_type=p.entry_order_type,
            session=session,
            duration=p.duration,
            price=p.entry_limit,
            stop_price=None,
            instruction=entry_instr,
            qty=p.qty,
            symbol=p.option_symbol,
        )

    if p.exit_mode == "TP_ONLY":
        child = _single_order_payload(
            order_type="LIMIT",
            session=session,
            duration=p.duration,
            price=p.tp_limit,
            stop_price=None,
            instruction=exit_instr,
            qty=p.qty,
            symbol=p.option_symbol,
        )
        return _trigger_payload(
            session=session,
            duration=p.duration,
            entry_type=p.entry_order_type,
            entry_price=p.entry_limit,
            entry_instruction=entry_instr,
            qty=p.qty,
            symbol=p.option_symbol,
            child_strategy=child,
        )

    if p.exit_mode == "STOP_ONLY":
        st = _upper(p.stop_type)
        if st == "STOP_MARKET":
            child = _single_order_payload(
                order_type="STOP",
                session=session,
                duration=p.duration,
                price=None,
                stop_price=p.stop_price,
                instruction=exit_instr,
                qty=p.qty,
                symbol=p.option_symbol,
            )
        else:
            child = _single_order_payload(
                order_type="STOP_LIMIT",
                session=session,
                duration=p.duration,
                price=p.stop_limit_price,
                stop_price=p.stop_price,
                instruction=exit_instr,
                qty=p.qty,
                symbol=p.option_symbol,
            )
        return _trigger_payload(
            session=session,
            duration=p.duration,
            entry_type=p.entry_order_type,
            entry_price=p.entry_limit,
            entry_instruction=entry_instr,
            qty=p.qty,
            symbol=p.option_symbol,
            child_strategy=child,
        )

    oco = _oco_payload(
        session=session,
        duration=p.duration,
        instruction=exit_instr,
        qty=p.qty,
        symbol=p.option_symbol,
        profit_price=float(p.tp_limit),
        stop_type=p.stop_type,
        stop_price=float(p.stop_price),
        stop_limit_price=p.stop_limit_price,
    )
    return _trigger_payload(
        session=session,
        duration=p.duration,
        entry_type=p.entry_order_type,
        entry_price=p.entry_limit,
        entry_instruction=entry_instr,
        qty=p.qty,
        symbol=p.option_symbol,
        child_strategy=oco,
    )


# ----------------------------
# Account resolution
# ----------------------------
def _pick_account_from_journal(db_path: str) -> Optional[Tuple[str, str]]:
    p = os.path.expanduser(db_path)
    if not Path(p).exists():
        return None
    try:
        con = duckdb.connect(p, read_only=True)
    except Exception:
        return None
    try:
        r = con.execute(
            """
            select account_hash, account_number
            from journal.accounts
            where account_hash is not null
            order by account_number
            """
        ).fetchall()
        if len(r) == 1:
            return str(r[0][0]), str(r[0][1])
        return None
    except Exception:
        return None
    finally:
        try:
            con.close()
        except Exception:
            pass


def _resolve_account_hash(account: Optional[str], cfg_account: Optional[str], journal_db: str) -> Tuple[str, str]:
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


def _make_rest_client() -> RestClient:
    store = TokenStore()
    auth = AuthClient(store)
    session = RestSession(auth)
    return RestClient(session)


# ----------------------------
# order_submissions table (run_id-scoped payload de-dupe)
# ----------------------------
def _ensure_submissions_table(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS ledger.lcl.order_submissions (
          submission_id        VARCHAR,
          submitted_at         TIMESTAMP,
          run_id               VARCHAR,

          module               VARCHAR,
          idea_key             VARCHAR,

          ticker               VARCHAR,
          expiry               DATE,
          strike_found         DOUBLE,
          qty                  DOUBLE,

          entry_order_type     VARCHAR,
          entry_limit          DOUBLE,
          duration             VARCHAR,

          attach_exit          VARCHAR,
          exit_mode            VARCHAR,
          tp_limit             DOUBLE,
          stop_type            VARCHAR,
          stop_price           DOUBLE,
          stop_limit_price     DOUBLE,

          option_symbol        VARCHAR,

          -- exact broker payload (kept)
          payload_sha256       VARCHAR,
          payload_json         VARCHAR,

          -- broker-agnostic plan keys (new)
          base_key             VARCHAR,
          intent_key           VARCHAR,
          payload_hash         VARCHAR,
          base_id              VARCHAR,
          payload_id           VARCHAR,
          perm_ids_json        VARCHAR,

          broker               VARCHAR,
          account              VARCHAR,
          dry_run              BOOLEAN,
          status               VARCHAR,
          broker_order_id      VARCHAR,
          broker_response_json VARCHAR
        );
        """
    )

    cols = _colset(con, "order_submissions")
    # Add missing columns (idempotent)
    for c, typ in [
        ("run_id", "VARCHAR"),
        ("base_key", "VARCHAR"),
        ("intent_key", "VARCHAR"),
        ("payload_hash", "VARCHAR"),
        ("base_id", "VARCHAR"),
        ("payload_id", "VARCHAR"),
        ("perm_ids_json", "VARCHAR"),
    ]:
        if c not in cols:
            try:
                con.execute(f"ALTER TABLE ledger.lcl.order_submissions ADD COLUMN {c} {typ};")
            except Exception:
                pass

    # Keep your run_id-scoped crash-safe de-dupe
    try:
        con.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_submissions_payload_run ON ledger.lcl.order_submissions(run_id, payload_sha256, dry_run);"
        )
    except Exception:
        pass

    # Normalize legacy statuses (idempotent)
    try:
        con.execute(
            """
            UPDATE ledger.lcl.order_submissions
            SET status = 'SUBMITTED'
            WHERE status IS NOT NULL
              AND upper(trim(status)) = 'SENT'
            """
        )
    except Exception:
        pass

    try:
        con.execute("""
        UPDATE ledger.lcl.order_submissions
        SET status = 'CANCELED'
        WHERE status IS NOT NULL AND upper(trim(status)) = 'CANCELLED'
        """)
    except Exception:
        pass


def _get_existing_submission_by_payload_in_run(con: duckdb.DuckDBPyConnection, run_id: str, payload_sha: str) -> Optional[dict]:
    r = con.execute(
        """
        SELECT submitted_at, status, broker_order_id
        FROM ledger.lcl.order_submissions
        WHERE run_id=? AND payload_sha256=? AND dry_run=FALSE
        ORDER BY submitted_at DESC
        LIMIT 1
        """,
        [run_id, payload_sha],
    ).fetchone()
    if not r:
        return None
    return {"submitted_at": r[0], "status": r[1], "broker_order_id": r[2]}


def _get_existing_submission_by_idea(
    con: duckdb.DuckDBPyConnection,
    *,
    module: str,
    ticker: str,
    expiry: date,
    strike_found: float,
) -> Optional[dict]:
    r = con.execute(
        """
        SELECT submitted_at, status, broker_order_id, payload_sha256
        FROM ledger.lcl.order_submissions
        WHERE dry_run=FALSE
          AND module=?
          AND ticker=?
          AND expiry=?
          AND strike_found=?
        ORDER BY submitted_at DESC
        LIMIT 1
        """,
        [module, ticker, expiry, float(strike_found)],
    ).fetchone()
    if not r:
        return None
    return {"submitted_at": r[0], "status": r[1], "broker_order_id": r[2], "payload_sha256": r[3]}

def _get_latest_submission_by_base_key(
    con: duckdb.DuckDBPyConnection,
    *,
    module: str,
    broker: str,
    account: str,
    base_key: str,
) -> Optional[dict]:
    r = con.execute(
        """
        SELECT
          submitted_at,
          status,
          broker_order_id,
          payload_hash,
          payload_sha256,
          intent_key,
          payload_id,
          perm_ids_json
        FROM ledger.lcl.order_submissions
        WHERE dry_run=FALSE
          AND module=?
          AND broker=?
          AND account=?
          AND base_key=?
        ORDER BY submitted_at DESC NULLS LAST
        LIMIT 1
        """,
        [module, broker, account, base_key],
    ).fetchone()

    if not r:
        return None

    return {
        "submitted_at": r[0],
        "status": r[1],
        "broker_order_id": r[2],
        "payload_hash": r[3],
        "payload_sha256": r[4],
        "intent_key": r[5],
        "payload_id": r[6],
        "perm_ids_json": r[7],
    }


def _reserve_pending(con: duckdb.DuckDBPyConnection, params: list[Any]) -> bool:
    try:
        con.execute(
            """
            INSERT INTO ledger.lcl.order_submissions (
              submission_id, submitted_at, run_id,
              module, idea_key,
              ticker, expiry, strike_found, qty,
              entry_order_type, entry_limit, duration,
              attach_exit, exit_mode, tp_limit, stop_type, stop_price, stop_limit_price,
              option_symbol,
              payload_sha256, payload_json,
              base_key, intent_key, payload_hash, base_id, payload_id, perm_ids_json,
              broker, account,
              dry_run, status, broker_order_id, broker_response_json
            )
            VALUES (
              ?, ?, ?,
              ?, ?,
              ?, ?, ?, ?,
              ?, ?, ?,
              ?, ?, ?, ?, ?, ?,
              ?,
              ?, ?,
              ?, ?, ?, ?, ?, ?,
              ?, ?,
              ?, ?, ?, ?
            )
            """,
            params,
        )
        return True
    except Exception as e:
        msg = str(e).lower()
        if "duplicate" in msg or "constraint" in msg or "unique" in msg:
            return False
        raise



def _update_submission(
    con: duckdb.DuckDBPyConnection,
    run_id: str,
    payload_sha: str,
    *,
    status: str,
    broker_order_id: Optional[str],
    resp_json: Optional[str],
) -> None:
    con.execute(
        """
        UPDATE ledger.lcl.order_submissions
        SET status=?, broker_order_id=?, broker_response_json=?
        WHERE run_id=? AND payload_sha256=? AND dry_run=FALSE
        """,
        [status, broker_order_id, resp_json, run_id, payload_sha],
    )


# ----------------------------
# Compact table
# ----------------------------
def _fmt_num(x: Any, ndp: int = 2) -> str:
    if x is None:
        return ""
    try:
        v = float(x)
        s = f"{v:.{ndp}f}"
        return s.rstrip("0").rstrip(".")
    except Exception:
        return str(x)


def _print_plan_table(title: str, rows: List[PlannedOrder], state_by_key: Dict[str, str]) -> None:
    if not rows:
        return

    print(f"\n[{title}]")
    header = (
        f"{'STATE':<9}  {'TICKER':<6}  {'EXPIRY':<10}  {'STRK':>6}  {'Q':>2}  "
        f"{'ENTRY':<6} {'LMT':>6}  {'DUR':<14}  "
        f"{'AX':<2}  {'EXIT':<8}  {'TP':>6}  {'STP_T':<10}  {'STP':>6}  {'STP_L':>6}"
    )
    print(header)
    print("-" * len(header))

    for p in rows:
        exp = p.expiry.isoformat()
        strike = f"{p.strike_found:g}"
        ax = (p.attach_exit or "NO")[:2]
        state = state_by_key.get(p.idea_key, "NEW")
        print(
            f"{state:<9}  {p.ticker:<6}  {exp:<10}  {strike:>6}  {p.qty:>2}  "
            f"{p.entry_order_type:<6} {_fmt_num(p.entry_limit):>6}  {p.duration:<14}  "
            f"{ax:<2}  {p.exit_mode:<8}  {_fmt_num(p.tp_limit):>6}  {p.stop_type:<10}  "
            f"{_fmt_num(p.stop_price):>6}  {_fmt_num(p.stop_limit_price):>6}"
        )


# ----------------------------
# Main
# ----------------------------
def cmd_run(args: argparse.Namespace) -> int:
    repo = _repo_root()
    user_root = _user_root(repo)
    ledger = _ledger_path(user_root)
    if not ledger.exists():
        raise SystemExit(f"❌ Ledger not found: {ledger}\nRun actions_capture import first.")

    cfg = _load_user_yml(_cfg_path(user_root))
    cfg_acct = ((cfg.get("broker", {}) or {}).get("account") or "").strip()
    journal_db = args.journal_db or _journal_db_default()

    rid = _run_id()

    con = _connect_attached(ledger)
    try:
        _ensure_submissions_table(con)

        rows = _fetch_latest_execute_actions(con, module=args.module, run_id=rid)

        if args.tickers:
            wanted = {t.strip().upper() for t in args.tickers.split(",") if t.strip()}
            rows = [r for r in rows if str(r.get("ticker", "")).strip().upper() in wanted]

        planned = _build_plans(rows, module=args.module)
        total = len(planned)
        ok = [p for p in planned if p.plan_status == "OK"]
        blocked = [p for p in planned if p.plan_status != "OK"]

        mode = "SUBMIT" if args.submit else "DRY_RUN"
        print(f"[exec_plan] run_id={rid} mode={mode} module={args.module}  total={total}  OK={len(ok)}  BLOCKED={len(blocked)}")

        if blocked:
            print("\n[BLOCKED]")
            for p in blocked[:25]:
                print(f" - {p.ticker} {p.expiry} {p.strike_found:g} :: " + "; ".join(p.blockers))
            if len(blocked) > 25:
                print(f" ... ({len(blocked)-25} more blocked rows)")

        if not ok:
            print("\nNothing to process.")
            return 0

        acct_hash, acct_num = _resolve_account_hash(args.account, cfg_acct, journal_db)
        acct_label = acct_num or (acct_hash[:8] + "…")
        broker = "SCHWAB"

        account_key = acct_hash  # stable for de-dupe + storage (do NOT use acct_label)


        rest: Optional[RestClient] = None
        if args.submit:
            rest = _make_rest_client()

        # STATE per idea_key (IDEA de-dupe, not payload)
        state_by_key: Dict[str, str] = {}
        for p in ok:
            existing_idea = _get_existing_submission_by_idea(
                con, module=p.module, ticker=p.ticker, expiry=p.expiry, strike_found=p.strike_found
            )
            if existing_idea:
                st = str(existing_idea.get("status") or "EXISTS")
                state_by_key[p.idea_key] = st[:9]
            else:
                state_by_key[p.idea_key] = "NEW"

        limit_n = args.limit if args.limit else len(ok)
        _print_plan_table("OK (compact)", ok[:limit_n], state_by_key)

        print("\n[OK ORDERS]")
        sent = 0
        skipped = 0
        errors = 0

        for p in ok[:limit_n]:
            # Determine prior idea submission state (idea-level)
            existing_base = _get_latest_submission_by_base_key(
                con,
                module=p.module,
                broker=broker,
                account=account_key,
                base_key=p.base_key,
            )

            # Idea-level de-dupe (Policy B):
            # - allow resubmit if last status is CANCELED/REJECTED/EXPIRED
            # - otherwise block (active/success/unknown), unless --force
            if existing_base and (not args.force):
                st = _upper(existing_base.get("status"))
                prev_ph = (existing_base.get("payload_hash") or "").strip()

                exp = p.expiry.isoformat()
                strike = f"{p.strike_found:g}"

                if st in DEDUP_ALLOW_RESUBMIT_STATUSES:
                    print(f"\n--- RETRY allowed (last status={st}) {p.ticker} {exp} P{strike} qty={p.qty:g} acct={acct_label} ---")
                elif st in DEDUP_BLOCK_STATUSES:
                    if prev_ph and prev_ph == p.payload_hash:
                        print(f"\n--- SKIP (same intent already active; status={st}) {p.ticker} {exp} P{strike} qty={p.qty:g} acct={acct_label} ---")
                        print(f"status={existing_base.get('status')} submitted_at={existing_base.get('submitted_at')} order_id={existing_base.get('broker_order_id')}")
                        skipped += 1
                        continue

                    print(f"\n--- BLOCKED (needs cancel/replace; status={st}) {p.ticker} {exp} P{strike} qty={p.qty:g} acct={acct_label} ---")
                    print(f"Existing order_id={existing_base.get('broker_order_id')} submitted_at={existing_base.get('submitted_at')}")
                    print("Rule: any change (qty/price/exits) must cancel the working order first, or use --force.")
                    errors += 1
                    continue
                else:
                    print(f"\n--- BLOCKED (unknown status={st}) {p.ticker} {exp} P{strike} qty={p.qty:g} acct={acct_label} ---")
                    skipped += 1
                    continue


            # Build payload only for NEW (or if --force bypassed)
            payload = _payload_for_plan(p)
            payload_json = _json_dumps_sorted(payload)
            payload_sha = _sha256_text(payload_json)

            # Block exact payload duplicates only within the SAME run_id unless --force
            existing_payload_run = _get_existing_submission_by_payload_in_run(con, rid, payload_sha)
            if existing_payload_run and (not args.force):
                exp = p.expiry.isoformat()
                strike = f"{p.strike_found:g}"
                print(f"\n--- SKIP (same payload already exists in this run_id) {p.ticker} {exp} P{strike} qty={p.qty:g} acct={acct_label} ---")
                print(f"status={existing_payload_run.get('status')} submitted_at={existing_payload_run.get('submitted_at')} order_id={existing_payload_run.get('broker_order_id')}")
                skipped += 1
                continue

            print(f"\n--- {p.ticker} {p.expiry} P{p.strike_found:g} qty={p.qty:g} acct={acct_label} ---")
            print(payload_json)

            if not args.submit:
                continue

            now_ts = datetime.now()
            submission_id = uuid.uuid4().hex

            # ---- CRASH-SAFE RESERVATION BEFORE BROKER CALL (run_id scoped) ----
            reserved = _reserve_pending(
                con,
                [
                    submission_id,
                    now_ts,
                    rid,

                    p.module,
                    p.idea_key,

                    p.ticker,
                    p.expiry,
                    p.strike_found,
                    p.qty,

                    p.entry_order_type,
                    p.entry_limit,
                    p.duration,

                    p.attach_exit,
                    p.exit_mode,
                    p.tp_limit,
                    p.stop_type,
                    p.stop_price,
                    p.stop_limit_price,

                    p.option_symbol,

                    payload_sha,
                    payload_json,

                    p.base_key,
                    p.intent_key,
                    p.payload_hash,
                    p.base_id,
                    p.payload_id,
                    None,  # perm_ids_json (Schwab)

                    broker,
                    account_key,

                    False,      # dry_run
                    "PENDING",  # status
                    None,       # broker_order_id
                    None,       # broker_response_json
                ],
            )

            if (not reserved) and (not args.force):
                print("[SKIP] reservation exists for this payload in this run_id.")
                skipped += 1
                continue

            # ---- Broker call ----
            try:
                assert rest is not None
                resp = rest.orders.place(acct_hash, payload)
                broker_order_id = _extract_order_id_from_response(resp)
                status = "SUBMITTED" if broker_order_id else "SUBMITTED_NO_ID"
                resp_json = json.dumps(resp, ensure_ascii=False)

                _update_submission(con, rid, payload_sha, status=status, broker_order_id=(broker_order_id or None), resp_json=resp_json)
                print(f"[SUBMITTED] order_id={broker_order_id or '(missing; sync later)'}")
                sent += 1
            except Exception as e:
                errors += 1
                _update_submission(
                    con,
                    rid,
                    payload_sha,
                    status="ERROR",
                    broker_order_id=None,
                    resp_json=json.dumps({"error": str(e)}, ensure_ascii=False),
                )
                print(f"[ERROR] {p.ticker} {p.expiry} {p.strike_found:g}: {e}")

    finally:
        con.close()


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Step 8: Build + (optionally) submit Schwab orders from tgps-user ledger (EXECUTE actions)")

    ap.add_argument(
        "cmd",
        nargs="?",
        default="preview",
        choices=["preview", "submit"],
        help="Default is preview (dry-run). Use 'submit' to actually place orders at Schwab.",
    )

    ap.add_argument("--module", default="sellput", help="Module name (default: sellput)")
    ap.add_argument("--tickers", default="", help="Optional: comma-separated ticker filter")
    ap.add_argument("--limit", type=int, default=0, help="Optional: max OK orders to process (0 = all)")
    ap.add_argument("--account", default=None, help="Account number (e.g. 41472449) or account hash")
    ap.add_argument("--journal-db", default="", help=f"Journal DuckDB path (default: {_journal_db_default()})")
    ap.add_argument("--force", action="store_true", help="Bypass safety de-dupe (dangerous)")
    return ap


def main() -> int:
    args = build_parser().parse_args()

    if getattr(args, "limit", 0) and args.limit < 0:
        args.limit = 0
    if getattr(args, "journal_db", "") == "":
        args.journal_db = _journal_db_default()

    args.submit = (args.cmd == "submit")
    return int(cmd_run(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
