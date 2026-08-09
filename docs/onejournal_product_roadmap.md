# OneJournal Product Roadmap and Action Queue

## Purpose

This document is the product-level source of truth for moving OneJournal from
its current internal prototype to a production journaling, portfolio, P&L, and
eventually controlled trading platform.

Detailed data contracts and operator runbooks remain authoritative for their
specific workflows. This roadmap controls priority and sequencing; it does not
override the current read-only trading safety boundary.

## Product objective

OneJournal will provide:

1. A reliable trading journal with structured and narrative review workflows.
2. A traceable portfolio view built from broker-confirmed activity.
3. Correct realized and unrealized P&L and performance reporting.
4. A sleek, beautiful, responsive, accessible production website.
5. A broker-independent foundation that can support multiple accounts and
   brokers.
6. A separately controlled paper-trading and, only after explicit approval,
   live-execution plane.

## Current verified baseline

The repository already has:

- ODFS folders, contracts, and a continuity guard.
- Broker-independent normalized record models.
- Manual CSV and Schwab orders/transactions normalization.
- Schwab reconciliation, guarded import, audit, and idempotency tooling.
- DuckDB journal tables for imports, fills, episodes, legs, and reviews.
- A basic trade-episode classifier and manual review workflow.
- A local Streamlit prototype backed by generated dashboard payloads.
- A documented read-only boundary between journal and future execution planes.
- Reproducible locked dependencies, automated tests, and a local clean-CI
  workflow.

The repository does not yet have:

- A complete trade-lifecycle engine.
- Trustworthy realized and unrealized P&L.
- Current position, valuation, market-data, or portfolio-history pipelines.
- Production web architecture, authentication, or deployment.
- Hosted-CI execution evidence from the GitHub workflow.
- Paper or live trading within the OneJournal architecture.

## Queue rules

- Work in queue order unless an explicitly approved dependency or urgent defect
  requires reprioritization.
- Prefer a simple, creative, high-performance foundation with safe defaults,
  clear guardrails, actionable failures, and measured optimization.
- Only one material implementation item should be in progress at a time.
- Every item requires acceptance criteria and validation before completion.
- Financial and data-contract work precedes presentation work that depends on it.
- Generated artifacts are fixed through their producers, not patched directly.
- Paper and live execution remain blocked until their entry gates are satisfied.

Queue status values:

- `NEXT` - the next approved item to execute.
- `QUEUED` - ready after its dependencies are complete.
- `BLOCKED` - depends on a decision or unfinished prerequisite.
- `LATER` - intentionally outside the near-term delivery path.
- `COMPLETE` - implemented and validated.

## Queue 0 - Make the foundation truthful and reproducible

Objective: establish a reliable development baseline before adding financial or
website features.

| ID | Status | Action | Completion evidence |
|---|---|---|---|
| FND-01 | COMPLETE | Add the approved OneJournal operating instructions to the repository-level agent guidance. | Instructions are versioned, reviewed, and discoverable from the repository root. |
| FND-02 | COMPLETE | Repair the baseline checker so every command is executed, every error increments failure state, and PASS cannot follow an uncounted error. | A deliberately failing check produces a non-zero exit; the repaired full baseline passes. |
| FND-03 | COMPLETE | Declare all runtime and development dependencies and define a reproducible clean-environment setup. | A clean environment can install OneJournal and run its checks from documented commands. |
| FND-04 | COMPLETE | Establish automated unit, integration, contract, and regression test structure. | Tests run through one documented command and include initial DB, payload, adapter, and lifecycle coverage. |
| FND-05 | COMPLETE | Activate the committed GitHub workflow for package installation, tests, contract checks, and secret/runtime-artifact guards. | The pushed branch runs the workflow successfully without private broker data; PR 1 run 6 passed. |
| FND-06 | COMPLETE | Replace the stale Phase 0 README with the current architecture, setup, safety boundary, and roadmap link. | README matches the verified repository and points to current operator documentation. |
| FND-07 | COMPLETE | Audit and classify `scripts/oldjournal`, `scripts/tgps_user`, and execution-related legacy code. | Each legacy path is marked migrate, retain-isolated, archive, or delete with evidence. |
| FND-08 | COMPLETE | Define architecture-decision-record and schema-migration conventions. | A documented template and storage location exist and one initial decision is recorded. |

### Queue 0 exit gate

