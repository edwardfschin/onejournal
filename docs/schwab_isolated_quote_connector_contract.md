# Offline Schwab quote connector contract

PNL-02-T12 introduces `onejournal.schwab.quote-connector.v1`, an offline-only acquisition boundary. It sits after T11's exact provider-use acknowledgement validation and before the existing credential-free Schwab JSON adapter and provider-neutral quote-capture envelope.

The canonical private persistence and loading boundary for that prerequisite is `onejournal.provider-usage-acknowledgement-artifact.v1`, documented in `docs/provider_usage_acknowledgement_artifact.md`. It uses an append-only 0700/0600 local store, a generated 128-bit opaque connection identity, canonical bytes, and checksum validation. The connector still receives the validated acknowledgement object; it does not read the store itself. No real acknowledgement or connection identity was created by adding this boundary.

The connector accepts only an explicit batch of mapped stock or option requests, a safe opaque connection UID, an approval reference, an as-of date, and the connection-scoped provider-use acknowledgement. It exposes no caller-supplied URL, HTTP method, headers, provider body, account identity, portfolio, transaction, or order operation. Its only operation is `quote_capture` with one bounded attempt.

For offline tests, all side-effecting concerns are injected ports: a non-persistent exclusive owner-lease registry, a non-persistent opaque credential-generation capability, and a synthetic fixed-operation quote transport.

The shipped module provides no network client, token value, credential backend, database writer, scheduler, CLI, service listener, or production activation path. Its local private store atomically creates one 0700 capture directory containing three 0600 files: exact response bytes, a checksum-bound provider-neutral envelope artifact for restart-safe recovery, and a secret-free v2 manifest binding both digests. It has no overwrite or delete capability. The returned result contains the immutable bytes, SHA-256, private-vault locator, existing `QuoteCaptureEnvelope`, and secret-free audit. It remains deliberately labelled `captured_private_uningested`; T13 independently reloads the immutable bundle before any approved journal persistence.

The connector rejects before returning a capture if acknowledgement/profile binding, exclusive owner lease, credential-generation continuity, fixed transport result, response content type/size/timing, JSON shape, exact requested symbol scope, adapter normalization, or existing complete-capture validation fails. It does not treat an acknowledgement as provider entitlement, and it preserves the adapter's provider reported entitlement and session facts.

No live provider activation is implied. `config/marketdata.yaml` keeps Schwab disabled, OneBot remains the temporary Schwab token owner, and the T15 break-before-make cutover remains required before any OneJournal credential use.
