# OneJournal ODFS Continuous Guard

## Purpose

This guard keeps ODFS rules active during everyday development.

It is not enough for ODFS folders to be documented.

The baseline must also prevent private broker files, generated normalized fills, dashboard output, and runtime database files from being staged accidentally.

## Command

python scripts/journal/check_odfs_continuity.py

## Required folders

- data/raw/schwab
- data/raw/ibkr
- data/raw/manual_imports
- data/normalized/fills
- data/journal
- data/audit/run_log
- output/dashboard
- output/reports

## Required tracked placeholders

- data/normalized/fills/.gitkeep

## Forbidden staged files

The guard fails if any of these are staged:

- data/normalized/fills/*.csv
- data/raw/schwab/**
- data/raw/ibkr/**
- output/**
- data/journal/*.duckdb
- data/journal/*.duckdb.wal

## Operational rule

ODFS folders must exist continuously.

Generated normalized fills CSV files are operational artifacts and must not be committed.

Raw broker files are private evidence files and must not be committed.

DuckDB runtime files are local source-of-truth data and must not be committed.

Dashboard output is generated and must not be committed.

## Safety

This guard is read-only.

It does not write DuckDB.

It does not call broker APIs.

It does not place, cancel, replace, or modify orders.
