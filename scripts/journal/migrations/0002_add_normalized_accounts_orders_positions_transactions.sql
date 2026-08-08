-- Migration 0002: add normalized account/order/position/transaction tables.
-- Purpose: JRN-02 foundational coverage for all broker-normalized record families
-- to support multi-broker extension (including IBKR) without schema churn.
--
-- Start state:
--   - Baseline schema from 0001 is present.
--   - migration ledger exists and is valid.
--
-- Expected effect:
--   - create all normalized record tables with source lineage to import_runs.
--   - ensure primary keys and required identifiers are present.
--
-- Rollback strategy:
--   - forward corrective migration only; no down-migration available.

CREATE TABLE normalized_accounts (
    account_uid VARCHAR PRIMARY KEY,
    source_broker VARCHAR NOT NULL,
    source_account_id VARCHAR NOT NULL,
    account_label VARCHAR NOT NULL,
    account_type VARCHAR NOT NULL,
    currency VARCHAR NOT NULL,
    asof_date DATE NOT NULL,
    fetched_at TIMESTAMP NOT NULL,
    raw_path VARCHAR,
    buying_power DECIMAL(38, 10),
    cash_balance DECIMAL(38, 10),
    net_liquidation_value DECIMAL(38, 10),
    maintenance_requirement DECIMAL(38, 10),
    initial_requirement DECIMAL(38, 10),
    day_trade_buying_power DECIMAL(38, 10),
    status VARCHAR,
    import_run_id VARCHAR,
    CONSTRAINT fk_normalized_accounts_import_run
      FOREIGN KEY (import_run_id)
      REFERENCES import_runs (import_run_id)
);

CREATE TABLE normalized_orders (
    order_uid VARCHAR PRIMARY KEY,
    source_broker VARCHAR NOT NULL,
    source_account_id VARCHAR NOT NULL,
    source_order_id VARCHAR NOT NULL,
    asof_date DATE NOT NULL,
    order_status VARCHAR NOT NULL,
    order_type VARCHAR NOT NULL,
    time_in_force VARCHAR NOT NULL,
    asset_class VARCHAR NOT NULL,
    symbol VARCHAR NOT NULL,
    side VARCHAR NOT NULL,
    quantity DECIMAL(38, 10) NOT NULL,
    created_at TIMESTAMP NOT NULL,
    fetched_at TIMESTAMP NOT NULL,
    raw_path VARCHAR,
    limit_price DECIMAL(38, 10),
    stop_price DECIMAL(38, 10),
    filled_quantity DECIMAL(38, 10),
    remaining_quantity DECIMAL(38, 10),
    average_fill_price DECIMAL(38, 10),
    cancelled_at TIMESTAMP,
    replaced_by_order_id VARCHAR,
    parent_order_id VARCHAR,
    broker_strategy_type VARCHAR,
    notes VARCHAR,
    import_run_id VARCHAR,
    CONSTRAINT fk_normalized_orders_import_run
      FOREIGN KEY (import_run_id)
      REFERENCES import_runs (import_run_id)
);

CREATE TABLE normalized_positions (
    position_uid VARCHAR PRIMARY KEY,
    source_broker VARCHAR NOT NULL,
    source_account_id VARCHAR NOT NULL,
    asof_date DATE NOT NULL,
    asset_class VARCHAR NOT NULL,
    symbol VARCHAR NOT NULL,
    quantity DECIMAL(38, 10) NOT NULL,
    average_cost DECIMAL(38, 10) NOT NULL,
    market_price DECIMAL(38, 10) NOT NULL,
    market_value DECIMAL(38, 10) NOT NULL,
    currency VARCHAR NOT NULL,
    fetched_at TIMESTAMP NOT NULL,
    raw_path VARCHAR,
    unrealized_pnl DECIMAL(38, 10),
    realized_pnl DECIMAL(38, 10),
    delta DECIMAL(38, 10),
    beta_weighted_delta DECIMAL(38, 10),
    option_symbol VARCHAR,
    underlying_symbol VARCHAR,
    option_type VARCHAR,
    expiry DATE,
    strike DECIMAL(38, 10),
    multiplier DECIMAL(38, 10),
    import_run_id VARCHAR,
    CONSTRAINT fk_normalized_positions_import_run
      FOREIGN KEY (import_run_id)
      REFERENCES import_runs (import_run_id)
);

CREATE TABLE normalized_transactions (
    transaction_uid VARCHAR PRIMARY KEY,
    source_broker VARCHAR NOT NULL,
    source_account_id VARCHAR NOT NULL,
    source_transaction_id VARCHAR NOT NULL,
    asof_date DATE NOT NULL,
    transaction_at TIMESTAMP NOT NULL,
    transaction_type VARCHAR NOT NULL,
    amount DECIMAL(38, 10) NOT NULL,
    currency VARCHAR NOT NULL,
    fetched_at TIMESTAMP NOT NULL,
    raw_path VARCHAR,
    symbol VARCHAR,
    asset_class VARCHAR,
    quantity DECIMAL(38, 10),
    price DECIMAL(38, 10),
    commission DECIMAL(38, 10),
    fees DECIMAL(38, 10),
    description VARCHAR,
    linked_order_id VARCHAR,
    linked_fill_id VARCHAR,
    import_run_id VARCHAR,
    CONSTRAINT fk_normalized_transactions_import_run
      FOREIGN KEY (import_run_id)
      REFERENCES import_runs (import_run_id)
);
