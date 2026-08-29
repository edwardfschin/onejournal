# ADR-0015: Permit a temporary single-owner external provider evidence bridge

- Status: Accepted
- Date: 2026-08-29
- Decision owners: OneJournal project owner
- Related roadmap items: PNL-02-T15 through PNL-02-T17
- Related contracts: ADR-0009, ADR-0011, ADR-0012, ADR-0013, ADR-0014,
  `docs/pnl02_t14_temporary_schwab_evidence_bridge.md`,
  `onejournal.market-data.quote-capture-artifact.v1`,
  `onejournal.private-raw-capture-manifest.v2`
- Supersedes: None
- Superseded by: ADR-0016 for decisions 15-16 on PNL-02 completion scope only

## Context

PNL-02-T14 proved a bounded Schwab evidence flow while OneBot/VPS remained the
sole token owner. The approved T14 runner was deliberately single-use: it was
not a service, scheduler, reusable command, or permanent dependency, and it
expired after its approved capture. The current OneJournal Schwab connector is
offline and credential-free, every provider remains disabled, and the durable
ingestion boundary accepts only a complete OneJournal private-capture bundle.

ADR-0012 and ADR-0014 require break-before-make cutover before OneJournal may
own or refresh the Schwab credential lifecycle. The project owner has now
stated that OneBot cannot yet be retired as token owner. Copying its token to
OneJournal, adding an independent OneJournal refresher, or allowing an
out-of-band program to share and refresh the same token would create the exact
split-ownership risk those ADRs prohibit.

Stopping all work is unnecessary. The broker response bytes can cross an
evidence boundary without making OneBot's derived values, runtime, or token
store authoritative OneJournal state. OneJournal can validate the acquisition
lineage, run its own provider adapter and session resolver, compute freshness,
and persist only through its existing provider-independent contracts.

The current T14 importer is not a recurring bridge contract. It accepts one
legacy OneBot quote bundle, requires one exact symbol and zero in-capture
refreshes, and performs no durable persistence. The current private-capture
manifest is also not an external acquisition contract because it binds a
OneJournal-normalized capture envelope produced inside the isolated connector.
A distinct external-acquisition intake boundary is therefore required.

## Decision

### Temporary operating mode

1. Until a separately approved T15 cutover, OneBot/VPS may remain the sole
   Schwab credential, token-refresh, and provider-session owner.
2. OneJournal remains credential-free. It must not receive, read, copy, store,
   refresh, revoke, or derive identity from an OneBot token, client secret,
   account identifier, credential path, or environment value.
3. Any interim acquisition producer must execute inside the OneBot owner
   boundary, under its approved operating identity and serialized credential
   controls. It cannot independently store or refresh credentials. A reusable
   producer requires a separately reviewed OneBot implementation or an
   equivalent owner-controlled runtime boundary; an unmanaged script sharing
   the token file is not accepted.
4. The initial bridge remains explicitly invoked and bounded. Background
   polling, a scheduler, public listener, website-triggered provider access,
   automatic token refresh, and silent retry are not approved by this ADR.

### Provider-neutral evidence handoff

5. OneJournal will define a versioned
   `onejournal.external-provider-acquisition.v1` intake contract. It contains
   only exact immutable provider response bytes and a secret-free,
   manifest-last acquisition record. It contains no normalized quote, session,
   freshness, valuation, journal, or P&L result supplied by OneBot.
6. The acquisition record must bind at minimum the provider, opaque connection
   UID, source-owner and owner-epoch identities, acquisition-run UID, exact
   approval and acknowledgement identities, provider-use profile, source
   artifact hashes, operation allowlist, exact request scope, request and
   receipt times, provider status and content type, response filenames, byte
   counts and SHA-256 digests, call and refresh counts, account/order/database
   counts, final completeness state, and the applicable raw-evidence lifecycle.
7. The first Schwab bridge profile permits only exact read-only quote and
   market-hours operations needed by the approved OneJournal adapters. It has
   no account, position, transaction, order, arbitrary URL/method/body,
   redirect, streaming, or execution operation.
8. A bridge capture must fail closed before provider access when its approval,
   acknowledgement, owner identity, source artifact, request scope, token-use
   mode, private output root, or evidence lifecycle is missing or mismatched.
   An expired token stops the capture. Any OneBot-owned refresh remains a
   separately authorized owner action and cannot be performed silently by the
   bridge producer.
9. Transfer into the OneJournal private vault remains checksum-preserving,
   non-overwriting, owner-only, and separately approved. Incomplete or altered
   bundles are retained as non-ingestible evidence or rejected; they cannot be
   repaired by editing bytes or a manifest.

### OneJournal authority and conversion

10. OneJournal treats the external bundle as source evidence only. Its own
    credential-free provider adapter, provider-native session resolver,
    complete-capture validator, entitlement and freshness rules, and durable
    ingestion boundary remain the only path to normalized OneJournal state.
11. A credential-free intake operator validates the external acquisition and
    converts it into the existing canonical private-capture bundle. The
    conversion is deterministic, append-only, checksum-linked to the external
    source, and separately approval-gated for private-evidence writes. It does
    not call a provider or write DuckDB.
12. Persistence remains a later explicit action through the existing guarded
    ingestion operator. Missing, stale, delayed, denied, crossed, future,
    session-unknown, identity-mismatched, or incomplete evidence remains
    unavailable and never becomes zero or a live mark.
13. OneBot-derived normalized values, cached market state, reports, logs, and
    database rows are not authoritative inputs to OneJournal. Only the exact
    provider bytes and verified acquisition lineage cross the bridge.

