-- Migration 0026: preserve accepted WEB-W08 realized values exactly.
--
-- Gate 4 rehearsal proved that 16 accepted values carry meaningful precision
-- beyond migration 0025's DECIMAL(38,13) item column. No report release has
-- been persisted, so this migration fails closed unless all four related
-- release tables are empty, then recreates only the empty realized-item table
-- at DECIMAL(38,27). The independent value-free API audit table is unchanged.

SELECT CASE
    WHEN (SELECT count(*) FROM phase1_reporting_releases) = 0
    AND (SELECT count(*) FROM phase1_reporting_release_accounts) = 0
    AND (SELECT count(*) FROM phase1_reporting_release_realized_items) = 0
    AND (SELECT count(*) FROM phase1_reporting_release_omissions) = 0
    THEN true
    ELSE error(
        'migration 0026 requires empty phase1 reporting release tables; '
        'existing release lineage must be reviewed explicitly'
    )
END;

DROP TABLE phase1_reporting_release_realized_items;

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
    realized_pnl DECIMAL(38, 27) NOT NULL,
    item_status VARCHAR NOT NULL,
    reason_codes_json VARCHAR NOT NULL,
    PRIMARY KEY (report_release_uid, item_uid),
    FOREIGN KEY (report_release_uid)
      REFERENCES phase1_reporting_releases (report_release_uid),
    CHECK (asset_class IN ('equity', 'option')),
    CHECK (item_status = 'valid')
);
