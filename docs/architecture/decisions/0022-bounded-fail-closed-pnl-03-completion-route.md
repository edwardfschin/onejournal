# ADR-0022: Adopt a bounded fail-closed PNL-03 completion route

- Status: Accepted
- Date: 2026-09-01
- Decision owners: OneJournal project owner
- Related roadmap items: P1-05, P1-07, PNL-03, PNL-03S, PNL-08, WEB-W07
- Related decisions: ADR-0004, ADR-0007, ADR-0019, ADR-0020, ADR-0021
- Related contracts: `docs/current_position_lifecycle_coverage_contract.md`
- Supersedes: None
- Superseded by: None

## Context

The complete accepted Schwab position snapshot contains 53 current positions.
Five contiguous, credential-free lifecycle windows from 2026-04-05 through
2026-09-01 assemble under
`onejournal.current-position-lifecycle-coverage.v1` with digest
`7454c4543439dd6fc49d3e2089ed326ebe6eac0a3cdf8a32a82765d19c041fe6`.
That bounded evidence proves fill-flat starts for 46 positions, leaves four
requiring earlier history, and leaves three review-required because transaction
evidence lacks provider order IDs. The newly surfaced PNL-03Q and PNL-03R cases
have no exact execution-signature order candidate.

Successive earlier windows showed diminishing acceptance value: PNL-03Q added
two fill-flat-proven positions, while PNL-03R added none and surfaced another
review-required position. More history may help the four history-extension
positions, but it cannot repair missing provider order identity without new
authoritative evidence. Requiring all 53 positions to become financially
eligible before any bounded product progress would therefore turn an explicit
data-quality state into an indefinite delivery blocker.

ADR-0019 and ADR-0007 already require unavailable values rather than guesses or
false zeroes and forbid a partial subtotal from being labelled as the portfolio
total. On 2026-09-01 the project owner approved the bounded fail-closed route
defined below.

## Decision

### Freeze the bounded evidence baseline

The five-window assembly digest above is the initial bounded PNL-03 lifecycle
coverage baseline for the 2026-08-31 complete broker snapshot. Its 46/4/3 state
is immutable evidence for this route; it is not rewritten when later history is
acquired.

Future contiguous lifecycle windows remain permitted through separately
approved acquisition and validation. A later result creates a new versioned
assembly and acceptance assessment. It does not silently change an earlier
calculation, output, or owner acceptance.

### Permit only eligible positions to advance

The 46 `fill_flat_start_proven` positions may advance to the remaining PNL-03
gates: durable private account/instrument binding, accepted lifecycle conversion
and cumulative FIFO, exact broker-quantity reconciliation, valuation-mark
assessment, persistence/migration, versioned API/presentation, and owner
financial acceptance.

`fill_flat_start_proven` is only an eligibility gate. It does not itself approve
cost basis, market value, unrealized P&L, a valuation mark, persistence, or
presentation.

### Preserve seven positions as explicit unavailable records

The four `history_extension_required` and three `review_required` positions
remain members of the complete broker snapshot. They must remain visible in the
bounded position scope with privacy-safe unavailability reasons. Their broker-
reported existence and quantity may be presented only after the normal binding,
snapshot, freshness, and API gates pass.

They cannot enter canonical FIFO lots, accepted cost basis, valuation, unrealized
P&L, strategy totals, account totals, portfolio totals, or performance metrics.
Missing values remain unavailable, never zero. A provider symbol, time, price,
quantity, or description cannot be used to infer a missing provider order ID.

### Label partial financial results truthfully

Financial results calculated from eligible positions are an `eligible subtotal`,
not the portfolio total. Every payload and screen must expose the complete
position count, eligible/processed count, unavailable count, reconciliation-
pending count, omission reasons, common evaluation scope, and subtotal status.

When any position in a requested strategy or consolidation scope is unavailable,
the complete strategy, account, or portfolio total is unavailable. OneJournal
must not silently omit the position, relabel the eligible subtotal, or compute a
percentage whose denominator implies complete portfolio coverage.

### PNL-03 remains open until the remaining gates pass

This decision removes complete historical backfill as a prerequisite for the
bounded route. It does not complete PNL-03. Completion still requires the 46
eligible positions to pass durable binding, cumulative FIFO, lifecycle and exact
broker reconciliation, approved valuation marks, additive persistence and
migration, versioned API and fail-closed presentation, regression validation,
and explicit owner financial acceptance. The seven unavailable positions must
also pass their visibility and exclusion tests.

## Alternatives considered

### Continue mandatory 30-day captures until all positions resolve

Rejected as the blocking route. It has diminishing returns, cannot guarantee
provider order identity, and delays safe product behavior that already has an
approved unavailable state. Additional history remains optional evidence work.

### Infer missing order identity from execution details

Rejected. The current contract deliberately requires the provider order ID, and
the newly surfaced cases have zero exact execution-signature candidates.

### Hide unresolved positions from the product

Rejected. The broker snapshot is complete; omission would falsely imply that the
positions do not exist and could make partial totals look complete.

### Treat the eligible subtotal as the portfolio total

Rejected. This violates ADR-0007 and ADR-0019 and would materially misstate the
owner's portfolio.

## Consequences

- PNL-03 can advance without guessing facts or waiting indefinitely for provider
  history that may never contain an order ID.
- The product must support mixed available/unavailable position states as a
  first-class contract rather than an exceptional UI case.
- Complete portfolio totals and dependent performance metrics remain unavailable
  while any included position is unresolved.
- Later evidence can improve coverage through a new deterministic version without
  invalidating or rewriting the frozen baseline.

## Approval boundaries

This decision authorizes the documentation and local contract implementation
needed to enforce the bounded route. It does not authorize a provider call,
credential access or refresh, private-evidence write, private binding creation,
database write or migration, commit, push, sync, deployment, website enablement,
or PNL-03 owner financial acceptance. Each remains separately approval-gated.

## Validation and rollout

Implementation must prove:

1. eligibility binds the exact snapshot and assembly digest and cannot be widened
   by symbol-only or descriptive matching;
2. the four history-extension and three review-required positions remain present
   with explicit unavailable reasons and no financial values;
3. eligible results cannot be labelled as complete strategy, account, portfolio,
   or performance totals;
4. processed, unavailable, reconciliation-pending, and omission counts reconcile
   to the complete 53-position snapshot;
5. replay is deterministic and a future history extension produces a new
   versioned assessment without overwriting the frozen baseline; and
6. existing PNL-01, PNL-02, PNL-03, API, privacy, and false-zero tests remain
   unchanged and passing.

## Rollback or supersession

Before persistence, rollback removes the additive route contract and restores
the earlier PNL-03 blocker wording. The immutable private evidence remains under
its approved lifecycle. After a result is persisted or owner-accepted, a policy
change requires a superseding ADR and versioned recalculation; no accepted result
or raw evidence is rewritten.
