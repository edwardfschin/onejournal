from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from pathlib import Path

import duckdb

PROJECT_DIR = Path(__file__).resolve().parents[2]

def run(cmd: list[str]) -> None:
    print("")
    print("$ " + " ".join(cmd))
    subprocess.run(cmd, cwd=PROJECT_DIR, check=True)

def _csv_row_count(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open(newline="", encoding="utf-8") as fh:
        return sum(1 for _ in csv.DictReader(fh))

def _db_counts(db_path: Path) -> dict[str, int]:
    if not db_path.exists():
        return {}
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        return {
            "import_runs": con.execute("select count(*) from import_runs").fetchone()[0],
            "normalized_fills": con.execute("select count(*) from normalized_fills").fetchone()[0],
            "trade_episodes": con.execute("select count(*) from trade_episodes").fetchone()[0],
            "trade_episode_legs": con.execute("select count(*) from trade_episode_legs").fetchone()[0],
        }
    finally:
        con.close()

def _print_operator_summary(*, asof: str, import_db: bool, orders_path: str, transactions_path: str, orders_rows: int, transactions_rows: int, db_path: Path, payload_out: Path, cleaned: bool) -> None:
    print("")
    print("===== Schwab Operator Summary =====")
    print(f"ASOF                 : {asof}")
    print(f"IMPORT_DB            : {import_db}")
    print(f"ORDERS_FILE          : {orders_path}")
    print(f"TRANSACTIONS_FILE    : {transactions_path}")
    print(f"ORDERS_ROWS          : {orders_rows}")
    print(f"TRANSACTIONS_ROWS    : {transactions_rows}")
    payload_text = str(payload_out) if import_db else "not built in dry-run"
    print(f"PAYLOAD_PATH         : {payload_text}")
    print(f"GENERATED_CSV_CLEANUP: {cleaned}")
    counts = _db_counts(db_path)
    if counts:
        print(f"DB_TOTAL_IMPORT_RUNS : {counts['import_runs']}")
        print(f"DB_TOTAL_FILLS       : {counts['normalized_fills']}")
        print(f"DB_TOTAL_EPISODES    : {counts['trade_episodes']}")
        print(f"DB_TOTAL_EPISODE_LEGS: {counts['trade_episode_legs']}")
    print("STATUS               : OK")

def _cleanup_generated(paths: list[Path], keep_files: bool) -> bool:
    cleaned = False
    if keep_files:
        return cleaned
    for generated in paths:
        if generated.exists():
            generated.unlink()
            cleaned = True
            print(f"REMOVED     : {generated}")
    return cleaned

def main() -> int:
    parser = argparse.ArgumentParser(description="Run guarded Schwab daily reconciliation and optional DuckDB import.")
    parser.add_argument("--asof", required=True)
    parser.add_argument("--orders", required=True)
    parser.add_argument("--transactions", required=True)
    parser.add_argument("--db", default="data/journal/onejournal.duckdb")
    parser.add_argument("--import-db", action="store_true")
    parser.add_argument("--keep-files", action="store_true")
    args = parser.parse_args()

    asof = args.asof
    db_path = Path(args.db)
    out_dir = PROJECT_DIR / "data" / "normalized" / "fills"
    out_dir.mkdir(parents=True, exist_ok=True)
    orders_out = out_dir / f"{asof}_schwab_orders_normalized_fills.csv"
    txns_out = out_dir / f"{asof}_schwab_transactions_normalized_fills.csv"
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

    try:
        run([sys.executable, "scripts/journal/convert_schwab_orders_json_to_normalized_fills.py", "--asof", asof, "--input", args.orders, "--output", str(orders_out)])
        run([sys.executable, "scripts/journal/convert_schwab_transactions_json_to_normalized_fills.py", "--asof", asof, "--input", args.transactions, "--output", str(txns_out)])
        orders_rows = _csv_row_count(orders_out)
        transactions_rows = _csv_row_count(txns_out)

        if orders_rows == 0 and transactions_rows == 0:
            print("")
            print("NO FILL RESULT: both Schwab orders and transactions produced 0 normalized fill rows.")
            print("NO FILL ACTION: DuckDB import skipped; this is a clean no-op trading day for OneJournal.")
            print("")
            print("===== Flow Result =====")
            print("STATUS      : OK")
            print("CANONICAL   : no normalized fills to import after orders/transactions conversion.")
            cleaned = _cleanup_generated([orders_out, txns_out], args.keep_files)
            _print_operator_summary(asof=asof, import_db=args.import_db, orders_path=args.orders, transactions_path=args.transactions, orders_rows=orders_rows, transactions_rows=transactions_rows, db_path=db_path, payload_out=payload_out, cleaned=cleaned)
            run([sys.executable, "scripts/journal/check_odfs_continuity.py"])
            return 0

        if transactions_rows > 0 and orders_rows == 0:
            print("")
            print("TRANSACTION-ONLY RESULT: Schwab transactions produced fill rows but orders produced 0 rows.")
            print("TRANSACTION-ONLY ACTION: strict orders-vs-transactions reconciliation skipped for historical window.")
            print("CANONICAL   : transactions-normalized fills are used as the import source.")
            run([sys.executable, "scripts/journal/check_normalized_fills_contract.py", "--asof", asof, "--file", str(txns_out)])
        elif transactions_rows == 0 and orders_rows > 0:
            print("")
            print("FAIL RESULT : Schwab orders produced fill rows but transactions produced 0 rows.")
            print("REASON      : transactions-normalized fills are the canonical import source.")
            raise SystemExit(1)
        elif transactions_rows > orders_rows:
            print("")
            print("TRANSACTION-SUPERSET RESULT: Schwab transactions has more fill rows than orders.")
            print("TRANSACTION-SUPERSET ACTION: reconciliation report runs non-strict; transactions remain canonical import source.")
            run([sys.executable, "scripts/journal/check_normalized_fills_contract.py", "--asof", asof, "--file", str(orders_out)])
            run([sys.executable, "scripts/journal/check_normalized_fills_contract.py", "--asof", asof, "--file", str(txns_out)])
            run([sys.executable, "scripts/journal/reconcile_schwab_orders_transactions.py", "--asof", asof, "--orders", str(orders_out), "--transactions", str(txns_out)])
        elif orders_rows > transactions_rows:
            print("")
            print("FAIL RESULT : Schwab orders has more fill rows than transactions.")
            print("REASON      : transactions-normalized fills are the canonical import source, so missing transaction rows are not safe to import.")
            raise SystemExit(1)
        else:
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
        cleaned = _cleanup_generated([orders_out, txns_out], args.keep_files)
        _print_operator_summary(asof=asof, import_db=args.import_db, orders_path=args.orders, transactions_path=args.transactions, orders_rows=orders_rows, transactions_rows=transactions_rows, db_path=db_path, payload_out=payload_out, cleaned=cleaned)
        run([sys.executable, "scripts/journal/check_odfs_continuity.py"])
        return 0
    finally:
        if not args.keep_files:
            _cleanup_generated([orders_out, txns_out], False)

if __name__ == "__main__":
    raise SystemExit(main())
