-- Migration 0021: add append-only journal history materialization revisions.
-- Expected predecessor: migration 0020.
--
-- Revision snapshots and activation events are immutable.  The legacy
-- materialization remains intact and is used until an explicitly built revision
-- is activated.  Current-read views select only the latest activation for each
-- broker account while preserving unrevisioned accounts through legacy fallback.

CREATE TABLE phase1_journal_history_revisions (
    revision_uid VARCHAR PRIMARY KEY,
    contract_version VARCHAR NOT NULL,
    source_broker VARCHAR NOT NULL,
    source_account_id VARCHAR NOT NULL,
    assembly_uid VARCHAR NOT NULL,
    materialization_uid VARCHAR NOT NULL,
    projection_uid VARCHAR NOT NULL,
    reconciliation_uid VARCHAR NOT NULL,
    history_window_start DATE NOT NULL,
    history_window_end DATE NOT NULL,
    asof_date DATE NOT NULL,
    fill_count INTEGER NOT NULL,
    episode_count INTEGER NOT NULL,
    instrument_count INTEGER NOT NULL,
    execution_count INTEGER NOT NULL,
    lifecycle_resolved_scope_count INTEGER NOT NULL,
    review_required_scope_count INTEGER NOT NULL,
    closed_count INTEGER NOT NULL,
    open_count INTEGER NOT NULL,
    review_required_count INTEGER NOT NULL,
    terminal_event_count INTEGER NOT NULL,
    terminal_event_leg_count INTEGER NOT NULL,
    matched_terminal_event_leg_count INTEGER NOT NULL,
    lifecycle_final_status VARCHAR NOT NULL,
    materialization_result_fingerprint VARCHAR NOT NULL,
    projection_result_fingerprint VARCHAR NOT NULL,
    reconciliation_result_fingerprint VARCHAR NOT NULL,
    origin VARCHAR NOT NULL,
    result_fingerprint VARCHAR NOT NULL UNIQUE,
    created_at TIMESTAMP NOT NULL,
    CHECK (contract_version = 'onejournal.history-materialization-revision.v1'),
    CHECK (source_broker = 'schwab'),
    CHECK (history_window_start <= history_window_end AND history_window_end <= asof_date),
    CHECK (fill_count >= 0 AND episode_count >= 0 AND instrument_count >= 0
           AND execution_count = fill_count AND lifecycle_resolved_scope_count >= 0
           AND review_required_scope_count >= 0 AND closed_count >= 0
           AND open_count >= 0 AND review_required_count >= 0
           AND episode_count = closed_count + open_count + review_required_count
           AND terminal_event_count >= 0 AND terminal_event_leg_count >= 0
           AND matched_terminal_event_leg_count >= 0
           AND matched_terminal_event_leg_count <= terminal_event_leg_count),
    CHECK (lifecycle_final_status IN ('reconciled', 'review_required')),
    CHECK (length(materialization_result_fingerprint) = 64
           AND length(projection_result_fingerprint) = 64
           AND length(reconciliation_result_fingerprint) = 64),
    CHECK (origin IN ('legacy_bootstrap', 'history_reconstruction')),
    CHECK (length(result_fingerprint) = 64)
);

