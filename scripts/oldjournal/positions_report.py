#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/journal/positions_report.py
Version: 0.3.0
Updated: 2025-12-05 (SGT)

Purpose
-------
Create a Schwab-UI-style positions report from LIVE positions stored in
DuckDB (journal.positions_live), and export an Excel workbook with:

  1) Summary – user-friendly view similar to Schwab UI:
       Instrument, Expiry, Strike, Type, Qty, DTE, Avg Price,
       Current Mark, P/L %, P/L Open, P/L Day (placeholder),
       Next Earnings, Earnings Estimate, Risk Flags.

  2) Positions_Raw – everything currently stored in
       journal.positions_live, plus derived fields:
       DTE, PL_FRACTION, next_earnings_date, earnings_is_estimate.

Notes
-----
- This script does NOT call Schwab directly. It assumes that
  scripts/journal/fetch_positions_live.py has already populated
  journal.positions_live.

- Report date for the filename is based on the latest UPDATED_AT
  timestamp in journal.positions_live, converted from UTC to
  America/New_York ("NYSE date").

- P/L % is stored as a FRACTION (0.10 = 10%) and formatted as
  a percentage in Excel.

- Earnings data:
    * Pulled from Yahoo Finance via yahooquery.Ticker.calendar_events
    * Uses earningsDate (string list, e.g. "2026-01-27 21:30:S")
      as the UPCOMING earnings date.
    * Ignores earningsDate values strictly before the NYSE date.
    * Added into Summary (Next Earnings, Earnings Estimate) and
      into Risk Flags as "Earnings Today" / "Earnings ≤7D".
