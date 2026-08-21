# OneJournal Project Operating Instructions

## Scope and precedence

These instructions apply to the entire OneJournal repository.

Follow explicit user instructions first. Then follow this file, the product
vision, strategic traceability documents, product roadmap, focused data
contracts, architecture decisions, and operator runbooks. When two project
documents conflict, do not guess: inspect the implementation, identify the
conflict, and obtain direction before encoding a durable policy.

The dependency-ordered delivery plan is maintained in
`docs/onejournal_product_roadmap.md`.

The strategic anchors are maintained in:

- `docs/vision/onejournal_product_vision.md`
- `docs/strategy_tracking/spreadsheet_to_onejournal_mapping.md`
- `docs/strategy_tracking/capability_maturity_map.md`

## Product identity and vision

The project is called OneJournal.

OneJournal will become a polished, production-grade website for:

- Trading journaling and review
- Portfolio monitoring
- Realized and unrealized P&L reporting
- Strategy and performance analytics
- Risk monitoring
- Eventually, controlled automated trading

The current Streamlit application is an internal prototype. It can validate
workflows, data contracts, and ideas, but it is not the final production
website.

The eventual website must be sleek, beautiful, responsive, intuitive, fast,
accessible, secure, and trustworthy. Visual quality matters, but financial
correctness, traceability, security, reliability, and maintainability come
first.

## Strategy and technical traceability

Track OneJournal product strategy alongside technical delivery. Preserve the
product vision and maintain an explicit trace from useful TGPS spreadsheet
thinking to broker-independent OneJournal capabilities. Preserve the intent,
control, calculation, review, and learning value of the spreadsheet workflow;
do not copy spreadsheet mechanics, hidden formulas, or workbook state into the
OneJournal architecture as unexamined requirements.

Use the strategic anchors when proposing or reviewing architecture decisions,
roadmap changes, product scope, and capability priorities. A decision that
changes a strategic principle, mapping, or maturity claim must update the
affected strategic document in the same focused change or explain why no update
is required.

Never equate documentation, a design, a roadmap status, code presence, passing
tests, or a prototype demonstration with operational acceptance. Track these as
distinct states. A capability is operationally accepted only when its stated
acceptance evidence exists, remaining limitations are explicit, and the project
owner has approved the capability for the stated operating scope. Do not infer
production readiness, broker authorization, deployment approval, or live-trading
approval from implementation progress.

## Model and credit routing

At the start of every new substantive work item, before repository inspection,
tool use, planning, implementation, or other credit-consuming work, advise the
user which currently available GPT model and reasoning level should be used,
unless automatic model switching for the current session has been explicitly
confirmed as available. Do not assume that automatic switching is available.

The advice must state:

- The exact recommended model name
- The recommended reasoning level
- Why the task needs that capability level
- Whether a lower-credit or no-credit model is sufficient
- Whether the current model is suitable or a switch is recommended

Verify current model names, availability, credit treatment, and intended uses
against current official OpenAI documentation or the model selector when that
information could have changed. Do not rely on stale model names or assume that
a model available in one Codex surface is available in another.

Use the lowest-cost model and lowest reasoning level that can complete the task
reliably without weakening correctness, safety, understanding, or validation.
Current routing examples, which must be revalidated as models change, are:

- Use GPT-5.3 Codex Spark, or its current no-credit or lowest-cost equivalent,
  for bounded, deterministic, low-risk work such as focused repository scans,
  inventories, small documentation changes, mechanical edits, well-specified
  tests, routine validation, and concise status reporting.
- Use GPT-5.6 Terra, or the current balanced equivalent, for everyday multi-file
  implementation, debugging, and review that require strong reasoning and tool
  use but do not require the flagship model.
- Use GPT-5.6 Sol, or the current flagship equivalent, for ambiguous or
  high-consequence work involving architecture, financial contracts, P&L,
  lifecycle semantics, database migrations, broker credentials, security,
  trading safety, difficult root-cause analysis, or final critical review.

If a less expensive model is sufficient and the current model consumes more
credits, recommend the switch and pause before substantive work so the user can
change models. If the current model is appropriate, state that and continue
unless another approval boundary requires a pause.

For credit-sensitive or high-risk work, do not begin substantive work before
communicating the recommendation, including whether the current model is
suitable or the user should switch.

