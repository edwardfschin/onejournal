"""Append-only Schwab history materialization revisions.

The module consumes an already validated assembly-v2 object.  It has no broker,
credential, filesystem discovery, deletion, or in-place rewrite capability.
Existing normalized fills are reused only when their stable economics match;
new fills and complete revision snapshots are appended atomically.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from typing import Any

import duckdb

from onejournal.journal.schwab_evidence_assembly import (
    SchwabPhase1EvidenceAssembly,
    canonical_schwab_evidence_json,
)
from onejournal.journal.schwab_evidence_materialization import (
    SchwabJournalMaterializationPlan,
    build_schwab_journal_materialization_plan,
)
from onejournal.journal.schwab_execution_projection import (
    ExecutionProjectionPlan,
    build_schwab_execution_projection_from_assembly,
)
from onejournal.journal.schwab_journal_lifecycle_reconciliation import (
    SchwabJournalLifecycleReconciliationPlan,
    build_schwab_journal_lifecycle_reconciliation,
)


HISTORY_REVISION_CONTRACT_VERSION = (
    "onejournal.history-materialization-revision.v1"
)
MIGRATION_VERSION = "0021"
MIGRATION_PATH = (
    Path(__file__).resolve().parents[3]
    / "scripts/journal/migrations/0021_add_append_only_history_revisions.sql"
)
REQUIRED_TABLES = {
    "phase1_journal_history_revisions",
    "phase1_journal_history_revision_episodes",
    "phase1_journal_history_revision_episode_fills",
    "phase1_journal_history_revision_instruments",
    "phase1_journal_history_revision_executions",
    "phase1_journal_history_revision_activations",
}


@dataclass(frozen=True)
class HistoryRevisionResult:
    revision_uid: str
    activation_uid: str
    activation_sequence: int
    predecessor_revision_uid: str | None
    fill_count: int
    new_fill_count: int
    reused_fill_count: int
    episode_count: int
    final_status: str
    created: bool
    replayed: bool


def _digest(value: object) -> str:
    return sha256(canonical_schwab_evidence_json(value).encode("utf-8")).hexdigest()


def _utc_naive(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("revision timestamp must include a timezone")
    return value.astimezone(UTC).replace(tzinfo=None)


def _utc_text(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("fill timestamp must include a timezone")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _database_contract(con: duckdb.DuckDBPyConnection) -> None:
    tables = {str(row[0]) for row in con.execute("SHOW TABLES").fetchall()}
    missing = REQUIRED_TABLES - tables
    if missing:
        raise ValueError(
            "database is missing migration 0021 table(s): "
            + ", ".join(sorted(missing))
        )
    expected = sha256(MIGRATION_PATH.read_bytes()).hexdigest()
    row = con.execute(
        "SELECT migration_name, file_checksum, status FROM schema_migrations WHERE version = ?",
        [MIGRATION_VERSION],
    ).fetchone()
    if row != ("add_append_only_history_revisions", expected, "applied"):
        raise ValueError("database migration 0021 ledger does not match repository")


def _stable_fill_row(fill: Any) -> tuple[Any, ...]:
    return (
        fill.fill_uid,
        fill.source_broker,
        fill.source_account_id,
        fill.source_fill_id,
        fill.source_order_id,
        fill.episode_group_id,
        fill.asof,
        _utc_naive(fill.filled_at),
        fill.asset_class,
        fill.symbol,
        fill.side,
        fill.quantity,
        fill.fill_price,
        fill.commission,
        fill.fees,
        fill.currency,
        fill.option_symbol,
        fill.underlying_symbol,
        fill.option_type,
        fill.expiry,
        fill.strike,
        fill.multiplier,
        fill.open_close,
        fill.execution_venue,
        fill.liquidity_flag,
        _utc_text(fill.filled_at),
    )


def _stored_stable_fill_row(
    con: duckdb.DuckDBPyConnection, fill_uid: str
) -> tuple[Any, ...] | None:
    return con.execute(
        """
        SELECT fill_uid, source_broker, source_account_id, source_fill_id,
               source_order_id, episode_group_id, asof_date, filled_at,
               asset_class, symbol, side, quantity, fill_price, commission,
               fees, currency, option_symbol, underlying_symbol, option_type,
               expiry, strike, multiplier, open_close, execution_venue,
               liquidity_flag, filled_at_utc
        FROM normalized_fills WHERE fill_uid = ?
        """,
        [fill_uid],
    ).fetchone()


def _insert_fill(
    con: duckdb.DuckDBPyConnection, fill: Any, *, import_run_id: str
) -> None:
    con.execute(
        """
        INSERT INTO normalized_fills (
            fill_uid, source_broker, source_account_id, source_fill_id,
            source_order_id, episode_group_id, asof_date, filled_at,
            asset_class, symbol, side, quantity, fill_price, commission, fees,
            currency, fetched_at, raw_path, option_symbol, underlying_symbol,
            option_type, expiry, strike, multiplier, open_close,
            execution_venue, liquidity_flag, import_run_id, filled_at_utc,
            fetched_at_utc
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                  ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            fill.fill_uid,
            fill.source_broker,
            fill.source_account_id,
            fill.source_fill_id,
            fill.source_order_id,
            fill.episode_group_id,
            fill.asof,
            _utc_naive(fill.filled_at),
            fill.asset_class,
            fill.symbol,
            fill.side,
            fill.quantity,
            fill.fill_price,
            fill.commission,
            fill.fees,
            fill.currency,
            _utc_naive(fill.fetched_at),
            fill.raw_path,
            fill.option_symbol,
            fill.underlying_symbol,
            fill.option_type,
            fill.expiry,
            fill.strike,
            fill.multiplier,
            fill.open_close,
            fill.execution_venue,
            fill.liquidity_flag,
            import_run_id,
            _utc_text(fill.filled_at),
            _utc_text(fill.fetched_at),
        ],
    )