- Baseline checks fail truthfully.
- A clean environment is reproducible.
- Automated tests and CI run successfully.
- Current documentation describes the actual system.
- Legacy execution-capable code is clearly isolated from the journal path.

## Queue 1 - Lock product and financial contracts

Objective: decide the semantics required for correct portfolio and P&L work.

| ID | Status | Action | Completion evidence |
|---|---|---|---|
| CON-01 | COMPLETE | Decide initial product scope: single user or multi-user, supported brokers, accounts, asset classes, and first production use case. | Approved product-scope decision record. |
| CON-02 | COMPLETE | Define base currency, multi-currency policy, decimal precision, timezone, market-date, and trading-session rules. | Approved financial-units and time contract with examples. |
| CON-03 | COMPLETE | Define realized P&L, unrealized P&L, cost basis, tax-lot policy, fees, commissions, and return calculations. | ADR-0004 plus FIFO lot engine and fail-closed contract tests in `src/onejournal/pnl/` plus mark-sourcing behavior tests. DB-backed payload now includes realized/unrealized P&L by currency. |
| CON-04 | COMPLETE | Define lifecycle treatment for partial fills, partial exits, and multi-leg trade matching by episode scope. | Lifecycle and preview contract tests are in place; complex lifecycle event types remain blocked under ADR-0005. |
| CON-05 | COMPLETE | Define stable identifiers, deduplication, idempotency, lineage, corrections, and data-version rules. | Stable fill identity, idempotent replay, and identity-conflict rejection are enforced and tested. |
| CON-06 | COMPLETE | Define data freshness, stale-price, missing-data, reconciliation, and fail-closed presentation policies. | DB payload now carries quality status for import/audit/completeness and fail-closed policy status checks. |

### Queue 1 exit gate

- No core financial metric depends on an unresolved accounting assumption.
- Time, currency, identity, and lifecycle semantics have approved examples.
- Incomplete or conflicting broker evidence has an explicit failure policy.

## Queue 2 - Build the canonical journal and trade-lifecycle engine

Objective: turn normalized broker activity into durable, correct trade and
position state.

| ID | Status | Action | Completion evidence |
|---|---|---|---|
| JRN-01 | COMPLETE | Version and migrate the DuckDB schema using the approved migration convention. | Migration ledger, baseline tables, schema checks, and contract tests are in place. |
| JRN-02 | COMPLETE | Persist normalized accounts, orders, positions, transactions, and required source lineage—not only fills. | Normalized family derivation, import-run linkage checks, and contract coverage now exercise all families. |
| JRN-03 | COMPLETE | Replace preview grouping with a deterministic trade-lifecycle engine. | Entry/exit/partial/reopen fixtures and deterministic lifecycle tests are implemented and merge-validated. |
| JRN-04 | COMPLETE | Add multi-leg lifecycle handling for verticals and later approved strategies. | Preview-level and lifecycle-contract fixtures for multi-leg and cross-symbol matching using explicit episode-group scope are in place. |
| JRN-05 | BLOCKED | Add assignments, exercises, expirations, rolls, transfers, dividends, and corporate-action handling. | ADR-0005 remains open; lifecycle extraction fixtures are implemented and waiting for event-ledger migration approval. |
| JRN-06 | COMPLETE | Add correction/replay support without losing audit history or manual reviews. | Replay-safe replace imports are implemented with manual-review preservation and signed revision rows. |
| JRN-07 | COMPLETE | Strengthen broker-to-journal reconciliation at fill, transaction, position, cash, and account levels. | Fill/transaction/position/cash/account checks are classified and policy-gated before publication. |

### Queue 2 exit gate

- Trade episodes represent complete lifecycles rather than previews.
- Broker evidence can be replayed without duplicates or lost reviews.
- Positions and cash reconcile within the approved policy.

## Queue 3 - Implement P&L, portfolio, and reporting

Objective: produce traceable financial results before building the production
presentation layer.

