# ADR-0006: Define record identity, lineage, and correction semantics

- Status: Proposed
- Date: 2026-07-23
- Decision owners: OneJournal project owner
- Related roadmap items: CON-05, JRN-01 through JRN-05, PNL-01 through PNL-08
- Related contracts: ADR-0003 through ADR-0005,
  `docs/import_run_audit_contract.md`, `docs/normalized_fills_odfs_contract.md`
- Supersedes: None
- Superseded by: None

## Context

Current normalized fills use a derived `fill_uid` based on broker, account,
and source fill ID. DuckDB uses it as a primary key and import scripts use
`INSERT OR REPLACE`. Import runs link rows to an import run, and the existing
checks detect duplicate fill IDs and repeat-import count growth. This provides
a useful prototype guard but does not preserve revisions, source hashes,
supersession, or a complete correction history.

Future P&L and lifecycle calculations require a stable answer to what source
record was used, which normalization version produced it, whether it was later
corrected, and which calculation output consumed it.

## Decision

Subject to project-owner approval, OneJournal will use these identity rules.

- Raw evidence is immutable and addressed by provider, account-safe source
  scope, retrieval/import run, original path or object key, content hash, and
  retention metadata. A new broker delivery is a new evidence version.
- Every normalized record has a stable internal ID and a natural-source key.
  For a confirmed fill, the natural key is broker + source account + source fill
  ID; when a provider lacks a fill ID, the adapter must define a documented
  deterministic key and collision strategy before publication.
- Identity is not presentation identity: an order ID, symbol, episode ID,
  account label, and dashboard row are never substitutes for a fill ID.
- Normalization writes a new version with adapter/contract version, normalized
  timestamp, raw-evidence reference, and validation result. It does not mutate
  an accepted financial record in place.
- Re-delivery of byte-identical evidence is idempotent: it records a delivery
  audit outcome but creates no duplicate active economic record.
- A corrected or restated broker record creates a new version that explicitly
  supersedes the affected prior record. Downstream lots, P&L, reports, and
  payloads are invalidated and recomputed from a declared event-set version.
- Operator/manual changes are separate review or correction records with actor,
  timestamp, reason, before/after values, approval status, and source link.
  They cannot overwrite broker evidence.
- Every generated financial result identifies its input event-set version,
  calculation version, as-of instant, and completeness/reconciliation status.

## Boundaries

This decision does not choose a hosted event store, user authorization model,
or data retention period. It does not allow an operator to “fix” source data
by editing raw files, CSV exports, generated payloads, or prior calculations.

## Alternatives considered

### Continue `INSERT OR REPLACE` as the permanent correction model

It prevents duplicate primary keys but loses prior values, correction reason,
and reproducibility. Rejected for canonical financial state.

### Deduplicate by date, symbol, quantity, and price

Independent fills can share these fields, especially for partial fills. This
risks data loss and is rejected.

### Make dashboard episode IDs financial identity

Episode grouping is a user-facing and evolving interpretation. It is not
source-level evidence. Rejected.

## Consequences

### Positive

- Replays, corrections, and recalculations become auditable and deterministic.
- Duplicate detection distinguishes an identical redelivery from a real broker
  correction.
- Financial outputs can identify exactly what they were calculated from.

### Negative and trade-offs

- The current replacement-based schema and importer require a versioned,
  tested migration.
- More lineage data increases schema and storage complexity, but is required
  for financial traceability.

## Compatibility and migration

No existing identifiers may be silently discarded. A migration must map each
current `fill_uid`, source fields, import run, and raw path into the new lineage
model on a temporary database copy. Where content hash or raw evidence is
missing, the record is marked legacy/unverified rather than given invented
provenance. Existing dashboard or episode IDs remain references only.

## Security, privacy, and financial impact

Identifiers and raw paths can expose broker/account information. Frontend
payloads must use only the minimum safe opaque IDs required for the owner’s
workflow. Financial corrections must be attributable and tamper-evident.

## Validation

Implementation must prove idempotent identical redelivery, retained history for
a changed source record, collision rejection, correction linkage, downstream
invalidation, deterministic replay, no duplicated active fills/lots/P&L, and
complete raw-to-output lineage. Migration validation must include row counts,
hash checks where evidence exists, rollback, and privacy checks.

## Rollback or supersession

This proposal changes no stored data. The durable implementation must be
additive until migration verification is complete and retain a rollback path to
the prior database copy. A later retention or multi-user decision may extend
the provenance model without removing historical links.
