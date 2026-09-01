# ADR-0021: Permit bounded Schwab lifecycle-evidence windows

- Status: Accepted
- Date: 2026-09-01
- Decision owners: OneJournal project owner
- Related roadmap items: P1-05, P1-07, PNL-03, PNL-03L
- Related decisions: ADR-0004, ADR-0005, ADR-0015, ADR-0019, ADR-0020
- Related contracts: `docs/external_provider_acquisition_contract.md`,
  `docs/schwab_transactions_json_adapter.md`,
  `docs/schwab_orders_transactions_reconciliation.md`
- Supersedes: None
- Superseded by: None

## Context

The transferred PNL-03I position snapshot contains 53 current identities but
does not supply authoritative currency, option multiplier, deliverable, or
complete fill/lifecycle history. PNL-03K compared those identities with the
five accepted PNL-01 trust-proof scopes and found zero exact overlap. It would
therefore be unsafe to create the private position mapping by defaulting USD,
multiplier 100, or standard deliverables.

ADR-0019 requires accepted cumulative fills and lifecycle events before a
current position can become canonical. The existing Schwab order and
transaction adapters already preserve broker-confirmed execution, accounting,
currency, multiplier, fee, and lifecycle-leg evidence, but the external bridge
explicitly forbids transaction and order acquisition. OneJournal needs an
additive source-evidence profile rather than an exception to that boundary.

The Schwab developer specification page required authenticated access when
reviewed on 2026-09-01. This offline decision therefore binds only the exact
request shapes already implemented in the repository. The first separately
approved provider call remains operational compatibility evidence and must stop
on any response, endpoint, permission, or scope mismatch.

On 2026-09-01 the project owner approved the lifecycle-acquisition contract and
offline implementation without authorizing a provider call or private write.

## Decision

### One paired, bounded history window

`onejournal.external-provider-acquisition.v1` additively supports
`schwab-read-only-single-account-lifecycle.v1`. One manifest represents exactly
one inclusive calendar window of at most 30 days and contains exactly two
successful, redirect-free GET responses in fixed order:

1. one account-orders response using the safe `{accountHash}` URL template,
   exact UTC `fromEnteredTime`/`toEnteredTime`, and `maxResults=3000`; and
2. one account-transactions response using the safe `{accountHash}` URL
   template, the same UTC `startDate`/`endDate`, and the complete approved
   transaction-type list.

Both requests bind the same SHA-256 digest of the owner-private account hash,
start date, end date, acquisition approval, owner epoch, source artifacts, and
provider-use acknowledgement. The manifest contains no raw account hash,
account number, credential, authorization header, normalized row, position,
or financial result.

Exactly two provider GETs, one order-endpoint call, and one transaction-endpoint
call are recorded. Account discovery, position calls, request bodies, retries,
redirects, database writes, execution operations, and implicit refresh remain
forbidden. A response with 3000 orders is rejected as potentially truncated;
the producer must use a smaller separately approved window.

### Owner-private account binding

`onejournal.schwab-account-private-binding.v1` contains only connection UID,
opaque OneJournal account ID, provider account hash, and provider account
number. It is an owner-only `0600` input, never Git or ordinary audit output.
It deliberately does not contain instrument mappings, so lifecycle evidence
can establish those mappings rather than depend on them circularly.

Credential-free conversion verifies the account-hash digest and every
non-empty response record's provider account number. An order record belongs
to the approved window when its entry, close, or recursive execution evidence
intersects the window. Transaction record membership continues to require an
observed provider time or trade date in the window. Empty paired responses
remain valid evidence of an empty window; they do not prove complete account
history or a flat position.

PNL-03P established that Schwab can replay an exact OCO parent from a later
window even when none of that parent tree's timestamps intersects the current
request. After account and timestamp validation of every raw order, conversion
preserves but excludes and counts such a top-level record before normalization.
Undated, malformed, or account-mismatched records still reject the complete
conversion. This is a source-boundary rule, not permission to infer or move a
fill between windows.

### OneJournal conversion and reconciliation

