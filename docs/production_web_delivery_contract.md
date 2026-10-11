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

### Canonical browser routes

The browser URL places the data mode before the product area. This makes the
authority boundary visible and gives every page one predictable address:

| Mode | Canonical pattern | Examples |
|---|---|---|
| Demo | `/demo/<area>` | `/demo`, `/demo/portfolio`, `/demo/trades`, `/demo/journal`, `/demo/reports`, `/demo/data`, `/demo/settings` |
| Private local owner | `/local/<area>` | `/local/portfolio`, `/local/trades`, `/local/journal` |
| Future authenticated production | `/<area>` | Reserved until authentication, hosting, and production acceptance are complete |

Browser paths must come from one shared route registry. During the unlaunched
transition, earlier preview paths redirect to their canonical demo or local
path; they are compatibility aliases, not additional websites. API paths keep
their independently versioned contracts because an API version identifies a
data contract, not a browser site or release mode.

The owner approved this mode-first route correction on 2026-09-07. Runtime
checks proved every canonical route returns HTTP 200, the former root and local
suffix paths return HTTP 307 to their canonical destinations, demo navigation
stays under `/demo`, and private navigation stays under `/local`. The private
API remained stopped during this verification, so the local pages proved their
unavailable behavior without creating another financial-read audit row.

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

### Owner-approved Mac-first completion sequence: 2026-10-11

The owner approved completing the work that can be implemented and verified on
the Mac before moving to the eventual hosting environment. This is an execution
sequence, not a replacement of ADR-0018's production acceptance gate or an
approval of a different frontend, database, hosting, or security policy.

Continue local implementation, focused validation, documentation and source
delivery within the existing approved boundaries. Do not wait for a VPS to
prepare security, operational tooling, quality improvements or the release.
Do not require repeated approval for ordinary steps inside that scope. A new
material architecture/policy decision, changed financial acceptance, live
database operation, runtime activation/restart or external deployment still
requires its exact operating authority; the Mac-first instruction does not
grant those actions.

| Package | Complete or prepare on the Mac first | Evidence reserved for the eventual host |
|---|---|---|
| P1-09 / WEB-W10 | Reuse accepted Mac passkey/login/logout/recovery evidence; complete relevant dependency disposition, private-access/secret/audit review and portable security preparation. Document domain-bound enrollment and recovery requirements without inventing a production domain or changing the localhost RP. | Actual production domain/RP/TLS, enrollment, proxy/abuse controls and hosted private-route/session/recovery verification. |
| P1-10 / WEB-W12 | Resolve release packaging against ADR-0017, prepare versioned start/deploy/rollback and monitoring tooling, migration mapping and approved disposable rehearsals, and backup/restore procedures. Present unresolved recovery/retention/incident choices before encoding policy. | Target-environment isolation, approved production-state migration, private deployment, monitoring/alerts, recurring encrypted backup, host restoration and rollback. |
| P1-11 / WEB-W11 | Agree browser/device and performance targets; inspect/fix accessibility and critical journeys with safe fixtures; measure the candidate artifact and reuse valid evidence for unchanged components. | Focused checks of the deployed artifact and any behavior that depends on the actual host, network or supported device. |
| P1-12 / WEB-W13 | Prepare the exact release scope, known limitations, export/correction/deletion/closure procedures and Streamlit disposition proposal. Reuse the evidence collected above rather than run another unchanged full suite. | Dated end-to-end private production verification and explicit final owner acceptance. |

The roadmap remains the single completion tracker. Record scoped Mac evidence
there; do not mark a whole production package complete merely because its local
preparation is ready. The formal count remains 8/12 until the remaining package
acceptance gates are met. No second website, new feature scope, routine approval
ceremony or independent certification process is introduced.

The separately prepared financial refresh is maintenance of completed P1-08.
Review and exact acceptance of its changed results precede release preparation
and any separately authorized live update. Its pending publication neither
reopens P1-08 nor prevents the local work above.

This sequencing preserves the product vision, spreadsheet-to-capability mapping
and maturity boundaries; no strategic or operational maturity is advanced by
the planning decision. Rollback of this documentation is a focused source
revert; implementation changes retain their own scoped rollback methods.

### Mac frontend packaging rehearsal: 2026-10-11

`npm run package:mac-preview` prepares a movable frontend-only feasibility
candidate after a fresh build in a disposable copy of tracked public `web/`
source. It does not package the Python API, journal, security store, TLS files,
release authorizations or private configuration, and does not start anything.
It is not an approved private release or a replacement for the protected Mac
launcher. Keep generated output outside Git.

The producer reuses the pinned Vinext standalone emitter. The actual relocation
test exposed a missing runtime dependency: the application externals manifest
was empty, but Vinext's own server imports React. An in-project start would mask
this defect by resolving ancestor `node_modules`. The producer now adds the
existing lockfile-matched `react`, `react-dom` and `scheduler` packages without
installing or upgrading anything. It retains the public source lockfile in the
candidate and replaces the upstream wildcard-binding starter with a fixed
`127.0.0.1:4187` starter that clears inherited environment values before loading
the server. It does not load dotenv or accept HOST/PORT overrides. An existing
standalone directory or missing externals manifest blocks packaging; use a fresh
disposable build rather than overwriting an earlier candidate.

