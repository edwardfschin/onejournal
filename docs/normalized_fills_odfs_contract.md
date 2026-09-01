# OneJournal Normalized Fills ODFS Contract

## Purpose

This contract defines how OneJournal treats CSV imports, normalized fills, DuckDB journal tables, and dashboard output.

CSV is an ingestion and transport format only. DuckDB is the source of truth for the journal.

## ODFS data flow

Broker export or manual entry moves through this path:

1. Raw evidence file under data/raw/
2. Canonical normalized fills under data/normalized/fills/
3. DuckDB table normalized_fills
4. DuckDB trade_episodes and trade_episode_legs
5. DuckDB manual_reviews
6. Generated dashboard payload under output/dashboard/
7. Streamlit review UI

## Folder roles

data/raw/ibkr stores original IBKR exports exactly as received.
data/raw/schwab stores original Schwab exports exactly as received.
data/raw/manual_imports stores manual import source files exactly as received.
data/normalized/fills stores canonical OneJournal normalized fill files when an export file is needed.
data/journal/onejournal.duckdb is the local DuckDB journal database.
output/dashboard is generated output and not a source of truth.

## Canonical normalized fills columns

The canonical normalized fills contract currently matches docs/examples/manual_csv/fills_template.csv.

Required columns:

- asof
- source_broker
- source_account_id
- source_fill_id
- source_order_id
- filled_at
- asset_class
- symbol
- side
- quantity
- fill_price
- commission
- fees
- currency
- option_symbol
- underlying_symbol
- option_type
- expiry
- strike
- multiplier
- open_close
- execution_venue
- liquidity_flag
- episode_group_id

Financial values use canonical decimal strings. Broker adapters must parse
source decimal tokens without a binary-float intermediate and fail closed on
missing, malformed, non-finite, or ambiguous required financial evidence.
Currency must be explicit in accounting evidence. This may be the record's
currency leg or a unique, conflict-free set of explicit provider currency legs
inside the same verified account/window, with resolution provenance recorded.
A broker-name, presentation, or account-configuration default is not currency
evidence.

### Stable identity and replay rules

Stable identity is defined by:

- `source_broker`
- `source_account_id`
- `source_fill_id`

Replay rules:

- Replay equivalence is based on the deterministic normalized-economic
  signature accepted by ADR-0006, not on byte-identical raw evidence.
- The signature deliberately excludes derived `fill_uid`, delivery-time
  `fetched_at`, and `raw_path`; changes to those fields alone do not create a
  different normalized economic fill.
- The same stable identity and equivalent normalized-economic signature is
  idempotent and deduplicates to one active normalized fill.
- The same stable identity with a changed normalized-economic signature is a
  conflict and is rejected by the normal replay path.

An explicitly requested replace import can preserve prior/next normalized
payloads and manual reviews in the current revision ledger. That bounded
mechanism is not complete source supersession or correction governance. Raw
content hashes, evidence-delivery versions, normalized-record versions,
correction actor/reason/approval, downstream invalidation, recalculation, and
raw-to-output lineage remain proposed in ADR-0010.

## Source-of-truth rule

Raw CSV files are evidence.
Normalized CSV files are transport or export artifacts.
DuckDB normalized_fills is the imported fills source of truth.
DuckDB trade_episodes is the episode source of truth.
DuckDB journal_reviews is durable review history after migration 0005;
manual_reviews is the current compatibility projection.
Dashboard JSON is generated output.

## Import audit rule

Every import into DuckDB must create or update an import_runs row with source_type, source_path, asof_date, imported_at, row_count, status, and notes.

## Broker adapter rule

Broker-specific formats must not write directly to trade_episodes.

Correct flow:

broker CSV to broker adapter to normalized fills to validator to DuckDB

Incorrect flow:

broker CSV directly to dashboard
broker CSV directly to trade_episodes
broker CSV directly to Streamlit review state

## Safety rule

All import flows are read-only with respect to brokerage accounts.

No broker API write call.
No order placement.
No order cancellation.
No order modification.
No auto-trade.

## Phase I1 historical decision

Phase I1 established CSV as the input and transport layer and DuckDB as the
journal source of truth. Schwab adapters now exist behind the normalized-fill
boundary; the earlier implementation hold on adding adapters is no longer a
current roadmap restriction.

OneJournal will not treat CSV as the live journal source of truth.

Any new or changed broker adapter must continue to satisfy this normalized-fill
contract and its validation baseline before publication.
