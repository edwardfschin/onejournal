# Schwab history materialization revision contract v1

The contract `onejournal.history-materialization-revision.v1` permits an
already validated Schwab assembly v2 to extend a private journal without
deleting or rewriting prior materializations.

## Preconditions

- The input is one explicit, immutable, mode-`0600` assembly-v2 file.
- The target is one explicit, existing, non-symlink, mode-`0600` DuckDB with
  migrations through 0021.
- The assembly is persisted and verifies by exact fingerprint.
- The operator supplies the exact currently active predecessor materialization.
- No provider, credential, order, P&L, or database-discovery capability exists
  in the revision command.

## Atomic behavior

On the first revision, the command snapshots the exact legacy materialization,
projection, and latest complete lifecycle state, then appends the reconstructed
revision and activates it in the same transaction. Later revisions must name
the current predecessor. Existing normalized fills are reused only after exact
stable-field comparison; new fills are appended once. Every fill belongs to
exactly one episode and one execution inside each revision.

An identical invocation is a verified replay. A reused identity with different
content, a stale predecessor, missing projection/lifecycle state, duplicate
fill, or cash mismatch rolls back the transaction and leaves the prior current
revision selected.

## Current and historical state

Application readers use `journal_current_*` views. They return the latest
activation for a revised broker account and legacy rows for an unrevisioned
account. Prior revision rows, reviews, entries, evidence assemblies, and legacy
tables remain preserved. Notes and reviews follow unchanged episode identities;
changed episodes require fresh review rather than silently inheriting a
potentially invalid judgment.

Rollback appends an activation selecting a prior revision. It never updates or
deletes a revision.

## Privacy-safe audit

Operator output may include opaque revision/activation identities, sequence,
record counts, reuse/addition counts, final quality state, and whether evidence
or revision content was created or replayed. It must not print account IDs,
symbols, holdings, values, journal prose, broker payloads, or credentials.
