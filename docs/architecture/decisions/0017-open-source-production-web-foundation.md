# ADR-0017: Adopt an open-source production web foundation and visible vertical delivery

- Status: Accepted
- Date: 2026-08-31
- Decision owners: OneJournal project owner
- Related roadmap items: PNL-03 through PNL-08, UXJ-05 through UXJ-06,
  WEB-01 through WEB-09, OPS-01 through OPS-07
- Related contracts: `AGENTS.md`, ADR-0002, ADR-0003, ADR-0004, ADR-0007,
  ADR-0008, ADR-0014, ADR-0016,
  `docs/production_web_delivery_contract.md`,
  `docs/onejournal_product_roadmap.md`
- Supersedes: None; resolves the production-web decision deliberately deferred
  by ADR-0014 and WEB-01
- Superseded by: None

## Context

OneJournal has a validated Python domain and data foundation plus an internal
Streamlit prototype. The prototype is useful for workflow and contract
validation, but it is not visually, structurally, or operationally suitable as
the production website. At the time of this decision, the repository had no
JavaScript application, public API, production authentication, hosted
operational database, or approved production deployment.

The previous roadmap placed all PNL work before web delivery. That sequencing
protected financial correctness, but it also meant that long-running backend
work produced no product experience for the owner to inspect. The project
needs visible vertical checkpoints without presenting synthetic, incomplete,
or prototype financial values as authoritative.

On 2026-08-31, the project owner approved a free and open-source foundation
based on React, TypeScript, Vite, Tailwind CSS, shadcn/ui with Base UI,
Apache ECharts, and FastAPI. The owner also approved contracting the associated
delivery work and acceptance sequence.

## Decision

### Application foundation

1. The production frontend will use React and TypeScript, built with Vite.
2. Styling will use Tailwind CSS and OneJournal-owned design tokens. Reusable
   accessible component source will use shadcn/ui with Base UI as the initial
   headless component foundation.
3. Interactive analytical charts will use Apache ECharts behind
   OneJournal-owned chart components and data contracts.
4. The application/API boundary will use FastAPI and reusable Python services
   under `src/onejournal/`. The API, not the browser, is the authority for
   domain validation, financial calculation, authorization, persistence, and
   audit behavior.
5. The selected application foundation must remain self-hostable and
   vendor-neutral. No paid UI kit, proprietary application builder, or hosting
   platform is required to build or operate the product.

### Data and process topology

6. DuckDB remains the local journal, analytical, migration-rehearsal, and
   validation store until separately approved migration work changes a stated
   runtime. A hosted multi-process production service will use PostgreSQL for
   operational application state after an additive, rehearsed, reconciled, and
   separately approved migration.
7. The website will never open DuckDB, PostgreSQL, raw broker files, private
   evidence, or generated dashboard payloads directly. It will consume
   versioned API contracts.
8. Broker acquisition, imports, reconciliation, report generation, and other
   long-running work will execute outside interactive HTTP request handling
   through an auditable worker/job boundary. The exact queue or scheduler
   product is deferred until measured workload requires it; the architecture
   does not require Redis or a proprietary job service by default.
9. The portable production topology is a separately deployable static web
   application, private HTTPS API, background worker, PostgreSQL store, and
   separately governed private object storage only where approved attachments
   or evidence require it. The hosting vendor and physical topology remain an
   OPS decision.

### Visible vertical delivery

10. OneJournal will deliver visible browser checkpoints throughout backend
    work. A safe synthetic-data preview may precede PNL-03 and authentication
    when it is loopback-only, contains no private information, makes no broker
    calls, and labels all data as demonstration data.
11. PNL-03 is not cancelled or bypassed. It remains the authority gate for
    current positions, cost basis, valuation marks, market value, and
    unrealized P&L. Until it passes, the production-shaped UI must display those
    real metrics as unavailable; synthetic demonstrations must be unmistakably
    separated from real operating mode.
12. Each material financial or trust increment must end with a corresponding
    browser-visible state and acceptance check. Presentation may expose
    independently valid data, but it may not convert missing or invalid data
    into zero, stale data into current data, or prototype calculations into
    accepted financial results.

### Experience direction

13. The product will use a premium, dark-first financial-workspace direction:
    graphite/navy foundations, restrained luminous accents, crisp information
    hierarchy, high-quality charts, subtle motion, and explicit provenance,
    freshness, completeness, and reconciliation states.
14. "Futuristic" means precise, calm, responsive, and information-rich. It
    does not mean decorative cyberpunk styling, excessive glow, glass effects
    that reduce readability, or animation that competes with financial data.
15. The application must meet the responsive, keyboard, contrast, reduced
    motion, screen-reader, loading, empty, partial, stale, unavailable, and
    failure-state requirements in the production web delivery contract before
    production acceptance.

## Boundaries

This decision selects the open-source application foundation, portable service
topology, experience direction, and visible-delivery policy. It does not:

- install dependencies, scaffold the frontend, or implement an API;
- select a hosting vendor, identity provider, email provider, queue product,
  object store, ORM, or PostgreSQL service;
