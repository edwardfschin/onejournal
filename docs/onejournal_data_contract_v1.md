# OneJournal Data Contract v1

## Purpose

OneJournal is a broker-independent trading journal and dashboard platform.

The journal must not depend directly on Schwab, IBKR, or any single broker. Every broker or import source must pass through a broker adapter and produce the same OneJournal normalized records.

Auto-trading is out of scope for this version.

## Locked Safety Rule

OneJournal v1 is read-only.

Order placement, order cancellation, order replacement, and live automation are disabled.

Required safety gates:

- config/app.yaml: allow_order_placement: false
- config/journal.yaml: allow_order_placement: false
- ~/.onejournal/env/machine.env: ONEJOURNAL_CAN_PLACE_ORDERS=0

## ODFS Layout

- config/ = safe YAML settings and schemas
- data/ = raw inputs, provider exports, cache, computed datasets, audit/history
- output/ = dashboard payloads, reports, charts, human-readable summaries
- src/ = reusable Python application code
- scripts/ = command-line jobs
- docs/ = design notes, contracts, operator guides
- tests/ = validation tests

## Data Flow

Broker/API/CSV raw data -> Broker adapter -> Normalized OneJournal records -> Trade episodes -> Journal notes and tags -> Metrics -> Dashboard payload -> Dashboard UI

## Source of Truth

