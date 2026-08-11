-- Migration 0010: add approved option-lifecycle instructions and versioned P&L runs.
-- Related contracts: accepted ADR-0003, ADR-0004, and ADR-0005.
--
-- Reviewed lifecycle instructions remain separate from raw/normalized
-- evidence. Calculation runs and allocation rows are append-only and
-- versioned. No raw evidence, fill, lifecycle event, or prior result is
-- rewritten.

CREATE TABLE approved_option_lifecycle_events (
    event_uid VARCHAR PRIMARY KEY,
    event_type VARCHAR NOT NULL,
    source_broker VARCHAR NOT NULL,
    source_account_id VARCHAR NOT NULL,
    currency VARCHAR NOT NULL,
    effective_at_utc VARCHAR NOT NULL,
    option_instrument_key VARCHAR NOT NULL,
    predecessor_direction VARCHAR NOT NULL,
    contracts DECIMAL(38, 10) NOT NULL,
    event_commission DECIMAL(38, 10) NOT NULL,
    event_fees DECIMAL(38, 10) NOT NULL,
    evidence_status VARCHAR NOT NULL,
    successor_action VARCHAR,
    successor_position_effect VARCHAR,
    successor_symbol VARCHAR,
    successor_quantity DECIMAL(38, 10),
    strike_cash_amount DECIMAL(38, 10),
    reviewed_at_utc VARCHAR NOT NULL,
    review_source VARCHAR NOT NULL,
    instruction_path VARCHAR NOT NULL
);

CREATE TABLE approved_option_lifecycle_predecessors (
    event_uid VARCHAR NOT NULL,
    predecessor_index INTEGER NOT NULL,
    open_fill_uid VARCHAR NOT NULL,
    PRIMARY KEY (event_uid, predecessor_index)
);

CREATE INDEX idx_approved_option_lifecycle_predecessor_fill
  ON approved_option_lifecycle_predecessors (open_fill_uid);

CREATE TABLE approved_option_lifecycle_source_legs (
    event_uid VARCHAR NOT NULL,
    event_leg_uid VARCHAR NOT NULL,
    PRIMARY KEY (event_uid, event_leg_uid)
);

CREATE TABLE pnl_calculation_runs (
    calculation_run_id VARCHAR PRIMARY KEY,
    calculation_version VARCHAR NOT NULL,
    lifecycle_calculation_version VARCHAR NOT NULL,
    asof_date DATE NOT NULL,
    started_at_utc VARCHAR NOT NULL,
    completed_at_utc VARCHAR,
    input_fill_fingerprint VARCHAR NOT NULL,
    approved_event_fingerprint VARCHAR NOT NULL,
    fill_count INTEGER NOT NULL,
    approved_event_count INTEGER NOT NULL,
    group_count INTEGER NOT NULL,
    closed_allocation_count INTEGER NOT NULL,
    lifecycle_allocation_count INTEGER NOT NULL,
    status VARCHAR NOT NULL,
    notes VARCHAR
);

CREATE INDEX idx_pnl_calculation_runs_asof_status
  ON pnl_calculation_runs (asof_date, status);

CREATE TABLE pnl_group_results (
    calculation_run_id VARCHAR NOT NULL,
    source_broker VARCHAR NOT NULL,
    source_account_id VARCHAR NOT NULL,
    instrument_key VARCHAR NOT NULL,
    currency VARCHAR NOT NULL,
    open_quantity DECIMAL(38, 10) NOT NULL,
    open_cost_basis DECIMAL(38, 10) NOT NULL,
    realized_pnl DECIMAL(38, 10) NOT NULL,
    unrealized_pnl DECIMAL(38, 10),
    PRIMARY KEY (
        calculation_run_id,
        source_broker,
        source_account_id,
        instrument_key,
        currency
    )
);

CREATE TABLE pnl_closed_lot_allocations (
    calculation_run_id VARCHAR NOT NULL,
    allocation_index INTEGER NOT NULL,
    source_broker VARCHAR NOT NULL,
    source_account_id VARCHAR NOT NULL,
    instrument_key VARCHAR NOT NULL,
    currency VARCHAR NOT NULL,
    open_fill_uid VARCHAR NOT NULL,
    close_fill_uid VARCHAR NOT NULL,
    source_event_uid VARCHAR,
    direction VARCHAR NOT NULL,
    quantity DECIMAL(38, 10) NOT NULL,
    multiplier DECIMAL(38, 10) NOT NULL,
    open_price DECIMAL(38, 10) NOT NULL,
    close_price DECIMAL(38, 10) NOT NULL,
    gross_realized_pnl DECIMAL(38, 10) NOT NULL,
    allocated_open_commission DECIMAL(38, 10) NOT NULL,
    allocated_open_fees DECIMAL(38, 10) NOT NULL,
    allocated_close_commission DECIMAL(38, 10) NOT NULL,
    allocated_close_fees DECIMAL(38, 10) NOT NULL,
    realized_pnl DECIMAL(38, 10) NOT NULL,
    closed_at_utc VARCHAR NOT NULL,
    PRIMARY KEY (calculation_run_id, allocation_index)
);

CREATE INDEX idx_pnl_closed_lot_event
  ON pnl_closed_lot_allocations (source_event_uid);

CREATE TABLE pnl_lifecycle_allocations (
    calculation_run_id VARCHAR NOT NULL,
    event_uid VARCHAR NOT NULL,
    allocation_index INTEGER NOT NULL,
    calculation_version VARCHAR NOT NULL,
    source_broker VARCHAR NOT NULL,
    source_account_id VARCHAR NOT NULL,
    option_instrument_key VARCHAR NOT NULL,
    currency VARCHAR NOT NULL,
    predecessor_open_fill_uid VARCHAR NOT NULL,
    predecessor_direction VARCHAR NOT NULL,
    contracts DECIMAL(38, 10) NOT NULL,
    multiplier DECIMAL(38, 10) NOT NULL,
    net_option_basis DECIMAL(38, 10) NOT NULL,
    allocated_open_commission DECIMAL(38, 10) NOT NULL,
    allocated_open_fees DECIMAL(38, 10) NOT NULL,
    allocated_event_commission DECIMAL(38, 10) NOT NULL,
    allocated_event_fees DECIMAL(38, 10) NOT NULL,
    realized_pnl DECIMAL(38, 10) NOT NULL,
    successor_fill_uid VARCHAR,
    successor_action VARCHAR,
    successor_position_effect VARCHAR,
    successor_symbol VARCHAR,
    successor_quantity DECIMAL(38, 10),
    successor_effective_price DECIMAL(38, 10),
    effective_at_utc VARCHAR NOT NULL,
    source_event_leg_uids_json VARCHAR NOT NULL,
    PRIMARY KEY (calculation_run_id, event_uid, allocation_index)
);

CREATE INDEX idx_pnl_lifecycle_allocations_event
  ON pnl_lifecycle_allocations (event_uid);
