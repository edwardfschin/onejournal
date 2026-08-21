# OneJournal Import Run Audit Contract

## Purpose

This contract ensures every imported fill batch is traceable.

OneJournal must be able to answer where imported fills came from, when they were imported, how many rows were imported, and whether the import succeeded.

## Source of truth

DuckDB import_runs is the import audit source of truth.

DuckDB normalized_fills must link back to import_runs through import_run_id.

This is batch lineage: it identifies which import run produced a current
normalized-fill row and records the source path, date, count, status, and notes
for that batch. It is not complete evidence provenance.

In particular, `import_runs` does not by itself prove immutable raw content
hashes, separate evidence-delivery versions, versioned normalized records,
explicit supersession, correction actor/reason/approval, downstream
invalidation, governed recalculation, or raw-to-output lineage. Those broader
decisions remain proposed in ADR-0010.

## Required import_runs fields

- import_run_id
- source_type
- source_path
- asof_date
- imported_at
- row_count
- status
- notes

## Required quality rules

- import_runs must have at least one row after import.
- source_type must be present.
- source_path must be present.
- asof_date must be present.
- imported_at must be present.
- row_count must be greater than zero.
- status must be ok, success, or completed.
- every normalized_fills row must have import_run_id.
- every normalized_fills import_run_id must exist in import_runs.

## ODFS rule

Raw CSV files are evidence.
Normalized CSV files are transport.
DuckDB import_runs is audit truth.
DuckDB normalized_fills is imported fills truth.

## Safety

This check is read-only.

No broker API call.
No order placement.
No order cancellation.
No order modification.
No auto-trade.

## Validation

python scripts/journal/check_import_run_audit.py --db data/journal/onejournal.duckdb
