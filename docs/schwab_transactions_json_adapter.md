# OneJournal Schwab Transactions JSON Adapter

## Purpose

This adapter converts Schwab transactions JSON into canonical normalized fills CSV.

It is read-only and focused on accounting evidence such as commissions, fees, net cash, and transferItems.

## Command

python scripts/journal/convert_schwab_transactions_json_to_normalized_fills.py --asof 2025-05-19 --input data/raw/schwab/YYYY-MM-DD/transactions/file.json --output data/normalized/fills/2025-05-19_schwab_transactions_normalized_fills.csv

Then validate:

python scripts/journal/check_normalized_fills_contract.py --asof 2025-05-19 --file data/normalized/fills/2025-05-19_schwab_transactions_normalized_fills.csv

## Extraction rule

Only TRADE and VALID transaction records are eligible for normalized fill
conversion.

Activity and subtype hints that represent lifecycle-only events are excluded from fill conversion in this version:

- `ASSIGNMENT`
- `EXERCISE`
- `OPTION_EXERCISE` (normalized as `EXERCISE`)
- `EXPIRATION`
- `ROLL`
- `ROLLOVER`
- `CORPORATE_ACTION`
- `DIVIDEND`
- `INTEREST`
- `TRANSFER`

These skipped rows are counted as unsupported in adapter statistics.

Observed Schwab history does not always populate structured `activityType` or
`subType` fields. Exact `assignment`, `exercise`, or `expiration` description
hints are therefore captured only as explicitly unconfirmed lifecycle review
evidence. Assignment/exercise hints are accepted only on `TRADE` records;
expiration hints are accepted only on `RECEIVE_AND_DELIVER` records. They are
labelled `description_hint:<EVENT>`, every child leg is `review_required`, and
they never produce normalized fills or financial results. This is the
ADR-0005 review-suggestion path, not canonical interpretation of broker text.

In addition to unsupported counters, the converter emits lifecycle-event
headers and may emit their transfer-item evidence legs:

- `LIFECYCLE_EVENTS` prints how many lifecycle-only rows were extracted from
  recognized `VALID` transactions in the same as-of slice.
- Each event row includes:
  `event_uid`, `source_broker`, `source_account_id`, `source_activity_id`,
  `source_order_id`, `source_position_id`, `event_class`, `event_type`,
  `asof`, `event_at`, and `event_name`.

ADR-0005 is accepted and event rows are now persisted to the normalized lifecycle
event ledger via the Schwab daily import pipeline when `--lifecycle-events` is
forwarded to `import_journal_to_db.py`.

Optionally add `--lifecycle-events <path>` to write these rows as a CSV file for
event-ledger ingestion. Add `--lifecycle-event-legs <path>` with it to write a
separate child CSV containing the observed transfer-item evidence:

- deterministic `event_leg_uid`, parent `event_uid`, and source item index
- security, cash, or unsupported leg classification
- symbol and option contract fields
- signed quantity, observed price, observed cash amount, and position effect
- fee type, source currency, and option deliverables when supplied
- `observed` or `review_required` structural evidence status and notes

Lifecycle leg extraction does not default a missing option multiplier, derive a
missing price, calculate P&L, or decide predecessor/successor lot allocations.
The evidence is persisted in `normalized_lifecycle_event_legs` only when both
event files are supplied to the importer. A leg referencing an event absent
from the supplied header file is rejected.
Any captured lifecycle event remains a publication/reconciliation blocker for
financial totals until an approved event-specific allocation rule consumes it.
A guarded lifecycle-only day is not treated as an empty trading-day no-op: its
event headers and legs may be imported even when both normalized fill files are
empty, and the import audit count includes both evidence families.
Unsupported activity reasons are reported by key (for example `activityType:ASSIGNMENT`,
`subType:EXERCISE`) and unsupported security asset types are reported separately.

Non-trade and non-valid records are also tracked as unsupported record reasons
(for example `record_type:TRANSFER`, `record_status:INVALID`) so that each skip
is explicitly auditable.

Additional skip diagnostics include structural reasons such as empty transfer items
(`record_items:empty`), non-list payloads
(`record_items:non_list`), malformed transfer items
(`record_items:non_object`), or missing instruments
(`record_items:missing_instrument`/`record_security:unsupported_or_missing`).

CURRENCY transferItems are fee and commission evidence.

Security transferItems are fill-leg candidates.

Fees are allocated evenly across security legs for the first adapter version.

Do not aggregate multi-leg transactions inside the adapter.

## ODFS rule

Raw Schwab transactions JSON stays under data/raw/schwab.

Generated normalized fills CSV stays under data/normalized/fills and must not be committed.

## Safety

This adapter does not write DuckDB. The separate journal importer owns durable
storage after schema migration and validation.

This adapter does not call Schwab REST APIs.

This adapter does not place, cancel, replace, or modify orders.
