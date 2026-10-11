-- Add immutable snapshot-cutoff assembly artifacts without touching v1/v2
-- rows, fingerprints, accepted reports, operational projections or views.
CREATE TABLE phase1_schwab_snapshot_evidence_imports (
    assembly_uid VARCHAR PRIMARY KEY,
    contract_version VARCHAR NOT NULL,
    source_account_id VARCHAR NOT NULL,
    connection_uid VARCHAR NOT NULL,
    asof_date DATE NOT NULL,
    lifecycle_window_start DATE NOT NULL,
    lifecycle_window_end DATE NOT NULL,
    snapshot_cutoff_utc TIMESTAMPTZ NOT NULL,
    result_fingerprint VARCHAR NOT NULL UNIQUE,
    artifact_sha256 VARCHAR NOT NULL,
    artifact_json VARCHAR NOT NULL,
    CHECK (contract_version = 'onejournal.schwab-phase1-evidence-assembly.v3'),
    CHECK (lifecycle_window_start <= lifecycle_window_end
       AND lifecycle_window_end = CAST(timezone('UTC', snapshot_cutoff_utc) AS DATE)),
    CHECK (asof_date = CAST(timezone('America/New_York', snapshot_cutoff_utc) AS DATE)),
    CHECK (length(result_fingerprint) = 64 AND length(artifact_sha256) = 64),
    CHECK (length(artifact_json) > 0)
);
