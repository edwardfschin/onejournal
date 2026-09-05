# Bounded PNL-03 valuation contract

## Status and scope

`onejournal.bounded-pnl03-valuation.v1` is the pure, fail-closed valuation
boundary for an already approved `BoundedPnl03FifoReconciliationRun`. The pure
calculation adds no provider client, credential, database, scheduler, API, or
presentation capability. Additive migration 0014, its guarded repository, and
the unregistered `onejournal.api.pnl03-position-valuation.v1` serializer form
separate downstream boundaries.

The boundary permits financial calculation only for positions whose lifecycle
coverage, FIFO cost basis, and exact broker quantity already reconcile. Every
other member of the complete broker snapshot remains present with unavailable
financial fields. An eligible result is always labelled `eligible_subtotal`;
it is never a complete account or portfolio total.

## Inputs and identity binding

The caller supplies:

- one completed bounded FIFO/reconciliation run;
- one lowercase SHA-256 digest for the exact quote-evidence envelope;
- zero or one quote plus freshness assessment for each eligible canonical
  instrument identity;
- one timezone-aware evaluation instant; and
- one explicit maximum age for the reconciliation evidence.

The reconciliation must have zero pending positions, internally consistent
complete/eligible/unavailable counts, an eligible cost-basis subtotal, no
portfolio cost-basis total, and `financial_acceptance=false`. Quote input may
contain only eligible identities. Provider, connection, canonical instrument,
currency, quote UID, freshness UID, and evaluation instant must all agree.

An absent, stale, delayed, denied, mismatched, crossed, or otherwise invalid
eligible quote makes both eligible valuation subtotals unavailable. It is not
converted to zero and does not silently shrink the subtotal scope.

## Mark and calculation rules

The existing `pnl-03-mark.v1` selection remains authoritative:

- a fresh active-session long position uses bid;
- a fresh active-session short position uses ask; and
- an eligible `market_closed_last` quote uses exact last.

Market value is canonical quantity multiplied by the selected price and the
canonical instrument multiplier. Equity multiplier is one. Unrealized P&L is
market value less FIFO open cost basis. Calculations remain exact `Decimal`
values in native currency; this boundary performs no FX conversion.

When every eligible mark is valid, the result exposes eligible market-value
and unrealized-P&L subtotals by currency. Portfolio market value and portfolio
unrealized P&L remain `None`, `complete_portfolio_totals_available` remains
false, and `financial_acceptance` remains false.

## Privacy-safe audit

`privacy_safe_audit()` emits only contract and route versions, opaque run and
evidence digests, evaluation/age lineage, counts, availability flags, subtotal
status, and final status. It emits no instrument identity, provider symbol,
quantity, price, cost basis, market value, or P&L value.

Private materialization is append-only and outside Git. Private directories use
`0700`; files use `0600`; manifests are written last and bind every member by
SHA-256. A private value file may retain identities and exact financial values,
while its ordinary audit and manifest remain value-free.

## PNL-03V evidence

The versioned private route `pnl-03v-58-position-2026-09-04.v4` independently
replayed the complete 58-position snapshot against six selected contiguous
lifecycle windows. It preserved the durable binding digest
`0e1000853e056a5a6079494f6b92c2d8eb802ad562476de8025ef0a5c2e7894d`
and produced assembly
`6e3787b92892fba4c536c5bd88dfcc57b22e985f8ee80e5663629cac6202115f`.
Exactly 48 positions passed FIFO and broker reconciliation; six require history
extension and four require review. The latter ten remain financially
unavailable.

The bounded quote capture used one exact 48-symbol batch and one Schwab
market-hours request, with zero OAuth refreshes, retries, account, position,
order, transaction, database, or order-write actions. Capture occurred after
the provider's 16:00 New York equity-option close. All 48 exact real-time quote
records therefore passed same-provider session authority as
`market_closed_last` and selected exact last; zero marks were unavailable.

The resulting private valuation is deterministic and makes eligible cost-basis,
market-value, and unrealized-P&L subtotals available while keeping all portfolio
totals unavailable. Replacement package
`PNL-03V-VALUATION-GATE-20260904-02` preserves the `-01` manifest digest as
historical lineage, binds persisted result fingerprint
`81f058147783b24d1cbedcea1ca0514ffa52b2468df7a42fdad5e68fd7a8ee6d`,
and proves exact create/read-back/replay through migration 0014 in a disposable
database that was not retained. Its manifest digest is
`c2d7eaf8c46b4511774137dedab4fb7e069cd43d2acdbadf3d8036a662f3b751`.
Owner financial acceptance, an actual journal migration, active private route,
commit, push, and deployment remain separate approval gates.

## Persistence and private response boundary

Migration 0014 adds separate bounded run, complete-position, and eligible-
subtotal tables. It preserves migration 0013 unchanged and persists the route,
private-binding digest, snapshot UID, assembly digest, fill fingerprint, quote
evidence/scope digests, evaluation instant, calculation version, counts, and
explicit false portfolio/acceptance flags. The repository:

- never creates or migrates a database;
- validates exact snapshot membership and broker quantities before writing;
- writes atomically and accepts only an identical replay;
- stores all complete-snapshot members, including unavailable positions; and
- reads one exact run UID without an implicit latest-run fallback.

`onejournal.api.pnl03-position-valuation.v1` serializes only that durable
read-back. Without a matching run UID and stored result fingerprint in
`onejournal.pnl03-financial-release-authorization.v1`, all quantities, mark
lineage, and financial values are withheld. A mismatched authorization fails
closed. A matching authorization releases eligible position values and
eligible subtotals as decimal strings while unavailable positions stay null.
Portfolio market value and unrealized P&L are always null and
`complete_portfolio_totals_available` is always false.

This serializer is deliberately not registered on the current unauthenticated
FastAPI application. It is not authentication or authorization infrastructure
and does not itself create owner acceptance. Route activation belongs behind
the later accepted private authentication boundary.

The one-run reconciliation-age ceiling recorded by the private package is the
exact rounded-up separation between its position/reconciliation evidence and
quote evaluation. It is evidence-specific and does not establish a reusable
global freshness policy.

## Validation and rollback

Focused tests cover 53-position `46/7` and 58-position `48/10` bounded shapes,
long/short mark selection, missing and stale quotes, scope widening, route
drift, reconciliation age, privacy-safe audit output, and the absence of
portfolio totals. Batch quote tests cover the 50-symbol cap, exact ordered
scope, canonical instrument identities, complete response matching, and legacy
single-symbol compatibility.

Temporary-DuckDB tests additionally cover migration 0014, exact create/read-
back/replay behavior, snapshot quantity drift, withheld financial values,
mismatched owner authorization, matching owner authorization, the visible
58-position `48/10` shape, decimal-string release, and invariant null portfolio
totals. The active API route table remains unchanged.

Before database or API integration, rollback is a focused code/documentation
reversion. Immutable private evidence remains under its approved retention
policy and is not deleted or rewritten by rollback.
