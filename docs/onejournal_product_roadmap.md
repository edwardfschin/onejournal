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
- An accepted open-source production web foundation and visible vertical
  delivery contract; implementation has not started.

The repository does not yet have:

- Broker-reconciled, lifecycle-event-allocated P&L across the complete
  portfolio scope.
- Continuous provider-backed acquisition and PNL-03-approved valuation marks
  for real portfolio use.
- Time-period reporting and export workflows that reconcile to canonical P&L.
- Production web implementation, authentication, hosted runtime, or deployment.
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
- Synthetic presentation work may precede a financial dependency only when it
  is unmistakably demo-only and the corresponding real metric remains
  unavailable until its financial gate passes.
- No more than two consecutive trust/backend work packages should complete
  without a browser-visible increment or an explicit reason why no safe visible
  increment exists.
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

## Phase 1 - Private Owner Release

ADR-0018 defines the finite first releasable product. Phase 1 is a secure,
private, single-owner Schwab website for supported US equities and listed equity
options, with trustworthy journal, current portfolio, realized/unrealized P&L,
bounded reporting/export, explicit quality states, and production recovery.

Phase 1 progress: **2 of 12 work packages complete**.

This tracker is the authoritative Phase 1 completion record. Update the row and
evidence whenever a package changes state. A broader PNL, UXJ, WEB, or OPS item
is not complete merely because its required Phase 1 slice is complete.

| ID | Status | Phase 1 work package | Completion evidence |
|---|---|---|---|
| P1-01 | COMPLETE | Approve the finite Phase 1 owner, broker, account, instrument, financial, web, operational, and explicit non-goal scope. | Accepted ADR-0002 and ADR-0018 define the Private Owner Release and its exit gate. No implementation or operational acceptance is claimed. |
| P1-02 | COMPLETE | Approve the open-source web foundation, portable topology, information architecture, user journeys, and vertical-delivery policy. | Accepted ADR-0017 and `docs/production_web_delivery_contract.md`; corresponds to WEB-W01 and WEB-W02. |
| P1-03 | NEXT | Render and approve the distinctive OneJournal design system, responsive shell, and high-fidelity synthetic routes. | WEB-W03 and WEB-W04 pass desktop/mobile visual, state, keyboard, and owner-experience review with no private data. |
| P1-04 | QUEUED | Implement the versioned FastAPI/frontend application boundary against safe fixtures. | WEB-W05 passes OpenAPI, decimal/time/quality, privacy-safe failure, build, and contract tests with no raw-file or direct-database browser access. |
| P1-05 | BLOCKED | Implement and accept a repeatable read-only Schwab evidence/import route for required account, position, order, transaction, fill, cash, quote, and session families. | Original evidence and exact lineage feed OneJournal-owned normalization, reconciliation, replay-safe persistence, and audit. Manual or credential-free external acquisition is allowed; OneJournal token ownership, continuous polling, T15, and OneBot-derived state are not required or accepted. Provider access and evidence use remain separately approval-gated. |
| P1-06 | QUEUED | Deliver the private local-owner trade and journal vertical slice through the new application boundary. | WEB-W06 proves search, review queues, lifecycle inspection, append-only entries/reviews, audit, replay, and privacy against approved local state without Streamlit or broker calls. |
| P1-07 | BLOCKED | Approve and deliver canonical current positions, cost basis, marks, market value, and unrealized P&L. | PNL-03 and WEB-W07 pass cumulative position authority, broker reconciliation, mark selection, instrument/spread, exact as-of, and fail-closed financial acceptance. |
| P1-08 | BLOCKED | Deliver the bounded Phase 1 current portfolio, account/symbol breakdown, date-filtered P&L history, CSV export, and complete quality states for displayed metrics. | WEB-W08 and the required bounded PNL-06 through PNL-08 slices reconcile every displayed/exported value and preserve processed/unavailable counts and reasons. Advanced returns, drawdown, exposure, portfolio-history series, and broader analytics remain later. |
| P1-09 | BLOCKED | Implement and accept owner authentication, authorization, secure sessions, recovery, and audit. | WEB-W10 security decision and negative route/service/record/session/recovery tests pass with no critical finding. |
| P1-10 | BLOCKED | Establish approved environments, private HTTPS hosting, production state, deployment/rollback, observability, encrypted backup, and tested restoration. | WEB-W12 and required OPS gates prove environment identity, migration/reconciliation where needed, release/rollback, monitoring, recovery, and privacy without provider or order-safety drift. |
| P1-11 | BLOCKED | Complete production accessibility, responsive, browser/device, performance, visual-regression, and end-to-end validation. | WEB-W11 passes the approved quality budgets and supported-device matrix using privacy-safe evidence. |
| P1-12 | BLOCKED | Execute and accept the end-to-end private production release. | WEB-W13 produces a dated acceptance pack identifying artifact, environment, owner scope, supported instruments, data routes, calculations, quality/freshness, limitations, recovery, and rollback; the owner explicitly accepts Phase 1 and Streamlit disposition is recorded. |

