# External provider acquisition contract

## Status and scope

`onejournal.external-provider-acquisition.v1` implements the credential-free
intake and in-memory conversion boundary approved by ADR-0015 and ADR-0016. The
first profile is `schwab-read-only-quotes-and-market-hours.v1` for explicitly
bounded evidence produced inside the sole OneBot credential-owner boundary.
ADR-0020 additively defines
`schwab-read-only-single-account-positions.v1` for one separately approved,
complete account-position response under the same sole-owner boundary.
ADR-0021 additively defines
`schwab-read-only-single-account-lifecycle.v1` for one paired, bounded order
and transaction history window under that same boundary.

This implementation does not call Schwab, access or refresh credentials,
discover accounts, write private evidence or
DuckDB, schedule work, listen for requests, synchronize, or deploy. The
position profile only validates and converts already supplied position bytes;
the lifecycle profile only validates and converts already supplied order and
transaction bytes. Actual acquisition and checksum-preserving transfer remain
separately approved actions.

## Authoritative inputs and outputs

The intake accepts canonical `acquisition-manifest.json` bytes, the exact
provider response bytes named by that manifest, the exact current provider-use
acknowledgement artifact bytes, and explicit expected run, approval,
source-owner, and owner-epoch identities.

The external producer supplies no normalized quote, session, freshness,
valuation, journal, or P&L value. OneJournal verifies the acquisition and then
uses only its own `schwab-quote-json-v2`, `schwab-market-hours-json-v1`, and
`schwab-market-hours-resolver-v1` boundaries.

Quote conversion returns, in memory, the exact response bytes, an existing
`onejournal.market-data.quote-capture.v1` envelope, an existing
`onejournal.private-raw-capture-manifest.v2`, and canonical capture-artifact
bytes. It does not materialize them. The capture run UID is deterministically
derived from the external manifest digest, request UID, and response digest,
so identical replay is stable and changed lineage cannot reuse the identity.

Market-hours conversion returns parsed schedule evidence whose combined
lineage binds the external manifest digest and every response digest. An
explicit normal-reference date and validity limit are required; neither is
inferred from a weekday, clock, or another provider.

## Manifest contract

The canonical, manifest-last record binds schema/profile, provider, connection,
source owner and epoch, operating identity, source artifact hashes, acquisition
run and approval, acknowledgement artifact, active provider-use and raw-
evidence lifecycle, exact request/response scope, request and receipt times,
HTTP status and content type, filenames, byte counts and SHA-256 digests,
bounded activity counts, and final completeness.

JSON is UTF-8, finite, newline-terminated, key-sorted, and compact. Unknown,
missing, duplicate, or noncanonical fields fail closed. The manifest contains
no provider response body, authorization header, token, secret, credential
path, raw account identifier, normalized value, or derived financial result.

## Schwab allowlist

The v1 Schwab profile requires both operation types and permits two through
five total responses:

- one or two exact single-symbol `GET` requests to
  `https://api.schwabapi.com/marketdata/v1/quotes`, with ordered `symbols` and
  `fields=quote,reference` query parameters; and
- one through three exact `GET` requests to
  `https://api.schwabapi.com/marketdata/v1/markets`, with ordered repeated
  `markets=equity`, `markets=option`, and `date=YYYY-MM-DD` parameters.

Every request is one attempt, status 200, JSON, body-free, and redirect-free.
Arbitrary hosts, paths, methods, queries, comma-collapsed market arrays,
retries, additional responses, and repeated response digests are rejected.
Account, position, transaction, order, request-body, and database counts must
be zero. An owner-side OAuth refresh count may be zero or one; one requires its
own explicit approval ID and is evidence only, never a OneJournal action.

The separate `schwab-read-only-single-account-positions.v1` profile permits
exactly one response from one redirect-free GET represented by
`https://api.schwabapi.com/trader/v1/accounts/{accountHash}` with exactly
`fields=positions`. Its controls require one provider GET, one response, one
position-endpoint call, and zero account-discovery, transaction, order,
request-body, or database activity. The safe manifest stores only the endpoint
template and SHA-256 digest of the opaque account hash. The raw account hash
and provider account number remain owner-only conversion inputs and must never
enter Git or ordinary audit output.

