from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

VALID_STATUS = {"open", "closed"}

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check OneJournal episode quality contract.")
    parser.add_argument("--payload", default="output/dashboard/latest/dashboard_payload_from_db.json", help="Dashboard payload JSON path.")
    return parser.parse_args()

def failures_for_episode(row: dict[str, Any]) -> list[str]:
    failures = []
    episode_uid = str(row.get("episode_uid") or "")
    primary_symbol = str(row.get("primary_symbol") or "")
    strategy_label = str(row.get("strategy_label") or "")
    status = str(row.get("status") or "")
    leg_summary = str(row.get("leg_summary") or "")

    if not episode_uid:
        failures.append("missing episode_uid")
    if not primary_symbol:
        failures.append("missing primary_symbol")

    episode_key = episode_uid.rsplit(":", 1)[-1] if episode_uid else ""
    if primary_symbol == episode_key and "_" in primary_symbol:
        failures.append("primary_symbol appears to be episode_group_id")

    if not strategy_label:
        failures.append("missing strategy_label")
    if strategy_label == "Unknown":
        failures.append("strategy_label is Unknown")
    if status not in VALID_STATUS:
        failures.append(f"invalid status {status!r}")

    legs = row.get("legs") or []
    if not isinstance(legs, list):
        failures.append("legs is not a list")
        legs = []

    try:
        leg_count = int(row.get("leg_count"))
    except Exception:
        failures.append("invalid leg_count")
        leg_count = -1

    if leg_count != len(legs):
        failures.append(f"leg_count {leg_count} does not match legs {len(legs)}")
    if leg_count <= 0:
        failures.append("leg_count must be positive")
    if not leg_summary:
        failures.append("missing leg_summary")

    for field in ("gross_cashflow", "commission", "fees"):
        if row.get(field) is None:
            failures.append(f"missing {field}")

    return failures

def main() -> int:
    args = parse_args()
    payload_path = Path(args.payload)
    print("===== OneJournal episode quality contract =====")
    print(f"PAYLOAD   : {payload_path}")
    print("MODE      : read-only")
    print("AUTO TRADE: disabled")

    data = json.loads(payload_path.read_text(encoding="utf-8"))
    rows = data.get("recent_trade_episodes") or []

    print()
    print("===== Result =====")
    print(f"EPISODES  : {len(rows)}")

    if not rows:
        print("STATUS    : failed no recent_trade_episodes")
        return 1

    failures = []
    for row in rows:
        episode_uid = str(row.get("episode_uid") or "<missing episode_uid>")
        for failure in failures_for_episode(row):
            failures.append((episode_uid, failure))

    if failures:
        print("STATUS    : failed episode quality contract")
        for episode_uid, failure in failures:
            print(f"FAIL      : {episode_uid}: {failure}")
        return 1

    print("STATUS    : OK")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
