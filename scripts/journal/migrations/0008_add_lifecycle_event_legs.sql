-- Migration 0008: add lifecycle-event economic evidence legs.
-- Related contracts: ADR-0003, ADR-0004, and accepted ADR-0005.
--
-- Start state:
--   - Migration version 0007 is applied.
--   - normalized_lifecycle_events contains immutable event headers.
--
-- Expected effect:
--   - add normalized_lifecycle_event_legs as an additive child evidence table.
--   - preserve signed quantity, price, cash, option terms, deliverables, and
--     structural evidence status without calculating or inferring P&L.
--   - existing event and journal rows remain unchanged.
--
-- Producer/consumer impact:
--   - Schwab transaction conversion may emit a separate event-leg CSV.
--   - the journal importer may persist those rows with import lineage.
--   - health and audit checks validate identity and event/import linkage.
--
-- Failure and rollback:
--   - the migration runner applies this file in one transaction.
--   - no destructive down migration is provided; restore a verified pre-
--     migration backup before post-migration writes, or use a reviewed forward
--     corrective migration.

CREATE TABLE normalized_lifecycle_event_legs (
    event_leg_uid VARCHAR PRIMARY KEY,
    event_uid VARCHAR NOT NULL,
    leg_index INTEGER NOT NULL,
    leg_kind VARCHAR NOT NULL,
    asset_class VARCHAR,
    symbol VARCHAR,
    option_symbol VARCHAR,
    underlying_symbol VARCHAR,
    option_type VARCHAR,
    expiry DATE,
    strike DECIMAL(38, 10),
    multiplier DECIMAL(38, 10),
    signed_quantity DECIMAL(38, 10),
    price DECIMAL(38, 10),
    cash_amount DECIMAL(38, 10),
    position_effect VARCHAR,
    fee_type VARCHAR,
    currency VARCHAR,
    deliverable_json VARCHAR,
    evidence_status VARCHAR NOT NULL,
    evidence_notes VARCHAR,
    raw_path VARCHAR,
    import_run_id VARCHAR
);

CREATE INDEX idx_normalized_lifecycle_event_legs_event
  ON normalized_lifecycle_event_legs (event_uid);

CREATE INDEX idx_normalized_lifecycle_event_legs_import_run
  ON normalized_lifecycle_event_legs (import_run_id);
