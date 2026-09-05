# ADR-0019: Define Canonical Position, Reconciliation, and Valuation-Mark Authority

- Status: Accepted
- Date: 2026-08-31
- Decision owners: OneJournal project owner
- Related roadmap items: P1-05, P1-07, PNL-03, PNL-04, PNL-06, PNL-08, WEB-W07
- Related contracts: ADR-0003, ADR-0004, ADR-0007, ADR-0009, ADR-0011,
  ADR-0016, `docs/onejournal_data_contract_v1.md`,
  `docs/normalized_fills_odfs_contract.md`
- Supersedes: None
- Partially superseded by: ADR-0023 for separately labelled
  broker-reconciled current-position basis and unrealized P&L only
- Superseded by: None

## Context

ADR-0004 makes cumulative FIFO lots from accepted fills and lifecycle events
the canonical source of cost basis and realized P&L. ADR-0009 and ADR-0011
make provider/connection-bound quote evidence and point-in-time freshness
available, but explicitly do not make a quote a valuation mark.

The current `normalized_positions` path cannot fill this gap. It derives a
position only from one import's fills, writes the last fill price as
`market_price`, and is checked against the same fill population. Its rows are
useful prototype/import diagnostics but are neither cumulative broker-position
evidence nor approved valuation results. The current option keys used by the
quote and FIFO paths also differ, so a price cannot safely be applied to a
lot without a canonical identity boundary.

On 2026-08-31 the project owner approved the following PNL-03 authority
contract before implementation.

## Decision

### One canonical instrument identity

OneJournal will introduce `onejournal.instrument-identity.v1`, a structured,
versioned, broker-independent identity used by fills, lifecycle events, broker
position snapshots, quote requests, valuation marks, P&L lots, reconciliation,
and presentation.

For the initial Phase 1 US-listed scope, identity contains:

- equities: US listing scope, normalized symbol, and native currency; and
- listed equity options: canonical underlying identity, expiration, call/put
  right, decimal strike, contract multiplier, and native currency.

The deterministic serialized key is derived only from those typed fields and
its version. A broker/provider symbol, option display symbol, CUSIP-like
identifier, or account-local position identifier is a separately preserved
mapping or lineage field, never an interchangeable canonical key. Missing or
ambiguous identity fields fail closed. The existing free-form PNL-02 quote key
and FIFO key remain compatible evidence/prototype inputs only until every
affected producer and consumer has migrated together.

### Position and cost-basis authority

`CanonicalOpenPosition` is a calculation result from the complete accepted
fill and lifecycle-event set through one explicit UTC evaluation instant. It
contains the FIFO open lots, signed quantity, allocated native-currency cost
basis, calculation version, exact input fingerprints, and completeness state.

An independently acquired `BrokerPositionSnapshot` is the authority for
broker-reported existence and quantity at an account/instrument/time scope. A
snapshot must retain provider, opaque connection and account identity,
provider position identifier where present, canonical instrument identity,
reported quantity, source/evidence lineage, provider-observed time when
available, retrieval time, market date, and an explicit account-completeness
assertion. A partial list cannot imply that omitted positions are flat.

Canonical quantity must reconcile exactly to the broker snapshot for every
supported account/instrument scope. A missing snapshot, incomplete account
snapshot, identity mismatch, quantity mismatch, or later accepted event makes
the affected position `reconciliation_pending` or `unavailable`; it cannot
contribute to an authoritative market-value, unrealized-P&L, or portfolio
total. The applicable snapshot-age policy must be explicit in the valuation
run; it must never be inferred from a market date alone.

Broker-reported average cost, market value, unrealized P&L, and realized P&L
are reconciliation evidence. They must be preserved when supplied, compared
with the OneJournal calculation where the comparison is meaningful, and never
override FIFO lots or silently repair a discrepancy.

ADR-0023 adds a distinct broker-reconciled current-position view. It may use
the direction-specific broker tax-lot aggregate, market value, and open P&L
from one complete fresh position snapshot. It never overrides or masquerades
as the FIFO book result.

### Valuation-mark authority

Each `ValuationMarkAssessment` binds one canonical instrument identity and
evaluation instant to the exact PNL-02 quote evidence, provider connection,
quote UID, source/retrieval/provider times, session authority, freshness
assessment, selected price field, selected decimal price, selection policy
version, and failure reason when no mark is valid.

For a freshness-eligible active market session, the initial policy is
liquidation-side valuation:

- a long position uses the quote bid; and
- a short position uses the quote ask.

For an eligible closed-session `market_closed_last` assessment, the selected
price is the provider's exact last price. A normal active-session last price,
midpoint, broker-reported position price, stale/delayed/denied/unknown quote,
crossed market, missing required side, provider/connection mismatch, or
unresolved schedule authority is not a valid mark. There is no cross-provider
or cross-connection fallback.

