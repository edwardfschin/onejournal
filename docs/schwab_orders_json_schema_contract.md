# OneJournal Schwab Orders JSON Schema Contract

## Purpose

This contract defines how OneJournal should read Schwab orders JSON and convert actual executions into canonical normalized fills.

It is based on a real Schwab orders JSON sample containing filled, canceled, replaced, OCO, vertical, calendar, and partial-fill records.

## Source type

This contract applies to Schwab orders JSON.

It does not apply to Schwab transactions transferItems JSON.

It does not apply to Schwab UI CSV exports.

## Input rule

The input is a JSON list of Schwab order records.

Top-level records may be regular SINGLE orders or OCO parent orders.

OCO parent orders may contain childOrderStrategies.

The adapter must flatten childOrderStrategies before extracting fills.

## Fill source of truth

The fill source of truth is orderActivityCollection execution records where executionType is FILL.

Do not use order status alone as the fill source of truth.

Do not create normalized fill rows from CANCELED execution records.

Do not create normalized fill rows from REPLACED orders unless they contain executionType FILL records.

Do not create normalized fill rows from WORKING, REJECTED, EXPIRED, CANCELED, or REPLACED status alone.

## Leg matching rule

Each executionLeg must be matched to orderLegCollection by legId.

The executionLeg provides actual fill quantity, fill price, and fill time.

The matched order leg provides instrument, instruction, positionEffect, and intended leg metadata.

Emit one canonical normalized fill row per executionLeg with executionType FILL.

## Required Schwab order fields

The adapter should read these order-level fields when available:

- orderId
- accountNumber
- orderType
- complexOrderStrategyType
- orderStrategyType
- enteredTime
- closeTime
- status
- tag

## Required execution fields

The adapter should read these execution fields:

- orderActivityCollection[].activityId
- orderActivityCollection[].executionType
- orderActivityCollection[].executionLegs[].legId
- orderActivityCollection[].executionLegs[].quantity
- orderActivityCollection[].executionLegs[].price
- orderActivityCollection[].executionLegs[].time
- orderActivityCollection[].executionLegs[].instrumentId

## Required order leg fields

The adapter should read these order leg fields:

- orderLegCollection[].legId
- orderLegCollection[].orderLegType
- orderLegCollection[].instruction
- orderLegCollection[].positionEffect
- orderLegCollection[].quantity
- orderLegCollection[].instrument.assetType
- orderLegCollection[].instrument.symbol
- orderLegCollection[].instrument.description
- orderLegCollection[].instrument.instrumentId
- orderLegCollection[].instrument.putCall
- orderLegCollection[].instrument.underlyingSymbol
- orderLegCollection[].instrument.optionDeliverables

## Canonical normalized fills mapping

asof comes from the date portion of executionLeg.time.

source_broker is schwab.

source_account_id comes from accountNumber.

source_fill_id must be unique and should use orderId, activityId, and legId.

source_order_id comes from orderId.

filled_at comes from executionLeg.time.

asset_class comes from instrument.assetType.

symbol is the equity symbol for stock rows and underlyingSymbol for option rows.

side comes from instruction.

quantity comes from executionLeg.quantity.

fill_price comes from executionLeg.price.

commission is zero for Schwab orders JSON unless enriched later from transactions JSON.

fees is zero for Schwab orders JSON unless enriched later from transactions JSON.

currency is USD unless a future sample proves otherwise.

option_symbol comes from instrument.symbol for option rows.

underlying_symbol comes from instrument.underlyingSymbol for option rows.

option_type comes from instrument.putCall.

expiry should be parsed from Schwab option symbol or instrument description when expirationDate is absent.

strike should be parsed from Schwab option symbol or instrument description when strikePrice is absent.

multiplier should come from optionDeliverables deliverableUnits when available, otherwise default to 100 for US options.

open_close comes from positionEffect.

execution_venue may come from destinationLinkName when available.

liquidity_flag should be blank unless Schwab provides reliable maker/taker evidence.

episode_group_id should be blank or derived conservatively until episode grouping rules are explicit.

## Instruction mapping

BUY_TO_OPEN maps to side buy and open_close open.

BUY_TO_CLOSE maps to side buy and open_close close.

SELL_TO_OPEN maps to side sell and open_close open.

SELL_TO_CLOSE maps to side sell and open_close close.

BUY maps to side buy.

SELL maps to side sell.

Unknown instruction values must fail validation or be logged as unsupported.

## Option symbol parsing rule

Schwab option symbols may use OCC-style spacing such as AAPL  250815C00150000.

The adapter must preserve the raw Schwab option symbol in option_symbol.

The adapter may parse underlying, expiry, put_call, and strike from the Schwab option symbol when explicit fields are missing.

## Multi-leg rule

Vertical and calendar orders must emit one normalized fill row per executed leg.

Rows from the same order fill activity should share source_order_id.

Rows from the same order fill activity may later be grouped into an episode using orderId, strategy type, timestamp, and legs.

## Partial-fill rule

One order may contain multiple FILL activities.

Each activityId and legId combination must produce a separate source_fill_id.

Do not aggregate partial fills inside the adapter.

Aggregation belongs later in episode building, not raw fill normalization.

## OCO rule

OCO parent orders must be flattened into child orders.

Only child orders with executionType FILL execution records should produce normalized fills.

Canceled child orders should not produce normalized fills.

## Fee limitation

Schwab orders JSON does not reliably include commission and fee transferItems.

Set commission and fees to zero for this source unless a later sample provides explicit fee fields.

Fee enrichment should come later from Schwab transactions transferItems JSON.

## Raw evidence rule

The original Schwab orders JSON must be preserved under data/raw/schwab.

The adapter output must be canonical normalized fills CSV under data/normalized/fills.

The adapter must not write DuckDB directly.

The adapter must not write dashboard JSON directly.

The adapter must not call Streamlit.

## Safety

This contract adds no adapter execution.

This contract adds no broker API call.

This contract adds no order placement.
This contract adds no order cancellation.
This contract adds no order replacement.
This contract adds no order modification.
This contract adds no auto-trade.

## Phase J3 conclusion

OneJournal can now build a read-only Schwab orders JSON to normalized fills adapter.

The adapter must emit one canonical normalized fill row per FILL execution leg.