CREATE TABLE phase1_journal_history_revision_episodes (
    revision_uid VARCHAR NOT NULL,
    episode_uid VARCHAR NOT NULL,
    source_broker VARCHAR NOT NULL,
    source_account_id VARCHAR NOT NULL,
    primary_symbol VARCHAR NOT NULL,
    asset_class VARCHAR NOT NULL,
    strategy_type VARCHAR NOT NULL,
    strategy_label VARCHAR NOT NULL,
    opened_at TIMESTAMP NOT NULL,
    status VARCHAR NOT NULL,
    fill_count INTEGER NOT NULL,
    leg_count INTEGER NOT NULL,
    leg_summary VARCHAR,
    cashflow_label VARCHAR,
    net_quantity DECIMAL(38, 10),
    gross_cashflow DECIMAL(38, 10),
    commission DECIMAL(38, 10),
    fees DECIMAL(38, 10),
    updated_at TIMESTAMP NOT NULL,
    scope_uid VARCHAR NOT NULL,
    materialization_lifecycle_quality VARCHAR NOT NULL,
    materialization_reason_code VARCHAR,
    lifecycle_quality VARCHAR NOT NULL,
    reason_code VARCHAR,
    source_fill_count INTEGER NOT NULL,
    episode_fingerprint VARCHAR NOT NULL,
    instrument_count INTEGER NOT NULL,
    execution_count INTEGER NOT NULL,
    lifecycle_sequence INTEGER NOT NULL,
    lifecycle_count INTEGER NOT NULL,
    instrument_summary VARCHAR NOT NULL,
    episode_projection_fingerprint VARCHAR NOT NULL,
    prior_status VARCHAR NOT NULL,
    reconciled_status VARCHAR NOT NULL,
    position_reconciliation_status VARCHAR NOT NULL,
    matched_terminal_event_count INTEGER NOT NULL,
    state_fingerprint VARCHAR NOT NULL,
    PRIMARY KEY (revision_uid, episode_uid),
    FOREIGN KEY (revision_uid) REFERENCES phase1_journal_history_revisions (revision_uid),
    CHECK (status IN ('open', 'closed', 'review_required')),
    CHECK (prior_status IN ('open', 'closed', 'review_required')),
    CHECK (reconciled_status IN ('open', 'closed', 'review_required')),
    CHECK (materialization_lifecycle_quality IN ('resolved', 'review_required')),
    CHECK (lifecycle_quality IN ('resolved', 'review_required')),
    CHECK (fill_count > 0 AND leg_count > 0 AND source_fill_count = fill_count
           AND instrument_count > 0 AND execution_count = fill_count
           AND lifecycle_sequence > 0 AND lifecycle_count >= lifecycle_sequence),
    CHECK (length(episode_fingerprint) = 64
           AND length(episode_projection_fingerprint) = 64
           AND length(state_fingerprint) = 64)
);

CREATE TABLE phase1_journal_history_revision_episode_fills (
    revision_uid VARCHAR NOT NULL,
    episode_uid VARCHAR NOT NULL,
    leg_index INTEGER NOT NULL,
    fill_uid VARCHAR NOT NULL,
    source_record_fingerprint VARCHAR NOT NULL,
    PRIMARY KEY (revision_uid, episode_uid, leg_index),
    UNIQUE (revision_uid, fill_uid),
    FOREIGN KEY (revision_uid, episode_uid)
      REFERENCES phase1_journal_history_revision_episodes (revision_uid, episode_uid),
    FOREIGN KEY (fill_uid) REFERENCES normalized_fills (fill_uid),
    CHECK (leg_index > 0 AND length(source_record_fingerprint) = 64)
);

CREATE TABLE phase1_journal_history_revision_instruments (
    revision_uid VARCHAR NOT NULL,
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
    PRIMARY KEY (revision_uid, episode_uid, instrument_index),
    UNIQUE (revision_uid, episode_uid, instrument_uid),
    FOREIGN KEY (revision_uid, episode_uid)
      REFERENCES phase1_journal_history_revision_episodes (revision_uid, episode_uid),
    CHECK (instrument_index > 0 AND execution_count > 0),
    CHECK (opening_direction IS NULL OR opening_direction IN ('LONG', 'SHORT')),
    CHECK (length(instrument_projection_fingerprint) = 64)
);

CREATE TABLE phase1_journal_history_revision_executions (
    revision_uid VARCHAR NOT NULL,
    episode_uid VARCHAR NOT NULL,
    execution_index INTEGER NOT NULL,
    execution_uid VARCHAR NOT NULL,
    fill_uid VARCHAR NOT NULL,
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
    PRIMARY KEY (revision_uid, episode_uid, execution_index),
    UNIQUE (revision_uid, fill_uid),
    FOREIGN KEY (revision_uid, episode_uid)
      REFERENCES phase1_journal_history_revision_episodes (revision_uid, episode_uid),
    FOREIGN KEY (fill_uid) REFERENCES normalized_fills (fill_uid),
    CHECK (execution_index > 0 AND quantity > 0 AND multiplier > 0),
    CHECK (net_amount_reconciled = TRUE
           AND schwab_net_cash_movement = calculated_net_cash_movement),
    CHECK (length(execution_projection_fingerprint) = 64)
);

