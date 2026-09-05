# ADR-0023: Add broker-reconciled current-position valuation

- Status: Accepted
- Date: 2026-09-05
- Accepted date: 2026-09-05
- Decision owners: OneJournal project owner
- Related roadmap items: P1-05, P1-07, PNL-03, PNL-04, PNL-08, WEB-W07
- Related decisions: ADR-0003, ADR-0004, ADR-0007, ADR-0019, ADR-0020,
  ADR-0022
- Partially supersedes: ADR-0004 and ADR-0019 only where they reject broker
  basis for every authoritative current-position metric
- Superseded by: None

## Context

The bounded FIFO route correctly refuses to fabricate missing fills or
individual lots. That rule also made current cost basis, market value, and
unrealized P&L unavailable for positions whose complete lifetime history was
not captured, even when a complete Schwab position response supplied its
current tax-lot aggregate basis and open P&L.

Authenticated review of Schwab's official Individual Trader API OpenAPI
specification on 2026-09-05 established that:

- GET /accounts/{accountNumber}?fields=positions supplies complete current
  positions when explicitly requested;
- each position schema can supply direction-specific
  taxLotAverageLongPrice or taxLotAverageShortPrice, market value, and
  direction-specific open P&L;
- the Trader API specification exposes no individual open-tax-lot endpoint;
- transaction history is limited to one year and 3,000 returned records, with
  no documented pagination parameter; and
- transactions support RECEIVE_AND_DELIVER, activityType=TRANSFER, stable
  activityId, and transfer-item amount, cost, price, and position effect.

Owner-private evidence independently confirmed that every member of the
current 58-position snapshot supplies its applicable directional tax-lot
average. The raw values, identities, and account information remain private
and are not recorded here.

The root problem is therefore not absent Schwab current-basis data. It is that
OneJournal had only a complete-lifetime FIFO authority path for every current
valuation use case.

## Decision

### Keep two explicit financial views

OneJournal keeps its existing FIFO book ledger for realized P&L, lot-level
journaling, lifecycle analysis, and provider-independent analytics.

OneJournal additively introduces a separately labelled
broker-reconciled current-position valuation. It may use a complete, fresh,
directly sourced broker position snapshot for current open cost basis, market
value, and unrealized P&L. It is not called OneJournal FIFO, a tax return,
realized P&L, or individual-lot history.

### Use the directional broker tax-lot aggregate

The broker adapter preserves the explicit direction-appropriate tax-lot
average separately from generic average-price fields. It never substitutes a
display average, transaction average, screenshot, manually typed value, or
zero.

For a non-zero position:

    signed open basis =
        signed quantity
        * direction-appropriate broker tax-lot average price
        * explicit instrument multiplier

    calculated current unrealized P&L =
        broker market value - signed open basis

Long basis is positive. Short opening credit is represented as negative signed
open basis so the same unrealized-P&L equation remains valid.

The calculated unrealized value is available only when it reconciles to the
broker's direction-appropriate reported open P&L at the explicitly supplied
currency quantum. A missing, zero/negative tax-lot average for a non-zero
position, directionally inconsistent market value, missing broker open P&L, or
reconciliation mismatch remains unavailable with a reason code.

### Make availability metric-specific

Quantity, current basis, market value, and unrealized P&L have independent
availability. Missing basis does not suppress a valid market value.

A complete account or portfolio total for one metric is available only when
the source snapshot explicitly asserts account completeness and every
position in that scope has that metric available under one account, currency,
and evaluation scope. A partial value remains a subtotal and cannot be
labelled as the complete total.

### Do not fabricate individual lots

An aggregate tax-lot average does not establish acquisition dates, individual
lot quantities, wash-sale adjustments, covered status, holding period, or
disposal selection. OneJournal must not manufacture those records from the
aggregate. FIFO realized P&L remains unavailable until accepted fills and
typed lifecycle evidence support it.

### Treat non-order broker activity as non-order activity

