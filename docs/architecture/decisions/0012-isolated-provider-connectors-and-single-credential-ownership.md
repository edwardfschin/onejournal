# ADR-0012: Isolate provider connectors and enforce single credential ownership

- Status: Accepted
- Date: 2026-08-28
- Decision owners: OneJournal project owner
- Related roadmap items: PNL-02-T10 through PNL-02-T16
- Related contracts: ADR-0001, ADR-0002, ADR-0009, ADR-0011,
  `docs/onejournal_data_contract_v1.md`, `config/marketdata.yaml`
- Supersedes: None
- Superseded by: None

## Context

OneJournal currently has no active broker credential, token-refresh path, or
provider-call operator. Its Schwab quote adapter, provider-native session
resolver boundary, capture-envelope validator, and evidence importer are
credential-free. All configured market-data providers remain disabled.

For the bounded PNL-02 evidence step, OneBot/VPS is the temporary sole owner of
the available Schwab application and refreshable token. OneJournal consumes
only separately approved, checksum-bound private evidence. That bridge is not
the target architecture and must not become a permanent OneJournal dependency.

PNL-02-T10 requires a target security and ownership design before a
credentialed OneJournal connector can be implemented. The design must support
provider-specific authentication and session behavior without allowing those
details to enter normalized quote, journal, financial, or presentation
contracts. It must also prevent the journal website, provider adapters,
ingestion operators, or multiple processes from competing to refresh or use the
same credential lifecycle.

Provider authentication is not uniform. Schwab uses its provider-specific
authorization flow; an IBKR username may have only one brokerage session and
market data requires that session; Moomoo uses an OpenD gateway and its own
connection and entitlement model. The common boundary must therefore define
ownership and safety invariants without pretending that every provider uses an
OAuth refresh token.

The production website authentication, authorization, tenancy, hosting, and
deployment architecture remains unresolved. This decision must not silently
choose any of those policies.

## Decision

### Isolated provider-connector plane

1. OneJournal will use a dedicated provider-connector plane, separate from the
   website/API process, journal and P&L services, DuckDB writers, reporting
   workers, and any future execution plane.
2. Each provider connector owns only its provider-specific authentication,
   session lifecycle, exact read-only request construction, rate limiting,
   immutable raw-response capture, and secret-free capture audit. Provider
   adapters remain deterministic, credential-free transformations behind that
   acquisition boundary.
3. The first Schwab implementation is an explicitly invoked bounded operator,
   not a background scheduler or public service. A later continuously running
   or website-triggered connector mode requires separate deployment,
   authentication, authorization, scheduling, and operational approval.
4. A connector accepts only a versioned, provider-neutral request containing an
   opaque `connection_uid`, explicit instrument mappings, exact approved
   operation, as-of date, approval reference, and terms-acknowledgement
   reference. It exposes no arbitrary URL, HTTP method, headers, provider body,
   account identifier, or generic pass-through operation to callers.
5. A connector may write an immutable raw response and secret-free manifest to
   an approved private evidence root. It has no journal database path or
   credentials and cannot persist normalized quotes. Credential-free validation
   and the common capture/persistence boundary remain separate downstream
   responsibilities.
6. The connector has no public inbound listener. A same-host implementation
   may use an owner-only local command or local IPC boundary. Any cross-host or
   hosted transport must be separately designed and approved rather than
   inheriting trust from this local-owner decision.

### Credential and session ownership

7. Persistent credentials, refresh tokens, private keys, session secrets, and
   provider login material live behind an injected provider-credential-store
   interface. They remain outside Git, repository configuration, raw evidence,
   manifests, logs, normalized records, DuckDB, generated output, command-line
   arguments, and caller-visible responses.
8. Offline implementation and tests use a non-persistent fake credential store.
   Before any real activation, the deployment must separately approve one
   concrete host-appropriate secret backend, its backup/recovery behavior, and
   the connector operating identity. This ADR does not select a production
   secret manager or hosting platform.
