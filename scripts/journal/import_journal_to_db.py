#!/usr/bin/env python3
"""Import current OneJournal CSV-derived journal data into DuckDB.

Safe local importer.

This script does not call broker APIs, does not place orders, and does not auto-trade.
"""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime
from pathlib import Path

import duckdb

from onejournal.brokers.manual_csv.fills import parse_manual_fills_csv
from onejournal.journal.episodes import build_episode_previews_from_fills
from onejournal.journal.reviews import load_manual_reviews
from onejournal.journal.identity import dedupe_identical_fills

DEFAULT_DB = Path("data/journal/onejournal.duckdb")
DEFAULT_FILLS = Path("docs/examples/manual_csv/fills_template.csv")
DEFAULT_REVIEWS = Path("data/journal/reviews/manual_reviews.csv")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import OneJournal journal data into DuckDB.")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="DuckDB database path.")
    parser.add_argument("--asof", required=False, help="Optional as-of date in YYYY-MM-DD format. When provided, imported fills must match this date.")
    parser.add_argument("--file", dest="fills_alias", required=False, help="ODFS alias for --fills.")
    parser.add_argument("--fills", default=str(DEFAULT_FILLS), help="Manual fills CSV path.")
    parser.add_argument("--reviews", default=str(DEFAULT_REVIEWS), help="Manual reviews CSV path.")
    parser.add_argument("--replace", action="store_true", help="Replace existing imported journal rows.")
    args = parser.parse_args()
    if args.fills_alias:
        args.fills = args.fills_alias
    return args


def _to_text(value):
    if value is None:
        return None
    return str(value)


def import_to_db(db_path: Path, fills_path: Path, reviews_path: Path, replace: bool, asof: date | None = None) -> dict[str, int]:
    import_run_id = "manual_csv:" + datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
    imported_at = datetime.now().astimezone().replace(tzinfo=None)
    fills = parse_manual_fills_csv(fills_path)
    fills = dedupe_identical_fills(fills)
    if asof is not None:
        mismatch_count = sum(1 for fill in fills if fill.asof != asof)
        if mismatch_count:
            raise ValueError(f"{mismatch_count} fill(s) have asof different from --asof {asof}")
    episodes = build_episode_previews_from_fills(fills)
    reviews = load_manual_reviews(reviews_path)
    con = duckdb.connect(str(db_path))
    try:
        if replace:
            con.execute("DELETE FROM trade_episode_legs")
            con.execute("DELETE FROM trade_episodes")
            con.execute("DELETE FROM manual_reviews")
            con.execute("DELETE FROM normalized_fills")
            con.execute("DELETE FROM import_runs")

        con.executemany("""
            INSERT OR REPLACE INTO normalized_fills (
                fill_uid, source_broker, source_account_id, source_fill_id, source_order_id,
                episode_group_id, asof_date, filled_at, asset_class, symbol, side, quantity,
                fill_price, commission, fees, currency, fetched_at, raw_path, option_symbol,
                underlying_symbol, option_type, expiry, strike, multiplier, open_close,
                execution_venue, liquidity_flag, import_run_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            (
                f.fill_uid, f.source_broker, f.source_account_id, f.source_fill_id, f.source_order_id,
                f.episode_group_id, f.asof, f.filled_at.replace(tzinfo=None), f.asset_class, f.symbol, f.side, f.quantity,
                f.fill_price, f.commission, f.fees, f.currency, f.fetched_at.replace(tzinfo=None), f.raw_path, f.option_symbol,
                f.underlying_symbol, f.option_type, f.expiry, f.strike, f.multiplier, f.open_close,
                f.execution_venue, f.liquidity_flag, import_run_id,
            )
            for f in fills
        ])

        con.executemany("""
            INSERT OR REPLACE INTO manual_reviews (
                episode_uid, review_status, setup_quality, entry_reason, notes, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
        """, [
            (r.episode_uid, r.review_status, r.setup_quality, r.entry_reason, r.notes, imported_at)
            for r in reviews.values()
        ])

        con.executemany("""
            INSERT OR REPLACE INTO trade_episodes (
                episode_uid, source_broker, source_account_id, primary_symbol, asset_class,
                strategy_type, strategy_label, opened_at, status, fill_count, leg_count,
                leg_summary, cashflow_label, net_quantity, gross_cashflow, commission, fees, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            (
                e.episode_uid, e.source_broker, e.source_account_id, e.primary_symbol, e.asset_class,
                e.strategy_type, e.strategy_label, e.opened_at.replace(tzinfo=None), e.status, e.fill_count, e.leg_count,
                e.leg_summary, e.cashflow_label, e.net_quantity, e.gross_cashflow, e.total_commission, e.total_fees, imported_at,
            )
            for e in episodes
        ])

        leg_rows = []
        for e in episodes:
            for idx, leg in enumerate(e.legs, start=1):
                leg_rows.append((
                    e.episode_uid, idx, leg.get("asset_class"), leg.get("symbol"), leg.get("side"),
                    leg.get("quantity"), leg.get("option_type"), leg.get("expiry"), leg.get("strike"), json.dumps(leg, sort_keys=True),
                ))
        con.executemany("""
            INSERT OR REPLACE INTO trade_episode_legs (
                episode_uid, leg_index, asset_class, symbol, side, quantity, option_type, expiry, strike, raw_leg_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, leg_rows)

        con.execute("""
            INSERT OR REPLACE INTO import_runs (
                import_run_id, source_type, source_path, asof_date, imported_at, row_count, status, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (import_run_id, "manual_csv", str(fills_path), fills[0].asof if fills else None, imported_at, len(fills), "ok", "DB-1D initial CSV import"))

        return {
            "import_runs": con.execute("SELECT COUNT(*) FROM import_runs").fetchone()[0],
            "normalized_fills": con.execute("SELECT COUNT(*) FROM normalized_fills").fetchone()[0],
            "trade_episodes": con.execute("SELECT COUNT(*) FROM trade_episodes").fetchone()[0],
            "trade_episode_legs": con.execute("SELECT COUNT(*) FROM trade_episode_legs").fetchone()[0],
            "manual_reviews": con.execute("SELECT COUNT(*) FROM manual_reviews").fetchone()[0],
        }
    finally:
        con.close()


def main() -> int:
    args = parse_args()
    asof = date.fromisoformat(args.asof) if args.asof else None
    counts = import_to_db(Path(args.db), Path(args.fills), Path(args.reviews), args.replace, asof)
    print("===== OneJournal DB import =====")
    print(f"DB        : {args.db}")
    print(f"ASOF      : {args.asof or 'not enforced'}")
    print(f"FILLS     : {args.fills}")
    print(f"REVIEWS   : {args.reviews}")
    for key, value in counts.items():
        print(f"{key}: {value}")
    print("STATUS    : OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
