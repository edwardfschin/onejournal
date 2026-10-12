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
trade actions enter the fill comparison. Matching requires exact supported
instrument fields, side, option opening/closing effect, quantity, price, net cash
and recorded costs. Provider side capitalization is normalized for comparison,
not changed in the source. Posting and broker as-of dates remain separate and
are compared against existing explicit execution-date evidence.

A one-to-one economic match is a diagnostic candidate, not proof that provider
activity identities are equal. Repeated website economics or multiple candidate
fills are marked ambiguous rather than deduplicated or preferred. Candidate
lists are deterministically sorted without choosing a winning identity.

Unmatched rows are not automatically missing trades. The private follow-up
distinguishes execution-detail differences, cost/cash differences, date
differences, repeated economics and absence from the currently admitted or
nonconflicting archive candidates. Split execution, withheld archive versions,
aliases, corporate actions and transfers still require source reconciliation.

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
competing lots, transfers, missing inputs and non-finite values. Actual private
replay verifies pinned sources, unchanged database bytes and unchanged base
financial results. No broad regression suite or dependency installation is
needed because the diagnostic is not connected to existing runtime consumers.

Original artifacts are never overwritten. Failed or superseded diagnostic
attempts are retained with explicit replacement receipts. Rollback means stop
using this review and revert the focused diagnostic source if necessary; no
live restoration, source deletion or service restart is required.

This reinforces existing evidence-before-interpretation principles without
changing strategic scope, financial methodology or operational acceptance.
