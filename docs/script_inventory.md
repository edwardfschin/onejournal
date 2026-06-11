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
## Phase J0 Schwab Execution Boundary

| Item | Phase | Keep/Review | Reason |
|---|---|---|---|
| docs/schwab_execution_boundary_contract.md | db_phase_j0_schwab_execution_boundary | KEEP | Defines journal-vs-execution boundary for Schwab ingestion and future auto-trading readiness. |
## Phase J1 Schwab Adapter Readiness Audit

| Item | Phase | Keep/Review | Reason |
|---|---|---|---|
| docs/schwab_adapter_readiness_audit.md | db_phase_j1_schwab_adapter_readiness | KEEP | Defines planned Schwab adapter shape before adapter code is added. |
## Phase J2 Schwab Legacy Normalizer Findings

| Item | Phase | Keep/Review | Reason |
|---|---|---|---|
| docs/schwab_legacy_normalizer_findings.md | db_phase_j2_schwab_legacy_findings | KEEP | Captures reusable Schwab normalization findings before parser implementation. |
## Phase J3 Schwab Orders JSON Schema Contract

| Item | Phase | Keep/Review | Reason |
|---|---|---|---|
| docs/schwab_orders_json_schema_contract.md | db_phase_j3_schwab_orders_schema | KEEP | Defines read-only Schwab orders JSON to normalized fills extraction rules. |

## Phase J4 Schwab Orders JSON Adapter

| Item | Phase | Keep/Review | Reason |
|---|---|---|---|
| src/onejournal/brokers/schwab/orders_json.py | db_phase_j4_schwab_orders_adapter | KEEP | Read-only Schwab orders JSON normalizer. |
| scripts/journal/convert_schwab_orders_json_to_normalized_fills.py | db_phase_j4_schwab_orders_adapter | KEEP | Operator CLI to write canonical normalized fills CSV from Schwab orders JSON. |
| docs/schwab_orders_json_adapter.md | db_phase_j4_schwab_orders_adapter | KEEP | Operator and design notes for the adapter. |

## Phase K1 ODFS Continuous Guard

| Item | Phase | Keep/Review | Reason |
|---|---|---|---|
| scripts/journal/check_odfs_continuity.py | db_phase_k1_odfs_continuous_guard | KEEP | Prevents ODFS folder and runtime/private file staging drift. |
| docs/odfs_continuous_guard.md | db_phase_k1_odfs_continuous_guard | KEEP | Documents continuous ODFS enforcement. |

## Phase L1 Schwab Transactions JSON Contract

| Item | Phase | Keep/Review | Reason |
|---|---|---|---|
| docs/schwab_transactions_json_contract.md | db_phase_l1_schwab_transactions_contract | KEEP | Defines accounting, fee, and transferItems evidence rules for Schwab transactions JSON. |

## Phase L2 Schwab Transactions JSON Adapter

| Item | Phase | Keep/Review | Reason |
|---|---|---|---|
| src/onejournal/brokers/schwab/transactions_json.py | db_phase_l2_schwab_transactions_adapter | KEEP | Read-only Schwab transactions transferItems normalizer. |
| scripts/journal/convert_schwab_transactions_json_to_normalized_fills.py | db_phase_l2_schwab_transactions_adapter | KEEP | Operator CLI to write canonical normalized fills CSV from Schwab transactions JSON. |
| docs/schwab_transactions_json_adapter.md | db_phase_l2_schwab_transactions_adapter | KEEP | Operator and design notes for the transactions adapter. |

## Phase L3 Schwab Orders Transactions Reconciliation

| Item | Phase | Keep/Review | Reason |
|---|---|---|---|
| scripts/journal/reconcile_schwab_orders_transactions.py | db_phase_l3_schwab_reconciliation | KEEP | Read-only reconciliation between Schwab execution truth and accounting truth. |
| docs/schwab_orders_transactions_reconciliation.md | db_phase_l3_schwab_reconciliation | KEEP | Documents Schwab orders vs transactions reconciliation. |

## Phase M1 Schwab Daily Reconciliation Operator

| Item | Phase | Keep/Review | Reason |
|---|---|---|---|
| scripts/journal/run_schwab_daily_reconciliation.py | db_phase_m1_schwab_daily_operator | KEEP | Runs safe daily Schwab conversion, validation, reconciliation, cleanup, and ODFS guard. |
| docs/schwab_daily_reconciliation_operator.md | db_phase_m1_schwab_daily_operator | KEEP | Documents the daily Schwab reconciliation operator command. |

## Phase M2 Schwab Guarded Daily Import Operator

| Item | Phase | Keep/Review | Reason |
|---|---|---|---|
| scripts/journal/run_schwab_daily_import.py | db_phase_m2_schwab_guarded_import | KEEP | Runs guarded Schwab daily flow and optional DuckDB import after strict reconciliation. |
| docs/schwab_daily_import_operator.md | db_phase_m2_schwab_guarded_import | KEEP | Documents the guarded Schwab daily import operator. |

## Phase M3 Schwab Import Idempotency Guard

| Item | Phase | Keep/Review | Reason |
|---|---|---|---|
| scripts/journal/check_schwab_daily_import_idempotency.py | db_phase_m3_schwab_idempotency | KEEP | Verifies rerunning the same Schwab import does not duplicate fills or episodes. |
| docs/schwab_daily_import_idempotency.md | db_phase_m3_schwab_idempotency | KEEP | Documents the Schwab import idempotency guard. |

