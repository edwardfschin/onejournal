# Mac data-refresh capture preparation

## Status: prepared, not authorized or executed

Prepared on 2026-10-09 for the existing private single-owner `Primary` scope.
This is a request-scope plan, not an executable acquisition command or a new
provider policy. No provider call, credential read, private evidence creation,
transfer, database write or service restart was performed during preparation.

The accepted report covers 2026-03-06 through 2026-09-04. The reviewed local v2
assemblies have a 2026-09-04 snapshot; a newer assembled update was not found.
The guarded subsequent-report-release operator is now available, but it cannot
create fresh source evidence. Browser reload is not broker-data refresh.

## Smallest useful capture

Keep OneBot as the sole Schwab credential owner under ADR-0016. OneJournal
receives exact provider bytes and acquisition lineage, not OneBot calculations,
caches or database rows. Do not copy a token to the Mac website or add a second
credential owner.

The first capture scope is one complete position snapshot and the missing
paired order/transaction windows for the same existing private account binding.
Use the already known account hash privately; account discovery is outside this
scope. `Primary` is the display alias, not a provider identifier.

The existing offline planner verified these candidate windows:

| Candidate history end | First window | Second window | History GETs | Including one position GET |
| --- | --- | --- | ---: | ---: |
| 2026-10-08 | 2026-09-05–2026-10-04 (30 days) | 2026-10-05–2026-10-08 (4 days) | 4 | 5 |
| 2026-10-09 | 2026-09-05–2026-10-04 (30 days) | 2026-10-05–2026-10-09 (5 days) | 4 | 5 |

These are alternatives, not permission to fetch both. The end date and actual
snapshot market date must be fixed in the reviewed capture specification before
broker access. Do not infer a completed US session from the Singapore calendar,
backdate a current snapshot, or silently roll this plan forward. An intraday
capture is not proof of a complete day's activity. Record request/receipt times
and apply the existing snapshot cutoff and freshness rules. The lifecycle
coverage check requires the snapshot cutoff's UTC date inside the assembled
range, while Phase 1 assembly requires the lifecycle end no later than the
snapshot's market date. Verify both before selecting the capture time; do not
solve a UTC/New York date mismatch by changing timestamps or weakening a guard.

Each lifecycle window uses
`schwab-read-only-single-account-lifecycle.v1`: exactly one orders GET followed
by one transactions GET. The implemented queries use UTC start
`T00:00:00.000Z` and end `T23:59:59.999Z`, `maxResults=3000` for orders, and the
complete transaction-type list in `external_acquisition.py`. Do not add a status
filter or restrict transactions to trades; assignment, exercise, expiration and
cash evidence must not be discarded. Exactly 3000 returned orders is a stop,
not permission to retry with a new window.

The position request uses
`schwab-read-only-single-account-positions.v1`: exactly one GET to the approved
single-account template with `fields=positions`. Neither profile permits
account discovery, retries, redirects, request bodies, database writes or order
submission/modification. OAuth refresh is zero for this proposed scope; an
expired token stops the capture rather than invoking a refresh.

## Execution dependency still unresolved

Read-only inspection of the checked-in OneBot entry point
`scripts/marketdata/capture_schwab_quote_evidence.py` and its implementation
`client/schwab_quote_evidence.py` found a one-symbol exporter producing the
legacy `onebot.schwab.quote-evidence-capture.v1` bundle. It is not a position,
lifecycle or bounded-batch acquisition command. Do not substitute it or
relabel its output as `onejournal.external-provider-acquisition.v1`.

ADR-0015 and the historical capture records describe separately reviewed,
bounded owner-side runners. Preparation has not verified a current installed
runner or its operating identity, hashes, owner epoch, private output root or
active acknowledgement. Old single-use approvals cannot be reused. Locate and
review the retained owner-controlled producer before supplying a runnable
command; do not claim that historical successful captures establish current
execution readiness. Changes to OneBot or deployment are not authorized by
this OneJournal preparation.

## Handoff and checks that matter

One coherent acquisition approval can cover the exact bounded GETs, creation
of new owner-only evidence bundles, checksum-preserving transfer to a named
new private Mac destination and credential-free validation, once the producer,
dates, identities and destinations are explicit. It does not include a live
database write, financial acceptance or runtime activation.

Retain immutable responses in new non-overwriting `0700` bundle directories
with `0600` files and a canonical manifest written last. Bind source hashes,
run/approval identities, acknowledgement, owner epoch, exact request scope,
counts, response sizes and checksums. Suppress raw account identifiers,
payloads and credentials from ordinary output. Transfer only the required
evidence and lineage, never credentials. Validate with the existing position
and lifecycle intake operators; changed instrument scope needs explicit
source-backed mappings, not inferred contract terms.

Combine the verified extension with the retained history through September 4
in memory. The assembled windows must be contiguous and non-overlapping.
Do not append overlapping recaptures or hide changed stable identities: a
conflict, missing order evidence, truncated response or unmatched lifecycle
scope stops financial publication and requires a bounded investigation.
Successful window validation alone does not prove complete account history.

Only then fix the exact required quote scope from verified current positions.
The batch profile permits one sorted unique batch of at most 50 symbols and
one through three explicit same-provider schedule dates. The old 48-symbol
batch is not automatically today's scope. Required mappings, session dates,
normal-reference date and validity limit must be explicit; missing marks stay
unavailable. Do not promise a total quote-call budget before that scope exists.

After complete evidence validation, use the existing v2 assembly and
append-only history-revision path on a disposable journal copy, reconcile new
financial results, and rehearse the exact subsequent report release. Stop
before live persistence or switching the protected site's authorizations.
Old evidence, notes, reviews and accepted releases remain rollback history.

## Impact and rollback

Authoritative inputs are immutable provider evidence under the approved bridge
contracts. This preparation changes only operator documentation; downstream
intake, assembly, history revision, financial calculation and report-release
contracts are unchanged. No persisted state or user-facing runtime is changed.
Validation is the offline date-window calculation, source/profile comparison
and documentation diff check; no broad test run or provider probe is needed.
Rollback is a focused documentation revert, not deletion of private evidence.
