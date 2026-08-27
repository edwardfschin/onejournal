# ADR-0009: Use account-broker market data through a provider-independent quote contract

- Status: Accepted
- Date: 2026-08-11
- Decision owners: OneJournal project owner
- Related roadmap items: PNL-02 through PNL-04, PNL-08, UXJ-06
- Related contracts: ADR-0002, ADR-0003, ADR-0004, ADR-0007,
  `config/marketdata.yaml`
- Supersedes: None
- Superseded by: None

## Context

OneJournal has deterministic realized-P&L and open-lot calculations, but its
prototype mark boundary accepts an unqualified mapping from instrument key to
price. Imported `normalized_positions` can also contain broker-supplied
`market_price` without independent quote timestamp, entitlement, delay,
session, or source lineage. Those values cannot prove that unrealized P&L is
current.

The project owner has a Schwab account now and approved Schwab as the first
market-data source, IBKR as the next integration, and Moomoo as a future source.
Each user will connect their own provider account and must possess the required
market-data entitlement. OneJournal is not a market-data redistributor.

Current provider documentation reinforces the need for per-connection state:

- Schwab's Trader API documentation is available through its authenticated
  developer portal, and Schwab's online terms restrict use and redistribution
  of supplied content: <https://www.schwab.com/legal/terms>.
- IBKR requires an authorized session, a brokerage session, and relevant market
  data subscriptions for top-of-book API data. It also imposes request and
  market-data-line limits:
  <https://ibkrcampus.com/campus/ibkr-api-page/webapi-doc/>.
- Moomoo provides quote and push APIs through OpenAPI, while its market-data
  terms describe personal use and prohibit redistribution without consent:
  <https://openapi.moomoo.com/pdfs/moomoo-API-Doc-en-Python.pdf> and
  <https://www.moomoo.com/terms>.

Provider contracts and entitlements can change. The current official terms for
the connected user's jurisdiction and product remain authoritative at runtime.

## Decision

### Provider and connection scope

1. Quote ingestion is read-only and provider-independent after the adapter
   boundary.
2. Provider rollout order is Schwab first, IBKR second, and Moomoo later.
3. A holding uses the market-data connection for its account broker. OneJournal
   does not silently replace a missing Schwab quote with IBKR or Moomoo data.
4. Every quote carries an opaque local `connection_uid`. It identifies the
   user-owned connection and entitlement context without containing an account
   number, username, token, or credential.
5. Provider adapters must preserve the provider instrument identifier and map
   it explicitly to OneJournal's broker-independent `instrument_key`.

### Evidence and storage

6. The raw provider response is immutable private evidence. During the current
   bounded Schwab evidence step, OneBot/VPS is the temporary single token owner
   and capture producer; OneJournal may consume only a checksum-validated,
   secret-free evidence bundle transferred into its private vault. This bridge
   is not the target provider architecture. Raw evidence is never served
   directly to the UI or copied into Git.
7. DuckDB stores normalized top-of-book evidence: provider, connection,
   instrument identity, symbol, asset class, currency, bid, ask, last,
   provider-quote time, receive time, market session, data mode, entitlement
   status, market date, raw path/hash, and adapter version.
8. Credentials and OAuth tokens remain outside OneJournal's current runtime,
   as well as outside the repository, raw evidence, normalized quote rows,
   generated output, and DuckDB quote tables. The target isolated OneJournal
   provider-integration service may own approved provider connections, but must
   keep secrets outside all of those evidence, storage, presentation, and Git
   boundaries. Credentialed code retained only in isolated legacy directories
   is not an active or approved runtime path.
9. Quote data is local-only for the connected owner's own portfolio. It is not
   redistributed, shared between users, committed to Git, or exposed through a
   public endpoint.
10. No fixed raw-quote deletion duration is approved yet. Retention must comply
    with current provider terms and a later owner-approved retention/deletion
    policy. Until then, automatic deletion is disabled; this is not permission
    for indefinite redistribution or public storage.

### User responsibility and terms acknowledgement

11. OneJournal does not grant a user any right to receive, retain, display, or
    redistribute market data. The user must connect an account they are
    authorized to use and remain responsible for the provider agreement,
    subscription, jurisdiction, exchange terms, and permitted use that apply to
    that account.
12. Before a provider connection can be activated or used to retrieve quotes,
    the production product must obtain an explicit, versioned acknowledgement
    from that user for that provider connection. The acknowledgement must state
    that the user:

    - is authorized to use the connected account and credentials;
    - has reviewed and accepts the applicable provider and market-data terms;
    - is responsible for maintaining any required subscriptions or
      entitlements;
    - will use the retrieved data only for purposes allowed by those terms,
      including their own portfolio where applicable;
    - will not use OneJournal to redistribute or publicly expose licensed data;
      and
    - understands that OneJournal does not supply or certify a market-data
      licence.