### Phase 1 exit gate

Phase 1 is complete only when:

- `P1-01` through `P1-12` are all `COMPLETE`;
- the deployed private website passes its financial, security, accessibility,
  migration, recovery, and operational acceptance checks;
- every displayed financial scope reconciles or is visibly unavailable; and
- the project owner explicitly accepts the dated Private Owner Release scope.

IBKR/Moomoo, multi-user/public features, continuous OneJournal-owned Schwab
connectivity, attachments, advanced journal routines, advanced analytics,
paper/live trading, and automated trading are explicitly post-Phase 1 and do
not block this gate.

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
| PNL-02 | COMPLETE | Select a market-data provider and define quote ingestion, storage, licensing, and freshness. | Completed 2026-08-31 for the bounded owner-operated local Schwab bridge scope accepted by ADR-0016. Provider-neutral quote/capture contracts, migrations 0011/0012, exact source lineage, entitlement and fail-closed freshness, same-provider session authority, credential-free external acquisition, append-only private materialization, guarded isolated-DuckDB persistence/read-back, and idempotent replay are implemented and validated. T16 evidence `PNL-02-T16-SCHWAB-20260831-02` completed five bounded Schwab GETs, exact transfer, OneJournal-owned equity/option conversion and `market_closed_last` assessment, two accepted persisted runs, and explicit owner acceptance `PNL-02-T16-OWNER-ACCEPTANCE-20260831-01`; 338 repository tests pass. This does not accept continuous acquisition, a public/hosted market-data service, production journal migration, OneJournal credential ownership, T15 cutover, IBKR/Moomoo integration, or PNL-03 valuation marks. |
| PNL-03 | BLOCKED | Implement current positions, cost basis, market value, and unrealized P&L. | PNL-02's bounded quote/freshness dependency is complete. The exact PNL-03 entry gate is now to approve and implement cumulative broker-position authority and reconciliation, cost-basis scope, mark-selection and spread/instrument policy, and fail-closed unavailable behavior. Current per-import fill-derived positions and their last-fill `market_price` remain prototype-only; no PNL-02 quote is an approved valuation mark yet. |
| PNL-04 | BLOCKED | Build account and consolidated portfolio snapshots over time. | As-of payload selection exists, but its inputs are per-import derived position rows rather than canonical cumulative and broker-reconciled portfolio state. Historical snapshots cannot yet satisfy the acceptance criterion. |
| PNL-05 | BLOCKED | Implement performance metrics: total P&L, returns, win rate, profit factor, average win/loss, holding period, drawdown, and exposure. | Win/loss, profit factor, average result, and holding-time groundwork exists; returns and max drawdown are explicitly unavailable and valuation-dependent exposure is not approved. |
| PNL-06 | BLOCKED | Implement breakdowns by account, broker, strategy, symbol, and asset class. Time-period reporting belongs to PNL-07. | Initial groupings exist, but completion depends on canonical PNL-01/03 inputs and reconciliation tests proving every breakdown sums to the authoritative portfolio totals. |
| PNL-07 | BLOCKED | Build daily, monthly, and custom-period reports and exports. | Reports reconcile to canonical calculations and identify their as-of state. |
| PNL-08 | BLOCKED | Conform every published financial payload and presentation path to accepted ADR-0007. | Status scaffolding exists for imports, as-of data, unmatched closes, and missing unrealized values. Completion remains blocked by false-valid derived positions, implicit USD and false-zero paths, incomplete processed/unavailable counts, missing per-item omission reasons, absent broker/quote/reconciliation evidence, and absent responsive/accessibility validation. |

