# OneJournal Architecture Decisions

## Purpose

Significant OneJournal architecture and durable policy decisions are recorded
as architecture decision records (ADRs) under `docs/architecture/decisions/`.

ADRs explain why a decision exists, its boundaries and consequences, the
alternatives considered, and how the decision is validated. They complement
current contracts and implementation; they do not replace either.

## When an ADR is required

Create or supersede an ADR for material decisions involving:

- frontend, backend/API, database, background jobs, or hosting
- authentication, authorization, privacy, retention, or security boundaries
- broker, market-data, or execution architecture
- financial calculation, currency, time, lifecycle, or reconciliation policy
- public data contracts and compatibility strategy
- database migration or recovery policy
- dependencies or infrastructure with significant operational consequences

Routine defect fixes and implementation details that do not create durable
policy normally need tests and updated documentation, but not an ADR.

## Naming and numbering

Use:

```text
docs/architecture/decisions/NNNN-short-kebab-title.md
```

- `NNNN` is the next unused four-digit number.
- Numbers are never reused, even when an ADR is rejected or superseded.
- Renaming an accepted ADR must not change its number.
- The title describes the decision, not the work item.

## Status lifecycle

Allowed statuses:

- `Proposed` — under review; not durable policy
- `Accepted` — approved and authoritative within its stated scope
- `Rejected` — considered but not adopted
- `Deprecated` — no longer recommended but retained for history
- `Superseded by ADR-NNNN` — replaced by a later accepted decision

An unresolved roadmap question must remain `Proposed` or absent. It must not be
recorded as `Accepted` until the project owner approves it.

Accepted ADRs are immutable historical records apart from typo/link corrections
that do not alter meaning. A material change requires a new ADR that supersedes
the earlier one.

## Required content

Use [ADR-0000 template](decisions/0000-template.md). Every decision must state:

- status, date, owners, and related roadmap/contracts
- factual context and decision drivers
- the decision and explicit boundaries
- alternatives and trade-offs
- positive and negative consequences
- compatibility, migration, security, and operational impact
- validation evidence and rollback/supersession path

Claims must be grounded in the repository, runtime, contracts, or approved
requirements. An ADR must identify uncertainty rather than converting it into
policy.

## Review process

1. Inspect the current implementation and authoritative contracts.
2. Write a `Proposed` ADR with viable alternatives and a recommendation.
3. Identify public-contract, migration, security, financial, and operational
   impact.
4. Obtain explicit approval when the decision crosses a project approval
   boundary.
5. Change status to `Accepted` and implement the decision in a focused change.
6. Update affected contracts, runbooks, tests, and roadmap entries.
7. Link any later superseding ADR in both records.

## Decision register

| ADR | Status | Decision |
|---|---|---|
| [ADR-0001](decisions/0001-separate-journal-and-execution-planes.md) | Accepted | Keep journal and presentation paths isolated from broker order execution |
| [ADR-0002](decisions/0002-initial-product-scope.md) | Accepted | Start with one user, multiple owned accounts, Schwab then IBKR, and read-only US stock/equity-option workflows |
| [ADR-0003](decisions/0003-financial-units-and-time-contract.md) | Accepted | Use USD reporting with preserved native currency, decimal-safe financial values, UTC instants, New York market dates, Singapore display time, and evidence-backed session classification |
| [ADR-0004](decisions/0004-pnl-and-performance-calculation-contract.md) | Accepted | Calculate FIFO lot-based P&L from confirmed evidence and fresh marks |
| [ADR-0005](decisions/0005-trade-lifecycle-event-contract.md) | Accepted | Model fills and exceptional trade activity as immutable typed lifecycle events |
| [ADR-0006](decisions/0006-record-identity-lineage-and-correction-contract.md) | Accepted | Use normalized-fill natural identity, deterministic replay/conflict handling, and exact P&L input fingerprints |
| [ADR-0007](decisions/0007-data-freshness-and-fail-closed-presentation-contract.md) | Accepted | Keep independently valid information visible while incomplete consolidated financial results fail closed |
| [ADR-0008](decisions/0008-durable-journal-domain-and-history.md) | Accepted | Preserve journal/review history and define private strategy, tag, lesson, mistake, and attachment boundaries |
| [ADR-0009](decisions/0009-provider-independent-market-quotes.md) | Accepted | Use Schwab first, then IBKR and Moomoo, through local provider-independent quote evidence and explicit freshness states |
| [ADR-0010](decisions/0010-complete-evidence-provenance-and-correction-governance.md) | Proposed | Define immutable evidence versions, governed corrections, supersession, invalidation, recalculation, and complete raw-to-output lineage |
| [ADR-0011](decisions/0011-provider-native-market-session-authority.md) | Accepted | Use each connected account broker as the exclusive schedule authority for its quotes, with no cross-provider or external-calendar fallback |