- approve public exposure, deployment, database migration, broker access,
  production credentials, private-data transfer, or runtime changes;
- approve exact typography, palette values, screen designs, or component
  implementations before visual review;
- make demonstration data or the Streamlit prototype authoritative;
- approve any PNL-03 valuation mark or weaken existing financial gates; or
- retire Streamlit before production-web parity is proven.

Authentication will use server-validated ownership and secure server-managed
sessions; the exact identity, recovery, session, and audit design remains the
separate WEB-06 security decision.

## Alternatives considered

### Continue polishing Streamlit

This is the fastest way to change the current appearance, but Streamlit keeps
presentation, application behavior, and direct local data access too closely
coupled and has a lower ceiling for a distinctive responsive product. It is
retained only as a temporary internal validation tool.

### Next.js with a Python API

Next.js provides server rendering, integrated routing, and a large production
ecosystem. OneJournal's initial private authenticated application does not need
search-engine rendering, and a Next.js server beside FastAPI would add a second
server-side application layer. It remains a viable future superseding choice
if public content or server rendering becomes a proven requirement.

### React, TypeScript, and Vite with FastAPI

This keeps the browser application small, preserves a single Python authority
for financial and persistence behavior, is portable across hosts, and retains
full visual flexibility. It is accepted.

### Proprietary low-code or hosted application builder

This can accelerate initial screens but creates platform coupling and may
restrict private-data controls, financial contract boundaries, testing, and
self-hosting. It is rejected as the production foundation.

### Finish all PNL work before showing any web UI

This protects financial sequencing but defers product feedback too long. It is
replaced by synthetic preview and vertically integrated acceptance checkpoints
that preserve the same financial authority gates.

## Consequences

### Positive

- The owner can review the actual product experience early without accepting
  unsafe financial claims.
- The frontend remains broker-independent and cannot become a financial source
  of truth.
- The selected tools are free, open source, widely supported, customizable,
  and self-hostable.
- Python domain logic remains reusable rather than being duplicated in the
  browser or a second server framework.
- Every backend increment has an explicit route to a visible product outcome.

### Negative and trade-offs

- The repository gains a TypeScript toolchain and corresponding dependency,
  build, test, accessibility, and security maintenance.
- PostgreSQL support requires a later repository abstraction, schema mapping,
  data migration, reconciliation, and recovery program.
- A custom visual system requires deliberate design and visual QA; open-source
  components do not create a distinctive product by themselves.
- Synthetic preview work must be tightly labelled and kept separate from
  private or authoritative runtime modes.

## Compatibility and migration

The decision changes no current runtime contract or database. Existing Python
services and DuckDB behavior remain authoritative for their accepted scopes.

Implementation will add a separate web workspace and versioned FastAPI
contracts without moving financial calculations into TypeScript. Any shared
schema must preserve decimal strings, stable identifiers, UTC instants,
market-date semantics, source lineage, calculation versions, and quality
states. Breaking API changes require versioning and coordinated producer and
consumer migration.

PostgreSQL adoption is not a file copy or a silent replacement. It requires an
approved storage contract, versioned migrations, realistic rehearsal,
row/identity/value reconciliation, backup and restoration evidence, rollback,
and explicit runtime approval. DuckDB remains supported for local analytical
and controlled operator workflows unless a later ADR changes that boundary.

## Security, privacy, and financial impact

The browser must receive the minimum private data required for the active
view. It must not receive credentials, tokens, raw broker evidence, private
storage paths, unrestricted account identifiers, or attachment storage keys.

Production authentication and authorization must fail closed. Secure cookies,
CSRF defenses, session rotation and expiry, recovery, audit records, rate
limits, origin policy, content security policy, dependency review, and negative
authorization tests are required before private hosted use.

All financial values remain decimal strings with explicit units and quality
metadata. The browser formats values but does not calculate authoritative
positions, P&L, returns, reconciliation, or freshness. Unsupported,
unreconciled, stale, partial, or unavailable results remain visibly distinct.

No API, worker, frontend, or Streamlit route gains broker order capability from
this decision.

## Validation

Policy validation requires:

- this ADR appears exactly once in the decision register;
- the delivery contract records architecture, experience, data-state,
  security, migration, validation, and visible WBS boundaries;
- the roadmap records the current web package state and its bounded evidence;
- the maturity map records only the maturity proven by the current local
  synthetic-fixture evidence, separately from operational acceptance; and
- repository documentation and clean CI pass with only the focused files
  changed.

Runtime implementation will later require frontend build, type, unit,
component, API-contract, authorization, end-to-end, accessibility, responsive,
performance, secret, migration, reconciliation, recovery, and visual-review
evidence appropriate to each delivery gate.

## Rollback or supersession

Before runtime implementation, rollback is a focused reversion of this ADR and
its linked documentation. After implementation begins, the open-source
components and OneJournal-owned contracts allow the frontend to be replaced
without changing financial authority.

A material change to the frontend framework, API authority, hosted operational
database, or portable service topology requires a superseding ADR with
compatibility, migration, security, operational, and rollback analysis.
