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

## Phase M6 Schwab final daily operator workflow

This is the current recommended Schwab daily workflow.

### Place raw files

Place Schwab raw JSON exports under data/raw/schwab, using these folders:

- data/raw/schwab/<snapshot-date>/orders_all/
- data/raw/schwab/<snapshot-date>/transactions/

The operator finds files by asof date using the filename suffix __YYYY-MM-DD.json.

If multiple snapshots contain the same asof date, the operator fails safely by default. Use --use-latest-snapshot only when you deliberately want the newest path by name.

### Dry run

Run this first:

    python scripts/journal/find_and_run_schwab_daily_import.py --asof YYYY-MM-DD

Expected success markers:

    MATCHED_ROWS      : same as ORDERS_ROWS and TXN_ROWS
    ONLY_ORDERS_ROWS  : 0
    ONLY_TXNS_ROWS    : 0
    DRY RUN RESULT    : all gates passed; DuckDB import skipped
    GENERATED_CSV_CLEANUP: True
    STATUS            : OK

### Real import

Run this only after dry run passes:

    python scripts/journal/find_and_run_schwab_daily_import.py --asof YYYY-MM-DD --import-db

Expected success markers:

    IMPORT RESULT: DuckDB import and DB dashboard payload checks completed.
    PAYLOAD_PATH : output/dashboard/validation/YYYY-MM-DD_dashboard_payload_from_db.json
    GENERATED_CSV_CLEANUP: True
    STATUS      : OK

### Idempotency check

Use this when validating a date, after changing import logic, or before trusting a new raw Schwab file type:

    python scripts/journal/check_schwab_daily_import_idempotency.py --asof YYYY-MM-DD --orders PATH_TO_ORDERS_JSON --transactions PATH_TO_TRANSACTIONS_JSON

Expected success marker:

    IDEMPOTENT : second import did not duplicate fills or episodes
    STATUS     : OK

### Current canonical import source

Transactions-normalized fills are the current DuckDB import source after strict reconciliation with orders-normalized fills.

Orders JSON remains the execution cross-check.

Transactions JSON provides fee and commission evidence.

### Do not commit

Do not commit generated files from:

- data/normalized/fills/*.csv
- data/raw/schwab/**/*.json
- data/journal/*.duckdb
- output/**

The ODFS guard should remain clean after every run.

### Safety

The Schwab journal workflow does not call Schwab REST APIs.

It does not place, cancel, replace, or modify orders.

DuckDB import requires explicit --import-db.

### Duplicate raw snapshots

If duplicate raw snapshots exist for the same asof date, the operator fails safely by default. To deliberately use the newest snapshot by path name, add --use-latest-snapshot.

### Duplicate wording

When --use-latest-snapshot is provided, duplicate snapshot output is labelled DUPLICATE rather than FAIL because the operator made an explicit choice.

### DB total labels

DB_TOTAL_IMPORT_RUNS means current DuckDB total import_runs after the run, not rows imported during this run.
DB_TOTAL_FILLS, DB_TOTAL_EPISODES, and DB_TOTAL_EPISODE_LEGS are also current DuckDB totals after the run.