"""

from __future__ import annotations

import os
from pathlib import Path
from datetime import datetime, date, timezone
from zoneinfo import ZoneInfo
from typing import Dict, List, Optional, Tuple

import duckdb
import pandas as pd
from yahooquery import Ticker
import json

UNDERLYING_PX_STALE_HOURS = 6
# ---------------------------------------------------------------------------
# DEFAULTS (standalone robustness)
# ---------------------------------------------------------------------------

WARM_IF_SNAP_MISSING = True
WARM_IF_SNAP_STALE = True  # re-warm if snap exists but timestamp too old
DEFAULT_WARM_OPTION_EXPIRIES = 3


# ---------------------------------------------------------------------------
# Paths / Config
# ---------------------------------------------------------------------------


def get_db_path() -> str:
    """
    Mirror fetch_positions_live.py so both scripts point to the same DB.
    """
    default = os.path.expanduser("~/tgps-project/data/journal/tgps_trades.duckdb")
    return os.environ.get("TGPS_JOURNAL_DB", default)


def get_output_dir() -> Path:
    """
    Output:
        ~/tgps-project/output/journal/positions/
    """
    p = Path(os.path.expanduser("~/tgps-project/output/journal/positions"))
    p.mkdir(parents=True, exist_ok=True)
    return p


NY_TZ = ZoneInfo("America/New_York")


# ---------------------------------------------------------------------------
# Helpers – NYSE date, classification, P/L, group maps
# ---------------------------------------------------------------------------
def snap_path_for_symbol(symbol: str) -> str:
    return os.path.expanduser(
        f"~/tgps-project/data/options_cache/{symbol}/underlying/latest.snap.json"
    )


def snap_age_hours(snap: dict, snapshot_ts_utc: datetime) -> Optional[float]:
    """
    Return snap age in hours vs snapshot_ts_utc (UTC). None if unknown.
    """
    if not snap:
        return None
    ts = snap.get("timestamp")
    if not ts:
        return None
    try:
        ts_dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if ts_dt.tzinfo is None:
            ts_dt = ts_dt.replace(tzinfo=timezone.utc)
        return (snapshot_ts_utc - ts_dt).total_seconds() / 3600.0
    except Exception:
        return None


def load_underlying_snap(symbol: str) -> Optional[dict]:
    """
    Load latest underlying snap for a symbol from option_cache.
    """
    path = os.path.expanduser(
        f"~/tgps-project/data/options_cache/{symbol}/underlying/latest.snap.json"
    )
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return None


def extract_underlying_price(snap: dict):
    """
    Extract underlying price using fallback order.
    Returns: (price, source, timestamp)
    """
    if not snap:
        return None, None, None

    for key in ("mid", "last", "price_for_sellput", "rth_close", "previous_close"):
        if key in snap and snap[key] is not None:
            return float(snap[key]), key, snap.get("timestamp")

    return None, None, snap.get("timestamp")


def get_nyse_date(con: duckdb.DuckDBPyConnection) -> date:
    """
    Use MAX(updated_at) from journal.positions_live as snapshot timestamp (UTC),
    convert to NY timezone and take the calendar date.
    """
    row = con.execute("SELECT MAX(updated_at) FROM journal.positions_live;").fetchone()

    if not row or row[0] is None:
        # Fallback: today in NY if table is empty (shouldn't happen)
        return datetime.now(tz=NY_TZ).date()

    ts = row[0]
    # DuckDB usually returns naive datetime; treat as UTC.
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    else:
        ts = ts.astimezone(timezone.utc)

    ny_dt = ts.astimezone(NY_TZ)
    return ny_dt.date()


def classify_type(
    asset_type: str, qty: float, put_call: Optional[str], dte: Optional[int]
) -> str:
    asset = (asset_type or "").upper()
    pc = (put_call or "").upper()

    if asset != "OPTION":
        return "Stock"

    if qty > 0:
        if pc == "CALL":
            return "Long Call"
        elif pc == "PUT":
            return "Long Put"
    elif qty < 0:
        if pc == "CALL":
            return "Short Call"
        elif pc == "PUT":
            return "Short Put"

    return "Option"


def compute_pl_fraction(open_pnl: float, market_value: float) -> Optional[float]:
    """
    P/L % as a FRACTION (0.10 == +10% gain).

    cost_basis = market_value - open_pnl
    Works for long/short positions consistently.
    """
    if open_pnl is None or market_value is None:
        return None

    cost_basis = market_value - open_pnl
    if cost_basis == 0:
        return None

    return float(open_pnl) / float(cost_basis)


def build_stock_qty_map(df: pd.DataFrame) -> Dict[str, float]:
    """
    Map underlying symbol -> total stock qty (non-option positions).
    """
    mask = df["asset_type"].str.upper().ne("OPTION")
    stocks = df.loc[mask].copy()
    if stocks.empty:
        return {}

    stocks["underlying_key"] = stocks["underlying"].fillna(stocks["symbol"])
    agg = stocks.groupby("underlying_key")["qty"].sum()
    return agg.to_dict()


def build_option_groups(df: pd.DataFrame) -> Dict[str, Dict[str, float]]:
    """
    For diagonal risk: track per underlying + put_call whether there are
    both longs and shorts with mismatched quantities.

    Returns:
        { key: {"long": total_long_qty, "short": total_short_abs_qty} }
        where key = f"{underlying}|{put_call}"
    """
    mask = df["asset_type"].str.upper().eq("OPTION")
    opts = df.loc[mask].copy()
    if opts.empty:
        return {}

    opts["underlying_key"] = opts["underlying"].fillna(opts["symbol"])
    opts["put_call_key"] = opts["put_call"].fillna("")

    groups: Dict[str, Dict[str, float]] = {}

    for _, row in opts.iterrows():
        key = f"{row['underlying_key']}|{row['put_call_key']}"
        qty = float(row["qty"] or 0.0)

        if key not in groups:
            groups[key] = {"long": 0.0, "short": 0.0}

        if qty > 0:
            groups[key]["long"] += qty
        elif qty < 0:
            groups[key]["short"] += abs(qty)

    return groups


def make_instrument_label(
    asset_type: str,
    symbol: str,
    underlying: Optional[str],
    expiry: Optional[pd.Timestamp],
    strike: Optional[float],
    put_call: Optional[str],
) -> str:
    """
    Approximate Schwab UI-style instrument text.
      GM              (stock)
      GM 20 MAR 26 65 CALL
    """
    asset = (asset_type or "").upper()
    sym = (symbol or "").strip()
    und = (underlying or sym or "").strip()
    pc = (put_call or "").upper()

    if asset != "OPTION" or expiry is pd.NaT or strike is None:
        return und or sym

    try:
        exp_dt = expiry.to_pydatetime().date()
        exp_str = exp_dt.strftime("%d %b %y").upper()
    except Exception:
        exp_str = ""

    strike_str = f"{strike:g}" if strike is not None else ""

    if pc == "CALL":
        pc_str = "CALL"
    elif pc == "PUT":
        pc_str = "PUT"
    else:
        pc_str = ""

    parts = [und, exp_str, strike_str, pc_str]
    return " ".join(p for p in parts if p)


# ---------------------------------------------------------------------------
# Earnings via yahooquery
# ---------------------------------------------------------------------------


def _parse_earnings_date_str(s: str) -> Optional[date]:
    """
    Handle strings like '2026-01-27 21:30:S'.
    We only care about the DATE portion.
    """
    if not s:
        return None
    try:
        date_part = s.split()[0]  # '2026-01-27'
        dt = datetime.fromisoformat(date_part)
        return dt.date()
    except Exception:
        return None


def fetch_next_earnings_map(
    symbols: List[str], nyse_date: date
) -> Tuple[Dict[str, date], Dict[str, bool]]:
    """
    For each symbol, fetch the *next* earnings date + is_estimate flag from Yahoo.

    We treat:
      - earningsDate (string list, e.g. "2026-01-27 21:30:S") as the UPCOMING earnings.
      - earningsCallDate (unix ts list) as LAST call (ignored for "next").

    We also ignore stale earningsDate values that are strictly before the
    given nyse_date, so we don't flag already-passed earnings as future risk.

    Returns:
        date_map: {symbol: next_earnings_date (date)}
        est_map:  {symbol: is_estimate (bool)}
    """
    date_map: Dict[str, date] = {}
    est_map: Dict[str, bool] = {}

    if not symbols:
        return date_map, est_map

    for sym in symbols:
        sym_clean = sym.strip()
        if not sym_clean:
            continue

        try:
            t = Ticker(sym_clean)
            ce = t.calendar_events
        except Exception as e:
            print(f"[positions_report] Earnings fetch error for {sym_clean}: {e}")
            continue

        entry = {}
        if isinstance(ce, dict):
            # Prefer explicit keys; fallback to whole dict if needed
            entry = ce.get(sym_clean) or ce.get(sym_clean.lower()) or ce

        if not isinstance(entry, dict):
            print(
                f"[positions_report] Unexpected calendar_events payload for {sym_clean}: {type(entry)} – skipping."
            )
            continue

        earnings = entry.get("earnings") or {}
        is_estimate = bool(earnings.get("isEarningsDateEstimate", True))

        next_dt: Optional[date] = None

        # Use earningsDate as the next earnings (string list).
        dates = earnings.get("earningsDate") or []
        if dates:
            next_dt = _parse_earnings_date_str(str(dates[0]))

        # If we found a date but it's in the past vs NYSE date, ignore it
        if next_dt and next_dt < nyse_date:
            print(
                f"[positions_report] Ignoring stale earningsDate {next_dt} for {sym_clean}"
            )
            next_dt = None

        if next_dt:
            date_map[sym_clean] = next_dt
            est_map[sym_clean] = is_estimate
            print(
                f"[positions_report] {sym_clean} next earnings: {next_dt} (estimate={is_estimate})"
            )
        else:
            print(f"[positions_report] No upcoming earnings date for {sym_clean}")

    return date_map, est_map


# ---------------------------------------------------------------------------
# Risk Flags
# ---------------------------------------------------------------------------


def compute_risk_flags(
    row: pd.Series,
    nyse_date: date,
    stock_qty_map: Dict[str, float],
    option_groups: Dict[str, Dict[str, float]],
) -> str:
    """
    Risk flags (comma-separated string):

      - Naked Call: short call with no underlying stock.
      - Naked Put:  short put with no stock (we can't see cash).
      - Assignment ≤7D: option with DTE <= 7.
      - Large Loss ≥50%: PL_FRACTION <= -0.50.
      - Large Profit ≥150%: PL_FRACTION >= 1.50.
      - Diagonal Risk (Qty mismatch): long+short of same underlying+PC with
        mismatched net quantities.
      - Underlying Missing: options on underlying with 0 stock qty.
      - Earnings Today: next_earnings_date == NYSE date.
      - Earnings ≤7D: 0 < days_to_earnings <= 7.
    """
    flags: List[str] = []

    asset_type = (row.get("asset_type") or "").upper()
    put_call = (row.get("put_call") or "").upper()
    qty = float(row.get("qty") or 0.0)
    dte = row.get("DTE")
    pl_frac = row.get("PL_FRACTION")
    underlying = (row.get("underlying") or row.get("symbol") or "").strip()

    next_earnings = row.get("next_earnings_date")

    # Earnings-based risk (applies to any asset, based on underlying)
    if isinstance(next_earnings, (datetime, date)):
        ed = (
            next_earnings.date()
            if isinstance(next_earnings, datetime)
            else next_earnings
        )
        delta_days = (ed - nyse_date).days
        if delta_days == 0:
            flags.append("Earnings Today")
        elif 0 < delta_days <= 7:
            flags.append("Earnings ≤7D")

    # Option-specific flags
    if asset_type == "OPTION":
        total_stock_qty = stock_qty_map.get(underlying, 0.0)

        if qty < 0 and put_call == "CALL":
            if total_stock_qty <= 0:
                flags.append("Naked Call")
                flags.append("Underlying Missing")
        elif qty < 0 and put_call == "PUT":
            if total_stock_qty <= 0:
                flags.append("Naked Put")

        # Assignment risk: near expiry
        if isinstance(dte, int) and dte <= 7:
            flags.append("Assignment ≤7D")

        # Diagonal risk: long + short options for same underlying+PC
        key = f"{underlying}|{put_call}"
        grp = option_groups.get(key)
        if grp:
            long_q = grp["long"]
            short_q = grp["short"]
            if long_q > 0 and short_q > 0 and abs(long_q - short_q) > 0.0:
                flags.append("Diagonal Risk (Qty mismatch)")

    # Large loss / large profit (applies to any asset)
    if isinstance(pl_frac, float):
        if pl_frac <= -0.50:
            flags.append("Large Loss ≥50%")
        elif pl_frac >= 1.50:
            flags.append("Large Profit ≥150%")

    if row.get("underlying_px_stale") is True:
        flags.append("Underlying Px Stale")

    return ", ".join(sorted(set(flags)))


# ---------------------------------------------------------------------------
# Core report builder
# ---------------------------------------------------------------------------


def build_summary(df: pd.DataFrame, nyse_date: date) -> pd.DataFrame:
    """
    Build the Schwab-style Summary view.
    """
    # Ensure expiry is date-only (defensive)
    if "expiry" in df.columns:
        try:
            df["expiry"] = pd.to_datetime(df["expiry"], errors="coerce").dt.date
        except Exception:
            pass

    df = df.copy()

    # Ensure numeric
    for col in (
        "qty",
        "long_qty",
        "short_qty",
        "avg_price",
        "market_value",
        "open_pnl",
    ):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # DTE (expiry is already a date)
    if "expiry" in df.columns:
        df["DTE"] = df["expiry"].apply(
            lambda x: (x - nyse_date).days if pd.notna(x) else None
        )

    # Classification
    df["Type"] = df.apply(
        lambda r: classify_type(
            r.get("asset_type"),
            r.get("qty") or 0.0,
            r.get("put_call"),
            r.get("DTE"),
        ),
        axis=1,
    )

    # Instrument label
    df["Instrument"] = df.apply(
        lambda r: make_instrument_label(
            r.get("asset_type"),
            r.get("symbol"),
            r.get("underlying"),
            r.get("expiry"),
            r.get("strike"),
            r.get("put_call"),
        ),
        axis=1,
    )

    # Derived mark – per-unit price (100x for options)
    def compute_mark(r: pd.Series) -> Optional[float]:
        qty = float(r.get("qty") or 0.0)
        mv = r.get("market_value")
        asset_type = (r.get("asset_type") or "").upper()
        if mv is None or qty == 0.0:
            return None

        if asset_type == "OPTION":
            return float(mv) / (abs(qty) * 100.0)
        else:
            return float(mv) / abs(qty)

    df["Mark"] = df.apply(compute_mark, axis=1)

    # Stock qty map & option group map for risk flags
    stock_qty_map = build_stock_qty_map(df)
    option_groups = build_option_groups(df)

    df["Risk Flags"] = df.apply(
        lambda r: compute_risk_flags(r, nyse_date, stock_qty_map, option_groups),
        axis=1,
    )

    # P/L Day – placeholder (Schwab has it; we don't yet)
    df["PL_Day"] = None

    summary = pd.DataFrame(
        {
            "Instrument": df["Instrument"],
            "Underlying": df.get("underlying"),
            "Expiry": df.get("expiry"),
            "Strike": df.get("strike"),
            "Underlying Px": df.get("underlying_px"),
            "Type": df["Type"],
            "Qty": df.get("qty"),
            "DTE": df.get("DTE"),
            "Avg Price": df.get("avg_price"),
            "Current Mark": df.get("Mark"),
            "P/L %": df.get("PL_FRACTION"),
            "P/L Open": df.get("open_pnl"),
            "Next Earnings": df.get("next_earnings_date"),
            "Earnings Estimate": df.get("earnings_is_estimate"),
            "P/L Day": df.get("PL_Day"),
            "Risk Flags": df.get("Risk Flags"),
        }
    )

    summary["Expiry_sort"] = summary["Expiry"]
    summary["Strike_sort"] = summary["Strike"]
    summary = summary.sort_values(
        by=["Instrument", "Expiry_sort", "Strike_sort"],
        ascending=[True, True, True],
        na_position="last",
    ).drop(columns=["Expiry_sort", "Strike_sort"])

    return summary


def build_raw(df: pd.DataFrame, nyse_date: date) -> pd.DataFrame:
    """
    Raw positions sheet – keep all original columns from
    journal.positions_live, plus derived fields:
        DTE, PL_FRACTION (and earnings fields already added in main()).
    """
    df = df.copy()

    for _, row in df.iterrows():
        symbol = (row.get("underlying") or row.get("symbol") or "").strip()
        snap = load_underlying_snap(symbol)

        if snap is None:
            print(f"[underlying_px] SNAP NOT FOUND for symbol={symbol}")

    # Force expiry to pure date (no time)
    if "expiry" in df.columns:
        try:
            df["expiry"] = df["expiry"].dt.date
        except Exception:
            pass

    # DTE (expiry is already a date)
    if "expiry" in df.columns:
        df["DTE"] = df["expiry"].apply(
            lambda x: (x - nyse_date).days if pd.notna(x) else None
        )

    for col in ("qty", "market_value", "open_pnl"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df["PL_FRACTION"] = df.apply(
        lambda r: compute_pl_fraction(r.get("open_pnl"), r.get("market_value")),
        axis=1,
    )

    # ------------------------------------------------------------------
    # Underlying price enrichment from option_cache
    # ------------------------------------------------------------------
    snapshot_ts = df["updated_at"].max()
    if snapshot_ts.tzinfo is None:
        snapshot_ts = snapshot_ts.replace(tzinfo=timezone.utc)

    px_values = []
    px_sources = []
    px_ts_list = []
    px_age_hrs = []
    px_stale = []

    for _, row in df.iterrows():
        symbol = (row.get("underlying") or row.get("symbol") or "").strip()
        snap = load_underlying_snap(symbol)

        px, src, ts = extract_underlying_price(snap)

        if ts:
            try:
                ts_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except Exception:
                ts_dt = None
        else:
            ts_dt = None

        if ts_dt:
            age = (snapshot_ts - ts_dt).total_seconds() / 3600.0
        else:
            age = None

        stale = age is not None and age > UNDERLYING_PX_STALE_HOURS

        px_values.append(px)
        px_sources.append(src)
        px_ts_list.append(ts_dt)
        px_age_hrs.append(age)
        px_stale.append(stale)

    df["underlying_px"] = px_values
    df["underlying_px_source"] = px_sources
    df["underlying_px_ts"] = px_ts_list
    df["underlying_px_age_hrs"] = px_age_hrs
    df["underlying_px_stale"] = px_stale

    # Excel cannot handle timezone-aware datetimes → strip tzinfo
    for col in ("updated_at", "underlying_px_ts"):
        if col in df.columns:
            try:
                df[col] = pd.to_datetime(df[col], errors="coerce").dt.tz_localize(None)
            except Exception:
                pass

    return df


# ---------------------------------------------------------------------------
# Excel export
# ---------------------------------------------------------------------------


def write_excel(
    summary: pd.DataFrame, raw: pd.DataFrame, nyse_date: date, out_dir: Path
) -> Path:
    """
    Write the two sheets into YYYY-MM-DD_positions_report.xlsx
    with basic formatting.
    """
    date_str = nyse_date.strftime("%Y-%m-%d")
    out_path = out_dir / f"{date_str}_positions_report.xlsx"

    with pd.ExcelWriter(out_path, engine="xlsxwriter") as writer:
        summary.to_excel(writer, sheet_name="Summary", index=False)
        raw.to_excel(writer, sheet_name="Positions_Raw", index=False)

        workbook = writer.book

        pct_fmt = workbook.add_format({"num_format": "0.00%"})
        money_fmt = workbook.add_format({"num_format": "#,##0.00"})
        int_fmt = workbook.add_format({"num_format": "0"})
        dte_fmt = workbook.add_format({"num_format": "0"})
        date_fmt = workbook.add_format({"num_format": "yyyy-mm-dd"})

        # Summary sheet formatting
        ws_sum = writer.sheets["Summary"]
        headers = {c: i for i, c in enumerate(summary.columns)}

        # P/L % as percentage
        if "P/L %" in headers:
            col_idx = headers["P/L %"]
            ws_sum.set_column(col_idx, col_idx, 10, pct_fmt)

        # Money columns
        for col_name in ("Avg Price", "Current Mark", "P/L Open"):
            if col_name in headers:
                idx = headers[col_name]
                ws_sum.set_column(idx, idx, 12, money_fmt)

        # Qty / DTE as integers
        for col_name in ("Qty", "DTE"):
            if col_name in headers:
                idx = headers[col_name]
                ws_sum.set_column(idx, idx, 8, dte_fmt)

        # Expiry as date
        if "Expiry" in headers:
            idx = headers["Expiry"]
            ws_sum.set_column(idx, idx, 12, date_fmt)

        # Underlying width
        if "Underlying" in headers:
            idx = headers["Underlying"]
            ws_sum.set_column(idx, idx, 12)

        # Next Earnings as date
        if "Next Earnings" in headers:
            idx = headers["Next Earnings"]
            ws_sum.set_column(idx, idx, 14, date_fmt)

        # Earnings Estimate as bool/text
        if "Earnings Estimate" in headers:
            idx = headers["Earnings Estimate"]
            ws_sum.set_column(idx, idx, 12)

        # Risk Flags column
        if "Risk Flags" in headers:
            idx = headers["Risk Flags"]
            ws_sum.set_column(idx, idx, 35)

        # Raw sheet formatting
        ws_raw = writer.sheets["Positions_Raw"]
        raw_headers = {c: i for i, c in enumerate(raw.columns)}

        # Expiry / updated_at as dates
        if "expiry" in raw_headers:
            idx = raw_headers["expiry"]
            ws_raw.set_column(idx, idx, 12, date_fmt)
        if "updated_at" in raw_headers:
            idx = raw_headers["updated_at"]
            ws_raw.set_column(idx, idx, 20, date_fmt)

        # DTE & qty as ints
        for col_name in ("DTE", "qty", "long_qty", "short_qty"):
            if col_name in raw_headers:
                idx = raw_headers[col_name]
                ws_raw.set_column(idx, idx, 10, int_fmt)

        # Money-style columns
        for col_name in ("avg_price", "market_value", "open_pnl"):
            if col_name in raw_headers:
                idx = raw_headers[col_name]
                ws_raw.set_column(idx, idx, 14, money_fmt)

        # PL_FRACTION as percentage
        if "PL_FRACTION" in raw_headers:
            idx = raw_headers["PL_FRACTION"]
            ws_raw.set_column(idx, idx, 10, pct_fmt)

        # next_earnings_date as date
        if "next_earnings_date" in raw_headers:
            idx = raw_headers["next_earnings_date"]
            ws_raw.set_column(idx, idx, 14, date_fmt)

        # underlying_px as money
        if "Underlying Px" in headers:
            idx = headers["Underlying Px"]
            ws_sum.set_column(idx, idx, 12, money_fmt)

        # underlying_px as money in Raw
        if "underlying_px" in raw_headers:
            idx = raw_headers["underlying_px"]
            ws_raw.set_column(idx, idx, 14, money_fmt)

    print(f"[positions_report] Wrote report → {out_path}")
    return out_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    db_path = get_db_path()
    print(f"[positions_report] Using DB: {db_path}")

    con = duckdb.connect(db_path)

    df_positions = con.execute("SELECT * FROM journal.positions_live;").df()

    # Keep only current positions (avoid stale zero-qty rows)
    if "qty" in df_positions.columns:
        df_positions = df_positions[
            pd.to_numeric(df_positions["qty"], errors="coerce").fillna(0) != 0
        ].copy()

    # ------------------------------------------------------------
    # Standalone robustness: warm missing/stale underlying snaps
    # ------------------------------------------------------------
    if df_positions.empty:
        print(
            "[positions_report] No rows in journal.positions_live – "
            "run fetch_positions_live.py first."
        )
        return

    # snapshot timestamp (UTC) used for staleness comparison
    snapshot_ts = df_positions["updated_at"].max()
    snapshot_ts = pd.to_datetime(snapshot_ts, errors="coerce")
    if snapshot_ts is None or pd.isna(snapshot_ts):
        snapshot_ts_utc = datetime.now(timezone.utc)
    else:
        # Treat naive as UTC; if tz-aware, normalize to UTC
        if snapshot_ts.tzinfo is None:
            snapshot_ts_utc = snapshot_ts.to_pydatetime().replace(tzinfo=timezone.utc)
        else:
            snapshot_ts_utc = snapshot_ts.to_pydatetime().astimezone(timezone.utc)

    held_underlyings = set(
        df_positions["underlying"]
        .fillna(df_positions["symbol"])
        .astype(str)
        .str.strip()
    )
    held_underlyings = set(s for s in held_underlyings if s)

    # Map: underlying -> does user hold OPTIONS on this underlying?
    has_options_map = (
        df_positions.assign(
            underlying_key=df_positions["underlying"]
            .fillna(df_positions["symbol"])
            .astype(str)
            .str.strip()
        )
        .groupby("underlying_key")["asset_type"]
        .apply(lambda s: (s.astype(str).str.upper() == "OPTION").any())
        .to_dict()
    )

    to_warm = set()

    for sym in held_underlyings:
        p = snap_path_for_symbol(sym)
        snap = load_underlying_snap(sym)

        if WARM_IF_SNAP_MISSING and not os.path.exists(p):
            to_warm.add(sym)
            continue

        if WARM_IF_SNAP_STALE and snap:
            age = snap_age_hours(snap, snapshot_ts_utc)
            if age is not None and age > UNDERLYING_PX_STALE_HOURS:
                to_warm.add(sym)

    if to_warm:
        to_warm_options = {s for s in to_warm if has_options_map.get(s, False)}
        to_warm_ohlcv_only = to_warm - to_warm_options

        print(
            f"[positions_report] Warming market data for {len(to_warm)} symbols "
            f"(missing/stale snaps): {sorted(to_warm)}"
        )

        from common.warm_market_dataset import warm_market_dataset

        if to_warm_ohlcv_only:
            print(
                f"[positions_report] OHLCV-only warm (no options): {sorted(to_warm_ohlcv_only)}"
            )
            warm_market_dataset(
                symbols=to_warm_ohlcv_only,
                warm_options=False,
            )

        if to_warm_options:
            print(f"[positions_report] OHLCV+options warm: {sorted(to_warm_options)}")
            warm_market_dataset(
                symbols=to_warm_options,
                option_expiries=DEFAULT_WARM_OPTION_EXPIRIES,
                warm_options=True,
            )
    else:
        print("[positions_report] Underlying snaps OK (no warm needed).")

    # ------------------------------------------------------------

    nyse_date = get_nyse_date(con)
    print(f"[positions_report] NYSE date for report: {nyse_date}")

    # Ensure expiry is datetime64[ns]
    if "expiry" in df_positions.columns:
        df_positions["expiry"] = pd.to_datetime(df_positions["expiry"], errors="coerce")

    # ---- Earnings enrichment (in-memory, no DB table) ----
    underlying_series = (
        df_positions["underlying"].fillna(df_positions["symbol"]).astype(str)
    )
    unique_syms = sorted(set(s.strip() for s in underlying_series if s.strip()))

    print(f"[positions_report] Fetching earnings for {len(unique_syms)} symbols...")
    earnings_date_map, earnings_est_map = fetch_next_earnings_map(
        unique_syms, nyse_date
    )

    def map_earnings_date(sym: str) -> Optional[date]:
        sym_clean = (sym or "").strip()
        return earnings_date_map.get(sym_clean)

    def map_earnings_est(sym: str) -> Optional[bool]:
        sym_clean = (sym or "").strip()
        return earnings_est_map.get(sym_clean)

    df_positions["next_earnings_date"] = underlying_series.apply(map_earnings_date)
    df_positions["earnings_is_estimate"] = underlying_series.apply(map_earnings_est)

    # ---- Build views ----
    raw = build_raw(df_positions, nyse_date)
    summary = build_summary(raw, nyse_date)

    out_dir = get_output_dir()
    write_excel(summary, raw, nyse_date, out_dir)


if __name__ == "__main__":
    main()
