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
- Rotating broker session files: ~/.onejournal/tokens/

Broker credentials and environment keys are application-scoped. The Schwab
raw-history fetcher uses only `ONEJOURNAL_SCHWAB_*` configuration and its
OneJournal token path; it must reject generic/OneBot credential configuration.

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

## Minimum Adapter Interface

Each broker/import adapter should eventually support read-only methods:

- fetch_accounts(asof)
- fetch_orders(asof)
- fetch_fills(asof)
- fetch_positions(asof)
- fetch_transactions(asof)

Unsupported methods must fail clearly or return an explicit empty result with a reason.

## Minimum Normalized Records

- NormalizedAccount
- NormalizedOrder
- NormalizedFill
- NormalizedPosition
- NormalizedTransaction
- TradeEpisode
- TradeLeg
- JournalEntry
- TradeTag
- RiskEvent

All normalized records should include source_broker, source_account_id, source_record_id where applicable, asof, fetched_at, normalized_at, and raw_path.

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
