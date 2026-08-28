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

- Broker-reconciled, lifecycle-event-allocated P&L across the complete
  portfolio scope.
- Provider-backed market-data valuation with approved freshness and licensing
  policy.
- Time-period reporting and export workflows that reconcile to canonical P&L.
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

Queue status values are delivery-workflow states:

- `NEXT` - the next approved item to execute.
- `QUEUED` - ready after its dependencies are complete.
- `IN PROGRESS` - approved implementation work is actively underway.
- `BLOCKED` - depends on a decision or unfinished prerequisite.
- `COMPLETE` - the stated implementation work and its defined evidence are
  complete.
- `LATER` - intentionally outside the near-term delivery path.

`COMPLETE` does not by itself mean the capability is available in an intended
runtime, production ready, operationally accepted, or financially accepted.
Those states require their own explicit evidence and acceptance.

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
| CON-02 | COMPLETE | Define base currency, multi-currency policy, decimal precision, timezone, market-date, and trading-session rules. | Accepted ADR-0003 records project-owner confirmation of all seven reporting currency, native-currency/FX, decimal/rounding, UTC-instant, New York market-date, Singapore-display, and calendar/session decisions. Runtime conformance remains separately validated. |
| CON-03 | COMPLETE | Define realized P&L, unrealized P&L, cost basis, tax-lot policy, fees, commissions, and return calculations. | ADR-0004 plus FIFO lot engine and fail-closed contract tests in `src/onejournal/pnl/` plus mark-sourcing behavior tests. DB-backed payload now includes realized/unrealized P&L by currency. |
| CON-04 | COMPLETE | Define lifecycle treatment for partial fills, partial exits, and multi-leg trade matching by episode scope. | Lifecycle and preview contract tests are in place; complex lifecycle event types remain blocked under ADR-0005. |
| CON-05 | COMPLETE | Define the bounded normalized-fill identity, equivalent replay/conflict, and calculation-input fingerprint foundation. | Accepted ADR-0006 matches implemented stable fill identity, normalized-economic replay deduplication/conflict rejection, and exact fill/approved-lifecycle P&L fingerprints. It does not claim complete correction or provenance. |
| CON-06 | COMPLETE | Accept data freshness, missing-data, reconciliation, and fail-closed presentation policy. | Accepted ADR-0007 establishes that independently valid partial information may remain visible while hidden uncertainty, false zero, and affected consolidated totals fail closed. Runtime conformance remains incomplete under PNL-08. |
| CON-07 | BLOCKED | Decide complete raw-evidence provenance, normalized-record versioning, supersession, correction governance, invalidation, recalculation, retention, and recovery rules. | Proposed ADR-0010 requires project-owner approval and a separately approved implementation/migration plan. Current import and revision mechanisms are partial evidence only. |

### Queue 1 exit gate (not yet satisfied)

- No core financial metric depends on an unresolved accounting assumption.
- Time, currency, identity, and lifecycle semantics have approved examples.
- Incomplete or conflicting broker evidence has an explicit failure policy.

CON-02 policy is complete. Dependent financial acceptance still requires
case-specific implementation and reconciliation evidence. CON-07 blocks claims
of complete correction/provenance capability but does not undo or prevent
continued validation of the accepted ADR-0006 identity foundation.

## Queue 2 - Build the canonical journal and trade-lifecycle engine

Objective: turn normalized broker activity into durable, correct trade and
position state.

| ID | Status | Action | Completion evidence |
|---|---|---|---|
| JRN-01 | COMPLETE | Version and migrate the DuckDB schema using the approved migration convention. | Migration ledger, baseline tables, schema checks, and contract tests are in place. |
| JRN-02 | COMPLETE | Persist normalized accounts, orders, positions, transactions, and required source lineage—not only fills. | Normalized family derivation, import-run linkage checks, and contract coverage now exercise all families. |
| JRN-03 | COMPLETE | Replace preview grouping with a deterministic trade-lifecycle engine. | Entry/exit/partial/reopen fixtures and deterministic lifecycle tests are implemented and merge-validated. |
| JRN-04 | COMPLETE | Add multi-leg lifecycle handling for verticals and later approved strategies. | Preview-level and lifecycle-contract fixtures for multi-leg and cross-symbol matching using explicit episode-group scope are in place. |
| JRN-05 | COMPLETE | Add assignments, exercises, expirations, rolls, transfers, dividends, and corporate-action handling. | Lifecycle extraction is covered for all listed event types and ADR-0005 event-ledger persistence is wired end-to-end through Schwab conversion and DB import flow. |
| JRN-06 | COMPLETE | Preserve current normalized-fill replay and replace-import revision evidence without losing manual reviews. | Equivalent replay is deduplicated, conflicting normal replay is rejected, and explicit replace imports preserve manual reviews plus prior/next signed normalized payloads. This is not complete source supersession or correction governance. |
| JRN-07 | COMPLETE | Strengthen broker-to-journal reconciliation at fill, transaction, position, cash, and account levels. | Fill/transaction/position/cash/account checks are classified and policy-gated before publication. |
| JRN-08 | BLOCKED | Implement durable source supersession, governed corrections, event-set versions, downstream invalidation, and recalculation lineage. | Depends on accepted ADR-0010, approved privacy/retention/recovery policy, an additive migration plan, and raw-to-output validation evidence. |

