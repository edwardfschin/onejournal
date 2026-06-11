# OneJournal Schwab Orders JSON Adapter

## Purpose

This adapter converts Schwab orders JSON into canonical OneJournal normalized fills CSV.

It is read-only.

It does not call Schwab REST APIs.

It does not place, cancel, replace, or modify orders.

## Command

python scripts/journal/convert_schwab_orders_json_to_normalized_fills.py --asof 2025-07-18 --input docs/examples/schwab_orders_json/orders_sample.json --output output/validation/schwab_orders_json/2025-07-18_schwab_orders_normalized_fills.csv

Then validate:

python scripts/journal/check_normalized_fills_contract.py --asof 2025-07-18 --file output/validation/schwab_orders_json/2025-07-18_schwab_orders_normalized_fills.csv

## Extraction rule

The adapter flattens OCO childOrderStrategies, extracts only executionType FILL records, matches executionLeg legId to orderLegCollection legId, and emits one normalized fill row per executed leg.

## Fee limitation

Schwab orders JSON does not reliably include commission and fee transferItems.

The adapter writes commission and fees as zero for this source.

Fee enrichment should come later from Schwab transactions transferItems JSON.

## Output rule

The adapter writes canonical normalized fills CSV only.

DuckDB import remains a separate operator step.

## Daily validation rule

The normalized fills validator is daily and requires --asof.

When converting a date-range Schwab orders JSON file, use --asof and write one daily normalized fills CSV at a time.

Date-range output may be useful for inspection, but it should not be used as the validated import artifact.

