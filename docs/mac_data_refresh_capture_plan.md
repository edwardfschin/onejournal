# Mac data-refresh capture preparation

## Status: capture, mapping and offline coverage complete; financial release pending

### Approved offline correction and rehearsal: 2026-10-11

The owner's `Proceed to next few items` approved the bounded implementation,
copy-only upgrade rehearsal, focused validation, documentation, commit and push
described below. It did not approve further broker requests, live database
writes, deployment, report activation or runtime changes.

Implemented offline:

- Batch acquisition profile v2 retains two disjoint captures, each at most 50
  symbols, within the existing five-GET ceiling. The intake operator accepts
  the complete synthetic 50+14 scope and emits instrument digests, not symbols.
- Assembly v3 retains all ten families, separate quote-source lineage, actual
  provider quote dates, the New York snapshot date and the exact UTC snapshot
  cutoff. UTC history windows are not relabelled. Later financial activity is
  excluded and counted; orders remain source observations rather than proof
  that their later state existed at the snapshot instant. Fill reconciliation
  is recomputed across the admitted history. Freshness/session guards remain.
- Migration 0027 adds one private immutable artifact store. It does not rebuild
  accepted v1/v2 tables, alter current views, activate history or publish reports.
  The writer requires the exact migration checksum and exact artifact read-back.
- Pure journal, execution and lifecycle calculations accept the new evidence.
  The legacy history-activation writer explicitly rejects v3 before opening a
  database: its migration-0021 date constraint and v2 foreign-key lineage are
  not bypassed. A compatible history/report refresh writer remains outstanding.

Copy-only rehearsal used the existing immutable schema-0026 pre-report-persist
backup (SHA-256 `c009a21c4b0eaa85e06031bb01e41a2981fb9574b0582f096427febb3b218b13`).
The upgrade preserved all 73 existing base-table counts (apart from the one
expected ledger entry), existing column definitions, nine view definitions and
two old assembly fingerprints. The new evidence table stayed empty. Migration
replay passed and the original backup checksum remained unchanged. The live
database was not opened. The accepted private v2 artifact also passed exact
canonical byte-for-byte roundtrip under the changed implementation. Migration 0027 SHA-256:
`2bc7f348910bd92e95b825929a2fd344a37b12d840f011b0169794c272b828fa`.

Forty-four focused tests passed across the affected modules. Synthetic
regressions cover 64-instrument intake, batch scope/lineage, weekend
date separation, exact cutoff admission/exclusions, tamper rejection, storage
replay, operator dispatch and legacy activation rejection. Existing acquisition,
assembly, lifecycle and history-revision tests also pass. No private v3 assembly
or refreshed financial release has been produced: fresh quote/session responses
are still absent. All eight unresolved current-position scopes remain unresolved;
Phase 1 remains **8/12**. Product scope and strategic maturity claims are unchanged.

Rollback before any live use is a focused source revert. Disposable copies were
removed on completion; existing private evidence and accepted reports remain.

### Retained request-scope proposal: 2026-10-11

The request scope below remains a proposal, not broker authority. The additive
contracts have now been implemented under the offline approval above.
Read-only preparation from the validated 64-position binding created a new
private `quote-preparation-01/scope-proposal.json` below the Mac refresh root.
It contains the exact sorted provider symbols and two disjoint batches of
**50 and 14**; membership, uniqueness, ordering and recombination were checked.
No instrument is dropped because it lacks fill-history eligibility. Proposal
SHA-256: `fd149f54a86fa17ca62206a07d3f1bd74acd2189637dc46b62ed819f32a3bcdd`.
The proposal is explicitly non-executable and unaccepted financially.

The pre-correction code had three concrete compatibility blockers:

1. The batch acquisition profile and converter accept exactly one quote batch
   of at most 50 instruments. The assembly also accepts one converted quote
   capture. They cannot express the complete 64-instrument scope. The proposed
   additive path allows two disjoint batches, each retaining the existing
   50-symbol ceiling and independent immutable response lineage.
2. Assembly builder and read-back compare UTC history-window end dates with
   the position's New York date. October 11 UTC history and the October 10
   snapshot therefore fail `lifecycle evidence extends beyond asof`. This
   exact guard was reproduced offline. Migration 0020 also encodes the same
   date comparison in its run-table CHECK constraint; changing only Python
   would leave persistence broken. The proposed versioned correction preserves
   actual UTC query dates and bounds admitted financial activity by the exact
   snapshot receipt instant, with explicit exclusions for later rows.
