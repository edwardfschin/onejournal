# OneJournal Schwab Transactions JSON Contract

## Purpose

This contract defines how OneJournal should read Schwab transactions JSON.

Schwab transactions JSON is the accounting and fee evidence source.

Schwab orders JSON is the execution-leg source.

The two sources should not be confused.

## Source type

This contract applies to Schwab transactions JSON containing transaction records with transferItems.

It does not apply to Schwab orders JSON.

It does not apply to Schwab UI CSV exports.

## Main rule

Transactions JSON should be used to capture trade accounting evidence.

Orders JSON should be used to capture execution-leg timing and order-leg matching.

Future reconciliation may join orders JSON and transactions JSON by orderId, symbol, quantity, price, and time.

## Transaction record fields

The adapter should read these transaction-level fields when available:

- activityId
- time
- accountNumber
- type
- status
- subAccount
- tradeDate
- positionId
- orderId
- netAmount
- transferItems

## Transaction filter rule

Only type TRADE and status VALID records should produce fill/accounting rows.

Non-trade transaction records should be ignored or reported as unsupported.

Invalid, canceled, reversed, or non-valid transaction records should not produce normalized fills.

## Transfer item rule

transferItems contain both CURRENCY items and security items.

CURRENCY transferItems are fee or cash evidence, not fill legs.

Security transferItems are fill-leg candidates.

Each security transferItem may produce one canonical normalized fill row or one fee-enrichment row in a later reconciliation phase.

## Fee evidence rule

CURRENCY transferItems with feeType such as COMMISSION, OPT_REG_FEE, SEC_FEE, TAF_FEE, and GST_FEE should be preserved as fee evidence.

Transaction-level fee totals should be calculated from CURRENCY transferItems.

Fees may be allocated across security legs when producing normalized fill rows.

Allocated fees must remain auditable.

Do not lose transaction-level fee evidence when allocating fees to legs.

## Security item rule

Security transferItems should be detected by instrument.assetType.

OPTION transferItems are option fill candidates.

EQUITY transferItems are stock fill candidates.

CURRENCY transferItems are not fill candidates.

Unknown asset types must be reported as unsupported rather than guessed.

## Quantity and cash sign rule

Schwab security transferItem amount is signed quantity evidence.

Positive amount generally indicates buy or increase in long exposure.

Negative amount generally indicates sell or decrease in long exposure.

Schwab security transferItem cost is cash movement evidence.

Do not infer strategy outcome directly from amount or cost signs.

Use positionEffect and order instruction when available.

## Price rule

Use security transferItem price when available.

If price is missing and cost, amount, and multiplier are available, infer price from absolute cost divided by absolute quantity times multiplier.

Derived prices should be marked as derived evidence in future enriched output when possible.

## Option field rule

For option transferItems, preserve instrument.symbol as option_symbol.

Use instrument.underlyingSymbol as underlying_symbol.

Use instrument.putCall as option_type.

Use instrument.expirationDate as expiry.

Use instrument.strikePrice as strike.

Use instrument.optionPremiumMultiplier as multiplier, defaulting to 100 only when missing.

Use instrument.optionDeliverables as supporting deliverable evidence.

## Source identity rule

source_fill_id for transaction-derived rows should use activityId, orderId, positionId, and security transfer item index.

source_order_id should use orderId when available.

source_account_id should use accountNumber.

filled_at should use tradeDate or time.

asof should use the date portion of filled_at.

## Multi-leg rule

A multi-leg option trade may appear as multiple transaction records with the same orderId and time.

Each transaction security transferItem should remain separately auditable.

Do not aggregate multi-leg trades inside the transactions adapter.

Episode grouping belongs later.

## Output rule

The first transactions adapter may output canonical normalized fills CSV if it can satisfy the normalized fills contract.

If fee evidence cannot map cleanly to canonical fills, the adapter should output a separate fee-enrichment evidence report first.

Do not write directly to DuckDB.

Do not write directly to dashboard JSON.

Do not call Streamlit.

Lifecycle-only transactions must remain outside normalized fills. Their event
headers and transfer-item legs may be emitted as separate normalized evidence.
Leg evidence preserves source signs and missing-value meaning without semantic
reinterpretation; it must not
default an absent option multiplier or silently derive lifecycle P&L. Structural
gaps are labelled `review_required` and remain unavailable to financial totals
until an approved lifecycle allocation rule and reconciliation evidence exist.

Some observed Schwab assignment and expiration records omit structured
`activityType` and `subType` fields. An exact lifecycle word in `description`
may therefore create a review suggestion only when its record-type shape is
recognized. Such rows use `description_hint:<EVENT>`, all child legs are
`review_required`, and no fill or P&L is produced from the hint. Description
text is never canonical lifecycle confirmation.

## Reconciliation rule

Orders JSON and transactions JSON should be reconciled after both have normalized outputs.

Use orderId as the strongest link when available.

Use symbol, quantity, price, and time as secondary evidence.

Never overwrite execution data with accounting data silently.

Never overwrite accounting data with execution data silently.

## ODFS rule

Raw Schwab transactions JSON belongs under data/raw/schwab.

Generated normalized fills CSV belongs under data/normalized/fills.

Generated reconciliation reports belong under output or data/audit, depending on whether they are runtime output or audit evidence.

Generated operational files must not be committed.

## Safety

This contract adds no adapter execution.

This contract adds no broker API call.

This contract adds no order placement.
This contract adds no order cancellation.
This contract adds no order replacement.
This contract adds no order modification.
This contract adds no auto-trade.

## Phase L1 conclusion

OneJournal should use Schwab transactions JSON for fee and cash truth.

The next implementation step is a read-only transactions JSON audit or adapter that extracts TRADE VALID records and reports security transferItems plus CURRENCY fee evidence.
