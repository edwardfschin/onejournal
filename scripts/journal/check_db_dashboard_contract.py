#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import logging
import re
from pathlib import Path
from typing import Any

LOG = logging.getLogger("onejournal.db_dashboard_contract")
PROJECT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_PAYLOAD = PROJECT_DIR / "output/dashboard/latest/dashboard_payload_from_db.json"
REQUIRED_METADATA_KEYS = {"asof", "source"}
REQUIRED_ENTRY_KEYS = {"episode_uid"}
REQUIRED_REVIEW_KEYS = {"review_status", "setup_quality", "entry_reason", "notes"}
ENTRY_LIST_KEYS = ("recent_trade_episodes", "journal_review_queue", "closed_trade_episodes")

def fail(message: str) -> int:
    LOG.error("FAIL: %s", message)
    return 1

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate OneJournal DB dashboard payload contract.")
    parser.add_argument("--asof", required=True, help="Market/review date in YYYY-MM-DD format.")
    parser.add_argument("--payload", default=str(DEFAULT_PAYLOAD), help="Path to dashboard_payload_from_db.json.")
    return parser.parse_args()

def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)

def find_entry_list(payload: dict[str, Any]) -> tuple[str, list[dict[str, Any]]] | tuple[str, None]:
    for key in ENTRY_LIST_KEYS:
        value = payload.get(key)
        if isinstance(value, list):
            return key, value
    return "", None

def validate_payload(payload: Any, asof: str, payload_path: Path) -> int:
    if not isinstance(payload, dict):
        return fail("payload root must be a JSON object")
    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        return fail("payload metadata must be an object")
    missing_meta = sorted(REQUIRED_METADATA_KEYS - set(metadata))
    if missing_meta:
        return fail(f"metadata missing keys: {missing_meta}")
    payload_asof = str(metadata.get("asof", ""))
    if payload_asof != asof:
        return fail(f"metadata.asof mismatch: expected {asof}, got {payload_asof}")
    source = str(metadata.get("source", "")).lower()
    if "db" not in source and "duckdb" not in source:
        return fail("metadata.source must identify DB or DuckDB source, got " + repr(metadata.get("source")))
    entry_key, entries = find_entry_list(payload)
    if entries is None:
        return fail(f"payload must contain one dashboard entry list key: {ENTRY_LIST_KEYS}")
    if not entries:
        return fail(f"payload entry list is empty: {entry_key}")
    seen = set()
    duplicates = set()
    for row in entries:
        if not isinstance(row, dict):
            return fail(f"payload {entry_key} must contain objects only")
        episode_uid = str(row.get("episode_uid", "<missing>"))
        missing_entry = sorted(REQUIRED_ENTRY_KEYS - set(row))
        if missing_entry:
            return fail(f"entry missing required keys: {episode_uid} {missing_entry}")
        missing_review = sorted(REQUIRED_REVIEW_KEYS - set(row))
        if missing_review:
            return fail(f"entry missing review keys: {episode_uid} {missing_review}")
        if episode_uid in seen:
            duplicates.add(episode_uid)
        seen.add(episode_uid)
    if duplicates:
        return fail(f"duplicate episode_uid values found: {sorted(duplicates)[:5]}")
    LOG.info("PASS: DB dashboard payload contract is valid")
    LOG.info("PAYLOAD: %s", payload_path)
    LOG.info("ASOF: %s", asof)
    LOG.info("SOURCE: %s", metadata.get("source"))
    LOG.info("ENTRY_KEY: %s", entry_key)
    LOG.info("ENTRIES: %s", len(entries))
    return 0

def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = parse_args()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", args.asof):
        return fail("--asof must be YYYY-MM-DD")
    payload_path = Path(args.payload)
    if not payload_path.is_absolute():
        payload_path = PROJECT_DIR / payload_path
    LOG.info("===== OneJournal DB Dashboard Contract Check =====")
    LOG.info("PROJECT_DIR: %s", PROJECT_DIR)
    LOG.info("PAYLOAD    : %s", payload_path)
    LOG.info("ASOF       : %s", args.asof)
    if not payload_path.exists():
        return fail(f"payload not found: {payload_path}")
    try:
        payload = load_json(payload_path)
    except Exception as exc:
        return fail(f"cannot read JSON payload: {exc}")
    return validate_payload(payload, args.asof, payload_path)

if __name__ == "__main__":
    raise SystemExit(main())
