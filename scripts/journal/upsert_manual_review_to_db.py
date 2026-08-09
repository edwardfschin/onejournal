#!/usr/bin/env python3
"""Append one OneJournal review and update its compatibility projection.

Safe scope:
- writes journal_reviews history when migration 0005 is present
- updates manual_reviews compatibility projection
- does not touch fills or trade episodes
- does not call broker APIs
- does not place, cancel, or modify orders
- does not enable auto-trade
"""

from __future__ import annotations

import argparse
from pathlib import Path

import duckdb

from onejournal.journal.domain import ReviewWriteResult, save_review

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


def upsert_review(
    db_path: Path,
    episode_uid: str,
    review_status: str,
    setup_quality: str,
    entry_reason: str,
    notes: str,
) -> ReviewWriteResult:
    con = duckdb.connect(str(db_path))
    try:
        return save_review(
            con,
            episode_uid=episode_uid,
            review_status=review_status,
            setup_quality=setup_quality,
            entry_reason=entry_reason,
            notes=notes,
            source="streamlit",
        )
    finally:
        con.close()


def main() -> int:
    args = parse_args()
    db_path = Path(args.db)
    result = upsert_review(
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
    print(f"HISTORY_WRITE : {'yes' if result.history_written else 'no'}")
    print(f"COMPATIBILITY : {'legacy projection only' if result.compatibility_only else 'dual-write'}")
    print("SCOPE         : journal_reviews + manual_reviews compatibility projection")
    print("AUTO TRADE    : disabled")
    print("STATUS        : OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