def _current_activation(
    con: duckdb.DuckDBPyConnection, *, account_id: str
) -> tuple[str, str, int] | None:
    row = con.execute(
        """
        SELECT a.activation_uid, a.revision_uid, a.activation_sequence
        FROM phase1_journal_history_revision_activations a
        WHERE a.source_broker = 'schwab' AND a.source_account_id = ?
        ORDER BY a.activation_sequence DESC LIMIT 1
        """,
        [account_id],
    ).fetchone()
    return None if row is None else (str(row[0]), str(row[1]), int(row[2]))


def _activation_uid(
    *, account_id: str, sequence: int, revision_uid: str, reason: str
) -> str:
    return f"journal-history-activation:{_digest((account_id, sequence, revision_uid, reason))}"


def _insert_activation(
    con: duckdb.DuckDBPyConnection,
    *,
    account_id: str,
    sequence: int,
    revision_uid: str,
    previous_activation_uid: str | None,
    reason: str,
    activated_at: datetime,
) -> str:
    activation_uid = _activation_uid(
        account_id=account_id,
        sequence=sequence,
        revision_uid=revision_uid,
        reason=reason,
    )
    con.execute(
        """
        INSERT INTO phase1_journal_history_revision_activations (
            activation_uid, source_broker, source_account_id,
            activation_sequence, revision_uid, previous_activation_uid,
            activation_reason, activated_at
        ) VALUES (?, 'schwab', ?, ?, ?, ?, ?, ?)
        """,
        [
            activation_uid,
            account_id,
            sequence,
            revision_uid,
            previous_activation_uid,
            reason,
            _utc_naive(activated_at),
        ],
    )
    return activation_uid


