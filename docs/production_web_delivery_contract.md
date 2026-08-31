# OneJournal Production Web Delivery Contract

## Purpose

This contract turns ADR-0017 into a finite, visible delivery path from the
internal Streamlit prototype to a private production website. It controls the
web application boundary, experience principles, demonstration modes, work
breakdown, and acceptance checkpoints.

The product roadmap controls priority and status. Financial ADRs and domain
contracts remain authoritative for calculations, evidence, and quality states.
This document does not authorize implementation, dependency installation,
database migration, hosting, deployment, broker access, or private-data use.

## Approved foundation

| Concern | Approved direction | Boundary |
|---|---|---|
| Frontend | React and TypeScript built with Vite | No domain or authoritative financial calculation in the browser |
| Styling | Tailwind CSS with OneJournal-owned design tokens | No paid UI kit or template dependency |
| Components | shadcn/ui source using Base UI initially | Components are adapted into a OneJournal design system, not used as an unmodified generic theme |
| Charts | Apache ECharts behind OneJournal chart components | Charts consume versioned display contracts and show data quality and as-of context |
| Application API | FastAPI using reusable Python domain/application services | Browser never opens raw evidence, DuckDB, PostgreSQL, or generated payload files |
| Local state | DuckDB for current local journal, analytics, and rehearsals | No browser or public direct database access |
| Hosted state | PostgreSQL after separately approved migration | No production migration or hosted private data is approved by this contract |
| Long-running work | Auditable worker/job boundary | No broker acquisition or heavy reconciliation in an interactive request |
| Hosting | Self-hostable, vendor-neutral web/API/worker/database topology | Exact provider, target and release procedure remain OPS decisions |

## Product information architecture

The initial authenticated product navigation is:

1. **Today** — attention queue, portfolio state, recent activity, data health,
   and review prompts.
2. **Portfolio** — account and consolidated holdings, valuation, exposure, and
   history, subject to PNL-03 through PNL-08 acceptance.
3. **Trades** — searchable episodes, lifecycle, fills, costs, realized result,
   and evidence/quality context.
4. **Journal** — review queues, plans, entries, revisions, strategies, tags,
   mistakes, lessons, goals, and recurring reviews within approved privacy
   controls.
5. **Reports** — daily, monthly, custom-period, breakdown, and export
   experiences after canonical reporting contracts pass.
6. **Data & connections** — imports, reconciliation, freshness, broker
   connections, evidence status, and bounded operator actions.
7. **Settings** — owner profile, timezone display, accounts, privacy,
   retention, backup/export, security, and application preferences.

Broker names may appear as source and account context, but broker-specific
formats and behaviors must not define navigation or presentation contracts.

## Priority user journeys

### Understand the current state

The owner opens Today and can distinguish:

- the newest accepted as-of time;
- what is current, stale, partial, unreconciled, unavailable, or failed;
- account and consolidated scope;
- which items need attention; and
- where each displayed result came from.

### Inspect a trade and learn from it

The owner finds a trade by symbol, account, strategy, date, or review state,
opens its lifecycle and financial result, reads or adds private reflection, and
can trace the financial result separately from authored journal content.

### Review a portfolio without false certainty

The owner sees only PNL-03-approved positions and marks in authoritative mode.
An unsupported or unreconciled scope remains unavailable with an actionable
reason; it never becomes zero or an unlabeled estimate.

### Import and reconcile safely

The owner can inspect a proposed import, validation result, reconciliation,
counts, omissions, and failures before any separately authorized write. The web
experience does not silently refresh provider credentials or bypass operator
approval boundaries.

### Produce a reproducible report

The owner selects an account scope and period, sees exact as-of, source,
calculation and quality context, then generates an export that reconciles to
the same canonical result.

## Visual experience contract

### Character

OneJournal is a premium financial workspace: calm, focused, precise, modern,
and information-rich. The initial direction is dark-first with graphite and
deep navy surfaces, restrained luminous accents, crisp typography, strong
hierarchy, high-quality charts, and subtle motion.

