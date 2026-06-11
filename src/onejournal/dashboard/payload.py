"""Dashboard payload builder for OneJournal.

Purpose
-------
Convert simple trade episode previews into a dashboard-ready JSON payload.

This module is read-only with respect to broker activity:
- no broker API calls
- no order placement
- no order cancellation
- no automation

It only prepares a payload object. Writing the JSON file is done explicitly
by a script when requested.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from onejournal.journal.episodes import TradeEpisodePreview
from onejournal.journal.reviews import ManualReview


DASHBOARD_PAYLOAD_VERSION = "0.1.0"


def build_dashboard_payload(
    *,
    asof: date,
    episodes: list[TradeEpisodePreview],
    generated_at: datetime | None = None,
    reviews: dict[str, ManualReview] | None = None,
) -> dict[str, Any]:
    """Build a small dashboard payload from trade episode previews."""

    generated = generated_at or datetime.now().astimezone()
    review_map = reviews or {}

    open_episodes = [e for e in episodes if e.status == "open"]
    closed_episodes = [e for e in episodes if e.status == "closed"]

    total_gross_cashflow = sum(
        (e.gross_cashflow for e in episodes),
        Decimal("0"),
    )
    total_commission = sum(
        (e.total_commission for e in episodes),
        Decimal("0"),
    )
    total_fees = sum(
        (e.total_fees for e in episodes),
        Decimal("0"),
    )

    return {
        "metadata": {
            "version": DASHBOARD_PAYLOAD_VERSION,
            "asof": asof.isoformat(),
            "generated_at": generated.isoformat(),
            "mode": "read_only",
            "auto_trade": "disabled",
            "record_counts": {
                "trade_episode_previews": len(episodes),
                "open_trade_episode_previews": len(open_episodes),
                "closed_trade_episode_previews": len(closed_episodes),
            },
        },
        "trade_summary": {
            "gross_cashflow": _decimal_to_string(total_gross_cashflow),
            "commission": _decimal_to_string(total_commission),
            "fees": _decimal_to_string(total_fees),
        },
        "open_positions": [],
        "recent_trade_episodes": [_episode_to_payload(e, review_map.get(e.episode_uid)) for e in episodes],
        "closed_trade_episodes": [_episode_to_payload(e, review_map.get(e.episode_uid)) for e in closed_episodes],
        "metrics_by_strategy": [],
        "risk_events": [],
        "journal_review_queue": [],
    }


def _episode_to_payload(episode: TradeEpisodePreview, review: ManualReview | None = None) -> dict[str, Any]:
    review_status = review.review_status if review else "unreviewed"
    setup_quality = review.setup_quality if review else "unknown"
    entry_reason = review.entry_reason if review else ""
    notes = review.notes if review else ""
    return {
        "episode_uid": episode.episode_uid,
        "source_broker": episode.source_broker,
        "source_account_id": episode.source_account_id,
        "primary_symbol": episode.primary_symbol,
        "asset_class": episode.asset_class,
        "strategy_type": episode.strategy_type,
        "strategy_label": episode.strategy_label,
        "review_status": review_status,
        "setup_quality": setup_quality,
        "entry_reason": entry_reason,
        "notes": notes,
        "opened_at": episode.opened_at.isoformat(),
        "status": episode.status,
        "fill_count": episode.fill_count,
        "leg_count": episode.leg_count,
        "leg_summary": episode.leg_summary,
        "cashflow_label": episode.cashflow_label,
        "legs": episode.legs,
        "net_quantity": _decimal_to_string(episode.net_quantity),
        "gross_cashflow": _decimal_to_string(episode.gross_cashflow),
        "commission": _decimal_to_string(episode.total_commission),
        "fees": _decimal_to_string(episode.total_fees),
    }


def _decimal_to_string(value: Decimal) -> str:
    """Render Decimal safely for JSON payloads."""

    return format(value, "f")