CREATE TABLE phase1_journal_history_revision_activations (
    activation_uid VARCHAR PRIMARY KEY,
    source_broker VARCHAR NOT NULL,
    source_account_id VARCHAR NOT NULL,
    activation_sequence INTEGER NOT NULL,
    revision_uid VARCHAR NOT NULL,
    previous_activation_uid VARCHAR,
    activation_reason VARCHAR NOT NULL,
    activated_at TIMESTAMP NOT NULL,
    UNIQUE (source_broker, source_account_id, activation_sequence),
    FOREIGN KEY (revision_uid) REFERENCES phase1_journal_history_revisions (revision_uid),
    FOREIGN KEY (previous_activation_uid)
      REFERENCES phase1_journal_history_revision_activations (activation_uid),
    CHECK (source_broker = 'schwab' AND activation_sequence > 0),
    CHECK (activation_reason IN ('legacy_bootstrap', 'history_extension', 'rollback'))
);

CREATE VIEW phase1_journal_current_revision_ids AS
SELECT source_broker, source_account_id, revision_uid, activation_uid,
       activation_sequence, activated_at
FROM (
    SELECT a.*, ROW_NUMBER() OVER (
        PARTITION BY source_broker, source_account_id
        ORDER BY activation_sequence DESC, activated_at DESC, activation_uid DESC
    ) AS row_num
    FROM phase1_journal_history_revision_activations a
) ranked
WHERE row_num = 1;

CREATE VIEW journal_current_trade_episodes AS
SELECT e.episode_uid, e.source_broker, e.source_account_id, e.primary_symbol,
       e.asset_class, e.strategy_type, e.strategy_label, e.opened_at, e.status,
       e.fill_count, e.leg_count, e.leg_summary, e.cashflow_label,
       e.net_quantity, e.gross_cashflow, e.commission, e.fees, e.updated_at
FROM phase1_journal_history_revision_episodes e
JOIN phase1_journal_current_revision_ids c USING (revision_uid)
UNION ALL
SELECT e.* FROM trade_episodes e
WHERE NOT EXISTS (
    SELECT 1 FROM phase1_journal_current_revision_ids c
    WHERE c.source_broker = e.source_broker
      AND c.source_account_id = e.source_account_id
);

CREATE VIEW journal_current_materialized_episodes AS
SELECT r.materialization_uid, e.episode_uid, e.scope_uid,
       e.materialization_lifecycle_quality AS lifecycle_quality,
       e.materialization_reason_code AS reason_code,
       e.source_fill_count, e.episode_fingerprint
FROM phase1_journal_history_revision_episodes e
JOIN phase1_journal_current_revision_ids c USING (revision_uid)
JOIN phase1_journal_history_revisions r USING (revision_uid)
UNION ALL
SELECT m.* FROM phase1_journal_materialized_episodes m
JOIN trade_episodes e USING (episode_uid)
WHERE NOT EXISTS (
    SELECT 1 FROM phase1_journal_current_revision_ids c
    WHERE c.source_broker = e.source_broker
      AND c.source_account_id = e.source_account_id
);

CREATE VIEW journal_current_materialized_episode_fills AS
SELECT r.materialization_uid, x.episode_uid, x.leg_index, x.fill_uid
FROM phase1_journal_history_revision_episode_fills x
JOIN phase1_journal_current_revision_ids c USING (revision_uid)
JOIN phase1_journal_history_revisions r USING (revision_uid)
UNION ALL
SELECT x.* FROM phase1_journal_materialized_episode_fills x
JOIN trade_episodes e USING (episode_uid)
WHERE NOT EXISTS (
    SELECT 1 FROM phase1_journal_current_revision_ids c
    WHERE c.source_broker = e.source_broker
      AND c.source_account_id = e.source_account_id
);

CREATE VIEW journal_current_projected_episodes AS
SELECT r.projection_uid, e.episode_uid, e.strategy_type, e.strategy_label,
       e.instrument_count, e.execution_count, e.lifecycle_sequence,
       e.lifecycle_count, e.instrument_summary,
       e.episode_projection_fingerprint
FROM phase1_journal_history_revision_episodes e
JOIN phase1_journal_current_revision_ids c USING (revision_uid)
JOIN phase1_journal_history_revisions r USING (revision_uid)
UNION ALL
SELECT p.* FROM phase1_journal_projected_episodes p
JOIN trade_episodes e USING (episode_uid)
WHERE NOT EXISTS (
    SELECT 1 FROM phase1_journal_current_revision_ids c
    WHERE c.source_broker = e.source_broker
      AND c.source_account_id = e.source_account_id
);