The design must avoid:

- a generic admin-template or unmodified component-library appearance;
- excessive nested cards, decorative gradients, glow, or glass effects;
- dense spreadsheet imitation where hierarchy and progressive disclosure are
  more appropriate;
- green/red as the only encoding of gain, loss, validity, or failure;
- motion that delays interaction or obscures changing financial state; and
- fabricated activity, metrics, or claims used merely to make an empty screen
  look complete.

### Design tokens and components

WEB-03 must define and visually approve:

- semantic color tokens for surfaces, text, borders, focus, action, gain,
  loss, warning, stale, partial, unavailable, failure, and provenance;
- typography families, type scale, numeric alignment, tabular-number behavior,
  and content density;
- spacing, radius, elevation, divider, icon, and motion scales;
- application shell, navigation, command/search, page header, toolbar, filter,
  table, list, card, metric, badge, callout, dialog, drawer, form, timeline,
  audit/provenance, chart, skeleton, empty, unavailable, and error components;
- compact and comfortable density modes where justified; and
- reusable chart grammar for currency, percent, position, exposure,
  performance, distribution, and time-series views.

Exact token values and typefaces require rendered visual review. They are not
approved merely because they appear in source code.

### Financial presentation

Every material financial view must preserve:

- account and consolidation scope;
- currency and units;
- as-of or event time and display timezone;
- calculation or interpretation version where applicable;
- source, reconciliation, completeness, entitlement, and freshness context;
- unavailable and omission reasons; and
- navigation to deeper evidence or audit context without exposing secrets or
  unrestricted raw provider payloads.

Authoritative monetary values enter the API as decimal strings. TypeScript may
parse values only for controlled visualization and formatting; it must not
produce authoritative calculations or silently round stored values.

### Responsive and accessible behavior

Every production route must be visually inspected at representative mobile,
tablet, desktop, and wide-desktop sizes. The design must remain usable from a
360-pixel mobile viewport upward without clipped content or inaccessible
actions.

Production acceptance requires WCAG 2.2 AA as the target, including keyboard
navigation, visible focus, semantic structure, labels, screen-reader names,
contrast, zoom/reflow, reduced motion, and non-color status cues. Financial
tables may use a deliberate mobile transformation, horizontal region, or
detail drill-down, but may not hide material data silently.

## Data modes and truth labels

The application must expose its active mode persistently and unambiguously.

| Mode | Allowed data and behavior | Prohibited claim |
|---|---|---|
| `demo` | Committed non-private fixtures, synthetic scenarios, no credentials, no broker calls, no operational DB | Real account, current market, accepted P&L, or operational health |
| `local_owner` | Approved local private state through loopback FastAPI and existing domain services | Public availability, hosted security, or continuous provider operation |
| `staging` | Approved isolated environment and non-production identities/data; private data only after explicit security and migration approval | Production acceptance or authority |
| `production` | Explicitly approved authenticated owner scope, migrated state, monitoring, backup, recovery, and accepted financial capabilities | Any capability beyond its recorded acceptance scope |

Demo and real operating modes must not share a route, database, storage root,
or visual state in a way that can cause synthetic values to be mistaken for
real values. Screenshots and tests must not contain private financial data.

## API and application boundary

### Required API behavior

- Version public application contracts from the first route family.
- Validate input and authorization before domain or persistence work.
- Return decimal financial values as strings and instants with explicit
  timezone semantics.
- Return structured, privacy-safe quality and failure information rather than
  relying on HTTP success plus missing fields.
- Support deterministic request or operation identity for state-changing
  journal actions.
- Record audit context for sensitive reads and all accepted state changes.
- Paginate and filter server-side when datasets can grow materially.
- Generate an OpenAPI description and validate frontend compatibility against
  it.

### Prohibited API behavior

