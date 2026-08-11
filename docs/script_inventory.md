# OneJournal Script Inventory

## Purpose and scope

This is the current, repository-wide inventory of executable material under
`scripts/`. It distinguishes active OneJournal operator/validation commands
from retained legacy TradersGPS/OneBot material. It is not a roadmap, and it
does not make a script production-approved merely because it is retained.

The inventory is based on the source code, current CI/baseline and Streamlit
call sites, operator documentation, and the full
[legacy-code audit](legacy_code_audit.md). Last reviewed: 2026-08-10.

Status meanings:

- **ACTIVE** — part of the present OneJournal validation or operator workflow.
- **LEGACY_BACKFILL** — retained only for prototype CSV/DB transition or
  historical recovery; not a future production-service design.
- **MAINTENANCE_EXPLICIT** — can change local journal data only with an
  explicit command flag and documented backup/recovery behaviour.
- **RETAIN_ISOLATED**, **MIGRATE**, **ARCHIVE** — legacy classifications from
  the legacy-code audit. They are not active OneJournal runtime paths.

No script in this inventory may place, cancel, replace, or modify broker orders
as part of an active OneJournal path. `scripts/execution/`,
`scripts/oldjournal/`, and `scripts/tgps_user/` are specifically excluded from
all active imports, UI actions, CI workflows, and operator commands.

## Active OneJournal scripts

