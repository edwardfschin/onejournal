# OneJournal Operator Quickstart

## Purpose

This is the simple operator workflow for the current OneJournal internal prototype.

OneJournal is read-only. It does not place orders, cancel orders, replace orders, or auto-trade.

## Activate OneJournal

Run: actoj

This activates the OneJournal Python environment and moves into the project folder.

## Baseline Check

Run: ./bin/onejournal_check.sh

Expected final line: PASS OneJournal baseline looks good.

If it fails, fix the failing section before continuing.

## Refresh Dashboard Payload

Run: python scripts/journal/build_dashboard_payload_from_db.py --asof 2026-06-02 --db data/journal/onejournal.duckdb --output output/dashboard/latest/dashboard_payload_from_db.json --write

This rebuilds output/dashboard/latest/dashboard_payload_from_db.json from DuckDB manual_reviews.

## Edit Manual Reviews

Phase B review source of truth: DuckDB manual_reviews

Edit review_status, setup_quality, entry_reason, and notes.

Do not edit episode_uid unless the trade episode itself changes.

After saving reviews in Streamlit, the DB dashboard payload is rebuilt from DuckDB manual_reviews.

## Start Dashboard

Run: streamlit run src/onejournal/apps/streamlit_app.py

Then refresh the browser page.

## Current Data Source

Current prototype input: docs/examples/manual_csv/fills_template.csv

This is a sample manual CSV file used to test Sell Put, Buy Call, and vertical workflows.

## Multi-Leg Trade Grouping

Use episode_group_id to group related legs into one trade episode.

For single-leg trades, episode_group_id can be unique per trade.

For verticals or multi-leg trades, all related legs must share the same episode_group_id.

Example: SPY_PUT_VERTICAL_001

OneJournal currently supports simple 2-leg vertical classification and can safely group up to 4-leg option trades as Multi-Leg Option.

## Supported Strategy Labels

Current prototype validates these strategy labels:

- Sell Put
- Buy Call
- Sell Call
- Buy Put
- Put Credit Vertical
- Put Debit Vertical
- Call Credit Vertical
- Call Debit Vertical
- Stock Long
- Stock Short

3-4 leg option trades are grouped safely as Multi-Leg Option until a more specific classifier is added.

## Current Flow

manual CSV fill -> NormalizedFill -> strategy classification -> TradeEpisodePreview -> DuckDB manual_reviews -> dashboard_payload_from_db.json -> Streamlit dashboard

## Safety Rules

No broker API in this prototype.

No auto-trade.

No order placement.

No order cancellation.

No order replacement.

No broker credentials in CSV files.

## Normal Daily Prototype Loop

1. actoj

2. ./bin/onejournal_check.sh

3. python scripts/journal/build_dashboard_payload_from_db.py --asof 2026-06-02 --db data/journal/onejournal.duckdb --output output/dashboard/latest/dashboard_payload_from_db.json --write

4. Use Streamlit DB payload Save Review to write DuckDB manual_reviews.

5. Save Review in Streamlit writes DuckDB manual_reviews and rebuilds the DB dashboard payload.

6. streamlit run src/onejournal/apps/streamlit_app.py

7. Refresh Streamlit browser page.

## DuckDB Phase B Review Store

OneJournal Phase B uses DuckDB manual_reviews as the primary editable review store.

Use this command when you want to refresh the dashboard and prove that the CSV-built payload and DB-built payload still match:

```bash
python scripts/journal/refresh_dashboard_db_transition.py
```

What it does:

1. Rebuilds the normal CSV dashboard payload.
2. Imports fills and legacy/backfill CSV reviews into DuckDB when a resync is needed.
3. Checks the DuckDB journal database.
4. Builds a dashboard payload from DuckDB.
5. Compares the legacy CSV-built payload against the DB payload for migration safety.
6. Runs the OneJournal baseline check.
7. Prints a final result block.

Expected final result:

```text
CSV_PAYLOAD_REFRESH=PASS
DB_IMPORT=PASS
DB_CHECK=PASS
DB_PAYLOAD_BUILD=PASS
CSV_VS_DB_PAYLOAD_COMPARE=PASS
BASELINE=PASS
OVERALL=PASS
```

Safety notes:

- This runner is read-only from a trading perspective.
- It does not call broker APIs.
- It does not place, cancel, or modify orders.
- It does not enable auto-trade.
- It keeps the existing Streamlit dashboard flow untouched.


## Phase B Review Save

Streamlit DB payload Save Review writes DuckDB manual_reviews.
CSV manual_reviews.csv is legacy/backfill/export only.
No auto-trade.

## Phase B Default Payload

DB payload is the default Streamlit payload in Phase B.
Save Review writes DuckDB manual_reviews.
CSV payload is legacy/backfill/export only.
No auto-trade.

## Phase B Read-only Payloads