Reassess the recommendation when the scope, risk, ambiguity, or required
judgment changes materially during a task. Tell the user before moving to a
stronger or more credit-intensive model.

Model selection does not relax any inspection, validation, security, financial,
Git, or approval requirement in this file. A model recommendation is not
authorization to perform a restricted action.

## Core working behaviour

Work factually. Do not assume when the answer can be established from the
repository, configuration, database, payload, source data, logs, or runtime
output.

Before changing anything:

1. Inspect the current implementation.
2. Identify the authoritative source of truth.
3. Understand the complete relevant data and dependency flow.
4. Determine the root cause or missing capability.
5. Define the expected result and validation method.
6. Make the smallest safe change.
7. Validate it before moving forward.

Always fix root causes rather than introducing workarounds.

Work one small, validated step at a time. Avoid broad rewrites unless evidence
proves the current architecture cannot safely support the requirement.

Do not provide fragmented command spam. Show commands only when the user needs
to run them, inspect their output, or approve an action.

When requirements are unclear and different interpretations would materially
change the result, stop and ask. Otherwise, make a conservative assumption,
state it clearly, and continue.

Do not claim success when validation is incomplete.

## Foundation design principles

This is a new, unlaunched project. Use that freedom to establish a clean
foundation before compatibility obligations accumulate.

Be creative when it materially improves the product or removes unnecessary
complexity, but prefer the simplest design that is correct, observable,
testable, reversible, and easy to operate.

- Avoid speculative abstraction and unnecessary dependencies.
- Choose safe defaults and make dangerous actions explicit.
- Validate inputs at boundaries and give actionable error messages.
- Make normal workflows obvious and difficult to misuse.
- Prefer deterministic and idempotent operations.
- Fail closed where financial data, private data, or future execution is at risk.
- Design recovery and rollback with the happy path, not afterward.
- Measure before optimizing, then optimize proven bottlenecks.
- Keep interactive paths small, fast, and free of avoidable work.
- Do not trade correctness or traceability for cosmetic speed.

"Fail-proof" and "idiot-proof" mean strong guardrails, clear feedback, safe
retries, and prevention of accidental misuse. They do not mean hiding failures
or silently guessing the user's intent.

## Mandatory understanding before changing artifacts

Before modifying any script, source file, configuration file, database,
database table, migration, JSON, YAML, CSV, schema, payload, generated artifact,
documentation file, or operator command, understand in detail:

- What it does and why it exists
- Whether it is authoritative, derived, generated, cached, or historical
- What reads it and what writes it
- Its inputs, outputs, and side effects
- Its callers and runtime entry points
- Its upstream producers and downstream consumers
- Its dependencies
- Its schema, field meanings, defaults, and fallback behaviour
- Its validation and failure rules
- Whether it contains private, financial, broker, or runtime data
- Which tests, documentation, and operator procedures cover it
- Whether changing it creates a compatibility or migration requirement
- How the proposed change will be verified
- How the previous working state can be restored

Inspect the complete relevant implementation. Do not rely only on filenames,
search snippets, documentation, or assumptions.

Documentation is evidence, but the running implementation is the final
authority when documentation and code disagree.

This rule also applies when renaming, moving, consolidating, archiving, or
deleting files. A file is not unused until its static references, runtime
references, operator references, generated-artifact relationships, and
deployment role have been checked.

Understand the complete relevant dependency chain, but do not waste time
reading unrelated parts of the repository.

## Impact map before implementation

Before a material change, establish a concise impact map:

- Authoritative source
- Upstream producer
- Changed component
- Downstream consumers
- Persisted state affected
- User-facing surfaces affected
- Validation required
- Rollback method

If a shared contract changes, identify and update every affected producer and
consumer in the same controlled change.

## Local source of truth

The user's Mac/MacBook project copy is the development source of truth.

The canonical OneJournal development repository is:

```text
/Users/edward/Projects/OneJournal
```

The former iCloud checkout is retained only as a backup/reference copy. It is
not authoritative and must not be used for new development changes. Private
financial evidence is stored separately under
`/Users/edward/Projects/Private/OneJournal` and must never be copied into Git.

Make and validate changes locally first. Deployment, VPS synchronization,
hosting changes, or production operations happen only after local validation
and explicit approval.

Never treat a deployed or remote copy as the authoritative development version
unless the user explicitly says otherwise. Preserve unrelated local changes.

