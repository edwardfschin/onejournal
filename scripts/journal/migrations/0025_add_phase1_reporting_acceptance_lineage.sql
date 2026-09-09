-- Migration 0025: preserve separate approval lineage for both financial inputs.
--
-- DuckDB does not allow the referenced migration-0024 release table to be
-- altered while its child foreign keys exist. Gate 4 has not persisted any
-- report release, so this migration first proves the four release tables are
-- empty and then recreates only those empty tables with the corrected schema.
-- The independent, value-free API audit table is not changed.

SELECT CASE
    WHEN (SELECT count(*) FROM phase1_reporting_releases) = 0
    AND (SELECT count(*) FROM phase1_reporting_release_accounts) = 0
    AND (SELECT count(*) FROM phase1_reporting_release_realized_items) = 0
    AND (SELECT count(*) FROM phase1_reporting_release_omissions) = 0
    THEN true
    ELSE error(
        'migration 0025 requires empty phase1 reporting release tables; '
        'existing release lineage must be reviewed explicitly'
    )
END;

DROP TABLE phase1_reporting_release_realized_items;
DROP TABLE phase1_reporting_release_omissions;
DROP TABLE phase1_reporting_release_accounts;
DROP TABLE phase1_reporting_releases;

CREATE TABLE phase1_reporting_releases (
    report_release_uid VARCHAR PRIMARY KEY,
    contract_version VARCHAR NOT NULL,
    report_release_fingerprint VARCHAR NOT NULL UNIQUE,
    current_valuation_run_uid VARCHAR NOT NULL,
    current_result_fingerprint VARCHAR NOT NULL,
    current_owner_acceptance_uid VARCHAR NOT NULL,
    current_owner_accepted_at_utc VARCHAR NOT NULL,
    realized_calculation_run_id VARCHAR NOT NULL,
    realized_result_fingerprint VARCHAR NOT NULL,
    realized_owner_acceptance_uid VARCHAR NOT NULL,
    realized_owner_accepted_at_utc VARCHAR NOT NULL,
    history_revision_uid VARCHAR NOT NULL,
    coverage_start_date DATE NOT NULL,
    coverage_end_date DATE NOT NULL,
    calculation_version VARCHAR NOT NULL,
    generated_at_utc VARCHAR NOT NULL,
    release_status VARCHAR NOT NULL,
    owner_acceptance_uid VARCHAR,
    owner_accepted_at_utc VARCHAR,
    processed_count INTEGER NOT NULL,
    available_count INTEGER NOT NULL,
    unavailable_count INTEGER NOT NULL,
    reconciliation_pending_count INTEGER NOT NULL,
    reason_counts_json VARCHAR NOT NULL,
    CHECK (contract_version = 'onejournal.phase1-report-release.v1'),
    CHECK (length(report_release_fingerprint) = 64),
    CHECK (length(current_result_fingerprint) = 64),
    CHECK (length(current_owner_acceptance_uid) BETWEEN 1 AND 256),
    CHECK (length(realized_result_fingerprint) = 64),
    CHECK (length(realized_owner_acceptance_uid) BETWEEN 1 AND 256),
    CHECK (coverage_start_date <= coverage_end_date),
    CHECK (release_status IN ('draft', 'owner_accepted')),
    CHECK ((release_status = 'owner_accepted') =
      (owner_acceptance_uid IS NOT NULL AND owner_accepted_at_utc IS NOT NULL)),
    CHECK (processed_count >= 0 AND available_count >= 0
      AND unavailable_count >= 0 AND reconciliation_pending_count >= 0
      AND processed_count = available_count + unavailable_count
        + reconciliation_pending_count)
);

CREATE TABLE phase1_reporting_release_accounts (
    report_release_uid VARCHAR NOT NULL,
    source_broker VARCHAR NOT NULL,
    source_account_id VARCHAR NOT NULL,
    account_alias VARCHAR NOT NULL,
    PRIMARY KEY (report_release_uid, source_broker, source_account_id),
    UNIQUE (report_release_uid, account_alias),
    FOREIGN KEY (report_release_uid)
      REFERENCES phase1_reporting_releases (report_release_uid),
    CHECK (length(account_alias) BETWEEN 1 AND 64)
);

CREATE TABLE phase1_reporting_release_realized_items (
    report_release_uid VARCHAR NOT NULL,
    item_uid VARCHAR NOT NULL,
    source_broker VARCHAR NOT NULL,
    source_account_id VARCHAR NOT NULL,
    instrument_key VARCHAR NOT NULL,
    symbol VARCHAR NOT NULL,
    asset_class VARCHAR NOT NULL,
    close_market_date DATE NOT NULL,
    closed_at_utc VARCHAR NOT NULL,
    currency VARCHAR NOT NULL,
    realized_pnl DECIMAL(38, 13) NOT NULL,
    item_status VARCHAR NOT NULL,
    reason_codes_json VARCHAR NOT NULL,
    PRIMARY KEY (report_release_uid, item_uid),
    FOREIGN KEY (report_release_uid)
      REFERENCES phase1_reporting_releases (report_release_uid),
    CHECK (asset_class IN ('equity', 'option')),
    CHECK (item_status = 'valid')
);

CREATE TABLE phase1_reporting_release_omissions (
    report_release_uid VARCHAR NOT NULL,
    omission_uid VARCHAR NOT NULL,
    source_broker VARCHAR NOT NULL,
    source_account_id VARCHAR NOT NULL,
    close_market_date DATE NOT NULL,
    symbol VARCHAR,
    reason_code VARCHAR NOT NULL,
    item_status VARCHAR NOT NULL,
    PRIMARY KEY (report_release_uid, omission_uid),
    FOREIGN KEY (report_release_uid)
      REFERENCES phase1_reporting_releases (report_release_uid),
    CHECK (item_status IN ('incomplete', 'reconciliation_pending', 'unavailable'))
);
