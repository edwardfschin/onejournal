# ADR-0013: Enforce provider-use authorization and raw-evidence lifecycle policy

- Status: Accepted
- Date: 2026-08-28
- Decision owners: OneJournal project owner
- Related roadmap items: PNL-02-T11 through PNL-02-T16
- Related contracts: ADR-0007, ADR-0009, ADR-0011, ADR-0012,
  `config/marketdata.yaml`,
  `onejournal.provider-usage-policy.v1`,
  `onejournal.provider-usage-acknowledgement.v1`
- Supersedes: None
- Superseded by: None

## Context

ADR-0009 requires explicit, versioned terms acknowledgement before a provider
connection is activated or used for quote retrieval. It also requires the
acknowledgement to remain distinct from provider-reported entitlement. The
repository previously recorded those requirements only as configuration text
with an enforcement status of
`contract_only_until_auth_and_tenancy_are_approved`.

ADR-0012 now defines an isolated, local-owner provider-connector plane without
selecting production authentication or tenancy. PNL-02-T11 therefore needs an
enforceable gate that T12 can consume without inventing a production user or
putting credentials, provider access, or database writes into the policy layer.

Current official Schwab public documents establish the following facts for the
approved local-owner scope:

- the Schwab Online Services Agreement grants a limited personal licence,
  prohibits unauthorized commercial use and redistribution, incorporates
  service-specific rules, and may change over time:
  <https://www.schwab.com/legal/terms>;
- the current Online Addendum to the Electronic Services Agreement records
  account-level exchange acknowledgement, distinguishes professional from
  nonprofessional use, and limits a nonprofessional subscriber to personal,
  non-business use:
  <https://www.schwab.com/legal/electronic-services-agreement-online>; and
- the Trader API Market Data Production specification and related provider
  terms are presented through Schwab's authenticated developer portal:
  <https://developer.schwab.com/products/trader-api--individual/details/specifications/Market%20Data%20Production>.

The public documents reviewed on 2026-08-28 did not state a fixed raw API-data
retention duration. OneJournal must not invent one or treat that absence as
permission for hosted storage, redistribution, or automatic deletion. The
connection owner must confirm the authenticated provider terms that apply to
the actual application and account before activation.

The production authentication, tenancy, hosted-storage, and user-to-connection
mapping decisions remain unresolved. They are not required to establish the
approved single-owner local boundary.

## Decision

### Active provider terms profile

1. OneJournal maintains exactly one active, versioned provider-use profile per
   provider in `config/marketdata.yaml` for an approved operating scope.
2. The initial Schwab profile is limited to an
   `owner_operated_local_connection` and `personal_noncommercial` use. It
   forbids redistribution, public display, and hosted storage.
3. A profile identifies the acknowledgement notice, official terms references,
   review instant, required declarations, entitlement rule, and raw-evidence
   lifecycle policy.
4. The public terms references do not replace the authenticated application,
   account, exchange, jurisdiction, or provider terms. The local connection
   owner must declare that the applicable authenticated terms were reviewed.
5. A material terms, permitted-use, retention, or notice change requires a new
   profile or notice version. Activating it invalidates acknowledgements bound
   to the previous version.

### Connection-scoped acknowledgement

6. Before a connector may activate or retrieve provider evidence, it must
   validate an externally persisted
   `onejournal.provider-usage-acknowledgement.v1` record against the active
   profile.
7. The record binds the exact provider, opaque `connection_uid`, active terms
   profile, notice version, operating scope, acceptance time in UTC, OneJournal
   product version, raw-evidence lifecycle policy, and complete declaration set.
8. A deterministic SHA-256 identity covers every acknowledgement field. An
   append-only persistence layer may use that identity for replay and audit; it
   must reject changed content under the same identity.
9. Missing, pre-review, future-dated, tampered, incomplete, superseded,
   provider-mismatched, connection-mismatched, scope-mismatched, notice-
   mismatched, or lifecycle-mismatched acknowledgement fails closed before the
   provider request boundary.
10. The local-owner record deliberately contains no placeholder production user
    identity. A future approved authentication and tenancy layer must bind its
    authenticated user to the same opaque connection without changing quote or
    acknowledgement history.
11. No real acknowledgement record is created by T11. Its private append-only
    storage, creation operator, or later UI remains a separate implementation
    and operational boundary.

### Entitlement remains provider evidence

12. Authorization proves only the owner's declaration and the permitted local
    operating scope. It does not grant, certify, or infer market-data rights.
13. Every active provider profile requires runtime provider-reported
    entitlement. The later connector and adapter must preserve provider delay,
    denial, unknown, and entitlement facts through the existing normalized
    quote contract.
14. Delayed, denied, unknown, absent, or conflicting entitlement continues to
    fail closed under ADR-0009 even when acknowledgement validation succeeds.
    Session authority cannot override it.

### Raw-evidence lifecycle

15. Raw provider responses remain immutable, private, local evidence outside
    Git, public output, ordinary logs, and the journal UI.
16. The initial lifecycle policy defines no fixed deletion deadline because the
    reviewed official public sources establish none. Automatic deletion is
    disabled.
17. The connector, adapter, importer, and journal repository receive no delete
    capability from this decision.
18. A future deletion operator may proceed only with a separately approved,
    exact-scope deletion authorization and an audit path ready to record at
    minimum the approval, provider, connection, acknowledgement, lifecycle
    policy, targeted source identities and hashes, reason, affected downstream
    lineage, authorization time, and completion or failure state.
19. The implemented deletion function creates only a deterministic authorization
    value. It does not locate, modify, or delete evidence.
