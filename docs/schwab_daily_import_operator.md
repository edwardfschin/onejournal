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
