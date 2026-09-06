# ADR-0027: Derive lifecycle phases and option settlement links from exact Schwab evidence

- Status: Accepted
- Date: 2026-09-06
- Owner: OneJournal project owner
- Related: ADR-0005, ADR-0024, ADR-0025, P1-06, WEB-W06

## Context

The execution-first journal stores an option's opening and closing fills in one
instrument lifecycle, but the list previously rendered that lifecycle as a
single flat row. This hid whether a closed option was bought or sold to close.
An option assignment or exercise and its resulting stock execution were also
separate records with no safe presentation relationship. Schwab expiration
events were present in the accepted evidence but were not visible in the
journal presentation.

The latest reconciled Schwab assembly contains the exact transaction type,
time, instrument, side, quantity, price, multiplier, account scope, and journal
execution projection needed to make these relationships visible. Description
text and screenshots are not authoritative enough to create them.

## Decision

OneJournal may derive a read-only `schwab-lifecycle-presentation.v1` story from
the latest reconciled Schwab assembly and its exact journal execution
projection:

- opening and closing fills for one exact instrument episode are summarized as
  ordered phases with source-derived instruction, time, quantity, weighted
  average fill, cash movement, commissions, fees, currency, and execution count;
- an option settlement is labelled `assignment` only for a short option and
  `exercise` only for a long option;
- the resulting stock execution is linked only when a Schwab option-closing
  receive-and-deliver transaction and stock trade uniquely agree on the
  same private account, UTC instant, underlying, strike price, contract
  quantity times multiplier, expected stock direction, and projected journal
  executions; and
- a closed option may show `expiration_indicated` only when an exact Schwab
  receive-and-deliver expiration event matches the private account, option
  contract, residual FIFO quantity, expiry date, reconciled terminal-event
  state, and projected lifecycle; the presentation exposes expiry and posting
  dates separately and remains `review_required`; and
- API and UI output omit provider account and transaction identities and expose
  only stable OneJournal identities and privacy-safe financial facts.

Ambiguous or inconsistent candidates do not receive a derived phase or stock
link. The option and stock remain independently searchable and inspectable.

## Boundaries and consequences

- This relationship does not merge option and stock lifecycles, change their
  status, write journal state, allocate stock lots, or calculate P&L.
- A linked assignment can still be `review_required`; presentation evidence
  does not promote financial authority.
- A stock episode may contain multiple assignments or other fills, so the link
  targets the exact stock execution while the stock lifecycle remains whole.
- The exact stock execution may open stock, as with shares acquired through a
  short-put assignment, or close stock, as with covered-call shares called
  away. Requiring only an opening stock effect would discard valid settlements.
- The list may suppress a standalone stock card while that same stock lifecycle
  is linked beneath a displayed assignment or exercise. The stock record is not
  deleted or merged and remains available through exact lifecycle inspection.
- An expiration description hint does not prove that an option expired out of
  the money or worthless. The UI may say that Schwab indicates expiration and
  that no stock settlement was matched, but it must not promote that evidence
  into a financially authoritative outcome.
- Vertical presentation groups from ADR-0026 remain higher-level list groups;
  their member lifecycles remain available for exact inspection.
- No provider call, database migration, screenshot transcription, ticker-only
  match, free-text match, or manual financial override is permitted.

## Validation and rollback

Tests must prove opening-plus-buy-to-close grouping, exact assignment linkage,
exact expiration matching, privacy-safe output, and fail-closed behavior for
ambiguous stock or expiration candidates.
The versioned API, frontend build, real private read-only smoke, and responsive
browser view must also pass. The browser presentation uses compact two-line
phase/member rows with readable type and reduced empty space; density changes
must not remove source-derived quantities, prices, cash movement, fees, dates,
status, or quality.

Rollback removes the derived v1 reader and API/UI fields and restarts the local
services. It does not restore or rewrite journal data.