3. Quote capture validation correctly requires a quote's `asof` to match its
   provider timestamp in New York. Assembly currently requires that date to
   equal the snapshot date. A last-session October 9 quote therefore cannot
   accompany an October 10 snapshot. This is a structural incompatibility, not
   evidence that newly fetched quotes necessarily have October 9 timestamps.
   The proposed correction keeps quote date, snapshot date and evaluation
   instant distinct, relying on existing same-provider session/freshness
   authority. It does not relabel a quote, infer a session or loosen freshness.

The exact candidate request scope is two quote GETs with
`fields=quote,reference`, plus three same-provider equity/option market-hours
GETs for October 9, 10 and 11: **five GETs total**, no retry, account discovery,
order write or credential transfer. October 9 is only a proposed normal
reference and must be confirmed by returned provider schedule evidence. Actual
quote/evaluation dates must be covered by those responses. The proposed
schedule validity ends October 12 at 00:00 UTC. Expired or insufficient scope
requires repreparation; no invented trading calendar, waiting rule or timestamp
change is permitted. No new broker GET is approved or performed here.

The implementation approval covered the additive acquisition and
assembly contracts, affected conversion/read-back/materialization consumers,
necessary additive migration preparation, focused synthetic regressions,
disposable-copy rehearsal where evidence permits, documentation, commit and
push to `codex/pnl-02-market-data-contract`. Preserve v1/v2 fingerprints,
accepted releases and all eight unresolved positions. Live migration,
persistence, broker access, deployment and runtime changes remain excluded.
The impact is the credential-free evidence pipeline and its private persistence
format, not the frontend or a new provider/security policy. Rollback retains
the accepted September release and old contracts. The initial proposal-only
investigation changed no source, schema, financial policy or live state;
the subsequent offline implementation is recorded above.

### Date correction: 2026-10-11

The noon Singapore restriction was introduced by OneJournal's preparer, not
Schwab. It incorrectly required the UTC download date to equal the New York
market date. The owner approved correcting this mismatch. `--asof` in the
capture preparer now fixes the approved **UTC acquisition day** only. Requests
and responses must remain within that UTC day; naive timestamps and an expired
day still stop before a complete manifest. History query boundaries remain
the exact approved UTC windows. The retained position producer already derives
its market date from the actual receipt timestamp in `America/New_York`; that
behavior is preserved. No timestamp is backdated, and receipt is not proof of
a completed market session.

Thirteen focused preparation tests cover both sides of midnight, standard and
daylight-saving offsets, and a response crossing New York midnight versus UTC
midnight. Nine focused position-intake tests also pass, including preservation
of the actual New York market date when UTC dates differ and rejection of a
false market date. No intake, financial, assembly, database or publication guard is
weakened. The approved scope remains five read-only requests, private transfer
and credential-free intake validation. Full financial assembly is a later
step: its existing UTC-history-end versus market-date constraint must be
resolved explicitly if the actual evidence exposes it, not bypassed to publish
results. Live database writes and runtime restarts remain excluded.

The three installed `-01` programs contain the superseded equality guard and
have not executed any broker request. Keep them unused and prepare corrected
programs in new `-02` run directories under the same approved private parents,
reusing the validated isolated environment and existing acquisition approval.
Do not overwrite old programs or evidence. Source rollback is a focused revert;
unused private programs do not affect OneBot or the website.

### Execution receipt: 2026-10-11, 10:29 Singapore time

The corrected `-02` programs were installed without overwriting the `-01`
programs. Their actual isolated-runtime date, transport and isolation guards
passed before noon. Source/runtime/wrapper pins and the active VPS role matched.
The position runner then stopped before its GET because the existing OneBot
access token had expired. Both history runners remained unstarted. All three
acquisition directories are empty: zero provider responses and zero completed
manifests. The position preflight's acknowledgement and source contract are
preserved as incomplete run evidence. No OAuth refresh, automatic retry, Mac
evidence transfer, live database write or service restart occurred.

Renewal of the existing OneBot-owned token was initially excluded. The owner
then explicitly authorized it and instructed `proceed`. The failed directory
was preserved, not retried; a fresh `POSITION-03` program was prepared for the
same approved UTC day and known account scope.

### Authorized renewal, capture and transfer receipt: 2026-10-11