def _bootstrap_legacy_revision(
    con: duckdb.DuckDBPyConnection,
    *,
    account_id: str,
    materialization_uid: str,
    created_at: datetime,
) -> tuple[str, str]:
    run = con.execute(
        """
        SELECT assembly_uid, asof_date, fill_count, episode_count,
               lifecycle_resolved_scope_count, review_required_scope_count,
               result_fingerprint
        FROM phase1_journal_materialization_runs
        WHERE materialization_uid = ? AND source_account_id = ?
        """,
        [materialization_uid, account_id],
    ).fetchone()
    if run is None:
        raise ValueError("explicit predecessor materialization was not found")
    projection = con.execute(
        """
        SELECT projection_uid, instrument_count, execution_count,
               result_fingerprint
        FROM phase1_journal_execution_projection_runs
        WHERE materialization_uid = ?
        """,
        [materialization_uid],
    ).fetchone()
    if projection is None:
        raise ValueError("predecessor lacks its exact execution projection")
    lifecycle = con.execute(
        """
        SELECT reconciliation_uid, assembly_uid, asof_date, closed_count,
               open_count, review_required_count, terminal_event_count,
               terminal_event_leg_count, matched_terminal_event_leg_count,
               final_status, result_fingerprint
        FROM phase1_journal_lifecycle_reconciliation_runs
        WHERE source_account_id = ?
        ORDER BY asof_date DESC, reconciled_at DESC, reconciliation_uid DESC
        LIMIT 1
        """,
        [account_id],
    ).fetchone()
    if lifecycle is None or sum(int(value) for value in lifecycle[3:6]) != int(run[3]):
        raise ValueError("predecessor lacks a complete lifecycle reconciliation")
    history_start = con.execute(
        """
        SELECT MIN(f.asof_date)
        FROM phase1_journal_materialized_fills m
        JOIN normalized_fills f USING (fill_uid)
        WHERE m.materialization_uid = ?
        """,
        [materialization_uid],
    ).fetchone()[0]
    projection_uid = str(projection[0])
    reconciliation_uid = str(lifecycle[0])
    fingerprint = _digest(
        {
            "origin": "legacy_bootstrap",
            "materialization": str(run[6]),
            "projection": str(projection[3]),
            "reconciliation": str(lifecycle[10]),
        }
    )
    revision_uid = f"journal-history-revision:{fingerprint}"
    con.execute(
        "INSERT INTO phase1_journal_history_revisions VALUES ("
        + ", ".join("?" for _ in range(30))
        + ")",
        [
            revision_uid,
            HISTORY_REVISION_CONTRACT_VERSION,
            "schwab",
            account_id,
            str(run[0]),
            materialization_uid,
            projection_uid,
            reconciliation_uid,
            history_start,
            run[1],
            run[1],
            int(run[2]),
            int(run[3]),
            int(projection[1]),
            int(projection[2]),
            int(run[4]),
            int(run[5]),
            int(lifecycle[3]),
            int(lifecycle[4]),
            int(lifecycle[5]),
            int(lifecycle[6]),
            int(lifecycle[7]),
            int(lifecycle[8]),
            str(lifecycle[9]),
            str(run[6]),
            str(projection[3]),
            str(lifecycle[10]),
            "legacy_bootstrap",
            fingerprint,
            _utc_naive(created_at),
        ],
    )
    rows = con.execute(
        """
        SELECT e.episode_uid, e.source_broker, e.source_account_id,
               e.primary_symbol, e.asset_class, e.strategy_type,
               e.strategy_label, e.opened_at, e.status, e.fill_count,
               e.leg_count, e.leg_summary, e.cashflow_label, e.net_quantity,
               e.gross_cashflow, e.commission, e.fees, e.updated_at,
               m.scope_uid, m.lifecycle_quality, m.reason_code,
               m.source_fill_count, m.episode_fingerprint,
               p.strategy_type, p.strategy_label, p.instrument_count,
               p.execution_count, p.lifecycle_sequence, p.lifecycle_count,
               p.instrument_summary, p.episode_projection_fingerprint,
               s.prior_status, s.reconciled_status, s.lifecycle_quality,
               s.reason_code, s.position_reconciliation_status,
               s.matched_terminal_event_count, s.state_fingerprint
        FROM phase1_journal_materialized_episodes m
        JOIN trade_episodes e USING (episode_uid)
        JOIN phase1_journal_projected_episodes p USING (episode_uid)
        JOIN phase1_journal_episode_lifecycle_states s USING (episode_uid)
        WHERE m.materialization_uid = ? AND p.projection_uid = ?
          AND s.reconciliation_uid = ?
        ORDER BY e.episode_uid
        """,
        [materialization_uid, projection_uid, reconciliation_uid],
    ).fetchall()
    if len(rows) != int(run[3]):
        raise ValueError("predecessor episode snapshot is incomplete")
    con.executemany(
        "INSERT INTO phase1_journal_history_revision_episodes VALUES ("
        + ", ".join("?" for _ in range(37))
        + ")",
        [
            (
                revision_uid,
                *row[:18],
                row[18],
                row[19],
                row[20],
                row[33],
                row[34],
                row[21],
                row[22],
                row[25],
                row[26],
                row[27],
                row[28],
                row[29],
                row[30],
                row[31],
                row[32],
                row[35],
                row[36],
                row[37],
            )
            for row in rows
        ],
    )
    con.execute(
        """
        INSERT INTO phase1_journal_history_revision_episode_fills
        SELECT ?, x.episode_uid, x.leg_index, x.fill_uid,
               f.source_record_fingerprint
        FROM phase1_journal_materialized_episode_fills x
        JOIN phase1_journal_materialized_fills f
          ON f.materialization_uid = x.materialization_uid
         AND f.fill_uid = x.fill_uid
        WHERE x.materialization_uid = ?
        """,
        [revision_uid, materialization_uid],
    )
    con.execute(
        """
        INSERT INTO phase1_journal_history_revision_instruments
        SELECT ?, episode_uid, instrument_index, instrument_uid, asset_class,
               symbol, underlying_symbol, option_type, expiry, strike,
               multiplier, currency, opening_direction, execution_count,
               buy_quantity, sell_quantity, captured_quantity_delta,
               instrument_projection_fingerprint
        FROM phase1_journal_projected_instruments WHERE projection_uid = ?
        """,
        [revision_uid, projection_uid],
    )
    con.execute(
        """
        INSERT INTO phase1_journal_history_revision_executions
        SELECT ?, episode_uid, execution_index, execution_uid, fill_uid,
               instrument_uid, filled_at_utc, side, quantity, fill_price,
               multiplier, commission, fees, currency,
               schwab_net_cash_movement, calculated_net_cash_movement,
               net_amount_reconciled, execution_projection_fingerprint
        FROM phase1_journal_projected_executions WHERE projection_uid = ?
        """,
        [revision_uid, projection_uid],
    )
    activation_uid = _insert_activation(
        con,
        account_id=account_id,
        sequence=1,
        revision_uid=revision_uid,
        previous_activation_uid=None,
        reason="legacy_bootstrap",
        activated_at=created_at,
    )
    return revision_uid, activation_uid


