# Historical activity evidence and retained website-history review

The original source review remains read-only. The separately approved historical
activity evidence loader imports only into a disposable journal copy in this
delivery; it does not admit canonical executions, publish financial results or
claim lifetime completeness. Formal Phase 1 remains **8/12**.

## Source and data flow

The owner-authenticated broker website produces unchanged private JSON/CSV
exports and monthly statements. Private acquisition receipts pin the original
bytes, selected account/query scope and capture observation. The review uses
the JSON plus an exact saved journal-history assembly and the earlier
nonconflicting archive-version candidates. Original acquisition metadata for
recovered archive files remain unknown.

`src/onejournal/brokers/schwab/web_history_review.py` is a pure diagnostic reader.
It has no broker client, credential, persistence, API or website dependency.
The caller verifies source checksums, account scope and explicit currency before
using it. It never creates provider IDs or normalized fills from website rows.

The only consumers are private reconciliation artifacts and human review. The
operator reads an exact quiescent disposable database copy; the source/copy
bytes and existing financial fingerprint are verified unchanged. No schema,
runtime, native journal row or accepted reporting authorization changes.

## Economic comparison

The review preserves every row, including non-execution activities; only explicit
trade actions enter the fill comparison. Individual matching requires exact supported
instrument fields, side, option opening/closing effect, quantity, price, net cash
and recorded costs. Provider side capitalization is normalized for comparison,
not changed in the source. Posting and broker as-of dates remain separate and
are compared against existing explicit execution-date evidence.

A one-to-one economic match is a diagnostic candidate, not proof that provider
activity identities are equal. Repeated website economics or multiple candidate
fills are marked ambiguous rather than deduplicated or preferred. Candidate
lists are deterministically sorted without choosing a winning identity.

The second comparison operates on **complete dated execution bundles**. Website
rows may combine partial fills or distribute displayed fees differently between
rows, while API records retain individual fills. Bundle matching requires the
same supported instrument, side, option effect, explicit currency, one consistent
deliverable multiplier, exact total quantity, net cash and known total costs.
It compares the complete source group, not a hand-picked subset. It preserves
every original fill and website-row multiplicity; no merged fill is created.

Posting/as-of and existing execution-date alternatives remain visible. Different
valid source groups or reuse of one source group across website date groups are
ambiguous, not resolved by preference. A reconciled bundle does not prove which
website row represents an individual provider activity. Displayed prices are
not patched or used to conceal a net-cash difference. No tolerance or rounding
rule is added to achieve a match.

Private raw-activity review additionally compares every retained economic version
for the same actual provider activity. Identical economics with changed item or
position references can corroborate cash without granting a new fill identity.
Conflicting economic versions remain excluded. A single-instrument raw cash
group must reconcile actual security cash and explicit currency charges to the
broker's net amount before it is compared with website quantity/cash/cost totals.
Confirmed settled cash is kept distinct from calculations using price and
fractional quantity; it does not silently change execution price, cost-basis or
financial rounding policy. Cash-only corroboration is not canonical admission.

Unmatched rows are not automatically missing trades. The private follow-up
distinguishes execution-detail differences, cost/cash differences, date
differences, repeated economics and absence from the currently admitted or
nonconflicting archive candidates. Split execution, withheld archive versions,
aliases, corporate actions and transfers still require source reconciliation.

## Legacy statement corroboration

Retained legacy-provider monthly statements can corroborate website-only
history without manufacturing canonical fills. The private review verifies
each PDF against its acquisition receipt, extracts the account-activity table
by its displayed columns, and checks the relevant layout visually. Wrapped
quantities and option opening/closing descriptions are preserved. Exact
instrument, action, quantity, displayed price and signed amount must agree.
Explicit commission/fee and regulatory-fee components are compared when present;
an absent cost line stays unknown rather than becoming zero.

