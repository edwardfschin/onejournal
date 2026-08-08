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
  quality
    - overall_status
    - checks
    - checks.import
    - checks.asof
    - checks.pnl
    - trade_summary_status
recent_trade_episodes
```

metadata must contain:

```text
asof
source
```

source must identify the DB/DuckDB path.

Valid status values are:

`valid`, `stale`, `incomplete`, `reconciliation_pending`, `unavailable`, `failed`.

`overall_status` starts as the most restrictive result across import health, as-of coverage, and P&L completeness.

- `valid`: accepted import status and requested as-of slice is present for required metrics.
- `stale`: requested as-of is newer than latest fill as-of.
- `incomplete`: required requested as-of rows are missing or unmatched close fills were skipped.
- `failed`: latest import status is not `ok`, `success`, or `completed`.

`trade_summary_status` maps per metric status using the same value vocabulary.

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