def _insert_new_revision(
    con: duckdb.DuckDBPyConnection,
    *,
    assembly: SchwabPhase1EvidenceAssembly,
    materialization: SchwabJournalMaterializationPlan,
    projection: ExecutionProjectionPlan,
    lifecycle: SchwabJournalLifecycleReconciliationPlan,
    revision_uid: str,
    fingerprint: str,
    created_at: datetime,
) -> tuple[int, int]:
    new_fills = 0
    for fill in materialization.fills:
        stored = _stored_stable_fill_row(con, fill.fill_uid)
        if stored is None:
            new_fills += 1
        elif stored != _stable_fill_row(fill):
            raise ValueError("existing normalized fill differs from reconstructed evidence")
    if new_fills:
        con.execute(
            """
            INSERT INTO import_runs (
                import_run_id, source_type, source_path, asof_date, imported_at,
                row_count, status, notes
            ) VALUES (?, 'schwab_history_revision', NULL, ?, ?, ?, 'completed',
                      'append-only normalized fills for a history revision')
            """,
            [revision_uid, assembly.asof, _utc_naive(created_at), new_fills],
        )
        for fill in materialization.fills:
            if _stored_stable_fill_row(con, fill.fill_uid) is None:
                _insert_fill(con, fill, import_run_id=revision_uid)

    con.execute(
        "INSERT INTO phase1_journal_history_revisions VALUES ("
        + ", ".join("?" for _ in range(30))
        + ")",
        [
            revision_uid,
            HISTORY_REVISION_CONTRACT_VERSION,
            "schwab",
            assembly.source_account_id,
            assembly.assembly_uid,
            materialization.materialization_uid,
            projection.projection_uid,
            lifecycle.reconciliation_uid,
            assembly.lifecycle_window_start,
            assembly.lifecycle_window_end,
            assembly.asof,
            len(materialization.fills),
            len(materialization.episodes),
            len(projection.instruments),
            len(projection.executions),
            materialization.lifecycle_resolved_scope_count,
            materialization.review_required_scope_count,
            lifecycle.closed_count,
            lifecycle.open_count,
            lifecycle.review_required_count,
            lifecycle.terminal_event_count,
            lifecycle.terminal_event_leg_count,
            lifecycle.matched_terminal_event_leg_count,
            lifecycle.final_status,
            materialization.result_fingerprint,
            projection.result_fingerprint,
            lifecycle.result_fingerprint,
            "history_reconstruction",
            fingerprint,
            _utc_naive(created_at),
        ],
    )
    projected_by_episode = {item.episode_uid: item for item in projection.episodes}
    states_by_episode = {item.episode_uid: item for item in lifecycle.states}
    fill_fingerprints = dict(materialization.source_record_fingerprints)
    episode_rows = []
    fill_rows = []
    for item in materialization.episodes:
        preview = item.preview
        projected = projected_by_episode[preview.episode_uid]
        state = states_by_episode[preview.episode_uid]
        financial = item.lifecycle_quality != "review_required"
        episode_rows.append(
            (
                revision_uid,
                preview.episode_uid,
                preview.source_broker,
                preview.source_account_id,
                preview.primary_symbol,
                preview.asset_class,
                preview.strategy_type,
                preview.strategy_label,
                _utc_naive(preview.opened_at),
                preview.status,
                preview.fill_count,
                preview.leg_count,
                preview.leg_summary,
                preview.cashflow_label,
                preview.net_quantity if financial else None,
                preview.gross_cashflow if financial else None,
                preview.total_commission if financial else None,
                preview.total_fees if financial else None,
                _utc_naive(created_at),
                item.scope_uid,
                item.lifecycle_quality,
                item.reason_code,
                state.lifecycle_quality,
                state.reason_code,
                len(item.fill_uids),
                item.episode_fingerprint,
                projected.instrument_count,
                projected.execution_count,
                projected.lifecycle_sequence,
                projected.lifecycle_count,
                projected.instrument_summary,
                projected.episode_projection_fingerprint,
                state.prior_status,
                state.reconciled_status,
                state.position_reconciliation_status,
                state.matched_terminal_event_count,
                state.state_fingerprint,
            )
        )
        fill_rows.extend(
            (
                revision_uid,
                preview.episode_uid,
                index,
                fill_uid,
                fill_fingerprints[fill_uid],
            )
            for index, fill_uid in enumerate(item.fill_uids, start=1)
        )
    con.executemany(
        "INSERT INTO phase1_journal_history_revision_episodes VALUES ("
        + ", ".join("?" for _ in range(37))
        + ")",
        episode_rows,
    )
    con.executemany(
        "INSERT INTO phase1_journal_history_revision_episode_fills VALUES (?, ?, ?, ?, ?)",
        fill_rows,
    )
    con.executemany(
        """
        INSERT INTO phase1_journal_history_revision_instruments VALUES (
          ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        )
        """,
        [(revision_uid, *tuple(asdict(item).values())) for item in projection.instruments],
    )
    con.executemany(
        """
        INSERT INTO phase1_journal_history_revision_executions VALUES (
          ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, TRUE, ?
        )
        """,
        [
            (
                revision_uid,
                item.episode_uid,
                item.execution_index,
                item.execution_uid,
                item.fill_uid,
                item.instrument_uid,
                item.filled_at_utc,
                item.side,
                item.quantity,
                item.fill_price,
                item.multiplier,
                item.commission,
                item.fees,
                item.currency,
                item.schwab_net_cash_movement,
                item.calculated_net_cash_movement,
                item.execution_projection_fingerprint,
            )
            for item in projection.executions
        ],
    )
    return new_fills, len(materialization.fills) - new_fills


