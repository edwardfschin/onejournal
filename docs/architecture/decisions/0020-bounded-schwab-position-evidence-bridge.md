# ADR-0020: Permit a bounded Schwab position-evidence bridge

- Status: Accepted
- Date: 2026-08-31
- Decision owners: OneJournal project owner
- Related roadmap items: P1-05, P1-07, PNL-03, WEB-W07
- Related decisions: ADR-0013, ADR-0015, ADR-0016, ADR-0019
- Related contracts: `docs/external_provider_acquisition_contract.md`,
  `docs/schwab_positions_json_contract.md`
- Supersedes: None
- Superseded by: None

## Context

ADR-0015 permits a temporary, manually invoked, single-owner external evidence
bridge while OneBot remains the sole Schwab credential owner. Its first profile
deliberately allows only quotes and market hours and forbids account and
position endpoints. ADR-0019 now requires an independently acquired, complete
broker-position snapshot before a OneJournal position can be reconciled or
valued. The implemented `schwab-position-json-v2` adapter is credential-free
and synthetically tested, but cannot establish real compatibility without one
bounded source response.

Using the quote profile for positions would violate its allowlist and obscure a
material privacy boundary. Making OneBot-derived positions authoritative would
also violate ADR-0015. A separate acquisition profile is therefore required.

On 2026-08-31 the project owner approved the PNL-03G contract and offline
implementation described below.

## Decision

### Separate position profile

`onejournal.external-provider-acquisition.v1` will support the additive profile
`schwab-read-only-single-account-positions.v1`. It permits exactly one
successful, redirect-free GET represented by the safe endpoint template
`https://api.schwabapi.com/trader/v1/accounts/{accountHash}` with the sole
ordered query parameter `fields=positions`.

The profile requires exactly one response, one recorded provider GET, and one
recorded position-endpoint call. Account-discovery, transaction, order,
database, request-body, arbitrary host/path/query, retry, redirect, streaming,
and execution activity remain zero and forbidden. An owner-side refresh is
still outside OneJournal and, if later needed, requires its own explicit
approval and manifest identity under ADR-0015.

### Private account binding

The acquisition manifest contains the literal safe endpoint template and a
SHA-256 digest of the opaque provider account hash. It never contains the raw
account hash, provider account number, credential, authorization header, token,
or response body. The exact raw response remains private evidence and may
contain provider account data.

Credential-free conversion later receives the raw account hash and expected
provider account number only from a separately approved owner-only input. It
verifies the hash against the manifest digest, constructs the exact in-memory
request context, and requires the response account number to match. Neither
private identifier enters ordinary audit output, Git, fixtures, or frontend
data. Checked-in tests use visibly synthetic values only.

### OneJournal conversion authority

After the existing external-acquisition owner, acknowledgement, source,
approval, canonical-byte, checksum, count, and lifecycle gates pass,
OneJournal converts the response only through `schwab-position-json-v2`.
Explicit provider-symbol to `onejournal.instrument-identity.v1` mappings must
cover every returned position exactly. Missing positions scope, mapping
mismatch, duplicate identity, account mismatch, altered bytes, unsupported
shape, or ambiguous quantity fails closed.

The pure result is a complete `BrokerPositionSnapshot` in memory. The bridge
does not supply canonical quantities, FIFO cost basis, a valuation mark,
market value, unrealized P&L, reconciliation success, or a portfolio total.
OneBot-derived values, reports, logs, and database rows remain non-authoritative.

## Approval boundaries

This decision authorizes the local credential-free profile, converter,
documentation, and synthetic offline tests. It does not authorize a Schwab
call, token or credential access, refresh, private-evidence creation or
transfer, private account-mapping creation, database migration or write,
production journal use, website/API enablement, commit, push, sync, deployment,
or financial acceptance. Those remain separate explicit gates.

## Alternatives considered

### Reuse the quote and market-hours profile

Rejected. That profile explicitly forbids account and position operations, and
its request/count rules cannot truthfully represent a position snapshot.

### Put the raw account hash in the acquisition manifest

Rejected. It would unnecessarily spread a private account identifier through
metadata and audit surfaces. A digest plus later owner-only binding preserves
exact lineage without exposing the identifier.

### Consume OneBot normalized positions

Rejected. Only exact provider bytes and verified acquisition lineage may cross
the temporary bridge. OneJournal owns normalization and reconciliation.

### Let the adapter infer mappings from provider symbols

Rejected. Provider symbols are lineage, not canonical instrument identity, and
option multiplier/currency semantics must remain explicit.

Deterministic parsing of a strict 21-character OCC symbol is permitted only to
verify every available option term against an already explicit private mapping;
it does not construct or replace that mapping. Schwab
`COLLECTIVE_INVESTMENT` is likewise accepted as canonical equity only for the
explicit provider subtype `EXCHANGE_TRADED_FUND`; other subtypes remain
unsupported and fail closed.

## Consequences

- One bounded real response can test the existing adapter without transferring
  credential ownership to OneJournal.
- The PNL-02 quote profile and historical manifests remain unchanged.
- A later operator needs a protected owner-only account/mapping input before
  real conversion can run.
- Position acquisition alone cannot close PNL-03; complete fill/lifecycle,
  quote/session, reconciliation, presentation, migration, and owner-acceptance
  gates remain.
- Strategic maturity does not change because this decision and implementation
  are not operational evidence or financial acceptance.

## Validation

Offline tests must prove:

1. canonical serialization and exact replay of both acquisition profiles;
2. exactly one safe position request and exact control counts;
3. rejection of raw target URLs, arbitrary endpoints, methods, queries,
   retries, redirects, extra requests, and forbidden activity counts;
4. omission and rejection of raw account identifiers and credential fields in
   manifest metadata;
5. manifest-to-private-account digest binding, response-account binding,
   checksum validation, and exact mapping coverage;
6. deterministic conversion to the existing complete broker snapshot; and
7. unchanged external quote, Schwab adapter, PNL-01/02/03, and full repository
   validation.

No real provider bytes may enter Git or synthetic fixtures.

## Rollback or supersession

Before operational use, rollback is a focused reversion of the additive
profile, converter, documentation, and tests; no private or database state
exists. After a separately approved capture, immutable evidence remains under
its accepted lifecycle even if this profile is later disabled or superseded.
Future OneJournal credential ownership or another broker requires its own
decision and must not silently widen this profile.
