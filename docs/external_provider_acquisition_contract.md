# External provider acquisition contract

## Status and scope

`onejournal.external-provider-acquisition.v1` implements the credential-free
intake and in-memory conversion boundary approved by ADR-0015 and ADR-0016. The
first profile is `schwab-read-only-quotes-and-market-hours.v1` for explicitly
bounded evidence produced inside the sole OneBot credential-owner boundary.
ADR-0020 additively defines
`schwab-read-only-single-account-positions.v1` for one separately approved,
complete account-position response under the same sole-owner boundary.

This implementation does not call Schwab, access or refresh credentials,
discover accounts, read transactions or orders, write private evidence or
DuckDB, schedule work, listen for requests, synchronize, or deploy. The
position profile only validates and converts already supplied position bytes;
the actual acquisition and checksum-preserving transfer remain separately
approved actions.

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
`schwab-position-json-v1` with an explicit complete provider-symbol mapping.
It returns an in-memory `BrokerPositionSnapshot`; it does not create canonical
lots, reconcile quantities, select a mark, calculate P&L, persist data, or
establish PNL-03 acceptance.

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

That filesystem operator remains quote/market-hours-specific and must reject
the position profile. PNL-03G implements only the pure in-memory position
verification/conversion boundary. A later owner-only position operator must be
separately reviewed and approved before it may read a private account-binding
or mapping input, transfer evidence, or materialize a capture.

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
