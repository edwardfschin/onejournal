# ADR-0011: Use the connected account broker as market-session authority

- Status: Accepted
- Date: 2026-08-28
- Decision owners: OneJournal project owner
- Related roadmap items: PNL-02 through PNL-04, PNL-08
- Related contracts: ADR-0003, ADR-0007, ADR-0009,
  `docs/provider_native_market_session_contract.md`,
  `docs/onejournal_data_contract_v1.md`, `config/marketdata.yaml`
- Supersedes: None
- Superseded by: None

## Context

ADR-0009 selects the holding's connected account broker for quotes and disables
silent cross-provider quote fallback. The implemented
`onejournal.market-session-authority.v1` value proves useful temporal and
calendar semantics but deliberately selects no resolver. Its exact-MIC design
also lacks provider, connection, and provider-instrument identity.

PNL-02 must classify quote time and evaluation time across normal, extended,
closed, holiday, early-close, and unscheduled-closure cases. Schwab, IBKR,
Moomoo, and later provider APIs may expose those facts using different quote,
market-hours, schedule, contract, or instrument responses. A universal external
calendar would separate the session decision from the user's connected broker
and introduce a second licensing and lineage boundary.

The project owner confirmed that OneJournal is a user journal connected to the
user's own broker accounts and should use the broker's information when that
broker satisfies the required contract. A provider that cannot supply adequate
evidence should not be repaired silently with an unrelated source.

## Decision

1. The connected account broker is the exclusive market-session schedule
   authority for its quote and holding.
2. Provider-native evidence may come from that broker's quote, market-hours,
   trading-schedule, contract, or instrument response according to its official
   API contract.
3. Provider adapters normalize that evidence behind a common OneJournal
   contract while preserving the exact provider, opaque connection,
   provider-instrument, broker-independent instrument, schedule scope,
   timezone, temporal scope, raw lineage, and adapter version.
4. Another broker, TradingHours or another third-party calendar, a weekday
   rule, and clock-only inference are not PNL-02 sources or fallbacks.
5. Missing, expired, conflicting, cross-provider, cross-connection, or
   identity-mismatched schedule evidence makes freshness and valuation
   unavailable. Schedule evidence cannot override denied, delayed, or unknown
   quote entitlement.
6. A provider is eligible for freshness-dependent valuation only for asset
   classes and sessions its official API and bounded evidence satisfy. Support
   may be narrower by provider, but the limitation must be explicit.
7. An unexpired provider-native schedule response may be cached locally under
   provider rules with immutable lineage and an explicit validity window. An
   expired cache or provider outage fails closed without external fallback.
8. The detailed provider eligibility gate, acceptance matrix, real-evidence
   cases, and approval boundaries are part of this decision through
   `docs/provider_native_market_session_contract.md`.

## Boundaries

This decision selects authority policy only. It does not prove that Schwab,
IBKR, Moomoo, or another provider currently meets the eligibility gate. It does
not authorize credentials, provider calls, subscriptions, token refresh,
private-evidence transfer, runtime persistence, migration, connector
activation, deployment, synchronization, redistribution, or order capability.

OneBot/VPS remains only the temporary Schwab token owner and bounded evidence
bridge until the separately approved single-owner cutover. The current
OneJournal runtime remains credential-free.

## Alternatives considered

### Use TradingHours as the primary schedule source

This offers broad normalized calendar coverage and offline use after download,
but its [per-application annual licensing](https://www.tradinghours.com/data)
adds a separate commercial boundary and makes a third party authoritative for a
quote whose entitlement and instrument context belong to the user's broker.
Rejected for PNL-02.

### Use any available broker as a schedule fallback

This avoids a third-party calendar subscription but breaks account-broker and
connection lineage. An IBKR schedule cannot silently qualify a Schwab quote,
or vice versa. Rejected.

### Infer sessions from the clock and weekdays

This is mechanically simple but cannot prove holidays, early closes,
unscheduled closures, venue/product distinctions, or provider-specific extended
sessions. Rejected.

### Fail closed when the connected broker is insufficient

This reduces apparent provider coverage but protects financial correctness and
makes unsupported capabilities visible. Accepted.

## Consequences

### Positive

- Quote, entitlement, instrument, and schedule evidence retain one provider and
  connection lineage.
- OneJournal avoids an unnecessary external calendar dependency and licence.
- Each provider adapter can map its strongest native schedule contract into a
  stable broker-independent interface.
- Missing or ambiguous session evidence cannot masquerade as a current mark.

### Negative and trade-offs

- Provider coverage is limited by the quality and availability of each broker's
  API.
- Equivalent session states may require different provider-specific endpoints
  and mapping tests.
- A provider outage may make valuation unavailable even when a third-party
  calendar could supply a plausible schedule.
- Product support may differ by provider and asset class and must be explained
  clearly to the user.

## Compatibility and migration

The existing `onejournal.market-session-authority.v1` object and tests remain
unchanged historical groundwork. Its exact-MIC field and missing provider,
connection, and provider-instrument fields cannot satisfy this decision. T09
must introduce a new contract version and update every affected producer and
consumer rather than reinterpret `v1` silently.

No database schema or persisted quote changes in this decision. Session
authority and computed freshness remain point-in-time inputs and results rather
than permanent quote properties. Any future persistence of provider schedule
evidence requires its own reviewed schema and migration decision.

## Security, privacy, licensing, and financial impact

Provider schedule requests share the user's connection and may reveal
instrument interests. Credentials remain isolated in the provider connector;
raw responses remain private and must not enter Git, logs, fixtures, or public
payloads. Provider terms govern retrieval, caching, retention, and display.

This policy does not grant market-data rights and does not permit
redistribution. A correct session schedule cannot cure missing quote
entitlement, price evidence, or an unapproved mark-selection policy. Any
affected unrealized P&L remains unavailable rather than guessed or zero.

## Validation

Implementation must prove:

- deterministic identity and exact provider, connection, provider-instrument,
  broker-independent instrument, schedule-scope, timezone, market-date,
  evaluation-time, phase-window, source, and validity binding;
- regular, supported extended, normal close, holiday, early-close,
  unscheduled-closure, and DST behavior;
- quote-time and evaluation-time session separation;
- fail-closed missing, expired, outage, conflict, unsupported, identity-mismatch,
  cross-provider, and cross-connection cases;
- entitlement and delay cannot be overridden by schedule evidence;
- no external calendar, network, credential, persistence, or order capability
  in offline contract tests; and
- bounded official evidence for each provider and asset class before that scope
  is accepted.

The exact matrix and initial Schwab evidence scope are maintained in
`docs/provider_native_market_session_contract.md`.

## Rollback or supersession

This decision changes documentation only. Before T09 implementation, rollback
is focused reversion of this ADR and its linked contract/tracker changes. After
a new versioned runtime contract exists, supersession requires compatibility
handling for every producer and consumer; no historical evidence may be
silently reinterpreted.

A later ADR may approve an external source or fallback only with explicit
licensing, source labels, identity, reconciliation, outage, retention, and
financial-failure rules.
