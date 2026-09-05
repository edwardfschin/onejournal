-- Migration 0015: persist ADR-0023 broker-current position valuations.
-- Expected predecessor: migration 0014.
-- This is additive and does not reinterpret FIFO valuation history.

ALTER TABLE broker_position_snapshot_records
ADD COLUMN broker_tax_lot_average_price DECIMAL(38, 10);

CREATE TABLE pnl_broker_current_valuation_runs (
    valuation_run_uid VARCHAR PRIMARY KEY,
    contract_version VARCHAR NOT NULL,
    basis_method VARCHAR NOT NULL,
    snapshot_uid VARCHAR NOT NULL,
    source_broker VARCHAR NOT NULL,
    connection_uid VARCHAR NOT NULL,
    source_account_id VARCHAR NOT NULL,
    asof_date DATE NOT NULL,
    retrieved_at_utc VARCHAR NOT NULL,
    evaluated_at_utc VARCHAR NOT NULL,
    max_snapshot_age_seconds INTEGER NOT NULL,
    snapshot_age_seconds DECIMAL(38, 10) NOT NULL,
    currency_quantum_json VARCHAR NOT NULL,
    position_count INTEGER NOT NULL,
    cost_basis_available_count INTEGER NOT NULL,
    market_value_available_count INTEGER NOT NULL,
    unrealized_pnl_available_count INTEGER NOT NULL,
    complete_portfolio_cost_basis_available BOOLEAN NOT NULL,
    complete_portfolio_market_value_available BOOLEAN NOT NULL,
    complete_portfolio_unrealized_pnl_available BOOLEAN NOT NULL,
    financial_acceptance BOOLEAN NOT NULL,
    result_fingerprint VARCHAR NOT NULL,
    final_status VARCHAR NOT NULL
);

CREATE INDEX idx_pnl_broker_current_valuation_scope
  ON pnl_broker_current_valuation_runs (
    source_broker, connection_uid, source_account_id, asof_date,
    evaluated_at_utc, final_status
  );

CREATE TABLE pnl_broker_current_position_valuations (
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
    quantity DECIMAL(38, 10) NOT NULL,
    tax_lot_average_price DECIMAL(38, 10),
    open_cost_basis DECIMAL(38, 10),
    broker_market_value DECIMAL(38, 10),
    broker_reported_unrealized_pnl DECIMAL(38, 10),
    unrealized_pnl DECIMAL(38, 10),
    unrealized_reconciliation_difference DECIMAL(38, 10),
    cost_basis_status VARCHAR NOT NULL,
    market_value_status VARCHAR NOT NULL,
    unrealized_pnl_status VARCHAR NOT NULL,
    position_status VARCHAR NOT NULL,
    reason_codes_json VARCHAR NOT NULL,
    PRIMARY KEY (valuation_run_uid, instrument_key)
);

CREATE TABLE pnl_broker_current_portfolio_totals (
    valuation_run_uid VARCHAR NOT NULL,
    currency VARCHAR NOT NULL,
    portfolio_cost_basis DECIMAL(38, 10),
    portfolio_market_value DECIMAL(38, 10),
    portfolio_unrealized_pnl DECIMAL(38, 10),
    PRIMARY KEY (valuation_run_uid, currency)
);
