#!/usr/bin/env python3
"""Check simple trade episode preview building.

Purpose
-------
Read manual fills CSV, normalize fills, build simple trade episode previews,
and print a small review.

Read-only:
- no broker API calls
- no database writes
- no output files
- no order placement
- no order cancellation
- no automation
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from onejournal.brokers.manual_csv.fills import parse_manual_fills_csv
from onejournal.journal.episodes import build_episode_previews_from_fills


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check OneJournal trade episode preview generation."
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
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    asof = date.fromisoformat(args.asof)
    csv_path = Path(args.file)

    print("===== OneJournal trade episode check =====")
    print(f"ASOF      : {asof}")
    print(f"CSV FILE  : {csv_path}")
    print("MODE      : read-only")
    print("AUTO TRADE: disabled")
    print()

    fills = parse_manual_fills_csv(csv_path)
    episodes = build_episode_previews_from_fills(fills)

    mismatch_count = sum(1 for fill in fills if fill.asof != asof)

    print("===== Result =====")
    print(f"FILLS     : {len(fills)}")
    print(f"EPISODES  : {len(episodes)}")
    print(f"MISMATCH  : {mismatch_count} fill(s) with asof different from --asof")

    if not episodes:
        print("STATUS    : no episodes built")
        return 1

    first = episodes[0]

    print()
    print("===== First trade episode preview =====")
    print(f"episode_uid      : {first.episode_uid}")
    print(f"source_broker    : {first.source_broker}")
    print(f"source_account_id: {first.source_account_id}")
    print(f"primary_symbol   : {first.primary_symbol}")
    print(f"asset_class      : {first.asset_class}")
    print(f"strategy         : {first.strategy_label}")
    print(f"opened_at        : {first.opened_at}")
    print(f"status           : {first.status}")
    print(f"fill_count       : {first.fill_count}")
    print(f"net_quantity     : {first.net_quantity}")
    print(f"gross_cashflow   : {first.gross_cashflow}")
    print(f"total_commission : {first.total_commission}")
    print(f"total_fees       : {first.total_fees}")

    bad_primary_symbols = [
        episode
        for episode in episodes
        if episode.primary_symbol == episode.episode_uid.rsplit(":", 1)[-1]
        and "_" in episode.primary_symbol
    ]
    if bad_primary_symbols:
        print()
        print("STATUS    : failed primary_symbol quality check")
        for episode in bad_primary_symbols:
            print(f"BAD PRIMARY SYMBOL: {episode.episode_uid} -> {episode.primary_symbol}")
        return 1

    if mismatch_count:
        print()
        print("STATUS    : failed asof consistency check")
        return 1

    print()
    print("STATUS    : OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