CREATE VIEW journal_current_projected_instruments AS
SELECT r.projection_uid, i.episode_uid, i.instrument_index, i.instrument_uid,
       i.asset_class, i.symbol, i.underlying_symbol, i.option_type, i.expiry,
       i.strike, i.multiplier, i.currency, i.opening_direction,
       i.execution_count, i.buy_quantity, i.sell_quantity,
       i.captured_quantity_delta, i.instrument_projection_fingerprint
FROM phase1_journal_history_revision_instruments i
JOIN phase1_journal_current_revision_ids c USING (revision_uid)
JOIN phase1_journal_history_revisions r USING (revision_uid)
UNION ALL
SELECT i.* FROM phase1_journal_projected_instruments i
JOIN trade_episodes e USING (episode_uid)
WHERE NOT EXISTS (
    SELECT 1 FROM phase1_journal_current_revision_ids c
    WHERE c.source_broker = e.source_broker
      AND c.source_account_id = e.source_account_id
);

CREATE VIEW journal_current_projected_executions AS
SELECT r.projection_uid, x.episode_uid, x.execution_index, x.execution_uid,
       x.fill_uid, x.instrument_uid, x.filled_at_utc, x.side, x.quantity,
       x.fill_price, x.multiplier, x.commission, x.fees, x.currency,
       x.schwab_net_cash_movement, x.calculated_net_cash_movement,
       x.net_amount_reconciled, x.execution_projection_fingerprint
FROM phase1_journal_history_revision_executions x
JOIN phase1_journal_current_revision_ids c USING (revision_uid)
JOIN phase1_journal_history_revisions r USING (revision_uid)
UNION ALL
SELECT x.* FROM phase1_journal_projected_executions x
JOIN trade_episodes e USING (episode_uid)
WHERE NOT EXISTS (
    SELECT 1 FROM phase1_journal_current_revision_ids c
    WHERE c.source_broker = e.source_broker
      AND c.source_account_id = e.source_account_id
);

CREATE VIEW journal_current_lifecycle_reconciliation_runs AS
SELECT r.reconciliation_uid,
       'onejournal.phase1-journal-lifecycle-reconciliation.v1' AS contract_version,
       r.assembly_uid, r.materialization_uid AS source_materialization_uid,
       r.source_account_id, r.asof_date, r.episode_count, r.closed_count,
       r.open_count, r.review_required_count, r.terminal_event_count,
       r.terminal_event_leg_count, r.matched_terminal_event_leg_count,
       r.lifecycle_final_status AS final_status,
       r.reconciliation_result_fingerprint AS result_fingerprint,
       r.created_at AS reconciled_at
FROM phase1_journal_history_revisions r
JOIN phase1_journal_current_revision_ids c USING (revision_uid)
UNION ALL
SELECT r.* FROM phase1_journal_lifecycle_reconciliation_runs r
WHERE NOT EXISTS (
    SELECT 1 FROM phase1_journal_current_revision_ids c
    WHERE c.source_broker = 'schwab'
      AND c.source_account_id = r.source_account_id
);

CREATE VIEW journal_current_episode_lifecycle_states AS
SELECT r.reconciliation_uid, e.episode_uid, e.prior_status,
       e.reconciled_status, e.lifecycle_quality, e.reason_code,
       e.position_reconciliation_status, e.matched_terminal_event_count,
       e.state_fingerprint
FROM phase1_journal_history_revision_episodes e
JOIN phase1_journal_current_revision_ids c USING (revision_uid)
JOIN phase1_journal_history_revisions r USING (revision_uid)
UNION ALL
SELECT s.* FROM phase1_journal_episode_lifecycle_states s
JOIN trade_episodes e USING (episode_uid)
WHERE NOT EXISTS (
    SELECT 1 FROM phase1_journal_current_revision_ids c
    WHERE c.source_broker = e.source_broker
      AND c.source_account_id = e.source_account_id
);

CREATE INDEX idx_phase1_history_revision_account
  ON phase1_journal_history_revisions (source_broker, source_account_id, created_at);
CREATE INDEX idx_phase1_history_revision_episode_scope
  ON phase1_journal_history_revision_episodes (revision_uid, scope_uid, opened_at);
CREATE INDEX idx_phase1_history_revision_activation
  ON phase1_journal_history_revision_activations (
    source_broker, source_account_id, activation_sequence
  );
