-- Migration 0011: add provider-independent market quote evidence.
-- Related contracts: ADR-0004, ADR-0007, and ADR-0009.
--
-- Raw provider responses remain immutable under data/raw/<provider>/ and are
-- not stored in DuckDB. This migration records local source lineage and
-- normalized top-of-book evidence. Freshness is computed at read time because
-- it changes with the evaluation instant.

CREATE TABLE market_quote_ingestion_runs (
    quote_run_uid VARCHAR PRIMARY KEY,
    provider VARCHAR NOT NULL,
    connection_uid VARCHAR NOT NULL,
    asof_date DATE NOT NULL,
    started_at_utc VARCHAR NOT NULL,
    completed_at_utc VARCHAR NOT NULL,
    requested_instrument_count INTEGER NOT NULL,
    received_quote_count INTEGER NOT NULL,
    accepted_quote_count INTEGER NOT NULL,
    rejected_quote_count INTEGER NOT NULL,
    input_fingerprint VARCHAR NOT NULL,
    adapter_version VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    notes VARCHAR
);

CREATE INDEX idx_market_quote_runs_provider_asof
  ON market_quote_ingestion_runs (provider, connection_uid, asof_date, status);

CREATE TABLE normalized_market_quotes (
    quote_uid VARCHAR PRIMARY KEY,
    quote_run_uid VARCHAR NOT NULL,
    provider VARCHAR NOT NULL,
    connection_uid VARCHAR NOT NULL,
    instrument_key VARCHAR NOT NULL,
    provider_instrument_id VARCHAR NOT NULL,
    symbol VARCHAR NOT NULL,
    asset_class VARCHAR NOT NULL,
    currency VARCHAR NOT NULL,
    bid DECIMAL(38, 10),
    ask DECIMAL(38, 10),
    last_price DECIMAL(38, 10),
    provider_quote_at_utc VARCHAR NOT NULL,
    received_at_utc VARCHAR NOT NULL,
    market_session VARCHAR NOT NULL,
    data_mode VARCHAR NOT NULL,
    entitlement_status VARCHAR NOT NULL,
    asof_date DATE NOT NULL,
    raw_path VARCHAR NOT NULL,
    raw_sha256 VARCHAR NOT NULL,
    adapter_version VARCHAR NOT NULL
);

CREATE INDEX idx_normalized_market_quotes_latest
  ON normalized_market_quotes (
    provider,
    connection_uid,
    instrument_key,
    provider_quote_at_utc
  );

CREATE INDEX idx_normalized_market_quotes_run
  ON normalized_market_quotes (quote_run_uid);
