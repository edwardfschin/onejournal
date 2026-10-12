-- Additive activity evidence only. No fills, active histories or reports change.
CREATE TABLE historical_activity_import_runs (
    run_uid VARCHAR PRIMARY KEY,
    contract_version VARCHAR NOT NULL,
    source_broker VARCHAR NOT NULL,
    source_account_id VARCHAR NOT NULL,
    asof_date DATE NOT NULL,
    observed_at_utc VARCHAR NOT NULL,
    bundle_fingerprint VARCHAR NOT NULL,
    bundle_json VARCHAR NOT NULL,
    observation_count INTEGER NOT NULL,
    CHECK (contract_version = 'onejournal.historical-activity-evidence.v1'),
    CHECK (length(bundle_fingerprint) = 64 AND observation_count > 0)
);
CREATE TABLE historical_activity_documents (
    document_uid VARCHAR PRIMARY KEY,
    source_broker VARCHAR NOT NULL,
    source_account_id VARCHAR NOT NULL,
    source_kind VARCHAR NOT NULL,
    raw_sha256 VARCHAR NOT NULL,
    CHECK (length(raw_sha256) = 64)
);
CREATE TABLE historical_activity_observations (
    observation_uid VARCHAR PRIMARY KEY,
    document_uid VARCHAR NOT NULL REFERENCES historical_activity_documents(document_uid),
    source_locator VARCHAR NOT NULL,
    record_fingerprint VARCHAR NOT NULL,
    record_json VARCHAR NOT NULL,
    posting_date DATE,
    asof_date DATE,
    trade_date DATE,
    settlement_date DATE,
    occurred_at_utc VARCHAR,
    timestamp_kind VARCHAR NOT NULL,
    date_precision VARCHAR NOT NULL,
    provider_activity_id VARCHAR,
    UNIQUE (document_uid, source_locator),
    CHECK (length(record_fingerprint) = 64),
    CHECK (date_precision IN ('day', 'instant', 'unknown')),
    CHECK (timestamp_kind IN ('none', 'provider_transaction')),
    CHECK ((date_precision = 'instant' AND occurred_at_utc IS NOT NULL
            AND timestamp_kind = 'provider_transaction')
        OR (date_precision != 'instant' AND occurred_at_utc IS NULL AND timestamp_kind = 'none'))
);
CREATE TABLE historical_activity_run_observations (
    run_uid VARCHAR NOT NULL REFERENCES historical_activity_import_runs(run_uid),
    observation_uid VARCHAR NOT NULL REFERENCES historical_activity_observations(observation_uid),
    PRIMARY KEY (run_uid, observation_uid)
);
CREATE TABLE historical_activity_bundle_reviews (
    run_uid VARCHAR NOT NULL REFERENCES historical_activity_import_runs(run_uid),
    provider_activity_id VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    review_json VARCHAR NOT NULL,
    PRIMARY KEY (run_uid, provider_activity_id),
    CHECK (status IN ('consistent_bundle', 'economic_conflict', 'ambiguous_security_items', 'unsupported_assets'))
);
