-- Migration 0019: add the corrected execution-first journal projection.
-- Expected predecessor: migration 0018.
--
-- Migration 0018 and the accepted Phase 1 assembly remain immutable.  This
-- additive projection distinguishes broker executions from instruments and
-- trade strategy, and records exact Schwab net-cash reconciliation.

CREATE TABLE phase1_journal_execution_projection_runs (
    projection_uid VARCHAR PRIMARY KEY,
    contract_version VARCHAR NOT NULL,
    materialization_uid VARCHAR NOT NULL UNIQUE,
    episode_count INTEGER NOT NULL,
    instrument_count INTEGER NOT NULL,
    execution_count INTEGER NOT NULL,
    schwab_net_amount_match_count INTEGER NOT NULL,
    schwab_net_amount_mismatch_count INTEGER NOT NULL,
    result_fingerprint VARCHAR NOT NULL UNIQUE,
    projected_at TIMESTAMP NOT NULL,
    CONSTRAINT fk_phase1_execution_projection_materialization
      FOREIGN KEY (materialization_uid)
      REFERENCES phase1_journal_materialization_runs (materialization_uid),
    CONSTRAINT ck_phase1_execution_projection_contract
      CHECK (contract_version = 'onejournal.phase1-journal-execution-projection.v1'),
    CONSTRAINT ck_phase1_execution_projection_counts
      CHECK (episode_count >= 0 AND instrument_count >= 0
             AND execution_count >= 0
             AND schwab_net_amount_match_count >= 0
             AND schwab_net_amount_mismatch_count = 0
             AND execution_count = schwab_net_amount_match_count),
    CONSTRAINT ck_phase1_execution_projection_fingerprint
      CHECK (length(result_fingerprint) = 64)
);

CREATE TABLE phase1_journal_projected_episodes (
    projection_uid VARCHAR NOT NULL,
    episode_uid VARCHAR NOT NULL UNIQUE,
    strategy_type VARCHAR NOT NULL,
    strategy_label VARCHAR NOT NULL,
    instrument_count INTEGER NOT NULL,
    execution_count INTEGER NOT NULL,
    lifecycle_sequence INTEGER NOT NULL,
    lifecycle_count INTEGER NOT NULL,
    instrument_summary VARCHAR NOT NULL,
    episode_projection_fingerprint VARCHAR NOT NULL,
    PRIMARY KEY (projection_uid, episode_uid),
    CONSTRAINT fk_phase1_projected_episode_run
      FOREIGN KEY (projection_uid)
      REFERENCES phase1_journal_execution_projection_runs (projection_uid),
    CONSTRAINT fk_phase1_projected_episode
      FOREIGN KEY (episode_uid) REFERENCES trade_episodes (episode_uid),
    CONSTRAINT ck_phase1_projected_episode_counts
      CHECK (instrument_count > 0 AND execution_count > 0
             AND lifecycle_sequence > 0
             AND lifecycle_count >= lifecycle_sequence),
    CONSTRAINT ck_phase1_projected_episode_fingerprint
      CHECK (length(episode_projection_fingerprint) = 64)
);

CREATE TABLE phase1_journal_projected_instruments (
    projection_uid VARCHAR NOT NULL,
    episode_uid VARCHAR NOT NULL,
    instrument_index INTEGER NOT NULL,
    instrument_uid VARCHAR NOT NULL,
    asset_class VARCHAR NOT NULL,
    symbol VARCHAR NOT NULL,
    underlying_symbol VARCHAR,
    option_type VARCHAR,
    expiry DATE,
    strike DECIMAL(38, 10),
    multiplier DECIMAL(38, 10),
    currency VARCHAR NOT NULL,
    opening_direction VARCHAR,
    execution_count INTEGER NOT NULL,
    buy_quantity DECIMAL(38, 10) NOT NULL,
    sell_quantity DECIMAL(38, 10) NOT NULL,
    captured_quantity_delta DECIMAL(38, 10) NOT NULL,
    instrument_projection_fingerprint VARCHAR NOT NULL,
    PRIMARY KEY (projection_uid, episode_uid, instrument_index),
    UNIQUE (projection_uid, episode_uid, instrument_uid),
    CONSTRAINT fk_phase1_projected_instrument_episode
      FOREIGN KEY (projection_uid, episode_uid)
      REFERENCES phase1_journal_projected_episodes (projection_uid, episode_uid),
    CONSTRAINT ck_phase1_projected_instrument_index
      CHECK (instrument_index > 0 AND execution_count > 0),
    CONSTRAINT ck_phase1_projected_instrument_direction
      CHECK (opening_direction IS NULL OR opening_direction IN ('LONG', 'SHORT')),
    CONSTRAINT ck_phase1_projected_instrument_fingerprint
      CHECK (length(instrument_projection_fingerprint) = 64)
);

CREATE TABLE phase1_journal_projected_executions (
    projection_uid VARCHAR NOT NULL,
    episode_uid VARCHAR NOT NULL,
    execution_index INTEGER NOT NULL,
    execution_uid VARCHAR NOT NULL UNIQUE,
    fill_uid VARCHAR NOT NULL UNIQUE,
    instrument_uid VARCHAR NOT NULL,
    filled_at_utc VARCHAR NOT NULL,
    side VARCHAR NOT NULL,
    quantity DECIMAL(38, 10) NOT NULL,
    fill_price DECIMAL(38, 10) NOT NULL,
    multiplier DECIMAL(38, 10) NOT NULL,
    commission DECIMAL(38, 10) NOT NULL,
    fees DECIMAL(38, 10) NOT NULL,
    currency VARCHAR NOT NULL,
    schwab_net_cash_movement DECIMAL(38, 10) NOT NULL,
    calculated_net_cash_movement DECIMAL(38, 10) NOT NULL,
    net_amount_reconciled BOOLEAN NOT NULL,
    execution_projection_fingerprint VARCHAR NOT NULL,
    PRIMARY KEY (projection_uid, episode_uid, execution_index),
    CONSTRAINT fk_phase1_projected_execution_episode
      FOREIGN KEY (projection_uid, episode_uid)
      REFERENCES phase1_journal_projected_episodes (projection_uid, episode_uid),
    CONSTRAINT fk_phase1_projected_execution_fill
      FOREIGN KEY (fill_uid) REFERENCES normalized_fills (fill_uid),
    CONSTRAINT ck_phase1_projected_execution_index
      CHECK (execution_index > 0 AND quantity > 0 AND multiplier > 0),
    CONSTRAINT ck_phase1_projected_execution_reconciled
      CHECK (net_amount_reconciled = TRUE
             AND schwab_net_cash_movement = calculated_net_cash_movement),
    CONSTRAINT ck_phase1_projected_execution_fingerprint
      CHECK (length(execution_projection_fingerprint) = 64)
);

CREATE INDEX idx_phase1_projected_episode_search
  ON phase1_journal_projected_episodes (strategy_type, lifecycle_sequence);

CREATE INDEX idx_phase1_projected_execution_read
  ON phase1_journal_projected_executions (episode_uid, execution_index);
