# OneJournal Schwab Execution Boundary Contract

## Purpose

This contract defines how OneJournal will support Schwab ingestion now while staying ready for future auto-trading.

The current OneJournal journal path remains read-only.

Future broker write operations must live in a separate execution plane.

## Current rule

Schwab journal ingestion is read-only.

Schwab journal ingestion may read raw files, normalized fills, transactions, positions, accounts, and fills.

Schwab journal ingestion must not place orders.
Schwab journal ingestion must not cancel orders.
Schwab journal ingestion must not replace orders.
Schwab journal ingestion must not modify orders.
Schwab journal ingestion must not auto-trade.

## Plane separation

Journal plane:

- raw broker files
- normalized fills
- DuckDB import_runs
- DuckDB normalized_fills
- DuckDB trade_episodes
- DuckDB trade_episode_legs
- DuckDB manual_reviews
- dashboard JSON
- Streamlit review UI

Execution plane:

- strategy signal
- order intent
- risk gate
- approval state
- broker order submission
- broker order status
- broker fill feedback
- post-trade journal import

Journal scripts must not directly call execution scripts.

Dashboard and Streamlit scripts must not directly call broker order write endpoints.

## Future order intent rule

Future auto-trading must use order intents.

A strategy must not call Schwab order-place directly.

Correct future flow:

strategy signal to order_intent to risk_gate to approval_or_policy to broker_order to broker_fill to normalized_fills to OneJournal

An order intent should include at least:

- intent_id
- strategy_id
- source_signal_id
- account_id
- broker
- symbol
- asset_class
- option_symbol
- side
- quantity
- order_type
- limit_price
- time_in_force
- max_loss
- reason
- created_at
- status
- risk_status
- approval_status
- broker_order_id

## Risk gate rule

Every future broker write action must pass a risk gate first.

The risk gate must be auditable.

Risk checks should include account permission, symbol permission, max quantity, max notional, max loss, duplicate intent prevention, market-hours policy, and strategy enablement.

## Schwab module rule

Schwab journal adapter modules may exist under onejournal/brokers/schwab.

Schwab execution modules may exist under onejournal/execution.

Journal adapter modules must not import order-place, order-cancel, order-replace, or order-modify functions.

Execution modules must be isolated from dashboard, Streamlit review, and import scripts.

## Token rule

Schwab token lifecycle must have one owner.

Future automation should run Schwab auth preflight first, then worker scripts should run in batch mode.

Journal scripts should not independently rotate refresh tokens.

Dashboard and Streamlit scripts should not independently rotate refresh tokens.

## Fill feedback rule

Every future broker fill must return to OneJournal through the normalized_fills contract.

Broker fills must not be written directly into trade_episodes.

Broker fills must not be written directly into dashboard JSON.

## Streaming rule

Schwab streaming is not journal source of truth.

Streaming may be used later for live monitoring, quote updates, or order status support.

Transactions and fills remain the journal truth.

## Safety

This contract does not enable auto-trading.

This contract does not add any broker API write call.

This contract does not add order placement.
This contract does not add order cancellation.
This contract does not add order replacement.
This contract does not add order modification.
