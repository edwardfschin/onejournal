# OneJournal Schwab Orders vs Transactions Reconciliation

## Purpose

This read-only check compares Schwab orders-normalized fills against Schwab transactions-normalized fills for the same asof date.

Orders JSON is the execution truth.

Transactions JSON is the accounting and fee truth.

The reconciliation check confirms whether the two normalized outputs agree on orderId, symbol, side, quantity, price, and asof.

## Command

python scripts/journal/reconcile_schwab_orders_transactions.py --asof 2025-05-19 --orders data/normalized/fills/2025-05-19_schwab_orders_all_normalized_fills.csv --transactions data/normalized/fills/2025-05-19_schwab_transactions_normalized_fills.csv

Use --strict when you want unmatched rows to fail the command.

## ODFS rule

Input CSV files are generated operational files under data/normalized/fills.

They must not be committed.

Run reconciliation, inspect the output, then remove generated CSV files unless they are needed for the next operator step.

## Safety

This checker is read-only.

It does not write DuckDB.

It does not call broker APIs.

It does not place, cancel, replace, or modify orders.
