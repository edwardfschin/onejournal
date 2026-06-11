# OneJournal Schwab Adapter Readiness Audit

## Purpose

This audit defines the planned Schwab ingestion adapter shape before any Schwab adapter code is added.

It exists to avoid coding against assumptions and to keep OneJournal compatible with future execution and auto-trading work.

## Current decision

Do not build a Schwab adapter until at least one real Schwab export sample has been reviewed.

Do not copy the TradersGPS Schwab client directly into OneJournal.

Use the TradersGPS Schwab architecture as reference only.

## ODFS entry point

Original Schwab files belong under:

data/raw/schwab

Canonical normalized fills belong under:

data/normalized/fills

Schwab journal import must follow this path:

raw Schwab export to Schwab adapter to normalized fills CSV to normalized fills validator to DuckDB import to dashboard payload

## Planned package layout

Reserved package path:

src/onejournal/brokers/schwab

Planned future files:

- src/onejournal/brokers/schwab/__init__.py
- src/onejournal/brokers/schwab/csv_adapter.py
- src/onejournal/brokers/schwab/transactions_adapter.py
- src/onejournal/brokers/schwab/field_map.py
- src/onejournal/brokers/schwab/normalizer.py

## Planned operator script

Reserved script path:

scripts/journal/convert_schwab_export_to_normalized_fills.py

Expected future command shape:

python scripts/journal/convert_schwab_export_to_normalized_fills.py --asof YYYY-MM-DD --input data/raw/schwab/...csv --output data/normalized/fills/YYYY-MM-DD_schwab_normalized_fills.csv

## First adapter scope

The first Schwab adapter should be file-based.

It should read a raw Schwab export CSV and write a canonical OneJournal normalized fills CSV.

It should not write DuckDB directly.

It should not build dashboard JSON directly.

It should not call Streamlit.

It should not call Schwab REST APIs.

It should not call Schwab streaming.

It should not place, cancel, replace, or modify orders.

## Future REST scope

A later Schwab REST transactions adapter may be added after file-based import is working.

Future REST transaction import must still output the canonical normalized fills contract first.

Future REST transaction import must not write directly to trade_episodes or dashboard JSON.

## Future execution scope

Future Schwab order operations belong in the execution plane, not the journal adapter.

Future auto-trading must use order intents, a risk gate, approval or policy checks, broker execution, broker fill feedback, and normalized_fills journal import.

The journal adapter must remain read-only.

## Existing OneJournal components to reuse

Reuse the canonical normalized fills contract.

Reuse scripts/journal/check_normalized_fills_contract.py.

Reuse scripts/journal/import_journal_to_db.py.

Reuse scripts/journal/check_import_run_audit.py.

Reuse scripts/journal/build_dashboard_payload_from_db.py.

Reuse scripts/journal/check_db_dashboard_contract.py.

Reuse scripts/journal/check_episode_quality_contract.py.

## Adapter output requirements

The Schwab adapter output must include the canonical normalized fills fields, including:

- asof
- source_broker
- source_account_id
- source_fill_id
- source_order_id
- filled_at
- asset_class
- symbol
- side
- quantity
- fill_price
- commission
- fees
- currency
- option_symbol
- underlying_symbol
- option_type
- expiry
- strike
- multiplier
- open_close
- execution_venue
- liquidity_flag
- episode_group_id

## Unknowns requiring real Schwab sample

The following must not be guessed:

- exact Schwab CSV header names
- option symbol format
- quantity sign convention
- price sign convention
- commission and fee columns
- account identifier column
- order identifier column
- fill identifier column
- option open or close indicator
- assignment and expiry representation
- multi-leg spread representation

## Safety

This readiness audit adds no broker API write call.

This readiness audit adds no adapter execution.

This readiness audit adds no order placement.
This readiness audit adds no order cancellation.
This readiness audit adds no order replacement.
This readiness audit adds no order modification.
This readiness audit adds no auto-trade.

## Phase J1 conclusion

OneJournal is ready to design a Schwab CSV adapter once a real Schwab export sample is available.

The adapter must produce normalized fills first and must remain separate from future execution modules.
