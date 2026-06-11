#!/usr/bin/env python3
"""Upsert one OneJournal manual review row into DuckDB.

Safe scope:
- writes only to manual_reviews
- does not touch fills or trade episodes
- does not call broker APIs
- does not place, cancel, or modify orders
- does not enable auto-trade
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import duckdb

DEFAULT_DB = Path("data/journal/onejournal.duckdb")
ALLOWED_REVIEW_STATUS = {"unreviewed", "reviewed", "needs_review", "mistake_review"}
ALLOWED_SETUP_QUALITY = {"unknown", "good", "acceptable", "poor", "mistake"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Upsert one manual review into OneJournal DuckDB.")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="DuckDB database path.")
    parser.add_argument("--episode-uid", required=True, help="Episode UID to review.")
    parser.add_argument("--review-status", required=True, choices=sorted(ALLOWED_REVIEW_STATUS))
    parser.add_argument("--setup-quality", required=True, choices=sorted(ALLOWED_SETUP_QUALITY))
    parser.add_argument("--entry-reason", default="")
    parser.add_argument("--notes", default="")
    return parser.parse_args()


def upsert_review(db_path: Path, episode_uid: str, review_status: str, setup_quality: str, entry_reason: str, notes: str) -> None:
    updated_at = datetime.now().astimezone().replace(tzinfo=None)
    con = duckdb.connect(str(db_path))
    try:
        existing_episode = con.execute(
            "SELECT COUNT(*) FROM trade_episodes WHERE episode_uid = ?",
            [episode_uid],
        ).fetchone()[0]
        if existing_episode == 0:
            raise SystemExit(f"Episode UID not found in trade_episodes: {episode_uid}")
        con.execute(
            """
            INSERT OR REPLACE INTO manual_reviews (
                episode_uid, review_status, setup_quality, entry_reason, notes, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            [episode_uid, review_status, setup_quality, entry_reason, notes, updated_at],
        )
    finally:
        con.close()


def main() -> int:
    args = parse_args()
    db_path = Path(args.db)
    upsert_review(
        db_path=db_path,
        episode_uid=args.episode_uid,
        review_status=args.review_status,
        setup_quality=args.setup_quality,
        entry_reason=args.entry_reason,
        notes=args.notes,
    )
    print("===== OneJournal manual review DB upsert =====")
    print(f"DB            : {db_path}")
    print(f"EPISODE_UID   : {args.episode_uid}")
    print(f"REVIEW_STATUS : {args.review_status}")
    print(f"SETUP_QUALITY : {args.setup_quality}")
    print("SCOPE         : manual_reviews only")
    print("AUTO TRADE    : disabled")
    print("STATUS        : OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
