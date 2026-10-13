-- Additive normalized activity and checkpoint in the SAME immutable artifact.
-- No history activation, normalized_fills, reviews or reporting views change.
CREATE TABLE incremental_activity_imports (
    import_uid VARCHAR PRIMARY KEY,
    source_broker VARCHAR NOT NULL CHECK (source_broker = 'schwab'),
    source_account_id VARCHAR NOT NULL,
    import_sequence BIGINT NOT NULL CHECK (import_sequence > 0),
    acquisition_run_uid VARCHAR NOT NULL,
    artifact_json VARCHAR NOT NULL,
    UNIQUE (source_broker, source_account_id, import_sequence),
    UNIQUE (source_broker, source_account_id, acquisition_run_uid),
    CHECK (length(import_uid) = 64)
);
