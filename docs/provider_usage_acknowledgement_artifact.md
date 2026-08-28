# Provider-usage acknowledgement artifact

## Status and authority

This document describes the local persistence implementation for the accepted
ADR-0013 connection-scoped provider-usage acknowledgement. The controlling
policy remains `config/marketdata.yaml`; this artifact does not grant provider
rights, prove provider entitlement, activate a provider, or authorize a
provider call.

No real acknowledgement or connection identity was created by this
implementation. Creating the first record requires the project owner to attest
to every active-profile declaration and separately approve the private write.

## Contract and identity

`onejournal.provider-usage-acknowledgement-artifact.v1` is canonical JSON with
one trailing newline. It contains only:

- the artifact schema;
- a secret-safe creation approval identifier; and
- one complete `onejournal.provider-usage-acknowledgement.v1` object.

The acknowledgement binds the provider, opaque connection UID, active terms
profile, notice, operating scope, acceptance time, OneJournal product version,
raw-evidence lifecycle policy, and the complete declaration set. Its
`provider-usage-ack:<sha256>` identity is derived from every acknowledgement
field except the identity itself. The artifact is separately SHA-256 bound.
Reformatted, incomplete, duplicate, superseded, future-dated, pre-review,
provider-mismatched, connection-mismatched, lifecycle-mismatched, or
checksum-mismatched bytes fail closed.

The local store generates a provider-scoped connection UID from 128 random bits;
callers cannot supply the production identity. The test-only factory seam is
used solely for deterministic synthetic validation.

## Private append-only storage

The caller must supply a pre-existing absolute private root with mode `0700`
and no symlink traversal. Creation writes exactly one canonical file with mode
`0600` and create-exclusive semantics at:

```text
<private-root>/provider-usage-acknowledgements/
  <provider>/<connection-uid>/<acknowledgement-uid>.json
```

Every created directory is `0700`. Load requires the exact canonical path,
private permissions, checksum, current active profile, exact provider and
connection, and valid acceptance time. The module has no credential, network,
provider, database, overwrite, deletion, hosted-storage, redistribution, or UI
capability.

The accepted raw-evidence lifecycle still governs supersession and deletion.
A later acknowledgement creates a new immutable record; it does not rewrite the
old record. Any deletion remains a separate explicit approval and audited
operation.

## Temporary T14 bridge binding

The temporary Schwab evidence bridge must receive the exact private artifact
path, artifact SHA-256, acknowledgement UID, and connection UID. It validates
the complete canonical artifact before runtime-module verification, token
access, or provider transport. A successful evidence bundle contains an exact
`0600` copy and records its checksum and creation approval reference in the
manifest. An opaque acknowledgement string alone is insufficient.

The bridge copy is capture lineage, not the authoritative acceptance store.
OneBot remains only the temporary Schwab credential owner until the explicit
T15 break-before-make cutover; OneJournal does not obtain or refresh a token
through this artifact.

## Validation and rollback

Focused tests cover canonical round-trip, exact active-profile authorization,
128-bit connection identity, private permissions, canonical path, append-only
creation, checksum tampering, missing declarations, connection mismatch, and
unsafe roots. The temporary bridge tests independently prove that invalid
acknowledgement evidence stops before token access or output creation.

Before a real record exists, rollback is a focused code and documentation
revert. After an approved record exists, rollback never deletes or rewrites the
artifact; the record remains immutable evidence and a new approved record is
used for supersession.
