# OneJournal Schwab Legacy Normalizer Findings

## Purpose

This document captures what OneJournal learned from the legacy Schwab journal and fills workflow.

It defines the reusable Schwab normalization ideas without copying legacy code directly into OneJournal.

## Current sample status

The uploaded Schwab JSON transaction sample contained an empty transaction list.

That sample confirms the expected input may be a JSON transaction list, but it is not sufficient to build field-level parser logic.

A non-empty Schwab transaction JSON or CSV export is still required before implementing the adapter.

## Main legacy lesson

The legacy workflow did not write Schwab records directly into trade episodes.

It first preserved raw Schwab transaction evidence, then normalized trade legs into a fill-like table.

OneJournal should preserve that pattern using ODFS:

raw Schwab evidence to Schwab adapter to canonical normalized fills to validator to DuckDB import to dashboard payload

## Schwab transaction structure findings

Schwab transaction records may contain transferItems.

Security transferItems represent fill legs.

CURRENCY transferItems should not become fill legs.

Transaction-level JSON should be preserved as evidence.

Transaction-level fees may need allocation across security legs.

## Schwab field mapping findings

transactionId or activityId maps to source fill identity.

orderId maps to source_order_id.

transaction date or trade date maps to filled_at and asof evidence.

transferItems instrument symbol maps to symbol or option_symbol.

transferItems instrument assetType maps to asset_class.

transferItems amount is signed quantity evidence.

Absolute transferItems amount is fill quantity evidence.

transferItems price is preferred fill price when available.

transferItems cost may be used to infer price when price is missing.

instrument underlyingSymbol maps to underlying_symbol.

instrument putCall maps to option_type.

instrument expirationDate maps to expiry.

instrument strikePrice maps to strike.

instrument optionPremiumMultiplier maps to multiplier, usually 100 for US options.

positionEffect maps to open_close when available.

## Price inference rule

If a security leg has price, use price.

If price is missing and cost, amount, and multiplier are available, infer price from absolute cost divided by absolute quantity times multiplier.

The inferred price should be treated as derived data, not raw evidence.

## Quantity and side rule

Schwab amount sign must be audited with real samples before final adapter implementation.

The adapter must not guess buy or sell direction until non-empty Schwab examples are reviewed.

Once confirmed, side may be inferred from signed quantity and Schwab instruction fields.

## Fees rule

Schwab fees may appear at transaction level rather than leg level.

If a transaction has multiple security legs, fees should be allocated carefully and auditably.

The adapter should preserve both allocated leg fees and transaction-level fee evidence when possible.

## Multi-leg rule

Multi-leg option trades should preserve one normalized fill row per security leg.

Rows from the same Schwab transaction or order should share source_order_id or another grouping key when available.

episode_group_id should be generated only when there is enough evidence.

## OneJournal output rule

The Schwab adapter must output the canonical OneJournal normalized fills contract.

It must not output a separate legacy oms_fills table.

It must not write directly to trade_episodes.

It must not write directly to dashboard JSON.

## Future shared normalizer rule

Schwab CSV import and Schwab REST transaction import should share the same normalizer core.

The file adapter and REST adapter should differ only in input reading and raw evidence capture.

Both paths must produce canonical normalized fills before DuckDB import.

## Future execution lesson

Legacy workflow concepts such as intent key, base key, payload hash, dry-run, queue, action capture, and fills feedback are useful for future execution planning.

Those concepts belong in the execution plane, not the journal adapter.

Future auto-trading must still use order intents, risk gates, approval or policy checks, broker execution, fill feedback, and normalized_fills journal import.

## Safety

This findings document adds no adapter execution.

This findings document adds no broker API call.

This findings document adds no order placement.
This findings document adds no order cancellation.
This findings document adds no order replacement.
This findings document adds no order modification.
This findings document adds no auto-trade.

## Phase J2 conclusion

OneJournal has enough legacy understanding to design the Schwab normalizer core.

OneJournal still needs a non-empty Schwab transaction JSON or CSV sample before implementing the parser.