Liquidation-side pricing is selected because it is provider-neutral and does
not invent an executable value inside a wide spread. A midpoint may later be
presented as separately labelled reference information only after an approved
policy; it is not the canonical Phase 1 valuation mark.

Market value and unrealized P&L are calculated from canonical open lots and
the selected mark, respecting option multipliers and ADR-0003 currency rules.
They remain unavailable—not zero—when their required authority is absent.

### Multi-leg positions and totals

A spread or other multi-leg strategy is a presentation grouping, not a
synthetic market instrument. OneJournal values each exact open leg
independently. A strategy total is available only when every included leg has
the same evaluation instant, a valid canonical identity, reconciled position
state, valid mark, native-currency treatment, and stated inclusion scope.
Any failed leg makes the strategy valuation unavailable and prevents it from
silently entering a consolidated total.

Portfolio totals are computed only across positions with a common declared
account, currency, and evaluation scope. They expose processed, unavailable,
and reconciliation-pending counts and privacy-safe reason codes. A partial
subtotal must never be labelled as the portfolio total.

### Storage and compatibility

Implementation will add versioned, additive position-snapshot, canonical
position-result, reconciliation-result, and valuation-mark records. It will
not reinterpret, overwrite, or use legacy `normalized_positions.market_price`,
`market_value`, or `average_cost` as PNL-03 authority. Existing prototype
rows and payload fields remain explicitly non-authoritative until a separately
approved migration and versioned producer/consumer change are complete.

The new records retain source locator/hash, adapter/calculation/policy version,
input identifiers, exact evaluation instant, status, and deterministic result
identity. Raw broker evidence stays private and does not enter frontend
responses or Git.

## Alternatives considered

### Continue deriving positions from each imported fill batch

This cannot represent cumulative inventory, independent broker evidence, or a
current broker position. Rejected.

### Treat broker cost basis or broker P&L as canonical

This would hide broker methodology and prevent a provider-neutral, auditable
FIFO journal. Rejected; broker figures remain reconciliation evidence.

### Use last price or midpoint for every active-session valuation

Last can be stale and midpoint can create a non-executable value inside a wide
spread. Rejected for canonical valuation. Liquidation-side bid/ask is accepted
for active sessions; `market_closed_last` is the narrow closed-session case.

### Build a synthetic spread mark

This hides missing or stale leg evidence and fails to preserve contract
multipliers. Rejected; all legs are marked independently.

## Consequences

### Positive

- Current position and valuation values become traceable to independent broker,
  fill/lifecycle, quote, and session evidence.
- PNL-03 can support Schwab first without embedding Schwab symbols or provider
  semantics into P&L or the web API.
- Missing evidence and discrepancies remain visible without contaminating
  financial totals.

### Trade-offs

- A current value may be unavailable more often than a broker display because
  OneJournal will not guess identity, use a stale price, or bypass a mismatch.
- The implementation requires an additive schema, broker-position adapter,
  reconciliation service, mark selector, and versioned payload before WEB-W07
  can display real valuations.
- Broker displays may differ from liquidation-side values; the difference is
  evidence for reconciliation, not an automatic defect or override.

## Approval boundaries

This decision authorizes local, credential-free contract implementation and
synthetic/temporary-DuckDB validation only. It does not authorize a provider
call, token or credential access, private-evidence write, production-journal
migration, deployment, push, sync, or live financial acceptance. Each requires
separate explicit approval.

## Validation and rollout

The first implementation slice must prove:

1. deterministic identity equality and collision rejection across fill,
   snapshot, quote, and mark inputs;
2. cumulative long/short equity and option lots, partial exits, multipliers,
   and approved lifecycle events through an exact evaluation instant;
3. exact broker quantity reconciliation, missing/partial snapshots, extra
   broker positions, mismatches, and later-event invalidation;
4. active bid/ask, eligible closed-session last, and every rejected mark path;
5. multi-leg all-or-nothing valuation, per-item reasons/counts, currency, and
   false-zero prevention; and
6. additive migration rehearsal, idempotent replay, scoped read-back, and
   existing PNL-01/PNL-02 regression coverage.

A later bounded Schwab position-evidence acquisition and acceptance will test
the provider adapter and real reconciliation scope separately. No code or test
success alone constitutes PNL-03, WEB-W07, or Phase 1 acceptance.

## Rollback or supersession

The implementation is additive and versioned. A failed migration or policy
change is rolled back by retaining existing evidence and prior calculation
results, then disabling the new result version; no raw evidence or accepted
history is overwritten. A future broker-neutral fair-value, FX, or expanded
instrument policy must supersede this ADR explicitly and provide comparison
and migration rules.
