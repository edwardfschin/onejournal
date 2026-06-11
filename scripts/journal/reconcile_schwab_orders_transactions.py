#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as fh:
        return [dict(r) for r in csv.DictReader(fh)]


def _money(value: str) -> str:
    try:
        return str(Decimal(str(value)).quantize(Decimal("0.0001")))
    except (InvalidOperation, ValueError):
        return str(value).strip()


def _qty(value: str) -> str:
    try:
        return str(Decimal(str(value)).quantize(Decimal("0.0001")))
    except (InvalidOperation, ValueError):
        return str(value).strip()


def _key(row: dict[str, str]) -> tuple[str, str, str, str, str, str]:
    return (
        row.get("asof", "").strip(),
        row.get("source_order_id", "").strip(),
        row.get("symbol", "").strip().upper(),
        row.get("side", "").strip().lower(),
        _qty(row.get("quantity", "")),
        _money(row.get("fill_price", "")),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Reconcile Schwab orders-normalized fills against transactions-normalized fills.")
    parser.add_argument("--asof", required=True, help="YYYY-MM-DD date being reconciled.")
    parser.add_argument("--orders", required=True, help="Orders normalized fills CSV.")
    parser.add_argument("--transactions", required=True, help="Transactions normalized fills CSV.")
    parser.add_argument("--strict", action="store_true", help="Fail if any unmatched rows exist.")
    args = parser.parse_args()

    orders_path = Path(args.orders)
    txns_path = Path(args.transactions)
    orders = _read_rows(orders_path)
    txns = _read_rows(txns_path)

    order_rows = [r for r in orders if r.get("asof") == args.asof]
    txn_rows = [r for r in txns if r.get("asof") == args.asof]

    order_counter = Counter(_key(r) for r in order_rows)
    txn_counter = Counter(_key(r) for r in txn_rows)

    matched = 0
    for key in set(order_counter) | set(txn_counter):
        matched += min(order_counter.get(key, 0), txn_counter.get(key, 0))

    only_orders = order_counter - txn_counter
    only_txns = txn_counter - order_counter

    print("===== Schwab Orders vs Transactions Reconciliation =====")
    print(f"ASOF         : {args.asof}")
    print(f"ORDERS CSV   : {orders_path}")
    print(f"TXNS CSV     : {txns_path}")
    print("MODE         : read-only")
    print("DUCKDB WRITE : disabled")
    print("BROKER API   : disabled")
    print("ORDER API    : disabled")
    print("")
    print("===== Counts =====")
    print(f"ORDERS_ROWS       : {len(order_rows)}")
    print(f"TXN_ROWS          : {len(txn_rows)}")
    print(f"MATCHED_ROWS      : {matched}")
    print(f"ONLY_ORDERS_ROWS  : {sum(only_orders.values())}")
    print(f"ONLY_TXNS_ROWS    : {sum(only_txns.values())}")

    if only_orders:
        print("")
        print("===== Only in orders normalized fills =====")
        for key, count in only_orders.most_common(20):
            print(f"{count} x {key}")

    if only_txns:
        print("")
        print("===== Only in transactions normalized fills =====")
        for key, count in only_txns.most_common(20):
            print(f"{count} x {key}")

    print("")
    print("===== Result =====")
    if args.strict and (only_orders or only_txns):
        print("STATUS       : failed reconciliation")
        return 1
    print("STATUS       : OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
