# OneJournal Operator Import Runbook

## Purpose

This runbook defines the safe ODFS-aligned import path for OneJournal.

It is designed for operator use before any broker-specific adapter is added.

## Core rule

CSV is allowed as import transport only.

DuckDB is the journal source of truth.

Dashboard JSON is generated output.

Streamlit is the review UI.

## Safe import sequence

1. Put the original raw source file under data/raw/.
2. Prepare or generate a canonical normalized fills CSV.
3. Validate the normalized fills CSV.
4. Import validated fills into DuckDB.
5. Check DuckDB journal integrity.
6. Check import run audit integrity.
7. Build the DB dashboard payload.
8. Check the DB dashboard contract.
9. Launch Streamlit using the DB payload.

## Example using the current manual normalized CSV

Validate normalized fills:

python scripts/journal/check_normalized_fills_contract.py --asof 2026-06-02 --file docs/examples/manual_csv/fills_template.csv

Import into DuckDB:

python scripts/journal/import_journal_to_db.py --asof 2026-06-02 --file docs/examples/manual_csv/fills_template.csv --reviews data/journal/reviews/manual_reviews.csv --db data/journal/onejournal.duckdb --replace

Check journal DB:

python scripts/journal/check_journal_db.py --db data/journal/onejournal.duckdb

Check import audit:

python scripts/journal/check_import_run_audit.py --db data/journal/onejournal.duckdb

Build DB dashboard payload:

python scripts/journal/build_dashboard_payload_from_db.py --asof 2026-06-02 --db data/journal/onejournal.duckdb --output output/dashboard/latest/dashboard_payload_from_db.json --write

Check dashboard DB contract:

python scripts/journal/check_db_dashboard_contract.py --asof 2026-06-02 --payload output/dashboard/latest/dashboard_payload_from_db.json

Check episode quality:

python scripts/journal/check_episode_quality_contract.py --payload output/dashboard/latest/dashboard_payload_from_db.json

Launch Streamlit:

streamlit run src/onejournal/apps/streamlit_app.py

## Do not do this

Do not edit raw broker exports in place.
Do not use raw broker CSV directly for dashboard payloads.
Do not use raw broker CSV directly for Streamlit review state.
Do not import raw broker CSV directly into trade_episodes.
Do not treat dashboard JSON as source of truth.
Do not treat manual_reviews.csv as live review source of truth.

## Safety

This runbook does not call broker APIs.

It does not place orders.
It does not cancel orders.
It does not modify orders.
It does not auto-trade.

## Broker adapter rule

When Schwab or IBKR adapters are added later, they must output the canonical normalized fills contract first.

Broker-specific adapters must not write directly to dashboard JSON, Streamlit review state, or trade_episodes.

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
