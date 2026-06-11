# OneJournal Schwab Daily Import Operator

## Purpose

This operator command runs the guarded daily Schwab flow and can import into DuckDB only when explicitly requested.

## Command: dry run

python scripts/journal/run_schwab_daily_import.py --asof 2025-05-19 --orders data/raw/schwab/YYYY-MM-DD/orders_all/file.json --transactions data/raw/schwab/YYYY-MM-DD/transactions/file.json

## Command: import

python scripts/journal/run_schwab_daily_import.py --asof 2025-05-19 --orders data/raw/schwab/YYYY-MM-DD/orders_all/file.json --transactions data/raw/schwab/YYYY-MM-DD/transactions/file.json --import-db

## Gates before import

1. Convert Schwab orders JSON to daily normalized fills.
2. Convert Schwab transactions JSON to daily normalized fills.
3. Validate orders-normalized fills.
4. Validate transactions-normalized fills.
5. Strictly reconcile orders and transactions normalized fills.
6. Import transactions-normalized fills into DuckDB only when --import-db is present.
7. Check journal DB.
8. Check import run audit.
9. Build DB dashboard payload.
10. Check DB dashboard contract.
11. Run ODFS continuity guard.

## Current canonical import source

Transactions-normalized fills are the current DuckDB import source after strict reconciliation.

Reason: transactions JSON includes fee and commission evidence, while orders JSON remains the execution cross-check.

## Safety

This command does not call Schwab REST APIs.

This command does not place, cancel, replace, or modify orders.

This command does not import into DuckDB unless --import-db is provided.

Generated normalized fills CSV files are removed by default unless --keep-files is provided.
