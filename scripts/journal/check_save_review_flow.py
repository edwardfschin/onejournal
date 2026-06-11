#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import logging
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import duckdb

LOG = logging.getLogger("onejournal.save_review_flow")
PROJECT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_DB = PROJECT_DIR / "data/journal/onejournal.duckdb"
DEFAULT_WORK_DIR = PROJECT_DIR / "output/validation/save_review_flow"

def fail(message: str) -> int:
    LOG.error("FAIL: %s", message)
    return 1

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate OneJournal Save Review flow using a temporary DB copy.")
    parser.add_argument("--asof", required=True, help="Market/review date in YYYY-MM-DD format.")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="Production DuckDB path to copy for validation.")
    parser.add_argument("--work-dir", default=str(DEFAULT_WORK_DIR), help="Validation output folder.")
    return parser.parse_args()

def run_cmd(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=str(cwd), text=True, capture_output=True)

def first_episode_uid(db_path: Path) -> str:
    with duckdb.connect(str(db_path)) as con:
        row = con.execute("SELECT episode_uid FROM trade_episodes ORDER BY episode_uid LIMIT 1").fetchone()
    if not row or not row[0]:
        raise SystemExit("No trade_episodes row available for Save Review flow validation")
    return str(row[0])

def read_review(db_path: Path, episode_uid: str) -> tuple[str, str, str, str] | None:
    with duckdb.connect(str(db_path)) as con:
        row = con.execute(
            "SELECT review_status, setup_quality, entry_reason, notes FROM manual_reviews WHERE episode_uid = ?",
            [episode_uid],
        ).fetchone()
    if not row:
        return None
    return tuple(str(x or "") for x in row)

def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = parse_args()
    db_path = Path(args.db)
    if not db_path.is_absolute():
        db_path = PROJECT_DIR / db_path
    work_dir = Path(args.work_dir)
    if not work_dir.is_absolute():
        work_dir = PROJECT_DIR / work_dir
    work_dir.mkdir(parents=True, exist_ok=True)
    if not db_path.exists():
        return fail(f"DB not found: {db_path}")
    temp_db = work_dir / "onejournal_save_review_flow.duckdb"
    temp_payload = work_dir / "dashboard_payload_from_db_save_review_flow.json"
    if temp_db.exists():
        temp_db.unlink()
    shutil.copy2(db_path, temp_db)
    episode_uid = first_episode_uid(temp_db)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    expected_status = "reviewed"
    expected_quality = "good"
    expected_reason = f"phase_d_validation_{stamp}"
    expected_notes = "OneJournal Phase D validation on temporary DB copy. No broker action. No production DB write."
    LOG.info("===== OneJournal Save Review Flow Check =====")
    LOG.info("PROJECT_DIR : %s", PROJECT_DIR)
    LOG.info("SOURCE_DB   : %s", db_path)
    LOG.info("TEMP_DB     : %s", temp_db)
    LOG.info("TEMP_PAYLOAD: %s", temp_payload)
    LOG.info("ASOF        : %s", args.asof)
    LOG.info("EPISODE_UID : %s", episode_uid)
    upsert_cmd = [
        sys.executable,
        str(PROJECT_DIR / "scripts/journal/upsert_manual_review_to_db.py"),
        "--db", str(temp_db),
        "--episode-uid", episode_uid,
        "--review-status", expected_status,
        "--setup-quality", expected_quality,
        "--entry-reason", expected_reason,
        "--notes", expected_notes,
    ]
    upsert = run_cmd(upsert_cmd, PROJECT_DIR)
    if upsert.returncode != 0:
        LOG.error(upsert.stdout)
        LOG.error(upsert.stderr)
        return fail("upsert_manual_review_to_db.py failed on temp DB")
    saved = read_review(temp_db, episode_uid)
    expected = (expected_status, expected_quality, expected_reason, expected_notes)
    if saved != expected:
        return fail(f"manual_reviews row mismatch: expected={expected!r} got={saved!r}")
    build_cmd = [
        sys.executable,
        str(PROJECT_DIR / "scripts/journal/build_dashboard_payload_from_db.py"),
        "--asof", args.asof,
        "--db", str(temp_db),
        "--output", str(temp_payload),
        "--write",
    ]
    build = run_cmd(build_cmd, PROJECT_DIR)
    if build.returncode != 0:
        LOG.error(build.stdout)
        LOG.error(build.stderr)
        return fail("build_dashboard_payload_from_db.py failed on temp DB")
    if not temp_payload.exists():
        return fail(f"temp payload not written: {temp_payload}")
    payload = json.loads(temp_payload.read_text(encoding="utf-8"))
    entries = payload.get("recent_trade_episodes")
    if not isinstance(entries, list):
        return fail("payload missing recent_trade_episodes list")
    match = None
    for row in entries:
        if isinstance(row, dict) and str(row.get("episode_uid")) == episode_uid:
            match = row
            break
    if not match:
        return fail(f"reviewed episode missing from rebuilt payload: {episode_uid}")
    for key, expected_value in [
        ("review_status", expected_status),
        ("setup_quality", expected_quality),
        ("entry_reason", expected_reason),
        ("notes", expected_notes),
    ]:
        got = str(match.get(key, ""))
        if got != expected_value:
            return fail(f"payload field mismatch for {key}: expected={expected_value!r} got={got!r}")
    LOG.info("PASS: Save Review flow is valid on temporary DB copy")
    LOG.info("SCOPE: temp DB only; production DB untouched")
    LOG.info("BROKER ACTION: none")
    LOG.info("ORDER ACTION : none")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
