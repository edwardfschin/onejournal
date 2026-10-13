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
The owner-reviewed bounded publication completed on 2026-10-11 as recorded below;
it neither reopens P1-08 nor completes a later package. Changed results continue
to require exact acceptance before a deliberately authorized live update.

This sequencing preserves the product vision, spreadsheet-to-capability mapping
and maturity boundaries; no strategic or operational maturity is advanced by
the planning decision. Rollback of this documentation is a focused source
revert; implementation changes retain their own scoped rollback methods.

### Mac frontend packaging rehearsal: 2026-10-11

Historical feasibility evidence below applies to commit `cc1fa8a`. The owner
subsequently approved alignment with ADR-0017; the static implementation below
supersedes this Node-server candidate and its packaging command. It is retained
as evidence, not a current operator procedure.

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

### Approved static alignment and Mac preparation: 2026-10-11

The owner approved implementation of the already accepted ADR-0017 static
React/Vite plus Python API design, preserving the existing UI and financial
contracts, with local validation, commit and push but no live changes. This is
implementation conformance, not a new stack/policy decision or release acceptance.
It does not change the vision, spreadsheet mapping or capability maturity.

Impact map:

- Source: tracked React screens and `web/lib/routes.ts`; the existing Python
  API and passkey gate remain financial/access authorities.
- Producer: pinned Vite/React build; `web/dist` contains only static HTML,
  lazy page modules, CSS, existing locally packaged Geist fonts and a versioned
  route manifest. No raw/private data, TLS files, credentials or Node packages.
- Changed components: browser entry/navigation, build configuration and locked
  dependency pruning; development launchers now invoke Vite directly.
- Consumers: the 14 unchanged canonical demo/local screens and their existing
  same-origin APIs. The Python adapter validates the generated route contract,
  serves exact public shell/assets and mounts the unchanged protected API.
- Persisted state: none for this preparation. The prepared serving command
  uses existing private journal/release/security/TLS state only when separately
  activated; normal API writes/security audits retain their existing semantics.
- Validation: clean locked install, build/type/lint checks, route and API-client
  contracts, disposable signed access/CSRF/logout/expiry and static isolation,
  relocated public browser rendering at desktop/tablet/phone sizes.
- Rollback: revert this source change. The watched canonical checkout and
  active services were deliberately left unchanged, so no live rollback occurs.

`npm ci --ignore-scripts --no-audit --no-fund` and `npm run build` in `web/`
produce the portable artifact. Copy the **entire** `dist` directory, not a
subset. A clean destination needs the locked Python/security application
environment, not frontend source or Node packages. Fonts are the existing
cached Google Fonts Geist/Geist Mono binaries, unmodified and redistributed
with their SIL OFL 1.1 notice; runtime/build font downloading is no longer needed.
Recharts remains unchanged; the separate ECharts conformance question is not
silently included in this framework alignment.

Every built `/local/` page always checks the existing passkey session before
its child view mounts. Native links preserve history, keyboard and new-tab
behavior, checking access afresh at each private destination. Legacy paths
redirect to the mode-first canonical route and preserve the query string;
the browser entry additionally preserves fragments. Unknown API/export paths
never receive an HTML shell. Missing/incompatible manifests or an unprotected
backend fail before serving; only assets/fonts/favicon and exact shell paths
are public. Local Host/Origin checks and no-store/frame/privacy headers apply.
The adapter propagates the protected API lifespan, including session revocation
and security-store closure on shutdown. No server rendering is involved.

Prepared activation entry point, **not executed against owner state in this
pass**; uppercase values are placeholders, not commands to run literally:

```text
python scripts/web/run_mac_static_site.py --owner-local --web-config PRIVATE_CONFIG --security-db PRIVATE_SECURITY_DB --tls-cert PRIVATE_LOCALHOST_CERT --tls-key PRIVATE_LOCALHOST_KEY --static-dir ABSOLUTE_COPIED_DIST
```