Position conversion verifies that private account hash against the manifest,
binds the exact response account number and checksum, and invokes only
`schwab-position-json-v2` with an explicit complete provider-symbol mapping.
It returns an in-memory `BrokerPositionSnapshot`; it does not create canonical
lots, reconcile quantities, select a mark, calculate P&L, persist data, or
establish PNL-03 acceptance.

The separate `schwab-read-only-single-account-lifecycle.v1` profile permits
exactly one ordered pair of successful redirect-free account-scoped GETs for
one inclusive window of at most 30 days: orders with exact UTC
`fromEnteredTime`/`toEnteredTime` and `maxResults=3000`, followed by transactions
with the same exact UTC `startDate`/`endDate` and the approved complete type
list. Both requests bind the same digest of the owner-private account hash and
the same start/end dates. Controls require exactly two provider GETs, one order
call, and one transaction call; account discovery, position, body, database,
retry, and redirect counts remain zero.

An order response containing 3000 records is rejected as potentially
truncated. A smaller separately approved window is required. Empty paired JSON
arrays are valid source evidence for that exact window but cannot prove a flat
account or complete history.

Lifecycle conversion receives an owner-only
`onejournal.schwab-account-private-binding.v1` input containing connection UID,
opaque OneJournal account ID, provider account hash, and provider account
number. It verifies the account digest, response account numbers, and record
dates, then invokes the existing order and transaction adapters in memory. A
provider-returned order record belongs to the approved window only when its
entry time, close time, or execution evidence anywhere in its recursive child
order tree intersects that window. This keeps a pre-window order whose actual
execution or closure occurred inside the requested period without treating
the order's entry date as the fill date. Schwab may replay an otherwise valid
OCO parent outside a requested window. Conversion validates the account and
timestamp syntax of every raw order record, preserves the response unchanged,
and excludes and counts a non-intersecting top-level record before order
normalization. A missing timestamp, malformed timestamp, or account mismatch
still rejects the complete conversion.

Every normalized order and transaction fill is then admitted only when its
exact execution timestamp is inside the window. Every lifecycle event is
admitted only when its exact event timestamp is inside the window, and its
legs are admitted only with that event. Out-of-window fill, event, and leg
counts and the raw-order exclusion count remain explicit in the privacy-safe
validation audit; raw provider bytes are never altered.

Normalized rows contain only the opaque OneJournal account ID. Transaction rows
are accounting authority; order rows are independent execution evidence.
Privacy-safe exact-identity reconciliation reports matched and unmatched rows
without persisting or accepting financial state.

PNL-03N adds the pure
`onejournal.current-position-lifecycle-coverage.v1` boundary. It assembles
multiple already verified lifecycle windows only when their provider,
connection, opaque account, and contiguous non-overlapping dates agree. Exact
stable-identity replay deduplicates; conflicting replay fails closed. Order and
transaction rows reconcile across the assembled set. Source-window exclusions
and rows later than the broker snapshot instant are independently counted and
bound into the deterministic assembly digest.

For each private current-position target, transaction evidence supplies the
canonical currency and instrument terms. Exact signed fill net against the
complete broker quantity can prove a bounded fill-flat start; missing or
mismatched history requires earlier contiguous evidence. Missing order IDs,
unmatched execution/accounting rows, and applicable lifecycle evidence remain
review-required. The result is unmaterialized coverage evidence, not a private
binding, FIFO position, valuation, or PNL-03 acceptance. The detailed contract
is `docs/current_position_lifecycle_coverage_contract.md`.