9. Exactly one active connector owner and one credential-store record are
   permitted for each `(provider, connection_uid)` in an environment. A
   per-connection exclusive lease serializes authentication, refresh, session
   initialization, and credential rotation. The connector must fail closed if
   it cannot prove exclusive ownership.
10. Credential replacement is atomic and generation-checked. A successful
    refresh or session transition advances an opaque credential-generation UID;
    stale processes cannot overwrite a newer generation. Token values or token
    hashes are never used as public or audit identity.
11. A provider-specific authentication driver owns refresh, reauthorization,
    session keepalive, logout, and revocation semantics. The common connector
    must not assume every provider has a refresh token. Ambiguous refresh or
    session state becomes `reauthentication_required`; another process must not
    guess, retry indefinitely, or take over silently.

### Opaque connection identity and least privilege

12. Every new credentialed connection created under this decision receives a
    stable, randomly generated opaque local `connection_uid` with at least 128
    bits of entropy. It is not derived from a username, account number, token,
    provider subject, email address, or future OneJournal user identifier.
    Credential rotation does not change it. A later approved tenancy model may
    map it to an authenticated owner without changing quote identity. Existing
    bounded evidence identifiers remain historical lineage and are not silently
    reidentified or activated as credential-store keys.
13. Each connector uses an explicit provider/version endpoint allowlist. Only
    the authentication/session operations required by that provider and the
    approved quote and market-session reads are reachable. Redirects to an
    unapproved host, arbitrary paths, account discovery, portfolio endpoints,
    transaction endpoints, order endpoints, and dynamic methods fail closed.
14. The connector code and runtime contain no order model, order request
    builder, account-order identifier, or broker-write API. A provider session
    that technically permits trading does not authorize OneJournal to expose or
    call those endpoints.
15. Network egress is limited to the exact approved provider authentication and
    market-data hosts where the deployment can enforce it. The connector runs
    under a dedicated least-privilege operating identity that can access only
    its credential-store entries and approved private capture/audit roots.

### Rate limits, retry, and fail-closed behavior

16. Provider libraries may not hide retries. Each provider operation declares
    a versioned retry policy and request deadline. Read-only quote or schedule
    requests may retry only bounded transient transport failures, HTTP 429, and
    explicitly approved transient provider failures, while honoring provider
    `Retry-After` guidance.
17. Authentication, refresh, entitlement, permission, identity, schema, and
    scope failures are not treated as ordinary transient errors. A provider-
    supported serialized refresh may be attempted once for an expired session,
    followed by at most one replay of the exact read-only request. An ambiguous
    result fails closed and requires operator review or reauthorization.
18. Every attempt is independently auditable. Partial, mixed-attempt, changed-
    scope, or incomplete responses never cross the complete-capture boundary.
    Rate-limit exhaustion, provider outage, or failed authentication cannot be
    hidden by labelling an earlier quote as live.

### Audit and secret-safe diagnostics

19. Connector audit records are append-only, secret-free, and versioned. They
    record the run UID, provider, opaque connection UID, connector and policy
    versions, credential-generation UID, approval and acknowledgement
    references, operation class, request-scope hash and count, start/end times,
    attempt and refresh counts, safe provider status/correlation metadata, raw
    locator/hash/byte count when captured, final status, and stable failure
    code.
20. General service logs contain only allowlisted operational fields. They must
    not contain authorization headers, cookies, tokens, secrets, usernames,
    account identifiers, provider request/response bodies, private paths, or
    exact holdings scope. Detailed request scope and raw responses remain only
    in approved private evidence/audit storage.
21. A failed run writes no accepted capture envelope and no normalized or
    journal state. Crash remnants remain explicitly incomplete and are never
    promoted by filename discovery or a later retry.

### Recovery, rollback, and Schwab single-owner cutover

22. Connector code is implemented and validated offline while every live
    provider remains disabled. Enabling a provider, installing credentials,
    using or refreshing a token, making a provider call, deploying a connector,
    or starting a service remains a separate explicit approval.