- raw SQL or direct database paths supplied by the browser;
- raw broker or credential proxy endpoints;
- browser-triggered token refresh or generic provider calls;
- order place, cancel, replace, or modify operations;
- authoritative financial calculation in request handlers when reusable domain
  services should own it;
- secrets, raw private paths, account numbers, unrestricted evidence, or stack
  traces in responses; or
- successful responses that conceal a material reconciliation, freshness,
  authorization, or persistence failure.

## Security and privacy gates

Before any private hosted mode, WEB-06 and OPS-06 must approve and validate:

- owner identity and account ownership representation;
- authentication, recovery, reauthentication, and administrative access;
- server-managed session cookies, rotation, expiry, revocation, and device
  behavior;
- CSRF, origin, content security, transport, rate-limit, and abuse controls;
- authorization at route, service, record, account, export, and attachment
  boundaries;
- secret storage and rotation outside source, images, logs, and frontend
  bundles;
- privacy-safe logs, audit records, support procedures, and screenshots;
- dependency, software-supply-chain, vulnerability, and threat-model review;
- retention, deletion, backup, restoration, incident, and breach procedures;
  and
- negative tests proving cross-scope access and unapproved operations fail
  closed.

The initial single-user scope reduces tenancy breadth; it does not remove these
requirements.

## Database and migration gates

PostgreSQL becomes a production runtime only after a separate approved plan
proves:

1. repository and transaction boundaries independent of DuckDB-specific
   presentation behavior;
2. schema mapping for identifiers, decimals, timestamps, JSON, constraints,
   migrations, and append-only history;
3. an export/import or replay source with exact lineage;
4. rehearsal against a realistic temporary copy;
5. row, identity, decimal-value, lifecycle, P&L, review-history, and audit
   reconciliation;
6. backup, restoration, point-in-time recovery, rollback, and failed-migration
   behavior;
7. concurrent reader/writer and idempotency validation; and
8. separate approval before any real journal or private evidence is migrated.

DuckDB remains valid for local analytical and operator workflows. PostgreSQL
does not become the source of raw broker evidence, and migration does not
weaken ODFS or evidence lineage.

## Phase 1 release boundary

ADR-0018 defines **Phase 1 — Private Owner Release** as the first operational
product, not merely the synthetic preview. Phase 1 is finite and requires the
twelve `P1` roadmap items to complete.

The web delivery packages map to Phase 1 as follows:

| Phase 1 need | Required web package or dependency |
|---|---|
| Approved foundation and product journeys | WEB-W01 and WEB-W02 |
| Distinctive responsive product shell and screens | WEB-W03 and WEB-W04 |
| Versioned application/API boundary | WEB-W05 |
| Private journal workflow | WEB-W06 |
| Broker-reconciled current positions and unrealized P&L | PNL-03 and WEB-W07 |
| Bounded current portfolio, account/symbol breakdown, date-filtered P&L history, export, and complete quality states for displayed metrics | Bounded accepted PNL-06 through PNL-08 slices and WEB-W08 |
| Authentication and owner-only access | WEB-W10 |
| Accessibility, responsive, browser and end-to-end quality | WEB-W11 |
| Private hosting, approved state, deployment, observability, backup, restoration and rollback | WEB-W12 |
| Dated owner acceptance and Streamlit disposition | WEB-W13 |

WEB-W09, additional brokers, continuous OneJournal-owned Schwab connectivity,
advanced portfolio-history series, advanced returns/drawdown/exposure/risk
analytics, public/multi-user features, and any trading automation are outside
Phase 1. They remain valid later roadmap work but cannot delay the Phase 1 exit
gate.

Completing a bounded Phase 1 slice does not mark a broader PNL or UXJ roadmap
item complete unless that item's full completion evidence also exists. Anything
displayed, even when optional for Phase 1, must satisfy its controlling
financial, privacy, and failure contract.

## Product work breakdown and visible acceptance tracker

The roadmap is the authoritative status record. This table defines the work
packages and the browser-visible checkpoint for each package. Before starting
each package, reassess the most cost-efficient sufficient GPT model and pause
if a switch is recommended.

