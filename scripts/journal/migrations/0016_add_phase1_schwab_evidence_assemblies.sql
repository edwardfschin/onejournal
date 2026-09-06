-- Migration 0016: persist complete Phase 1 Schwab evidence assemblies.
-- Expected predecessor: migration 0015.
-- This is additive. It does not rewrite legacy fill-derived family tables,
-- PNL-03 results, quote captures, or private raw evidence.

CREATE TABLE phase1_schwab_evidence_import_runs (
    assembly_uid VARCHAR PRIMARY KEY,
    contract_version VARCHAR NOT NULL,
    provider VARCHAR NOT NULL,
    connection_uid VARCHAR NOT NULL,
    source_account_id VARCHAR NOT NULL,
    asof_date DATE NOT NULL,
    assembled_at_utc VARCHAR NOT NULL,
    lifecycle_window_start DATE NOT NULL,
    lifecycle_window_end DATE NOT NULL,
    matched_fill_rows INTEGER NOT NULL,
    order_only_fill_rows INTEGER NOT NULL,
    transaction_only_fill_rows INTEGER NOT NULL,
    position_count INTEGER NOT NULL,
    quote_count INTEGER NOT NULL,
    positions_without_quotes INTEGER NOT NULL,
    session_count INTEGER NOT NULL,
    cash_review_required_rows INTEGER NOT NULL,
    all_positions_have_quotes BOOLEAN NOT NULL,
    all_quotes_have_session_authority BOOLEAN NOT NULL,
    final_status VARCHAR NOT NULL,
    result_fingerprint VARCHAR NOT NULL UNIQUE,
    CONSTRAINT ck_phase1_schwab_provider
      CHECK (provider = 'schwab'),
    CONSTRAINT ck_phase1_schwab_contract
      CHECK (contract_version = 'onejournal.schwab-phase1-evidence-assembly.v1'),
    CONSTRAINT ck_phase1_schwab_window
      CHECK (lifecycle_window_start <= lifecycle_window_end
             AND lifecycle_window_end <= asof_date),
    CONSTRAINT ck_phase1_schwab_counts
      CHECK (matched_fill_rows >= 0
             AND order_only_fill_rows >= 0
             AND transaction_only_fill_rows >= 0
             AND position_count >= 0
             AND quote_count >= 0
             AND positions_without_quotes >= 0
             AND position_count = quote_count + positions_without_quotes
             AND session_count >= 0
             AND cash_review_required_rows >= 0),
    CONSTRAINT ck_phase1_schwab_status
      CHECK (final_status IN ('ready', 'review_required')),
    CONSTRAINT ck_phase1_schwab_fingerprint
      CHECK (length(result_fingerprint) = 64)
);

CREATE INDEX idx_phase1_schwab_evidence_import_scope
  ON phase1_schwab_evidence_import_runs (
    connection_uid, source_account_id, asof_date, assembled_at_utc, final_status
  );

CREATE TABLE phase1_schwab_evidence_import_families (
    assembly_uid VARCHAR NOT NULL,
    family VARCHAR NOT NULL,
    source_manifest_sha256s_json VARCHAR NOT NULL,
    source_raw_sha256s_json VARCHAR NOT NULL,
    source_record_count INTEGER NOT NULL,
    normalized_record_count INTEGER NOT NULL,
    excluded_record_count INTEGER NOT NULL,
    exclusion_reasons_json VARCHAR NOT NULL,
    records_json VARCHAR NOT NULL,
    family_fingerprint VARCHAR NOT NULL,
    PRIMARY KEY (assembly_uid, family),
    CONSTRAINT ck_phase1_schwab_family
      CHECK (family IN (
        'account', 'positions', 'orders', 'transactions',
        'fills', 'cash', 'quotes', 'sessions'
      )),
    CONSTRAINT ck_phase1_schwab_family_counts
      CHECK (source_record_count >= 0
             AND normalized_record_count >= 0
             AND excluded_record_count >= 0),
    CONSTRAINT ck_phase1_schwab_family_fingerprint
      CHECK (length(family_fingerprint) = 64),
    CONSTRAINT fk_phase1_schwab_evidence_import_run
      FOREIGN KEY (assembly_uid)
      REFERENCES phase1_schwab_evidence_import_runs (assembly_uid)
);
