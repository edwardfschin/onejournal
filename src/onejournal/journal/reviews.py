"""Manual review override loader for OneJournal.

Purpose
-------
Load simple journal review fields from a local CSV file.

This is intentionally lightweight before adding DuckDB.

Read-only:
- no broker API calls
- no order placement
- no order cancellation
- no automation
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ManualReview:
    """Manual journal review fields for one trade episode."""

    episode_uid: str
    review_status: str = "unreviewed"
    setup_quality: str = "unknown"
    entry_reason: str = ""
    notes: str = ""


def load_manual_reviews(path: str | Path) -> dict[str, ManualReview]:
    """Load manual review rows keyed by episode_uid."""

    review_path = Path(path)

    if not review_path.exists():
        return {}

    reviews: dict[str, ManualReview] = {}

    with review_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)

        if reader.fieldnames is None:
            raise ValueError(f"Manual reviews CSV has no header row: {review_path}")

        required = {"episode_uid", "review_status", "setup_quality", "entry_reason", "notes"}
        missing = sorted(required - set(reader.fieldnames))
        if missing:
            raise ValueError(f"Manual reviews CSV missing required column(s): {missing}")

        for row_num, row in enumerate(reader, start=2):
            episode_uid = (row.get("episode_uid") or "").strip()
            if not episode_uid:
                raise ValueError(f"Row {row_num}: missing episode_uid")

            reviews[episode_uid] = ManualReview(
                episode_uid=episode_uid,
                review_status=(row.get("review_status") or "unreviewed").strip() or "unreviewed",
                setup_quality=(row.get("setup_quality") or "unknown").strip() or "unknown",
                entry_reason=(row.get("entry_reason") or "").strip(),
                notes=(row.get("notes") or "").strip(),
            )

    return reviews
