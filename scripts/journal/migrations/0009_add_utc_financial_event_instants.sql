-- Migration 0009: add timezone-aware UTC evidence columns for P&L ordering.
-- Related contract: accepted ADR-0003.
--
-- Existing timezone-less values are not reinterpreted or backfilled. New
-- imports populate both the legacy compatibility column and the UTC evidence
-- column. A later evidence-backed backfill may resolve legacy NULL values.

ALTER TABLE normalized_fills
  ADD COLUMN filled_at_utc VARCHAR;

ALTER TABLE normalized_fills
  ADD COLUMN fetched_at_utc VARCHAR;

ALTER TABLE normalized_lifecycle_events
  ADD COLUMN event_at_utc VARCHAR;