### Queue 2 exit gate (not yet satisfied)

- Trade episodes represent complete lifecycles rather than previews.
- Broker evidence can be replayed without duplicates or lost reviews.
- Positions and cash reconcile within the approved policy.

JRN-08 remains blocked. The completed JRN-06 replace-import path must not be
reported as complete source supersession, governed correction, or raw-to-output
recalculation lineage.

## Queue 3 - Implement P&L, portfolio, and reporting

Objective: produce traceable financial results before building the production
presentation layer.

| ID | Status | Action | Completion evidence |
|---|---|---|---|
| PNL-01 | COMPLETE | Implement realized P&L from closed lifecycle allocations. | ADR-0004 rules and the Decimal FIFO/lifecycle implementation are validated by focused tests and five owner-accepted, broker-reconciled real-evidence scopes: ordinary close, partial close, expiration, assignment through successor closure, and the original-contract roll boundary. The bounded acceptance is recorded under `data/audit/trust_proofs/PNL-01/`. It excludes real exercise, the roll replacement contract's closure, unresolved `review_required` or unapproved description-only events, complete account history, portfolio-wide correctness, unrealized P&L/valuation, production readiness, and complete ADR-0010 provenance. |
| PNL-02 | IN PROGRESS | Select a market-data provider and define quote ingestion, storage, licensing, and freshness. | ADR-0009 accepts Schwab first, IBKR next, and Moomoo later through a provider-independent, local-only quote contract. Repository-policy loading, migrations 0011/0012, a provider-neutral complete-capture envelope, atomic normalized storage, full-envelope replay lineage, and fail-closed tests are implemented. A separately approved one-symbol Schwab capture was checksum-transferred to the private vault and validated through the credential-free importer. The observed response confirmed real-time entitlement and the core equity mapping but supplied no market-session field, so valuation correctly remained unavailable. A provider-neutral, deterministic point-in-time session-authority boundary now validates exact instrument/MIC/calendar/timezone/date/evaluation/phase/source/expiry binding and fails closed on conflicts, holidays, early closes, mismatches, and unsupported states without choosing a calendar provider. No approved resolver is selected or wired, so this implementation does not change the bounded capture's unavailable result. OneBot/VPS remains only the temporary Schwab-token owner; the target is an isolated OneJournal-owned multi-provider connector plane with OneBot access retired at cutover. Completion still requires approved authoritative session resolver evidence in the runtime path, connector security and ownership design, an approved durable ingestion operator/runtime migration, broader provider/asset validation, single-owner cutover, and end-to-end acceptance. |
| PNL-03 | BLOCKED | Implement current positions, cost basis, market value, and unrealized P&L. | FIFO open quantity/cost groundwork exists, but current `normalized_positions` are derived independently from each import date's fills and use the last fill as `market_price`; they are not cumulative broker snapshots or approved valuations. Completion requires PNL-02 plus broker-position reconciliation. |
| PNL-04 | BLOCKED | Build account and consolidated portfolio snapshots over time. | As-of payload selection exists, but its inputs are per-import derived position rows rather than canonical cumulative and broker-reconciled portfolio state. Historical snapshots cannot yet satisfy the acceptance criterion. |
| PNL-05 | BLOCKED | Implement performance metrics: total P&L, returns, win rate, profit factor, average win/loss, holding period, drawdown, and exposure. | Win/loss, profit factor, average result, and holding-time groundwork exists; returns and max drawdown are explicitly unavailable and valuation-dependent exposure is not approved. |
| PNL-06 | BLOCKED | Implement breakdowns by account, broker, strategy, symbol, and asset class. Time-period reporting belongs to PNL-07. | Initial groupings exist, but completion depends on canonical PNL-01/03 inputs and reconciliation tests proving every breakdown sums to the authoritative portfolio totals. |
| PNL-07 | BLOCKED | Build daily, monthly, and custom-period reports and exports. | Reports reconcile to canonical calculations and identify their as-of state. |
| PNL-08 | BLOCKED | Conform every published financial payload and presentation path to accepted ADR-0007. | Status scaffolding exists for imports, as-of data, unmatched closes, and missing unrealized values. Completion remains blocked by false-valid derived positions, implicit USD and false-zero paths, incomplete processed/unavailable counts, missing per-item omission reasons, absent broker/quote/reconciliation evidence, and absent responsive/accessibility validation. |

