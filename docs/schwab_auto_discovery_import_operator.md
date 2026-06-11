# OneJournal Schwab Auto-Discovery Daily Import Operator

## Purpose

This operator shortcut finds the raw Schwab orders and transactions JSON files for a given asof date and runs the guarded Schwab daily import operator.

## Command: dry run

python scripts/journal/find_and_run_schwab_daily_import.py --asof 2025-05-19

## Command: import

python scripts/journal/find_and_run_schwab_daily_import.py --asof 2025-05-19 --import-db

## File discovery

The operator searches under data/raw/schwab.

It finds orders files using:

data/raw/schwab/**/orders_all/*__YYYY-MM-DD.json

It finds transactions files using:

data/raw/schwab/**/transactions/*__YYYY-MM-DD.json

## Safety

This shortcut does not call Schwab REST APIs.

This shortcut does not place, cancel, replace, or modify orders.

DuckDB import still requires explicit --import-db.

The underlying guarded import still validates normalized fills, strictly reconciles orders and transactions, checks DB integrity, builds a dated validation dashboard payload, and runs the ODFS guard.
