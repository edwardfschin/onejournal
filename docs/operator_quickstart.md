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
