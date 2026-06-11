# OneJournal Schwab Transactions JSON Adapter

## Purpose

This adapter converts Schwab transactions JSON into canonical normalized fills CSV.

It is read-only and focused on accounting evidence such as commissions, fees, net cash, and transferItems.

## Command

python scripts/journal/convert_schwab_transactions_json_to_normalized_fills.py --asof 2025-05-19 --input data/raw/schwab/YYYY-MM-DD/transactions/file.json --output data/normalized/fills/2025-05-19_schwab_transactions_normalized_fills.csv

Then validate:

python scripts/journal/check_normalized_fills_contract.py --asof 2025-05-19 --file data/normalized/fills/2025-05-19_schwab_transactions_normalized_fills.csv

## Extraction rule

Only TRADE and VALID transaction records are converted.

CURRENCY transferItems are fee and commission evidence.

Security transferItems are fill-leg candidates.

Fees are allocated evenly across security legs for the first adapter version.

Do not aggregate multi-leg transactions inside the adapter.

## ODFS rule

Raw Schwab transactions JSON stays under data/raw/schwab.

Generated normalized fills CSV stays under data/normalized/fills and must not be committed.

## Safety

This adapter does not write DuckDB.

This adapter does not call Schwab REST APIs.

This adapter does not place, cancel, replace, or modify orders.