Build procedure, **in the disposable public-source copy only**, using the
declared Node runtime and an empty inherited environment:

```text
npm ci --ignore-scripts --no-audit --no-fund
npm run build
npm run package:mac-preview
```

Move the entire `dist/standalone` folder to a separate location with no ancestor
project dependency installation. Start its `server.js` with the declared Node
runtime in an empty inherited environment. It serves the public packaging
preview on port 4187; no package installation is required there. Do not use
`npm start`, the upstream wildcard starter or this candidate to restart the
protected site. If 4187 is occupied, stop: no existing process is replaced.

The corrected relocated Mac candidate contains 59 runtime packages and is
approximately 45 MiB unpacked. Vite, Wrangler, shadcn's generator and its
`proxy-addr` chain are absent from its top-level runtime installation. The
Reports demonstration and its 20 referenced script/style/font resources return
200; the legacy portfolio alias returns 307 to the canonical route. Both the
private portfolio API and access-session API return 404: the development proxy
is not present and no private backend was connected. Four focused packaging
tests and focused lint pass. The isolated preview is stopped after verification.
This evidence does not establish browser hydration, private authentication or
export journeys, Linux compatibility, dependency security clearance, monitoring,
backup/rollback acceptance or a complete frontend/backend release.

ADR-0017 remains authoritative. Its static React/Vite frontend avoids a second
application server; the current Vinext/Next-compatible preview requires Node
server rendering. This candidate proves the latter can be moved on the Mac,
not that it is selected for production. The next material decision is to align
the existing UI/routing with the accepted static topology (recommended), or
explicitly supersede that topology with a reviewed Node-server design. Do not
silently choose either through packaging. Trusted HTTPS, same-origin private
API routing, session/header preservation and the API/service package must then
be validated for the chosen design before any private runtime activation.