After canonical manifest, owner, acknowledgement, source, checksum, byte-count,
request, and private account gates pass, OneJournal parses the exact response
bytes through its existing order and transaction adapters in memory. Raw
provider account numbers are replaced in normalized results by the opaque
OneJournal account ID.

The approved record-level gate does not decide normalized row membership.
Normalized order and transaction fills are admitted only by exact execution
timestamp. Lifecycle events are admitted only by exact event timestamp, and
their legs only with the admitted event. The converter and cross-window audit
expose each out-of-window fill, event, and leg count, and the assembly digest
binds those counts plus the raw-order exclusion count. Provider bytes remain
immutable.

Transaction rows remain accounting authority for currency, fees, option
multiplier, and provider-observed lifecycle evidence. Order rows remain
independent execution evidence. A privacy-safe reconciliation compares exact
date, order, asset class, equity or option identity, side, quantity, price, and
option multiplier. Unmatched rows are reported as pending; no value is guessed,
dropped, persisted, or presented.

PNL-03M real evidence exposed one eligible equity trade without its own
currency leg while the same verified account/window contained 296 explicit
`CURRENCY_USD` legs on eligible valid trades and no conflicting eligible
currency. On 2026-09-01 the owner approved a source-bound correction: after the
account/window gate, conversion may resolve a missing per-record currency from
exactly one conflict-free explicit currency code across eligible valid trades
in that response. It records the code, evidence-item count, and resolved-record
count. Zero or conflicting eligible codes fail closed. This rule is not a
Schwab-wide USD default and does not make unmatched rows accepted P&L.

One paired window is source evidence only. Complete history requires contiguous
accepted windows, deduplication, lifecycle review, current-position coverage,
and later owner financial acceptance. This ADR does not equate a valid empty or
reconciled window with complete account history.

## Approval boundaries

This decision authorizes the additive local contract, pure conversion, private
account-binding format, validation-only operator, documentation, and synthetic
offline tests. It does not authorize a Schwab call, token access or refresh,
private binding or evidence creation, transfer, DuckDB write, journal import,
commit, push, sync, deployment, website enablement, or PNL-03 acceptance.

## Alternatives considered

### Infer USD and standard 100-share option contracts

Rejected. OCC identity does not prove currency, multiplier, or deliverable, and
adjusted contracts exist.

### Consume OneBot normalized fills or database rows

Rejected. ADR-0015 permits exact provider bytes and acquisition lineage only;
OneJournal owns normalization and reconciliation.

### Permit arbitrary history ranges in one manifest

Rejected. Large or truncated responses would be difficult to detect and retry
safely. Exact 30-day-or-smaller windows are deterministic, resumable, and can
be assembled under a later bounded batch approval.

### Acquire transactions without orders

Rejected. Transactions provide accounting truth, but independent order
execution evidence is required for the existing reconciliation contract.

## Consequences

- Current position identity facts can be sourced from provider evidence rather
  than owner defaults.
- The position profile and quote profile remain unchanged.
- A historical backfill may require many paired windows and explicit coverage
  tracking.
- Order-entry windows can contain fills completed later; complete reconciliation
  is assessed across the assembled accepted window set, not inferred from one
  pair.
- Live compatibility is accepted only for the separately approved bounded
  PNL-03M/O captures; broader history and provider date-range behavior remain
  unaccepted.

## Validation

Offline validation must prove canonical serialization, fixed paired request
order, account/window equality, maximum window length, exact queries and counts,
checksum and byte-count binding, raw-account privacy, deterministic conversion,
opaque-account substitution, exact option reconciliation, empty-window
behavior, potential order truncation rejection, malformed/out-of-window/account
mismatch rejection, no operator write/provider capability, and unchanged quote,
position, transaction, PNL, architecture-register, and full repository tests.

No real provider payload may enter Git or synthetic fixtures.

## Rollback or supersession

Before operational use, rollback is a focused reversion of this additive
profile, binding, operator, documentation, and tests. After a separately
approved capture, immutable private evidence remains governed by its approved
lifecycle and is not deleted by code rollback. A changed Schwab request shape,
pagination contract, provider-owned connector, or another broker requires a new
decision rather than silent widening.
