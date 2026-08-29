# ADR-0014: Stage PNL-02 connector delivery separately from website hosting

- Status: Accepted
- Date: 2026-08-28
- Decision owners: OneJournal project owner
- Related roadmap items: PNL-02-T12 through PNL-02-T16, WEB-01, OPS-01 through OPS-06
- Related contracts: ADR-0009, ADR-0011, ADR-0012, ADR-0013, `config/marketdata.yaml`, `docs/onejournal_product_roadmap.md`
- Supersedes: None
- Superseded by: None

## Context

PNL-02 has approved provider-independent quote, session-authority, connector-isolation,
and provider-usage boundaries. The remaining work begins with an offline connector
implementation (PNL-02-T12) and later requires an explicit Schwab single-owner
cutover (PNL-02-T15). The current provider-use profile is local-only and declares
`hosted_storage_allowed: false`; it therefore does not authorize hosted storage of
live market-data evidence.

The current Streamlit prototype directly opens and writes the DuckDB journal. It is
not an approved production website or public service architecture. WEB-01 and the
operations roadmap items remain blocked, with no approved cloud vendor, hosting
account, secret backend, public endpoint, production database topology, or deployment
automation.

OneBot is the temporary Schwab evidence bridge and token owner. ADR-0012 prohibits
dual token lifecycle ownership and requires break-before-make cutover. It is not a
permanent OneJournal runtime or a foundation for the OneJournal deployment design.

On 2026-08-29, the project owner approved the current Mac as the temporary,
local-only T15 staging host. The approved scope uses macOS Keychain, exposes no
public listener, mounts no operational DuckDB journal, and forbids copying any
OneBot token. This is a bounded local target selection, not provider activation.

## Decision

PNL-02 will use a staged release sequence:

1. PNL-02-T12 through T14 remain local, offline, and credential-free until their
   separately approved provider-access gates are reached.
2. For the bounded T15 local-owner cutover, the current owner-operated Mac is the
   approved temporary staging host and must remain distinct from every OneBot runtime.
   A later remote staging host or VM requires a new approval. The connector runs under
   a distinct local identity and is not a public listener.
3. The staging connector is an isolated provider boundary: it has no order capability,
   no shared OneBot credential or refresh path, no mount of the operational DuckDB
   journal, and only the specifically approved provider egress and local operator or
   tightly scoped internal control path.
4. A future production website, public API, hosting vendor, production database, and
   deployment platform remain decisions for WEB-01 and OPS-01 through OPS-06. The
   Streamlit prototype must not be exposed as that website.

This ADR and the dated target approval accept the isolation boundary and temporary
local Mac target. They do not authorize deployment, provider activation, credential
installation, provider access, private-evidence creation, or journal storage.

## Boundaries

This decision does not authorize VPS or cloud provisioning, credentials or token
refresh, Schwab access, OneBot changes, database migration, private-evidence transfer,
live quote capture, deployment, synchronization, or a public service.

The current provider-use profile continues to prohibit hosted raw or normalized live
market-data storage. The temporary Mac is local rather than hosted; any private raw
capture must still use the separately approved external private vault and lifecycle,
not the repository or DuckDB. A future hosted target requires a replacement
provider-use profile after an authenticated review of the applicable provider terms,
exact data products, and storage location. Until separately approved, the Mac target
remains provider-disabled and credential-free.

At cutover, ADR-0012's break-before-make rule remains controlling: disable and make
the OneBot Schwab token unavailable before provisioning a newly authorized OneJournal
owner. Do not copy an active OneBot token to OneJournal. Rollback cannot create dual
ownership.

## Alternatives considered

### Continue using OneBot as the permanent connector host

This would reuse existing operational machinery but would couple OneJournal to a
temporary evidence bridge, obscure credential ownership, and weaken the single-owner
cutover boundary. It is rejected.

### Expose the current Streamlit application or connector through a public PaaS service

This could shorten a demonstration path, but it would decide unresolved web,
authentication, database, secret-management, and hosted-data policies prematurely.
It is deferred to WEB-01 and OPS-01 through OPS-06.

### Deploy the current PNL-02 branch now

The branch has no approved deployment target and the remaining offline, durable-ingest,
and cutover gates are incomplete. It is rejected.

### Use an isolated OneJournal staging host only after offline readiness

This preserves a small, auditable connector surface while keeping provider, data, and
website decisions separately approval-gated. It is accepted.

## Consequences

### Positive

- Connector ownership, broker access, and future website hosting remain independently
  reviewable and reversible.
- The first live-capable boundary can be validated without placing an operational
  journal database or public website beside provider credentials.
- OneBot has a defined temporary role rather than becoming a hidden OneJournal
  dependency.

### Negative and trade-offs

- A real provider cutover requires later credential, provider-access, private-evidence,
  OneBot-retirement, rollback, and operational approvals.
- This decision deliberately does not accelerate public website delivery.
- A dedicated staging host introduces future operating work that must be designed and
  accepted under the OPS roadmap.

## Compatibility and migration

No runtime artifact, persisted data, database schema, provider contract, or API is
changed by this ADR. PNL-02-T12 and T13 must preserve the existing capture and
repository contracts. Any later hosted-data authorization, deployment contract, or
database topology decision requires its own approved impact analysis and compatibility
path.

## Security, privacy, and financial impact

The staging connector must fail closed if its authorized provider use, credential
owner, connection identity, egress path, raw-evidence lifecycle, or session evidence
is absent or inconsistent. It must not submit orders or expose credentials, account
identifiers, raw provider payloads, or financial data in public endpoints or logs.

The connector host must be separate from OneBot and the journal store. The temporary
Mac stores credentials only in macOS Keychain and may write approved raw capture only
to the external private vault; it must not mount DuckDB. No quote may become
authoritative merely because it passed through the connector.

## Validation

This document is validated by the ADR register test and repository documentation
checks. It is not operational acceptance evidence.

Before a provider-disabled Mac staging rehearsal, validate the release artifact
identity, disabled-provider configuration, absence of credentials and live data,
Keychain policy gates, process identity, lack of public listener, no journal-database
mount, and rollback procedure. Before a real T15 cutover, additionally require a
fresh owner authorization, break-before-make evidence, secret-safe logs, exact allowed
egress, the approved private-evidence lifecycle, and PNL-02-T15 acceptance evidence.
The credential-free
`onejournal.provider-connection-cutover.v1` validator defines the required
four-phase evidence sequence, but passing it does not establish the external facts
or authorize any operational action.

## Rollback or supersession

This ADR makes no live change, so no runtime rollback is needed. A later staging
rehearsal rolls back by disabling the OneJournal connector and restoring the prior
verified provider-disabled artifact or configuration. Do not reactivate OneBot as a
fallback while a OneJournal owner remains active. A future approved hosting or
hosted-data ADR may supersede this decision without changing the historical PNL-02
evidence boundary.