Trade and settlement dates remain separate. A month-end trade can appear in
the following month's statement because of settlement. The caller checks that
neighboring statement rather than treating a calendar-month mismatch as lost
history. Repeated economics and reuse of one statement observation remain
ambiguous. Local page/row references identify an evidence location, not a
provider execution ID.

The later-provider statement explicitly identifies its Date column as the
settlement/process date. The review binds that footnote to the exact source
PDF/page; it does not compare that column as an execution date. Exact
instrument/action/quantity/price/cash/cost candidates may corroborate one unique
statement observation while both original dates remain independently visible.
No market calendar, guessed settlement schedule, nearest-date preference or
one-to-four-day tolerance is used. Neighboring retained statements are inspected
for month-end settlement, not used to fabricate a missing execution instant.

Statement agreement proves corroborated source fields, not a normalized fill,
an intraday UTC instant, independent currency evidence, lifetime completeness
or financial-release eligibility. Statement-backed candidates remain separate
from native import admission. Changed generated archive IDs remain withheld
even when retained economic versions agree. Price-derived cash differences and
unsupported asset classifications are not waived by corroborated settled cash.

The review consumes existing private PDFs/JSON and produces only new private
diagnostic artifacts. It adds no PDF dependency to the application, importer,
API or website and changes no financial, identity or timestamp contract.

## Approved bounded historical evidence contract

Contract: `onejournal.historical-activity-evidence.v1`. The owner instructed
`Proceed` after the implementation, critical validation, disposable-copy
rehearsal, commit and push proposal. This approves that source-only batch, not
live migration/import, financial acceptance/publication or runtime activation.

The existing `NormalizedFill` requires an execution datetime, and materialization,
FIFO lifecycle processing, snapshot cutoffs and reporting consume that instant.
Date-only website/statement observations cannot safely be forced through it.
The transaction-derived fill key also includes order/position/item references
that can change between retained versions. ADR-0006 does not authorize economic
deduplication of distinct source IDs, and broader correction governance in
ADR-0010 remains proposed. The recovered-opening supplement is still held and
is not a shortcut around these constraints.

The implemented bounded design is an additive, broker-independent historical
activity evidence ledger, separate from active normalized fills and reports:

- Preserve every activity, including assignments, expirations, cash movements
  and transfers, with immutable source-document hashes and row/page locations.
  A document location is an observation identity, never a fabricated provider
  fill ID. Separate exports remain deliveries; duplicate economics are not
  silently discarded.
- Preserve posting, reported trade/as-of and settlement dates separately;
  timestamp precision is explicit and unknown execution instants remain null.
  Keep native explicit currency, combined costs and missing values without
  inventing a commission split, option deliverable or currency default.
- For existing API evidence, retain the actual provider activity identity and
  all original generated IDs. Propose a reviewed activity-bundle equivalence
  link only when every retained economic version agrees and item multiplicity
  is preserved. Ambiguous equal items, conflicting versions and changed
  financial fields stay withheld. Existing fill keys are not renamed.
- Link observations to an existing canonical execution only when unique source
  reconciliation proves the relationship. Otherwise retain a historical
  activity candidate, not an additional execution or accepted P&L input.
- Support a date-granular lifecycle preview only where all possible intraday
  orderings yield the same result. Same-day competing openings, unknown basis,
  adjusted deliverables and incomplete transfers remain unavailable. Reuse
  established decimal calculation rules; do not create a second permissive
  P&L engine or change rounding to force cash agreement.

Alternatives are to postpone all date-only history until native execution
evidence is found, or to replace the existing fill contract with a precision-
aware version throughout the application. The first prevents useful historical
intake; the second has much wider migration and regression impact. Synthetic
midnight timestamps and economics-only deduplication are not acceptable options.

This is evidence admission, not canonical fill or financial admission. It does
not accept the broader ADR-0010 correction, supersession, retention or activation
proposal. There is no automatic choice of a current source version, canonical
fill key, currency, lot basis, commission split or execution timestamp. No
provider request or credential operation is required.

