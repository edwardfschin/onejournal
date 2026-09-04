# Bounded PNL-03 FIFO and reconciliation contract

## Purpose

`onejournal.bounded-pnl03-fifo-reconciliation.v1` is the pure financial gate
between an approved current-position lifecycle coverage assessment and later
valuation-mark, persistence, API, and owner-acceptance work.

The boundary has no filesystem, provider, credential, database, process,
valuation-mark, or presentation capability. It consumes already validated
in-memory evidence and emits a deterministic in-memory result plus a
privacy-safe audit.

Repository code and synthetic tests do not establish that a private binding is
durable, that the owner-private vault is present, or that the real eligible 46
positions pass FIFO or reconciliation.

## Authoritative inputs

One run requires:

- one explicit versioned route specification containing the approved private
  binding SHA-256, complete broker snapshot UID, lifecycle assembly SHA-256,
  normalized-fill fingerprint, and expected status counts;
- canonical private Schwab account/instrument binding bytes;
- one complete `BrokerPositionSnapshot`;
- one `AssembledLifecycleCoverage` result;
- normalized transaction-authoritative fills for exactly the eligible provider
  instruments; and
- an explicit broker snapshot age limit.

The initial ADR-0022 route is fixed to lifecycle assembly
`7454c4543439dd6fc49d3e2089ed326ebe6eac0a3cdf8a32a82765d19c041fe6`
and the 53-position `46/4/3` state. The initial-route constructor cannot change
that digest or those counts. The private binding digest and snapshot UID remain
runtime evidence inputs because their owner-private source must not be copied
into Git.

## Exact binding and membership

The binding, lifecycle assessment, and broker snapshot must share the same
provider, opaque connection, and source account. The lifecycle cutoff must
equal the snapshot retrieval instant, and the snapshot must assert complete
account coverage.

The private provider-symbol mappings must cover every lifecycle target and
every canonical snapshot identity exactly once. Normalized provider identifiers
follow the already accepted lifecycle-coverage normalization only inside this
complete account, snapshot, assembly, and binding scope. Symbol-only or
description-only matching cannot widen eligibility.

Any binding digest, snapshot UID, assembly digest, account scope, membership,
identity, approved fill fingerprint, broker quantity, status-count, or source-
identifier conflict fails the entire boundary before FIFO acceptance.

## Eligible fill conversion gate

Only positions with `fill_flat_start_proven` coverage may contribute fills.
`normalized_fill_from_lifecycle_transaction_row` converts one accepted row only
when the caller also supplies its timezone-aware acquisition time and private
raw lineage reference; it performs no file read or write.
Every supplied `NormalizedFill` must match one eligible transaction row exactly
for source identity, order identity, execution time, as-of date, asset class,
symbol and option terms, side, quantity, price, commission, fees, currency, and
open/close state. It must also retain timezone-aware acquisition time and a
non-empty private raw lineage reference.

The normalized fill set must equal the complete eligible transaction-row set:
missing fills, extra fills, unresolved-position fills, duplicates, or changed
economics fail closed. Transaction rows remain accounting authority; order rows
remain independent execution evidence through the upstream lifecycle contract.

## FIFO and broker reconciliation

The gate runs the existing versioned FIFO engine without valuation marks. The
initial eligible scope contains no lifecycle-affected position; approved option
lifecycle instructions therefore remain outside this bounded slice. A future
route containing an accepted lifecycle event requires a separately versioned
extension rather than silent admission.

Non-zero FIFO groups become canonical position quantities and reconcile against
the complete independent broker snapshot. An eligible position is
`fifo_reconciled` only when canonical and broker quantities match exactly under
the explicit snapshot-age policy. Any eligible discrepancy remains
`reconciliation_pending` and makes the eligible subtotal unavailable.

The four `history_extension_required` and three `review_required` positions in
the initial route remain present as `unavailable`. They receive no canonical
quantity or cost basis and cannot enter FIFO, valuation, P&L, strategy totals,
account totals, portfolio totals, or performance metrics.

## Totals and privacy-safe audit

When every eligible position reconciles, native-currency cost basis may be
returned only as `eligible_cost_basis_subtotal_by_currency` with
`subtotal_status=eligible_subtotal`. `portfolio_cost_basis_by_currency` remains
unavailable. The result never claims financial acceptance or complete portfolio
totals.

The privacy-safe audit includes only contract/version identifiers, run and
evidence digests, calculation/fill fingerprints, counts, availability flags,
subtotal status, and final status. It emits no provider symbol, canonical
instrument identity, account identifier, quantity, price, cost basis, private
path, raw evidence, or credential.

## Validation and rollback

Synthetic tests prove deterministic replay, exact binding/snapshot/assembly
identity, complete binding membership, exact fill scope/economics, broker
quantity conflict rejection, unavailable-state preservation, privacy-safe
audit, and immutable initial `46/4/3` construction. Existing lifecycle-coverage,
FIFO, lifecycle-allocation, and position-reconciliation tests remain regression
dependencies.

Rollback removes the additive module, tests, and documentation references. It
does not alter private evidence, a database, generated output, or an accepted
financial result.