## ODFS project structure

OneJournal uses ODFS as its organizing and data-flow standard.

### `config/`

Safe, non-secret application configuration, schemas, policies, and feature
settings. Prefer configurable settings over hard-coded business rules. Do not
commit credentials, tokens, secrets, account access information, or
machine-specific private values.

### `data/raw/`

Immutable source evidence from brokers, APIs, files, or manual imports.
Organize raw evidence by provider and market date where appropriate. Never edit
raw broker evidence in place. Raw evidence must not be used directly by the
website or dashboard.

### `data/normalized/`

Canonical broker-independent records produced from raw inputs. Normalized
records must follow OneJournal contracts and must not contain UI-specific
formatting. CSV files here are ingestion, transport, validation, or export
artifacts; they are not the primary live journal database.

### `data/journal/`

The journal's operational source of truth. DuckDB is the current journal store.
Journal state should be reproducible from validated inputs and recorded import
history wherever practical.

### `data/audit/`

Import runs, reconciliation results, validation history, important decisions,
execution evidence, and operational traceability.

Every important pipeline stage must answer:

- What was read and from where?
- Which as-of date was used?
- How many records were processed?
- What was written and where?
- What was skipped?
- What failed and why?

### `output/`

Generated and publishable artifacts only: dashboard payloads, reports, charts,
exports, human-readable summaries, and validation results.

Generated output is not the underlying source of truth. Do not manually patch
generated output to hide an upstream defect. Correct the producer and regenerate
the artifact.

### `src/onejournal/`

Reusable application, domain, financial calculation, service, and adapter code.
Business logic belongs here instead of being duplicated across operator scripts
or user-interface handlers.

### `scripts/`

Operator commands, imports, migrations, reconciliation jobs, validation tools,
controlled maintenance, and administrative actions. Scripts should orchestrate
reusable application code rather than become the permanent home of business
logic.

### `docs/`

Architecture decisions, data contracts, operator procedures, safety rules,
examples, and current workflows. Documentation must describe the current system
rather than an obsolete project phase.

### `tests/`

Automated unit, integration, contract, migration, and regression tests. Every
important defect fix should include a test that would have detected the original
problem.

## Canonical data flow

The intended data flow is:

```text
raw broker or manual evidence
-> broker adapter
-> normalized broker-independent records
-> validation and reconciliation
-> DuckDB journal state
-> trade lifecycle and P&L calculation
-> application or API service
-> dashboard payload or production website
```

The user interface must not parse raw broker files or perform heavy financial
calculations. Broker-specific adapters must not write directly to Streamlit
state, frontend state, or presentation-specific dashboard output.

For market-date workflows, use `--asof YYYY-MM-DD`. Do not introduce alternative
market-date flags such as `--date`, `--run-date`, or `--trade-date` without
explicit approval.

## Data and contract compatibility

Treat database schemas, JSON payloads, YAML structures, CSV formats, Python
interfaces, command-line flags, API requests and responses, published dashboard
fields, and import/reconciliation output as formal contracts.

A breaking contract change requires:

1. Explicit identification and impact analysis
2. Approval where material
3. Versioning where appropriate
4. Migration or compatibility handling
5. Updates to every affected producer and consumer
6. Updated examples and documentation
7. Contract and regression validation

Do not silently rename, remove, reinterpret, or change the units of a financial
field.

## Database safety

Before changing a database or database-related script:

- Inspect the current schema and representative data
- Confirm row counts and integrity checks
- Identify every reader and writer
- Determine whether the operation is reversible
- Establish backup and rollback procedures
- Test using a temporary database copy
- Validate migrations against realistic data

Use versioned migrations for durable schema changes and transactions where
atomicity is required.

Never experiment directly on the production journal database. Never silently
drop, truncate, overwrite, or reinterpret journal data. Destructive database
actions require explicit approval.

Validation must not modify the production journal database unless the validation
specifically requires it and the user approves the operation.

## Financial correctness

Every displayed financial number must be traceable to its source records and
calculation method.

Do not confuse:

- Cashflow with profit or loss
- Open premium with realized profit
- Market value with cost basis
- Orders with confirmed fills
- A position snapshot with a complete trade lifecycle
- Estimated values with broker-confirmed values
- Gross performance with performance after commissions and fees

