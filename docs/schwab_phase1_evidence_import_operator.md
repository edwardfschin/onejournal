# Schwab Phase 1 evidence import operator

`scripts/journal/ingest_schwab_phase1_evidence_assembly.py` validates a
pre-existing private `onejournal.schwab-phase1-evidence-artifact.v1` file. It
does not assemble provider bytes, access Schwab, open credentials, apply a
migration, write raw evidence, select P&L, or place orders.

## Validate only

The default mode reads one absolute, non-symlink, mode-0600 artifact, validates
the full contract and fingerprints, and emits a privacy-safe JSON audit:

```bash
PYTHONPATH=.:src python -m scripts.journal.ingest_schwab_phase1_evidence_assembly \
  --assembly /absolute/private/path/schwab-phase1-assembly.json
```

## Persist to an isolated database

Persistence requires both the explicit flag and an existing absolute,
non-symlink, mode-0600 DuckDB file with migration 0016 already applied:

```bash
PYTHONPATH=.:src python -m scripts.journal.ingest_schwab_phase1_evidence_assembly \
  --assembly /absolute/private/path/schwab-phase1-assembly.json \
  --persist \
  --db /absolute/private/path/isolated-acceptance.duckdb
```

The command atomically stores all eight families, loads the exact assembly UID
back, revalidates it, and reports `persisted` or `replayed`. A nonzero exit means
the result must not be used. Do not redirect output into a public path; although
the audit omits holdings and values, it remains operating evidence.

## Recovery and rollback

If validation fails, correct or replace the upstream artifact; never edit it in
place. If persistence fails before commit, the transaction rolls back. If the
process stops after commit but before read-back, rerun the exact immutable
artifact. A valid replay proves the stored state without duplication.

Migration of any real journal requires separate inspection, backup, exclusive
writer control, temporary-copy rehearsal, restoration proof, and explicit
approval. This operator cannot perform that migration. If later writes exist,
do not delete rows or restore an old file over them; use a reviewed forward
correction under ADR-0010.

Private evidence use, operational acceptance, a real database write, commit,
push, deployment, and provider access are separate approval gates.