### Lifetime and PNL-02 status

14. This is a temporary transition mode, not a replacement for the isolated
    OneJournal connector plane. It ends when T15 cutover begins, the owner
    withdraws approval, the provider-use profile or acknowledgement ceases to
    be valid, exclusive OneBot ownership cannot be proven, or a material source
    contract changes.
15. Bridge implementation or bridge-mode end-to-end validation does not complete
    T15, T16, or T17 under the current roadmap. T15 remains the later explicit
    break-before-make ownership cutover, and PNL-02 remains `IN PROGRESS` until
    its accepted completion gates are changed or satisfied.
16. A later proposal may explicitly revise the PNL-02 completion scope if the
    owner chooses to accept bridge-mode operation as a bounded product state.
    This ADR does not make that policy change.

## Boundaries

This proposal does not authorize or implement a provider call, token access or
refresh, OneBot change, recurring producer, background schedule, private-
evidence write or transfer, database migration or write, connector activation,
public listener, website integration, commit, push, synchronization,
deployment, T15 cutover, or PNL-02 acceptance.

It does not make OneBot a permanent gateway, allow OneJournal to consume
OneBot-derived financial state, or weaken the final break-before-make rule. A
safe recurring bridge will require some owner-controlled acquisition capability
on the OneBot side; without that separately approved capability, only
individually approved bounded captures are possible.

## Alternatives considered

### Retire OneBot immediately

This would permit the accepted T15 cutover sequence, but the project owner has
stated that OneBot cannot yet be retired as token owner. Proceeding anyway
would create unacceptable operational risk. Deferred.

### Copy or share the current token with OneJournal

This appears fast but creates two credential users, competing refresh state,
stale-generation overwrite risk, and ambiguous rollback. Rejected.

### Make OneBot's normalized outputs authoritative OneJournal input

This avoids OneJournal adapter work but couples journal truth to another
project's derived state and blocks provider-independent evolution. Rejected.

### Pause all PNL-02-related work

This preserves safety but unnecessarily blocks credential-free intake,
normalization, persistence rehearsal, and failure validation. Rejected in favor
of a temporary evidence-only bridge.

## Consequences

### Positive

- OneBot can remain the sole token owner until retirement is operationally safe.
- OneJournal never receives a Schwab credential and does not depend on OneBot's
  normalized or journal state.
- The handoff remains provider-neutral and can later accept an isolated
  OneJournal, IBKR, Moomoo, or other acquisition producer without changing the
  quote, session, freshness, or persistence contracts.
- The final T15 cutover remains explicit and auditable.

### Negative and trade-offs

- This does not close PNL-02 under the current tracker.
- A sustainable bridge requires a separately approved owner-controlled OneBot
  acquisition capability; no safe OneJournal-only change can create it.
- The evidence transfer and conversion add latency, storage, and operational
  steps, so this is suitable for bounded local use rather than a public live
  website.
- Every recurring or scheduled mode still needs explicit operating, provider-
  use, retention, and failure-policy approval.

## Compatibility and migration

The proposed intake contract is additive. It does not change normalized quote,
session-authority, freshness, capture-envelope, private-capture-manifest, or
DuckDB schemas. The converter produces the existing canonical private-capture
contract rather than creating a second persistence path.

Historical T14 evidence remains immutable under its original source contract
and is not silently relabelled as an external-acquisition-v1 bundle. A focused
compatibility test may use synthetic equivalents of the observed T14 response
shapes, but no private evidence is copied into tests or Git.

## Security, privacy, licensing, and financial impact

The bridge is restricted to the accepted owner-operated local,
personal/noncommercial, non-redistributed scope. Provider-reported entitlement
remains authoritative and the current profile still forbids hosted storage and
public display.

The external bundle and its canonical conversion are private financial
evidence. They remain outside Git, ordinary logs, generated output, and the
website. No account or order endpoint is permitted. Acquisition success does
not establish freshness, session authority, valuation eligibility, or P&L.

## Validation

Before accepting an implementation, focused offline tests must prove:

- exact schema, canonical serialization, digest, byte-count, time, owner,
  approval, acknowledgement, and source-artifact binding;
- exact Schwab quote and market-hours allowlists with rejection of arbitrary
  hosts, methods, paths, queries, symbols, dates, redirects, and extra calls;
- rejection of token values, credential paths, authorization headers, account
  identifiers, normalized values, and response bodies in the manifest or logs;
- fail-closed incomplete, altered, expired, mismatched, duplicate, replay-
  conflict, entitlement, and session-authority cases;
- non-overwriting `0700`/`0600` private conversion with exact external-to-
  canonical lineage and deterministic replay;
- no provider, credential, database, order, listener, scheduler, or external
  write during offline tests; and
- unchanged existing quote, session, connector, private-capture, durable-
  ingestion, cutover, and full repository tests.

Operational bridge acceptance later requires authoritative evidence from the
actual OneBot owner boundary, checksum-preserving private transfer, exact
OneJournal conversion, and a separately approved persistence/read-back scope.
It cannot be inferred from unit tests or documentation.

## Rollback or supersession

While proposed, rollback is deletion or revision of this proposal and its
register reference; no runtime or private state exists. After implementation
but before operational use, rollback is a focused reversion while providers
remain disabled.

After a bridge capture, immutable evidence remains governed by its approved
lifecycle and is not deleted by code rollback. T15 supersedes the operating
need for this bridge only after OneBot access is retired and the OneJournal
owner is accepted without overlap.