| ID | Status | Action | Completion evidence |
|---|---|---|---|
| PNL-01 | BLOCKED | Implement realized P&L from closed lifecycle allocations. | Worked examples match expected results including fees and multipliers. |
| PNL-02 | BLOCKED | Select a market-data provider and define quote ingestion, storage, licensing, and freshness. | Approved provider decision and validated read-only quote pipeline. |
| PNL-03 | BLOCKED | Implement current positions, cost basis, market value, and unrealized P&L. | Position totals reconcile to broker snapshots under the approved policy. |
| PNL-04 | BLOCKED | Build account and consolidated portfolio snapshots over time. | Historical snapshots are reproducible by as-of date. |
| PNL-05 | BLOCKED | Implement performance metrics: total P&L, returns, win rate, profit factor, average win/loss, holding period, drawdown, and exposure. | Every metric has a definition, unit tests, and source lineage. |
| PNL-06 | BLOCKED | Implement breakdowns by account, broker, strategy, symbol, asset class, and time period. | Aggregations reconcile to portfolio totals. |
| PNL-07 | BLOCKED | Build daily, monthly, and custom-period reports and exports. | Reports reconcile to canonical calculations and identify their as-of state. |
| PNL-08 | BLOCKED | Add data-quality and stale-data indicators to every published financial payload. | Missing or stale evidence cannot appear as a silently valid number. |

### Queue 3 exit gate

- Realized and unrealized P&L reconcile to approved examples and broker evidence.
- Portfolio totals and all breakdowns reconcile.
- Every displayed metric is traceable, dated, and freshness-aware.

## Queue 4 - Complete the journaling product

Objective: provide the workflows needed to learn from trading activity.

| ID | Status | Action | Completion evidence |
|---|---|---|---|
| UXJ-01 | BLOCKED | Define the journal-entry, review, tag, strategy, mistake, lesson, and attachment model. | Approved schema and representative journal examples. |
| UXJ-02 | BLOCKED | Build review queues for unreviewed, incomplete, risk-flagged, and mistake trades. | Queue membership is deterministic and traceable. |
| UXJ-03 | BLOCKED | Add structured pre-trade plan, entry thesis, execution review, exit review, and post-trade reflection. | Entries survive lifecycle rebuilds and maintain history. |
| UXJ-04 | BLOCKED | Add search, filters, saved views, and navigation by date, strategy, symbol, account, and review state. | Usability tests cover primary review journeys. |
| UXJ-05 | BLOCKED | Add charts, screenshots, notes, and evidence attachments with privacy and retention controls. | Attachments are authorized, traceable, and excluded from public output. |
| UXJ-06 | BLOCKED | Add goal, habit, and recurring review workflows only after the core trade journal is stable. | Weekly/monthly review workflows use canonical portfolio metrics. |

### Queue 4 exit gate

- A user can find, review, annotate, and learn from any imported trade.
- Journal content is durable, searchable, private, and linked to canonical data.

## Queue 5 - Design and build the production website

Objective: replace the internal Streamlit presentation with a production-grade
web experience while retaining Streamlit as a temporary validation tool until
the new website reaches parity.

| ID | Status | Action | Completion evidence |
|---|---|---|---|
| WEB-01 | BLOCKED | Decide frontend, backend/API, database evolution, background-job, and hosting architecture. | Approved architecture decision with security, cost, and migration trade-offs. |
| WEB-02 | BLOCKED | Define information architecture and priority user journeys. | Approved sitemap and flows for dashboard, portfolio, trades, journal, reports, and settings. |
| WEB-03 | BLOCKED | Create the OneJournal visual design system. | Approved typography, colour, spacing, components, charts, states, and responsive rules. |
| WEB-04 | BLOCKED | Design high-fidelity responsive screens and validate them before full implementation. | Desktop, tablet, and mobile designs cover loading, empty, stale, and error states. |
| WEB-05 | BLOCKED | Build the application/API layer so the frontend never reads raw broker data or DuckDB files directly. | Versioned API contracts and authorization tests pass. |
| WEB-06 | BLOCKED | Implement authentication, authorization, secure sessions, account recovery, and audit logging. | Security review and negative authorization tests pass. |
| WEB-07 | BLOCKED | Implement portfolio, P&L, trade, journal, report, and settings experiences. | Production UI reaches approved functional parity and visual QA. |
| WEB-08 | BLOCKED | Add accessibility, performance, browser, device, and end-to-end testing. | Agreed accessibility and performance targets pass in supported browsers. |
| WEB-09 | BLOCKED | Migrate operator workflows away from Streamlit only after verified parity. | Production website is authoritative; Streamlit retirement/retention is documented. |

### Queue 5 exit gate

