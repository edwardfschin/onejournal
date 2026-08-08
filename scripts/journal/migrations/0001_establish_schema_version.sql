-- Migration 0001: establish schema version ledger.
-- Contract: baseline migration for JRN-01.

CREATE TABLE IF NOT EXISTS schema_migrations (
    version VARCHAR PRIMARY KEY,
    migration_name VARCHAR NOT NULL,
    file_checksum VARCHAR(64) NOT NULL,
    applied_at TIMESTAMP NOT NULL,
    application_version VARCHAR,
    git_revision VARCHAR,
    run_id VARCHAR NOT NULL,
    status VARCHAR NOT NULL
);
