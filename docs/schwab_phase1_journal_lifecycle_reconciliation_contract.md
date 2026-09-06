# Schwab Phase 1 journal lifecycle reconciliation contract

## Purpose and source authority

`onejournal.phase1-journal-lifecycle-reconciliation.v1` corrects historical
journal lifecycle labels using only an immutable
`onejournal.schwab-phase1-evidence-assembly.v2`. Schwab transaction lifecycle
events and the complete current position snapshot are authoritative inputs.
Screenshots, UI state, and manual symbol lists are not inputs.

The projection is credential-free and provider-call-free. It does not calculate
realized or unrealized P&L, cost basis, market value, or portfolio totals.
It also does not infer economic multi-leg trade grouping. A broker multi-leg
order is execution grouping evidence, not proof that the owner intends one
journal trade. Instrument lifecycles remain separate unless an explicit
approved episode group exists.

## Deterministic state rules

The projection reconstructs the exact migration-0018 episode basis, then:

- matches `EXPIRATION`, `ASSIGNMENT`, and `EXERCISE` security legs by canonical
  instrument identity;
- allocates signed terminal quantities FIFO across open historical episodes;
- compares aggregate residual quantity by instrument with the complete snapshot;
- returns `closed` for an exactly consumed episode residual;
- returns `open` only when the remaining instrument scope reconciles to the
  snapshot;
- returns `review_required` when the current position is absent without closure
  evidence, or any terminal/current quantity is inconsistent; and
- preserves already closed or review-required historical episodes.

Lifecycle quality is independent of lifecycle status. A terminal observation
whose extraction requires review can close the historical label while retaining
`broker_terminal_event_review_required`. No consumer may use that label to
promote unavailable financial aggregates.

## Persistence, replay, and operation

Migration 0020 stores assembly-v2 runs/families and additive reconciliation
runs/states. The repository requires the exact v2 assembly to be persisted and
the operational episode set to match its deterministic basis. A write is atomic;
an identical replay creates no rows; changed content under an existing identity
fails closed.

`scripts/journal/reconcile_schwab_phase1_journal_lifecycle.py` requires absolute,
regular, non-symlink mode-`0600` artifact and database files. It cannot create or
migrate a database, access Schwab or credentials, calculate P&L, or place orders.
Its output contains only dates, counts, contract versions, opaque identities,
fingerprints, and status.

Before operational use, create and checksum a mode-`0600` database backup,
rehearse migration 0020 and the exact v2 artifact on a disposable copy, verify
replay and database integrity, then obtain explicit approval for the real local
database change. Rollback is restoration of the verified pre-0020 backup.