It serves the static frontend and protected Python API in one loopback HTTPS
process at the configured existing website port, with the same localhost RP,
cookie origin and release authority. It does not provision access, migrate a
database, fetch a broker, select a new financial release, install dependencies
or terminate another process. Occupied ports fail; Ctrl-C stops this process
only. The bind check uses the same `SO_REUSEADDR` semantics as Uvicorn:
recently closed TCP connections are not mistaken for active listeners.
An immediate-restart regression and the real-listener refusal check cover
this distinction. The legacy development launcher remains available with direct Vite and
its existing loopback API proxy. Vite preview is only a public/demo check,
not the private release server ([Vite deployment guidance](https://vite.dev/guide/static-deploy.html)).

Scoped evidence: 19 focused frontend tests and 29 Python route/launcher/static
integration tests passed; one pre-existing opt-in full launcher process smoke
was not run. Locked build, TypeScript and lint passed. Real signed synthetic
WebAuthn verified private reads/exports, CSRF rejection/acceptance, logout,
idle expiry, headers, origin/host rejection, asset traversal isolation and API
shutdown. The copied static artifact rendered via Python with no Node server:
Reports at 1440x1000, portfolio at 820x1180 and 390x844, with no measured page
overflow at tablet/phone sizes. A private Reports URL with no connected access
service remained locked and displayed no financial view. These browser checks
were public-only HTTP fixtures; HTTPS/security integration used disposable
TestClient state, not an owner device or live private browser journey.
The direct Vite development entry point also started on an isolated port:
the canonical page returned 200, the query-preserving alias 307 and the absent
API a JSON 404. Headers were verified before redirects/API handling, not just
on served files; a focused regression check preserves this ordering.

Remaining: authorized Mac handover with trusted HTTPS and an owner-device
private navigation/export check, plus
remaining operations/quality/security acceptance. No live journal/security
write, accepted website change, restart, broker call or financial refresh
publication was performed. Formal Phase 1 remains 8/12; changed financial
results still require exact owner acceptance before publication.

### Installed Mac release packaging: 2026-10-11

The next approved preparation moves the existing static-service orchestration
into `onejournal.mac_static_site`, with the installed `onejournal-mac-site`
entry point. The source command remains a thin compatibility wrapper. The
unchanged API factory validates the existing migrated journal and exact
financial authorizations; no migration scripts are needed on its serving path.

Impact: committed Python/React source and existing locks are authoritative;
`scripts/web/package_mac_release.py` builds a wheel and complete static website
from one clean HEAD snapshot. Its consumers are a separate Python environment
and the existing same-origin browser/API contracts. No persisted owner state,
financial method, dependency version or access policy is changed. Private files
must stay outside both public code and the static artifact. Validation covers
non-overwrite/privacy guards and a relocated installed HTTPS service with
synthetic access/journal state. Rollback preserves the previous environment and
launcher; this preparation leaves the running Mac services untouched.

From a clean committed checkout, with existing build dependencies installed:

```text
python scripts/web/package_mac_release.py --destination NEW_EXTERNAL_RELEASE.tar.gz
```

The destination must be a new `.tar.gz` file in an existing directory outside
Git. The producer snapshots **tracked HEAD only**, builds in a disposable
directory, and refuses links, private-key/token signatures or overwrite. It
does not copy ignored `.env`, old build output or untracked public assets.
The archive contains one application wheel, both existing Python lock files,
the entire static build, installation instructions and SHA-256 file hashes
bound to the source commit. Checksums detect changes, not signer authenticity.
No private configuration, journal, access store, TLS material, broker evidence
or operator/migration scripts are included.

Install the pinned requirements and wheel into a **new** Python 3.11–3.13
environment, following `INSTALL.txt` in the archive. Dependency installation
requires package-index or cache access; this is not an offline Python/runtime
bundle. The installed service requires neither Node nor a source checkout.
Its serving arguments and explicit Mac activation boundary are unchanged.
Evidence: a 58-file public archive from source commit `ba476b0` was installed
non-editably into a fresh Python 3.13.9 environment using the unchanged locks;
dependency consistency passed. The relocated service started on a separate
loopback HTTPS port with no Node executable in PATH and no source import.
Explicit test-client certificate trust, real ES256 synthetic passkey login,
private journal search, CSRF denial/acceptance, append/replay, logout and owned
process shutdown passed. Startup left the disposable journal byte-identical;
the deliberate API write affected that synthetic database only. File hashes
were verified after archive relocation. Five focused packaging/activation
guards and five existing static/access integration checks passed. The first
restricted-process attempt timed out; the local-process-authorized rerun
passed, and test cleanup now bounds termination of its own process even on
failure. No owner journal, security store, system certificate trust, watched
checkout or running service was changed. These checks do not substitute for
the actual owner-device navigation/export handover.

No Linux/VPS portability, hosted deployment, production security clearance or
owner-device acceptance is claimed. Phase 1 remains 8/12.

### Approved Mac installed-release handover: 2026-10-11

Following the packaging checkpoint, the owner instructed the next controlled
Mac switchover. The corrected public release from `19b0bd8` is installed in a
new permanent environment outside Git and private evidence, and now serves
both static frontend and protected API at the existing
`https://localhost:4173`. It has one loopback Python listener and no Node
runtime or separate listener on port 8765. Existing localhost RP, certificate,
private configuration, journal and exact financial authorizations are reused.

Impact: the committed wheel/static artifact is the release input; the existing
journal and release authorizations remain financial authorities. Only the
inspected OneJournal process groups were stopped gracefully, followed by the
owned replacement process. No source synchronization, schema migration,
financial release selection/publication, enrollment/recovery, broker access,
hosting or security-policy change was included. Restart removes volatile
sessions, not saved passkeys. Normal value-free access auditing is retained.

The first startup was refused. Inspection and a disposable socket reproduction
identified a restart defect: plain bind failed with `EADDRINUSE` on a recently
closed connection while Uvicorn-compatible
`SO_REUSEADDR` succeeded. The minimal correction retains refusal of actual
listeners; six focused packaging/admission checks passed, including immediate
restart and an active listener already using `SO_REUSEADDR`. The corrected
release was built from clean committed source and installed separately; neither
previous environment was patched in place.

Read-only preflight validated the artifact hashes, installed module, existing
schema/release authority, private permissions and TLS. Live checks verified
HTTPS shell/assets, query-preserving canonical redirect, existing-passkey
session state and anonymous CSV denial. The journal, exact authorizations,
private configuration and TLS files remained byte-identical. Two intentional
anonymous export checks across the temporary/corrected static processes each
added one normal value-free access-denial event; no financial endpoint was
admitted and no journal read-audit or manual write was requested.

The canonical checkout at `cc1fa8a` and its original environment are preserved
unchanged for rollback. The installed public artifact/environment are
permanent, not served from a temporary folder. The current start and protected
rollback commands are in `docs/operator_quickstart.md`; stop only the owned
installed process before rollback, never overwrite private state or bypass
authentication. No daemon, scheduler or automatic-login service was added.

The owner completed the installed-release device check on 2026-10-11: real
passkey sign-in and opening Portfolio worked in the external browser. The
owner-supplied Reports current-positions CSV matched the exporter schema, with
consistent row widths, no duplicate position keys, valid decimal/date fields,
consistent release/selection lineage and matching metric availability fields.
The private CSV and its financial contents remain outside Git. This closes the
bounded Mac handover check; it is not a new financial reconciliation, freshness
claim, hosted acceptance or final Phase 1 acceptance. Phase 1 remains 8/12;
the financial refresh and remaining security, operations, quality and final
owner-acceptance work were separate at this handover checkpoint. The subsequent
approved financial publication is recorded below.

### Installed migration-resource correction: 2026-10-11

Preflight for the owner-approved October financial publication found that the
installed wheel lacked the exact SQL files used by history checksum guards.
The correction includes the authoritative `scripts/journal/migrations/*.sql`
bytes under the environment's `share/onejournal/migrations` directory. All
checksum consumers use the shared migration-directory resolver: source runs
retain the existing repository path, installed runs use their own prefix.
The public source archive includes those tracked SQL inputs; operator scripts,
private state and credentials remain excluded. No SQL, financial calculation,
checksum requirement or startup migration behavior changes. Three focused
resource-routing checks passed. The corrected `fc80998` public artifact was
installed in a separate permanent environment; every authoritative SQL file
matched its source bytes and the static frontend remained byte-identical.
Installed API/export validation on a disposable copy also passed before live
publication. These checks preserve checksum guards rather than bypass them.

### Owner-reviewed Mac maintenance publication: 2026-10-11

The owner reviewed the private refreshed results and approved the recommended
bounded publication. A verified fresh backup and copy rehearsal preceded exact
migrations 0027/0028, append-only history/financial/report persistence and a
controlled protected restart with new exact authorizations. Previous journal,
report and audit rows are retained; exact financial evidence and configuration
locations are recorded only in private receipts.

The new installed runtime uses source `fc80998` and the unchanged static
frontend. Installed-copy checks matched portfolio, breakdowns, history and CSV
decimals, with outside-coverage unavailable behavior. Live checks verified the
trusted HTTPS shell, retained enrollment, one loopback Python listener, no
separate API listener and anonymous export denial. The denial added one normal
value-free access-audit event; no authenticated live financial read was made.
Owner sign-in after this restart has not yet been confirmed. Saved passkeys,
TLS and security policy are unchanged; no additional broker requests, orders,
canonical synchronization or hosting work occurred.

Old configuration, history/report authorities, installed environments and two
verified Mac backups remain private rollback evidence. Existing encrypted USB
images retain their earlier dated scope. Saved values remain dated snapshots;
unavailable and withheld financial scopes are not silently filled. Publication
closes maintenance, not production security/operations/quality or final owner
acceptance. Phase 1 remains 8/12. Current start/rollback instructions are in
`docs/operator_quickstart.md`.

### Focused Mac quality candidate: 2026-10-12

The owner approved the next Mac-first accessibility/performance increment.
An isolated loopback preview used the installed public frontend first, then the
rebuilt candidate, with synthetic responses only. It never connected to the
private journal, passkey store, broker or running protected site.

Two small presentation corrections were validated:

- Reports, Portfolio and the shared Trades/Journal template now reuse the
  existing overview-page `Skip to content` link, visible-focus style and a
  unique programmatically focusable content target. This provides a consistent
  keyboard shortcut past repeated navigation, following
  [W3C's bypass-block guidance](https://www.w3.org/WAI/WCAG22/Understanding/bypass-blocks.html).
  No blanket WCAG conformance claim is made.
- The shared Trades/Journal search box can shrink within its flex header.
  Before correction, a 320-CSS-pixel viewport produced a 352-pixel page width;
  afterwards both routes stayed at 320 pixels without hiding the search action.

Keyboard-only menu/navigation, skip-target focus, history submission, focusable
table scrolling in both directions, captions/column headers and download-button
focus were checked. Synthetic unavailable reporting removed tables/downloads;
locked access did not mount a financial view. Desktop, tablet and phone views
were inspected, including 320-CSS-pixel reflow. This is not a physical-device,
native browser-zoom or screen-reader speech check.

One unthrottled local candidate sample recorded first contentful paint at 76 ms,
account/symbol reports ready at approximately 350 ms, and a 300-row synthetic
history rendered approximately 26 ms after keyboard submission. Small
diagnostic markers were confined to the disposable preview shell. These are
local measurements, not statistical benchmarks, real-network/host results,
production guarantees or newly approved performance budgets.

Both focused regressions detected their original omissions and passed after
correction. Scoped type-aware lint and the production frontend build passed.
The impact is four presentation sources plus a focused regression file; API
contracts, financial calculations, private persisted state and access policy
are unchanged. Rollback is a focused source revert/rebuild. No runtime install,
restart, canonical synchronization or financial read was performed. The
candidate is not the currently installed release. P1-11/WEB-W11 local work is
in progress; supported browser/device choices, actual zoom/screen-reader checks,
agreed performance budgets and final environment acceptance remain open.
Phase 1 remains 8/12.

### Approved Mac quality installation: 2026-10-12

The owner instructed the next presented UI-only installation/restart. The
public wheel/static package from clean pushed source `c173b88` was verified and
installed into a new permanent Mac environment with the unchanged pinned
dependencies. Exact artifact hashes, installed imports, dependency consistency,
bundled migration SQL and read-only configuration/authority validation passed
before interrupting the existing site.

Only the identity-verified owned OneJournal listener was stopped gracefully.
The handover waited for actual process completion, not merely a closed port,
before recording the private unchanged-input baseline. The replacement serves
the new keyboard/reflow corrections at the same protected loopback HTTPS origin.
Trusted HTTPS, the exact new static shell/changed assets, retained enrollment,
new-session requirement and anonymous financial denial passed. The journal,
authorizations, active configuration and TLS files remained byte-identical.
The denial produces its normal value-free security audit event; security-store
byte identity is not claimed. No authenticated financial request was made.

The private foreground startup shortcut now selects the new installed release
explicitly. The previous environment/static artifact and shortcut are retained
for UI-only rollback using the same current private configuration. There was
no migration, financial publication/calculation, broker call, passkey recovery,
policy change, canonical synchronization, daemon or hosted deployment. Detailed
receipts and private file locations stay outside Git. The owner confirmed
passkey sign-in and the updated site after this restart; earlier synthetic visual/keyboard validation
is not repeated or relabeled as owner acceptance. P1-11 remains in progress and
Phase 1 remains 8/12.

### Bounded native-browser follow-up: 2026-10-12

The owner instructed the next accessibility checks. A separate Chrome window
served the current installed static artifact with synthetic responses on an
isolated loopback port, not the private API. Native Chrome reported 200% page
zoom; the enlarged Reports heading/navigation/action layout remained readable,
and Load history rendered the synthetic 300-row result with explicit partial
coverage. The native accessibility tree exposed table names, column/row headers
and labeled date/account/symbol controls. No source defect was established by
this bounded check, so no implementation change or broad suite was added.

VoiceOver activation/control could not be established through the connection;
read-only process inspection confirmed it was not running. Screen-reader speech
is still unverified, not a passed test. This is one native Chrome check, not
an approved full browser/device matrix or blanket accessibility conformance.
Browser control was interrupted during cleanup; the temporary test window may
remain open. Only the owned synthetic server was stopped; the protected site
was not restarted and no broker/data publication was requested. Phase 1 remains
8/12 with P1-11 in progress.

### P1-09–12 Mac completion checkpoint: 2026-10-13

The owner directed resuming P1-09 through P1-12 on the Mac, keeping history
recovery separate and reusing unchanged evidence. This authorizes ordinary
local implementation, critical validation, documentation, commit and push;
it does not activate a new release, accept financial figures, change policy,
perform live restoration or authorize hosting/broker operations.

One missing operational component is now implemented:
`scripts/web/check_mac_release.py` delegates to the reusable
`onejournal.mac_release_check`. It consumes an existing public v1 release,
independent manifest/source pins and optionally the exact localhost HTTPS
origin. It verifies file inventory/hashes and the static route contract, then
reads only the public shell and cookie-free access status. It opens no
database, logs no response body, authenticates no owner, creates no session or
audit event in the inspected status flow, and performs no automatic repair.
Integrity pins must come from a separately trusted receipt; this is not signer
authentication or package-vulnerability clearance. Failure is value-free and
nonzero, never an HTML-200-only readiness claim.

Nine focused checks passed: immutable file validation, independent pins,
missing/extra/changed/link/traversal/scope rejection, system-verified TLS settings,
exact two cookie-free GETs, response/header and enrollment failure, non-local
origin refusal, paired independent certificate pins with verification retained,
value-free CLI failure and a disposable status read without
financial access or security-state mutation. No frontend source changed, so
no frontend rebuild, layout cycle or unchanged full suite was repeated.

The current installed public files matched the independently retained original
archive and prior handover source identity. The initial live connection check
received connection refusal; it did not establish HTTPS/access readiness and
did not start, repair or switch the service. A subsequent authorized start/check,
if performed, is recorded separately; source checks are not runtime acceptance.
Detailed artifact pins and operating receipts remain private.

`docs/operator_quickstart.md` now provides the on-demand check, bounded
failure/recovery actions and truthful export/correction/closure limitations.
These are existing fail-closed mechanisms, not newly adopted service/retention
budgets. There is no automatic scheduler, silent restore, legacy fallback,
credential reset, deletion or Streamlit retirement.

The release preparation uses existing evidence as follows:

| Package | Mac evidence reused or delivered | Still required; do not invent or claim passed |
|---|---|---|
| P1-09 | Installed protected passkey boundary; owner sign-in/logout/two-tab lock; offline revocation/re-enrollment; existing dependency reachability review; source-pinned artifact/access-status check. | Candidate-specific dependency/security disposition before exposure; owner-approved audit/incident/retention choices; actual host/RP/TLS/enrollment/proxy/abuse verification. |
| P1-10 | Installed static/Python package and retained rollback; dated encrypted access, journal/release and evidence/audit image restoration; on-demand integrity/connection check and actionable runbook. | Backup cadence/retention, recovery objectives and alert/incident choices; another-Mac/host restore and target-dependent state/migration/deployment/rollback verification. |
| P1-11 | Existing keyboard/reflow/contrast, synthetic failure/export/session and local timing evidence; native Chrome 200% zoom/table semantics; unchanged frontend not retested. | Chosen browser/device scope and performance budgets; actual screen-reader speech and only uncovered critical journeys; final target checks. |
| P1-12 | Exact current artifact/configuration/release identity remains in private receipts; limitations and operator export/correction/closure procedures are explicit; history expansion and advanced features are separate. | Approved retention/deletion/closure and Streamlit disposition; dated final operating scope, target-dependent end-to-end verification and owner acceptance. |

This is the finite remaining list, not a new certification programme. Resolve
the owner choices once as a coherent operating scope, reuse dated valid
evidence and run only checks affected by the eventual target or changed code.
Do not make complete lifetime history or continuous website broker refresh a
Phase 1 prerequisite. Formal Phase 1 remains 8/12; Mac preparation is not
hosted acceptance. The product vision, strategy mapping and maturity claims
are unchanged. Rollback is a focused source revert; no private restoration or
runtime change is needed to undo this source-only delivery.

### Same-release Mac start and completed transport check: 2026-10-13

The owner authorized starting the same protected release and finishing the
pending check. The existing shortcut command matched its retained handover
intent; public files and TLS setup matched independent receipts, and the port
was unoccupied. The unchanged shortcut started installed `c173b88` in the
owner's Terminal, not the newer checkout. One loopback listener matched that
existing command/configuration. The private configuration, exact financial
authorization files and TLS bytes also matched the retained operating baseline;
that comparison did not open the journal. The public checker passed: exact Reports shell,
verified TLS/privacy headers and anonymous enrolled access status, using only
two cookie-free GETs. No financial request, login ceremony, broker call,
migration, repair or requested audit write occurred.

Startup normally opens existing application stores and resets volatile sessions;
unchanged store bytes or new owner-login acceptance are not claimed. Saved
enrollment is retained. The original connection-refusal receipt is preserved,
and new operating evidence remains private. Keep the foreground Terminal open.
No installation, daemon, trust change, financial publication or history
activation was performed. The actual unchanged checker was exercised once;
unchanged unit/build/browser/USB checks were not repeated. This closes the
pending transport check, not the remaining Phase 1 packages.

### Combined operating choices — accepted Mac testing profile: 2026-10-13

**Status: owner-approved for bounded Mac testing.** The owner explicitly
approved the combined profile and remaining Mac work, including commit/push,
while keeping history separate. This profile is limited to Mac testing, not hosted
production. Existing passkey/session/CSRF and offline-recovery controls stay
unchanged. Acceptance activates no automation, deletion or new
financial authority.

| Choice | Accepted Mac trial setting |
|---|---|
| Browsers and accessibility | Existing Mac, supported Chrome and Safari; record tested versions without unnecessary upgrades. Keyboard core journeys and one Safari/VoiceOver speech check. Reuse unchanged 200% text-resize and 320-CSS-pixel reflow evidence. Actual phone/tablet and hosted checks remain for soft launch. |
| Speed | Usable private page within 2 seconds after authentication; ordinary local filter/history update within 1 second for up to 300 displayed rows. Exclude device-verification waiting. These are initial targets, not proven real-data performance: measure once and fix confirmed failures, not speculative bottlenecks. |
| Backup | New encrypted journal/release image after a day of journal edits and after approved financial publication. Refresh evidence/audit after new accepted source lineage and weekly during active use. Refresh access/TLS only when setup changes. Use quiet/stopped sources as existing operators require; unchanged days need no new journal image. |
| Loss and recovery goals | Target at most one working day of unbacked-up journal edits and up to one week of security-audit lag, provided the owner performs those manual backups. Target usable restoration within one working day after recognizing a failure. The same-Mac restored-service signed-client rehearsal passed on 2026-10-13; owner-hardware re-enrollment and another-Mac/host recovery are not proven by it. |
| Retention and passwords | Preserve current recovery images, raw evidence, journal revisions and audit during the Mac trial; no automatic expiry/deletion. Keep image passwords separately from USB. Review space if needed; decide hosted retention later. Do not restore old passkeys/counters as a shortcut. This is not indefinite production retention. |
| Availability and incidents | Attended foreground use, no 24/7 uptime promise. Use the check after a release switch or startup/error concern, not continuously. Terminal-visible failures, no external alert service. Suspected exposure: stop only the owned private service and preserve evidence. Incorrect figures: stop using affected output; stop serving if it cannot be safely isolated. Ordinary outages: troubleshoot on next use, never bypass login. |
| Corrections, closure and release | Corrections remain source-reviewed/append-only. Closure/deletion requires a deliberate offline inventory and decision, not automatic SQL erasure. Leave Streamlit parked as internal reference, not a running fallback. Reuse accepted bounded financial scope and explicit stale/unavailable states; finish missing critical journeys and one dated final acceptance. History and hosting stay separate. |

These numbers are accepted trial targets, not guarantees or industry-mandated
thresholds. Manual encrypted backup preserves owner password custody but
depends on the owner doing it; no scheduler or reminder is enabled here. Existing
verified images retain their exact dated scope and are not recreated for this
acceptance. No retention cleanup, browser upgrade or production policy is adopted.

The accessibility scope draws on W3C's
[text-resize](https://www.w3.org/WAI/WCAG22/Understanding/resize-text.html) and
[reflow](https://www.w3.org/WAI/WCAG22/Understanding/reflow.html) guidance and
[Apple's VoiceOver web commands](https://support.apple.com/guide/voiceover/web-commands-vo27972/mac).
One speech check is not comprehensive WCAG conformance; necessary table
scrolling and existing semantic evidence remain relevant.

Implement only exposed gaps within this accepted scope; do not create routine
approval gates or repeat unchanged evidence. Exact
live restore, runtime switch, credential, broker, financial publication and
hosting authority remain separate. Formal Phase 1 stays 8/12; strategic scope
and ADR-0018's production exit gate are unchanged.

### Accepted-profile browser check and remaining Mac evidence: 2026-10-13

The unchanged installed `c173b88` static files were served on a separate
loopback port with synthetic session/report responses. No private configuration,
journal, security store or broker connection was opened by this preview; it
cannot enroll/sign in an owner. Fixture injection and timing instrumentation
were confined to the disposable response, not installed release files. The
synthetic account and numbers are not owner data or financial acceptance.

| Environment | Reports ready from navigation | Keyboard-submitted 300-row history |
|---|---|---|
| macOS 26.3.1 (a), Chrome 155.0.8059.40 | 1,318 ms | 75 ms |
| Same Mac, Safari 26.3.1 | 642 ms | 89 ms |

Both samples meet the accepted 2-second page and 1-second interaction targets
for this fixture. Readiness required the two current tables; history required
300 rendered rows, with two animation frames before recording. Chrome's skip
link focused `workspace-content`; Chrome Enter and Safari Option-Tab/Space
submitted the history action. Both showed the partial/withheld context rather
than implying complete history. This checks the static rendering/client path,
not real private API latency, actual passkey timing, every route or hosted
performance. Unchanged export/security/reflow evidence was reused; no build,
dependency installation, financial refresh or repeated full suite was needed.

VoiceOver was visibly off initially. Its system switch could be enabled, but
the control connection did not expose actual speech/caption output. It was
restored to visibly off. The speech check is **not passed**; Safari accessibility
semantics and an enabled switch are not substitutes. Temporary preview tabs
were closed and the separately owned fixture server stopped; the protected
site was not restarted or replaced.

The finite remaining Mac acceptance evidence is:

- One actual Safari/VoiceOver reading of a Reports heading, filter/action and
  table context, with owner-heard output; then restore the owner's setting.
- A complete restored-service journey from the existing recovery images into
  fresh private locations, compatible installed runtime and fresh offline
  access setup. Existing encrypted file/schema/release restore evidence is
  retained, but does not establish a timed usable-service recovery. Owner
  password/device custody is required; no live overwrite or old-counter restore.
- A dated owner check/acceptance of the exact operating release and limitations,
  including real-data page responsiveness after existing-passkey sign-in.

These can be grouped into one hands-on Mac close-out, without another policy
approval or repeating unchanged suites. Image passwords/new credential entry
remain owner actions; a live replacement is not part of a disposable rehearsal.
The already accepted manual backup, trial retention, attended availability,
incident and Streamlit-parking choices are resolved for this trial. Hosted
domain/RP/TLS/proxy/abuse/state/deployment/rollback and physical-device checks
remain a separate soft-launch boundary, not work to perform on the current Mac
by assumption. History recovery remains parked. P1-09–12 are IN PROGRESS and
formal Phase 1 remains 8/12; neither synthetic checks nor this profile approval
is final release acceptance.

### Owner-authorized one-session close-out preparation: 2026-10-13

The owner approved the remaining Mac close-out as one session, including
commit/push, with private password entry and actual VoiceOver listening when
needed. `scripts/web/rehearse_mac_recovery.py` now orchestrates the existing
three encrypted-image restore mechanisms through temporary-copy contexts.
Existing create/verify interfaces and image formats are unchanged. There is
no new backup stack, dependency, image creation, scheduling or live restoration.

The contexts retain verified restored files only for the session, then detach
their own read-only mounts and remove their own temporary folders. The operator
checks restored accepted-source lineage, independently pinned public artifact
and original TLS, rebinds only a new disposable config, provisions only a new
temporary security store, and starts the compatible **installed** protected
service on a separate loopback port. A signed ephemeral test client uses its
own cookie jar to check enrollment/login, current reports and release-matching
CSV, then logout/lock. It does not enroll an owner-device passkey or disturb the
live browser's localhost cookies. No history request/import is performed.

Ten focused synthetic checks passed for copy lifetimes/cleanup, private modes,
manifest path refusal, original-config preservation/new binding, owned-child
shutdown on failure, exactly scoped disposable read-audit changes, no live port,
noninteractive refusal and no-overwrite receipts. Four existing password/image
guards and the existing journal manifest/authority guard also passed; unchanged
native image creation, frontend builds and broad suites were not repeated.
These fifteen checks establish preparation safeguards, **not** an executed
owner-image recovery or screen-reader/owner acceptance. The separate owner
Terminal run is pending; passwords must never enter chat or agent tool input.
See `docs/operator_quickstart.md` for the finite run and acceptance boundaries.

### Failed owner attempt and focused runner correction: 2026-10-13

The owner's first attempt reached the evidence/audit password prompt. The
preceding journal and access contexts had therefore unlocked and validated;
do not blame those passwords. The original receipt retained only `incomplete`,
so the exact later failure stage cannot be established from that attempt.
The immediate retry stopped because its fixed receipt path already existed;
the no-overwrite guard preserved the earlier evidence.

Inspection also found a definite startup defect: invoking
`python -m onejournal.mac_static_site` only imports the installed module; it
has no `__main__` invocation. A non-mutating installed-runtime `--help` check
confirmed the silent exit, while the console entry point reached its parser.
The runner now explicitly invokes the installed module's `main` with the
selected interpreter and isolated child environment. Fixed value-free progress
and failure stages distinguish image, lineage and service failures. The private
shortcut selects a fresh receipt each time, retaining the original failed one.

Twelve focused checks passed, including a real installed-runtime entry-point
smoke and a post-unlock failure regression proving stage reporting without
password/response disclosure. No owner image was reopened, no password read,
no restored server started and no live state changed during this correction.
Actual restored-service completion, speech and owner acceptance remain pending.

### Mac-testing close-out — owner accepted: 2026-10-13

**The agreed Mac-testing work is closed.** The owner reported that recovery
passed, VoiceOver read the headings, controls and table clearly, and Reports
opened promptly, then explicitly instructed closing out the Mac work. This
accepts the existing protected single-owner Mac-testing release under the
combined profile above, not a hosted production release or new financial scope.
The exact installed source/artifact, configuration/financial-authority lineage,
successful recovery receipt and owner statement are retained privately.

The independently read recovery receipt records `passed`: existing encrypted
images preserved, restored journal/evidence lineage matched, exact static shell
and verified HTTPS, fresh temporary signed-test enrollment/login, current
account/symbol reports and release-matching CSV, logout lock and temporary
service/copy cleanup. Only the three scoped read-audit additions occurred in
the disposable journal; the accepted guard checked unchanged schema and other
relation counts. Recorded session time includes owner password entry and is
within the Mac trial's one-working-day recovery target for this same-Mac path.
It is not a general recovery-time guarantee, fresh owner-device enrollment,
full lifetime-history recovery, another-Mac restoration or hosted acceptance.

The actual VoiceOver result is owner-heard evidence for the requested Safari
check, not agent-observed speech or comprehensive WCAG conformity. Prompt
Reports opening is an owner usability confirmation, not a stopwatch measurement
of real-data latency. Existing Chrome/Safari synthetic timings, zoom/reflow,
keyboard, export, financial-quality and security evidence are reused unchanged.
The rehearsal's test-helper import emitted a TestClient deprecation warning;
the run then passed. No dependency replacement or unnecessary test cycle is
included in this documentation-only close-out.

| Package | Mac-testing disposition | Separate soft-launch/production work |
|---|---|---|
| P1-09 | Accepted bounded protected Mac access/session/offline recovery/audit and trial operating choices. | Actual domain/RP/TLS and enrollment/recovery, candidate dependency/security review, host/proxy/abuse boundaries and production security-state/audit policy. |
| P1-10 | Accepted installed package/start/retained rollback, encrypted images, scoped restored service and manual trial operations. | Target state and migration if required, deployment/rollback, host recovery and final production availability/retention/alerting objectives. |
| P1-11 | Accepted bounded Mac browser/keyboard/zoom/reflow evidence, owner-heard VoiceOver and responsive Reports use. | Physical-device and host/network-dependent journeys and final target accessibility/performance checks. |
| P1-12 | Owner accepted the dated existing Mac-testing release and its limitations; Streamlit remains parked. | Dated exact production release and explicit owner acceptance after the target-dependent checks. |

No routine Mac close-out action remains under this accepted scope. Do not reopen
unchanged backup/browser/login suites to keep working. Normal use and the
accepted manual backup cadence continue; a changed release or new defect gets
only its relevant validation. This close-out installs nothing, writes no live
database, restarts no service and activates no historical migration/import,
broker refresh, hosting, scheduler, deletion or trading. History recovery stays
separate. ADR-0018's production gate is unchanged: formal Phase 1 stays 8/12,
with P1-09–12 IN PROGRESS solely for their remaining production scope.

### Hosted candidate preparation — 2026-10-13

The owner approved the combined profile in ADR-0017 and one local implementation
batch: hosted entry point, synthetic PostgreSQL rehearsal, deployment/recovery
preparation, commit and push. No deployment, private-data transfer, live Mac
database/runtime change, OneBot change or historical backfill is included.
The accepted Mac close-out above remains closed.

The candidate introduces independent hosted configuration and exact DNS/RP
binding, fresh hosted passkey provisioning/recovery, a loopback/proxy boundary,
non-owner PostgreSQL roles and an exclusive single-worker lease. Existing
financial API/release authorizations and journal revisions/receipts are reused.
Source migrations through 0028 map to an independently versioned PostgreSQL
baseline; 0029 is excluded. The website does not receive connection strings,
raw broker evidence, provisioning secrets or SQL access.

Actual disposable PostgreSQL rehearsal uses invented source records only. It
compares API JSON/CSV with DuckDB, exact report precision and acceptance
fingerprints, append-only current-revision views, journal edits and receipt
replays. Signed synthetic hosted enrollment/login, CSRF, logout/expiry,
proxy-origin denial and offline recovery exercise the protected static shell.
Encrypted dump/restore checks exact table contents, wrong passwords, tampering,
existing-file preservation and refusal of a nonempty restore target. These
checks do not establish real-account migration or owner-device enrollment.

The public package contains the wheel (including pinned schema), locked
dependencies, passkey-enabled static build, operator commands and Caddy/systemd
preparation. It contains no private configuration or database. The Mac's Python
environment is never copied to Linux. Templates are not installed or enabled.
On 2026-10-13 the owner clarified that `one-prod` remains exclusively OneBot's
VPS and OneJournal must use a separate VPS. This supersedes the shared-host
proposal; the earlier host inventory is not target-readiness evidence. No
OneJournal hosting access, installation or activation on one-prod is in scope.
The separate target/provider/size/address remain unselected; work stays on the
Mac. Resource caps are provisional conservative templates. Actual Linux
dependencies, capacity, service compatibility, firewall/cloud exposure and
privileged configuration require verification on the separate target before
separately approved activation. No purchase or private-data transfer is approved.

The owner confirmed control and chose `https://journal.onelumiq.com` on
2026-10-13. The public example and package renderer bind that exact origin and
RP (`journal.onelumiq.com`); release metadata records both plus the hosted home
`/local/today`. Hosted `/` opens that protected-workspace shell rather than the
demo; API/session/financial gates are unchanged. The Mac/default demo redirect
is not altered. Signed synthetic RP/origin rejection and focused root/gate
checks cover this local change; no actual owner passkey was enrolled.

Read-only authoritative DNS currently points the chosen name to a Porkbun
target, not OneJournal. No DNS record, certificate, host package, service,
private data or OneBot setting was changed. Deployment must replace only the
exact journal record, preserving the root domain and other services. The owner
selected the name, not a hosted-production acceptance claim.

Remaining production work is actual DNS/TLS; candidate dependency/security
disposition; a separately authorized,
backed-up and exactly reconciled private-state transfer/cutover; real deployment
and rollback; independently held off-server backups and host restoration;
physical-device/host-dependent quality checks; final operating objectives and
dated owner acceptance. The next batch must name those actions explicitly.
No synthetic pass is promoted to operational acceptance. Phase 1 remains 8/12.

Local dependency maintenance on 2026-10-13 separated the hosted lock from the
accepted Mac profile and patched only AnyIO, Starlette and python-multipart.
Exact installed pins, dependency consistency and the focused static/signed
access plus actual synthetic PostgreSQL JSON/CSV/replay/failure checks passed.
The three patched pins have no matches in the dated OSV check; frontend runtime
audit has zero findings. Build/development alerts and other Python matches
remain explicitly un-cleared. See `docs/mac_passkey_access_contract.md` for the
scope and remaining disposition. No live environment, private state, one-prod
hosting or history work was included; actual separate-target acceptance remains.

The subsequent 2026-10-13 local batch patches the available build-tool findings
and adds a temporary-copy-only journal migration rehearsal command to the
public package. Build audit is down to six high findings in the unpatched
braces generator chain, with zero critical/moderate findings; this is not full
dependency clearance. Six packaging checks and the static build passed.
Three focused migration tests passed against synthetic PostgreSQL state,
including exact tables/views, unchanged source, all-insert rollback on a forced
mismatch and matching Portfolio/Reports/CSV/journal output. Normal runtime
targets, populated targets and newer history schemas are refused. No live
migration or activation capability was added. Operator details and rollback are
in `docs/operator_quickstart.md`; remaining dependency disposition is in
`docs/mac_passkey_access_contract.md`. Separate-VPS selection, real-state
cutover and hosted acceptance remain outstanding; Phase 1 remains 8/12.

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
| WEB-W11 | WEB-08 | IN PROGRESS | End-to-end quality, accessibility, performance and browser/device coverage | Use the accepted flows on supported desktop, tablet and mobile targets | Bounded Mac checks and owner-heard VoiceOver/prompt Reports use accepted 2026-10-13; physical-device and final host/network acceptance remain | Terra Medium; Luna Low for routine regression maintenance |
| WEB-W12 | OPS-01 through OPS-06 | IN PROGRESS | Environment, hosting, PostgreSQL migration, deployment, observability, backup and recovery | Use the accepted Mac installed release and recovery/check tooling; hosted staging remains separate | Mac trial operations and scoped restored-service journey accepted 2026-10-13; actual target state/deployment/restore/rollback and production-policy acceptance remain | Sol High for architecture/security/migration; Terra Medium for automation |
| WEB-W13 | WEB-09, OPS-07 | IN PROGRESS | Production acceptance and Streamlit transition | Use the dated accepted Mac-testing release with explicit limitations | Mac-testing release, trial retention and Streamlit parking accepted 2026-10-13; final production-target verification and dated production owner acceptance remain | Sol High for final critical review; Luna Low for release-record maintenance |

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