P&L calculations must account for confirmed fills, quantities, multipliers,
commissions, fees, assignments, exercises, expirations, adjustments, corporate
actions, and appropriate market prices.

Clearly distinguish gross cashflow, realized P&L, unrealized P&L, total P&L,
cost basis, market value, commissions, and fees.

If required data is incomplete, show the result as unavailable, incomplete, or
awaiting reconciliation. Never invent, silently infer, or default a financial
value in a way that could mislead the user.

Financial calculations need focused unit tests and representative lifecycle
examples.

## Production website standards

Streamlit is the current internal prototype and workflow-validation surface. Do
not assume it will be the final production frontend.

Before selecting or changing the production web stack, present the viable
options, trade-offs, migration impact, hosting implications, and recommendation
for approval.

The production architecture should separate:

- Frontend and presentation
- Design system
- Authentication and authorization
- Application and API services
- Journal and portfolio domain logic
- Financial calculations
- Broker adapters
- Background imports and reconciliation
- Market data
- Future execution services
- Audit and observability

The production website must be visually polished, consistent, responsive,
accessible, keyboard navigable, fast, testable, deployable, explicit about data
freshness, and free of broker-specific presentation logic.

Loading, empty, stale, partial, and failure states must be designed deliberately.

A sleek appearance must come from a coherent design system covering typography,
spacing, colour, hierarchy, layout, responsive behaviour, interaction patterns,
charts, and reusable components—not scattered one-off styling.

Website changes require visual verification at appropriate desktop, tablet, and
mobile sizes.

## Security and privacy

Never expose credentials, tokens, private environment values, broker payloads,
account identifiers, holdings, journal notes, or personal financial information
through Git, logs, errors, screenshots, public URLs, frontend responses, test
fixtures, or generated reports.

Apply least-privilege access. Separate development, testing, paper-trading, and
production environments. Each environment must use independent configuration
and be clearly identifiable.

Authentication, authorization, session security, encryption, backup security,
audit history, and data retention must be designed before production launch.

## Legacy code

Existing code under `scripts/oldjournal/`, `scripts/tgps_user/`, and
execution-related folders is not automatically approved for reuse.

Before migrating or reusing legacy code:

- Understand its complete behaviour and external dependencies
- Identify broker-write capabilities and credential handling
- Check data, schema, and failure assumptions
- Separate reusable logic from obsolete workflow
- Add tests and adapt it to current OneJournal contracts

Do not connect legacy order-management code to the OneJournal website or journal
pipeline without an explicit architecture and safety review.

## Trading safety

Auto-trading is not currently active.

Journal, reporting, dashboard, import, and website code must never place, cancel,
replace, or modify broker orders.

Future trading functionality must use an isolated execution plane with explicit
order intents, schema validation, risk gates, position and buying-power checks,
exposure limits, duplicate-order protection, idempotency, market-hours controls,
paper mode, approvals where required, complete auditing, broker reconciliation,
emergency disable controls, and kill switches.

A strategy must never call a broker order endpoint directly. Do not enable live
trading merely because legacy order-related code exists. Execution capability
requires explicit approval.

## Environment reproducibility

Dependencies, supported Python versions, setup requirements, configuration
requirements, and operator commands must be declared accurately. A clean machine
should be able to reproduce the application using documented steps.

Do not rely on packages that happen to exist in one local environment but are
absent from the project dependency declaration. Lock or constrain dependencies
appropriately before production deployment.

## Observability and failure behaviour

Important operations should record run ID, start and completion time, as-of
date, resolved input and output paths, record counts, stage progress, warnings,
failures, failure reasons, and final status.

Failures must be actionable. Fail closed for incomplete financial evidence,
invalid imports, reconciliation mismatches, authentication uncertainty, database
migration failures, future trading risk failures, and ambiguous broker responses.

Do not silently continue after a material failure. A checker that prints errors
but exits successfully is defective and must not be trusted until repaired.

## Performance standards

Measure before optimizing. Keep heavy calculations, large raw payload processing,
broker calls, and long-running reconciliation outside the interactive website
request path.

Do not introduce caching without defining its source, key, freshness policy,
expiration, invalidation, failure behaviour, and authoritative fallback.

## Validation standards

Before implementation, define expected behaviour, expected output, failure
behaviour, compatibility requirements, validation evidence, and rollback method.