- The production website is secure, responsive, accessible, and visually approved.
- It consumes versioned application contracts rather than raw files.
- Financial and journal flows match canonical backend results.

## Queue 6 - Production operations and resilience

Objective: make the website and journal safe to operate continuously.

| ID | Status | Action | Completion evidence |
|---|---|---|---|
| OPS-01 | BLOCKED | Define development, test, staging, paper, and production environment boundaries. | Environments use separate configuration, credentials, data, and visible identity. |
| OPS-02 | BLOCKED | Implement versioned deployment and rollback automation. | A staging release and rollback are successfully rehearsed. |
| OPS-03 | BLOCKED | Implement encrypted backups and tested restoration for databases and journal attachments. | Recovery drill meets the approved recovery objectives. |
| OPS-04 | BLOCKED | Add structured logs, metrics, traces, run IDs, dashboards, and actionable alerts. | Failures can be detected and traced without exposing private data. |
| OPS-05 | BLOCKED | Define availability, performance, retention, incident-response, and disaster-recovery policies. | Approved operating policies and tested incident runbooks. |
| OPS-06 | BLOCKED | Complete privacy, security, dependency, secret, and threat-model reviews. | Critical findings are resolved before production launch. |
| OPS-07 | BLOCKED | Define data export, correction, deletion, and account closure procedures. | Procedures preserve audit requirements and meet approved privacy policy. |

### Queue 6 exit gate

- Production can be monitored, backed up, restored, rolled back, and supported.
- Private financial information is protected through tested controls.

## Queue 7 - Paper-trading execution plane

Objective: prove execution architecture without risking live capital.

| ID | Status | Action | Completion evidence |
|---|---|---|---|
| PAP-01 | LATER | Approve the isolated execution-plane architecture and broker abstraction. | Journal and website code cannot bypass the execution boundary. |
| PAP-02 | LATER | Implement durable order intents and lifecycle state transitions. | Intents are idempotent, auditable, and replay-safe. |
| PAP-03 | LATER | Implement the risk engine and configurable account, symbol, strategy, quantity, notional, loss, and market-hours limits. | Every rejected or approved intent has recorded evidence. |
| PAP-04 | LATER | Implement approval policies, emergency disable controls, and kill switches. | Tests prove all broker writes stop when disabled. |
| PAP-05 | LATER | Implement a deterministic paper broker or approved broker paper-account adapter. | Orders, fills, cancellations, and failures reconcile into OneJournal. |
| PAP-06 | LATER | Add execution monitoring, duplicate prevention, retry policy, and failure recovery. | Fault-injection tests do not create duplicate orders. |
| PAP-07 | LATER | Run an extended paper-trading soak period and reconcile every intent, order, fill, position, and P&L result. | Approved soak report has no unresolved critical discrepancies. |

### Queue 7 exit gate

- Paper execution is isolated, risk-gated, auditable, idempotent, and reconciled.
- Kill switches and failure recovery are proven.
- No live broker-write permission is enabled.

## Queue 8 - Guarded live trading

Objective: consider limited live execution only after a separate explicit
approval and successful completion of every prior safety gate.

| ID | Status | Action | Completion evidence |
|---|---|---|---|
| LIV-01 | NEXT | Perform legal, regulatory, broker-permission, security, operational, and financial-risk readiness review. | Written approval records all accepted risks and constraints. |
| LIV-02 | LATER | Define a minimal live pilot with allow-listed accounts, symbols, strategies, sizes, schedules, and loss limits. | Configuration fails closed outside the pilot scope. |
| LIV-03 | LATER | Require human approval for initial live order intents. | Approval and submission are independently audited. |
| LIV-04 | LATER | Reconcile every live intent, broker order, fill, position, cash movement, and journal record. | No unexplained discrepancy remains before expansion. |
| LIV-05 | LATER | Expand automation only through separately approved stages backed by operating evidence. | Each expansion has explicit entry, monitoring, and rollback gates. |

## Immediate execution order

The current actionable sequence is:

1. `JRN-05` - add assignments, exercises, expirations, rolls, transfers, dividends, and corporate actions.
2. `JRN-05` remains blocked until ADR-0005 is approved and event-ledger migration completes.
3. `LIV-01` - legal/regulatory/security/operational readiness for guarded execution in Queue 8.

No P&L, production website, or execution implementation should bypass these
foundational and contract decisions.