After the account/window gate, lifecycle conversion derives a currency
consensus only from explicit CURRENCY legs on eligible valid trade records with
supported security legs. It may use that consensus for an otherwise eligible
same-window trade whose individual currency leg is absent only when exactly
one code exists across the eligible scope. The validation audit reports the
code, explicit evidence-item count, and resolved-record count. Zero or
conflicting eligible currency codes remain fail-closed. This is provider-byte
lineage, not a Schwab-wide or account-configuration USD default. Any unmatched
transaction remains pending and unavailable for accepted P&L.

## Credential-free intake operator

`scripts/journal/materialize_external_provider_acquisition.py` is the guarded
filesystem operator for a checksum-preserving transferred bundle. It requires
an existing absolute `0700` acquisition root containing exactly the canonical
manifest and its named `0600` provider responses, plus the exact current `0600`
provider-use acknowledgement. The operator requires explicit expected run,
approval, source-owner, owner-epoch, quote-mapping, schedule-scope, evaluation,
normal-reference-date, and schedule-validity inputs.

Validation-only is the default. It verifies and converts the acquisition,
builds exact same-provider schedule authority, and reports the freshness result
without writing evidence. `--require-valuation-allowed` stops before any write
unless every quote is eligible under the current policy. Append-only private
materialization additionally requires `--materialize-private` and an already
provisioned absolute `0700` OneJournal vault root. Existing capture identities
are never overwritten.

That filesystem operator remains quote/market-hours-specific. PNL-03H adds
`scripts/journal/validate_external_schwab_position_acquisition.py`, a separate
position-only validation operator. It reads, but never creates or materializes,
one pre-existing position bundle, acknowledgement, and `0600` private binding;
its output contains only secret-free digests, count, complete-account flag, and
validation status. The operator cannot capture, transfer, retain, or persist
evidence. Its exact input/output contract is documented in
`docs/schwab_position_evidence_intake_operator.md`.

PNL-03L adds
`scripts/journal/validate_external_schwab_lifecycle_acquisition.py`, a separate
lifecycle-window validation operator. It requires exact `0700`/`0600` inputs,
the active acknowledgement, and the owner-private account binding. It emits
only secret-safe digests, dates, counts, reconciliation status, and validation
status. Its exact contract is documented in
`docs/schwab_lifecycle_evidence_intake_operator.md`.

PNL-03N does not add another filesystem operator. The cross-window assembler
accepts only existing verified in-memory conversions and private current-
position targets. Its privacy-safe audit contains counts and digests only.

The operator has no provider, credential, refresh, account, order, migration,
database, scheduling, listener, synchronization, or deployment capability. Its
secret-free stdout audit supplies the exact capture identities needed by the
separate durable-ingestion operator.

## Conversion and later approval gates

The pure boundary is implemented in
`src/onejournal/provider_connectors/external_acquisition.py`. The guarded
operator may pass a verified conversion result to the existing append-only
private capture store only under its explicit materialization flag. A real
private write remains separately approved and preserves `0700`/`0600`,
no-overwrite, exact response bytes, capture artifact, and manifest-last rules.

Durable ingestion remains a separate action through the existing guarded
operator. It requires an approved prepared local DuckDB, explicit persistence,
exact read-back, and acceptance evidence. T16 exercised that separate action in
an isolated local DuckDB and the project owner accepted the resulting bounded
bridge scope on 2026-08-31. Conversion success alone still does not establish
freshness, session authority, valuation eligibility, operational acceptance,
or PNL-02 completion, and the T16 result does not authorize a production
journal migration or PNL-03 valuation mark.

## Validation and rollback

Focused offline tests cover canonical replay, exact response checksums,
provider-use and owner-epoch binding, quote conversion, schedule lineage,
arbitrary endpoint/method/query rejection, forbidden activity counts,
incomplete manifests, tampering, mapping mismatches, validation-only behavior,
explicit append-only materialization, permission enforcement, overwrite
rejection, and the absence of network, credential, database, and subprocess
capability.

Before materialization, rollback is a focused code reversion; no private or
database state exists. After any separately approved materialization, immutable
evidence remains under its accepted lifecycle and is never deleted by rollback.