### Queue 3 audit record

**Status: reopened after source-level audit (2026-08-09).** PNL-01 returned to
`COMPLETE` on 2026-08-27 after bounded owner acceptance of five real-broker,
broker-reconciled lifecycle scopes. PNL-02, PNL-03, PNL-04, PNL-05, PNL-06,
PNL-07, and PNL-08 remain open. Earlier
completion labels for PNL-03 through PNL-06 and PNL-08 described useful
prototype scaffolding, but their acceptance criteria are not yet satisfied.
The source-level reasons are recorded in the queue rows above so no placeholder
or unavailable value is mistaken for completed financial behavior.

### Queue 3 financial exit gate (not yet satisfied)

- Realized and unrealized P&L reconcile to approved examples and broker evidence.
- Portfolio totals and all breakdowns reconcile.
- Every displayed metric is traceable, dated, and freshness-aware.

The remaining closure conditions are:

- PNL-01: bounded delivery and financial acceptance were recorded on
  2026-08-27 for ONJ-TRUST-01B, ONJ-TRUST-02, ONJ-TRUST-03, ONJ-TRUST-04,
  and ONJ-TRUST-06. Those scopes cover an ordinary close, partial close,
  expiration, assignment through successor closure, and the original-contract
  roll boundary. No real exercise example is accepted, the replacement roll
  contract is not followed to closure, and unresolved `review_required` or
  unapproved description-only records remain outside financial totals. This
  bounded closure does not establish complete account history, portfolio-wide
  correctness, unrealized P&L/valuation, or complete ADR-0010 provenance.
- PNL-02: the project owner approved Schwab first, IBKR next, and Moomoo later,
  local-only personal-account evidence, no silent provider fallback, and the
  ADR-0009 polling/freshness policy. The provider-neutral quote and complete-
  capture contracts plus temporary-DuckDB storage pipeline are implemented
  offline. PNL-02A adds a synthetic-contract-validated
  Schwab adapter. The interim one-app evidence bridge makes OneBot/VPS the
  temporary single token-owning producer and the current OneJournal runtime a
  credential-free evidence importer; it does not add provider acceptance or
  define the target architecture. The target is a OneJournal-owned
  provider-connector plane supporting Schwab, IBKR, Moomoo, and later providers
  through common contracts, with OneBot Schwab access retired before cutover.
  A versioned, connection-scoped user acknowledgement is required before future
  activation and retrieval, but it cannot replace provider-reported
  entitlement. Its persistence and UI remain gated on the authentication and
  tenancy decisions. Completion remains gated on a separately approved
  authoritative market-session/calendar integration, an approved durable
  ingestion operator/runtime migration, connector security/ownership design,
  broader provider/asset validation, single-owner cutover, and end-to-end
  adapter validation. The bounded 2026-08-27 equity capture, private transfer,
  and sanitized official-shape fixture are evidence only and did not produce an
  eligible valuation.
- PNL-03/04: canonical cumulative positions and portfolio snapshots must be
  derived from lifecycle lots, then reconciled to actual broker position
  snapshots; per-import fill aggregation is not a substitute.
- PNL-05/06: complete metrics and breakdown reconciliation follow canonical
  realized/unrealized P&L and position state. Returns and drawdown remain
  unavailable until their denominator/equity-curve policies are approved.
- PNL-07: period-reporting and export scope must be defined and reconciled to
  canonical calculations.
- PNL-08: no metric may claim `valid` without the exact required source,
  reconciliation, completeness, and approved freshness evidence. Every affected
  scope must report processed/unavailable counts and omission reasons; missing
  values must not become zero, and responsive/accessibility evidence remains
  required separately.

