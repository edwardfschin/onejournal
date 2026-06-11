# OneJournal Save Review Flow

Phase D proves the operator Save Review workflow end to end without touching broker APIs and without writing to production DuckDB during validation.

## Source of Truth

```text
data/journal/onejournal.duckdb :: manual_reviews
```

## Save Review Runtime Flow

```text
Streamlit DB payload
-> Save Review form
-> scripts/journal/upsert_manual_review_to_db.py
-> DuckDB manual_reviews
-> scripts/journal/build_dashboard_payload_from_db.py
-> output/dashboard/latest/dashboard_payload_from_db.json
```

## Validation Method

The Phase D checker copies the production DuckDB file to a temporary validation DB:

```text
output/validation/save_review_flow/onejournal_save_review_flow.duckdb
```

It then:

```text
1. Finds one existing trade_episodes.episode_uid in the temp DB.
2. Runs upsert_manual_review_to_db.py against the temp DB only.
3. Confirms manual_reviews contains the saved review.
4. Rebuilds a temp DB dashboard payload from the temp DB only.
5. Confirms recent_trade_episodes contains the saved review fields.
```

## Safety Contract

```text
No broker API call.
No order placement.
No order cancel.
No order modification.
No production DB write during validation.
```

## Command

```text
python scripts/journal/check_save_review_flow.py --asof 2026-06-02 --db data/journal/onejournal.duckdb
```

The baseline also runs this checker through:

```text
./bin/onejournal_check.sh
```
