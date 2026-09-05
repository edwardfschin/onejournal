# Broker-reconciled current-position valuation contract

## Scope

onejournal.broker-current-position-valuation.v1 evaluates one complete, fresh
BrokerPositionSnapshot without reconstructing lifetime fills or inventing
individual tax lots. It is the provider-neutral implementation of ADR-0023.

The result is a broker-reconciled current-position view. It is distinct from
OneJournal FIFO book P&L, realized P&L, tax reporting, and lot-level journal
history.

## Required evidence

Every run binds:

- one complete broker account snapshot and its raw checksum;
- one provider, connection, opaque account, market date, retrieval instant,
  and evaluation instant;
- one canonical instrument identity for every snapshot member;
- signed non-zero quantity;
- an explicit direction-appropriate broker tax-lot average;
- broker market value and direction-appropriate broker open P&L;
- explicit option multiplier, or multiplier one for equities;
- an explicit positive Decimal currency quantum; and
- an explicit maximum snapshot age.

Missing or stale scope, future-dated retrieval, incomplete account assertion,
empty portfolio scope, identity collision, missing currency policy, and
invalid multiplier reject the run.

The exact currency-to-quantum mapping is retained on the run and included in
its deterministic identity, persistence fingerprint, read-back, and private
response metadata. It is not an ambient application default.

## Calculation and reconciliation

broker-tax-lot-average.v1 calculates signed open basis as signed quantity times
the directional tax-lot average times multiplier. Long basis is positive and
short opening credit is negative. Current unrealized P&L is broker market value
less signed open basis.

The calculated unrealized amount must equal the direction-appropriate broker
open P&L when both are rounded to the supplied currency quantum using
round-half-even. The calculation retains its exact Decimal value and the exact
unrounded reconciliation difference.

Generic broker average price is preserved separately and never substituted for
a missing tax-lot average. A non-positive tax-lot average on a non-zero
position is unavailable rather than zero.

## Independent availability

Each position separately reports cost-basis, market-value, and unrealized-P&L
availability:

- valid tax-lot average and quantity can make signed open basis available;
- valid directionally consistent broker market value is independently
  available;
- unrealized P&L requires both inputs, broker-reported open P&L, and successful
  currency-quantum reconciliation.

One unavailable metric does not erase another valid metric. A complete
portfolio total for a metric exists only when every member of the complete
snapshot has that metric available. Otherwise that total is null.

The ordinary audit contains lineage, counts, availability booleans, and final
status only. It emits no instrument identifiers or financial values.

## Persistence and private release

Migration 0015 stores broker-current results separately from FIFO and bounded
eligible-subtotal results. The repository accepts only an existing migrated
database, rebuilds the supplied run from the exact broker snapshot before an
atomic append, rejects conflicting replay, and reads only an explicitly named
run. It never selects an implicit latest result. If the shared snapshot already
exists, its complete identity set and stored tax-lot averages must match; a
legacy null is not silently backfilled into current financial authority.

`onejournal.api.broker-current-position-valuation.v1` is a serialization
contract, not an active route. It labels the view
`broker_reconciled_current_position` and withholds quantities and financial
values until supplied an exact
`onejournal.broker-current-financial-release-authorization.v1` matching both
the valuation run UID and result fingerprint. The calculation's
`financial_acceptance=false` cannot impersonate that separate owner decision.

The owner-private 58-position replay is versioned as
`PNL-03X-BROKER-CURRENT-20260905-02`; it supersedes but does not overwrite
`-01`, retains the explicit USD quantum, and independently reports 58 available
cost bases, market values, and reconciled unrealized-P&L values. Separate
owner-acceptance package
`PNL-03X-BROKER-CURRENT-ACCEPTANCE-20260905-01` binds that exact result. These
artifacts accept the owner-private current-position financial result only; they
do not accept a live migration, active API route, authentication design, or
production release.

## Schwab mapping

schwab-position-json-v3 reads:

- long positions from taxLotAverageLongPrice and longOpenProfitLoss;
- short positions from taxLotAverageShortPrice and shortOpenProfitLoss;
- signed quantity from longQuantity - shortQuantity; and
- current value from marketValue.

A non-zero opposite-direction tax-lot average or open-P&L value rejects the
position. Missing directional tax-lot values remain explicit; they are not
filled from averagePrice.

The official Individual Trader API specification exposes these fields through
GET /accounts/{accountNumber}?fields=positions but exposes no individual
open-lot endpoint. Exact Commercial API parity remains unverified and is
required before multi-user release.

## Boundaries

This contract has no provider, credential, database, process, API-route, or
order capability. It does not modify the historical bounded FIFO route and
does not establish financial or operational acceptance.
