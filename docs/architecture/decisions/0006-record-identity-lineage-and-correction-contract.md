# ADR-0006: Define normalized-fill identity, replay, and calculation fingerprints

- Status: Accepted
- Date: 2026-08-20
- Decision owners: OneJournal project owner
- Related roadmap items: CON-05, JRN-06, PNL-01 through PNL-08
- Related contracts: ADR-0003 through ADR-0005, ADR-0010,
  `docs/normalized_fills_odfs_contract.md`,
  `docs/import_run_audit_contract.md`
- Supersedes: None
- Superseded by: None

## Context

OneJournal needs a bounded identity foundation that can distinguish an
equivalent normalized-fill replay from a conflicting economic payload and can
reject stale persisted P&L results. The repository implements and tests this
foundation today.

The broader provenance and correction model previously proposed in this ADR is
not implemented. Current import runs provide batch lineage, and replace imports
can preserve prior/next normalized-fill payloads and manual reviews. They do not
establish immutable raw content addressing, versioned normalized records,
explicit source supersession, correction actor/reason/approval, complete
downstream invalidation, or raw-to-output lineage. Those decisions are
separated into proposed ADR-0010.

## Decision

OneJournal accepts the following bounded identity, replay, and calculation-
fingerprint contract.

### Normalized-fill identity

- A confirmed normalized fill's natural key is `source_broker` +
  `source_account_id` + `source_fill_id`.
- A provider that lacks a stable source fill ID must define a documented,
  deterministic key and collision strategy before its fills can use this
  contract.
- Identity is not presentation identity. An order ID, symbol, episode ID,
  account label, dashboard row, or generated `fill_uid` is not a substitute for
  the natural key.

### Equivalent replay and conflict handling

- OneJournal builds a deterministic signature from normalized economic fields.
  It deliberately excludes the derived `fill_uid`, `raw_path`, and `fetched_at`
  so transport/delivery differences do not create false economic conflicts.
- Repeated records with the same natural key and the same normalized-economic
  signature are equivalent replays. They deduplicate to one active normalized
  fill.
- Records with the same natural key and different normalized-economic
  signatures are conflicts. The normal replay path rejects them rather than
  silently overwriting the active fill.
- This contract does not claim byte-identical raw-evidence replay. Raw content
  identity and evidence-delivery versions belong to ADR-0010.

### Calculation input fingerprints

- Fill-based P&L inputs are canonicalized and fingerprinted independently of
  record order.
- Approved lifecycle-instruction inputs are canonicalized and fingerprinted
  independently of record order.
- A persisted P&L run is current only when both stored fingerprints match the
  complete current as-of fill and approved-lifecycle inputs. A non-matching run
  is not published as current financial evidence.
- Calculation fingerprints prove exact calculation-input identity for their
  stated scope. They do not by themselves prove raw provenance, correction
  approval, completeness, reconciliation, or operational acceptance.

## Boundaries

This decision accepts only the repository's normalized-fill identity/replay and
P&L input-fingerprint foundation. It does not accept a complete lineage or
correction-governance model.

In particular, it does not define immutable raw evidence hashes, evidence-
delivery versions, versioned normalized records, source supersession,
correction actor/reason/approval, event-set versions, downstream invalidation,
governed recalculation, raw-to-output lineage, retention, deletion, or recovery.
Those remain proposed in ADR-0010.

The existing replace-import revision ledger is a bounded prototype mechanism.
Its ability to retain prior/next payloads and preserve manual reviews does not
authorize operators to edit raw evidence or establish a canonical broker-
correction process.

## Alternatives considered

### Keep the full lineage and correction promise in ADR-0006

This would describe capabilities the repository does not yet provide and would
make acceptance misleading. Rejected; the broader proposal is now ADR-0010.

### Deduplicate by date, symbol, quantity, and price

Independent fills can share these fields, especially for partial fills. This
risks data loss and is rejected.

### Treat `fill_uid` or episode IDs as financial identity

These identifiers are derived or presentation-oriented. They cannot replace
the broker/account/source-fill natural key. Rejected.

### Include delivery metadata in the economic signature

Including `raw_path`, `fetched_at`, or derived `fill_uid` would turn equivalent
redelivery into false economic conflict. Rejected for this signature; delivery
identity belongs to ADR-0010.

## Consequences

### Positive

- Equivalent normalized replays are deterministic and duplicate-safe.
- Conflicting normalized economics cannot silently replace an active fill in
  the normal replay path.
- Persisted P&L cannot be treated as current after its declared inputs change.
- Governance can accurately claim a strong bounded identity foundation without
  claiming complete correction or provenance capability.

### Negative and trade-offs

- Equivalent normalized signatures do not prove the raw deliveries were byte-
  identical.
- The current replace-import revision path remains operationally useful but is
  not a complete correction-governance model.
- Full raw-to-output traceability and governed recalculation remain blocked on
  ADR-0010 and later implementation.

## Compatibility and migration

This acceptance changes no runtime behavior, schema, or stored data. Current
natural keys, normalized-economic signatures, revision rows, and calculation
fingerprints remain unchanged.

Any future implementation of ADR-0010 must preserve the accepted identity and
fingerprint semantics or supersede this ADR explicitly. Released migrations
remain immutable; future schema work must be additive, versioned, rehearsed on
a temporary database copy, and separately approved.

## Security, privacy, and financial impact

Broker/account identifiers and raw paths are private. UI payloads must expose
only the minimum safe opaque identities needed for the owner's workflow.

Identity conflict or fingerprint mismatch is financial-integrity evidence. It
must fail closed and remain visible to operators; it must not be coerced into a
duplicate, correction, or current financial result.

## Validation

The accepted scope must continue to prove:

- natural-key construction from broker, account, and source fill ID;
- equivalent normalized-economic replay deduplication;
- conflicting normalized-economic replay rejection;
- exclusion of `fill_uid`, `raw_path`, and `fetched_at` from the replay
  signature;
- deterministic fill and approved-lifecycle input fingerprints; and
- rejection of persisted P&L runs whose fingerprints do not match current
  as-of inputs.

These checks validate only this ADR's bounded scope. They do not validate the
proposed ADR-0010 capabilities.

## Rollback or supersession

This documentation acceptance changes no runtime state. A material change to
the accepted identity, replay, or fingerprint semantics requires a new ADR that
supersedes ADR-0006. ADR-0010 can be revised or rejected independently while it
remains proposed.
