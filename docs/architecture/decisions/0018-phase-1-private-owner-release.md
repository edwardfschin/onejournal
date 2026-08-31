# ADR-0018: Define the finite Phase 1 Private Owner Release

- Status: Accepted
- Date: 2026-08-31
- Decision owners: OneJournal project owner
- Related roadmap items: PNL-01 through PNL-08, UXJ-01 through UXJ-06,
  WEB-01 through WEB-09, OPS-01 through OPS-07, P1-01 through P1-12
- Related contracts: ADR-0001, ADR-0002, ADR-0003, ADR-0004, ADR-0007,
  ADR-0008, ADR-0009, ADR-0014, ADR-0016, ADR-0017,
  `docs/production_web_delivery_contract.md`,
  `docs/onejournal_product_roadmap.md`
- Supersedes: None; refines ADR-0002's initial production scope into a finite
  Phase 1 exit gate
- Superseded by: None

## Context

ADR-0002 defines the intended first production use case: one authenticated
owner, multiple owned accounts, Schwab first, US-listed stocks and listed
equity options, read-only broker access, trustworthy journal, portfolio, P&L,
performance, risk, and responsive web workflows.

ADR-0017 defines the production web foundation and a visible vertical delivery
route. Its WEB-W13 endpoint reaches a private production website, but the
roadmap still lacks one named Phase 1 gate that states exactly which product,
financial, data, security, and operating capabilities must be accepted and
which desirable features may follow later.

Without that boundary, Phase 1 could expand whenever an advanced analytic,
additional broker, attachment workflow, continuous connector, or automation
idea appears. On 2026-08-31, the project owner approved making the first release
finite through the scope and tracker below.

## Decision

The first releasable OneJournal product is named:

> **Phase 1 — Private Owner Release**

Phase 1 is complete only when all twelve `P1` tracker items are complete and
the project owner explicitly accepts the resulting private operating scope.
Documentation, a design, a synthetic preview, code presence, passing tests, a
deployment, or partial financial acceptance cannot complete Phase 1 alone.

### Owner and account scope

Phase 1 supports:

- one authenticated owner;
- multiple Schwab brokerage accounts owned or controlled by that owner;
- account-specific and consolidated views; and
- US-listed equities and listed equity options only where the exact instrument
  and lifecycle behavior is supported.

Unsupported instruments, accounts, or lifecycle cases must be rejected or
shown as unavailable. They do not prevent release when they are outside the
declared support matrix, cannot contaminate accepted totals, and have explicit
reasons and counts.

### Broker and evidence scope

Phase 1 requires at least one approved, repeatable, read-only Schwab evidence
route for the source records needed by the accepted product views. It must
preserve original provider or broker-export evidence, exact source lineage,
identity, as-of and retrieval context, reconciliation, replay safety, and
privacy.

The route may be a controlled manual import or a separately approved
credential-free external acquisition while another isolated owner remains the
sole credential owner. Phase 1 does not require OneJournal to own or refresh a
Schwab token, complete PNL-02-T15, poll continuously, or make provider calls
from the website. OneBot-derived values and runtime state remain non-authoritative;
only approved original evidence and OneJournal-owned normalization,
reconciliation, persistence, and calculation may feed the product.

The required Phase 1 evidence families are accounts, positions, orders,
transactions, fills, cash where needed for displayed totals, and market
quote/session evidence where needed for valuation. If a displayed metric does
not require one family, the omission must be contractually explicit rather than
silently inferred.

### Journal scope

The private website must allow the owner to:

- find and inspect imported trades and their lifecycle;
- use review queues and search by the approved dimensions;
- create and revise private structured journal entries and reviews through
  append-only domain behavior; and
- view strategy, tag, mistake, lesson, source, quality, and financial context
  supported by current contracts.

Attachments, goals, habits, and recurring review automation are not Phase 1
release blockers. They remain later work unless a future approved decision
promotes a specific item into Phase 1.

### Financial scope

Phase 1 must present, for the explicitly supported and reconciled scope:

- realized P&L from accepted lifecycle allocations;
- current broker-reconciled positions and cost basis;
- approved valuation marks, market value, and unrealized P&L;
- total P&L only when its realized and unrealized components are both valid for
  the stated account, currency, instrument, and as-of scope;
- account and consolidated totals;
- per-symbol and per-account breakdowns that reconcile to those totals;
- date-filtered trade and P&L history; and
- a privacy-safe CSV export of the same accepted records and displayed values.

Every displayed metric must preserve currency, units, account scope, source,
as-of time, calculation version, reconciliation, completeness, and freshness
state. Missing or invalid inputs remain unavailable and never become zero.

Phase 1 does not require advanced returns, drawdown, exposure analytics,
historical portfolio snapshot series, every possible strategy breakdown,
advanced risk models, or the full long-term PNL-04 through PNL-07 scope. Any
such value displayed in Phase 1 must nevertheless meet its complete existing
contract and acceptance gate.

### Web experience scope

The Phase 1 website must provide the accepted production routes for:

- Today;
- Portfolio;
- Trades;
- Journal;
- a bounded Reports/Export experience;
- Data & connections health; and
- Settings and security.

The experience must be visually approved, responsive from supported mobile to
desktop sizes, keyboard usable, and conform to the accepted accessibility,
loading, empty, stale, partial, unavailable, failure, and privacy rules.
Synthetic mode may demonstrate richer future features, but Phase 1 acceptance
uses the clearly identified private owner mode and only accepted capabilities.