### PNL-02 completion tracker

This register is the authoritative task-level tracker for PNL-02. `COMPLETE`
means that implementation and validation exist only for the scope stated in
that row; it does not expand the operational or financial acceptance boundary.
Before starting each unfinished task, reassess and state the exact GPT model
and reasoning level, why it fits, whether a lower-credit or no-credit model is
sufficient, and whether a switch is advised. Update the row with dated evidence
whenever a task changes state. Baseline verified on 2026-08-28 at commit
`303b0da`.

| ID | Status | Task and completion gate | Evidence, dependency, or approval boundary |
|---|---|---|---|
| PNL-02-T01 | COMPLETE | Approve the provider and operating policy: read-only, account-broker selection, Schwab first, IBKR next, Moomoo later, no silent fallback, local-only personal use, and explicit entitlement/freshness states. | Accepted ADR-0009 and repository policy in `config/marketdata.yaml`; implemented by `a6c8933` and terms acknowledgement strengthened by `3b354d0`. |
| PNL-02-T02 | COMPLETE | Implement the provider-independent normalized quote, deterministic identity, point-in-time freshness policy, and fail-closed delayed/denied/unknown/future/crossed/stale behavior. | `src/onejournal/market_data/quotes.py`, `NormalizedQuote`, and focused quote-contract tests; implemented by `a6c8933`. |
| PNL-02-T03 | COMPLETE | Add additive quote-ingestion and normalized-quote storage schemas with provider/connection/source lineage, atomic writes, idempotent replay, conflict rejection, and scoped latest-quote reads. | Migrations 0011/0012 and `src/onejournal/market_data/repository.py`; validated only against temporary DuckDB databases. No current runtime database migration is claimed. |
| PNL-02-T04 | COMPLETE | Establish the provider-neutral complete-capture envelope binding exact requested/received identities, quote/receive/evaluation times, New York market date, source locator/hash, adapter version, and the complete normalized batch before persistence. | `src/onejournal/market_data/ingestion.py`, temporary-DuckDB contract tests, and commit `a278a24` (PNL-02A). |
| PNL-02-T05 | COMPLETE | Implement the credential-free Schwab JSON adapter and private-evidence importer without network, token, refresh, account, order, database-write, or raw-evidence-write capability. | `src/onejournal/brokers/schwab/quotes_json.py`, `scripts/journal/import_schwab_quote_evidence.py`, and focused boundary tests; commits `e1c881f` and `2113301`. |
| PNL-02-T06 | COMPLETE | Validate one separately approved official Schwab equity response through the temporary OneBot/VPS evidence bridge and preserve the actual entitlement/session outcome. | Private checksum transfer and credential-free validation recorded by `87ed474`. Evidence confirmed real-time entitlement and core equity mapping but no provider session; freshness therefore remained `unavailable` and valuation was disallowed. This is bounded evidence, not provider or PNL-02 acceptance. |
| PNL-02-T07 | COMPLETE | Define and validate a provider-neutral market-session authority value boundary without selecting a calendar provider or inferring session from the clock. | `src/onejournal/market_data/sessions.py`, freshness integration, and regular/extended/closed/holiday/early-close/conflict/expiry tests; commit `303b0da`. No resolver or runtime session evidence exists yet. |
| PNL-02-T08 | COMPLETE | Define the PNL-02 acceptance matrix and select the authoritative market-session/calendar resolver. Completion requires approved source, schedule-scope/MIC/calendar/timezone coverage, regular/extended/closed/holiday/early-close/unscheduled-closure behavior, update/outage policy, licensing constraints, and exact real-evidence cases. | Owner approved ADR-0011 on 2026-08-28: same-connected-broker provider-native schedule evidence is the exclusive authority. `docs/provider_native_market_session_contract.md` records provider eligibility, acceptance cases, caching/outage rules, licensing boundaries, no external or cross-provider fallback, and the required versioned replacement for the exact-MIC-only `v1` object. This design approval makes no provider call and does not establish runtime acceptance. |
| PNL-02-T09 | COMPLETE | Implement the approved provider-native resolver boundary and wire exact session-authority observations into the credential-free importer and common freshness/read boundary without persisting freshness as a permanent quote property. | `onejournal.provider-market-session-authority.v2`, the injected resolver interface, freshness integration, importer summary `v2`, and focused tests bind exact provider, connection, quote, provider instrument, schedule scope, timezone, source lineage, validity, and optional evidence-backed MIC. Tests prove deterministic identity, separate quote/evaluation phases, regular/extended/closed/holiday/early-close/unscheduled-closure/DST behavior, entitlement non-override, and fail-closed legacy, expiry, cross-provider, mismatch, conflict, and outage cases without provider, credential, database, or evidence writes. T14 later added the concrete Schwab payload parser/resolver and same-date private evidence; actual stock and listed-option quotes now pass this v2 boundary offline without persistence. |
| PNL-02-T10 | COMPLETE | Approve the target OneJournal provider-connector security and ownership design for the bounded local-owner scope and later provider adapters. Completion requires credential storage and refresh ownership, opaque connection identity, process/deployment isolation, least privilege, secret-safe logs, rate-limit/retry behavior, audit boundaries, no-order capability, recovery, rollback, and a no-dual-owner Schwab cutover plan. | Accepted ADR-0012 defines the isolated connector plane, deployment-neutral credential-store boundary, exclusive per-connection owner and generation checks, opaque identity, endpoint and egress allowlists, bounded retry/audit rules, no-order capability, fail-closed recovery, and break-before-make Schwab cutover/rollback. It does not choose production authentication, tenancy, hosting, or a secret backend. OneBot remains the temporary Schwab token owner until PNL-02-T15. |
| PNL-02-T11 | COMPLETE | Make provider terms, connection-scoped acknowledgement, entitlement verification, permitted local use, and raw-data retention/deletion behavior enforceable for the approved operating scope. | Owner approved ADR-0013 on 2026-08-28. `onejournal.provider-usage-policy.v1` and `onejournal.provider-usage-acknowledgement.v1` strictly bind the active terms profile, official references, local personal/noncommercial scope, provider, connection, notice, acceptance time, product version, declarations, entitlement requirement, and raw lifecycle. Focused synthetic tests reject missing, pre-review, future, tampered, superseded, mismatched, redistributed, hosted/public, automatic-deletion, and unaudited-deletion cases. A real owner-approved acknowledgement was later created in the private vault for the bounded T14 capture; it did not add a provider client, database write, deletion, authentication, tenancy, or UI. |
| PNL-02-T12 | COMPLETE | Implement the isolated, read-only OneJournal Schwab connector behind the common capture contract, with exact immutable raw capture and no account/order/database responsibilities. | Offline-only `onejournal.schwab.quote-connector.v1` validates the T11 acknowledgement before a fixed quote operation, serializes an injected owner lease, generation-checks an opaque credential capability, atomically writes only synthetic private 0700/0600 raw/manifest/envelope bundles without overwrite or delete capability, invokes the existing credential-free adapter and complete-capture contract, and emits a secret-free `captured_private_uningested` audit. `src/onejournal/provider_connectors/schwab_quotes.py`, `src/onejournal/provider_connectors/private_capture.py`, `docs/schwab_isolated_quote_connector_contract.md`, and focused tests prove no shipped network, credential backend, database, account, transaction, position, order, scheduler, CLI, or listener capability. Schwab remains disabled; no credential, provider call, real evidence, activation, or deployment is claimed. |
| PNL-02-T13 | COMPLETE | Implement and document the durable ingestion operator/runtime path from validated capture through atomic repository persistence and scoped read-back, including audit output, idempotency, failure behavior, recovery, and migration procedure. | `onejournal.market-data.quote-capture-artifact.v1` and private manifest v2 make the normalized capture restart-safe and bind it separately to immutable raw bytes. The guarded operator defaults to validation-only, requires explicit `--persist`, refuses missing/unprepared databases, uses the existing transaction, distinguishes first write from exact replay, and verifies fingerprint, lineage, counts, quote identities, and semantic field equality through exact provider/connection/run/date read-back. Synthetic private-vault and temporary-DuckDB tests prove tamper/scope/schema failure before writes plus recovery by identical replay. `docs/durable_quote_ingestion_operator.md` defines failure, recovery, backup/rehearsal, migration, post-check, rollback, and separate approval gates. No actual journal database, migration, provider, credential, private evidence, deployment, push, or P&L mark was used. Applying migrations 0011/0012 or persisting a real capture remains separately approval-gated. |
| PNL-02-T14 | COMPLETE | Execute the approved broader conformance matrix across Schwab equity and listed-option shapes, required session states, entitlement/delay states, stale/future/crossed/missing evidence, exact identity, and provider-neutral non-fallback behavior. | Synthetic conformance covers equity/listed-option mapping, configured freshness/session states, exact identity/source binding, outage/expiry, frozen-open failure, atomic replay/read-back, and cross-provider fallback rejection. Same-date capture `PNL-02-T14-SCHWAB-20260829-06` used unchanged v5 (`4c092ee5cd0c57dfa71d50b8d54310139a7e45bf9b8a969c40337a6a4fc0f6b0`) after one separately approved corrected OneBot-owned refresh, then completed exactly five GETs with zero in-capture refresh/account/order/database actions. The nine-file VPS/private-vault bundle retains manifest SHA-256 `a518edd8869b4e3cc41fec9355f30fb109d5c241a1fb567003adb2e7dae74317`, exact checksum parity, and `0700`/`0600` permissions. Both official quotes report real-time entitlement and omit market session; their 2026-08-28 date matches the normal `EQ`/`EQO`/`IND` schedule. The option produces combined v2 authority and `market_closed_last`. `schwab-quote-json-v2` maps the observed equity `securityStatus=Closed` to provider-neutral `frozen`, forces session unknown, and produces the same outcome only after exact v2 authority confirms close; without authority or while the effective market is open it remains valuation-ineligible. Closed-sentinel and shortened-session bytes also pass. No journal write, migration, provider activation, commit, push, repository sync, or deployment is authorized or claimed. Live IBKR and Moomoo remain later rollouts. |
| PNL-02-T15 | LATER | Execute the explicit single-owner Schwab cutover: retire OneBot's Schwab access before OneJournal becomes the only token-lifecycle owner, then prove there is no dual refresh or provider-call path. | ADR-0016 makes this target-architecture cutover non-blocking for bounded bridge-mode PNL-02 completion. The credential-free `onejournal.provider-connection-cutover.v1` boundary, provider-disabled macOS staging foundation, and rehearsal remain preserved for later use. Cutover still requires current authorization, a clean target artifact, fresh credential handling after a proven owner gap, exact OneBot retirement, bounded OneJournal activation/provider access, operational evidence, and rollback. No dual ownership or OneBot token copy is permitted. |
| PNL-02-T16 | COMPLETE | Implement, run, and reconcile bounded end-to-end bridge-mode acceptance from exact externally acquired Schwab provider bytes and verified acquisition lineage through OneJournal's credential-free intake, adapter, capture envelope, session authority, guarded durable persistence, scoped read-back, and freshness decision, including negative fail-closed and secret/order safety cases. | Completed and owner-accepted 2026-08-31 for the bounded local bridge scope. `PNL-02-T16-SCHWAB-20260831-02` completed exactly five market-data GETs with zero in-capture refresh/account/order/database actions; all transfer hashes matched; OneJournal independently converted equity/option bytes and resolved same-provider authority; both assessments were valuation-eligible `market_closed_last`; append-only 0700/0600 captures persisted to isolated DuckDB 0012 with exact read-back; identical replay produced no duplicates. The private evidence pack and owner acceptance `PNL-02-T16-OWNER-ACCEPTANCE-20260831-01` preserve the scope and limitations. Focused negative tests and the 338-test suite pass. No credential, continuous service, public listener, production journal, deployment, or PNL-03 mark is accepted. |
| PNL-02-T17 | COMPLETE | Close PNL-02: reconcile ADRs/contracts/runbooks/tests, record limitations and acceptance evidence, update strategic maturity, change the roadmap item to `COMPLETE`, and identify the exact PNL-03 entry gate. | Completed 2026-08-31 after T16 owner acceptance. ADR-0009/0016, README, the data contract, roadmap, and maturity map now distinguish M4 bounded local bridge acceptance from continuous/live provider operation and target connector ownership. Full CI passes 338 tests. PNL-03 remains blocked until it separately approves and implements broker-position authority/reconciliation, cost-basis scope, mark-selection and spread/instrument policy, and fail-closed unavailable behavior; quotes accepted by PNL-02 are not automatically valuation marks. Commit, push, merge, production migration, deployment, and PNL-03 implementation remain separately authorized. |

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
- PNL-02: completed and owner-accepted on 2026-08-31 for ADR-0016's bounded,
  owner-operated, local Schwab bridge scope. OneBot/VPS remains the sole token
  owner; OneJournal accepts only exact provider bytes and verified acquisition
  lineage, then performs its own adapter, session-authority, entitlement,
  freshness, private-capture, persistence, and read-back work. T16 evidence
  covers AAPL equity and listed option, normal/closed/early-close schedules,
  exact checksum transfer, append-only private materialization, isolated
  DuckDB 0012 persistence, exact replay, and negative fail-closed cases. This
  completion does not establish continuous acquisition, production journal
  migration, a public/hosted service, OneJournal credential ownership, IBKR or
  Moomoo integration, or PNL-03 valuation marks. T15 remains later target-
  architecture work; automatic raw-evidence deletion remains disabled.
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
| WEB-01 | COMPLETE | Decide frontend, backend/API, database evolution, background-job, and portable hosting architecture. | Accepted ADR-0017 and `docs/production_web_delivery_contract.md` select React/TypeScript/Vite, Tailwind CSS, shadcn/ui with Base UI, Apache ECharts, FastAPI, local DuckDB, later migration-gated PostgreSQL, an isolated worker boundary, and a self-hostable vendor-neutral topology. No implementation, host, migration, deployment, or private runtime is claimed. |
| WEB-02 | COMPLETE | Define information architecture and priority user journeys. | The production web delivery contract defines Today, Portfolio, Trades, Journal, Reports, Data & connections, and Settings plus current-state, trade-review, portfolio, import/reconciliation, and reporting journeys with authority and unavailable-state rules. Screen implementation and usability acceptance remain separate. |
| WEB-03 | NEXT | Create the OneJournal visual design system and responsive application shell. | Approved rendered typography, colour, spacing, components, charts, state gallery, and responsive rules produce a distinctive local synthetic-data shell with no private data. |
| WEB-04 | QUEUED | Design high-fidelity responsive screens and validate them before full implementation. | Desktop, tablet, and mobile designs cover loading, empty, demo, stale, partial, unavailable, and error states for all initial routes. |
| WEB-05 | QUEUED | Build the application/API layer so the frontend never reads raw broker data, generated payloads, or database files directly. | Versioned OpenAPI contracts, generated frontend compatibility, decimal/time/quality-state behavior, privacy-safe failures, and boundary tests pass against safe fixtures. |
| WEB-06 | BLOCKED | Implement authentication, authorization, secure sessions, account recovery, and audit logging. | Security review and negative authorization tests pass. |
| WEB-07 | BLOCKED | Implement local-owner journal, portfolio, P&L, trade, report, data-health, and settings vertical slices. | Each slice uses authoritative Python services through the API, reaches its financial dependency gate, and passes functional and visual acceptance. PNL-03 blocks authoritative position/valuation views but not the synthetic preview or accepted journal slice. |
| WEB-08 | BLOCKED | Add accessibility, performance, browser, device, and end-to-end testing. | Agreed accessibility and performance targets pass in supported browsers. |
| WEB-09 | BLOCKED | Migrate operator workflows away from Streamlit only after verified parity. | Production website is authoritative; Streamlit retirement/retention is documented. |

