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

### Retained runner review: 2026-10-09

Read-only inspection located the archived position runner
`pnl03v_schwab_position_capture_v2.py` and the later history runner
`onejournal_p1_06_history_capture_v1.py`. Both are mode `0600` and match the
producer SHA-256 in their respective retained acquisition manifests. Their
code was inspected without executing it, importing the provider client or
reading credentials. Private constant values were suppressed from review
output; no source bundle was changed.

These are fixed, single-use owner-side programs, not recurring refresh tools.
They bind old run/approval identities, source/runtime hashes, owner identities,
acknowledgement and private output locations; the history runner also binds an
old date window. Both require the active OneBot VPS role, no refresh override,
empty non-overwriting acquisition directories, unchanged token state and
manifest-last output. The position runner checks token expiry before its one
GET; the history runner makes exactly the ordered pair of GETs.

The current local OneBot authentication source does not match either retained
runner's authentication-source pin; its configuration source does match.
This is a local source comparison, not proof of the installed VPS version or
a security defect. The inspected current `get_access_token` branch still stops
on expiry in batch mode, but source/runtime provenance must be reviewed and
rebound rather than bypassed. The archived position source contract also
records a historical pre-capture refresh; it must not be carried forward as
authority for this proposed zero-refresh run.

The archive-location/code-review dependency is resolved. Current owner-host
identity, installed source/runtime hashes, acknowledgement, exact new dates,
new run/approval identities and empty output/transfer destinations remain to be
bound before a runnable command or broker-access approval is presented. Old
single-use approvals cannot be reused. Do not alter or execute the archived
runners on the Mac. No OneBot source change, deployment, provider call or
credential access is authorized by this preparation.

### Owner-host read-only verification: 2026-10-09

The owner supplied the existing SSH destination. Strict known-host,
non-interactive read-only inspection reached the expected host and OS account.
Both retained runner files match their archived producer hashes and remain
`0600`; their existing source/evidence directories remain `0700`. The pinned
acknowledgement and account-binding files match their historical checksums,
remain `0600` and are not symlinks. Account-binding fields were not parsed or
displayed, and broker credentials were not opened; checksum equality is not a
new acceptance or proof that the acknowledgement is currently active.

The installed authentication module no longer matches either historical pin,
but its SHA-256 matches the current local OneBot source inspected above. The
installed configuration module still matches both old pins. The runners'
pinned Python executable exists but has a different hash from the historical
executable. The system Python version reported by a separate read-only probe
was 3.12.3; this is not proof of the capture environment's installed dependency
versions. No provider client was imported, no token was read, and no remote
file, environment configuration, database or service was modified.

The target/retained-installation lookup is now resolved. A fresh fixed capture
must use reviewed current source/runtime pins, fresh approval/run identities,
explicit dates and new output directories; do not relax a hash check or reuse
an old approval. Current owner-role/epoch and acknowledgement validity still
need explicit validation before capture. New runner installation and provider
access are not authorized by this read-only verification.

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