### Security and operating scope

Phase 1 requires:

- production owner authentication and authorization;
- secure server-managed sessions, recovery, audit, and negative access tests;
- an approved private HTTPS hosting target and visibly distinct environments;
- no public financial-data access and no credentials or private evidence in the
  frontend, repository, logs, screenshots, or generated public assets;
- an approved production-state database topology and separately rehearsed,
  reconciled migration where needed;
- versioned deployment and rollback;
- structured privacy-safe observability and actionable failure reporting;
- encrypted backup and tested restoration;
- current dependency, secret, privacy, and threat review; and
- an owner-tested export and recovery path.

The exact vendors and production targets remain separately approval-gated. A
local synthetic preview or private staging demonstration is not Phase 1
operational acceptance.

### Phase 1 completion evidence

Phase 1 completes only when:

1. all `P1-01` through `P1-12` roadmap rows are `COMPLETE`;
2. the production website passes the approved functional, financial, API,
   authorization, accessibility, responsive, browser, performance, migration,
   recovery, and operational checks;
3. a dated acceptance pack identifies the exact deployed artifact,
   environment, owner, supported accounts/instruments, source routes,
   calculation versions, as-of/freshness behavior, evidence, limitations, and
   rollback;
4. every displayed financial scope reconciles or is visibly unavailable;
5. no critical security, privacy, financial, reconciliation, recovery, or
   operational finding remains unresolved; and
6. the project owner explicitly accepts the private production release for the
   recorded scope.

## Explicitly outside Phase 1

The following do not block Phase 1:

- IBKR, Moomoo, or other additional brokers;
- multi-user, household, team, advisor, client, or public tenancy;
- public sharing, social features, or public financial pages;
- OneJournal-owned continuous Schwab acquisition or PNL-02-T15 cutover;
- browser-triggered broker calls or credential refresh;
- automatic background provider polling;
- attachment storage and advanced journal routines;
- advanced returns, drawdown, exposure, risk, optimization, or every possible
  performance breakdown;
- tax reporting, tax advice, or broker-statement replacement;
- paper trading, live trading, broker order writes, or automated trading; and
- unsupported asset classes or instrument types.

These exclusions prevent scope expansion; they do not weaken the correctness,
privacy, or fail-closed requirements for anything Phase 1 does display.

## Alternatives considered

### Require the entire long-term roadmap before Phase 1

This would maximize breadth but make the first usable product indefinite.
Rejected.

### Call the synthetic local preview Phase 1

This would create early visual satisfaction but would not deliver secure,
private, broker-reconciled, recoverable, operational use. Rejected. The
synthetic preview is a milestone, not the release.

### Require continuous OneJournal-owned broker connectivity

This would make PNL-02-T15 and credential ownership block the first product
despite the approved bounded bridge/manual evidence path. Rejected for Phase 1;
it remains target architecture.

### Deliver a bounded private owner release

This supplies a useful real product with explicit financial and operational
trust while deferring breadth that is not required for initial owner value.
Accepted.

## Consequences

### Positive

- Phase 1 has a countable end rather than an open-ended feature ambition.
- The owner sees a polished web product early and later accepts a real private
  operating product.
- PNL-03 remains mandatory for real valuation while advanced analytics no
  longer block the first release.
- Temporary credential-free evidence acquisition can support the first release
  without dual token ownership.
- Every exclusion is explicit and can be scheduled later without ambiguity.

### Negative and trade-offs

- Phase 1 may expose unavailable states for unsupported instruments or
  lifecycle cases rather than complete portfolio-wide coverage.
- Provider data updates may remain manually initiated rather than continuous.
- Advanced analytics, attachments, additional brokers, and automation arrive
  after the first release.
- Secure private hosting, authentication, migration, backup, and recovery still
  require substantial work before operational acceptance.

## Compatibility and migration

This decision changes no runtime, schema, data, API, provider, or credential
state. It narrows the Phase 1 release gate without removing broader roadmap
items.

Existing accepted contracts remain controlling. A Phase 1 implementation may
deliver a bounded slice of a broader PNL or UXJ roadmap item, but it must not
mark the broader item complete unless that item's full completion evidence is
met. API and database changes remain versioned and separately migration-gated.

## Security, privacy, and financial impact

Phase 1 contains real private financial and journal data and therefore requires
production-grade access, storage, audit, recovery, and disclosure controls even
for one owner.

Bounded financial scope is permitted only through visible quality and omission
states. A partial supported scope must not be presented as a complete account or
portfolio total. Unsupported data cannot be silently dropped from a total.

The release remains read-only toward brokers. No UI, API, worker, import,
provider, journal, or report path may place, cancel, replace, or modify an
order.

## Validation

Policy validation requires:

- this ADR appears exactly once in the decision register;
- the roadmap contains exactly twelve Phase 1 tracker rows with an explicit
  exit gate and no excluded feature as a blocker;
- the production web contract maps its work packages to the Phase 1 gate;
- README distinguishes the finite Phase 1 scope from later product breadth;
- strategic maturity remains unchanged until implementation or acceptance
  evidence advances it; and
- documentation checks and clean CI pass with no runtime or private-data
  changes.

## Rollback or supersession

Before implementation, rollback is a focused documentation reversion. After
Phase 1 implementation begins, a scope change requires a superseding ADR that
identifies work already performed, compatibility, migration, security,
financial, schedule, and acceptance impact.

A later phase may add excluded capabilities without altering the historical
Phase 1 acceptance scope.
