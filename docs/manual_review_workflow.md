# OneJournal Manual Review Workflow

## Purpose

This note explains the Phase B manual review workflow.

OneJournal is still an internal read-only prototype.

It does not place orders, cancel orders, replace orders, or auto-trade.

## Current Review File

Phase B review source of truth: DuckDB manual_reviews in data/journal/onejournal.duckdb.

Streamlit DB payload Save Review writes DuckDB manual_reviews. CSV manual_reviews.csv is legacy/backfill/export only.

## Review File Columns

episode_uid,review_status,setup_quality,entry_reason,notes

## Column Meaning

episode_uid must match the trade episode exactly.

Example: manual_csv:DEMO_ACCOUNT:option:AAPL 2026-07-17 180P

If the episode_uid does not match, the dashboard will not apply the review.

For multi-leg trades, episode_uid is built from the shared episode_group_id. This is why all legs of a vertical or spread must use the same episode_group_id.

review_status suggested values: unreviewed, reviewed, needs_review, mistake_review.

setup_quality suggested values: unknown, good, acceptable, poor, mistake.

entry_reason is a short reason for the trade.

notes is a free-text journal note.

## Supported Strategy Labels

Current prototype validates these strategy labels: Sell Put, Buy Call, Sell Call, Buy Put, Put Credit Vertical, Put Debit Vertical, Call Credit Vertical, Call Debit Vertical, Stock Long, Stock Short.

3-4 leg option trades are grouped safely as Multi-Leg Option until a more specific classifier is added.

## Current Flow

manual CSV fill -> NormalizedFill -> strategy classification -> TradeEpisodePreview -> DuckDB manual_reviews -> dashboard_payload_from_db.json -> Streamlit dashboard

## How to Update the Review Template

When new trade episodes appear in dashboard_payload.json, run:

python scripts/journal/update_review_template.py --asof 2026-06-02

This is a legacy/backfill helper for data/journal/reviews/manual_reviews.csv. It is not the normal Phase B review write path.

## How to Edit Reviews in Phase B

1. Start Streamlit.

2. Select the DB payload.

3. Use Save Review in Streamlit.

4. Save Review writes DuckDB manual_reviews.

5. Save Review rebuilds output/dashboard/latest/dashboard_payload_from_db.json.

6. Refresh the Streamlit dashboard if needed.

## Important Rules

Do not edit broker raw data to change journal notes.

Do not change episode_uid unless the trade episode itself changes.

Do not use this workflow for order placement.

Do not add broker credentials or tokens to this CSV.

## Future Direction

Phase B has replaced the normal editable CSV review workflow with DuckDB manual_reviews.

For now, CSV is enough because it is simple, visible, and easy to validate.

## DuckDB Phase B Check

Manual reviews are still stored in:

```text
data/journal/reviews/manual_reviews.csv
```

Use this command when a legacy CSV/backfill resync is needed and you want to confirm the DB payload still matches the migration payload:

```bash
python scripts/journal/refresh_dashboard_db_transition.py
```

The important line is:

```text
CSV_VS_DB_PAYLOAD_COMPARE=PASS
```

This is a migration safety check. The normal Phase B review write path is Streamlit DB payload Save Review -> DuckDB manual_reviews -> dashboard_payload_from_db.json.


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
