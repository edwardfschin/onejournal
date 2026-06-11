#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

import duckdb


def one(con: duckdb.DuckDBPyConnection, sql: str, default=None):
    try:
        row = con.execute(sql).fetchone()
        if not row:
            return default
        return row[0]
    except Exception:
        return default


def main() -> int:
    parser = argparse.ArgumentParser(description="Show read-only OneJournal import status.")
    parser.add_argument("--db", default="data/journal/onejournal.duckdb")
    parser.add_argument("--payload-dir", default="output/dashboard/validation")
    args = parser.parse_args()

    db_path = Path(args.db)
    payload_dir = Path(args.payload_dir)

    print("===== OneJournal Import Status =====")
    print(f"DB        : {db_path}")
    print(f"MODE      : read-only")
    print(f"AUTO TRADE: disabled")
    print("")

    if not db_path.exists():
        print("STATUS    : FAIL")
        print("REASON    : DB file missing")
        return 1

    con = duckdb.connect(str(db_path), read_only=True)
    try:
        import_runs = one(con, "select count(*) from import_runs", 0)
        normalized_fills = one(con, "select count(*) from normalized_fills", 0)
        trade_episodes = one(con, "select count(*) from trade_episodes", 0)
        trade_episode_legs = one(con, "select count(*) from trade_episode_legs", 0)
        manual_reviews = one(con, "select count(*) from manual_reviews", 0)

        duplicate_fill_uid = one(con, "select count(*) from (select fill_uid from normalized_fills group by fill_uid having count(*) > 1)", 0)
        duplicate_episode_uid = one(con, "select count(*) from (select episode_uid from trade_episodes group by episode_uid having count(*) > 1)", 0)
        duplicate_review_episode_uid = one(con, "select count(*) from (select episode_uid from manual_reviews group by episode_uid having count(*) > 1)", 0)

        latest_asof = one(con, "select max(asof) from normalized_fills", "none")
        latest_import_started = one(con, "select max(started_at) from import_runs", "none")
        latest_import_status = one(con, "select status from import_runs order by started_at desc limit 1", "none")
        latest_import_source = one(con, "select source_file from import_runs order by started_at desc limit 1", "none")

        print("===== DB Totals =====")
        print(f"IMPORT_RUNS             : {import_runs}")
        print(f"NORMALIZED_FILLS        : {normalized_fills}")
        print(f"TRADE_EPISODES          : {trade_episodes}")
        print(f"TRADE_EPISODE_LEGS      : {trade_episode_legs}")
        print(f"MANUAL_REVIEWS          : {manual_reviews}")
        print("")

        print("===== Latest Import =====")
        print(f"LATEST_FILL_ASOF        : {latest_asof}")
        print(f"LATEST_IMPORT_STARTED   : {latest_import_started}")
        print(f"LATEST_IMPORT_STATUS    : {latest_import_status}")
        print(f"LATEST_IMPORT_SOURCE    : {latest_import_source}")
        print("")

        payloads = sorted(payload_dir.glob("*_dashboard_payload_from_db.json")) if payload_dir.exists() else []
        latest_payload = payloads[-1] if payloads else None

        print("===== Dashboard Payload =====")
        print(f"PAYLOAD_DIR             : {payload_dir}")
        print(f"LATEST_PAYLOAD          : {latest_payload if latest_payload else none}")
        print("")

        print("===== Duplicate Guards =====")
        print(f"DUPLICATE_FILL_UIDS     : {duplicate_fill_uid}")
        print(f"DUPLICATE_EPISODE_UIDS  : {duplicate_episode_uid}")
        print(f"DUPLICATE_REVIEW_UIDS   : {duplicate_review_episode_uid}")
        print("")

        bad = [
            duplicate_fill_uid,
            duplicate_episode_uid,
            duplicate_review_episode_uid,
        ]
        if any(x for x in bad):
            print("STATUS                  : FAIL")
            return 1

        print("STATUS                  : OK")
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    raise SystemExit(main())
