# ADR-0016: Accept bounded bridge mode as a PNL-02 completion route

- Status: Accepted
- Date: 2026-08-29
- Decision owners: OneJournal project owner
- Related roadmap items: PNL-02, PNL-02-T15 through PNL-02-T17, PNL-03
- Related contracts: ADR-0002, ADR-0009, ADR-0011, ADR-0012, ADR-0013,
  ADR-0014, ADR-0015, `docs/onejournal_data_contract_v1.md`,
  `docs/onejournal_product_roadmap.md`
- Supersedes: The PNL-02 completion-gate requirements in ADR-0009 validation
  and ADR-0015 decisions 15-16 only
- Superseded by: None

## Context

The initial product scope requires read-only, Schwab-first, broker-independent
market-data workflows. PNL-02 requires selection of a market-data provider and
defined quote ingestion, storage, licensing, and freshness behavior. Neither
scope requires OneJournal to own a provider credential before the bounded
market-data contract can be completed.

The later T15-T17 sequence made OneJournal's Schwab single-owner cutover a hard
PNL-02 dependency. The project owner has stated that OneBot cannot yet be
retired as the sole Schwab token owner. ADR-0015 safely permits temporary
external provider evidence, but deliberately leaves bridge-mode completion for
a later decision. Keeping the cutover as a PNL-02 prerequisite would therefore
leave an otherwise testable credential-free market-data path blocked by an
operational ownership change that is not currently safe or required by the
original PNL-02 outcome.

This decision accepts the bounded bridge as the current completion route while
preserving the isolated OneJournal-owned connector plane as the target
architecture. It does not treat OneBot-derived values or OneBot runtime state as
authoritative OneJournal state.

## Decision

### Bounded completion scope

1. PNL-02 may complete for a bounded, owner-operated, local,
   personal/noncommercial Schwab evidence mode while OneBot/VPS remains the sole
   Schwab credential, refresh, and provider-session owner.
2. PNL-02 completion in this mode establishes the provider-independent quote,
   session-authority, entitlement, freshness, evidence, conversion,
   persistence, and read-back contracts for the accepted scope. It does not
   establish continuous acquisition, production readiness, public website use,
   or OneJournal credential ownership.
3. PNL-02-T15 remains the later break-before-make cutover to the isolated
   OneJournal-owned connector plane. It moves to `LATER` and is not a dependency
   of bridge-mode T16 or T17.
4. The T15 cutover invariants in ADR-0012 and ADR-0014 remain unchanged. OneBot
   and OneJournal must never share, copy, use, or refresh the same active Schwab
   credential lifecycle.

### T16 bridge-mode acceptance

5. T16 is the end-to-end acceptance gate for the temporary bridge. Completion
   requires:

   - an implemented and offline-validated
     `onejournal.external-provider-acquisition.v1` contract;
   - an explicitly approved, bounded acquisition from the authoritative OneBot
     owner boundary with exact provider response bytes and secret-free lineage;
   - checksum-preserving, non-overwriting transfer to the OneJournal private
     evidence root under the approved lifecycle;
   - deterministic OneJournal validation and conversion through its own Schwab
     adapter, provider-native session resolver, entitlement and freshness rules,
     and canonical private-capture contract;
   - separately approved persistence to, and exact scoped read-back from, an
     approved local OneJournal DuckDB using the existing guarded operator;
   - negative evidence proving rejection of missing, altered, stale, delayed,
     denied, crossed, future, session-unknown, identity-mismatched, incomplete,
     credential-bearing, account, order, and unsupported-operation inputs; and
   - a dated evidence pack plus explicit project-owner acceptance for the stated
     local bridge-mode operating scope and limitations.

6. OneJournal remains credential-free throughout T16. It accepts only provider
   bytes and verified external-acquisition lineage. OneBot-normalized quotes,
   session values, freshness results, reports, logs, database rows, and other
   derived state are not OneJournal inputs.
7. The bridge producer remains explicitly invoked and bounded. Scheduling,
   background polling, public listeners, website-triggered access, silent
   refresh, generic provider proxying, and redistribution are outside the
   accepted scope.

### T17 closure and later work

8. T17 remains the PNL-02 closure gate. After T16 owner acceptance, T17 must
   reconcile the ADRs, contracts, implementation, tests, private evidence
   references, limitations, strategic maturity, and exact PNL-03 entry gate
   before marking PNL-02 `COMPLETE`.