| Path | Status | Role and side effects | Current authority/use |
|---|---|---|---|
| `scripts/ci/__init__.py` | ACTIVE | Package marker; no command entry point. | Supports the repository CI guard module. |
| `scripts/ci/check_repository.py` | ACTIVE | Read-only Git tracked-file and secret/artifact guard. | Run by `bin/onejournal_ci.sh`. |
| `scripts/journal/init_journal_db.py` | ACTIVE | Runs migration-aligned bootstrap/schema init for DuckDB and prints a read-only schema summary. | Local bootstrap only; versioned migrations are authoritative. |
| `scripts/journal/migrate_journal_db.py` | ACTIVE | Reads migration artifacts and applies ordered SQL migrations with ledger enforcement and checksum validation. | Supports explicit DB migration runs and failure-safe re-entry behavior. |
| `scripts/journal/import_journal_to_db.py` | ACTIVE | Atomically imports normalized/manual fills, canonical UTC evidence, optional lifecycle-event headers/legs, and reviews. `--replace` rebuilds prototype tables only while no approved lifecycle or P&L history exists; otherwise it fails closed to preserve lineage. | Controlled local import; not a production migration. |
| `scripts/journal/rebuild_pnl_allocations.py` | ACTIVE | Dry-runs by default; validates reviewed instructions against normalized events, legs, predecessor fills, UTC evidence, FIFO rules, and ADR-0004. `--apply` atomically appends approvals plus a fingerprinted/versioned P&L run. | PNL-01 local operator; no broker/order API and no normalized-evidence mutation. |
| `scripts/journal/build_dashboard_payload_from_db.py` | ACTIVE | Reads DuckDB and writes a dashboard JSON only with `--write`; accepts persisted P&L only when current fill and approved-event fingerprints match the run. | Current DB-backed Streamlit payload producer. |
| `scripts/journal/upsert_manual_review_to_db.py` | ACTIVE | Appends one validated `journal_reviews` event when migration 0005 exists and atomically updates the `manual_reviews` compatibility projection after checking the episode. | Current Streamlit Save Review target; retains projection-only compatibility before migration 0005. |
| `scripts/journal/upsert_journal_entry_to_db.py` | ACTIVE | Creates or appends a durable private journal-entry revision; reads body text from a file/stdin and never prints it. | Local UXJ-03 operator workflow after migration 0005; no broker or execution writes. |
| `scripts/journal/check_journal_db.py` | ACTIVE | Read-only DuckDB integrity, duplicate-key, lifecycle evidence, approved predecessor/source-leg, and P&L run/allocation linkage check. | Baseline/operator validation. |
| `scripts/journal/check_journal_reconciliation.py` | ACTIVE | Read-only cross-family reconciliation check for fills, transactions, positions, cash, accounts, and lifecycle evidence. A lifecycle event clears the blocker only through a current fingerprint-matched P&L run. | JRN-07/PNL-01 publication blocker gate in the Schwab import flow. |
| `scripts/journal/check_import_run_audit.py` | ACTIVE | Read-only import-run and normalized-record lineage check, including lifecycle event legs. | Baseline/operator validation. |
| `scripts/journal/show_import_status.py` | ACTIVE | Read-only journal/import/payload status report. | Baseline/operator diagnostics. |
| `scripts/journal/check_manual_fills.py` | ACTIVE | Read-only manual CSV parser and episode-preview check. | Clean CI validation. |
| `scripts/journal/check_normalized_fills_contract.py` | ACTIVE | Read-only normalized-fill schema, as-of, identity, asset, and option-field validation. | Clean CI and import gate. |
| `scripts/journal/check_odfs_continuity.py` | ACTIVE | Read-only ODFS directory and Git/runtime-artifact continuity guard. | Baseline and guarded-import validation. |
| `scripts/journal/check_trade_episodes.py` | ACTIVE | Read-only episode-preview validation. | Clean CI validation; previews are not lifecycle truth. |
| `scripts/journal/check_strategy_classification.py` | ACTIVE | Read-only dashboard strategy-label validation. | Prototype payload quality check. |
| `scripts/journal/check_episode_quality_contract.py` | ACTIVE | Read-only DB-payload episode quality check. | DB dashboard validation. |
| `scripts/journal/check_db_dashboard_contract.py` | ACTIVE | Read-only DB dashboard JSON contract validation. | DB dashboard validation. |
| `scripts/journal/check_save_review_flow.py` | ACTIVE | Copies the journal DB and writes only a temporary validation DB/payload. | Proves Save Review flow without changing the source DB. |
| `scripts/journal/check_dashboard_payload.py` | ACTIVE | Builds a prototype CSV payload; writes JSON only with `--write`. | Legacy CSV/backfill payload validation. |
| `scripts/journal/compare_dashboard_payloads.py` | ACTIVE | Read-only comparison of CSV and DB dashboard payloads. | Transition-validation diagnostic. |
| `scripts/journal/convert_schwab_orders_json_to_normalized_fills.py` | ACTIVE | Converts raw Schwab orders evidence to a normalized CSV output. | Read-only broker evidence transformation; output is generated. |
| `scripts/journal/convert_schwab_transactions_json_to_normalized_fills.py` | ACTIVE | Converts raw Schwab transaction evidence to a normalized fill CSV plus optional lifecycle-event header and transfer-item evidence CSVs. | Current canonical Schwab fill-source and lifecycle-evidence transformation after reconciliation. |
| `scripts/journal/reconcile_schwab_orders_transactions.py` | ACTIVE | Read-only daily comparison of normalized order and transaction fills. | Import gate; strict mode rejects unmatched evidence. |
| `scripts/journal/run_schwab_daily_reconciliation.py` | ACTIVE | Orchestrates conversion, validation, reconciliation, and generated-CSV cleanup; never writes DuckDB. | Safe daily reconciliation workflow. |
| `scripts/journal/run_schwab_daily_import.py` | ACTIVE | Orchestrates daily conversion/reconciliation; writes normalized fills, lifecycle event headers/legs, DuckDB, and validation payload with `--import-db`. | Guarded Schwab import workflow. |
| `scripts/liv/validate_pilot_config.py` | ACTIVE | Read-only LIV-02 pilot-config validator (allow-list, risk controls, schedule, and controls schema). | Prevents invalid pilot policy from being used in staged execution planning. |
| `scripts/liv/validate_intent_event.py` | ACTIVE | Read-only LIV-03 intent validator (intent schema, approval/risk consistency, enum checks). | Blocks invalid approval payloads from entering intent handoff. |
| `scripts/liv/validate_reconciliation_chain.py` | ACTIVE | Read-only LIV-04 reconciliation-chain validator for intents, orders, fills, and optional journal/cash/position traces. | Prevents orphan/floating fills and mismatch from passing stage-readiness checks. |
| `scripts/liv/validate_readiness.py` | ACTIVE | Read-only LIV-01 readiness evidence validator for legal/security/risk readiness proof. | Prevents promotion past blocked or placeholder evidence artifacts. |
| `scripts/liv/validate_expansion_governance.py` | ACTIVE | Read-only LIV-05 governance validator for queue decision/evidence files. | Prevents incomplete expansion evidence from being treated as approved. |
| `scripts/journal/find_and_run_schwab_daily_import.py` | ACTIVE | Locates raw files and invokes guarded daily import; fails on duplicate raw snapshots unless explicitly overridden. | Operator convenience command. |
| `scripts/journal/check_schwab_daily_import_idempotency.py` | ACTIVE | Copies DB and runs the guarded import twice against the copy. | Proves repeat import does not duplicate active rows. |
| `scripts/journal/backfill_schwab_history.py` | LEGACY_BACKFILL | Discovers historical raw orders/transactions, writes a backfill report, and imports only with `--import-db`. | Controlled recovery/backfill; duplicate snapshots fail unless explicitly selected. |
| `scripts/journal/fetch_schwab_raw_history.py` | ACTIVE | Uses Schwab read endpoints, persists raw JSON evidence, and refreshes only a OneJournal-scoped token when needed. `--dry-run` prevents network/file writes. | Credentialed read-only ingestion; generic and OneBot credential configuration are rejected. |
| `scripts/journal/plan_schwab_raw_history_backfill.py` | ACTIVE | Offline-only planner for bounded historical fetch windows and future GET estimates; no network, token, file-write, or DuckDB dependency. | Review/planning tool; it does not authorize a broker fetch. |
| `scripts/journal/fetch_schwab_raw_history_backfill.py` | ACTIVE | Sequential, resumable OneJournal-scoped raw JSON fetcher with protected-time control, token lock, and CSV audit report. | Guarded raw-evidence ingestion; a live run requires separate approval and never normalizes or writes DuckDB. |
| `scripts/journal/purge_demo_manual_data_from_db.py` | MAINTENANCE_EXPLICIT | Dry-runs by default; `--apply` backs up then deletes only identified demo manual rows. | Never run against a real journal without explicit approval. |
| `scripts/journal/refresh_dashboard.py` | LEGACY_BACKFILL | Rebuilds legacy CSV payload and manual-review CSV artifacts. | Prototype/backfill only; Streamlit does not write through this path. |
| `scripts/journal/update_review_template.py` | LEGACY_BACKFILL | Writes/updates the legacy manual-review CSV from a dashboard payload. | Prototype/backfill only; not read-only despite its old docstring. |
| `scripts/journal/refresh_dashboard_db_transition.py` | LEGACY_BACKFILL | Runs CSV-to-DB transition checks and writes prototype DB/output artifacts. | Migration-safety validation; not a normal operator command. |

