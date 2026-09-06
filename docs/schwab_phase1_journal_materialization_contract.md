# Schwab Phase 1 journal materialization contract

## Purpose and authority

`onejournal.phase1-journal-materialization.v1` is the credential-free boundary
from one exact, persisted `onejournal.schwab-phase1-evidence-assembly.v1` to the
private operational journal tables used by WEB-W06. The immutable evidence
assembly remains authoritative. Materialization is a replayable projection; it
does not modify source evidence, call Schwab, calculate P&L, select marks, or
place orders.

Migration 0018 is preserved as the historical materialization boundary. Its
`trade_episode_legs` rows are execution-granular lineage and must not be
interpreted as distinct strategy instruments. Migration 0019 and
`docs/schwab_phase1_execution_projection_contract.md` provide the corrected
execution/instrument/strategy read model without rewriting this evidence.
Assembly-v2 lifecycle reconciliation is a further additive read projection
defined in `docs/schwab_phase1_journal_lifecycle_reconciliation_contract.md`;
it does not rewrite migration-0018 episodes.

Authoritative implementation:

- `src/onejournal/journal/schwab_evidence_materialization.py`;
- migration `0018_add_phase1_journal_materialization.sql`; and
- `scripts/journal/materialize_schwab_phase1_journal.py`.

## Fill conversion

Every transaction-authoritative fill in the assembly is converted exactly once
to `normalized_fills`. Stable identity is provider, opaque account, and source
fill identity. Decimal values never pass through binary float. Execution and
acquisition instants retain explicit UTC evidence. `raw_path` contains a stable
in-database evidence locator, not a workstation path. Migration 0018 records
the source-record fingerprint for every materialized fill.

Missing, duplicate, non-finite, timezone-less, cross-account, cross-provider,
or out-of-window fill evidence fails the complete transaction.

## Conservative episode projection

Fills are grouped by provider, opaque account, asset class, currency, and exact
instrument or explicit episode group. The existing lifecycle engine may derive
an episode only when captured open/close ordering is internally complete.

If a captured close needs an earlier opening fill, the complete scope remains
visible as one `review_required` episode with reason
`history_extension_required`. Its fill legs remain inspectable, but canonical
quantity, cashflow, commission, and fee aggregates are stored as unavailable,
not zero. Unsupported side, open/close, quantity, identity, or time semantics
fail the complete materialization rather than being relabelled.

Migration 0018 stores exact assembly-to-fill, assembly-to-episode, and
episode-to-fill lineage. The local-owner API returns `lifecycle_quality` and
`lifecycle_reason`; unresolved scopes enter the incomplete review queue.
Materialized episode identities are stable content-derived opaque values and do
not embed the private account identity used by legacy preview builders.

These episodes remain a private journal/review projection. They are not the
accepted FIFO engine, tax lots, realized P&L, current-position valuation, or
portfolio totals.

## Persistence, replay, and privacy

The operator requires an absolute non-symlink mode-`0600` artifact and a
pre-existing non-symlink mode-`0600` migration-0018 database. It first proves
that the exact assembly is present, then writes the import run, canonical fills,
episodes, legs, and lineage in one transaction. An identical replay performs no
new write and verifies stored run, fill, episode, and leg-link fingerprints.
Existing account-scoped fills or episodes outside the exact replay fail closed.

Ordinary audit contains only version identifiers, stable hashes, counts,
quality states, and operation status. It contains no symbol, account identity,
quantity, price, financial value, private path, broker payload, or credential.

## Validation and rollback

Automated tests use synthetic evidence and disposable databases to prove exact
conversion, resolved and incomplete-history behavior, atomic persistence,
replay, tamper rejection, migration presence, private file gates, and
privacy-safe audit.

Before creating an owner operational journal, rehearse the exact immutable
artifact in a disposable mode-`0600` migration-0018 database. Create the real
database exclusively, validate exact counts and replay, and only then bind the
loopback API. Because this first operational database has no prior owner journal
writes, rollback is to stop the local processes and remove the failed candidate;
the accepted P1-05 evidence database and artifact remain unchanged. Once owner
journal entries or reviews exist, replacement or restoration requires a
separately reviewed forward-preserving procedure.
