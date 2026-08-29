# PNL-02-T14 temporary Schwab evidence-bridge design

## Status

Accepted by the project owner on 2026-08-28. This document defines a bounded
evidence operation only. Acceptance authorizes offline implementation and
testing of a temporary runner outside both repositories. It does not access a
token, call Schwab, write private evidence, modify OneBot, transfer evidence,
migrate a database,
activate a connector, or complete PNL-02-T14.

ADR-0009, ADR-0011, ADR-0012, ADR-0013, and ADR-0014 control this design. If
this document conflicts with an accepted ADR, the ADR controls.

## Observed runtime facts

Read-only inspection of the OneBot VPS runtime on 2026-08-28 established:

- `/opt/one` is an installed runtime directory and is not a Git checkout.
- The installed guarded exporter supports one exact Schwab quote GET only.
- That exporter requires Git provenance from `/opt/one`, so it cannot pass its
  own provenance check in the installed runtime.
- `SCHWAB_BATCH_MODE=1` makes the installed `AuthClient` return an unexpired
  access token or fail; it does not refresh. `force_refresh` also refuses in
  batch mode unless a separate refresh override is set.
- No installed bounded market-hours evidence exporter was found.

No token contents, credential values, provider responses, account data, or
private evidence were read during that inspection.

## Purpose and lifetime

The bridge exists only to collect the official response evidence required to
implement and validate the credential-free Schwab quote and provider-native
session adapters before the T15 single-owner cutover.

It is not a OneJournal provider client, permanent OneBot feature, background
job, service, scheduler, fallback provider, or production dependency. It must
not be committed to either repository or installed as a reusable command. Its
only executable artifact is a reviewed temporary runner whose exact bytes are
preserved with the private evidence bundle.

The bridge expires after its one approved capture attempt. A later attempt
requires a new capture ID and approval. Retained runner and response evidence
follow the accepted raw-evidence lifecycle; deletion is never automatic.

## Exact acquisition scope

One approved run may issue at most five HTTPS GET requests to the Schwab market-
data host:

1. One exact-symbol equity quote request.
2. One exact-symbol listed-option quote request.
3. One market-hours request for an explicitly approved normal trading date.
4. One market-hours request for an explicitly approved holiday date.
5. One market-hours request for an explicitly approved early-close date.

The quote operation is fixed to
`https://api.schwabapi.com/marketdata/v1/quotes` with only `symbols` and
`fields=quote,reference` query parameters. Each request contains exactly one
pre-approved provider symbol. The runner has no option-chain operation; the
listed-option symbol must be selected and approved before execution.

Authenticated read-only review of the Schwab Market Data Production 1.0.0 OAS3
specification on 2026-08-28 established the market-hours operation as
`GET https://api.schwabapi.com/marketdata/v1/markets`. Its required `markets`
query parameter is an array whose available values are `equity`, `option`,
`bond`, `future`, and `forex`; its optional `date` query parameter uses
`YYYY-MM-DD`, defaults to the current date, and accepts the current date through
one year in the future. The T14 scope requests only `equity` and `option`.

The specification does not describe `markets` as comma-separated text. Under
the OAS3 query-parameter defaults, query parameters use `style=form` and form
arrays default to `explode=true`, which emits a separate parameter for each
array value. The runner therefore serializes the exact ordered query as
`markets=equity`, `markets=option`, and `date=<approved-date>` rather than
guessing a comma-delimited scalar. The source contract v2 must bind exactly:

- `market_hours_url`:
  `https://api.schwabapi.com/marketdata/v1/markets`;
- `markets_query_key`: `markets`;
- `markets_query_values`: `["equity", "option"]`; and
- `date_query_key`: `date`.

The official 200 example returns top-level `equity` and `option` product maps.
Each product supplies `date`, `marketType`, `product`, `productName`, `isOpen`,
and `sessionHours`; each session interval supplies offset-aware `start` and
`end` timestamps. The runner validates that bounded scope and identity but does
not infer whether a candidate date is normal, a holiday, or an early close.

Authoritative references reviewed:

- [Schwab Market Data Production specification](https://developer.schwab.com/products/trader-api--individual/details/specifications/Market%20Data%20Production)
  (authenticated portal); and
- [OpenAPI Specification 3.0.4 Parameter Object](https://spec.openapis.org/oas/v3.0.4.html#parameter-object)
  for the query `style` and `explode` defaults.

Candidate evidence dates for the later source-contract approval are:

- normal trading date: 2026-08-31;
- holiday: 2026-09-07; and
- early close: 2026-11-27.

Those classifications remain candidate inputs until the official Schwab
schedule response itself confirms the applicable provider-native state. They
must not be inferred into OneJournal from weekday or general-calendar rules.

Candidate quote symbols for that same later approval are equity symbol `AAPL`
and listed-option symbol `AAPL  260918C00315000`. Recording candidates does not
authorize a provider request.

No account, account-number, preference, transaction, position, order, option-
chain, price-history, OAuth, refresh, revoke, streaming, or arbitrary provider
endpoint is allowed. Redirects, retries, pagination, and concurrency are
disabled. Any need for an additional request stops the run.

## Credential and process boundary

The runner executes only on the current OneBot VPS under the existing OneBot
operating identity because OneBot remains the temporary sole Schwab credential
owner. It imports only the installed token-store and authentication boundary
needed to obtain an existing access token.

Required environment invariants are:

- `SCHWAB_BATCH_MODE=1`;
- `SCHWAB_ALLOW_REFRESH` is absent;
- the access token is unexpired beyond the installed five-minute safety skew;
- the token file is a regular non-symlink file, owner-readable, and inaccessible
  to group and other users; and
- no token, refresh token, credential path, authorization header, client secret,
  or environment value is printed, hashed into public output, copied, or
  written into evidence.

An expired or invalid access token stops before the first request. The bridge
must not run preflight, login, refresh, or reauthorization. Any refresh need is
a separate approval boundary.

The runner has no import of OneJournal source, no OneJournal credential access,
and no journal-database path. OneJournal therefore remains credential-free and
does not become coupled to OneBot runtime modules.

## Runtime provenance

Because `/opt/one` is not Git, runtime provenance is established from installed
bytes rather than a false clean-checkout assertion. Before token access, the
runner records SHA-256 hashes for:

- its own exact reviewed bytes;
- `/opt/one/client/schwab_admin.py`;
- `/opt/one/client/schwab_conf.py`; and
- the Python executable and dependency-version inventory used for the run.

The runner fails before token access unless the approved authentication and
configuration paths are the exact installed OneBot modules that are imported,
the approved Python executable is the interpreter actually running the bridge,
and the approved operating identity matches the process's effective OS owner.

Before those runtime checks, the runner also requires the exact canonical
`onejournal.provider-usage-acknowledgement-artifact.v1` path and SHA-256. It
validates the owner-approval reference, deterministic acknowledgement identity,
generated 128-bit connection identity, complete active-profile declarations,
acceptance window, product/profile/notice/scope/lifecycle binding, canonical
bytes, and exact capture-plan identities. A placeholder acknowledgement ID is
not sufficient.

The implementation approval must bind the expected hashes. A mismatch stops
before token access. The manifest records observed hashes but never copies
configuration or authentication-module contents into the evidence bundle.

## Private evidence bundle

The approved output root must already exist outside `/opt/one`, be a non-
symlink directory with mode `0700`, and be dedicated to this capture. The
runner creates one non-overwriting `0700` capture directory containing only
`0600` regular non-symlink files:

```text
<capture-id>/
  bridge-runner.py
  source-contract.json
  provider-usage-acknowledgement.json
  equity-quote-response.json
  option-quote-response.json
  market-hours-normal-response.json
  market-hours-holiday-response.json
  market-hours-early-close-response.json
  capture-manifest-v3.json
```

Each response is written from exact received bytes with create-exclusive
semantics, a maximum response size, `fsync`, and a recorded SHA-256. The final
manifest is written last and is the sole completeness marker. If any request or
write fails, no completeness manifest is written. Partial evidence is retained
as incomplete private evidence until a separately approved review or deletion;
it is never imported or silently retried.

The versioned manifest binds:

- capture, approval, terms-acknowledgement, provider, and opaque connection IDs;
- the exact acknowledgement copy, checksum, acceptance time, and creation-
  approval reference;
- OneBot as token owner and the exact VPS operating identity;
- runner and installed-runtime hashes;
- exact method, host, path, ordered query, request timestamp, receive timestamp,
  status, content type, byte count, and response SHA-256 for every request;
- the explicit equity and option provider symbols and the three requested dates;
- request count `5`, refresh count `0`, account count `0`, order count `0`, and
  database-write count `0`;
- redirects disabled, retries disabled, response bodies suppressed from errors,
  and automatic deletion disabled; and
- one final success or incomplete status without treating partial capture as
  acceptance.

The bundle contains no account identifier, token, credential, authorization
header, complete environment, journal data, normalized quote, or P&L result.

## Validation before any provider call

The temporary runner implementation must first pass offline tests using injected
fake token and HTTP boundaries. Tests must prove:

- exact five-request allowlisting and deterministic order;
- rejection of arbitrary hosts, methods, paths, query keys, symbols, dates, and
  response scope;
- no refresh, account, order, database, retry, redirect, or logging capability;
- failure before HTTP when authorization, terms, runtime hashes, token mode,
  token permissions, output permissions, or exact scope is wrong;
- failure before token access or output creation when acknowledgement bytes,
  checksum, declarations, deterministic identity, connection, profile, scope,
  lifecycle, acceptance time, or permissions are invalid;
- strict JSON content type, finite JSON, maximum size, response-scope, and non-
  2xx handling;
- exact repeated-key market-array serialization plus rejection of an encoded
  comma-delimited scalar;
- exact equity/option top-level scope, requested date, required `EQ` and `EQO`
  products, product identity, boolean `isOpen`, session-phase arrays, increasing
  intervals, and explicit timestamp offsets;
- create-exclusive `0700`/`0600` output, manifest-last completion, checksum
  verification, and no overwrite; and
- secret scanning of the runner, manifest, errors, and synthetic bundle.

The reviewed implementation, exact expected hashes, explicit symbols, exact
market-hours operation, dates, capture ID, approval ID, terms acknowledgement,
private output root, and expected request count must be presented before a
separate provider-call approval.

## Transfer and OneJournal use

Capture success does not authorize transfer. A later approval may copy only the
complete bundle into `/Users/edward/Projects/Private/OneJournal` using checksum-
verified transport. The destination root and bundle remain `0700`; files remain
`0600`; no symlink is accepted. Source and destination hashes must match.

OneJournal then consumes the evidence only through new credential-free adapters
and import validation. The Schwab schedule adapter must preserve actual provider
scope and response semantics behind
`onejournal.provider-market-session-authority.v2`; it must not infer unsupported
sessions, MICs, timezones, holidays, or early-close boundaries. The official
listed-option response must be reconciled against the existing provider-neutral
quote contract without broadening the bridge.

No response becomes authoritative merely because it was captured. T14 remains
blocked until the official evidence maps completely, the broader matrix passes,
and all limitations are recorded.

## Approval boundaries

The following remain separate explicit approvals:

1. Accept this temporary bridge design. **Approved 2026-08-28.**
2. Implement and offline-test the temporary runner outside both repositories.
   **Completed 2026-08-28; no provider or credential action.**
3. Review the authenticated Schwab specification and freeze the exact market-
   hours endpoint/query contract, symbols, dates, hashes, and capture metadata.
   **Completed and owner-approved for capture `-04` on 2026-08-28.**
4. Execute the bounded provider calls and private evidence write on the VPS.
   **Completed for same-date capture `PNL-02-T14-SCHWAB-20260829-06` on
   2026-08-29. `-05` stopped before any GET because the existing access token
   was expired. The first separately approved refresh command for `-06` made
   one failed OAuth request because the authoritative Schwab environment was not
   loaded; no capture ran. After the root invocation error was identified, the
   owner approved one corrected OneBot-owned refresh with
   `config/schwab_env.sh` loaded. It succeeded once, after which unchanged v5
   completed five GETs with zero in-capture refreshes and zero
   account/order/database actions.**
5. Transfer the complete evidence bundle into the OneJournal private vault.
   **Completed for `-06` on 2026-08-29 with nine-file checksum parity and
   `0700`/`0600` permissions. `-05` remains preserved and incomplete.**
6. Implement and test the credential-free Schwab schedule/option adapters.
   **The official option shape passes `schwab-quote-json-v2`. The isolated
   `schwab-market-hours-json-v1` parser accepts the exact normal, closed, and
   shortened-session bytes without inventing missing calendar semantics. The
   owner-approved offline resolver preserves unnamed closure as
   `closed_unspecified`, offset-validates the explicit Schwab product/timezone
   mapping, and binds combined evidence through the manifest. Capture `-06`
   supplies same-date quote and normal-schedule evidence. Its option produces
   actual combined v2 authority. Its equity `securityStatus=Closed` is preserved
   as a frozen quote with unknown session and becomes `market_closed_last` only
   through exact v2 authority; an open effective session remains ineligible.**
7. Commit and push focused OneJournal code or documentation.
8. Perform T15 cutover, deployment, migration, real ingestion, or end-to-end
   acceptance.

Approval of one item does not authorize any later item.

## Offline implementation evidence

Following owner acceptance, the temporary runner and its tests were implemented
outside both repositories under `/private/tmp/onejournal-pnl02-t14-bridge` on
2026-08-28. Authenticated specification review then exposed a scalar-versus-
array request gap, an under-validated market-hours response boundary, and an
opaque-placeholder acknowledgement gap. The corrected v3 runner now validates
the full canonical private acknowledgement before token access and preserves an
exact checksum-bound copy in the evidence bundle. Its SHA-256 is
`fc3ba1b4b313ec642ff7f0a2d5f7124e74eed12f086a264031f6bf3e707f2e06`;
the corrected test SHA-256 is
`e84258b74bc987987ff2da4dacf55631f4beddcb45720b826c8428595fd12537`.
These supersede the earlier reviewed temporary hashes before any transfer or
execution occurred.

The final v5 runner passed twelve offline tests using injected fake token and
transport boundaries. Its SHA-256 is
`4c092ee5cd0c57dfa71d50b8d54310139a7e45bf9b8a969c40337a6a4fc0f6b0`;
the final test SHA-256 is
`54885858f7f468f5e4ee57de6dca16d57442ad44eebe8bfdb4592ade377d136b`.
The tests cover the exact five-request order, repeated-key market serialization,
full acknowledgement/checksum/declaration/connection, source-contract, and
runtime-hash gates before token access, exact schedule scope/date/product/session
validation, manifest-last private output, secret exclusion, no overwrite,
noncanonical scope rejection, and incomplete-bundle behavior. The temporary
directory and files remain owner-only. Import-based syntax validation also
passed.

Read-only VPS inspection recorded the current installed runtime inputs for a
later approval review:

- `schwab_admin.py` SHA-256:
  `abcb2ebff40de3191511be6fd2a00119ea47b902e45d1febc814dd29326b06cb`;
- `schwab_conf.py` SHA-256:
  `f861ae3f1d9a72425e3be53f1ced5ade5c0617daae58417fbd3672c3b1094e6d`;
- `/usr/bin/python3.12` SHA-256:
  `1643dacd9feaedc58f3cc581e4d22577dfe25c09b10282936186ccf0f2e61118`;
- Python version `3.12.3`; and
- Requests version `2.31.0` from
  `/usr/lib/python3/dist-packages/requests`.

The owner attestation, append-only acknowledgement, source contract, private VPS
root, bounded provider capture, and private-vault transfer now exist for `-06`.
The complete local bundle contains nine files and preserves manifest SHA-256
`a518edd8869b4e3cc41fec9355f30fb109d5c241a1fb567003adb2e7dae74317`.
Both official quotes report real-time entitlement. The option reports
`securityStatus=Normal`; the after-hours equity reports
`securityStatus=Closed`. The market-hours parser accepts the three exact
responses and preserves their offsets and phase boundaries.

The 2026-08-29 source-faithful correction is approved and implemented offline:
unnamed closure remains `closed_unspecified`; exact Schwab product scopes map
explicitly to `America/New_York` with per-timestamp offset checks; and
multi-response authority lineage uses the checksum manifest. Capture `-06`
closes the date gap with a normal 2026-08-28 schedule matching both quote dates.
Read-only review produces actual combined v2 authority and
`market_closed_last` for the option. `schwab-quote-json-v2` maps the observed
equity `Closed` state to `data_mode=frozen`, keeps session unknown, and permits
the same result only when exact v2 authority reports the evaluation session
closed. Focused regression proves it remains ineligible while the effective
market is open. Any new capture, changed runner, or changed runtime hash still
requires separate review and approval.

## Rollback

Before provider use, rollback is removal or revision of the proposed design and
temporary implementation. The v5 capture itself remains read-only and cannot
refresh. The separately approved corrected pre-capture refresh rotated only the
existing OneBot-owned token lifecycle and cannot be reversed by restoring stale
token bytes. Immutable evidence is retained until separately approved deletion.
No rollback may copy or reactivate a token, create a second credential owner, or
convert the bridge into a recurring path.