13. The acceptance record must be append-only and auditable. At minimum it must
    identify the future authenticated user, provider, opaque connection UID,
    acknowledgement-text version, provider-terms reference, acceptance time in
    UTC, and the product version that presented it. It must not store broker
    credentials, tokens, account numbers, or copied private payloads.
14. Missing, expired, superseded, or connection-mismatched acknowledgement
    fails closed. Re-acknowledgement is required when the displayed notice
    changes materially, the provider connection owner changes, or current
    provider terms require it.
15. A user acknowledgement is evidence of the user's declaration, not proof of
    a live market-data entitlement. The provider adapter must still verify and
    preserve the provider-reported entitlement and delay state for every quote
    flow. Unknown or denied entitlement remains unusable even when an
    acknowledgement exists.
16. The current prototype has no approved authentication or tenancy model, so
    this change defines the contract only. It does not add a placeholder user
    identity, acceptance table, or UI checkbox. Those are implemented together
    after authentication and tenancy are approved, before any live quote
    connection is enabled.

### Transition and target provider boundary

17. For the current bounded PNL-02 evidence step only, OneBot/VPS is the
    temporary single owner of the available Schwab application and refreshable
    token. OneJournal's current runtime has no Schwab client ID, secret, token
    file, refresh path, or provider-call operator.
18. This temporary bridge may export only a separately approved, versioned,
    private quote evidence bundle. The bundle contains exact response bytes and
    a secret-free manifest binding request scope, approval, terms
    acknowledgement, source commit, timestamps, checksum, and zero
    refresh/account/order/database counts.
19. The target architecture makes OneJournal the only project that owns
    approved provider connections and calls Schwab, IBKR, Moomoo, or later
    providers through isolated provider-specific connectors behind the common
    quote contract. Moving Schwab ownership requires separately approved
    credential storage, connection identity, security, deployment, and cutover;
    OneBot access must be retired before OneJournal becomes token owner. The two
    projects must never refresh the same token lifecycle. Private transfer,
    durable storage, acceptance, and deployment remain separate gates.

### Freshness and polling

20. Freshness is computed at the evaluation instant; it is not persisted as a
    permanent property of a quote.
21. A real-time regular-session quote is `live_fresh` for at most 60 seconds.
    A pre-market or after-hours quote is `live_fresh` for at most 120 seconds.
    These are versioned, configurable safety thresholds.
22. Provider-reported delayed data is labelled `delayed` and is not current
    valuation evidence. Unknown or denied entitlement, unknown data mode,
    future-dated timestamps beyond five seconds, crossed bid/ask, and stale
    quotes fail closed.
23. An official close, frozen quote, or last real-time quote retained after
    provider-declared market close is labelled `market_closed_last`, never
    `live_fresh`. An approved exchange-calendar service must supply market-open
    expectations before OneJournal relies on calendar inference.
24. Recommended active-session polling defaults are 15 seconds for stocks,
    30 seconds for options, and 60 seconds in extended sessions. Polling pauses
    after five minutes of user inactivity and stops while the market is closed.
25. Background polling is disabled. Polling may begin only while an
    authenticated journal session is active, the provider connection is valid,
    and a separately approved read-only operator or service is running.
26. Rate limits, subscription limits, retry/backoff, and unsubscribe behavior
    are provider-adapter responsibilities. A rate-limit or entitlement failure
    cannot be hidden by continuing to publish the last quote as live.

### Financial boundary

27. Normalized quote evidence is not automatically a P&L mark. PNL-03 must
    explicitly approve the mark-selection method (for example midpoint, last,
    official close, or provider mark), spread-quality handling, and instrument
    exceptions before wiring quotes into unrealized P&L.
28. The current unqualified `marks` dictionary and fill-derived position
    `market_price` remain prototype-only. They cannot establish publication-
    grade unrealized P&L.

## Boundaries

This decision does not authorize live broker access, background scheduling,
streaming, a runtime database migration, a mark-selection methodology, quote
redistribution, multi-user tenancy, a production API, or any order endpoint.

For the current owner-operated local deployment, permitted quote evidence may
be stored on the user's own computer under the private raw and DuckDB paths
defined above. A future hosted or multi-user deployment is a different storage
and distribution context; it requires separate provider-specific licensing,
retention, privacy, authentication, and tenancy approval before server-side
quote storage is enabled.

