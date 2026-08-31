-- Migration 0013: add PNL-03 canonical position and valuation authority.
-- Related contracts: ADR-0003, ADR-0004, ADR-0007, ADR-0009, and ADR-0019.
-- Legacy normalized_positions rows remain unchanged and non-authoritative.

CREATE TABLE broker_position_snapshot_runs (
    snapshot_uid VARCHAR PRIMARY KEY,
    provider VARCHAR NOT NULL,
    connection_uid VARCHAR NOT NULL,
    source_account_id VARCHAR NOT NULL,
    asof_date DATE NOT NULL,
    retrieved_at_utc VARCHAR NOT NULL,
    provider_observed_at_utc VARCHAR,
    account_complete BOOLEAN NOT NULL,
    source_locator VARCHAR NOT NULL,
    source_raw_sha256 VARCHAR NOT NULL,
    adapter_version VARCHAR NOT NULL,
    snapshot_fingerprint VARCHAR NOT NULL,
    position_count INTEGER NOT NULL,
    status VARCHAR NOT NULL
);

CREATE INDEX idx_broker_position_snapshot_scope
  ON broker_position_snapshot_runs (
    provider, connection_uid, source_account_id, asof_date, retrieved_at_utc
  );

CREATE TABLE broker_position_snapshot_records (
    snapshot_uid VARCHAR NOT NULL,
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
    provider_position_id VARCHAR,
    quantity DECIMAL(38, 10) NOT NULL,
    broker_average_cost DECIMAL(38, 10),
    broker_market_value DECIMAL(38, 10),
    broker_unrealized_pnl DECIMAL(38, 10),
    PRIMARY KEY (snapshot_uid, instrument_key)
);

CREATE TABLE pnl_position_valuation_runs (
    valuation_run_uid VARCHAR PRIMARY KEY,
    snapshot_uid VARCHAR NOT NULL,
    source_broker VARCHAR NOT NULL,
    connection_uid VARCHAR NOT NULL,
    source_account_id VARCHAR NOT NULL,
    asof_date DATE NOT NULL,
    evaluated_at_utc VARCHAR NOT NULL,
    calculation_version VARCHAR NOT NULL,
    input_fill_fingerprint VARCHAR NOT NULL,
    lifecycle_input_fingerprint VARCHAR NOT NULL,
    max_snapshot_age_seconds INTEGER NOT NULL,
    result_fingerprint VARCHAR NOT NULL,
    position_count INTEGER NOT NULL,
    valid_count INTEGER NOT NULL,
    unavailable_count INTEGER NOT NULL,
    reconciliation_pending_count INTEGER NOT NULL,
    status VARCHAR NOT NULL
);

CREATE INDEX idx_pnl_position_valuation_scope
  ON pnl_position_valuation_runs (
    source_broker, connection_uid, source_account_id, asof_date,
    evaluated_at_utc, status
  );

CREATE TABLE pnl_canonical_position_valuations (
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
    legacy_instrument_key VARCHAR,
    direction VARCHAR,
    canonical_quantity DECIMAL(38, 10),
    broker_quantity DECIMAL(38, 10),
    open_cost_basis DECIMAL(38, 10),
    reconciliation_status VARCHAR NOT NULL,
    reconciliation_reason VARCHAR,
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
    status_reason VARCHAR,
    PRIMARY KEY (valuation_run_uid, instrument_key)
);
