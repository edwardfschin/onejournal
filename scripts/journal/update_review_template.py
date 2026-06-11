#!/usr/bin/env python3
"""Update OneJournal manual review template from dashboard payload.

Read-only prototype utility.

This script does not call broker APIs, does not place orders, and does not auto-trade.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

DEFAULT_PAYLOAD = Path("output/dashboard/latest/dashboard_payload.json")
DEFAULT_REVIEWS = Path("data/journal/reviews/manual_reviews.csv")
FIELDNAMES = ["episode_uid", "review_status", "setup_quality", "entry_reason", "notes"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Update manual review CSV from dashboard payload.")
    parser.add_argument("--asof", required=True, help="Market date in YYYY-MM-DD format.")
    parser.add_argument("--payload", default=str(DEFAULT_PAYLOAD), help="Dashboard payload JSON path.")
    parser.add_argument("--reviews", default=str(DEFAULT_REVIEWS), help="Manual reviews CSV path.")
    return parser.parse_args()


def read_existing_reviews(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            return {}
        missing = sorted(set(FIELDNAMES) - set(reader.fieldnames))
        if missing:
            raise ValueError(f"Review CSV missing required column(s): {missing}")
        rows = {}
        for row in reader:
            episode_uid = (row.get("episode_uid") or "").strip()
            if episode_uid:
                rows[episode_uid] = {field: (row.get(field) or "") for field in FIELDNAMES}
        return rows


def load_episode_uids(payload_path: Path, asof: str) -> list[str]:
    if not payload_path.exists():
        raise FileNotFoundError(f"Dashboard payload not found: {payload_path}")
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    payload_asof = str(payload.get("metadata", {}).get("asof", ""))
    if payload_asof != asof:
        raise ValueError(f"Payload asof {payload_asof} does not match --asof {asof}")
    episodes = payload.get("recent_trade_episodes", [])
    episode_uids = []
    for episode in episodes:
        episode_uid = str(episode.get("episode_uid", "")).strip()
        if episode_uid:
            episode_uids.append(episode_uid)
    return sorted(set(episode_uids))


def write_reviews(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    args = parse_args()
    payload_path = Path(args.payload)
    reviews_path = Path(args.reviews)

    print("===== OneJournal review template update =====")
    print(f"ASOF      : {args.asof}")
    print(f"PAYLOAD   : {payload_path}")
    print(f"REVIEWS   : {reviews_path}")
    print("MODE      : read-only")
    print("AUTO TRADE: disabled")
    print()

    existing = read_existing_reviews(reviews_path)
    episode_uids = load_episode_uids(payload_path, args.asof)

    added = 0
    output_rows = []
    for episode_uid in episode_uids:
        if episode_uid in existing:
            output_rows.append(existing[episode_uid])
        else:
            added += 1
            output_rows.append({
                "episode_uid": episode_uid,
                "review_status": "unreviewed",
                "setup_quality": "unknown",
                "entry_reason": "",
                "notes": "",
            })

    write_reviews(reviews_path, output_rows)

    print("===== Result =====")
    print(f"EPISODES  : {len(episode_uids)}")
    print(f"EXISTING  : {len(existing)}")
    print(f"ADDED     : {added}")
    print(f"WROTE     : {reviews_path}")
    print()
    print("STATUS    : OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

