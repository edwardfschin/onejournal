#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import duckdb


PROJECT_DIR = Path(__file__).resolve().parents[2]


def run(cmd: list[str]) -> None:
    print("")
    print("$ " + " ".join(cmd))
    subprocess.run(cmd, cwd=PROJECT_DIR, check=True)


def counts(db_path: Path) -> dict[str, int]:
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        out = {}
        for table in ["import_runs", "normalized_fills", "trade_episodes", "trade_episode_legs", "manual_reviews"]:
            out[table] = con.execute(f"select count(*) from {table}").fetchone()[0]
        out["duplicate_fill_uid"] = con.execute("select count(*) from (select source_fill_id from normalized_fills group by source_fill_id having count(*) > 1)").fetchone()[0]
        out["duplicate_episode_uid"] = con.execute("select count(*) from (select episode_uid from trade_episodes group by episode_uid having count(*) > 1)").fetchone()[0]
        out["duplicate_review_episode_uid"] = con.execute("select count(*) from (select episode_uid from manual_reviews group by episode_uid having count(*) > 1)").fetchone()[0]
        return out
    finally:
        con.close()


def print_counts(title: str, data: dict[str, int]) -> None:
    print("")
    print(f"===== {title} =====")
    for key in sorted(data):
        print(f"{key:28s}: {data[key]}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Check Schwab daily import idempotency on a temporary DB copy.")
    parser.add_argument("--asof", required=True)
    parser.add_argument("--orders", required=True)
    parser.add_argument("--transactions", required=True)
    parser.add_argument("--db", default="data/journal/onejournal.duckdb")
    args = parser.parse_args()

    source_db = PROJECT_DIR / args.db
    if not source_db.exists():
        raise SystemExit(f"FAIL: DB not found: {source_db}")

    print("===== Schwab Daily Import Idempotency Check =====")
    print(f"SOURCE_DB  : {source_db}")
    print(f"ASOF       : {args.asof}")
    print("MODE       : temporary DB copy")
    print("BROKER API : disabled")
    print("ORDER API  : disabled")

    with tempfile.TemporaryDirectory(prefix="onejournal_schwab_idempotency_") as td:
        tmp_db = Path(td) / "onejournal_idempotency.duckdb"
        shutil.copy2(source_db, tmp_db)

        before = counts(tmp_db)
        print_counts("Before", before)

        common = [sys.executable, "scripts/journal/run_schwab_daily_import.py", "--asof", args.asof, "--orders", args.orders, "--transactions", args.transactions, "--db", str(tmp_db), "--import-db"]
        run(common)
        after_first = counts(tmp_db)
        print_counts("After first import", after_first)

        run(common)
        after_second = counts(tmp_db)
        print_counts("After second import", after_second)

        failures: list[str] = []
        for key in ["duplicate_fill_uid", "duplicate_episode_uid", "duplicate_review_episode_uid"]:
            if after_second[key] != 0:
                failures.append(f"{key} expected 0 got {after_second[key]}")

        for key in ["normalized_fills", "trade_episodes", "trade_episode_legs"]:
            if after_second[key] != after_first[key]:
                failures.append(f"{key} changed on second import: first={after_first[key]} second={after_second[key]}")

        print("")
        print("===== Result =====")
        if failures:
            for f in failures:
                print(f"FAIL: {f}")
            return 1
        print("STATUS     : OK")
        print("IDEMPOTENT : second import did not duplicate fills or episodes")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
