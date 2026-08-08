#!/usr/bin/env python3
"""Build OneJournal dashboard payload from DuckDB.

Read-only DB-to-dashboard publisher.

This script does not call broker APIs, does not place orders, and does not auto-trade.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb

from onejournal.brokers.normalized import NormalizedFill
from onejournal.pnl import calculate_fifo_pnl_from_fills

DASHBOARD_PAYLOAD_VERSION = "0.1.0-db"
DEFAULT_DB = Path("data/journal/onejournal.duckdb")
DEFAULT_OUTPUT = Path("output/dashboard/latest/dashboard_payload_from_db.json")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build dashboard payload from OneJournal DuckDB.")
    parser.add_argument("--asof", required=True, help="Market date in YYYY-MM-DD format.")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="DuckDB database path.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Dashboard payload JSON path.")
    parser.add_argument("--write", action="store_true", help="Write dashboard payload JSON.")
    return parser.parse_args()


def _decimal_to_string(value: Any) -> str:
    if value is None:
        return "0.00"
    return f"{Decimal(str(value)):.2f}"


def _iso(value: Any) -> str:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _rows(con: duckdb.DuckDBPyConnection, sql: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
    result = con.execute(sql, params or [])
    cols = [d[0] for d in result.description]
    return [dict(zip(cols, row)) for row in result.fetchall()]


def _to_decimal(value: Any, field: str) -> Decimal:
    if value is None:
        raise ValueError(f"{field} must not be None for normalized fills")
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _build_fills_for_pnl(fills_rows: list[dict[str, Any]]) -> list[NormalizedFill]:
    return [
        NormalizedFill(
            fill_uid=row["fill_uid"],
            source_broker=row["source_broker"],
            source_account_id=row["source_account_id"],
            source_fill_id=row["source_fill_id"],
            source_order_id=row.get("source_order_id"),
            episode_group_id=row.get("episode_group_id"),
            asof=(
                row["asof_date"]
                if hasattr(row["asof_date"], "isoformat")
                else datetime.fromisoformat(str(row["asof_date"])).date()
            ),
            filled_at=row["filled_at"],
            asset_class=row["asset_class"],
            symbol=row["symbol"],
            side=row["side"],
            quantity=_to_decimal(row["quantity"], "quantity"),
            fill_price=_to_decimal(row["fill_price"], "fill_price"),
            commission=_to_decimal(row["commission"], "commission"),
            fees=_to_decimal(row["fees"], "fees"),
            currency=(row["currency"] or "USD").upper(),
            fetched_at=row["fetched_at"],
            raw_path=row.get("raw_path"),
            option_symbol=row.get("option_symbol"),
            underlying_symbol=row.get("underlying_symbol"),
            option_type=row.get("option_type"),
            expiry=row.get("expiry"),
            strike=_to_decimal(row["strike"], "strike") if row.get("strike") is not None else None,
            multiplier=_to_decimal(row["multiplier"], "multiplier") if row.get("multiplier") is not None else None,
            open_close=row.get("open_close"),
            execution_venue=row.get("execution_venue"),
            liquidity_flag=row.get("liquidity_flag"),
        )
        for row in fills_rows
    ]


def _build_currency_totals(values: dict[str, Decimal | None]) -> dict[str, str | None]:
    return {
        currency: _decimal_to_string(amount) if amount is not None else None
        for currency, amount in sorted(values.items())
    }


def build_payload(db_path: Path, asof: str) -> dict[str, Any]:
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        episodes = _rows(con, """
            SELECT
                e.episode_uid, e.source_broker, e.source_account_id, e.primary_symbol, e.asset_class,
                e.strategy_type, e.strategy_label, e.opened_at, e.status, e.fill_count, e.leg_count,
                e.leg_summary, e.cashflow_label, e.net_quantity, e.gross_cashflow, e.commission, e.fees,
                COALESCE(r.review_status, 'unreviewed') AS review_status,
                COALESCE(r.setup_quality, 'unknown') AS setup_quality,
                COALESCE(r.entry_reason, '') AS entry_reason,
                COALESCE(r.notes, '') AS notes
            FROM trade_episodes e
            LEFT JOIN manual_reviews r ON r.episode_uid = e.episode_uid
            ORDER BY e.opened_at DESC, e.episode_uid
        """)

        leg_rows = _rows(con, """
            SELECT episode_uid, leg_index, raw_leg_json
            FROM trade_episode_legs
            ORDER BY episode_uid, leg_index
        """)

        legs_by_episode: dict[str, list[dict[str, Any]]] = {}
        for row in leg_rows:
            raw = row.get("raw_leg_json") or "{}"
            try:
                leg = json.loads(raw)
            except json.JSONDecodeError:
                leg = {"raw_leg_json": raw}
            legs_by_episode.setdefault(str(row["episode_uid"]), []).append(leg)

        payload_episodes = []
        for e in episodes:
            episode_uid = str(e["episode_uid"])
            payload_episodes.append({
                "episode_uid": episode_uid,
                "source_broker": e["source_broker"],
                "source_account_id": e["source_account_id"],
                "primary_symbol": e["primary_symbol"],
                "asset_class": e["asset_class"],
                "strategy_type": e["strategy_type"],
                "strategy_label": e["strategy_label"],
                "review_status": e["review_status"],
                "setup_quality": e["setup_quality"],
                "entry_reason": e["entry_reason"],
                "notes": e["notes"],
                "opened_at": _iso(e["opened_at"]),
                "status": e["status"],
                "fill_count": int(e["fill_count"]),
                "leg_count": int(e["leg_count"]),
                "leg_summary": e["leg_summary"],
                "cashflow_label": e["cashflow_label"],
                "legs": legs_by_episode.get(episode_uid, []),
                "net_quantity": _decimal_to_string(e["net_quantity"]),
                "gross_cashflow": _decimal_to_string(e["gross_cashflow"]),
                "commission": _decimal_to_string(e["commission"]),
                "fees": _decimal_to_string(e["fees"]),
            })

        normalized_fill_rows = _rows(
            con,
            "SELECT * FROM normalized_fills ORDER BY source_account_id, source_broker, filled_at",
        )
        pnl_result = calculate_fifo_pnl_from_fills(_build_fills_for_pnl(normalized_fill_rows))

        open_episodes = [e for e in payload_episodes if e.get("status") == "open"]
        closed_episodes = [e for e in payload_episodes if e.get("status") == "closed"]
        gross_cashflow = con.execute("SELECT COALESCE(SUM(gross_cashflow), 0) FROM trade_episodes").fetchone()[0]
        commission = con.execute("SELECT COALESCE(SUM(commission), 0) FROM trade_episodes").fetchone()[0]
        fees = con.execute("SELECT COALESCE(SUM(fees), 0) FROM trade_episodes").fetchone()[0]

        return {
            "metadata": {
                "version": DASHBOARD_PAYLOAD_VERSION,
                "asof": asof,
                "generated_at": datetime.now().astimezone().isoformat(),
                "mode": "read_only",
                "auto_trade": "disabled",
                "source": "duckdb",
                "record_counts": {
                    "trade_episode_previews": len(payload_episodes),
                    "open_trade_episode_previews": len(open_episodes),
                    "closed_trade_episode_previews": len(closed_episodes),
                },
            },
            "trade_summary": {
                "gross_cashflow": _decimal_to_string(gross_cashflow),
                "commission": _decimal_to_string(commission),
                "fees": _decimal_to_string(fees),
                "realized_pnl_by_currency": _build_currency_totals(
                    pnl_result.total_realized_pnl_by_currency
                ),
                "unrealized_pnl_by_currency": _build_currency_totals(
                    pnl_result.total_unrealized_pnl_by_currency
                ),
            },
            "open_positions": [],
            "recent_trade_episodes": payload_episodes,
            "closed_trade_episodes": closed_episodes,
            "metrics_by_strategy": [],
            "risk_events": [],
            "journal_review_queue": [],
        }
    finally:
        con.close()


def main() -> int:
    args = parse_args()
    db_path = Path(args.db)
    output_path = Path(args.output)
    payload = build_payload(db_path, args.asof)
    print("===== OneJournal dashboard payload from DB =====")
    print(f"DB        : {db_path}")
    print(f"OUTPUT    : {output_path}")
    print(f"ASOF      : {args.asof}")
    print(f"EPISODES  : {len(payload['recent_trade_episodes'])}")
    print(f"SOURCE    : {payload['metadata']['source']}")
    print("MODE      : read-only")
    print("AUTO TRADE: disabled")
    if args.write:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        print(f"WROTE     : {output_path}")
    print("STATUS    : OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
