# ADR-0028: Append-only history materialization revisions

- Status: Accepted
- Date: 2026-09-07
- Owner: OneJournal project owner
- Related: P1-06, WEB-W06, ADR-0006, ADR-0008, ADR-0025

## Context

The first Schwab journal materialization covers a bounded history window. An
earlier source window can add valid fills that change lifecycle episode
boundaries. The migration-0018 and migration-0019 tables intentionally enforce
global episode, execution, and fill uniqueness, so writing a second complete
materialization into those tables would either fail, duplicate current UI rows,
or require destructive replacement. Reviews and journal entries also retain
their original episode identities.

## Decision

OneJournal stores every reconstructed materialization as an immutable revision
snapshot. An append-only activation ledger selects one current revision per
broker account. Before the first reconstructed revision is activated, the exact
legacy materialization, execution projection, and latest complete lifecycle
state are copied into a preserved bootstrap revision. Current-read views expose
only the latest activated revision and fall back to legacy tables for accounts
that have no activation history.

Normalized fills are shared across revisions only when their stable normalized
economics match exactly. Newly discovered fills are appended. A conflict fails
the entire transaction. Changed episode identities do not inherit reviews or
journal entries automatically; unchanged episode identities retain them, while
changed-episode notes remain preserved as historical records.

Rollback never deletes or updates revision content. It appends a new activation
that selects a prior revision.

## Boundaries

- This decision does not authorize a provider call, operational database
  migration, full-history fetch, P&L authority, deployment, or broker write.
- Evidence assembly v2 remains the immutable source input.
- The API continues to expose only current episodes; historical revision
  browsing is a separate future presentation capability.
- Incomplete financial evidence remains fail-closed.

## Alternatives considered

- Destructively rebuild the journal: rejected because it risks reviews, notes,
  lineage, and recovery.
- Insert all versions into the legacy tables: rejected because global
  uniqueness and current searches cannot distinguish versions safely.
- Delay history correction and show known-incomplete lifecycles: rejected
  because incomplete records would continue to look authoritative.

## Consequences and validation

Migration 0021 adds revision snapshots, activation history, current-read views,
and exact lineage to normalized fills. The application, search, review queues,
and lifecycle presentation resolve those views when available. Validation must
prove legacy rows remain unchanged, shared fills are exact, added fills are
unique, only one revision is current, replay adds nothing, rollback is an
activation event, and the API never mixes current and prior episodes.

The first operational application requires a verified backup and separate
owner approval. Restoring that backup remains the migration rollback if the new
schema itself is not trusted; selecting the bootstrap revision is the
non-destructive content rollback after a successful migration.
