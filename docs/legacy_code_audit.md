# OneJournal Legacy Code Audit

## Decision

The 36 tracked artifacts under `scripts/oldjournal/`, `scripts/tgps_user/`, and
`scripts/execution/` are not part of the active OneJournal runtime.

No legacy artifact is approved for direct reuse, import, broker access, database
access, migration, execution, deletion, or relocation. This audit classifies
the retained source and identifies concepts that may be reimplemented later
behind current OneJournal contracts.

## Scope and evidence

The audit inspected:

- all 18 files under `scripts/oldjournal/`
- all 17 files under `scripts/tgps_user/`
- `scripts/execution/stage_orders_v0.py`
- imports, CLI entry points, subprocess calls, HTTP/broker calls, database
  connections, SQL mutations, file writes, destructive flags, and documented
  defaults
- repository references outside the audited paths
- current dependency and directory availability
- syntax compilation for every audited Python file

Verified findings:

- No active OneJournal source, test, baseline, CI, or operator script imports or
  invokes an audited artifact.
- The only repository references outside the audited trees are the operating
  safety rule and the roadmap audit action.
- Expected top-level `client/`, `common/`, and `tgps-user/` directories are
  absent from this repository.
- `openpyxl`, `xlsxwriter`, `yahooquery`, `ibapi`, `client`, and `common` are
  unavailable in the reproducible OneJournal environment. `pandas` is present
  transitively, but the legacy applications and their complete dependencies are
  not declared OneJournal dependencies.
- All audited Python files compile syntactically without importing or executing
  them.
- Legacy defaults target TradersGPS paths, schemas, tokens, workbooks, and
  databases rather than OneJournal ODFS contracts.
- External schedulers, aliases, deployment copies, or operator habits cannot be
  proven absent from this repository alone. That prevents a safe deletion
  classification.

## Classification meanings

- `MIGRATE` — the requirement or algorithm is relevant to a future roadmap
  item. Reimplement it from evidence under OneJournal contracts and tests; do
  not copy or activate the legacy module.
- `RETAIN_ISOLATED` — the artifact has broker-write, credential, streaming, or
  execution-orchestration capability. Keep it outside active imports and
  operator paths until an approved execution architecture exists.
- `ARCHIVE` — the artifact targets a superseded schema or workflow and has no
  active repository reference. Preserve it as historical evidence until
  external-use checks and explicit archive approval are complete.
- `DELETE` — safe removal has been proven across static, runtime, operator, and
  deployment references. No artifact currently meets this standard.

These labels authorize no file operation by themselves.

## Critical safety findings

Broker-mutating capability exists in retained legacy source:

- `scripts/oldjournal/oms_cli.py` can place, replace, and cancel Schwab orders
  when `--submit` is supplied.
- `scripts/oldjournal/ideas_runner.py` can append `--submit` and invoke the OMS
  through `shell=True`.
- `scripts/tgps_user/exec_plan.py` has a submit mode that places Schwab orders
  and permits a dangerous deduplication bypass through `--force`.
- `scripts/tgps_user/order_mgt.py` can cancel and replace Schwab orders with
  `--submit`.
- `scripts/tgps_user/ibkr_order_mgt.py` directly calls the IBKR cancellation
  API.
- `scripts/tgps_user/ibkr_sellput_queue.py` can cancel and place IBKR orders;
  live mode has an additional acknowledgement flag but remains legacy
  execution code.
- `scripts/tgps_user/sellput_day.py` exposes a submit command that orchestrates
  the execution planner.

Other material side effects include destructive schema reset, database
overwrite, cache replacement, raw/history table mutation, workbook mutation,
network quote/history calls, token refresh, streaming processes, and removal of
temporary capture files.

None of these paths may be imported by `src/onejournal`, called by the
Streamlit application, added to the journal pipeline, or exposed through a
future website.

## `scripts/oldjournal/` classification