The repository implements the normalized contract, fail-closed policy loader,
additive migrations, transactional persistence, and synthetic validation.
Migration `0012` adds a provider-neutral capture envelope that binds exact
instrument requests, quote/receive/evaluation times, New York market date,
checksum-backed local evidence location, and the complete ingestion fingerprint
before normalized rows may be persisted. The Schwab-specific adapter and
credential-free evidence importer are implemented offline under
`docs/schwab_quotes_json_schema_contract.md`; the current OneBot capture producer
is only a temporary evidence bridge. The target provider plane is an isolated
OneJournal integration service with one connector per provider. Neither the
bridge nor the target plane is accepted for live use. Provider compatibility
still requires an official authenticated payload captured through a separately
approved read-only call and a sanitized contract fixture derived without
private data.

## Alternatives considered

### Use only position snapshot prices

This is simple but does not establish an independent quote timestamp, delay,
entitlement, or session state. Rejected as current valuation evidence; retained
as broker reconciliation evidence.

### Use one universal third-party quote source

This can simplify implementation but separates valuation from each connected
user's broker entitlement and introduces licensing and cross-provider mismatch.
Rejected as the default. A later explicit fallback policy may be proposed with
visible source labels and reconciliation rules.

### Store only the latest price

This loses source lineage and makes replay, stale-data diagnosis, and historical
valuation audit impossible. Rejected.

## Consequences

### Positive

- Schwab, IBKR, and Moomoo adapters can converge on one stable quote contract.
- Every quote remains traceable to an immutable local response and adapter
  version.
- Stale, delayed, unentitled, and closed-session states cannot masquerade as
  live data.
- Credentials and private account identifiers remain outside quote records.
- The website can later poll only visible holdings without putting provider
  parsing or heavy work in the request path.

### Negative and trade-offs

- A provider adapter must preserve more metadata than a simple symbol/price
  pair.
- The journal cannot show publication-grade unrealized P&L until the Schwab
  adapter, mark policy, and position reconciliation are validated.
- Local raw quote evidence consumes storage until retention policy is approved.
- Provider-specific subscriptions, session limits, and API changes require
  adapter-level monitoring and tests.

## Compatibility and migration

Migration `0011` adds `market_quote_ingestion_runs` and
`normalized_market_quotes`. It alters no existing table and does not run against
the live journal database as part of this work. Existing payloads and position
rows remain compatible but do not gain authoritative freshness by migration
alone.

Migration `0012` adds nullable envelope-lineage columns to the ingestion-run
table without rewriting migration `0011`. New provider-neutral writes require
the versioned capture contract and full-envelope fingerprint. Existing
migration-0011 rows remain legacy normalized evidence; no current runtime
database was migrated by this implementation.

Newly normalized quotes use identity version `onejournal.normalized-quote.v2`,
which covers receipt time, session, entitlement, market date, logical raw
location, and adapter version in addition to source, instrument, provider quote
time, and prices. Existing migration-0011 rows remain readable; they are not
silently re-identified or replayed as version-2 capture rows.

Any future quote payload/API contract must be versioned and must expose source,
as-of time, freshness status, and failure state without account identifiers or
private raw paths.

## Security, privacy, and financial impact

Raw responses and normalized quote rows reveal holdings interests and licensed
market data. They remain private local financial data. Logs and errors may show
provider and instrument identities only when appropriate; they must never show
tokens, account numbers, usernames, or complete private payloads.

No quote operation may call a broker order endpoint. Missing or invalid quote
evidence makes affected current valuations unavailable rather than zero.

## Validation

The accepted contract requires tests for:

- deterministic quote identity and provider-scoped raw lineage
- timezone-aware provider and receive timestamps
- fresh, stale, delayed, denied, unknown, future, crossed, closed, and missing-
  price behavior
- provider/connection/as-of consistency within an ingestion run
- exact requested/received identity equality and complete-batch acceptance
- receive/evaluation ordering and New York market-date consistency
- repository-policy loading with cross-provider fallback disabled
- provider-neutral source location and full-envelope replay conflict handling
- atomic and idempotent temporary-DuckDB persistence
- migration creation, ordering, checksums, and replay
- no secret, raw payload, runtime DB, or generated-output tracking
- no network or order calls in unit and migration tests
- fail-closed acknowledgement configuration that cannot substitute for
  provider-reported entitlement

PNL-02A's synthetic adapter and interim offline producer/consumer boundary do
not establish provider compatibility or the target provider-integration plane.
PNL-02 is not complete until a sanitized official Schwab response validates the
adapter mapping and separately approved capture, normalization, durable
storage, freshness assessment, security controls, and single-owner cutover
prove the end-to-end OneJournal connector boundary.

## Rollback or supersession

Before live migration, rollback is branch/commit reversion because no runtime
state has changed. After a live additive migration, OneJournal uses a reviewed
forward corrective migration or restores a verified pre-migration backup; it
does not destructively drop quote evidence.

A later accepted ADR may supersede provider order, retention, thresholds,
calendar service, or fallback rules without weakening lineage, entitlement,
privacy, and fail-closed requirements.
