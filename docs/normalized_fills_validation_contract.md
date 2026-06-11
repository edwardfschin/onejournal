# OneJournal Normalized Fills Validation Contract

## Purpose

This contract defines the validation gate for a canonical OneJournal normalized fills CSV file.

The checker validates transport files before they are imported into DuckDB.

## Command

python scripts/journal/check_normalized_fills_contract.py --asof 2026-06-02 --file docs/examples/manual_csv/fills_template.csv

## What it validates

- required columns through the existing manual CSV parser
- asof consistency
- unique fill_uid after parser normalization
- valid asset_class
- valid side
- required option fields when asset_class is option
- required stock fields when asset_class is stock

## ODFS rule

Normalized fills CSV is transport.

DuckDB normalized_fills is imported fills truth.

DuckDB import_runs is audit truth.

Dashboard JSON is generated output.

## Safety

This check is read-only.

No broker API call.
No order placement.
No order cancellation.
No order modification.
No auto-trade.
