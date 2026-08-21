# OneJournal evidence storage contract

Status: Approved

## Purpose

OneJournal separates public verification metadata from private financial
evidence. Git is the source of truth for code and public attestations; it is not
a financial evidence vault. This boundary prevents raw broker or personal data
from entering repository history while retaining enough cryptographic metadata
to reproduce and verify an assessment against controlled private evidence.

## Authoritative locations

The canonical development repository is:

```text
/Users/edward/Projects/OneJournal
```

It contains code, documentation, tests, public proof attestations, hashes, and
non-sensitive proof metadata.

The private evidence vault is:

```text
/Users/edward/Projects/Private/OneJournal
```

It contains raw broker evidence, private manifests, rehearsal databases,
sensitive validation logs, account-related artifacts, and other personal
financial information. The vault is outside Git and outside iCloud.

The former iCloud checkout is a preserved backup/reference copy only. It is not
an authoritative development repository and must not receive new development
changes.

Option 1 repository migration deliberately leaves that checkout byte-preserved.
Any private or runtime files that already exist there are legacy retained
copies: they are not copied into the canonical repository and are not
authoritative. Removing or relocating those legacy copies requires a separate,
explicitly approved privacy and operational-data cleanup with its own evidence
and rollback plan.

## Repository-allowed evidence

Git may contain only privacy-safe verification material, including:

- proof and assessment identifiers;
- cryptographic evidence and artifact hashes;
- repository commit or code-version references;
- calculation version and input fingerprints;
- assessment status and explicit limitation codes;
- owner sign-off state;
- non-sensitive reproducibility instructions.

Public proof material must not identify an account, holding, instrument, order,
fill, transaction, raw private path, or private financial value.

## Repository-forbidden evidence

Git must not contain:

- raw Schwab, IBKR, or other broker files;
- account identifiers or account exports;
- holdings, orders, fills, or transaction exports containing private details;
- private evidence manifests or preservation indexes;
- operational or rehearsal DuckDB databases and backups;
- private reproduction harnesses, command logs, or validation logs;
- journal notes, personal financial information, credentials, or tokens.

Private Trusted Ledger bundles under
`data/audit/trust_proofs/<proof-id>/private/` are ignored as a final guard. The
canonical retained bundle nevertheless belongs in the external private vault,
not inside the repository working tree.

## Reproducibility model

The public and private sides form one verification chain:

```text
public attestation
  -> proof and assessment identity
  -> private bundle-manifest hash
  -> code and calculation fingerprints
  -> assessment status and limitations

private evidence vault
  -> source evidence
  -> detailed manifests and checksums
  -> validation artifacts and rehearsal database
```

The public attestation proves which evidence and implementation produced the
assessment without publishing the evidence itself. Reproduction requires
authorized access to the corresponding private bundle and successful checksum
verification.

Assessments are append-only. A changed source record, adapter, calculation,
manifest, discrepancy, or acceptance decision creates a new version; it must
not overwrite earlier evidence or make historical results appear unchanged.

## Access and permission rules

- The private vault root and its directories must be mode `0700`.
- Private vault files must be mode `0600`.
- Symlinks are forbidden in retained private evidence bundles.
- The project owner controls private-vault access, backup policy, and financial
  acceptance.
- A repository commit or passing test does not grant private-evidence access or
  constitute Trusted Ledger acceptance.

## Validation and failure behaviour

Before a public assessment is used as evidence, validate:

1. the public checksum file;
2. every public-to-private manifest hash reference;
3. the private bundle's internal checksums;
4. private-vault permissions and absence of symlinks;
5. that Git tracks or stages no private evidence;
6. that the assessment status and limitations match the retained evidence.

Any missing bundle, hash mismatch, permission failure, unexpected private Git
path, or unexplained discrepancy fails closed. The assessment must not be
promoted or presented as accepted until the discrepancy is resolved and owner
sign-off is explicit.

## Separate operational boundary

This contract does not migrate or designate the operational journal database.
Database location, backup, restoration, migration, and writer coordination are
separate approval-gated operations. Establishing the canonical Git repository
must not copy or modify a live journal database, broker evidence, provider
credentials, or runtime output.