- Raw broker/import data: data/raw/<source>/
- Normalized records: data/normalized/
- Journal state/history: data/journal/onejournal.duckdb
- Dashboard payload: output/dashboard/latest/dashboard_payload.json
- Human review reports: output/reports/
- Project-safe config: config/*.yaml
- Private local config: ~/.onejournal/env/*.env

The current OneJournal runtime has no active broker credential or provider-call
path. Under the bounded PNL-02 mode accepted on 2026-08-31, OneBot/VPS remains
the temporary single-owner Schwab evidence bridge. OneJournal accepts only
separately approved private evidence bundles through credential-free
validation, adapter, reconciliation, and import boundaries.

The target architecture makes OneJournal the only project that owns approved
provider connections and calls Schwab, IBKR, Moomoo, or later providers. That
future integration boundary must keep credentials outside Git, raw evidence,
normalized records, DuckDB, logs, and UI state.

For bounded PNL-02 completion, ADR-0016 permits a temporary local bridge mode in
which OneBot remains the sole Schwab credential owner and OneJournal accepts
only exact provider bytes plus verified external-acquisition lineage. This does
not change the target provider-connector architecture, authorize continuous or
website-triggered acquisition, or make OneBot-derived normalized values
authoritative OneJournal state.

`onejournal.external-provider-acquisition.v1` is the versioned bridge intake.
Its canonical manifest binds the sole source owner and epoch, source artifact
hashes, approval and acknowledgement, active usage/lifecycle profile, exact
request/response scope, immutable byte digests, bounded activity counts, and
manifest-last completeness. OneJournal converts only verified exact provider
bytes through its own adapters. Deterministic conversion prepares the existing
quote-capture and private-capture contracts in memory; it does not itself write
private evidence or DuckDB. See `docs/external_provider_acquisition_contract.md`.

The dashboard is not the source of truth. It is a view.

## Market Date Standard

All market-date based scripts must use --asof YYYY-MM-DD.

Do not introduce duplicate flags such as --date, --run-date, or --trade-date unless explicitly approved.

## Broker Adapter Boundary

Each broker adapter must convert broker-specific payloads into OneJournal normalized records.

Supported adapter families:

- src/onejournal/brokers/manual_csv/
- src/onejournal/brokers/schwab/
- src/onejournal/brokers/ibkr/

The dashboard, journal metrics, and trade episode logic must not know whether a record came from Schwab, IBKR, or manual CSV.

## Minimum Evidence Adapter Interface

Each broker/import adapter should eventually support credential-free ingestion
capabilities over already captured evidence:

- normalize_accounts(evidence, asof)
- normalize_orders(evidence, asof)
- normalize_fills(evidence, asof)
- normalize_positions(evidence, asof)
- normalize_transactions(evidence, asof)

Provider access and token ownership remain outside evidence adapters and the
current runtime. Unsupported ingestion capabilities must fail clearly or
return an explicit empty result with a reason.

## Provider Connector Boundary

In the target architecture, isolated OneJournal provider connectors acquire
evidence from Schwab, IBKR, Moomoo, and later providers. These are capability
categories, not approved implementation signatures:

- accounts
- orders and fills
- positions
- transactions
- market quotes
- market hours and trading schedules

Provider connectors own provider-specific authentication, request construction,
rate-limit handling, and immutable raw capture. Evidence adapters own
normalization. Journal, lifecycle, financial, portfolio, and UI code must use
only broker-independent contracts and must not receive provider credentials or
parse provider payloads.

Before persistence, every connector/adapter result must cross the versioned
provider-neutral quote-capture envelope. It binds the exact provider-instrument
to OneJournal-instrument request scope, provider/connection identity, quote,
receive, and evaluation times, New York market date, checksum-backed local
source locator, adapter version, and complete normalized quote set. Partial or
identity-mismatched batches fail before accepted quote rows are written.

For restart-safe local ingestion, the immutable private capture directory also
contains a deterministic provider-neutral envelope artifact. Its SHA-256 is
bound by the private manifest separately from the raw-response SHA-256. The
durable ingestion operator reloads both, validates their exact identity and
request scope, persists the capture transactionally, and reads back only the
same provider, connection, run UID, and market date. Raw response bytes never
enter DuckDB. An identical replay is accepted; changed or incomplete lineage
fails closed.

Quote freshness may consume a separate provider-neutral market-session
observation normalized from the same connected broker as the quote. The raw
provider evidence may come from a quote, market-hours, trading-schedule, or
instrument response, but broker-specific payloads do not cross the adapter
boundary. The normalized observation is not persisted as a permanent property
of a quote. It binds provider, opaque connection, provider instrument,
broker-independent instrument, provider-declared schedule scope, IANA venue
timezone, market date, session phase, half-open phase window, trading-day kind
(`regular`, `early_close`, `holiday`, or `unscheduled_closure`), source lineage,
validity window, and deterministic identity. A MIC is retained only when the
provider supplies it or an approved mapping proves it; OneJournal does not
guess one.

Missing or invalid authority cannot replace an unknown provider session. When
supplied, its provider, connection, instrument, and evaluation instant must
exactly match the quote assessment; its own market date must match that instant
in the declared venue timezone. Provider and authority sessions are compared
only when the authority phase window covers the provider quote instant, so a
regular quote retained into a later closed phase is not misclassified as a
conflict. Same-phase conflicts, expired observations, unsupported states, or
identity/timezone/date/window mismatches make freshness unavailable. No other
broker, third-party calendar, weekday rule, or clock inference may supply a
fallback.

A freshness assessment records quote-time and evaluation-time sessions
separately and whether each came from the quote response, the same-provider
schedule authority, or both. These are point-in-time assessment facts, not
permanent properties of the stored quote. The legacy `v1` authority object is
not sufficient because it lacks provider/connection binding and requires an
exact MIC. `onejournal.provider-market-session-authority.v2` implements the
replacement value, exact binding, freshness integration, and credential-free
importer injection seam defined in
`docs/provider_native_market_session_contract.md`. The concrete Schwab
market-hours adapter and resolver are accepted only for the bounded local T16
bridge evidence and are not a continuous provider runtime. No IBKR or Moomoo
schedule adapter is implemented or accepted.

The current runtime does not implement this provider-connection plane. Its
credential storage, user/connection identity, tenancy, scheduling, deployment,
and single-owner cutover require separate decisions and approvals. When the
Schwab connector is activated, OneBot's temporary Schwab access must be retired
before OneJournal becomes the token owner; both projects must not refresh the
same token lifecycle.

## Minimum Normalized Records

- NormalizedAccount
- NormalizedOrder
- NormalizedFill
- NormalizedPosition
- NormalizedTransaction
- NormalizedQuote
- BrokerPositionSnapshot (PNL-03 implemented as a credential-free complete
  account envelope; no provider adapter or real evidence accepted yet)
- CanonicalOpenPosition (PNL-03 implemented as a cumulative FIFO/lifecycle
  result in the isolated service boundary)
- ValuationMarkAssessment (PNL-03 implemented as a quote-bound selected mark
  with freshness/session and reconciliation lineage)
- TradeEpisode
- TradeLeg
- JournalEntry
- TradeTag
- RiskEvent

All normalized records should include source_broker, source_account_id, source_record_id where applicable, asof, fetched_at, normalized_at, and raw_path.

### PNL-03 authority boundary

ADR-0019 is accepted policy for canonical position and valuation authority.
Migration 0013 and its repository are implemented and validated only against
temporary DuckDB databases; no actual journal migration or dashboard/API
contract change is accepted. The existing
`NormalizedPosition` and `normalized_positions` records are prototype/import
diagnostic rows and cannot establish PNL-03 current position, cost basis,
market value, unrealized P&L, or portfolio totals.

The isolated PNL-03 service now binds every supported current valuation
to all of the following: one `onejournal.instrument-identity.v1`, cumulative
accepted fills/lifecycle events through an exact UTC evaluation instant, an
independent complete broker-position snapshot, one exact provider/connection
quote and PNL-02 freshness assessment, mark-selection policy/version, native
currency, calculation/input lineage, status, and failure reason where
unavailable. Active-session marks use long bid/short ask; eligible
`market_closed_last` uses exact last. Missing, stale, mismatched, partial, or
unreconciled evidence is unavailable, never zero. A multi-leg strategy total
requires every included leg to satisfy the same boundary.

`schwab-position-json-v1` now supplies the isolated credential-free Schwab
position intake. It accepts only exact, checksum-bound single-account
`fields=positions` evidence with explicit account and canonical instrument
mappings. It preserves broker figures as reconciliation evidence and makes no
provider call or database write. Synthetic compatibility tests pass; bounded
real evidence is still required before operational or financial acceptance.

## Dashboard Payload v1

Future dashboard payload: output/dashboard/latest/dashboard_payload.json

Minimum top-level sections:

- metadata
- metadata.quality
- trade_summary
- performance
- open_positions
- portfolio_snapshots
- recent_trade_episodes
- closed_trade_episodes
- metrics_by_strategy
- risk_events
- journal_review_queue

### Governance and conformance boundary

- ADR-0003 is accepted for currency, precision/rounding, instant, market-date,
  display-timezone, and session policy. Financial acceptance still requires
  evidence that the applicable implementation path conforms.
- ADR-0007 is accepted policy, not proof that this v1 contract or current
  payload implementation conforms.
- Current payload paths do not yet provide processed/unavailable counts and an
  omission reason for every affected scope, separate every partial subtotal
  from its unavailable consolidated total, or remove every implicit USD/zero
  fallback.
- PNL-08 therefore remains blocked. A later versioned payload change must update
  producers, validators, consumers, tests, and presentation atomically; absent
  future fields must not be interpreted as `valid`.

## Portfolio Snapshot V1

- A `portfolio_snapshots` section appears in dashboard payloads that support
  account-level aggregate reporting.
- Each snapshot includes:
  - `source_broker`, `source_account_id`, `currency`
  - `position_count`
  - `market_value`
  - `cost_basis`
  - `realized_pnl`
  - `unrealized_pnl` (must be `null` when any included position has missing mark freshness)
  - `asof` (latest included position as-of date)
  - `fetched_at` (latest included position fetch timestamp)

The section is reproducible by requested as-of date by selecting the latest
normalized position snapshot per position identity where `position.asof_date <= requested_asof`.
- Closed positions with zero quantity are intentionally omitted from this section.

## Metrics v1

- realized_pnl
- unrealized_pnl
- win_rate
- profit_factor
- average_win
- average_loss
- average_days_in_trade
- trade_count
- assignment_count
- risk_event_count
- pnl_by_strategy
- pnl_by_symbol

Profit factor definition: gross_profit / absolute_gross_loss.

If there are no losses, profit factor must be shown as null or not_applicable, not infinity.

## Performance section v1

- `performance` appears as a dedicated top-level section.
- `performance.currency` includes:
  - `total_realized_pnl_by_currency`
  - `total_unrealized_pnl_by_currency` (can be `null` when mark freshness is missing)
  - `total_pnl_by_currency` (computed only when both sides are available)
  - `exposure_by_currency`
- `performance.trade_counts` includes:
  - `closed_trades`
  - `total_scope_groups`
- `performance.returns_by_currency` is present and explicit about denominator/benchmark
  availability; when policy is blocked it is not silently numeric.
- `performance.breakdowns` includes:
  - `by_account`
  - `by_broker`
  - `by_symbol`
  - `by_asset_class`
  - `by_strategy`
  - `by_period` (blocked until PNL-07 reporting scope is complete)

When mark data is unavailable, unrealized and total-PnL fields must be `null`, not zero.

## Validation Principles

Every pipeline stage should be able to answer:

- What did it read?
- Where did it read from?
- What asof date did it use?
- How many records did it process?
- What did it write?
- Where did it write to?
- What failed and why?

## Phase Order

- Phase 0 = project skeleton and validation helper
- Phase 1 = data contract and broker-independent model
- Phase 2 = manual CSV/import adapter
- Phase 3 = dashboard payload builder
- Phase 4 = Streamlit dashboard v1
- Phase 5 = Schwab read-only adapter
- Phase 6 = IBKR read-only adapter
- Phase 7 = reconciliation and review workflow
- Phase 8+ = paper/live execution discussion, not active scope

## Non-Negotiables

- No auto-trade in v1.
- No broker-specific logic in dashboard.
- No heavy computation in UI layer.
- No duplicate date flags.
- No raw broker payloads committed to Git.
- No private local env files committed to Git.
- No dashboard number without traceability to source data.
## Phase I1 normalized fills ODFS rule

CSV is the import and transport layer. DuckDB is the journal source of truth.

Raw broker or manual files stay under data/raw/ as evidence.

Canonical normalized fill exports use the same column contract as docs/examples/manual_csv/fills_template.csv.

Imported fills live in DuckDB normalized_fills.

Import audit records live in DuckDB import_runs.

Dashboard payload files are generated outputs, not source data.