The impact map is immutable exports/statements/API evidence -> offline adapter
and historical ledger -> private reconciliation/lifecycle preview. A later
application/API history reader must distinguish activity evidence from canonical
executions. Existing active fills, notes, accepted reports and website responses
remain untouched in the first implementation batch. Validation must prove exact
replay, changed-ID non-duplication, conflict rejection, day-only ambiguity,
assignment/share linkage, missing-value preservation and unchanged predecessor
rows/results. Rollback is to discard the disposable candidate and stop selecting
the new ledger; originals and accepted history are never deleted.

### Record and replay rules

`src/onejournal/journal/historical_activity.py` validates, fingerprints, stores
and reads the exact selected bundle. Migration `0029` adds only five
`historical_activity_*` tables: import runs, source documents, observations,
run/observation links and provider-activity bundle reviews. No active-history
view, existing fill, journal review, accepted allocation or reporting table is
modified. The migration runner is unchanged; installation's existing SQL glob
packages the new authoritative artifact.

Each import run has an explicit ID, account/broker scope, `asof`, aware UTC
normalization-observation time and exact bundle fingerprint. This time is not a
provider capture or trade instant. A different import run records a separate
delivery even when content is unchanged; identical original file copies do not
become invented provider retrievals.

A document identity binds broker, opaque account, source kind and immutable
raw checksum. The run preserves private source paths and exact scope/review
proof paths and hashes. Observation identity binds document identity to its
actual row/page location. Equal economics at different locations remain distinct.
The same observation with changed interpretation is rejected, not overwritten.
Exact run replay checks complete stored JSON, typed dates, document scope, links
and review rows. A conflicting run ID or a partial read-back fails closed in a
transaction. No latest-run selector is provided.

Calendar fields are independently nullable `posting_date`, `asof_date`,
`trade_date` and `settlement_date`. Precision is `day`, `instant` or `unknown`.
Website/statement observations must have no provider activity ID or timestamp.
An API accounting timestamp is explicitly `provider_transaction`, never
relabelled as execution evidence. Missing currency/cost fields stay unknown;
source decimal strings and combined costs are retained without a float or a
commission/fee split.

`src/onejournal/brokers/schwab/historical_activity.py` supplies credential-free
website, raw-API, saved-assembly and already-reviewed statement adapters. Before
copy writes, source observations are re-derived from their exact originals and
pinned scope/review proofs. Statement observations must be exact members of the
checksum-bound prior review; this adds no PDF dependency to the application.
Raw API account validation uses the existing private binding. Repeated activity
versions inside a saved assembly retain their immutable array locations; raw
single-response duplicate activity IDs still fail. Original source records and
instrument objects are retained, with raw account numbers left in the immutable
source rather than duplicated in the projection.

Provider reviews bind only the exact selected source set. Complete item
multiplicity, source financial fields, instrument evidence and timestamps enter
the version signature; order/position/item reference changes do not select a
new fill. Released-scheme fill-key references are metadata, not proof of fill
admission. Review statuses are `consistent_bundle`, `economic_conflict`,
`ambiguous_security_items` and `unsupported_assets`. Missing instrument objects
are explicit; a retained instrument object does not prove valid deliverables.
Every status keeps financial admission false. A consistent selected bundle is
not proof that lifetime history or all external retained versions were supplied.

The copy preview reuses the existing narrow assignment/predecessor/share source
review. It preserves unknown intraday ordering and unproven event charges; it
does not create a second P&L engine, approved lifecycle allocations or a new
report release. The recovered-opening financial preview remains held.

### Guarded operator and validation

`scripts/journal/rehearse_historical_activity_import.py` accepts exact
`--source-db`, `--source-db-sha256`, `--bundle`, `--bundle-fingerprint` and a
new `--rehearsal-dir`. The source and bundle must be private regular files;
the source must be a quiescent schema-0028 saved copy. No writable target DB,
broker, token, server or restart flag exists. The command creates a verified
owner-only copy outside the repository, applies exactly migration 0029 there,
imports/replays/reads back the bundle and writes private receipts. Existing
output is never overwritten. Unexpected errors are value-free and nonzero.

