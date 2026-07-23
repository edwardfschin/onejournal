# ADR-0003: Define financial units, currency, and time semantics

- Status: Proposed
- Date: 2026-07-23
- Decision owners: OneJournal project owner
- Related roadmap items: CON-02, CON-03 through CON-06, JRN-01 through JRN-05,
  PNL-01 through PNL-08
- Related contracts: `AGENTS.md`, `docs/onejournal_data_contract_v1.md`,
  `docs/schwab_orders_json_schema_contract.md`,
  `docs/schwab_transactions_json_contract.md`
- Supersedes: None
- Superseded by: None

## Context

The initial accepted product scope is one owner with multiple accounts,
Schwab-first, IBKR-next, and US-listed stocks and listed equity options. Its
first reporting currency can therefore be USD, but the normalized models
already carry a per-record `currency` and future broker/account data may be in
another currency. A trustworthy consolidated result must not silently treat
native-currency values as USD.

The current implementation uses `Decimal` for the reusable normalized domain
records and DuckDB `DECIMAL(38,10)` for persisted fills and episode amounts.
However, the current Schwab transaction adapter uses binary `float` while
deriving amounts, prices, commissions, and fees. The Streamlit prototype also
converts values to `float` for presentation. These are implementation gaps,
not an approved precision policy.

The prototype stores the current `filled_at`, `fetched_at`, `opened_at`, and
audit timestamps as DuckDB `TIMESTAMP` values. Its import scripts currently
discard timezone offsets before persistence. The Schwab orders and transactions
adapters derive `asof` by taking the first ten characters of the broker
timestamp instead of converting the instant into an explicit trading timezone.
This can assign an event to the wrong market date near midnight or during DST.

`config/app.yaml` names `Asia/Singapore` as the prototype application timezone,
while the accepted product scope is initially US instruments. The project needs
separate rules for storage, trading date, and display time before it implements
P&L, portfolio totals, reconciliation, or a production website.

## Decision

Subject to approval, OneJournal will use the following contract.

### Currency and aggregation

- USD is the initial reporting and consolidated portfolio currency.
- Every source monetary value retains its native transaction currency as an
  uppercase ISO 4217 code. A currency field means the unit of the value; it is
  not a display preference or an account's preferred currency.
- A native-currency record must never be relabelled as USD. Missing, blank, or
  unsupported currency is an ingestion error for financial records.
- A consolidated USD total may include a non-USD value only when the required
  FX rate is recorded with its base and quote currencies, source/provider,
  rate timestamp or as-of time, conversion purpose, and calculation version.
- Until an approved FX contract and evidence exist, non-USD records are shown
  in separate native-currency groups and any affected USD aggregate is
  unavailable or incomplete. OneJournal must not use a rate of 1, a latest
  rate, an account base currency, or a display preference as an implicit
  conversion.

### Numeric precision and rounding

- Domain calculations and persisted financial values use decimal arithmetic;
  binary floating point is prohibited for financial calculation, allocation,
  reconciliation, serialization, and persistence.
- Existing `DECIMAL(38,10)` storage remains unchanged by this ADR proposal.
  It is the minimum current storage precision for fills, prices, quantities,
  commissions, fees, strikes, multipliers, and calculated monetary values.
- Source precision is preserved through normalization and intermediate
  calculations. Rounding occurs only at a documented settlement, allocation,
  export, or display boundary.
- Monetary display and externally settled amounts use the currency's ISO 4217
  minor-unit scale (two decimal places for USD) with `ROUND_HALF_EVEN`, unless
  a later approved broker or legal contract requires a different rule.
- Prices, quantities, strikes, multipliers, and FX rates retain the available
  source precision up to the storage contract; they are not rounded merely for
  display. Any later allocation residual rule belongs to the P&L/lifecycle
  contract and must reconcile exactly.
- JSON and API financial values are decimal strings, never JSON numbers. The
  frontend may format them for display but must not calculate using a float.

### Instants, dates, and timezones

- An event instant is stored and exchanged as a timezone-aware UTC instant;
  raw broker timestamp text and offset remain traceable through raw evidence.
  Future durable database migrations use `TIMESTAMPTZ` (or an equivalent
  explicitly UTC representation), not a timezone-less `TIMESTAMP`.
- The project owner display timezone is `Asia/Singapore`. It changes only the
  presentation of an instant and never changes the market date or source
  record.
- The initial US market timezone is the IANA zone `America/New_York`, which
  observes DST. Fixed offsets such as `-04:00` and `-05:00` must not be used as
  a durable timezone policy.
- The `--asof YYYY-MM-DD` operator flag means the US market date in
  `America/New_York` for the initial supported instruments. It is neither the
  UTC date, Singapore display date, import date, broker posting date, nor
  settlement date.
- A fill's market date is derived by converting its confirmed execution instant
  to `America/New_York` first. Preserve event instant, market/trade date,
  posting date, settlement date, and import/fetch time as separate concepts.
  Do not substitute one for another.

### Trading sessions

- Session classification is metadata, not a replacement for the market date.
  It must use an approved exchange calendar and instrument/venue rules when
  available; weekends, holidays, early closes, and DST must not be inferred
  from a weekday-only rule.
- For initial US equities and listed equity options, normal regular-session
  evidence is classified against the applicable exchange calendar. Off-hours
  evidence is retained with an explicit pre-market, after-hours, overnight,
  closed, or unknown classification where that classification is supported by
  authoritative evidence.
