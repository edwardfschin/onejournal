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
    parser = argparse.ArgumentParser(description="Run safe daily Schwab orders/transactions reconciliation flow.")
    parser.add_argument("--asof", required=True, help="YYYY-MM-DD date to process.")
    parser.add_argument("--orders", required=True, help="Raw Schwab orders JSON path.")
    parser.add_argument("--transactions", required=True, help="Raw Schwab transactions JSON path.")
    parser.add_argument("--out-dir", default="data/normalized/fills", help="Output folder for generated normalized fills CSV files.")
    parser.add_argument("--strict", action="store_true", help="Fail if reconciliation has unmatched rows.")
    parser.add_argument("--keep-files", action="store_true", help="Keep generated normalized CSVs after the run. Default removes them to protect ODFS cleanliness.")
    args = parser.parse_args()

    asof = args.asof
    out_dir = Path(args.out_dir)
    orders_out = out_dir / f"{asof}_schwab_orders_normalized_fills.csv"
    txns_out = out_dir / f"{asof}_schwab_transactions_normalized_fills.csv"

    print("===== Schwab Daily Safe Reconciliation Flow =====")
    print(f"PROJECT_DIR : {PROJECT_DIR}")
    print(f"ASOF        : {asof}")
    print(f"ORDERS      : {args.orders}")
    print(f"TRANSACTIONS: {args.transactions}")
    print(f"ORDERS_OUT  : {orders_out}")
    print(f"TXNS_OUT    : {txns_out}")
    print("MODE        : read-only")
    print("DUCKDB WRITE: disabled")
    print("BROKER API  : disabled")
    print("ORDER API   : disabled")

    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        run([sys.executable, "scripts/journal/convert_schwab_orders_json_to_normalized_fills.py", "--asof", asof, "--input", args.orders, "--output", str(orders_out)])
        run([sys.executable, "scripts/journal/convert_schwab_transactions_json_to_normalized_fills.py", "--asof", asof, "--input", args.transactions, "--output", str(txns_out)])
        run([sys.executable, "scripts/journal/check_normalized_fills_contract.py", "--asof", asof, "--file", str(orders_out)])
        run([sys.executable, "scripts/journal/check_normalized_fills_contract.py", "--asof", asof, "--file", str(txns_out)])
        reconcile_cmd = [sys.executable, "scripts/journal/reconcile_schwab_orders_transactions.py", "--asof", asof, "--orders", str(orders_out), "--transactions", str(txns_out)]
        if args.strict:
            reconcile_cmd.append("--strict")
        run(reconcile_cmd)
        print("")
        print("===== Flow Result =====")
        print("STATUS      : OK")
        print("IMPORT NOTE : No DuckDB import was run.")
        print("ODFS NOTE   : Generated normalized CSVs are ignored runtime artifacts.")
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