OneBot's existing confidential-app renewal path renewed the expired access
token once, using its existing cross-process lock and atomic owner-only token
store. No token was copied into OneJournal. The owner implementation and its
configuration/wrapper pins were unchanged. The three capture programs then
completed all five approved GETs with zero in-capture refreshes, retries,
account-discovery requests, order writes or database writes:

| Bundle | GETs | Source records | Complete manifest SHA-256 |
| --- | ---: | --- | --- |
| `POSITION-03` | 1 | 64 position rows | `fa2be30a32ecba4e3f8c01aaead3cdef4fd2f7559d9654c031b2076f8a5066c8` |
| `HISTORY-W01-02` | 2 | 94 orders, 62 transactions | `fdcd56a62d6450166e5a5627db12f8e934423d2f47af5542192f036838b6746b` |
| `HISTORY-W02-02` | 2 | 30 orders, 20 transactions | `69fd1c4eaaef347f5eccc8d46d658c6ac41bac42927e9258a95d3f6b5cbbc862` |

The new private Mac destination below contains three separate bundles, 17
exact files. Source/destination checksums and `0700`/`0600` permissions matched.
Only producer programs, source contracts, acknowledgements, acquisition
manifests and response bytes were transferred; no credential or account-binding
source was transferred. The missing `mac-refresh` parent was created privately
under the existing private evidence root, without changing existing material.

Credential-free intake verified both lifecycle bundles under the existing
policy, account binding, owner epoch and exact approval/run identities. W01
has 50 matched fill rows, no order-only fills and one transaction-only fill;
reconciliation remains pending. W02 has 19 matched fill rows and no unmatched
fills. Existing window exclusions remain explicit: W01 excludes one order
observation and two order fill rows; W02 excludes three order observations.
Intake success is not complete financial-history acceptance.

Position conversion stopped correctly against the retained September mapping:
28 response instruments are unmapped and 22 old mappings are no longer in the
current response. The receipt-derived New York market date is **2026-10-10**,
while acquisition occurred on **2026-10-11 UTC**. No date was changed to make
those labels equal. Changed instrument identities need source-backed mappings;
do not guess option terms or multipliers. Resolve the unmatched transaction and
the assembly UTC-window/market-date constraint before financial acceptance.
Fresh quote/session evidence is also still a later bounded acquisition scope.

No journal materialization, live migration, report-release write, API restart
or website update occurred. The accepted September report remains unchanged;
Phase 1 remains **8/12**. The next useful work is offline mapping and lifecycle
reconciliation, not another copy of these already completed broker requests.

### Offline mapping and coverage receipt: 2026-10-11

The owner instructed `Proceed` for offline mapping and reconciliation using the
downloaded evidence. A new private binding and value-free preparation audit
were generated under the existing Mac refresh root in `offline-preparation-01`,
with `0700` directory and `0600` non-overwriting files. The September binding,
immutable provider responses and accepted release remain unchanged.

The new binding covers all **64** current positions: **36** retained mappings,
**28** new transaction-authoritative mappings and **22** retired mappings absent
from this snapshot. Every new option's canonical terms, currency and multiplier
come from verified accounting transactions; OCC fields only verify the binding.
The credential-free position intake operator passed against the saved binding,
including exact account completeness, quantities and receipt-derived New York
date `2026-10-10`. Binding SHA-256:
`389840b8a2ac0588b4249a44eea17ed78bf5fe3057522c04e6c8a332500dd07d`.

The accepted September assembly selects seven historical source manifests.
Those exact sources plus the two new windows form nine contiguous,
non-overlapping UTC windows from March 6 through October 11, evaluated at the
position receipt `2026-10-11T02:32:16.555819+00:00`. Coverage SHA-256:
`db32759dd96212093339cc8f1670df28ad7509b365b842b69f40645a39b371cc`.

Of 64 positions, **56** pass `fill_flat_start_proven`, **5** require history
extension and **3** require reconciliation review. All eight remain unavailable
for this fill-based financial scope; identity mapping does not admit them to
FIFO or promote them to accepted P&L. Across retained and new history there are
604 order fills, 609 transaction fills, 601 matches, three order-only fills and
eight transaction-only fills. These combined unmatched counts include retained
historical omissions, not eight new capture failures. The single newly unmatched
W01 transaction is dated September 11 and has no broker order number. It does
not affect a current position. Preserve it as unresolved historical evidence;
do not manufacture an order match from symbol, price, quantity or time.

