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

Activity and subtype hints that represent lifecycle-only events are excluded from fill conversion in this version:

- `ASSIGNMENT`
- `EXERCISE`
- `EXPIRATION`
- `CORPORATE_ACTION`
- `DIVIDEND`
- `INTEREST`
- `TRANSFER`

These skipped rows are counted as unsupported in adapter statistics.
Unsupported activity reasons are reported by key (for example `activityType:ASSIGNMENT`,
`subType:EXERCISE`) and unsupported security asset types are reported separately.

Non-trade and non-valid records are also tracked as unsupported record reasons
(for example `record_type:TRANSFER`, `record_status:INVALID`) so that each skip
is explicitly auditable.

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
