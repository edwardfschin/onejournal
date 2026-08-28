# Durable private quote-ingestion operator

PNL-02-T13 implements the local, provider-neutral boundary between an immutable
private quote capture and the journal quote tables. It does not retrieve quotes,
open credentials, apply migrations, select a valuation mark, or call account or
order endpoints.

## Durable source contract

The connector atomically creates one mode-0700 capture directory containing only
three mode-0600 files:

- `quote-response.json`: exact immutable provider response bytes;
- `capture-envelope.json`: deterministic
  `onejournal.market-data.quote-capture-artifact.v1` JSON containing the complete
  normalized provider-neutral capture; and
- `capture-manifest.json`: secret-free
  `onejournal.private-raw-capture-manifest.v2` metadata binding the raw digest,
  envelope digest, request-scope digest, approval, acknowledgement, connection,
  run identity, market date, timestamps, byte count, and
  `captured_private_uningested` state.

The envelope artifact is private financial evidence, not a UI payload. Its only
purpose is restart-safe reconstruction after a crash between capture and journal
persistence. The loader requires an explicit private root, relative source
locator, expected raw checksum, provider, connection, run UID, and market date.
It rejects symlinks, unsafe permissions, unexpected files, altered bytes,
manifest/envelope disagreement, incomplete request scope, or an invalid capture.
Raw response bytes never enter the ingestion audit or DuckDB.

## Operator behavior

`scripts/journal/ingest_private_quote_capture.py` defaults to validation only.
It emits one JSON audit with `validated_private_uningested` and never opens a
database. `--persist` is the explicit write gate and requires an absolute path to
an existing DuckDB journal.

The persistence path:

1. reloads and revalidates the complete private bundle;
2. verifies the exact approved provider, connection, run UID, market date,
   source checksum, and request-scope digest;
3. fails closed unless migrations 0011 and 0012 are already recorded as applied
   and their required quote tables and lineage columns exist;
4. uses the existing `persist_quote_capture_result` transaction to insert the
   ingestion run and all normalized quotes atomically;
5. reads back only the exact provider, connection, run UID, and market date;
6. verifies the stored capture fingerprint, request scope, source lineage,
   audit counts, quote UIDs, and semantic equality of every normalized field;
   and
7. emits `onejournal.market-data.quote-ingestion-audit.v1` with first-write or
   replay state and no raw payload or credential material.

DuckDB uses a fixed decimal scale, so read-back may add trailing zeroes without
changing a price. The proof therefore checks the stored pre-write fingerprint
and quote UIDs, then compares decimal values semantically. It does not recompute
an identity from DuckDB's display representation or weaken the accepted quote
identity contract.

An identical replay returns the existing row count with `was_replay=true`.
Changing the envelope under the same run UID, reusing a quote UID in another
run, missing rows, or altered lineage fails closed. A failure before commit
writes nothing. A transaction failure rolls back the run and its quote rows. If
the commit succeeded but the following read-back was interrupted, the recovery
procedure is to rerun the exact same immutable capture; replay validation then
proves the committed state. The operator never deletes or rewrites raw evidence.

## Migration and real-journal approval procedure

T13 validation uses only synthetic private bundles and temporary databases. No
actual journal database has been inspected, backed up, migrated, or written by
this implementation.

Before migrations 0011/0012 may be applied to an actual journal database, obtain
separate project-owner approval for a bounded migration rehearsal. That work
must identify the exact database and every writer, record its current version,
schema, DuckDB version, file size, row counts, integrity checks, and migration
checksums, then stop all writers and prove exclusive access. Create a timestamped
backup outside the live path, record source and backup checksums and sizes, and
prove the backup can be opened read-only. Copy the realistic database to an
isolated temporary location; run the versioned migration runner only on that
copy; validate the ledger, checksums, schema, indexes, preserved identifiers and
row counts, quote lineage, other journal contracts, repeat invocation, reopen,
and restoration.

Applying the rehearsed migration to the actual journal requires another explicit
approval that names the database, backup, target version, checksums, stopped-
writer proof, post-checks, and rollback method. The quote-ingestion operator does
not perform or repair migrations. After the migration is accepted, persisting a
specific private capture requires a separate approval bound to its provider,
connection UID, run UID, market date, source locator, and raw checksum.

Rollback is restoration of the verified pre-migration backup only while no
post-backup writes would be lost. If later writes exist, use a separately
reviewed forward correction and reconciliation; do not drop quote rows, rewrite
the migration ledger, or silently replace the journal. Provider activation,
credential use, real quote capture, OneBot retirement, deployment, push, and
quote use in P&L remain separate approval gates.