| Artifact | Classification | Observed behavior and reason |
|---|---|---|
| `audit_trades.py` | MIGRATE | Read-oriented checks for coverage, duplicates, nulls, and option fields in legacy `journal.trades`. Recreate integrity concepts against versioned OneJournal tables. |
| `db_inspect.py` | MIGRATE | Schema, count, time-range, and uniqueness diagnostics for legacy transaction views. Generic diagnostic behavior is useful; relation names are obsolete. |
| `export_trx.py` | ARCHIVE | Calls Schwab transaction endpoints, refreshes tokens, writes raw files, and mutates legacy raw/item/run-log tables. Current raw fetch and normalized adapters supersede this path. |
| `fetch_orders_live.py` | ARCHIVE | Calls Schwab order/account endpoints and replaces legacy live-order/account tables while appending raw and snapshot data. Current ODFS raw-history and adapter flow supersede it. |
| `fetch_positions_live.py` | MIGRATE | Calls the Schwab positions endpoint and replaces legacy account/position tables. Position ingestion remains a roadmap requirement, but this implementation bypasses OneJournal normalized contracts. |
| `ideas_runner.py` | RETAIN_ISOLATED | Reads and rewrites Excel, generates OMS commands, and can execute Schwab submissions indirectly with `--execute`. |
| `incremental_export.py` | ARCHIVE | Resumes/chunks legacy Schwab transaction export through subprocesses and old schemas. Current history fetch/backfill boundaries supersede it. |
| `ingest_acct_activity.py` | ARCHIVE | Auto-migrates and inserts streamer NDJSON into a legacy raw table. Streaming is not journal truth and no active producer exists here. |
| `init_journal.sql` | ARCHIVE | Bootstraps the superseded TradersGPS `journal.*` schema and installs DuckDB JSON support. It is incompatible with OneJournal migrations and tables. |
| `introspect_journal.py` | MIGRATE | Read-oriented DuckDB schema, constraint, relationship, and index inspection. Reimplement as a version-aware OneJournal diagnostic. |
| `journal_doctor.py` | ARCHIVE | Orchestrates legacy inspector/audit modules using module paths that no longer exist in this repository. |
| `migrate_open_orders_lineage.py` | ARCHIVE | Alters and backfills legacy live-order tables directly without OneJournal migration/version/rollback controls. |
| `oms_cli.py` | RETAIN_ISOLATED | Full Schwab OMS with list, place, bracket, trigger-OCO, cancel, and replace operations; `--submit` activates broker writes. |
| `positions_report.py` | MIGRATE | Builds a positions workbook from legacy snapshots and Yahoo earnings. Preserve reporting requirements, but reject placeholder daily P&L and unapproved Yahoo/fallback policy. |
| `rebuild_db.py` | ARCHIVE | Copies a legacy DuckDB into a new database and can unlink the destination with `--overwrite`. Not a OneJournal migration or backup mechanism. |
| `report_open_orders_live.py` | RETAIN_ISOLATED | Generates operational open-order workbooks from legacy raw/live/snapshot tables. Relevant only to a future isolated execution plane. |
| `run_trading_session.sh` | RETAIN_ISOLATED | Long-running Schwab token preflight, order polling, streaming, file rotation, ingestion, process killing, and cleanup against TradersGPS paths. |
| `transactions_report.py` | MIGRATE | Generates accounting/reconciliation workbooks from legacy views. Preserve report and reconciliation concepts; do not reuse its best-effort average-cost engine. |

## `scripts/tgps_user/` classification