### Production web work-breakdown tracker

This is the authoritative status summary for the finite web route. Detailed
deliverables, visible checkpoints, validation, model profiles, and approval
boundaries are in `docs/production_web_delivery_contract.md`. Update this table
whenever a package changes state.

| WBS | Status | Outcome |
|---|---|---|
| WEB-W01 | COMPLETE | Open-source application architecture and portable service topology accepted. |
| WEB-W02 | COMPLETE | Information architecture and priority user journeys accepted. |
| WEB-W03 | NEXT | Render and approve the OneJournal design system and synthetic local application shell. |
| WEB-W04 | QUEUED | Produce and validate high-fidelity responsive synthetic workflows. |
| WEB-W05 | QUEUED | Establish the versioned FastAPI and frontend contract boundary. |
| WEB-W06 | QUEUED | Deliver the existing journal capability through a local-owner web vertical slice. |
| WEB-W07 | BLOCKED | Deliver authoritative current positions and unrealized P&L after PNL-03 acceptance. |
| WEB-W08 | BLOCKED | Deliver the bounded Phase 1 account/symbol breakdown, date-filtered P&L history, CSV export, and complete quality states for displayed metrics. |
| WEB-W09 | LATER | Deliver post-Phase 1 attachments and recurring review workflows after UXJ-05 and UXJ-06 privacy/dependency gates. |
| WEB-W10 | BLOCKED | Implement and accept production authentication, authorization, sessions, recovery, and audit. |
| WEB-W11 | BLOCKED | Complete accessibility, performance, browser/device, visual-regression, and end-to-end acceptance. |
| WEB-W12 | BLOCKED | Establish environments, hosted state, deployment, observability, backup, recovery, and private staging acceptance. |
| WEB-W13 | BLOCKED | Obtain private production acceptance and record the Streamlit transition. |