## Queue 4 - Complete the journaling product

Objective: provide the workflows needed to learn from trading activity.

| ID | Status | Action | Completion evidence |
|---|---|---|---|
| UXJ-01 | COMPLETE | Define the journal-entry, review, tag, strategy, mistake, lesson, and attachment model. | Accepted ADR-0008, contract v1, migration 0005, append-only domain services, compatibility dual-write, replay preservation, and temporary-database tests are in place; the runtime database has not been migrated. |
| UXJ-02 | COMPLETE | Build review queues for unreviewed, incomplete, risk-flagged, and mistake trades. | Deterministic reason-coded queues, as-of filtering, pre-0005 compatibility, payload privacy checks, and internal prototype navigation are implemented and tested. |
| UXJ-03 | COMPLETE | Add structured pre-trade plan, entry thesis, execution review, exit review, and post-trade reflection. | All structured types use stable entry identities and append-only revisions; unlinked plans can later link to episodes, replay tests retain history, and local Streamlit/operator workflows are available after migration 0005. |
| UXJ-04 | COMPLETE | Add search, filters, saved views, and navigation by date, strategy, symbol, account, and review state. | Current-revision search and structured saved views cover all listed dimensions; queue and private journal navigation are wired into the internal prototype and contract-tested. |
| UXJ-05 | BLOCKED | Add charts, screenshots, notes, and evidence attachments with privacy and retention controls. | Metadata schema, validation, payload exclusion, and fail-closed writes are implemented; storage, authorization, encryption, deletion, retention, backup, and incident policy remain approval blockers. |
| UXJ-06 | BLOCKED | Add goal, habit, and recurring review workflows only after the core trade journal is stable. | Process goals, append-only check-ins, habits, and explicit-period weekly/monthly review events are implemented locally; financial evaluation remains disabled until PNL-02 and PNL-07 are resolved. |

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
| LIV-01 | COMPLETE | Perform legal, regulatory, broker-permission, security, operational, and financial-risk readiness review. | Internal owner-attested completion entries are in `docs/live_trading_readiness_checklist.md` and `docs/live_trading_readiness_evidence_pack.md`. External review remains required before production. |
| LIV-02 | COMPLETE | Define a minimal live pilot with allow-listed accounts, symbols, strategies, sizes, schedules, and loss limits. | Control contract, pilot evidence, and validator checks are complete and signed off by owner. |
| LIV-03 | COMPLETE | Require human approval for initial live order intents. | Approval schema and validator evidence are complete and signed off by owner. |
| LIV-04 | COMPLETE | Reconcile every live intent, broker order, fill, position, cash movement, and journal record. | Reconciliation-chain validator, sample artifacts, and evidence are complete and signed off by owner. |
| LIV-05 | COMPLETE | Expand automation only through separately approved stages backed by operating evidence. | Expansion governance validator and decision log are complete and signed off by owner. |

## Immediate execution order

CON-02's seven owner decisions are resolved in accepted ADR-0003. CON-07 and
JRN-08 remain separate future provenance/correction work. They do not
change the current `PNL-02` in-progress status or authorize any live provider
call, migration, or runtime change.

The current actionable sequence is:

1. `PNL-02` - validate the approved Schwab-first quote contract against official
   evidence, complete the target connector/security boundary, and obtain
   end-to-end acceptance.
2. `PNL-03` and `PNL-04` - replace per-import fill-derived position views
   with canonical cumulative lot state, approved valuations, broker
   reconciliation, and reproducible portfolio snapshots.
3. `PNL-05` and `PNL-06` - complete metrics and prove every breakdown
   reconciles to canonical P&L and position totals.
4. `PNL-07` - deliver daily/monthly/custom period report and export contracts with reconciliation behavior.
5. `PNL-08` - enforce per-metric source, reconciliation, completeness, and freshness states.
6. `UXJ-05` - finalize attachment controls policy (storage, authorization, encryption, retention, backup, incident response).
7. `UXJ-06` - enable non-financial journal process workflows after financial contracts are stable.
8. `WEB-01` - decide and approve production architecture, security, and hosting stack.
9. `WEB-02` to `WEB-09` - define IA/design system to production rollout in dependency order.

No implementation should bypass unresolved blockers above, especially P&L
financial correctness, quote governance, attachment controls, and production
architecture security.