20. If current provider terms later require a retention duration, revocation
    deletion, or another lifecycle action, OneJournal must create and approve a
    new provider profile, obtain a new acknowledgement, and implement the rule
    through a separately approved audited operator. The provider rule takes
    precedence over the no-fixed-duration default.

## Boundaries

This decision and implementation are limited to a pure offline authorization
contract. They do not approve or implement:

- production authentication, tenancy, user persistence, a UI checkbox, hosted
  storage, public display, or multi-user access;
- a real acknowledgement record or private acceptance store;
- a provider connector, network request, login, credential, token, refresh,
  entitlement call, quote capture, or market-session capture;
- a raw-evidence deletion operator, automatic deletion, migration, database
  write, evidence mutation, or actual deletion;
- OneBot modification, Schwab cutover, deployment, synchronization, push, or
  PNL-02 acceptance; or
- legal advice or a representation that the cited public terms are the complete
  agreement governing a particular connection.

OneBot/VPS remains the temporary sole Schwab token owner. The current
OneJournal runtime remains credential-free and every provider remains disabled.

## Alternatives considered

### Wait for production authentication and tenancy

This would avoid a temporary local-owner shape but would unnecessarily block
the approved owner-operated PNL-02 connector and mix provider-use enforcement
with unresolved website identity architecture. Rejected. The local contract
uses the already approved opaque connection identity and remains compatible
with a later authenticated owner mapping.

### Treat the acknowledgement identifier as sufficient

Passing an unchecked string is mechanically simple but cannot prove the active
terms, declaration content, exact connection, scope, lifecycle policy, time, or
tamper-resistant identity. Rejected in favor of full deterministic validation.

### Infer entitlement from acknowledgement

This would confuse the owner's declaration with the provider's actual market-
data state and could make delayed or denied data appear usable. Rejected.

### Choose an arbitrary fixed retention duration

This could limit disk use but would invent a provider or legal requirement and
could either delete audit evidence prematurely or retain it longer than later
terms allow. Rejected until current provider-specific authority establishes a
duration.

### Allow automatic or silent deletion

This would break immutable raw-to-normalized lineage and make downstream quote
and valuation evidence impossible to audit. Rejected. Deletion requires an
explicit approval and audit boundary.

## Consequences

### Positive

- T12 receives one deterministic, provider-neutral pre-request gate.
- Terms, provider, connection, scope, notice, and raw lifecycle are bound
  together and supersede fail closed.
- Provider-reported entitlement remains authoritative.
- Schwab, IBKR, Moomoo, and later providers can use separate active profiles
  without changing the common acknowledgement contract.
- The local-owner implementation does not settle production identity, hosting,
  or tenancy.
- No code in this task can call a provider, read credentials, write a database,
  or delete evidence.

### Negative and trade-offs

- A connection cannot activate until an acknowledgement record exists outside
  this task and validates against the active profile.
- Current provider terms still need periodic and activation-time owner review;
  the repository does not detect remote terms changes automatically.
- Raw evidence continues to consume private local storage until an approved
  provider rule or exact-scope deletion is implemented.
- Future hosted or multi-user use requires separate licensing, privacy,
  retention, identity, and storage decisions.

## Compatibility and migration

The implementation adds `src/onejournal/provider_connectors/usage_policy.py`
and the `marketdata.provider_usage` configuration section. Existing quote,
capture, session-authority, repository, importer, and DuckDB contracts are not
changed. No migration runs and no persisted record is reinterpreted.

The earlier `terms_acknowledgement` block remains as a high-level compatibility
summary, but its scope and enforcement status now describe the implemented
local-owner boundary. T12 must consume the new versioned policy and
acknowledgement objects rather than trusting the old summary fields or an opaque
acknowledgement string.

Any future acknowledgement persistence schema, authenticated owner mapping,
hosted provider profile, retention deadline, or deletion implementation needs a
versioned, separately approved design and migration where applicable.

## Security, privacy, licensing, and financial impact

Acknowledgement records are private security and licensing evidence even though
they contain no credentials or account numbers. They must remain append-only,
owner-only, secret-free, and outside Git and ordinary logs.

The profile forbids redistribution, public display, and hosted storage for the
approved scope. The validator accepts only exact known fields and HTTPS terms
references. It does not fetch remote terms or accept arbitrary provider
requests.

Successful authorization does not make a quote fresh, complete, reconciled, or
eligible for valuation. Existing entitlement, session, timing, identity,
freshness, persistence, and PNL-03 mark-selection gates remain controlling. No
order capability is added.

## Validation

Focused tests must prove:

- strict loading of the versioned active provider profile;
- local, personal/noncommercial, non-redistributed, non-public, non-hosted
  defaults;
- exact provider, connection, profile, notice, scope, lifecycle, time,
  declaration, and deterministic-identity binding;
- rejection of pre-review, future, incomplete, tampered, superseded, and
  expanded-scope records;
- inability to configure redistribution or automatic deletion silently;
- explicit preservation of the provider-reported entitlement requirement;
- rejection of automatic or unaudited deletion authorization; and
- deterministic manual deletion authorization without any filesystem or
  database action.

Tests must use only repository configuration and synthetic in-memory or
temporary values. They must not create a real acknowledgement, read private
evidence, call a provider, access credentials, write a journal database, or
delete evidence.

## Rollback or supersession

Before a provider connector consumes this boundary, rollback is a focused
reversion of the module, configuration, tests, ADR/register, and roadmap update.
All providers remain disabled, so no credential, acknowledgement, raw evidence,
or database state needs migration.

After connector adoption, a later ADR may supersede the profile, persistence,
identity mapping, retention, or deletion design only with compatibility for
existing acknowledgement and raw-lineage identities. Supersession must not
weaken provider-reported entitlement, non-redistribution, secret isolation,
explicit deletion approval, audit, or fail-closed behavior.