The reusable preparation function is pure: no files, broker requests,
credentials, database or runtime access. It requires the verified position
acquisition, canonical retained binding and exact-cutoff coverage; independently
checks derived identities against accounting rows; validates the complete
snapshot; and emits only digest/count-based audit fields. Nine focused synthetic
tests cover deterministic replay, explicit non-standard option multiplier,
identity conflicts/tampering, missing accounting proof, cutoff/scope/fingerprint,
quantity/membership and privacy failures. Nine existing coverage tests and nine
position-intake tests also pass. No broad test run was needed.

Next, prepare the exact quote/session scope from this verified snapshot and
resolve the UTC-history-window versus New York market-date assembly constraint
without weakening its instant cutoff. Further broker requests, live database
writes and website activation are not authorized by this offline preparation.
Rehearse financial assembly and the report release on a disposable journal only
after required evidence is valid; unresolved scopes must remain visible.
Phase 1 remains **8/12**. Rollback is a focused source revert and continued use
of the retained September binding/release, not deletion of private evidence.

Prepared on 2026-10-09 for the existing private single-owner `Primary` scope.
The offline preparation command now produces fixed, private owner-side runner
sources from the checksum-verified retained scripts. This is not broker-access
authorization or a new provider policy. No provider call, credential read,
broker evidence creation, transfer, database write or service restart was
performed during preparation. Local private program files are not broker
evidence and must not be committed.

## Authorized installation receipt: 2026-10-11

The owner explicitly instructed `Proceed` after the single bounded installation,
five-GET, private transfer and offline-validation proposal. Approval identity
`ONEJOURNAL-MAC-REFRESH-20261011-CAPTURE-01` now records that exact scope; it does
not authorize token refresh, retries, live DB writes or service changes.

The named separate environment and three prepared runners were installed under
the approved existing private parents. All new directories are owner-only;
programs, lock and wheels are `0600`. Installation used the five exact reviewed
wheels, offline hash enforcement and a copied executable matching the base pin.
Actual isolated-runtime validation passed: exact versions and origins, no
shared/user-site inheritance, all three producer hashes, TLS CA loading,
synthetic streamed response and package consistency. Shared Requests 2.31.0 and
urllib3 2.0.7 remain unchanged. No broker client was imported, token read,
provider request made, evidence transferred or service restarted.

At 10:16 Singapore time, the original equality guard rejected capture. That
restriction was an implementation error, corrected above, not a broker rule.
The installed acquisition directories remained empty. Continue the already-authorized five-request scope
only within the approved UTC day and after fresh role/pin/acknowledgement checks;
do not require a new approval for the same scope. No background schedule was
created. If the window expires, stop and reprepare rather than backdating or
silently changing approved identities/dates.

## Superseding preparation: 2026-10-11

The October 9 scope is expired. The proposal below supersedes it; subsequent
October 9 sections are historical evidence, not authority to run old commands.
This section records the preparation before the installation receipt above.

Read-only checks on `one-prod` reconfirmed the configured active VPS role,
expected OS user, unchanged auth/config/base-Python hashes and unchanged private
acknowledgement/binding pins. The acknowledgement validates against current
policy/time without renewal. The shared runtime still has Requests 2.31.0 and
urllib3 2.0.7; it must not run the capture. Python 3.12's `venv` module and pip
24.0 are available. No client was imported or token read during these checks.

The separate runtime root is the retained position runner's existing private
`OUTPUT_PARENT` plus `ONEJOURNAL-MAC-CAPTURE-RUNTIME-20261011-01`, with environment
child `python-env`. It and all proposed run roots are absent; their existing
owner-side parents are non-symlink `0700` directories. After authorization,
create only these named roots using a private umask. Use the inspected base
Python's `venv --copies --without-pip`, without inherited system packages.
Existing pip's `--python` target installs only into the new environment.
Do not upgrade shared OneBot packages, install OS packages, change services,
change credential paths or copy a token.

`config/mac_refresh_capture_requirements.lock` pins five universal wheels and
official PyPI hashes: Requests 2.33.0, urllib3 2.8.0, certifi 2026.7.22,
charset-normalizer 3.5.2 and idna 3.20. Metadata supports Python 3.12 and includes
all non-extra Requests dependencies. All five were downloaded locally with hash
enforcement; an isolated process imported the exact wheel bytes, loaded their
CA bundle and read a synthetic streamed response without network I/O. This is
not proof of the uninstalled VPS environment.

