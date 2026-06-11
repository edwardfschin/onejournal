# OneJournal ODFS Ingestion Folder Contract

## Purpose

This contract defines where import evidence, normalized transport files, audit logs, journal data, and generated outputs belong.

It prevents raw broker exports from drifting into dashboard, review, or trade episode logic.

## Folder roles

data/raw/schwab stores original Schwab files exactly as exported.
data/raw/ibkr stores original IBKR files exactly as exported.
data/raw/manual_imports stores original manually prepared import files exactly as received.
data/normalized/fills stores canonical OneJournal normalized fills when a CSV transport or export file is needed.
data/audit/run_log stores local run/audit logs.
data/journal stores DuckDB journal state and review backfill/export files.
output/dashboard stores generated dashboard payloads only.
output/reports stores generated reports only.

## Raw file rule

Raw files are evidence.

Do not edit raw broker exports in place.
Do not use raw broker CSV directly for dashboard payloads.
Do not use raw broker CSV directly for Streamlit review state.
Do not import raw broker CSV directly into trade_episodes.

## Normalized file rule

Every broker-specific import must normalize into the OneJournal canonical fills contract before journal import.

Correct flow:

raw broker CSV to broker adapter to normalized fills to validator to DuckDB

Manual normalized CSV may enter through the same canonical fills contract.

## DuckDB rule

DuckDB import_runs is audit truth.
DuckDB normalized_fills is imported fills truth.
DuckDB trade_episodes and trade_episode_legs are episode truth.
DuckDB manual_reviews is review truth.

## Generated output rule

output/dashboard files are generated outputs.

Generated dashboard payloads must be rebuildable from DuckDB.

## Safety

This folder contract is read-only with respect to brokerage accounts.

No broker API write call.
No order placement.
No order cancellation.
No order modification.
No auto-trade.

## Current Phase I3 decision

OneJournal will guard folder roles before adding broker-specific adapters.

Schwab and IBKR adapters must follow this folder contract when added later.

## Runtime file tracking rule

ODFS runtime folders must exist continuously.

Use .gitkeep to track required empty runtime folders such as data/normalized/fills.

Generated normalized fills CSV files are operational artifacts and must not be committed.

Raw Schwab and IBKR broker files are private evidence files and must not be committed.

