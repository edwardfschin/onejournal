#!/usr/bin/env python3
"""Check dashboard payload generation.

Purpose
-------
Read manual fills CSV, normalize fills, build trade episode previews, create a
small dashboard JSON payload, and optionally write it to output/dashboard/latest.

Read-only with respect to broker activity:
- no broker API calls
- no database writes
- no order placement
- no order cancellation
- no automation
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from onejournal.brokers.manual_csv.fills import parse_manual_fills_csv
from onejournal.dashboard.payload import build_dashboard_payload
from onejournal.journal.episodes import build_episode_previews_from_fills
from onejournal.journal.reviews import load_manual_reviews


DEFAULT_OUTPUT = Path("output/dashboard/latest/dashboard_payload.json")
DEFAULT_REVIEWS = Path("data/journal/reviews/manual_reviews.csv")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check OneJournal dashboard payload generation."
    )
    parser.add_argument(
        "--asof",
        required=True,
        help="Market date in YYYY-MM-DD format.",
    )
    parser.add_argument(
        "--file",
        required=True,
        help="Manual fills CSV file path.",
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT),
        help="Dashboard payload output path.",
    )
    parser.add_argument(
        "--reviews",
        default=str(DEFAULT_REVIEWS),
        help="Manual review CSV path. Missing file is allowed.",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write dashboard payload JSON. Without this flag, only preview.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    asof = date.fromisoformat(args.asof)
    csv_path = Path(args.file)
    output_path = Path(args.output)
    reviews_path = Path(args.reviews)

    print("===== OneJournal dashboard payload check =====")
    print(f"ASOF      : {asof}")
    print(f"CSV FILE  : {csv_path}")
    print(f"OUTPUT    : {output_path}")
    print(f"REVIEWS   : {reviews_path}")
    print("MODE      : read-only")
    print("AUTO TRADE: disabled")
    print(f"WRITE     : {args.write}")
    print()

    fills = parse_manual_fills_csv(csv_path)
    episodes = build_episode_previews_from_fills(fills)
    reviews = load_manual_reviews(reviews_path)
    payload = build_dashboard_payload(asof=asof, episodes=episodes, reviews=reviews)

    mismatch_count = sum(1 for fill in fills if fill.asof != asof)

    print("===== Result =====")
    print(f"FILLS     : {len(fills)}")
    print(f"EPISODES  : {len(episodes)}")
    print(f"REVIEWS   : {len(reviews)}")
    print(f"PAYLOAD   : version={payload['metadata']['version']}")
    print(f"MISMATCH  : {mismatch_count} fill(s) with asof different from --asof")

    if mismatch_count:
        print()
        print("STATUS    : failed asof consistency check")
        return 1

    if args.write:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(f"WROTE     : {output_path}")

    print()
    print("===== Payload preview =====")
    print(f"asof                  : {payload['metadata']['asof']}")
    print(f"auto_trade            : {payload['metadata']['auto_trade']}")
    print(f"trade_episode_previews: {payload['metadata']['record_counts']['trade_episode_previews']}")
    print(f"recent_trade_episodes : {len(payload['recent_trade_episodes'])}")

    print()
    print("STATUS    : OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
