-- Migration 0012: add provider-neutral quote-capture envelope lineage.
-- Related contracts: ADR-0003, ADR-0007, and ADR-0009.
--
-- Existing migration-0011 rows remain valid legacy normalized-quote evidence.
-- New provider-neutral ingestion records bind the full request scope, immutable
-- source locator, receive/evaluation times, and versioned capture contract to
-- the existing input fingerprint.

ALTER TABLE market_quote_ingestion_runs
  ADD COLUMN ingestion_contract_version VARCHAR;

ALTER TABLE market_quote_ingestion_runs
  ADD COLUMN received_at_utc VARCHAR;

ALTER TABLE market_quote_ingestion_runs
  ADD COLUMN request_scope_json VARCHAR;

ALTER TABLE market_quote_ingestion_runs
  ADD COLUMN source_storage_kind VARCHAR;

ALTER TABLE market_quote_ingestion_runs
  ADD COLUMN source_locator VARCHAR;

ALTER TABLE market_quote_ingestion_runs
  ADD COLUMN source_raw_sha256 VARCHAR;
