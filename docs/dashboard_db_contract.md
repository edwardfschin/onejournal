# OneJournal Dashboard DB Contract

Phase C locks the normal dashboard review path to DuckDB.

## Source of Truth

DuckDB table:

```text
data/journal/onejournal.duckdb :: manual_reviews
```

## Published Payload

Normal Streamlit DB payload:

```text
output/dashboard/latest/dashboard_payload_from_db.json
```

## Required Payload Shape

The DB dashboard payload must contain:

```text
metadata
recent_trade_episodes
```

metadata must contain:

```text
asof
source
```

source must identify the DB/DuckDB path.

Each dashboard entry must contain:

```text
episode_uid
review_status
setup_quality
entry_reason
notes
```

## Save Review Contract

Streamlit DB payload Save Review must follow this flow:

```text
Streamlit Save Review
-> scripts/journal/upsert_manual_review_to_db.py
-> DuckDB manual_reviews
-> scripts/journal/build_dashboard_payload_from_db.py
-> output/dashboard/latest/dashboard_payload_from_db.json
```

## Legacy Boundary

CSV payloads and manual_reviews.csv are legacy/backfill/export only.

Streamlit must not call:

```text
scripts/journal/refresh_dashboard.py
scripts/journal/update_review_template.py
```

Streamlit must not write:

```text
data/journal/reviews/manual_reviews.csv
```

## Validation

Run:

```text
python scripts/journal/check_db_dashboard_contract.py --asof 2026-06-02 --payload output/dashboard/latest/dashboard_payload_from_db.json
```

The baseline also runs this checker through:

```text
./bin/onejournal_check.sh
```
