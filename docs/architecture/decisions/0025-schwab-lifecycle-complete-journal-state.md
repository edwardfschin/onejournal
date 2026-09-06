# ADR-0025: Preserve Schwab terminal events and reconcile journal state

- Status: Accepted
- Date: 2026-09-06
- Decision owners: OneJournal project owner
- Related roadmap items: P1-06, WEB-W06
- Related decisions: ADR-0005, ADR-0006, ADR-0007, ADR-0018, ADR-0019,
  ADR-0021, ADR-0024
- Supersedes: None
- Superseded by: None

## Context

The accepted Phase 1 Schwab assembly v1 preserved transactions and 430
transaction-authoritative fills, but it did not preserve the normalized
lifecycle event headers and legs already extracted from those transactions.
The migration-0018 episode builder therefore saw only fills. An option that
expired, was assigned, or was exercised after its last fill could retain a
non-zero fill residual and be labelled `open` even though Schwab's transaction
evidence and complete current-position snapshot showed otherwise.

The journal is historical, so a closed symbol must remain searchable. The
defect is its lifecycle label, not its continued presence. Current-position
absence alone is also insufficient to invent a close, and lifecycle evidence
that needs review must not become financial P&L authority.

## Decision

OneJournal will preserve the v1 assembly and its accepted P1-05 evidence as
immutable history. The additive
`onejournal.schwab-phase1-evidence-assembly.v2` appends two exact families:
`lifecycle_events` and `lifecycle_event_legs`. It does not remove or reinterpret
any v1 family.

The credential-free
`onejournal.phase1-journal-lifecycle-reconciliation.v1` projection will:

1. rebuild the same deterministic fill-derived episode basis;
2. match Schwab `EXPIRATION`, `ASSIGNMENT`, and `EXERCISE` security legs by
   canonical instrument identity and allocate their signed quantities FIFO;
3. reconcile the aggregate remaining quantity for each instrument to the
   complete current Schwab position snapshot;
4. label an episode `closed` when terminal-event quantities close its residual;
5. label an episode `open` only when its remaining instrument scope reconciles
   to the current-position snapshot; and
6. label it `review_required`, never `open`, when the position is absent without
   sufficient terminal evidence or when quantities disagree.

Lifecycle status and financial authority remain separate. A review-required
Schwab terminal observation may establish the historical `closed` label while
retaining `lifecycle_quality=review_required`; financial aggregates remain
unavailable until the relevant financial gate accepts complete evidence.

Migration 0020 stores assembly v2 and the lifecycle projection additively. It
does not update the migration-0018 `trade_episodes` rows, source fills, reviews,
journal entries, PNL-03 evidence, or financial totals. Read services select the
latest account/as-of lifecycle projection for an episode. Exact replay is
idempotent and content conflicts fail closed.

The local-owner API advances to `onejournal.local-owner-journal.v3` and exposes
the reconciled lifecycle label and reason. Its private page calls the data
historical journal state and does not link its navigation to synthetic
portfolio or trade routes.

## Consequences

- Schwab is the source for the lifecycle correction; screenshots and manual
  holdings claims are not imported.
- Closed trades remain in the journal and are visibly labelled closed.
- A missing current position without closure evidence becomes an actionable
  review state rather than a false open or invented close.
- Assembly v1, migration 0018, and migration 0019 remain reproducible historical
  evidence.
- Migration 0020 must be rehearsed on a disposable copy and separately approved
  before application to the owner operational journal.
- This decision does not add provider access, choose production tenancy, enable
  multi-account consolidation, calculate P&L, or authorize deployment or orders.

## Rejected alternatives

- Hide symbols absent from the current snapshot: rejected because a journal is
  historical and would lose closed-trade review value.
- Mark every absent position closed: rejected because transfers, incomplete
  history, corporate actions, or quantity gaps can make absence ambiguous.
- Patch the known VIST, TRI, or SAP rows: rejected because the defect applies to
  every instrument and future Schwab account.
- Use screenshots or typed cost basis as source evidence: rejected because the
  durable product route must be replayable from Schwab evidence.
- Rewrite the original episodes in place: rejected because it would destroy the
  accepted historical projection and complicate rollback.
