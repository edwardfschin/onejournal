# OneJournal Schwab Daily Reconciliation Operator

## Purpose

This operator command runs the safe daily Schwab reconciliation flow.

It converts orders JSON and transactions JSON into daily normalized fills CSV files, validates both outputs, reconciles execution truth against accounting truth, and then removes generated CSV files by default.

## Command

python scripts/journal/run_schwab_daily_reconciliation.py --asof 2025-05-19 --orders data/raw/schwab/YYYY-MM-DD/orders_all/file.json --transactions data/raw/schwab/YYYY-MM-DD/transactions/file.json --strict

## What it does

1. Converts Schwab orders JSON to daily normalized fills.
2. Converts Schwab transactions JSON to daily normalized fills.
3. Runs normalized fills contract check on both files.
4. Runs Schwab orders-vs-transactions reconciliation.
5. Removes generated normalized CSVs unless --keep-files is provided.
6. Runs ODFS continuity guard.

## Safety

This command does not write DuckDB.

This command does not import into the journal database.

This command does not call broker APIs.

This command does not place, cancel, replace, or modify orders.

## ODFS rule

Generated normalized fills CSV files are operational artifacts.

They are ignored by git and should not be committed.

Use --keep-files only when the next explicit operator step needs the generated files.