def persist_schwab_history_revision(
    db_path: Path,
    assembly: SchwabPhase1EvidenceAssembly,
    *,
    predecessor_materialization_uid: str,
    created_at: datetime | None = None,
) -> HistoryRevisionResult:
    """Append and activate one exact reconstruction, bootstrapping legacy once."""

    timestamp = created_at or datetime.now(UTC)
    materialization = build_schwab_journal_materialization_plan(assembly)
    projection = build_schwab_execution_projection_from_assembly(
        assembly, materialization=materialization
    )
    lifecycle = build_schwab_journal_lifecycle_reconciliation(assembly)
    if lifecycle.source_materialization_uid != materialization.materialization_uid:
        raise ValueError("lifecycle and materialization plans differ")
    fingerprint = _digest(
        {
            "contract_version": HISTORY_REVISION_CONTRACT_VERSION,
            "assembly": assembly.result_fingerprint,
            "materialization": materialization.result_fingerprint,
            "projection": projection.result_fingerprint,
            "lifecycle": lifecycle.result_fingerprint,
        }
    )
    revision_uid = f"journal-history-revision:{fingerprint}"
    if db_path.is_symlink() or not db_path.is_file():
        raise ValueError("database must be a pre-existing non-symlink file")
    with duckdb.connect(str(db_path)) as con:
        _database_contract(con)
        evidence = con.execute(
            "SELECT result_fingerprint FROM phase1_schwab_evidence_v2_import_runs WHERE assembly_uid = ?",
            [assembly.assembly_uid],
        ).fetchone()
        if evidence != (assembly.result_fingerprint,):
            raise ValueError("exact assembly v2 must be persisted before revision")
        existing = con.execute(
            "SELECT source_account_id, result_fingerprint FROM phase1_journal_history_revisions WHERE revision_uid = ?",
            [revision_uid],
        ).fetchone()
        current = _current_activation(con, account_id=assembly.source_account_id)
        if existing is not None:
            if existing != (assembly.source_account_id, fingerprint):
                raise ValueError("history revision identity conflict")
            if current is None or current[1] != revision_uid:
                raise ValueError("existing revision is not current; explicit rollback is required")
            return HistoryRevisionResult(
                revision_uid=revision_uid,
                activation_uid=current[0],
                activation_sequence=current[2],
                predecessor_revision_uid=None,
                fill_count=len(materialization.fills),
                new_fill_count=0,
                reused_fill_count=len(materialization.fills),
                episode_count=len(materialization.episodes),
                final_status=lifecycle.final_status,
                created=False,
                replayed=True,
            )

        con.execute("BEGIN TRANSACTION")
        try:
            predecessor_revision_uid: str | None
            if current is None:
                predecessor_revision_uid, previous_activation_uid = (
                    _bootstrap_legacy_revision(
                        con,
                        account_id=assembly.source_account_id,
                        materialization_uid=predecessor_materialization_uid,
                        created_at=timestamp,
                    )
                )
                current = (previous_activation_uid, predecessor_revision_uid, 1)
            else:
                predecessor_revision_uid = current[1]
                predecessor_materialization = con.execute(
                    "SELECT materialization_uid FROM phase1_journal_history_revisions WHERE revision_uid = ?",
                    [predecessor_revision_uid],
                ).fetchone()
                if predecessor_materialization != (predecessor_materialization_uid,):
                    raise ValueError("explicit predecessor is not the current revision")

            new_count, reused_count = _insert_new_revision(
                con,
                assembly=assembly,
                materialization=materialization,
                projection=projection,
                lifecycle=lifecycle,
                revision_uid=revision_uid,
                fingerprint=fingerprint,
                created_at=timestamp,
            )
            sequence = current[2] + 1
            activation_uid = _insert_activation(
                con,
                account_id=assembly.source_account_id,
                sequence=sequence,
                revision_uid=revision_uid,
                previous_activation_uid=current[0],
                reason="history_extension",
                activated_at=timestamp,
            )
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
    return HistoryRevisionResult(
        revision_uid=revision_uid,
        activation_uid=activation_uid,
        activation_sequence=sequence,
        predecessor_revision_uid=predecessor_revision_uid,
        fill_count=len(materialization.fills),
        new_fill_count=new_count,
        reused_fill_count=reused_count,
        episode_count=len(materialization.episodes),
        final_status=lifecycle.final_status,
        created=True,
        replayed=False,
    )


def activate_prior_history_revision(
    db_path: Path,
    *,
    revision_uid: str,
    activated_at: datetime | None = None,
) -> str:
    """Append a rollback activation; never mutate or delete revision content."""

    timestamp = activated_at or datetime.now(UTC)
    with duckdb.connect(str(db_path)) as con:
        _database_contract(con)
        target = con.execute(
            "SELECT source_account_id FROM phase1_journal_history_revisions WHERE revision_uid = ?",
            [revision_uid],
        ).fetchone()
        if target is None:
            raise ValueError("rollback revision was not found")
        account_id = str(target[0])
        current = _current_activation(con, account_id=account_id)
        if current is None:
            raise ValueError("account has no revision activation history")
        if current[1] == revision_uid:
            return current[0]
        con.execute("BEGIN TRANSACTION")
        try:
            activation_uid = _insert_activation(
                con,
                account_id=account_id,
                sequence=current[2] + 1,
                revision_uid=revision_uid,
                previous_activation_uid=current[0],
                reason="rollback",
                activated_at=timestamp,
            )
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
    return activation_uid
