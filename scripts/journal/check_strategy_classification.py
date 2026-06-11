#!/usr/bin/env python3
"""Validate OneJournal strategy classification labels from dashboard payload.

Read-only validation script.

This script does not call broker APIs, does not place orders, and does not auto-trade.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

DEFAULT_PAYLOAD = Path("output/dashboard/latest/dashboard_payload.json")

EXPECTED_LABELS = {
    "Sell Put",
    "Buy Call",
    "Put Credit Vertical",
    "Put Debit Vertical",
    "Call Credit Vertical",
    "Call Debit Vertical",
    "Stock Long",
    "Stock Short",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate OneJournal strategy classification labels.")
    parser.add_argument("--asof", required=True, help="Market date in YYYY-MM-DD format.")
    parser.add_argument("--payload", default=str(DEFAULT_PAYLOAD), help="Dashboard payload JSON path.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload_path = Path(args.payload)

    print("===== OneJournal strategy classifier check =====")
    print(f"ASOF      : {args.asof}")
    print(f"PAYLOAD   : {payload_path}")
    print("MODE      : read-only")
    print("AUTO TRADE: disabled")
    print()

    if not payload_path.exists():
        raise FileNotFoundError(f"Dashboard payload not found: {payload_path}")

    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    payload_asof = str(payload.get("metadata", {}).get("asof", ""))
    if payload_asof != args.asof:
        raise ValueError(f"Payload asof {payload_asof} does not match --asof {args.asof}")

    episodes = payload.get("recent_trade_episodes", [])
    labels = {str(e.get("strategy_label", "")) for e in episodes}
    missing = sorted(EXPECTED_LABELS - labels)

    print("===== Strategy labels found =====")
    for label in sorted(labels):
        print(f"FOUND     : {label}")
    print()

    if missing:
        print("===== Missing expected labels =====")
        for label in missing:
            print(f"MISSING   : {label}")
        print()
        print("STATUS    : FAIL")
        return 1

    print("===== Result =====")
    print(f"EPISODES  : {len(episodes)}")
    print(f"EXPECTED  : {len(EXPECTED_LABELS)}")
    print("STATUS    : OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