| WBS | Roadmap | Initial status | Deliverable | What the owner can try | Completion gate | Expected model profile |
|---|---|---|---|---|---|---|
| WEB-W01 | WEB-01 | COMPLETE | Accepted open-source architecture and service topology | Review the approved decision and finite delivery route | ADR-0017, this contract, roadmap and maturity map agree; documentation validation passes | Sol High for architecture; Luna Low for later clerical maintenance |
| WEB-W02 | WEB-02 | COMPLETE | Information architecture and priority journeys | Review the intended navigation and task flows in this contract | Every initial route and priority journey has a defined purpose, authority boundary and unavailable behavior | Sol High for product contract; Luna Low for maintenance |
| WEB-W03 | WEB-03 | NEXT | Design tokens, component grammar and responsive application shell | Open a local synthetic browser shell and assess whether it feels unmistakably OneJournal | Desktop/mobile shell, core components, state gallery and visual review are approved; no private data | Sol High for first design direction, then Terra Medium for implementation |
| WEB-W04 | WEB-04 | QUEUED | High-fidelity responsive Today, Portfolio, Trades, Journal, Reports and Settings screens | Navigate realistic synthetic workflows across desktop and mobile | Approved loading, empty, demo, stale, partial, unavailable and error screens; responsive and keyboard visual checks pass | Terra Medium; Sol High only for critical design review |
| WEB-W05 | WEB-05 | QUEUED | Versioned read-only FastAPI foundation and generated frontend client boundary | Use the web shell against safe deterministic API fixtures | OpenAPI, schema, decimal/time/quality-state, privacy and failure-contract tests pass; no direct DB/raw access | Terra Medium |
| WEB-W06 | WEB-07 | QUEUED | Local-owner journal vertical slice | Browse real local trades and journal state through loopback API; create an approved append-only review without Streamlit | Existing domain services remain authoritative; read/write audit and replay tests pass; no broker call or public listener | Terra Medium; Sol High for financial/privacy review |
| WEB-W07 | PNL-03, WEB-07 | BLOCKED | Canonical positions, approved marks, market value and unrealized P&L vertical slice | View a real portfolio with explicit as-of and evidence state | PNL-03 policy, implementation, broker reconciliation, mark selection and fail-closed acceptance pass before authoritative UI enablement | Sol High for PNL contract/review; Terra Medium for implementation |
| WEB-W08 | Bounded PNL-06 through PNL-08 slices, WEB-07 | BLOCKED | Phase 1 account/symbol breakdown, date-filtered P&L history, export and quality-conformant views | Explore the accepted current portfolio and export the same bounded records and values | Every displayed metric reconciles, export matches the view, and ADR-0007 states are complete; broader advanced analytics remain later | Sol High for financial contracts; Terra Medium for implementation |
| WEB-W09 | UXJ-05, UXJ-06, WEB-07 | LATER | Post-Phase 1 attachments, goals, habits and recurring review experience | Complete the private review workflow beyond Phase 1 entries and reviews | Attachment privacy/retention/recovery and financial-evaluation dependencies pass | Sol High for privacy policy; Terra Medium for implementation |
| WEB-W10 | WEB-06 | BLOCKED | Authentication, authorization, secure sessions, recovery and audit | Sign in to an isolated environment and verify owner-only navigation | Security design accepted; negative authorization/session/recovery tests and review pass | Sol High |
| WEB-W11 | WEB-08 | BLOCKED | End-to-end quality, accessibility, performance and browser/device coverage | Use the accepted flows on supported desktop, tablet and mobile targets | Accessibility target, performance budget, browser matrix, visual regression and E2E suite pass | Terra Medium; Luna Low for routine regression maintenance |
| WEB-W12 | OPS-01 through OPS-06 | BLOCKED | Environment, hosting, PostgreSQL migration, deployment, observability, backup and recovery | Use a synthetic staging URL, then a separately approved private-owner staging release | Staging identity, deployment/rollback, security, monitoring, restore and migration evidence pass | Sol High for architecture/security/migration; Terra Medium for automation |
| WEB-W13 | WEB-09, OPS-07 | BLOCKED | Production acceptance and Streamlit transition | Use the private production website for every accepted initial journey | Owner acceptance, financial parity, export/correction procedures, runbook and rollback pass; Streamlit disposition recorded | Sol High for final critical review; Luna Low for release-record maintenance |