Transfer only reviewed wheels and the lock file into the named new runtime root.
Install with `--no-index --find-links`, `--require-hashes` and
`--only-binary=:all:`; do not fetch or compile other packages remotely. Before
broker access, validate its private permissions, absent shared/user package
inheritance, exact versions/module origins, installation consistency, capture
guards and one synthetic response. The copied non-symlink executable must match
the inspected base binary SHA-256 or execution stops for re-review. Recheck the
existing auth/config and private acknowledgement/binding pins without opening
the token store during setup validation.

The preparer's optional `--capture-python` explicitly rebinds the isolated
`bin/python3.12`. Launch with `-I -B`. Added guards enforce isolated mode,
disabled user site, exact executable/prefix, `0700` environment, no system
packages and matching Requests/urllib3 module origin/version before auth/token
access. Original hash checks, credential ownership and acquisition profiles
are preserved; no public contract is changed.

Approval: `ONEJOURNAL-MAC-REFRESH-20261011-CAPTURE-01` (granted for the bounded scope above).

| Order | New run identity | Scope | GETs |
| --- | --- | --- | ---: |
| 1 | `ONEJOURNAL-MAC-REFRESH-20261011-POSITION-03` | Complete existing-account positions; acquisition complete | 1 |
| 2 | `ONEJOURNAL-MAC-REFRESH-20261011-HISTORY-W01-02` | Orders then transactions, September 5–October 4; acquisition complete | 2 |
| 3 | `ONEJOURNAL-MAC-REFRESH-20261011-HISTORY-W02-02` | Orders then transactions, October 5–11; acquisition complete | 2 |

Each new run stays under its retained runner's existing private `OUTPUT_PARENT`.
Use only the known account binding; no discovery, quotes, order writes, retry,
redirect or OAuth refresh. Expired tokens stop, without a refresh or owner
change. Write manifests last; preserve incomplete evidence on failure.

The corrected UTC acquisition-day guard allows capture on October 11 UTC
(08:00 Singapore time on October 11 until before 08:00 on October 12),
independently of the actual New York market date. Do not schedule automatically
or roll the date forward. October 11 is Sunday: receipt time is not a new market
session, current prices or full-day financial acceptance. Keep actual timestamps
and existing cutoff rules.

Private Mac destination, initially confirmed absent and now checksum-verified
after the transfer receipt above:
`/Users/edward/Projects/Private/OneJournal/mac-refresh/ONEJOURNAL-MAC-REFRESH-20261011-01`.
Transfer only separate acquisition bundles, producer programs and required
lineage, preserving checksums and `0700`/`0600` permissions. Never transfer the
environment, token or private account-binding source. Use existing credential-free
intake validation; do not overwrite old evidence or persist journal state.

Twelve focused tests pass, including isolated-runtime acceptance/rejection,
module-origin/shared-package guards and the new dates. The three updated private
programs compile on owner Python 3.12.3 in memory without execution. The largest
coherent next approval can cover this named installation, five broker GETs
conditional on its validation, new evidence, Mac transfer and offline validation.
It excludes live DB writes, report release, API/site restart, trading, shared
OneBot changes or another capture after failure/expiry. Setup rollback is to
leave the new environment unused; no shared state needs restoration. Preserve
incomplete evidence; deletion is not automatically authorized.

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

These are alternatives, not permission to fetch both. The UTC query end and
acquisition day must be fixed before broker access; derive the snapshot market
date from actual New York receipt time. Do not infer a completed US session from the Singapore calendar,
backdate a current snapshot, or silently roll this plan forward. An intraday
capture is not proof of a complete day's activity. Record request/receipt times
and apply the existing snapshot cutoff and freshness rules. The lifecycle
coverage check requires the snapshot cutoff's UTC date inside the assembled
range, while Phase 1 assembly requires the lifecycle end no later than the
snapshot's market date. These are different scopes: do not restrict read-only
acquisition to make their dates equal. Resolve that assembly constraint before
financial publication; never change timestamps or bypass financial guards.

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

### Current fixed preparation: 2026-10-09

`scripts/journal/prepare_mac_refresh_capture.py` orchestrates the pure source
compiler in `src/onejournal/provider_connectors/capture_preparation.py`. It
never imports or executes a retained runner, accesses credentials or connects
to a provider. Inputs include the reviewed source checksum, exact source/runtime
pins, proposed approval/run identities, dates and owner output root. Output is
one non-overwriting `0600` program in an existing `0700` private directory.
Historical sources, identities, owner epoch, binding, acknowledgement and
manifest profiles remain intact; the historical pre-capture OAuth refresh
declaration is replaced with zero.