A genuine broker transfer or receive-and-deliver activity does not require an
order ID. Its provider account, stable activity ID, typed activity, instrument,
quantity, time, position effect, and source lineage form its identity and
audit boundary. Trade executions retain their order/fill reconciliation
requirements. This decision does not authorize description-text inference.

Transaction acquisition must use bounded, overlapping-safe windows, dedupe by
stable provider identity, and reject a response at the documented 3,000-record
maximum as potentially truncated. The existing 30-day external lifecycle
profile is already stricter than the one-year API maximum.

### Preserve historical evidence

The historical 53-position 46/4/3 and later 58-position 48/10 FIFO results
remain immutable evidence of their approved contracts. They are not relabelled
or overwritten. Applying this decision to owner-private evidence requires a
new versioned result, independent validation, and explicit financial
acceptance.

## Commercial product boundary

Schwab identifies Trader API - Commercial as the product for an application
distributed to other retail brokerage account holders and restricts it to
company profiles. The current authenticated profile provides Individual
Trader API access, so exact Commercial OpenAPI parity is not established.
Commercial access or written Schwab specification confirmation is required
before multi-user release. OneJournal must not assume parity.

## Alternatives considered

### Continue requiring complete lifetime FIFO for every current metric

Rejected. It unnecessarily hides broker-supplied current-position valuation
facts for transferred and older holdings while solving a different problem:
provider-independent lot reconstruction.

### Convert the aggregate into synthetic individual lots

Rejected. It would invent acquisition history and undermine auditability.

### Use screenshots or manually entered basis

Rejected for the durable product route. The source must be captured directly
from Schwab with immutable response lineage.

### Replace OneJournal FIFO with Schwab basis everywhere

Rejected. Broker aggregate basis cannot support OneJournal's individual-lot,
realized-P&L, lifecycle, or cross-broker analytical requirements.

## Consequences

- Transferred and older positions can have trustworthy current valuation
  without fabricated history.
- Current broker-reconciled P&L and OneJournal FIFO P&L remain visibly
  different metrics with different completeness states.
- Complete current portfolio totals can become available independently of
  realized-P&L and lot-history completeness.
- The adapter, result, persistence, and API contracts require explicit
  versioning and source labels.
- Commercial API entitlement and schema verification remain a launch gate for
  a multi-user product.

## Approval boundaries

This decision authorizes local credential-free contract implementation,
Schwab adapter-field validation, documentation, and synthetic tests. It does
not authorize a provider call, credential access, private-evidence write,
database migration, persistence, API activation, financial acceptance,
commit, push, synchronization, deployment, or production action.

## Validation

Tests must cover long and short equities/options, explicit multipliers,
directional tax-lot fields, transferred-position aggregate basis, cent-level
broker P&L reconciliation, missing and contradictory values, independent
metric availability, complete-total gates, snapshot freshness, deterministic
replay, and privacy-safe audit output.

## Implementation evidence

Additive migration 0015, the guarded broker-current repository, and the
unregistered private response serializer implement the persistence and release
side of this decision. Temporary-database tests prove exact snapshot replay,
transactional append, idempotent replay, read-back, currency-quantum lineage,
and value withholding unless an authorization matches both run UID and result
fingerprint.

Owner-private package `PNL-03X-BROKER-CURRENT-20260905-02` independently
replayed all 58 positions through `schwab-position-json-v3` and produced
complete cost-basis, market-value, and reconciled unrealized-P&L availability.
Separate package `PNL-03X-BROKER-CURRENT-ACCEPTANCE-20260905-01` records the
project owner's explicit acceptance of that exact broker-current result. The
earlier `-01` package and all FIFO evidence remain immutable. This evidence does
not apply migration 0015 to an actual journal, activate a route, or approve a
production release.

## Rollback or supersession

Before persistence or owner acceptance, rollback removes the additive
contract and restores the v2 adapter as current. Historical evidence is
untouched. After persistence or acceptance, any semantic change requires a new
version and side-by-side recalculation; no prior result is overwritten.
