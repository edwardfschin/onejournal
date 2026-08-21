# ADR-0010: Define complete evidence provenance and correction governance

- Status: Proposed
- Date: 2026-08-20
- Decision owners: OneJournal project owner
- Related roadmap items: CON-07, JRN-08, PNL-01 through PNL-08, OPS-03,
  OPS-07
- Related contracts: ADR-0006, `docs/import_run_audit_contract.md`,
  `docs/normalized_fills_odfs_contract.md`,
  `docs/database_migrations.md`
- Supersedes: None
- Superseded by: None

## Context

Accepted ADR-0006 establishes only normalized-fill natural identity,
deterministic replay/conflict handling, and P&L input fingerprints. The current
repository also has import-run batch audit and a replace-import revision ledger
that preserves prior/next normalized-fill payloads and manual reviews.

Those mechanisms are useful but do not establish complete evidence provenance
or governed corrections. The repository does not yet provide immutable raw
content addressing, evidence-delivery versions, versioned normalized records,
explicit supersession, correction actor/reason/approval, declared event-set
versions, complete downstream invalidation, governed recalculation, or
raw-to-output lineage.

OneJournal needs a separate decision so those broader capabilities can be
reviewed without overstating the accepted ADR-0006 foundation.

## Proposed decision

Subject to project-owner approval, OneJournal will adopt the following complete
evidence-provenance and correction-governance model.

### Raw evidence and deliveries

- Immutable raw evidence is addressed by cryptographic content hash and an
  account-safe provider/source scope.
- Each retrieval or import is a distinct evidence-delivery version even when
  its content hash matches an earlier delivery.
- Delivery records identify retrieval/import run, source object/path,
  provider-reported identity and timestamps, receipt time, validation result,
  retention class, and privacy classification without exposing secrets.
- Raw evidence is never edited in place. A restatement or correction is new
  evidence linked to the earlier delivery.

### Versioned normalized records and supersession

- Every normalized financial record has a stable logical identity and an
  immutable version identity.
- Each version identifies its raw-evidence delivery, adapter version, contract
  version, normalized timestamp, validation result, and normalization
  fingerprint.
- A new accepted version explicitly supersedes, rejects, or coexists with the
  prior version according to a documented source-specific rule. It does not
  silently overwrite accepted history.
- Active-state selection is reproducible for an explicit event-set version and
  as-of instant.

### Correction governance

- Broker restatements, normalization repairs, and operator/manual corrections
  are distinct correction types.
- A correction record includes actor or automated source, timestamp, reason,
  before/after values, evidence links, review status, and approval identity when
  approval is required.
- Operator corrections cannot modify or impersonate broker evidence. They are
  separate governed overlays or records whose authority is explicit.
- Conflicts remain fail-closed until the applicable correction policy resolves
  them.

### Invalidation, recalculation, and output lineage

- An accepted correction creates a new declared event-set version.
- Dependent lots, positions, cash, P&L, reports, and published payloads are
  marked invalid or superseded before recalculation; stale outputs cannot remain
  current.
- Recalculation is deterministic, versioned, and records the exact event set,
  calculation version, as-of instant, completeness, and reconciliation state.
- Every published financial result can trace through calculation inputs and
  normalized versions to immutable raw evidence deliveries.

### Privacy, retention, migration, and recovery

- The model must minimize account identifiers and private paths in operator and
  presentation surfaces while preserving local auditability.
- Retention, deletion, legal-hold, export, and account-closure rules require
  explicit policy before automated deletion or irreversible compaction.
- Schema changes are additive and versioned. Legacy records with missing hashes
  or raw evidence remain identified as legacy/unverified; provenance is never
  invented.
- Backup, restoration, failed-correction recovery, and partially completed
  recalculation behavior are designed and tested before operational acceptance.

## Boundaries

This proposal does not authorize a migration, database rewrite, raw-evidence
backfill, correction, recalculation, provider call, retention/deletion action,
or operational rollout. It does not change the accepted ADR-0006 identity and
fingerprint semantics.

The choice of storage engine, hosted event store, authentication/authorization
model, retention duration, correction approval roles, and multi-user tenancy
remains unresolved and requires explicit decisions before implementation.

## Alternatives considered

### Treat the replace-import revision ledger as complete provenance

It preserves useful prior/next payload evidence but lacks immutable raw hashes,
normalized versions, explicit supersession, correction approval, complete
invalidation, and raw-to-output lineage. Rejected as a complete model.

### Keep broader promises in accepted ADR-0006

This would make the accepted identity foundation appear to provide unimplemented
lineage and correction guarantees. Rejected.

### Rebuild only the latest state after a correction

This loses historical reproducibility and can leave published outputs without
an auditable relationship to the evidence used. Rejected.

## Consequences

### Positive

- Broker restatements and operator corrections can become attributable,
  reproducible, and reviewable.
- Every financial output can be invalidated and recalculated from declared
  evidence rather than silently drifting.
- Legacy uncertainty remains explicit instead of receiving invented provenance.

### Negative and trade-offs

- Versioned evidence, records, event sets, and calculations increase schema,
  storage, migration, and operator complexity.
- Privacy, retention, recovery, and approval-role decisions must be resolved
  before implementation can be accepted.
- Existing prototype revision mechanisms require careful compatibility mapping;
  they cannot simply be relabelled as the final model.

## Compatibility and migration

No implementation is approved by this proposal. A later implementation plan
must map every producer and consumer of raw evidence, import runs, normalized
records, revision rows, lifecycle inputs, P&L results, reports, payloads, and
operator workflows.

Released migration files remain immutable. Any schema change requires a new
additive migration, checksum validation, rehearsal on a realistic temporary
database copy, backup/restoration evidence, row/identity reconciliation, and a
separate project-owner approval before live application.

## Security, privacy, and financial impact

Complete lineage can expose account identifiers, holdings, private paths,
operator identities, and broker records. Storage, logs, exports, fixtures, and
presentation payloads must enforce least disclosure.

Incorrect supersession or invalidation can publish stale or duplicated P&L.
Therefore unresolved conflict, incomplete correction approval, failed lineage,
or recalculation mismatch must fail closed.

## Validation required before acceptance or implementation

The decision packet must define and later prove:

- content-hash and evidence-delivery identity;
- immutable normalized versions and explicit supersession;
- correction actor, reason, before/after, review, and approval behavior;
- event-set version selection and deterministic replay;
- complete downstream invalidation and governed recalculation;
- raw-to-output lineage for representative broker restatements and operator
  corrections;
- legacy/unverified handling without invented provenance;
- privacy-safe operator and presentation surfaces;
- migration, checksum, backup, restoration, failure, and rollback behavior; and
- retention, deletion, and recovery policy conformance.

## Rollback or supersession

This proposed ADR changes no runtime or stored state and can be revised or
rejected before acceptance. After acceptance, a material policy change requires
a superseding ADR. Any later implementation must remain reversible until its
migration, recalculation, reconciliation, and recovery evidence is accepted.