## Delivery sequence and PNL-03 coordination

The near-term sequence is intentionally vertical:

1. Finish this foundation contract.
2. Build WEB-W03 and WEB-W04 as a local, synthetic, browser-visible product
   preview.
3. Define the WEB-W05 API contracts against safe fixtures.
4. Complete the PNL-03 authority decision and implementation needed by
   WEB-W07. PNL-03 may proceed while visual feedback from the preview is being
   resolved, but it may not be bypassed.
5. Deliver WEB-W06 so existing accepted journal capability is usable through
   the new application boundary.
6. Enable WEB-W07 only after PNL-03 acceptance, then deliver the bounded
   Phase 1 WEB-W08 breakdown, history, export, and displayed-quality scope.
   Broader PNL-04 through PNL-08 completion remains later work where its full
   item gate is not already met.
7. Complete private-data security, hosted operations, staging, recovery, and
   production acceptance before exposing real owner data outside a local-only
   environment. WEB-W13 completes Phase 1 only when ADR-0018 and every `P1`
   tracker gate pass.

No more than two consecutive trust/backend work packages should complete
without either a browser-visible increment or an explicit statement that no
safe visible increment exists. A visual checkpoint does not upgrade financial
or operational maturity by itself.

## Validation matrix

| Area | Required evidence before relevant completion |
|---|---|
| Frontend correctness | Type check, lint, unit/component tests, production build, deterministic fixture smoke test |
| API boundary | OpenAPI compatibility, validation, decimal/time semantics, pagination/filtering, privacy-safe error tests |
| Financial fidelity | Canonical service comparison, exact scope/as-of/quality metadata, unavailable and omission behavior, no browser authority |
| Security | Negative authorization, session, CSRF/origin, rate-limit, secret, audit, dependency and threat-model evidence |
| Accessibility | Automated checks plus keyboard, focus, screen-reader semantics, zoom/reflow, contrast and reduced-motion review |
| Responsive/visual | Desktop, tablet and mobile render capture; clipping, hierarchy, density, state and chart inspection |
| Performance | Agreed page and interaction budgets measured with representative data before WEB-08 completion |
| Data migration | Temporary rehearsal, exact reconciliation, backup/restore, concurrency, idempotency and rollback |
| Operations | Environment identity, deployment/rollback, monitoring, alerts, backup/restore and incident rehearsal |
| Acceptance | Dated evidence, explicit scope, limitations and project-owner approval kept separate from implementation status |

## Explicit approval boundaries

Separate project-owner approval remains required before:

- installing the production web dependency set or creating the web workspace;
- accepting exact design tokens and high-fidelity screens;
- changing or publishing an API contract;
- changing authentication, authorization, privacy, retention, recovery, or
  security policy;
- adding or migrating a database, applying a migration, or writing real data;
- using private financial evidence or screenshots in web validation;
- selecting or provisioning a host, identity provider, database service,
  object store, email provider, queue, or secret backend;
- provider or credential access;
- commit, push, synchronization, deployment, public exposure, or production
  activation; and
- retiring Streamlit or changing the execution safety boundary.

## Rollback and supersession

Documentation rollback is a focused reversion or a later superseding ADR.
Implementation packages must each define their own rollback before work begins.
No rollback may delete raw evidence, journal history, audit records, or accepted
financial evidence.

The web application is replaceable. The canonical journal, domain contracts,
financial services, evidence lineage, and API version boundaries must remain
recoverable independently of any frontend implementation.
