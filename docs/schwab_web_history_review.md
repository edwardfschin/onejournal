# Retained website-history diagnostic review

This is a read-only maintenance review, not an importer, financial release or
claim that lifetime account history is complete. Formal Phase 1 remains **8/12**.

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

Statement agreement proves corroborated source fields, not a normalized fill,
an intraday UTC instant, independent currency evidence, lifetime completeness
or financial-release eligibility. Statement-backed candidates remain separate
from native import admission. Changed generated archive IDs remain withheld
even when retained economic versions agree. Price-derived cash differences and
unsupported asset classifications are not waived by corroborated settled cash.

The review consumes existing private PDFs/JSON and produces only new private
diagnostic artifacts. It adds no PDF dependency to the application, importer,
API or website and changes no financial, identity or timestamp contract.

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
financial results. No broad regression suite or dependency installation is
needed because the diagnostic is not connected to existing runtime consumers.

Original artifacts are never overwritten. Failed or superseded diagnostic
attempts are retained with explicit replacement receipts. Rollback means stop
using this review and revert the focused diagnostic source if necessary; no
live restoration, source deletion or service restart is required.

This reinforces existing evidence-before-interpretation principles without
changing strategic scope, financial methodology or operational acceptance.
