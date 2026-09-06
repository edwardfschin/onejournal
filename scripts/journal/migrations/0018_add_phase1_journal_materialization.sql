-- Migration 0018: record deterministic Phase 1 evidence-to-journal materialization.
-- Expected predecessor: migration 0017.
--
-- The accepted evidence assembly remains immutable. These additive tables bind
-- canonical fills and derived/review-required episode projections back to one
-- exact assembly without placing private evidence in ordinary audit output.

CREATE TABLE phase1_journal_materialization_runs (
    materialization_uid VARCHAR NOT NULL,
    contract_version VARCHAR NOT NULL,
    assembly_uid VARCHAR NOT NULL,
    source_account_id VARCHAR NOT NULL,
    asof_date DATE NOT NULL,
    fill_count INTEGER NOT NULL,
    episode_count INTEGER NOT NULL,
    lifecycle_resolved_scope_count INTEGER NOT NULL,
    review_required_scope_count INTEGER NOT NULL,
    lifecycle_resolved_fill_count INTEGER NOT NULL,
    review_required_fill_count INTEGER NOT NULL,
    final_status VARCHAR NOT NULL,
    result_fingerprint VARCHAR NOT NULL UNIQUE,
    materialized_at TIMESTAMP NOT NULL,
    PRIMARY KEY (materialization_uid),
    CONSTRAINT fk_phase1_journal_materialization_assembly
      FOREIGN KEY (assembly_uid)
      REFERENCES phase1_schwab_evidence_import_runs (assembly_uid),
    CONSTRAINT ck_phase1_journal_materialization_contract
      CHECK (contract_version = 'onejournal.phase1-journal-materialization.v1'),
    CONSTRAINT ck_phase1_journal_materialization_counts
      CHECK (fill_count >= 0 AND episode_count >= 0
             AND lifecycle_resolved_scope_count >= 0
             AND review_required_scope_count >= 0
             AND lifecycle_resolved_fill_count >= 0
             AND review_required_fill_count >= 0
             AND fill_count = lifecycle_resolved_fill_count + review_required_fill_count),
    CONSTRAINT ck_phase1_journal_materialization_status
      CHECK (final_status IN ('ready', 'review_required')),
    CONSTRAINT ck_phase1_journal_materialization_fingerprint
      CHECK (length(result_fingerprint) = 64)
);

CREATE TABLE phase1_journal_materialized_fills (
    materialization_uid VARCHAR NOT NULL,
    fill_uid VARCHAR NOT NULL,
    source_record_fingerprint VARCHAR NOT NULL,
    PRIMARY KEY (materialization_uid, fill_uid),
    CONSTRAINT fk_phase1_journal_materialized_fill_run
      FOREIGN KEY (materialization_uid)
      REFERENCES phase1_journal_materialization_runs (materialization_uid),
    CONSTRAINT fk_phase1_journal_materialized_fill
      FOREIGN KEY (fill_uid) REFERENCES normalized_fills (fill_uid),
    CONSTRAINT ck_phase1_journal_materialized_fill_fingerprint
      CHECK (length(source_record_fingerprint) = 64)
);

CREATE TABLE phase1_journal_materialized_episodes (
    materialization_uid VARCHAR NOT NULL,
    episode_uid VARCHAR NOT NULL,
    scope_uid VARCHAR NOT NULL,
    lifecycle_quality VARCHAR NOT NULL,
    reason_code VARCHAR,
    source_fill_count INTEGER NOT NULL,
    episode_fingerprint VARCHAR NOT NULL,
    PRIMARY KEY (materialization_uid, episode_uid),
    CONSTRAINT fk_phase1_journal_materialized_episode_run
      FOREIGN KEY (materialization_uid)
      REFERENCES phase1_journal_materialization_runs (materialization_uid),
    CONSTRAINT fk_phase1_journal_materialized_episode
      FOREIGN KEY (episode_uid) REFERENCES trade_episodes (episode_uid),
    CONSTRAINT ck_phase1_journal_materialized_episode_quality
      CHECK (lifecycle_quality IN ('resolved', 'review_required')),
    CONSTRAINT ck_phase1_journal_materialized_episode_reason
      CHECK ((lifecycle_quality = 'resolved' AND reason_code IS NULL)
             OR (lifecycle_quality = 'review_required' AND reason_code IS NOT NULL)),
    CONSTRAINT ck_phase1_journal_materialized_episode_counts
      CHECK (source_fill_count > 0),
    CONSTRAINT ck_phase1_journal_materialized_episode_fingerprint
      CHECK (length(episode_fingerprint) = 64)
);

CREATE TABLE phase1_journal_materialized_episode_fills (
    materialization_uid VARCHAR NOT NULL,
    episode_uid VARCHAR NOT NULL,
    leg_index INTEGER NOT NULL,
    fill_uid VARCHAR NOT NULL,
    PRIMARY KEY (materialization_uid, episode_uid, leg_index),
    UNIQUE (materialization_uid, fill_uid),
    CONSTRAINT fk_phase1_journal_materialized_episode_fill_episode
      FOREIGN KEY (materialization_uid, episode_uid)
      REFERENCES phase1_journal_materialized_episodes (materialization_uid, episode_uid),
    CONSTRAINT fk_phase1_journal_materialized_episode_fill_fill
      FOREIGN KEY (materialization_uid, fill_uid)
      REFERENCES phase1_journal_materialized_fills (materialization_uid, fill_uid),
    CONSTRAINT ck_phase1_journal_materialized_episode_fill_index
      CHECK (leg_index > 0)
);

CREATE INDEX idx_phase1_journal_materialization_scope
  ON phase1_journal_materialized_episodes (
    materialization_uid, lifecycle_quality, reason_code, scope_uid
  );