Impact: public build output and packaging tests only; no financial calculation,
API contract, private persisted state, accepted runtime or strategic maturity
changes. Rollback is a focused source revert and discarding this generated
candidate, not restoring any database. P1-10 remains incomplete and Phase 1
remains 8/12. The pending financial refresh still needs owner review and exact
acceptance before separately authorized publication.

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
| WEB-W03 | WEB-03 | COMPLETE | Design tokens, component grammar and responsive application shell | Open a local synthetic browser shell and assess whether it feels unmistakably OneJournal | `web/` shell implemented; build passes; desktop/mobile viewport checks show no horizontal overflow; owner approved the consolidated visual direction; no private data | Sol High for first design direction, then Terra Medium for implementation |
| WEB-W04 | WEB-04 | COMPLETE | High-fidelity responsive Today, Portfolio, Trades, Journal, Reports and Settings screens | Navigate realistic synthetic workflows across desktop and mobile | Seven synthetic routes return HTTP 200; demo/unavailable states are explicit; controls are focusable with visible focus styling; responsive checks pass at 1440x900 and 360x800; no provider or private-data access | Terra Medium; Sol High only for critical design review |
| WEB-W05 | WEB-05 | COMPLETE | Versioned read-only FastAPI foundation and typed frontend compatibility boundary | Use the web shell against safe deterministic API fixtures | `GET /api/v1/preview` publishes `onejournal.web-fixture.v1`; OpenAPI, decimal strings, UTC instants, explicit demo/unavailable quality, privacy-safe shape, focused API tests, full clean CI, frontend build, and loopback HTTP smoke pass. No direct DB/raw access | Terra Medium |
| WEB-W06 | WEB-07 | COMPLETE | Local-owner journal vertical slice | Browse real historical trades and journal state through loopback API; create an approved append-only review without Streamlit | Completed and owner-accepted on 2026-09-07 for the current local release scope. The v5 loopback API/UI uses the server-selected `0600` operational journal at migration 0021, passes read-only integrity, and exposes the active 267-lifecycle/539-execution history revision while retaining the prior 217-lifecycle/430-execution revision as append-only rollback evidence. ADR-0026 preserves 63 privacy-safe vertical presentation pairs. ADR-0027 preserves source-derived opening/closing phases, exact unique option-to-stock settlement links, and reason-coded expiration stories without changing review or P&L authority. Reviews and entries remain append-only; linked stock cards are only presentation-de-duplicated; ambiguous candidates fail closed; no provider order/account/transaction identity is exposed. The owner accepts the current experience for this release scope. Further visual refinement remains non-blocking enhancement backlog | Sol High for financial lifecycle review; Terra Medium for later bounded UI work |
| WEB-W07 | PNL-03, WEB-07 | COMPLETE | Canonical positions, approved marks, market value and unrealized P&L vertical slice | View a real portfolio with explicit as-of and evidence state | Completed and owner-accepted on 2026-09-07 for the demonstrated private single-owner local-only scope. The exact accepted 58-position result is stored in the mode-`0600` operational journal through migration 0023 as one run, 58 snapshots, 58 valuations, and one complete-total row. The process-start-authorized loopback API and canonical `/local/portfolio` route preserve as-of, source/run/snapshot/fingerprint/acceptance lineage, currency quantum, 58/58/58 independent metric availability, and complete totals. Exactly one value-free accepted-read audit row was written. Desktop, tablet, and mobile browser checks passed without horizontal overflow, and the stopped-API state failed closed with no synthetic, cached, or historical 48/10 FIFO substitution. The mode-first URL correction, focused frontend lint, the production build, authorization, journal-integrity, automatic-trading-disabled checks, and all 525 tests passed. Continuous acquisition, credential ownership, authentication, hosting, VPS work, deployment, broader or realized P&L, and trading remain outside this acceptance; no commit or push is included | Sol High for financial review; Terra Medium for implementation |
| WEB-W08 | Bounded PNL-06 through PNL-08 slices, WEB-07 | COMPLETE | Phase 1 account/symbol breakdown, date-filtered P&L history, export and quality-conformant views | Explore the accepted current portfolio and export the same bounded records and values | Completed and owner-accepted on 2026-10-05 for the demonstrated private single-owner local-only reporting scope, acceptance `ONEJOURNAL-WEB-W08-GATE4-OWNER-ACCEPTANCE-20261005-01`. Exact release `ONEJOURNAL-WEB-W08-REPORT-RELEASE-20260909-01`, fingerprint `506a4b49810e4da77f3880818a83425c835eb9cd25d08b1503dd95ed9d6ddb2c`, preserves one `Primary` account, 230 admitted allocations, 57 withheld scopes, 287 processed and zero pending, covering 2026-03-06 through 2026-09-04. PR #13 delivered implementation `c62531c` into canonical merge `eba4a4c`. The activated loopback API and `/local/reports` expose reconciled account/symbol breakdowns, date/account/symbol filters, explicit quality/count/reason and snapshot/provenance states, and exact-decimal CSV exports. Private JSON/CSV read-back matched accepted state; valid-empty and outside-coverage selections behaved correctly; desktop/tablet/mobile and keyboard/table access passed. Verification added 11 privacy-safe read-audit rows within the approved 16-row bound; row counts and contents of all 81 other compared tables/views were unchanged. No complete portfolio realized/total P&L, continuous acquisition, authentication, hosting, or trading is accepted. See `docs/phase1_reporting_release_contract.md` for the exact acceptance evidence and limitations. | Sol High for financial contracts and private acceptance; Terra Medium for bounded implementation |
| WEB-W09 | UXJ-05, UXJ-06, WEB-07 | LATER | Post-Phase 1 attachments, goals, habits and recurring review experience | Complete the private review workflow beyond Phase 1 entries and reviews | Attachment privacy/retention/recovery and financial-evaluation dependencies pass | Sol High for privacy policy; Terra Medium for implementation |
| WEB-W10 | WEB-06 | IN PROGRESS | Authentication, authorization, secure sessions, recovery and audit | Sign in to an isolated environment and verify owner-only navigation | ADR-0031's protected Mac pair, owner login/logout and bounded recovery checks are recorded. The 2026-10-09 source/dependency-reachability review found no additional confirmed critical defect in the inspected Mac owner workflow, without clearing all dependency alerts. Hosted domain/RP/TLS and recovery, production packaging/dependencies, proxy/abuse/access verification, and OPS-06 security-state/audit/incident procedures remain open. This is not hosted/production or Phase 1 acceptance. See `docs/mac_passkey_access_contract.md` | Sol High |
| WEB-W11 | WEB-08 | BLOCKED | End-to-end quality, accessibility, performance and browser/device coverage | Use the accepted flows on supported desktop, tablet and mobile targets | Accessibility target, performance budget, browser matrix, visual regression and E2E suite pass | Terra Medium; Luna Low for routine regression maintenance |
| WEB-W12 | OPS-01 through OPS-06 | BLOCKED | Environment, hosting, PostgreSQL migration, deployment, observability, backup and recovery | Use a synthetic staging URL, then a separately approved private-owner staging release | Staging identity, deployment/rollback, security, monitoring, restore and migration evidence pass | Sol High for architecture/security/migration; Terra Medium for automation |
| WEB-W13 | WEB-09, OPS-07 | BLOCKED | Production acceptance and Streamlit transition | Use the private production website for every accepted initial journey | Owner acceptance, financial parity, export/correction procedures, runbook and rollback pass; Streamlit disposition recorded | Sol High for final critical review; Luna Low for release-record maintenance |

## Delivery sequence and PNL-03 coordination

The near-term sequence is intentionally vertical:

1. Finish this foundation contract.
2. Build WEB-W03 and WEB-W04 as a local, synthetic, browser-visible product
   preview.
3. Define the WEB-W05 API contracts against safe fixtures.
4. PNL-03 authority, implementation, reconciliation, and bounded owner-private
   financial acceptance are complete; preserve that exact boundary in WEB-W07.
5. Deliver WEB-W06 so existing accepted journal capability is usable through
   the new application boundary.
6. Deliver the now-queued WEB-W07 against the accepted PNL-03 boundary, then
   deliver the bounded Phase 1 WEB-W08 breakdown, history, export, and
   displayed-quality scope.
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
