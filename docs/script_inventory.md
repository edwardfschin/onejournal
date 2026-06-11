# OneJournal Script Inventory

This inventory prevents accidental deletion of scripts during Phase B cleanup.

Phase B source of truth: DuckDB manual_reviews.
Streamlit DB payload is the normal editable review path.
CSV review files are legacy/backfill/export only.

No script in this inventory may place, cancel, or modify broker orders.

| Script | Category | Status | Reason |
|---|---|---|---|
| build_dashboard_payload_from_db.py | db_phase_b | KEEP | Required by Streamlit Phase B DB review/dashboard path. |
| check_dashboard_payload.py | legacy_csv_backfill | KEEP | Legacy CSV/backfill/export workflow; not the normal Phase B review write path. |
| check_journal_db.py | production_check | KEEP | Validates DuckDB journal integrity. |
| check_import_run_audit.py | db_phase_i_import_audit | KEEP | Baseline guard for import_runs and normalized_fills audit linkage. |
| check_manual_fills.py | baseline_data_quality | KEEP | Used by baseline to validate parser, classification, and episode construction. |
| check_normalized_fills_contract.py | db_phase_i_normalized_fills_validation | KEEP | Baseline guard for canonical normalized fills CSV contract. |
| check_strategy_classification.py | baseline_data_quality | KEEP | Used by baseline to validate parser, classification, and episode construction. |
| check_trade_episodes.py | baseline_data_quality | KEEP | Used by baseline to validate parser, classification, and episode construction. |
| check_episode_quality_contract.py | db_phase_h_episode_quality | KEEP | Baseline guard for dashboard episode quality contract. |
| compare_dashboard_payloads.py | migration_safety | KEEP | Used to verify legacy CSV/backfill and DB payload equivalence during migration. |
| import_journal_to_db.py | db_bootstrap_backfill | KEEP | Required to initialize or backfill DuckDB from source files. |
| init_journal_db.py | db_bootstrap_backfill | KEEP | Required to initialize or backfill DuckDB from source files. |
| refresh_dashboard.py | legacy_csv_backfill | KEEP | Legacy CSV/backfill/export workflow; not the normal Phase B review write path. |
| refresh_dashboard_db_transition.py | migration_safety | KEEP | Used to verify legacy CSV/backfill and DB payload equivalence during migration. |
| update_review_template.py | legacy_csv_backfill | KEEP | Legacy CSV/backfill/export workflow; not the normal Phase B review write path. |
| upsert_manual_review_to_db.py | db_phase_b | KEEP | Required by Streamlit Phase B DB review/dashboard path. |

## Removal Rule

A script can be removed only after the reference matrix shows zero production, baseline, documentation, and migration-safety references, and after this inventory is updated first.

## Phase F Guarded Review Workflow Scripts

| Script | Category | Status | Reason |
|---|---|---:|---|
| check_db_dashboard_contract.py | db_phase_c_contract | KEEP | Baseline guard for dashboard_payload_from_db.json schema and DB payload source. |
| check_save_review_flow.py | db_phase_d_save_flow | KEEP | Baseline guard proving Save Review -> DuckDB manual_reviews -> DB payload rebuild on a temporary DB copy. |
| src/onejournal/apps/streamlit_app.py | operator_ui | KEEP | Normal operator UI. DB payload is writable; CSV and Custom payloads are read-only. |

Removal rule: none of these can be removed unless the reference matrix and baseline are updated in the same commit.
## Phase I5 Operator Import Runbook

| Item | Phase | Keep/Review | Reason |
|---|---|---|---|
| docs/operator_import_runbook.md | db_phase_i_operator_import | KEEP | Defines safe ODFS import sequence before broker-specific adapters. |

