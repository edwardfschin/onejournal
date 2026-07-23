# ADR-0001: Separate journal and execution planes

- Status: Accepted
- Date: 2026-07-23
- Decision owners: OneJournal project owner
- Related roadmap items: PAP-01 through PAP-08, LIV-01 through LIV-08
- Related contracts: `AGENTS.md`,
  `docs/schwab_execution_boundary_contract.md`,
  `docs/legacy_code_audit.md`
- Supersedes: None
- Superseded by: None

## Context

OneJournal currently imports broker evidence, normalizes fills, writes local
journal state, generates dashboard payloads, and supports manual review through
an internal Streamlit prototype.

The repository also retains isolated legacy files that can place, replace, or
cancel Schwab and IBKR orders. The active OneJournal package and journal
operators do not import or invoke those files. Automated trading is not an
approved current capability.

Combining journaling, presentation, strategy decisions, and broker mutations
would allow a UI, import defect, or reporting process to create financial risk.
The established safety contract therefore requires separate journal and
execution planes.

## Decision

OneJournal journal, reporting, dashboard, and production-presentation paths
must remain isolated from broker order execution.

The journal plane may:

- read immutable broker or manual evidence
- normalize and reconcile broker-independent records
- write approved local journal, audit, and review state
- calculate approved lifecycle, portfolio, risk, and performance values
- publish read-only application/API responses and generated reports

The journal and presentation planes must not place, cancel, replace, or modify
broker orders.

Any future execution plane must consume explicit order intents and apply
independent schema validation, risk gates, account and exposure controls,
duplicate protection, environment separation, approvals where required,
auditing, reconciliation, emergency disable controls, and kill switches before
calling a broker write endpoint.

Broker-confirmed execution evidence must return to the journal through raw and
normalized ingestion contracts. Execution services must not write directly to
trade episodes, P&L tables, dashboard payloads, or frontend state.

## Boundaries

This decision:

- applies to every broker, account, strategy, frontend, API, worker, and
  deployment environment
- permits explicitly configured read-only broker data collection
- permits local journal-review writes and generated-output publication
- does not approve a production execution stack, paper trading, or live trading
- does not select a broker, order-intent schema, approval policy, or risk limits

Legacy execution-capable code remains retained in isolation and is not an
approved implementation of the future execution plane.

## Alternatives considered

### Allow strategies or the website to call broker APIs directly

This is simpler initially but couples user-interface or strategy defects to
financial side effects, weakens auditability, and makes independent risk
controls and emergency shutdown harder. Rejected.

### Place read and write broker operations in one adapter

This reduces module count but makes least privilege, testing, credential scope,
and deployment separation harder to prove. Rejected.

### Separate journal and execution planes

This adds explicit contracts and operational components, but contains broker
write authority and allows journal/reporting work to remain safe while
execution is unapproved. Accepted.

## Consequences

### Positive

- Journal, P&L, reporting, and UI development cannot accidentally inherit
  broker-write authority.
- Execution risk gates and credentials can be independently deployed, tested,
  audited, disabled, and reconciled.
- Broker fills return through the same normalized lineage used for manual and
  read-only imports.

### Negative and trade-offs

- Future automated trading requires additional schemas, services, deployment
  boundaries, reconciliation, and operational controls.
- A strategy signal cannot become an order without an explicit intent and
  execution workflow.
- Paper and live execution cannot reuse legacy scripts merely because they
  already call broker APIs.

## Compatibility and migration

Existing active journal and Streamlit paths already follow this decision. No
database migration is created by this ADR.

Any future execution implementation requires new approved contracts and must
not change existing journal payloads or database meanings silently.

## Security, privacy, and financial impact

Broker write credentials must never be available to the journal UI, reporting
workers, public frontend, or read-only import jobs. Future execution credentials
must use least privilege and environment-specific configuration.

Ambiguous order state, missing reconciliation, invalid intent data, or risk-gate
failure must fail closed.

## Validation

Implementation must prove:

- active journal and presentation modules have no broker-write imports or calls
- legacy execution paths remain outside active entry points
- read-only broker adapters cannot access write credentials or endpoints
- future execution uses approved order intents and independent risk gates
- broker results return through raw evidence, normalized records, and
  reconciliation

## Rollback or supersession

This is a safety boundary, not a temporary implementation toggle. Weakening or
removing it requires explicit project-owner approval and a new ADR that
supersedes this record with equivalent or stronger risk containment.