Further read-only verification confirmed the expected OS account and configured
active-producer role on `one-prod`. The actual pinned runtime reports Python
3.12.3. Authentication/configuration/runtime hashes were rebound to the inspected
installation; acknowledgement and account-binding checksums remain unchanged.
The archived acknowledgement was also validated against the current provider
policy and current time without renewal. This does not grant a new owner lease,
authorize execution or read the account-binding contents. The three proposed
owner run directories and the new Mac transfer destination do not exist.

Proposed approval identity: `ONEJOURNAL-MAC-REFRESH-20261009-CAPTURE-01`.
It is a label for the proposed scope, not an approval already obtained.

| Order | Proposed run | Scope | GETs |
| --- | --- | --- | ---: |
| 1 | `ONEJOURNAL-MAC-REFRESH-20261009-POSITION-01` | Complete existing-account positions | 1 |
| 2 | `ONEJOURNAL-MAC-REFRESH-20261009-HISTORY-W01-01` | Orders then transactions, September 5–October 4 | 2 |
| 3 | `ONEJOURNAL-MAC-REFRESH-20261009-HISTORY-W02-01` | Orders then transactions, October 5–9 | 2 |

Historically, capture date was fixed to October 9 in both UTC and New York.
That equality requirement is superseded by the correction above. The added guard
runs before any side effect and immediately before/after each GET; a date
rollover stops without a complete manifest. An intraday snapshot remains
intraday evidence, not complete October 9 session coverage. History collected
after positions still uses the existing snapshot cutoff. Prepared entry points
hide unexpected exception details because HTTP errors can contain a private
account hash in their URL. No retry or implicit token refresh was introduced.

### Critical runtime dependency; do not execute the current installation

The pinned owner environment contains Requests 2.31.0 and urllib3 2.0.7. The
retained runners use streamed responses, and the four-MiB payload limit does
not bound a malformed chunk-size line inside the HTTP library. The official
[urllib3 streaming advisory](https://github.com/urllib3/urllib3/security/advisories/GHSA-vxq7-64xx-v4gw)
identifies this path as affected below 2.8.0. Requests also has published fixes
after the installed version; see its
[official advisory](https://github.com/psf/requests/security/advisories/GHSA-gc5v-m9x4-r6x2).
That latter advisory concerns a utility the runner does not call; it is not
evidence of a credential leak in this capture path.

The prepared runners require stable Requests >=2.33.0 and urllib3 >=2.8.0
before any credential/client import or GET. Missing, older or prerelease
versions fail closed. The current owner environment therefore cannot execute
the prepared capture. No package was installed, no shared OneBot runtime was
changed, and no service was restarted. Do not work around the guard with custom
HTTP parsing or remove it to use the old environment. Resolve an isolated
capture runtime and rebind its inspected executable/source pins before broker
execution. An isolated runtime must be reviewed for the existing OneBot auth
module's dependencies and existing credential-store path; do not copy tokens
or assume environment compatibility.

The nine focused synthetic tests cover exact scope rebinding, retained owner
and acknowledgement constants, bounded history dates, checksum/identity/output
boundary rejection, date guards, stale/missing transport rejection, private
exception suppression and non-overwriting private output. All three updated
programs also compiled in memory on owner Python 3.12.3 without executing their
entry points. Executing only the isolated transport guard, without importing
the client or reading credentials, confirmed that it rejects the current
environment. Earlier private program files predate the HTTP guard and are
superseded, not approved for use. Reprepare from retained sources after
resolving the capture runtime. No broad application test run or broker probe is
needed for this source-only preparation.

Proposed new Mac transfer root:
`/Users/edward/Projects/Private/OneJournal/mac-refresh/ONEJOURNAL-MAC-REFRESH-20261009-01`.
Retain each acquisition as a separate non-overwriting bundle; do not merge raw
directories. Dates and identities must be freshly prepared if the fixed scope
expires before authorized execution.

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
contracts. This preparation adds an offline source compiler, operator, focused
synthetic tests and operator documentation; downstream
intake, assembly, history revision, financial calculation and report-release
contracts are unchanged. No persisted state or user-facing runtime is changed.
Validation is the offline date-window calculation, source/profile comparison,
twelve focused tests, exact locked-wheel synthetic check and documentation/Git
diff checks. No broad test run or provider probe is needed. Rollback is a focused source revert; uninstalled
private prepared programs do not affect the running system. Do not delete
retained private evidence as part of rollback.
