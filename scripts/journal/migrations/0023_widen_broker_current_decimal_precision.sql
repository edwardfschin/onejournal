-- Migration 0023: preserve accepted broker-current values through 13 decimals.
-- Expected predecessor: migration 0022.
--
-- The accepted WEB-W07 broker-current result contains exact values with up to
-- 13 fractional digits. Migration 0015 used DECIMAL(38, 10), which silently
-- rounded those values during persistence. These targeted type changes retain
-- 25 integer digits while preserving the complete accepted fractional scope.

ALTER TABLE broker_position_snapshot_records
ALTER COLUMN broker_average_cost SET DATA TYPE DECIMAL(38, 13);

ALTER TABLE broker_position_snapshot_records
ALTER COLUMN broker_unrealized_pnl SET DATA TYPE DECIMAL(38, 13);

ALTER TABLE broker_position_snapshot_records
ALTER COLUMN broker_tax_lot_average_price SET DATA TYPE DECIMAL(38, 13);

ALTER TABLE pnl_broker_current_position_valuations
ALTER COLUMN tax_lot_average_price SET DATA TYPE DECIMAL(38, 13);

ALTER TABLE pnl_broker_current_position_valuations
ALTER COLUMN open_cost_basis SET DATA TYPE DECIMAL(38, 13);

ALTER TABLE pnl_broker_current_position_valuations
ALTER COLUMN broker_reported_unrealized_pnl SET DATA TYPE DECIMAL(38, 13);

ALTER TABLE pnl_broker_current_position_valuations
ALTER COLUMN unrealized_pnl SET DATA TYPE DECIMAL(38, 13);

ALTER TABLE pnl_broker_current_position_valuations
ALTER COLUMN unrealized_reconciliation_difference SET DATA TYPE DECIMAL(38, 13);

ALTER TABLE pnl_broker_current_portfolio_totals
ALTER COLUMN portfolio_cost_basis SET DATA TYPE DECIMAL(38, 13);

ALTER TABLE pnl_broker_current_portfolio_totals
ALTER COLUMN portfolio_unrealized_pnl SET DATA TYPE DECIMAL(38, 13);
