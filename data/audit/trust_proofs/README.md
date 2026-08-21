# Trusted Ledger proof evidence

Each proof directory separates privacy-safe tracked metadata from private
financial evidence.

The authoritative repository/private-vault boundary is defined in
[`docs/evidence_storage_contract.md`](../../../docs/evidence_storage_contract.md).

- `public/` contains proof identity, cryptographic fingerprints, status,
  limitation codes, and sign-off state. It must not contain account IDs,
  holdings, instrument details, raw broker paths, financial values, or private
  logs.
- `private/` contains the retained source evidence, normalized artifacts,
  rehearsal databases, logs, manifests, and reproduction harnesses. Git ignores
  this directory. Directories must be mode `0700` and files mode `0600`.

Assessments are append-only. A changed adapter, calculation version, source
record, or discrepancy creates a new version; it does not overwrite an earlier
assessment. Verify the private bundle manifest and public checksums before using
an assessment as evidence.