CSV and Custom payloads are read-only in Phase B.
Use DB payload to save reviews.
CSV manual_reviews.csv is legacy/backfill/export only.
No auto-trade.

## Phase F Current Operator Runbook

Use this sequence for the normal OneJournal DB review workflow.

```text
1. Confirm Git identity and clean status.
2. Run ./bin/onejournal_check.sh.
3. Build the DB dashboard payload from DuckDB manual_reviews.
4. Run check_db_dashboard_contract.py to prove dashboard_payload_from_db.json has the expected DB schema.
5. Run check_save_review_flow.py to prove Save Review works end to end on a temporary DB copy.
6. Launch Streamlit.
7. Select DB payload.
8. Use Save Review to DuckDB.
9. Treat CSV and Custom payloads as read-only.
10. Confirm no broker API call, no order placement, no order cancellation, no order modification, and no auto-trade.
```

Normal DB payload build:

```text
python scripts/journal/build_dashboard_payload_from_db.py --asof 2026-06-02 --db data/journal/onejournal.duckdb --output output/dashboard/latest/dashboard_payload_from_db.json --write
```

DB payload contract check:

```text
python scripts/journal/check_db_dashboard_contract.py --asof 2026-06-02 --payload output/dashboard/latest/dashboard_payload_from_db.json
```

Save Review flow check:

```text
python scripts/journal/check_save_review_flow.py --asof 2026-06-02 --db data/journal/onejournal.duckdb
```

Streamlit launch:

```text
streamlit run src/onejournal/apps/streamlit_app.py
```

Operator rule: only DB payload is writable. CSV and Custom payloads are read-only in Phase F.

## Phase H0 ODFS Import CLI

Preferred ODFS-style journal import command:

```text
python scripts/journal/import_journal_to_db.py --asof 2026-06-02 --file docs/examples/manual_csv/fills_template.csv --reviews data/journal/reviews/manual_reviews.csv --db data/journal/onejournal.duckdb --replace
```

Compatibility command remains valid:

```text
python scripts/journal/import_journal_to_db.py --fills docs/examples/manual_csv/fills_template.csv --reviews data/journal/reviews/manual_reviews.csv --db data/journal/onejournal.duckdb --replace
```

`--file` is an ODFS alias for `--fills`. `--asof` validates imported fills and fails if fill dates do not match the requested as-of date.
## Phase I1 ODFS ingestion rule

CSV is allowed as the import and transport format only.

Raw broker exports belong under data/raw/.

Canonical normalized fill exports belong under data/normalized/fills/.

DuckDB normalized_fills, trade_episodes, trade_episode_legs, and manual_reviews are the journal source-of-truth tables.

Dashboard JSON under output/dashboard/ is generated output.

Do not build a broker-specific adapter that writes directly to Streamlit or dashboard JSON.
## Phase I3 ODFS folder rule

Raw broker files belong under data/raw/schwab, data/raw/ibkr, or data/raw/manual_imports.

Canonical normalized fills belong under data/normalized/fills when a CSV transport/export file is needed.

Do not edit raw broker exports in place.

Do not use raw broker CSV directly for dashboard, Streamlit review state, or trade_episodes.

Normalize first, validate, then import into DuckDB.
## Phase I5 operator import runbook

Use docs/operator_import_runbook.md for the safe import sequence.

The required sequence is raw evidence, normalized fills validation, DuckDB import, import audit check, DB dashboard build, dashboard contract check, then Streamlit review.

Do not use raw broker CSV directly for dashboard, Streamlit review state, or trade_episodes.
## Phase J0 Schwab execution boundary

Use docs/schwab_execution_boundary_contract.md as the rule for Schwab journal ingestion and future execution.

Current Schwab journal ingestion is read-only.

Future auto-trading must use order intents, risk gates, approval or policy checks, broker order execution, broker fill feedback, and normalized_fills journal import.

Journal scripts, dashboard scripts, and Streamlit review scripts must not call Schwab order-place, order-cancel, order-replace, or order-modify directly.
## Phase J1 Schwab adapter readiness audit

Use docs/schwab_adapter_readiness_audit.md before adding Schwab adapter code.

The first Schwab adapter should be file-based and should convert raw Schwab export CSV into canonical normalized fills CSV.

Do not build against guessed Schwab headers. Review a real Schwab export sample first.

The Schwab journal adapter must remain read-only and separate from future execution modules.
## Phase J2 Schwab legacy normalizer findings

Use docs/schwab_legacy_normalizer_findings.md before implementing Schwab parser logic.

Legacy Schwab findings confirm that security transferItems are fill-leg candidates, CURRENCY transferItems are not fill legs, raw transaction JSON should be preserved, and output must be canonical normalized fills.

The uploaded Schwab JSON transaction sample was empty, so a non-empty Schwab transaction JSON or CSV export is still required before adapter implementation.