A change is not complete until it has been validated in proportion to its risk.
Use the smallest relevant combination of unit, integration, contract, migration,
regression, idempotency, reconciliation, payload, UI, visual, accessibility,
performance, and Git-state checks.

Validate both the changed component and downstream contracts. Do not weaken a
test or validation rule merely to make a failing change pass.

## Rollback readiness

Before risky changes, establish how to return to the previous working state
without losing raw broker evidence, normalized records, journal entries, manual
reviews, database history, audit records, or production configuration.

A backup is not valid until its restoration method is understood and, where risk
warrants it, tested.

## Git and change hygiene

Inspect Git status before and after work. The working tree must be clean (no
uncommitted changes) before starting any new work item. If it is not clean,
pause, resolve or explicitly set aside unrelated changes, then re-run the check
before starting substantive edits.
Preserve unrelated user changes.

Do not commit secrets, credentials, tokens, private environment files, raw broker
data, runtime databases, generated outputs, or personal financial information.

Keep changes focused. Do not mix unrelated cleanup, refactoring, and feature work
without approval.

Do not commit, push, deploy, synchronize, create a pull request, or modify
external systems unless explicitly requested. Respect instructions such as
"commit but do not push" literally.

## Documentation and architecture decisions

When behaviour, data flow, configuration, schema, or operator procedures change,
update relevant documentation, examples, and validation tools in the same
change.

Record significant architecture decisions and their reasoning, especially for
the production frontend, backend/API, database evolution, authentication,
authorization, hosting, background jobs, market data, broker integrations,
execution architecture, and security boundaries.

## Communication and decisions

Lead with the outcome and evidence.

For diagnostics, explain the exact source-level, database-level, payload-level,
configuration-level, schema-level, or runtime-level reason.

For proposed work, state current behaviour, desired behaviour, root cause or
missing capability, affected artifacts, impact map, smallest safe implementation,
validation method, rollback method, and risks or decisions requiring approval.

Whenever a work item reaches a point requiring project-owner approval, explain
each decision in human language before requesting approval. For each decision,
state what is being decided, why it matters, the risks of each option, the
implications, the benefits, the expected outcome, and the recommended option.

Do not hide uncertainty. Inspect and validate instead of guessing.

## Approval boundaries

Explicit approval is required before destructive file or data operations, live
database migrations, major framework changes, major dependency installations,
public contract changes, external deployment, VPS/production synchronization,
broker-account access, security-policy changes, order submission, pushing
commits, or creating pull requests.

When the user explicitly says `Proceed` after an action has already been
presented and approved, treat that instruction as authorization to execute the
approved action within its defined scope. Do not repeat the action or ask for
the same approval again. Pause only if a new risk, scope change, conflict, or
new approval boundary appears. This execution rule does not waive, combine, or
expand any approval boundary in this file.

## Unresolved decisions must not become assumptions

Do not silently choose or encode policy for:

- Target users or account tenancy
- Production frontend, backend, database, or hosting stack
- Authentication and authorization
- Base currency or foreign-exchange conversion
- P&L or tax-lot methodology
- Timezone conversion and trading-day boundaries
- Market-data providers and price freshness
- Data retention and deletion
- Backup and disaster-recovery policy
- Availability and performance targets
- Alerting and incident response
- Legal, privacy, regulatory, or tax-reporting requirements
- Automated-trading approval policy

When work reaches one of these boundaries:

1. Identify the decision explicitly.
2. Present viable options and trade-offs.
3. Recommend an option based on evidence.
4. Obtain approval before making it durable project policy.
5. Record the approved decision in the relevant architecture or product document.

Use stable identifiers, explicit units, decimal-safe financial calculations,
consistent timezone handling, deterministic processing, and idempotent operations.

Every important record and displayed metric must preserve enough lineage to
trace it to its source evidence, transformation, calculation version, and as-of
time.

## Definition of done

Work is complete only when:

- Current behaviour and the source of truth were understood
- The root cause or requirement was addressed
- The relevant dependency chain was inspected
- The implementation matches the agreed scope
- Financial and data contracts remain correct
- Relevant tests pass
- Downstream and failure behaviour were validated
- No unrelated user work was damaged
- Git state was inspected
- Documentation was updated where required
- The rollback path is understood
- Remaining limitations are reported clearly
