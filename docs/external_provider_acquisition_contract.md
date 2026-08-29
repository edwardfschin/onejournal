# External provider acquisition contract

## Status and scope

`onejournal.external-provider-acquisition.v1` implements the credential-free
intake and in-memory conversion boundary approved by ADR-0015 and ADR-0016. The
first profile is `schwab-read-only-quotes-and-market-hours.v1` for explicitly
bounded evidence produced inside the sole OneBot credential-owner boundary.

This implementation does not call Schwab, access or refresh credentials, read
accounts, positions, transactions, or orders, write private evidence or
DuckDB, schedule work, listen for requests, synchronize, or deploy. It accepts
bytes supplied by an operator only after the separately approved acquisition
and checksum-preserving transfer steps.

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
path, account identifier, normalized value, or derived financial result.

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

## Conversion and later approval gates

The pure boundary is implemented in
`src/onejournal/provider_connectors/external_acquisition.py`. A later private
materialization action may pass a returned conversion result to the existing
append-only private capture store. That write remains separately approved and
must preserve `0700`/`0600`, no-overwrite, exact response bytes, capture
artifact, and manifest-last rules.

Durable ingestion remains a later action through the existing guarded
operator. It requires an approved prepared local DuckDB, explicit persistence,
exact read-back, and acceptance evidence. Conversion success alone does not
establish freshness, session authority, valuation eligibility, operational
acceptance, or PNL-02 completion.

## Validation and rollback

Focused offline tests cover canonical replay, exact response checksums,
provider-use and owner-epoch binding, quote conversion, schedule lineage,
arbitrary endpoint/method/query rejection, forbidden activity counts,
incomplete manifests, tampering, mapping mismatches, and the absence of network,
credential, database, subprocess, or file-write capability.

Before materialization, rollback is a focused code reversion; no private or
database state exists. After any separately approved materialization, immutable
evidence remains under its accepted lifecycle and is never deleted by rollback.
