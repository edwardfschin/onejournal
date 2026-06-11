#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
from datetime import datetime
from pathlib import Path

import duckdb


DEMO_SOURCE_BROKER = "manual_csv"
DEMO_ACCOUNT_ID = "DEMO_ACCOUNT"
DEMO_RAW_PATH = "docs/examples/manual_csv/fills_template.csv"


def scalar(con: duckdb.DuckDBPyConnection, sql: str, params: list[object] | None = None) -> int:
    row = con.execute(sql, params or []).fetchone()
    return int(row[0] if row else 0)


def main() -> int:
    parser = argparse.ArgumentParser(description="Purge demo manual CSV data from OneJournal DuckDB.")
    parser.add_argument("--db", default="data/journal/onejournal.duckdb")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup-dir", default="data/journal/backups")
    args = parser.parse_args()

    db_path = Path(args.db)
    backup_dir = Path(args.backup_dir)

    print("===== Purge Demo Manual Data =====")
    print(f"DB        : {db_path}")
    print("MODE      : " + ("APPLY" if args.apply else "DRY-RUN"))
    print("AUTO TRADE: disabled")
    print("BROKER API: disabled")
    print("ORDER API : disabled")
    print("")

    if not db_path.exists():
        print("STATUS    : FAIL")
        print("REASON    : DB file missing")
        return 1

    con = duckdb.connect(str(db_path), read_only=not args.apply)
    try:
        demo_fill_count = scalar(
            con,
            "select count(*) from normalized_fills where source_broker = ? and source_account_id = ? and raw_path = ?",
            [DEMO_SOURCE_BROKER, DEMO_ACCOUNT_ID, DEMO_RAW_PATH],
        )
        demo_episode_count = scalar(
            con,
            "select count(*) from trade_episodes where source_broker = ? and source_account_id = ?",
            [DEMO_SOURCE_BROKER, DEMO_ACCOUNT_ID],
        )
        demo_leg_count = scalar(
            con,
            "select count(*) from trade_episode_legs where episode_uid in (select episode_uid from trade_episodes where source_broker = ? and source_account_id = ?)",
            [DEMO_SOURCE_BROKER, DEMO_ACCOUNT_ID],
        )
        demo_review_count = scalar(
            con,
            "select count(*) from manual_reviews where episode_uid in (select episode_uid from trade_episodes where source_broker = ? and source_account_id = ?)",
            [DEMO_SOURCE_BROKER, DEMO_ACCOUNT_ID],
        )
        demo_import_count = scalar(
            con,
            "select count(*) from import_runs where source_type = ? and source_path = ?",
            [DEMO_SOURCE_BROKER, DEMO_RAW_PATH],
        )

        print("===== Matched Demo Rows =====")
        print(f"DEMO_FILLS        : {demo_fill_count}")
        print(f"DEMO_EPISODES     : {demo_episode_count}")
        print(f"DEMO_EPISODE_LEGS : {demo_leg_count}")
        print(f"DEMO_REVIEWS      : {demo_review_count}")
        print(f"DEMO_IMPORT_RUNS  : {demo_import_count}")
        print("")

        if not args.apply:
            print("STATUS    : OK")
            print("ACTION    : dry-run only. Re-run with --apply to purge demo manual data.")
            return 0

        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = backup_dir / f"onejournal_before_purge_demo_manual_{stamp}.duckdb"
        con.close()
        shutil.copy2(db_path, backup_path)
        con = duckdb.connect(str(db_path), read_only=False)

        print(f"BACKUP    : {backup_path}")
        print("")

        con.execute("begin transaction")
        con.execute(
            "delete from manual_reviews where episode_uid in (select episode_uid from trade_episodes where source_broker = ? and source_account_id = ?)",
            [DEMO_SOURCE_BROKER, DEMO_ACCOUNT_ID],
        )
        con.execute(
            "delete from trade_episode_legs where episode_uid in (select episode_uid from trade_episodes where source_broker = ? and source_account_id = ?)",
            [DEMO_SOURCE_BROKER, DEMO_ACCOUNT_ID],
        )
        con.execute(
            "delete from trade_episodes where source_broker = ? and source_account_id = ?",
            [DEMO_SOURCE_BROKER, DEMO_ACCOUNT_ID],
        )
        con.execute(
            "delete from normalized_fills where source_broker = ? and source_account_id = ? and raw_path = ?",
            [DEMO_SOURCE_BROKER, DEMO_ACCOUNT_ID, DEMO_RAW_PATH],
        )
        con.execute(
            "delete from import_runs where source_type = ? and source_path = ?",
            [DEMO_SOURCE_BROKER, DEMO_RAW_PATH],
        )
        con.execute("commit")

        remaining_demo_fills = scalar(
            con,
            "select count(*) from normalized_fills where source_broker = ? and source_account_id = ? and raw_path = ?",
            [DEMO_SOURCE_BROKER, DEMO_ACCOUNT_ID, DEMO_RAW_PATH],
        )
        remaining_demo_episodes = scalar(
            con,
            "select count(*) from trade_episodes where source_broker = ? and source_account_id = ?",
            [DEMO_SOURCE_BROKER, DEMO_ACCOUNT_ID],
        )

        print("===== Remaining Demo Rows =====")
        print(f"REMAINING_DEMO_FILLS   : {remaining_demo_fills}")
        print(f"REMAINING_DEMO_EPISODES: {remaining_demo_episodes}")
        print("")

        if remaining_demo_fills or remaining_demo_episodes:
            print("STATUS    : FAIL")
            return 1

        print("STATUS    : OK")
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    raise SystemExit(main())
