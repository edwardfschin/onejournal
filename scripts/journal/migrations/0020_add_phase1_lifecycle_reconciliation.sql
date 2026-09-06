-- Migration 0020: preserve assembly-v2 lifecycle evidence and reconcile the
-- historical journal to Schwab terminal events plus a complete position snapshot.
-- This is additive.  Assembly v1, materialization v1, fills, episodes, reviews,
-- entries, accepted PNL-03 evidence, and financial aggregates are not rewritten.

CREATE TABLE phase1_schwab_evidence_v2_import_runs (
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
    CONSTRAINT ck_phase1_schwab_v2_provider CHECK (provider = 'schwab'),
    CONSTRAINT ck_phase1_schwab_v2_contract CHECK (
      contract_version = 'onejournal.schwab-phase1-evidence-assembly.v2'
    ),
    CONSTRAINT ck_phase1_schwab_v2_window CHECK (
      lifecycle_window_start <= lifecycle_window_end
      AND lifecycle_window_end <= asof_date
    ),
    CONSTRAINT ck_phase1_schwab_v2_counts CHECK (
      matched_fill_rows >= 0
      AND order_only_fill_rows >= 0
      AND transaction_only_fill_rows >= 0
      AND position_count >= 0
      AND quote_count >= 0
      AND positions_without_quotes >= 0
      AND position_count = quote_count + positions_without_quotes
      AND session_count >= 0
      AND cash_review_required_rows >= 0
    ),
    CONSTRAINT ck_phase1_schwab_v2_status CHECK (
      final_status IN ('ready', 'review_required')
    ),
    CONSTRAINT ck_phase1_schwab_v2_fingerprint CHECK (
      length(result_fingerprint) = 64
    )
);

CREATE TABLE phase1_schwab_evidence_v2_import_families (
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
    CONSTRAINT ck_phase1_schwab_v2_family CHECK (family IN (
      'account', 'positions', 'orders', 'transactions', 'lifecycle_events',
      'lifecycle_event_legs', 'fills', 'cash', 'quotes', 'sessions'
    )),
    CONSTRAINT ck_phase1_schwab_v2_family_counts CHECK (
      source_record_count >= 0
      AND normalized_record_count >= 0
      AND excluded_record_count >= 0
    ),
    CONSTRAINT ck_phase1_schwab_v2_family_fingerprint CHECK (
      length(family_fingerprint) = 64
    ),
    CONSTRAINT fk_phase1_schwab_v2_import_run FOREIGN KEY (assembly_uid)
      REFERENCES phase1_schwab_evidence_v2_import_runs (assembly_uid)
);

CREATE TABLE phase1_journal_lifecycle_reconciliation_runs (
    reconciliation_uid VARCHAR PRIMARY KEY,
    contract_version VARCHAR NOT NULL,
    assembly_uid VARCHAR NOT NULL,
    source_materialization_uid VARCHAR NOT NULL,
    source_account_id VARCHAR NOT NULL,
    asof_date DATE NOT NULL,
    episode_count INTEGER NOT NULL,
    closed_count INTEGER NOT NULL,
    open_count INTEGER NOT NULL,
    review_required_count INTEGER NOT NULL,
    terminal_event_count INTEGER NOT NULL,
    terminal_event_leg_count INTEGER NOT NULL,
    matched_terminal_event_leg_count INTEGER NOT NULL,
    final_status VARCHAR NOT NULL,
    result_fingerprint VARCHAR NOT NULL UNIQUE,
    reconciled_at TIMESTAMP NOT NULL,
    CONSTRAINT ck_phase1_journal_lifecycle_contract CHECK (
      contract_version = 'onejournal.phase1-journal-lifecycle-reconciliation.v1'
    ),
    CONSTRAINT ck_phase1_journal_lifecycle_counts CHECK (
      episode_count >= 0
      AND closed_count >= 0
      AND open_count >= 0
      AND review_required_count >= 0
      AND episode_count = closed_count + open_count + review_required_count
      AND terminal_event_count >= 0
      AND terminal_event_leg_count >= 0
      AND matched_terminal_event_leg_count >= 0
      AND matched_terminal_event_leg_count <= terminal_event_leg_count
    ),
    CONSTRAINT ck_phase1_journal_lifecycle_status CHECK (
      final_status IN ('reconciled', 'review_required')
    ),
    CONSTRAINT ck_phase1_journal_lifecycle_fingerprint CHECK (
      length(result_fingerprint) = 64
    ),
    CONSTRAINT fk_phase1_journal_lifecycle_assembly FOREIGN KEY (assembly_uid)
      REFERENCES phase1_schwab_evidence_v2_import_runs (assembly_uid)
);

CREATE TABLE phase1_journal_episode_lifecycle_states (
    reconciliation_uid VARCHAR NOT NULL,
    episode_uid VARCHAR NOT NULL,
    prior_status VARCHAR NOT NULL,
    reconciled_status VARCHAR NOT NULL,
    lifecycle_quality VARCHAR NOT NULL,
    reason_code VARCHAR,
    position_reconciliation_status VARCHAR NOT NULL,
    matched_terminal_event_count INTEGER NOT NULL,
    state_fingerprint VARCHAR NOT NULL,
    PRIMARY KEY (reconciliation_uid, episode_uid),
    CONSTRAINT ck_phase1_journal_episode_prior_status CHECK (
      prior_status IN ('open', 'closed', 'review_required')
    ),
    CONSTRAINT ck_phase1_journal_episode_reconciled_status CHECK (
      reconciled_status IN ('open', 'closed', 'review_required')
    ),
    CONSTRAINT ck_phase1_journal_episode_quality CHECK (
      lifecycle_quality IN ('resolved', 'review_required')
    ),
    CONSTRAINT ck_phase1_journal_episode_position_status CHECK (
      position_reconciliation_status IN (
        'not_applicable', 'matched_current', 'terminal_reconciled',
        'absent_current', 'mismatch'
      )
    ),
    CONSTRAINT ck_phase1_journal_episode_terminal_count CHECK (
      matched_terminal_event_count >= 0
    ),
    CONSTRAINT ck_phase1_journal_episode_state_fingerprint CHECK (
      length(state_fingerprint) = 64
    ),
    CONSTRAINT fk_phase1_journal_episode_reconciliation
      FOREIGN KEY (reconciliation_uid)
      REFERENCES phase1_journal_lifecycle_reconciliation_runs (reconciliation_uid),
    CONSTRAINT fk_phase1_journal_episode_state
      FOREIGN KEY (episode_uid) REFERENCES trade_episodes (episode_uid)
);

CREATE UNIQUE INDEX idx_phase1_journal_lifecycle_scope
  ON phase1_journal_lifecycle_reconciliation_runs (
    source_account_id, asof_date, assembly_uid
  );

CREATE INDEX idx_phase1_journal_episode_lifecycle_lookup
  ON phase1_journal_episode_lifecycle_states (episode_uid, reconciliation_uid);