9. A bridge-mode PNL-02 completion does not automatically establish an
   operationally accepted live market-data service or approve quotes as PNL-03
   valuation marks. PNL-03 must still approve its position source,
   mark-selection method, reconciliation scope, and unavailable behavior.
10. T15 remains available as later target-architecture work. Completing PNL-02
    under this decision does not mark T15 complete or weaken its future cutover
    evidence.

## Boundaries

This decision changes only the accepted PNL-02 completion route and delivery
ordering. It does not authorize or implement an external-acquisition contract,
OneBot change, provider call, token use or refresh, credential transfer,
private-evidence creation or transfer, database migration or write, connector
activation, service, schedule, public listener, website integration, commit,
push, synchronization, or deployment.

It does not make OneBot a permanent OneJournal gateway, make OneBot-derived
state authoritative, approve cross-provider fallback, weaken provider-reported
entitlement or freshness gates, or change the target OneJournal-owned connector
architecture.

## Alternatives considered

### Keep T15 as a hard PNL-02 dependency

This preserves the current sequence but prevents PNL-02 closure until OneBot can
be safely retired, even though credential ownership is not part of the original
PNL-02 outcome. Rejected.

### Treat the existing T14 evidence as final acceptance

T14 proves bounded provider shapes and freshness behavior, but it predates the
external-acquisition contract, performs no accepted durable persistence, and is
not a complete operational bridge path. Rejected.

### Make OneBot the permanent market-data service

This would couple OneJournal to another project's credentials, runtime, and
derived behavior. Rejected. Only a temporary evidence producer is accepted.

## Consequences

### Positive

- PNL-02 has a finite completion path that does not require an unsafe immediate
  OneBot retirement.
- Provider bytes, lineage, normalization, session authority, freshness, and
  persistence remain controlled by OneJournal contracts.
- The target isolated connector and break-before-make cutover remain intact.
- PNL-03 can later enter through an explicit bounded gate rather than waiting on
  an unrelated credential-ownership migration.

### Negative and trade-offs

- Bridge-mode acquisition is manual and bounded, not continuous or suitable for
  a public website.
- OneJournal depends temporarily on an approved OneBot-owned evidence producer
  for new Schwab source bytes, although not on OneBot-derived state.
- T15 and production provider-connection work remain outstanding after PNL-02.
- Operational and financial acceptance remain narrower than eventual production
  capability.

## Compatibility and migration

This decision changes no normalized quote, session-authority, freshness,
private-capture, ingestion, DuckDB, provider, or UI schema. ADR-0015's additive
external-acquisition contract remains the required new intake boundary. Existing
T14 evidence retains its historical contract and is not relabelled.

The roadmap dependency changes from `T15 -> T16 -> T17` to a bridge-mode
`T16 -> T17`, with T15 retained as non-blocking later work. No data migration is
performed by this decision.

## Security, privacy, licensing, and financial impact

The accepted scope remains local, private, owner-operated,
personal/noncommercial, and non-redistributed. Credentials and tokens remain
outside OneJournal. Provider-reported entitlement, same-provider session
authority, freshness, exact identity, immutable raw evidence, and fail-closed
rules remain mandatory.

A successfully acquired or persisted quote is not automatically an approved
valuation mark. Missing or invalid evidence remains unavailable and never
becomes zero or live through fallback.

## Validation

This decision is valid when:

- the ADR register contains this accepted decision exactly once;
- the PNL-02 roadmap makes T15 `LATER` and non-blocking, T16 the bounded bridge
  acceptance gate, and T17 the closure gate;
- the data contract, README, and maturity map distinguish bounded bridge-mode
  completion from target connector ownership and operational acceptance;
- documentation and architecture-register tests pass; and
- Git diff and status checks show only the focused approved change.

Implementation and operational evidence remain the separate T16 gates listed
above.

## Rollback or supersession

Before T16 operational use, rollback is a focused reversion of this policy and
its roadmap references. After accepted bridge operation, immutable evidence and
journal rows remain governed by their approved lifecycle and migration rules;
policy rollback does not delete them.

A later accepted decision may restore cutover as a completion prerequisite or
supersede bridge mode after T15 succeeds, without weakening historical evidence
or the no-dual-owner rule.
