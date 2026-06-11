#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[2]


def run(cmd: list[str]) -> None:
    print("")
    print("$ " + " ".join(cmd))
    subprocess.run(cmd, cwd=PROJECT_DIR, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run guarded Schwab daily reconciliation and optional DuckDB import.")
    parser.add_argument("--asof", required=True, help="YYYY-MM-DD date to process.")
    parser.add_argument("--orders", required=True, help="Raw Schwab orders JSON path.")
    parser.add_argument("--transactions", required=True, help="Raw Schwab transactions JSON path.")
    parser.add_argument("--db", default="data/journal/onejournal.duckdb", help="DuckDB journal path.")
    parser.add_argument("--out-dir", default="data/normalized/fills", help="Output folder for generated normalized fills CSV files.")
    parser.add_argument("--import-db", action="store_true", help="Actually import transactions-normalized fills into DuckDB after all gates pass.")
    parser.add_argument("--keep-files", action="store_true", help="Keep generated normalized CSVs after the run.")
    args = parser.parse_args()

    asof = args.asof
    out_dir = Path(args.out_dir)
    orders_out = out_dir / f"{asof}_schwab_orders_normalized_fills.csv"
    txns_out = out_dir / f"{asof}_schwab_transactions_normalized_fills.csv"
    db_path = Path(args.db)
    payload_out = Path("output/dashboard/validation") / f"{asof}_dashboard_payload_from_db.json"

    print("===== Schwab Daily Guarded Import Flow =====")
    print(f"PROJECT_DIR : {PROJECT_DIR}")
    print(f"ASOF        : {asof}")
    print(f"ORDERS      : {args.orders}")
    print(f"TRANSACTIONS: {args.transactions}")
    print(f"DB          : {db_path}")
    print(f"IMPORT_DB   : {args.import_db}")
    print("MODE        : guarded")
    print("BROKER API  : disabled")
    print("ORDER API   : disabled")

    if not args.import_db:
        print("")
        print("IMPORT NOTE : dry-run only. Add --import-db to import into DuckDB after all gates pass.")

    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        run([sys.executable, "scripts/journal/convert_schwab_orders_json_to_normalized_fills.py", "--asof", asof, "--input", args.orders, "--output", str(orders_out)])
        run([sys.executable, "scripts/journal/convert_schwab_transactions_json_to_normalized_fills.py", "--asof", asof, "--input", args.transactions, "--output", str(txns_out)])
        run([sys.executable, "scripts/journal/check_normalized_fills_contract.py", "--asof", asof, "--file", str(orders_out)])
        run([sys.executable, "scripts/journal/check_normalized_fills_contract.py", "--asof", asof, "--file", str(txns_out)])
        run([sys.executable, "scripts/journal/reconcile_schwab_orders_transactions.py", "--asof", asof, "--orders", str(orders_out), "--transactions", str(txns_out), "--strict"])

        if args.import_db:
            run([sys.executable, "scripts/journal/import_journal_to_db.py", "--asof", asof, "--file", str(txns_out), "--db", str(db_path)])
            run([sys.executable, "scripts/journal/check_journal_db.py", "--db", str(db_path)])
            run([sys.executable, "scripts/journal/check_import_run_audit.py", "--db", str(db_path)])
            run([sys.executable, "scripts/journal/build_dashboard_payload_from_db.py", "--asof", asof, "--db", str(db_path), "--output", str(payload_out), "--write"])
            run([sys.executable, "scripts/journal/check_db_dashboard_contract.py", "--asof", asof, "--payload", str(payload_out)])
            print("")
            print("IMPORT RESULT: DuckDB import and DB dashboard payload checks completed.")
        else:
            print("")
            print("DRY RUN RESULT: all gates passed; DuckDB import skipped.")

        print("")
        print("===== Flow Result =====")
        print("STATUS      : OK")
        print("CANONICAL   : transactions-normalized fills are the current import source after strict reconciliation.")
    finally:
        if not args.keep_files:
            for p in [orders_out, txns_out]:
                try:
                    p.unlink()
                    print(f"REMOVED     : {p}")
                except FileNotFoundError:
                    pass

    run([sys.executable, "scripts/journal/check_odfs_continuity.py"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