### Queue 5 exit gate

- The production website is secure, responsive, accessible, and visually approved.
- It consumes versioned application contracts rather than raw files.
- Financial and journal flows match canonical backend results.

## Queue 6 - Production operations and resilience

Objective: make the website and journal safe to operate continuously.

| ID | Status | Action | Completion evidence |
|---|---|---|---|
| OPS-01 | BLOCKED | Define development, test, staging, paper, and production environment boundaries. | ADR-0014 supplies only the PNL-02 connector staging isolation boundary. Completion requires environments with separate configuration, credentials, data, and visible identity. |
| OPS-02 | BLOCKED | Implement versioned deployment and rollback automation. | ADR-0014 authorizes no deployment. Completion requires a staging release and rollback successfully rehearsed. |
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
JRN-08 remain separate future provenance/correction work. PNL-02 is complete
only for the bounded local bridge scope; that completion does not authorize a
live provider service, production migration, or PNL-03 valuation. ADR-0017 now
permits a clearly labelled synthetic web preview before PNL-03 while preserving
PNL-03 as the authority gate for real positions and unrealized P&L.

The current actionable sequence is:

1. `WEB-W03` and `WEB-W04` - render the design system, application shell, and
   high-fidelity initial routes locally with synthetic data only. This is the
   first browser-visible checkpoint and grants no financial or runtime
   acceptance.