`scripts/journal/migrations/README.md` is migration documentation, not an
executable script. `scripts/.DS_Store` is ignored operating-system metadata and
is not a project artifact.

## Phase-mapped script inventory references

- Phase F Guarded Review Workflow Scripts
- Phase B review compatibility projection: DuckDB manual_reviews; durable history after migration 0005: journal_reviews
- Phase M7 Schwab Duplicate Snapshot Guard
- Phase M6 Schwab Final Operator Runbook

## Reference matrix rule

Phase references and phase-specific operator runbooks rely on this file for discovery.
A script can be removed only after the reference matrix shows zero production, baseline, documentation, and migration-safety references.

## Contract and runbook references captured in this inventory

- `schwab_transactions_json_contract.md`
- `schwab_orders_json_schema_contract.md`
- `schwab_legacy_normalizer_findings.md`
- `schwab_adapter_readiness_audit.md`
- `schwab_execution_boundary_contract.md`
- `operator_import_runbook.md`
- `approved_lifecycle_pnl_operator.md`

## Isolated legacy and execution material

The following 36 retained artifacts are outside the active OneJournal runtime.
Their individual behavior, broker-write capability, dependencies, and
classification are authoritative in [legacy-code audit](legacy_code_audit.md).
They may not be called, imported, scheduled, or exposed by OneJournal.

| Directory | Files | Disposition |
|---|---:|---|
| `scripts/execution/` | 1 | `scripts/execution/stage_orders_v0.py` — RETAIN_ISOLATED; Excel/JSONL order staging with no active OneJournal route. |
| `scripts/oldjournal/` | 18 | `audit_trades.py`, `db_inspect.py`, `export_trx.py`, `fetch_orders_live.py`, `fetch_positions_live.py`, `ideas_runner.py`, `incremental_export.py`, `ingest_acct_activity.py`, `init_journal.sql`, `introspect_journal.py`, `journal_doctor.py`, `migrate_open_orders_lineage.py`, `oms_cli.py`, `positions_report.py`, `rebuild_db.py`, `report_open_orders_live.py`, `run_trading_session.sh`, `transactions_report.py` — individually classified MIGRATE, ARCHIVE, or RETAIN_ISOLATED. |
| `scripts/tgps_user/` | 17 | `_lock.py`, `actions_capture.py`, `doctor.py`, `exec_plan.py`, `fills_mgt.py`, `fills_normalize.py`, `ibkr_fills_mgt.py`, `ibkr_fills_normalize.py`, `ibkr_order_mgt.py`, `ibkr_sellput_queue.py`, `ideas_runner.py`, `init_ledger.py`, `order_mgt.py`, `policy_eval.py`, `queue_editor.py`, `sellput_day.py`, `sync_ideas.py` — individually classified MIGRATE, ARCHIVE, or RETAIN_ISOLATED. |

The legacy classification is a retention and safety boundary, not authorization
to reuse, relocate, run, delete, or connect those scripts to OneJournal.

## Inventory update rule

Before adding, moving, renaming, deprecating, or deleting any script:

1. Inspect the complete implementation, its callers, inputs, outputs, writes,
   dependencies, credentials, and operator documentation.
2. Update this inventory and any focused contract/runbook in the same change.
3. Classify data and broker side effects accurately; do not describe a
   write-capable command as read-only.
4. Add or update proportionate automated validation.
5. For legacy/execution material, update the legacy-code audit as well.

Deletion or relocation additionally requires the archive/deletion gate in the
legacy-code audit and explicit approval.
