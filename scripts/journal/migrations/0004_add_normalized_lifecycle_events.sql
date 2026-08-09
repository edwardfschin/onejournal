-- Migration 0004: add normalized lifecycle event ledger.
-- Purpose: JRN-05 persistence support for broker lifecycle-only events.
--
-- Start state:
--   - Migration version 0003 is applied.
--
-- Expected effect:
--   - add append-only `normalized_lifecycle_events` with import lineage.
--   - support future lifecycle-engine expansion and audit of assignment/exercise/
--    expiration/dividend/roll/corporate-action/interest transfer events.
--
-- Rollback strategy:
--   - forward corrective migration only; no down-migration available.

CREATE TABLE normalized_lifecycle_events (
    event_uid VARCHAR PRIMARY KEY,
    source_broker VARCHAR NOT NULL,
    source_account_id VARCHAR NOT NULL,
    source_activity_id VARCHAR,
    source_order_id VARCHAR,
    source_position_id VARCHAR,
    event_class VARCHAR NOT NULL,
    event_type VARCHAR NOT NULL,
    asof_date DATE NOT NULL,
    event_at TIMESTAMP NOT NULL,
    event_name VARCHAR,
    raw_path VARCHAR,
    import_run_id VARCHAR
);

CREATE INDEX idx_normalized_lifecycle_events_asof
  ON normalized_lifecycle_events (asof_date);

CREATE INDEX idx_normalized_lifecycle_events_broker_account
  ON normalized_lifecycle_events (source_broker, source_account_id);

CREATE INDEX idx_normalized_lifecycle_events_import_run_id
  ON normalized_lifecycle_events (import_run_id);
