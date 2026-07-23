# ADR-0002: Define the initial OneJournal product scope

- Status: Accepted
- Date: 2026-07-23
- Decision owners: OneJournal project owner
- Related roadmap items: CON-01, JRN-02, PNL-01 through PNL-08, UXJ-01
  through UXJ-06, WEB-01 through WEB-09
- Related contracts: `AGENTS.md`, `docs/onejournal_data_contract_v1.md`,
  `docs/onejournal_product_roadmap.md`
- Supersedes: None
- Superseded by: None

## Context

OneJournal needs a bounded first production use case before its financial,
journal, database, and website contracts can be finalized.

The current implementation is an internal Streamlit prototype. It has
broker-independent normalized models carrying `source_broker` and
`source_account_id`, manual CSV fill parsing, and Schwab orders/transactions
normalization. The IBKR package and raw-data boundary are reserved, but no
active OneJournal IBKR adapter exists. Current normalized-fill validation
recognizes `stock` and `option` asset classes.

Building multi-user tenancy, every broker, every asset class, and automated
execution into the first production release would expand security, privacy,
accounting, reconciliation, and operational risk before the core journal and
P&L are trustworthy.

On 2026-07-23, the project owner approved the initial scope recorded below.

## Decision

The first production release of OneJournal will be:

- a single-user product
- capable of holding multiple brokerage accounts owned or controlled by that
  user
- broker-independent at the domain and data-contract layers
- integrated with Schwab first
- extended to IBKR next through the same normalized contracts
- focused initially on US-listed stocks and listed equity options
- read-only with respect to broker accounts
- focused on trustworthy journaling, portfolio review, realized and unrealized
  P&L, performance analytics, and risk visibility

Manual CSV remains a supported controlled import and recovery/backfill path. It
is not the preferred long-term live data source.

Schwab-first means Schwab is the first broker for which the complete approved
read-only account, order, transaction, fill, position, cash, reconciliation,
and portfolio workflow will be delivered. It does not permit Schwab-specific
logic in the journal domain, P&L engine, API, or frontend.

IBKR-next means its adapter must produce the same broker-independent contracts
and pass equivalent reconciliation and lineage gates. Existing legacy IBKR
scripts are evidence only and are not approved for direct reuse.

## Boundaries

### Included

- one authenticated owner
- multiple accounts belonging to that owner
- per-account, per-broker, and consolidated views
- confirmed broker activity and reconciled journal state
- trade journaling and structured review
- portfolio holdings and history
- realized and unrealized P&L after the calculation contract is approved
- performance and risk analytics derived from canonical records
- responsive production web access after the web architecture and security
  decisions are approved

### Excluded from the initial production release

- multi-user, household, team, advisor, client, or public tenancy
- accounts not owned or explicitly controlled by the single user
- broker order placement, cancellation, replacement, or modification
- paper or live automated trading
- futures, futures options, foreign exchange, cryptocurrency, bonds, mutual
  funds, and other unapproved asset classes
- tax filing, tax advice, regulatory reporting, or broker-statement replacement
- social, copy-trading, shared-journal, or public-profile features

The exact treatment of ETFs, index options, non-US listings, and other
instrument subtypes remains outside this decision. It must be resolved through
the asset/instrument contract before those records are presented as supported.

## Alternatives considered

### Start as a multi-user SaaS product

This would establish tenant isolation early but immediately requires durable
user/organization models, authorization, data partitioning, privacy controls,
billing or entitlement decisions, support procedures, and substantially
broader security testing. Rejected for the initial release.

### Support only one broker permanently

This simplifies ingestion but would allow broker-specific assumptions to leak
into the domain and make later expansion expensive. Rejected. OneJournal remains
broker-independent while sequencing Schwab before IBKR.

### Implement Schwab and IBKR simultaneously

This may expose normalization differences earlier but doubles integration and
reconciliation work before the canonical lifecycle and P&L contracts are
stable. Rejected in favor of Schwab-first, IBKR-next sequencing.

### Support broad asset classes immediately

This would require lifecycle and valuation rules for materially different
instruments before stocks and options are correct. Rejected for the initial
release.

### Include automated trading in the first production use case

This conflicts with the accepted journal/execution separation and bypasses the
paper-trading safety gates. Rejected.

## Consequences

### Positive

- The first release can optimize for one owner's real journaling and portfolio
  workflows without premature tenancy complexity.
- Multiple accounts and future brokers remain explicit domain dimensions.
- Schwab provides a bounded first integration against which canonical contracts
  and reconciliation can be proven.
- Stocks and equity options cover the initial journal focus while containing
  lifecycle and valuation scope.
- Financial correctness can be established before execution risk is introduced.

### Negative and trade-offs

- A later multi-user product will require a separately approved tenancy and
  authorization architecture plus data migration.
- IBKR users wait until Schwab contracts and workflows establish the reference
  implementation.
- Unsupported instruments must be rejected or shown as unavailable rather than
  approximated.
- Single-user scope does not remove the need for production authentication,
  authorization, privacy, backup, and audit controls.

## Compatibility and migration

This decision creates no immediate database or payload migration.

Future schemas must retain stable broker and account identity and support
account-level and consolidated results. They must not assume that a broker
account number is globally unique or safe to expose.

The single-user scope does not authorize silently hard-coding credentials,
personal identity, or a permanent absence of ownership boundaries into
financial records. Production authentication and ownership representation will
be decided with the web and security architecture.

Unsupported broker or asset records must fail explicitly at ingestion or remain
unpublished until their contracts exist.

## Security, privacy, and financial impact

All accounts, holdings, trades, journal notes, and financial results are private
data even though the initial product has one user.

Broker integrations use read-only access and least privilege. Broker-native
identifiers must not be exposed unnecessarily through frontend payloads, logs,
screenshots, fixtures, or public URLs.

Consolidated portfolio and P&L values cannot be implemented until currency,
time, lifecycle, cost-basis, freshness, and reconciliation policies are
approved. Missing or unsupported data must not be silently converted to zero.

## Validation

Implementation of this decision must prove:

- every canonical record preserves broker and account lineage
- Schwab-specific fields stop at the adapter boundary
- account-specific totals reconcile before consolidation
- unsupported brokers and asset classes fail explicitly
- the website cannot access another owner because no multi-user access is
  offered
- no journal, API, or frontend path can perform broker order mutations
- IBKR adoption passes the same normalized contract and reconciliation suite as
  Schwab

## Rollback or supersession

Changing target users, adding shared tenancy, expanding brokers or asset
classes, or altering the first production use case requires a new approved ADR
that identifies migration, compatibility, privacy, security, and operational
impact.