- When venue/session evidence is insufficient, OneJournal records
  `unknown` rather than guessing. A future instrument with a cross-midnight
  trading-date convention requires its own approved mapping before P&L or
  market-date reporting relies on it.

### Worked examples

| Source execution instant | UTC instant | New York time | Market `asof` | Singapore display time |
|---|---|---|---|---|
| `2026-06-02T10:15:00-04:00` | `2026-06-02T14:15:00Z` | 10:15 EDT | `2026-06-02` | 22:15 SGT |
| `2026-06-02T23:30:00Z` | `2026-06-02T23:30:00Z` | 19:30 EDT | `2026-06-02` | 07:30 SGT on 2026-06-03 |
| `2026-01-05T15:00:00-05:00` | `2026-01-05T20:00:00Z` | 15:00 EST | `2026-01-05` | 04:00 SGT on 2026-01-06 |

A USD commission of `1.235` is preserved as `1.235` while calculated and
stored; a USD settlement or display boundary rounds it to `1.24` using
`ROUND_HALF_EVEN`. A EUR result without recorded EUR-to-USD evidence remains
EUR and makes any affected USD consolidated total unavailable or incomplete.

## Boundaries

This decision establishes units and temporal semantics only. It does not
choose a market-data provider, an FX provider, an FX-rate timing rule, a
tax-lot method, a realized/unrealized P&L formula, an exchange-calendar
library, or a production frontend/API/database stack.

It does not authorize a database migration, data rewrite, broker access,
currency conversion, consolidated financial reporting, order action, or
automated trading. The current `Asia/Singapore` prototype configuration is a
display preference only after the implementation adopts this contract; it is
not evidence that existing persisted `asof_date` values were correctly
derived.

## Alternatives considered

### Treat every initial record as USD and defer currency fields

This is initially simple but corrupts future non-USD broker evidence and makes
consolidated P&L impossible to audit. Rejected.

### Convert all values automatically using the latest FX rate

This produces convenient totals but makes historical P&L non-reproducible and
can conceal stale or missing conversion evidence. Rejected.

### Persist local naive timestamps and derive `asof` from their text date

This avoids a database migration now but produces ambiguous instants and wrong
market dates around timezone boundaries. Rejected as the future contract. The
existing behavior remains a known implementation gap until a controlled
migration is approved.

### Use Singapore date as the market date

This matches the project owner's location but shifts US evening activity into
the following date and breaks reconciliation to US market activity. Rejected.

### Round every imported value to two decimals

This is familiar for USD display but loses price, quantity, fee, and allocation
precision before financial calculations complete. Rejected.

## Consequences

### Positive

- Financial totals remain traceable to a stated currency and conversion
  evidence.
- Market-date reports reconcile to the initial US instrument scope despite a
  Singapore display timezone and DST.
- P&L, lifecycle, reconciliation, and future broker adapters have a common
  precision and time boundary.
- The design fails closed when currency, FX, timezone, or session evidence is
  incomplete.

### Negative and trade-offs

- Current adapters, scripts, schema, tests, contracts, payloads, and Streamlit
  formatting need focused follow-on changes before they conform.
- `TIMESTAMPTZ` adoption requires a versioned, tested migration on a temporary
  database copy; existing journal data must be classified before any conversion.
- FX conversion and exchange-session support remain unavailable until their
  own providers and contracts are approved.
- Decimal strings add frontend formatting work but avoid silent numeric loss.

## Compatibility and migration

After acceptance, implementation must first map every reader and writer of
`asof_date`, timestamp, currency, decimal, and payload fields. In particular,
it must replace date slicing in the Schwab adapters; remove float-based
financial derivation; preserve offsets rather than stripping them during DB
imports; migrate persisted instants using a versioned reversible plan; and
update tests, examples, contracts, scripts, payload consumers, and operator
documentation together.

No existing row may be silently reinterpreted as UTC, New York time, or
Singapore time. For each legacy timestamp, the migration must either prove its
timezone from source evidence, record an explicit conversion assumption for
review, or retain it as unresolved and exclude it from time-sensitive financial
results. Existing raw broker evidence remains immutable.

## Security, privacy, and financial impact

Currency, timestamps, broker source data, and account records are financial
evidence. Errors in currency conversion or market-date assignment can misstate
P&L, positions, performance periods, and risk. Therefore incomplete evidence
must be visible as unavailable or incomplete, not represented as zero or a
plausible total.

FX provenance, raw timestamps, account identities, and broker records remain
private and must not be exposed through public payloads, fixtures, logs, or
screenshots.

## Validation

An implementation of this ADR must prove:

- UTC instants and New York market dates are correct across EST/EDT transitions
  and Singapore date boundaries.
- A timezone-less or malformed timestamp fails ingestion unless an approved
  source-specific rule resolves it.
- `--asof` filters by the derived New York market date.
- Decimal calculations and JSON serialization do not pass through binary
  float.
- Intermediate precision is retained and boundary rounding follows the stated
  rule.
- Non-USD values without recorded FX evidence cannot enter a USD aggregate.
- FX-backed conversions preserve rate provenance and reproduce the same result.
- session classification is explicit, calendar-backed where supported, and
  unknown when evidence is insufficient.
- any database migration succeeds on a temporary copy, preserves row counts and
  evidence lineage, and has a tested rollback path.

## Rollback or supersession

This proposal changes no runtime behavior. If accepted, implementation changes
must be independently versioned and reversible. A future decision may
supersede this ADR to expand supported markets, define FX provider/rate timing,
or change the reporting currency; it must include compatibility and
recalculation rules for historical financial results.