23. The Schwab cutover is break-before-make:

    1. prove the OneJournal connector, credential boundary, raw capture, audit,
       and failure tests offline;
    2. stop and disable every OneBot Schwab provider-call and token-refresh path;
    3. verify no OneBot process, scheduler, service, or operator path can use or
       refresh the Schwab credential lifecycle;
    4. revoke or make the former OneBot credential inaccessible before
       provisioning the sole OneJournal owner;
    5. install or authorize the credential only in the approved OneJournal
       secret backend and record a new owner epoch without recording secrets;
    6. enable and validate OneJournal through a separately approved bounded
       provider call; and
    7. keep OneBot access retired after acceptance.
24. Cutover evidence records both owner states and proves there was no overlap.
    Copying a still-usable token to OneJournal while OneBot retains access is
    forbidden.
25. Rollback is also break-before-make: disable OneJournal, revoke or remove its
    usable credentials under explicit approval, verify it cannot call or
    refresh, and only then separately reauthorize the former owner if rollback
    is approved. A credential backup must never create two active owners.

## Boundaries

This decision is limited to the owner-operated PNL-02 connector boundary and
the provider-independent invariants needed by later Schwab, IBKR, Moomoo, and
future adapters.

It does not approve or implement:

- production website authentication, authorization, tenancy, or user mapping;
- a production secret manager, hosting platform, deployment topology, public
  or cross-host connector API, background schedule, or availability target;
- any real credential installation, transfer, use, refresh, revocation, or
  provider login;
- broker account discovery, transactions, positions, orders, or execution;
- live provider calls, private evidence transfer, DuckDB migration, durable
  runtime ingestion, synchronization, deployment, or PNL-02 acceptance; or
- hosted or multi-user storage, redistribution, licensing, retention, or
  deletion policy.

Until the later cutover is explicitly approved and executed, OneBot/VPS remains
the temporary sole Schwab token owner and the OneJournal runtime remains
credential-free.

## Alternatives considered

### Keep credentials in the website or journal process

This reduces process count but exposes provider secrets and trading-capable
sessions to larger, user-facing and database-writing surfaces. It weakens least
privilege, no-order proof, independent recovery, and secret-safe logging.
Rejected.

### Let multiple scripts share a token file or environment variables

This is simple initially but creates concurrent refresh races, stale-token
overwrite, untraceable ownership, command/process leakage, and an unsafe dual-
owner cutover. Rejected.

### Make OneBot the permanent market-data gateway

This avoids a Schwab migration but makes OneJournal depend on another project's
runtime, credentials, deployment, and derived outputs. It prevents OneJournal
from owning a provider-neutral connector plane and complicates IBKR, Moomoo,
and future user-owned connections. Rejected; OneBot remains only the temporary
evidence bridge.

### Implement one generic arbitrary broker proxy

A generic URL/method/body proxy minimizes adapter code but would expose account
or order endpoints and make endpoint-level least privilege impossible to
prove. Rejected in favor of explicit provider/version allowlists.

### Choose production authentication, tenancy, and secret infrastructure now

This could remove a later design step but would silently settle unresolved web,
hosting, identity, privacy, and multi-user policy beyond PNL-02's local-owner
scope. Deferred. The connector boundary remains compatible with a later owner
mapping and deployment-specific credential-store implementation.

## Consequences

### Positive

- One credential lifecycle has one provable owner.
- Schwab, IBKR, Moomoo, and later providers can keep different authentication
  and session mechanics behind one provider-independent evidence contract.
- Website, journal, financial, and presentation code cannot access credentials,
  raw provider responses, or broker order endpoints.
- Crash, refresh, retry, cutover, and rollback behavior fail closed and remain
  auditable without exposing secrets.
- The local-owner implementation does not force a premature production tenancy
  or hosting decision.

### Negative and trade-offs

- The connector plane adds a process boundary, credential-store interface,
  exclusive ownership mechanism, structured audit, and provider-specific
  operational logic.
- A concrete secret backend and deployment identity still require approval
  before real activation.
