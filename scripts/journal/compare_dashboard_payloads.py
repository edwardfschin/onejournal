#!/usr/bin/env python3
"""Compare two OneJournal dashboard payload JSON files.

Read-only safety check before switching dashboard source.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

DEFAULT_LEFT = Path("output/dashboard/latest/dashboard_payload.json")
DEFAULT_RIGHT = Path("output/dashboard/latest/dashboard_payload_from_db.json")

COMPARE_FIELDS = [
    "episode_uid",
    "strategy_label",
    "review_status",
    "setup_quality",
    "entry_reason",
    "status",
    "leg_count",
    "leg_summary",
    "cashflow_label",
    "gross_cashflow",
    "commission",
    "fees",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare OneJournal dashboard payloads.")
    parser.add_argument("--left", default=str(DEFAULT_LEFT), help="Left payload path.")
    parser.add_argument("--right", default=str(DEFAULT_RIGHT), help="Right payload path.")
    return parser.parse_args()


def load_payload(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Payload not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def index_episodes(payload: dict) -> dict[str, dict]:
    return {str(e.get("episode_uid")): e for e in payload.get("recent_trade_episodes", [])}


def main() -> int:
    args = parse_args()
    left_path = Path(args.left)
    right_path = Path(args.right)
    left = load_payload(left_path)
    right = load_payload(right_path)
    left_eps = index_episodes(left)
    right_eps = index_episodes(right)

    print("===== OneJournal dashboard payload compare =====")
    print(f"LEFT      : {left_path}")
    print(f"RIGHT     : {right_path}")
    print(f"LEFT SRC  : {left.get('metadata', {}).get('source', 'csv_or_legacy')}")
    print(f"RIGHT SRC : {right.get('metadata', {}).get('source', 'unknown')}")
    print(f"LEFT EPS  : {len(left_eps)}")
    print(f"RIGHT EPS : {len(right_eps)}")
    print()

    issues = []
    left_only = sorted(set(left_eps) - set(right_eps))
    right_only = sorted(set(right_eps) - set(left_eps))
    if left_only:
        issues.append(f"left_only episodes: {left_only}")
    if right_only:
        issues.append(f"right_only episodes: {right_only}")

    for episode_uid in sorted(set(left_eps) & set(right_eps)):
        le = left_eps[episode_uid]
        re = right_eps[episode_uid]
        for field in COMPARE_FIELDS:
            if str(le.get(field)) != str(re.get(field)):
                issues.append(f"{episode_uid} field {field}: left={le.get(field)!r} right={re.get(field)!r}")

    if issues:
        print("===== Differences =====")
        for issue in issues:
            print("DIFF", issue)
        print("STATUS    : DIFF")
        return 1

    print("STATUS    : OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