2. `WEB-W05` - establish versioned FastAPI/frontend contracts against safe
   deterministic fixtures; keep raw evidence and databases out of the browser.
3. `P1-05` and `PNL-03` - establish the approved read-only Schwab evidence
   route, then approve and implement cumulative broker-position authority and
   reconciliation, cost-basis scope, mark-selection and spread/instrument
   policy, and fail-closed unavailable behavior. Do not treat PNL-02 evidence
   as a valuation mark before this gate is accepted.
4. `WEB-W06` - expose already accepted journal capabilities through the local
   API/application boundary, then `WEB-W07` may expose real portfolio
   valuation only after PNL-03 acceptance.
5. `P1-08` and `WEB-W08` - deliver only the bounded Phase 1 account/symbol
   breakdown, date-filtered P&L history, export, and complete quality states
   for displayed metrics. Broader PNL-04 through PNL-08 work remains later
   where its full gate is not met.
6. `WEB-W10` and `WEB-W11` - complete authentication/security plus
   accessibility, performance, browser/device, and end-to-end acceptance.
7. `WEB-W12` - approve and prove environment, host, PostgreSQL migration,
   deployment, monitoring, backup, restoration, rollback, and private staging.
8. `WEB-W13` and `P1-12` - obtain explicit Phase 1 private production
   acceptance and retire or retain Streamlit only after verified parity.
9. After Phase 1, continue broader PNL-04 through PNL-08, UXJ-05/06 and
   WEB-W09, additional brokers, continuous connector ownership, and other
   explicitly deferred capabilities in approved dependency order.

No implementation should bypass unresolved blockers above, especially P&L
financial correctness, quote governance, attachment controls, and production
architecture security.