The declared and locked `pytz` dependency is required by the current DuckDB
Python client when reading predecessor `TIMESTAMPTZ` values. OneJournal's domain
date handling remains standard-library UTC/zoneinfo; this is client read-back
compatibility, not a new timezone policy. Rehearsal can use an isolated temporary
dependency location without modifying the installed site environment.

The preservation check fingerprints every existing table/view's schema and
complete row multiset, preserving decimals, UTC/date values, UUID audit keys,
duplicate rows and legacy floating bits exactly. Only the new migration-ledger
row is additive. Focused tests cover source re-derivation, incorrect account,
missing data, exact decimals, fake timestamps, changed generated references,
instrument/economic conflicts, repeated assembly captures, item ambiguity,
unsupported assets, immutable replay, atomic conflict rejection, typed read-back,
assignment ordering, prior notes and non-overwriting copy-only behavior.
Actual replay must additionally preserve the prior financial fingerprint and
all admitted allocations/omissions and existing assignment links. Detailed
counts, values, paths, fingerprints and receipts stay private, never in Git.

## Assignment and recorded cash review

An assignment must have explicit option identity and positive contracts. The
share leg must match its underlying, exact strike and unchanged broker date
text. Put delivery uses explicit `Buy`; call delivery may use `Sell` or
`Sell Short`. A short-stock delivery is retained as such, not relabelled as a
sale of previously owned shares.

Short-option predecessors are linked by the existing FIFO intent only when the
available dates determine their order. Multiple same-day reductions may be
resolved without intraday timestamps only when there is exactly one prior lot,
no new opening that day, and total reductions do not exceed its remaining
quantity. Every ordering then has the same predecessor and proportional premium.
Competing lots, same-day openings, deficits and transfers remain withheld.
Neither website display order nor a synthetic UTC instant is used as evidence.

The delivery ratio is derived from confirmed share/contracts quantities and
checked against the opening option's actual gross premium, recorded costs and
net cash. It is not blindly assumed to be a standard contract multiplier.

The isolated put review additionally requires only the delivery and one full
share disposal in that equity scope. It calculates recorded net put premium,
share cash outflow, net disposal proceeds and their exact sum. Other call,
vertical and strategy trades are excluded. Blank assignment cash/fee fields do
not prove the absence of a separate event charge. No commission/fee split is
invented from a combined website cost field.

This result is labelled **recorded cash-chain diagnostic**, not authoritative
journal/report P&L or a tax-lot change. Independent statement basis/result
checks are retained privately. Native lifecycle admission, source identity,
timestamp semantics and compatible reporting persistence remain separate work.
The earlier ordinary recovered-opening preview remains held.

## Focused validation and recovery

Synthetic tests cover exact cash, separate dates, lowercase/uppercase sides,
repeat ambiguity, input-order replay, costs and quantity conflicts, partial
option closes, short-stock call delivery, same-day invariant reductions,
competing lots, transfers, missing inputs and non-finite values. Bundle tests
also cover partial fills, repeated-row multiplicity, exact cash/cost/quantity
differences, source reuse, date alternatives, mixed accounts and deliverables.
Actual private
replay verifies pinned sources, unchanged database bytes and unchanged base
financial results. No broad regression suite or change to the installed site
environment is needed because the diagnostic is not connected to runtime consumers.

Original artifacts are never overwritten. Failed or superseded diagnostic
attempts are retained with explicit replacement receipts. Rollback means stop
using this review and revert the focused diagnostic source if necessary; no
live restoration, source deletion or service restart is required.

This reinforces existing evidence-before-interpretation principles without
changing strategic scope, financial methodology or operational acceptance.
