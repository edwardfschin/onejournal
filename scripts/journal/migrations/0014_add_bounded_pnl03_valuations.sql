-- Migration 0014: persist the bounded, fail-closed ADR-0022 PNL-03 route.
-- Expected predecessor: migration 0013.
-- This is additive. It does not reinterpret generic 0013 valuation rows and
-- contains no private evidence or account-specific values.

CREATE TABLE pnl_bounded_valuation_runs (
    valuation_run_uid VARCHAR PRIMARY KEY,
    contract_version VARCHAR NOT NULL,
    route_version VARCHAR NOT NULL,
    reconciliation_run_uid VARCHAR NOT NULL,
    binding_sha256 VARCHAR NOT NULL,
    snapshot_uid VARCHAR NOT NULL,
    assembly_sha256 VARCHAR NOT NULL,
    source_broker VARCHAR NOT NULL,
    connection_uid VARCHAR NOT NULL,
    source_account_id VARCHAR NOT NULL,
    asof_date DATE NOT NULL,
    evaluated_at_utc VARCHAR NOT NULL,
    calculation_version VARCHAR NOT NULL,
    fill_fingerprint VARCHAR NOT NULL,
    quote_evidence_sha256 VARCHAR NOT NULL,
    quote_scope_sha256 VARCHAR NOT NULL,
    max_reconciliation_age_seconds INTEGER NOT NULL,
    reconciliation_age_seconds DECIMAL(38, 10) NOT NULL,
    complete_position_count INTEGER NOT NULL,
    eligible_count INTEGER NOT NULL,
    valid_mark_count INTEGER NOT NULL,
    mark_unavailable_count INTEGER NOT NULL,
    unavailable_count INTEGER NOT NULL,
    subtotal_status VARCHAR NOT NULL,
    complete_portfolio_totals_available BOOLEAN NOT NULL,
    financial_acceptance BOOLEAN NOT NULL,
    result_fingerprint VARCHAR NOT NULL,
    final_status VARCHAR NOT NULL
);

CREATE INDEX idx_pnl_bounded_valuation_scope
  ON pnl_bounded_valuation_runs (
    source_broker, connection_uid, source_account_id, asof_date,
    evaluated_at_utc, route_version, final_status
  );

CREATE TABLE pnl_bounded_position_valuations (
    valuation_run_uid VARCHAR NOT NULL,
    instrument_key VARCHAR NOT NULL,
    asset_class VARCHAR NOT NULL,
    market_scope VARCHAR NOT NULL,
    currency VARCHAR NOT NULL,
    symbol VARCHAR,
    underlying_symbol VARCHAR,
    expiry DATE,
    option_right VARCHAR,
    strike DECIMAL(38, 10),
    multiplier DECIMAL(38, 10),
    coverage_status VARCHAR NOT NULL,
    broker_quantity DECIMAL(38, 10) NOT NULL,
    reconciliation_status VARCHAR NOT NULL,
    canonical_quantity DECIMAL(38, 10),
    open_cost_basis DECIMAL(38, 10),
    quote_uid VARCHAR,
    freshness_status VARCHAR,
    freshness_age_seconds DECIMAL(38, 10),
    quote_market_session VARCHAR,
    evaluation_market_session VARCHAR,
    session_authority_uid VARCHAR,
    mark_policy_version VARCHAR,
    selected_price_field VARCHAR,
    mark_price DECIMAL(38, 10),
    market_value DECIMAL(38, 10),
    unrealized_pnl DECIMAL(38, 10),
    position_status VARCHAR NOT NULL,
    reason_codes_json VARCHAR NOT NULL,
    PRIMARY KEY (valuation_run_uid, instrument_key)
);

CREATE TABLE pnl_bounded_valuation_subtotals (
    valuation_run_uid VARCHAR NOT NULL,
    currency VARCHAR NOT NULL,
    eligible_cost_basis DECIMAL(38, 10) NOT NULL,
    eligible_market_value DECIMAL(38, 10),
    eligible_unrealized_pnl DECIMAL(38, 10),
    subtotal_status VARCHAR NOT NULL,
    PRIMARY KEY (valuation_run_uid, currency)
);