- Providers whose market-data sessions also permit trading require stronger
  endpoint and egress controls because provider permissions alone may not
  provide quote-only least privilege.
- Break-before-make cutover creates a deliberate service interruption, but it
  prevents dual token ownership.

## Compatibility and migration

This decision changes no current code, database, payload, provider setting, or
private evidence. Existing normalized quote, session-authority, capture, and
repository contracts remain unchanged. `connection_uid` remains the shared
opaque connection dimension. Existing bounded evidence retains its recorded
connection identity; the random-identity rule applies prospectively to new
credentialed connections.

PNL-02-T12 may add provider-connector interfaces and an offline Schwab
implementation behind the existing complete-capture contract. It must not
replace the credential-free Schwab adapter or allow the connector to write
DuckDB. The temporary OneBot evidence importer remains available until the
explicit T15 cutover and is then retired or constrained through a separately
approved focused change.

Any later cross-host connector API, production user-to-connection mapping,
hosted secret backend, or multi-user persistence contract requires a versioned
and separately approved design.

## Security, privacy, and financial impact

Provider credentials and raw responses are high-sensitivity private data.
Normalized quotes and exact instrument scopes reveal financial interests even
when they contain no account number. The connector therefore minimizes both
secret exposure and holdings exposure in logs and inter-process messages.

No connector output becomes a valuation merely because acquisition succeeded.
The existing exact identity, entitlement, provider-native session authority,
freshness, complete-capture, and downstream persistence gates still apply.
Missing, partial, stale, ambiguous, or unauthorized evidence remains
unavailable rather than zero or live.

This connector plane has no execution authority. Provider sessions that could
technically access trading endpoints are constrained by code, operation and
endpoint allowlists, process isolation, and deployment egress controls.

## Validation

Before T10 can support later connector implementation, review must confirm that
this ADR covers every tracker gate and does not select production authentication
or tenancy.

Before any real provider activation, automated validation must prove:

- the website, journal, adapter, importer, and database layers cannot read the
  provider credential store;
- the connector has no journal database, account, transaction, position, or
  order capability;
- every outbound host, method, path, redirect, and operation is allowlisted;
- one per-connection owner lease serializes authentication and refresh, and a
  stale generation cannot overwrite current credential state;
- secrets and exact private request/response data cannot enter ordinary logs,
  errors, manifests, fixtures, Git, or generated output;
- retry limits, `Retry-After`, authentication failure, entitlement failure,
  rate-limit exhaustion, timeout, crash, partial response, and ambiguous
  refresh all fail closed with complete audit evidence;
- immutable raw capture and secret-free audit are atomically completed before
  the credential-free adapter/capture boundary can accept a batch;
- synthetic Schwab quote and schedule paths produce the existing provider-
  neutral contracts without network or credentials;
- IBKR and Moomoo connector conformance can use the same acquisition contract
  without assuming Schwab OAuth behavior;
- repository secret/order guards and the full clean CI suite pass; and
- a credential-free cutover rehearsal proves break-before-make state
  transitions and rollback ordering through
  `onejournal.provider-connection-cutover.v1`; and
- the pure validator rejects dual ownership, a missing owner gap, reused owner
  or credential lineage, host collision, phase/time disorder, a public target
  listener, and an operational journal mount without performing the cutover.

Real credentials, provider calls, private evidence, deployment, and the T15
cutover require separate bounded approval and dated evidence.

## Rollback or supersession

While proposed, this document can be revised or removed without runtime impact.
After acceptance but before connector activation, rollback is a focused
commit/branch reversion while providers remain disabled.

After activation, code rollback begins by disabling and stopping the OneJournal
connector. Credential rollback follows the break-before-make procedure above;
it must never reactivate OneBot or another owner until OneJournal's provider-call
and refresh capability is proven inactive. A later accepted ADR may supersede
the credential backend, IPC, deployment, or tenancy mapping without weakening
single ownership, no-order isolation, secret safety, evidence lineage, or
fail-closed behavior.