| Artifact | Classification | Observed behavior and reason |
|---|---|---|
| `_lock.py` | MIGRATE | Single-writer file lock with owner metadata and stale-lock handling. The concurrency requirement is useful, but paths and failure policy must be redesigned for OneJournal. |
| `actions_capture.py` | RETAIN_ISOLATED | Validates execution workbooks, optionally reads Schwab quotes, writes/purges ledger actions, and feeds the submit pipeline. |
| `doctor.py` | ARCHIVE | Health-checks a missing `tgps-user` configuration, ledger, policies, cloud sources, and legacy tables. |
| `exec_plan.py` | RETAIN_ISOLATED | Builds and submits Schwab orders, records submissions, performs deduplication, and exposes `--force`. This is broker-write execution code. |
| `fills_mgt.py` | MIGRATE | Reads Schwab transactions, accounts, balances, and positions and mutates legacy caches. Reimplement source-specific ingestion into immutable raw evidence and normalized contracts. |
| `fills_normalize.py` | MIGRATE | Converts Schwab transaction legs into shared OMS fills, allocates transaction fees, and optionally updates order status. Preserve evidence, but redesign accounting and linkage contracts first. |
| `ibkr_fills_mgt.py` | MIGRATE | Reads IBKR executions/commissions through TWS/Gateway into legacy generic cache tables. Useful evidence for a future read-only IBKR adapter. |
| `ibkr_fills_normalize.py` | MIGRATE | Normalizes cached IBKR executions and updates legacy submissions. Reimplement against approved OneJournal identities and lifecycle rules. |
| `ibkr_order_mgt.py` | RETAIN_ISOLATED | Pulls IBKR open orders, writes cache tables, and directly cancels orders by ID. |
| `ibkr_sellput_queue.py` | RETAIN_ISOLATED | Plans, cancels, replaces, and places IBKR sell-put/bracket orders with ledger mutation and paper/live configuration. |
| `ideas_runner.py` | ARCHIVE | Applies TradersGPS policy to cloud Excel and writes system queues plus policy ledger state. It is product-specific and not a journal responsibility. |
| `init_ledger.py` | ARCHIVE | Creates/migrates the separate `tgps-user` ledger and can drop the complete schema through `--reset`. |
| `order_mgt.py` | RETAIN_ISOLATED | Syncs Schwab orders and can cancel or replace them with `--submit`; also mutates legacy order/submission state. |
| `policy_eval.py` | ARCHIVE | Evaluates TradersGPS strategy policy against cloud Excel and creates workbooks. It is not part of the OneJournal journal domain. |
| `queue_editor.py` | ARCHIVE | Creates execution queue workbooks using missing shared key helpers and legacy ledger status. Retain only as workflow evidence. |
| `sellput_day.py` | RETAIN_ISOLATED | Orchestrates the complete TradersGPS preparation, action-import, plan, and submit pipeline. |
| `sync_ideas.py` | ARCHIVE | Imports cloud strategy ideas into a separate legacy ledger with snapshot/upsert state. It is unrelated to canonical broker evidence. |

## `scripts/execution/` classification

| Artifact | Classification | Observed behavior and reason |
|---|---|---|
| `stage_orders_v0.py` | RETAIN_ISOLATED | Dry-run Schwab order staging that mutates an Excel workbook and writes JSONL audit output. It has kill-switch and limit concepts, but depends on unapproved execution configuration and an unwired option-cache lookup. |

## Migration constraints

For every `MIGRATE` item:

1. Start from the approved OneJournal contract and representative raw evidence.
2. Extract only the requirement or algorithm proven useful.
3. Implement reusable code under `src/onejournal/`.
4. Keep broker-specific parsing inside the relevant adapter.
5. Use temporary databases and synthetic/private-safe fixtures.
6. Add focused unit, integration, contract, idempotency, and reconciliation
   tests.
7. Prove lineage, failure behavior, rollback, and downstream compatibility.
8. Do not import a legacy module as an implementation shortcut.

For every `RETAIN_ISOLATED` item:

- no active imports, aliases, scheduled jobs, UI buttons, API routes, or
  subprocess calls may be added
- no credentials or broker sessions may be provided from OneJournal
- no paper or live broker connection is authorized
- future evaluation requires an approved execution-plane architecture and
  trading-safety review

## Archive and deletion gate

Archiving or deleting any artifact requires:

- repository and Git-history reference review
- shell alias, scheduler, launch agent, deployment, VPS, and operator-runbook
  review
- confirmation that no external repository imports or copies it
- preservation of any unique contract or representative behavior
- explicit approval for the file operation

No deletion is recommended by this audit.
