"""Atomic persistence for lifecycle-complete Schwab assembly v2 and journal state."""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
import json
from pathlib import Path

import duckdb

from onejournal.journal.schwab_evidence_assembly import (
    FAMILY_ORDER_V2,
    SCHWAB_PHASE1_EVIDENCE_ASSEMBLY_V2,
    SchwabEvidenceFamily,
    SchwabEvidenceReconciliation,
    SchwabPhase1EvidenceAssembly,
    canonical_schwab_evidence_json,
    freeze_schwab_evidence_value,
    validate_schwab_phase1_evidence_assembly,
)
from onejournal.journal.schwab_evidence_import_repository import (
    SchwabEvidencePersistenceResult,
)
from onejournal.journal.schwab_journal_lifecycle_reconciliation import (
    SchwabJournalLifecycleReconciliationPlan,
    build_schwab_journal_lifecycle_reconciliation,
)


MIGRATION_VERSION = "0020"
MIGRATION_PATH = (
    Path(__file__).resolve().parents[3]
    / "scripts/journal/migrations/0020_add_phase1_lifecycle_reconciliation.sql"
)
REQUIRED_TABLES = {
    "phase1_schwab_evidence_v2_import_runs",
    "phase1_schwab_evidence_v2_import_families",
    "phase1_journal_lifecycle_reconciliation_runs",
    "phase1_journal_episode_lifecycle_states",
}


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _utc_text(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("assembled_at_utc must include a timezone")
    return value.astimezone(UTC).isoformat()


def _utc_naive(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("reconciled_at must include a timezone")
    return value.astimezone(UTC).replace(tzinfo=None)


def _database_contract(connection: duckdb.DuckDBPyConnection) -> None:
    tables = {str(row[0]) for row in connection.execute("SHOW TABLES").fetchall()}
    missing = REQUIRED_TABLES - tables
    if missing:
        raise ValueError(
            "database is missing migration 0020 table(s): "
            + ", ".join(sorted(missing))
        )
    row = connection.execute(
        "SELECT migration_name, file_checksum, status FROM schema_migrations WHERE version = ?",
        [MIGRATION_VERSION],
    ).fetchone()
    expected = sha256(MIGRATION_PATH.read_bytes()).hexdigest()
    if row != ("add_phase1_lifecycle_reconciliation", expected, "applied"):
        raise ValueError("database migration 0020 ledger does not match repository")


def _expected_run(assembly: SchwabPhase1EvidenceAssembly) -> tuple[object, ...]:
    reconciliation = assembly.reconciliation
    return (
        assembly.contract_version,
        assembly.provider,
        assembly.connection_uid,
        assembly.source_account_id,
        assembly.asof,
        _utc_text(assembly.assembled_at_utc),
        assembly.lifecycle_window_start,
        assembly.lifecycle_window_end,
        reconciliation.matched_fill_rows,
        reconciliation.order_only_fill_rows,
        reconciliation.transaction_only_fill_rows,
        reconciliation.position_count,
        reconciliation.quote_count,
        reconciliation.positions_without_quotes,
        reconciliation.session_count,
        reconciliation.cash_review_required_rows,
        reconciliation.all_positions_have_quotes,
        reconciliation.all_quotes_have_session_authority,
        assembly.final_status,
        assembly.result_fingerprint,
    )


def _expected_families(
    assembly: SchwabPhase1EvidenceAssembly,
) -> list[tuple[object, ...]]:
    return sorted(
        (
            family.family,
            _json(list(family.source_manifest_sha256s)),
            _json(list(family.source_raw_sha256s)),
            family.source_record_count,
            family.normalized_record_count,
            family.excluded_record_count,
            _json(list(family.exclusion_reasons)),
            canonical_schwab_evidence_json(family.records),
            family.family_fingerprint,
        )
        for family in assembly.families
    )


def persist_schwab_phase1_evidence_assembly_v2(
    db_path: Path,
    assembly: SchwabPhase1EvidenceAssembly,
) -> SchwabEvidencePersistenceResult:
    """Append v2 atomically and accept only an exact replay."""

    validate_schwab_phase1_evidence_assembly(assembly)
    if assembly.contract_version != SCHWAB_PHASE1_EVIDENCE_ASSEMBLY_V2:
        raise ValueError("v2 persistence requires assembly v2")
    if db_path.is_symlink() or not db_path.is_file():
        raise ValueError("database must be a pre-existing non-symlink file")
    con = duckdb.connect(str(db_path))
    began = False
    try:
        _database_contract(con)
        con.execute("BEGIN TRANSACTION")
        began = True
        existing = con.execute(
            """
            SELECT contract_version, provider, connection_uid,
                   source_account_id, asof_date, assembled_at_utc,
                   lifecycle_window_start, lifecycle_window_end,
                   matched_fill_rows, order_only_fill_rows,
                   transaction_only_fill_rows, position_count, quote_count,
                   positions_without_quotes, session_count,
                   cash_review_required_rows, all_positions_have_quotes,
                   all_quotes_have_session_authority, final_status,
                   result_fingerprint
            FROM phase1_schwab_evidence_v2_import_runs WHERE assembly_uid = ?
            """,
            [assembly.assembly_uid],
        ).fetchone()
        if existing is not None:
            if existing != _expected_run(assembly):
                raise ValueError("assembly identity conflict: stored v2 content differs")
            stored = con.execute(
                """
                SELECT family, source_manifest_sha256s_json,
                       source_raw_sha256s_json, source_record_count,
                       normalized_record_count, excluded_record_count,
                       exclusion_reasons_json, records_json, family_fingerprint
                FROM phase1_schwab_evidence_v2_import_families
                WHERE assembly_uid = ? ORDER BY family
                """,
                [assembly.assembly_uid],
            ).fetchall()
            if stored != _expected_families(assembly):
                raise ValueError("stored v2 assembly family set is incomplete or changed")
            con.execute("COMMIT")
            began = False
            return SchwabEvidencePersistenceResult(
                assembly_uid=assembly.assembly_uid,
                family_count=len(assembly.families),
                normalized_record_count=sum(
                    family.normalized_record_count for family in assembly.families
                ),
                created=False,
                replayed=True,
            )

        con.execute(
            """
            INSERT INTO phase1_schwab_evidence_v2_import_runs VALUES (
              ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            [assembly.assembly_uid, *_expected_run(assembly)],
        )
        con.executemany(
            """
            INSERT INTO phase1_schwab_evidence_v2_import_families VALUES (
              ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            [
                (assembly.assembly_uid, *row)
                for row in _expected_families(assembly)
            ],
        )
        con.execute("COMMIT")
        began = False
        return SchwabEvidencePersistenceResult(
            assembly_uid=assembly.assembly_uid,
            family_count=len(assembly.families),
            normalized_record_count=sum(
                family.normalized_record_count for family in assembly.families
            ),
            created=True,
            replayed=False,
        )
    except Exception:
        if began:
            con.execute("ROLLBACK")
        raise
    finally:
        con.close()


def load_schwab_phase1_evidence_assembly_v2(
    db_path: Path, *, assembly_uid: str
) -> SchwabPhase1EvidenceAssembly:
    """Read and validate one exact persisted v2 assembly."""

    if db_path.is_symlink() or not db_path.is_file():
        raise ValueError("database must be a pre-existing non-symlink file")
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        _database_contract(con)
        run = con.execute(
            """
            SELECT assembly_uid, contract_version, provider, connection_uid,
                   source_account_id, asof_date, assembled_at_utc,
                   lifecycle_window_start, lifecycle_window_end,
                   matched_fill_rows, order_only_fill_rows,
                   transaction_only_fill_rows, position_count, quote_count,
                   positions_without_quotes, session_count,
                   cash_review_required_rows, all_positions_have_quotes,
                   all_quotes_have_session_authority, final_status,
                   result_fingerprint
            FROM phase1_schwab_evidence_v2_import_runs WHERE assembly_uid = ?
            """,
            [assembly_uid],
        ).fetchone()
        if run is None:
            raise ValueError("exact Schwab v2 evidence assembly was not found")
        rows = con.execute(
            """
            SELECT family, source_manifest_sha256s_json,
                   source_raw_sha256s_json, source_record_count,
                   normalized_record_count, excluded_record_count,
                   exclusion_reasons_json, records_json, family_fingerprint
            FROM phase1_schwab_evidence_v2_import_families
            WHERE assembly_uid = ?
            """,
            [assembly_uid],
        ).fetchall()
    finally:
        con.close()
    try:
        by_name = {
            str(row[0]): SchwabEvidenceFamily(
                family=str(row[0]),
                source_manifest_sha256s=tuple(json.loads(str(row[1]))),
                source_raw_sha256s=tuple(json.loads(str(row[2]))),
                source_record_count=int(row[3]),
                normalized_record_count=int(row[4]),
                excluded_record_count=int(row[5]),
                exclusion_reasons=tuple(json.loads(str(row[6]))),
                records=tuple(
                    freeze_schwab_evidence_value(record)
                    for record in json.loads(str(row[7]))
                ),
                family_fingerprint=str(row[8]),
            )
            for row in rows
        }
        families = tuple(by_name[name] for name in FAMILY_ORDER_V2)
        assembled_at = datetime.fromisoformat(str(run[6]))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("stored Schwab v2 evidence assembly is malformed") from exc
    assembly = SchwabPhase1EvidenceAssembly(
        assembly_uid=str(run[0]),
        contract_version=str(run[1]),
        provider=str(run[2]),
        connection_uid=str(run[3]),
        source_account_id=str(run[4]),
        asof=run[5],
        assembled_at_utc=assembled_at,
        lifecycle_window_start=run[7],
        lifecycle_window_end=run[8],
        families=families,
        reconciliation=SchwabEvidenceReconciliation(
            matched_fill_rows=int(run[9]),
            order_only_fill_rows=int(run[10]),
            transaction_only_fill_rows=int(run[11]),
            position_count=int(run[12]),
            quote_count=int(run[13]),
            positions_without_quotes=int(run[14]),
            session_count=int(run[15]),
            cash_review_required_rows=int(run[16]),
            all_positions_have_quotes=bool(run[17]),
            all_quotes_have_session_authority=bool(run[18]),
        ),
        final_status=str(run[19]),
        result_fingerprint=str(run[20]),
    )
    validate_schwab_phase1_evidence_assembly(assembly)
    return assembly


def _verify_operational_basis(
    con: duckdb.DuckDBPyConnection,
    plan: SchwabJournalLifecycleReconciliationPlan,
) -> None:
    stored = con.execute(
        """
        SELECT episode_uid, status FROM trade_episodes
        WHERE source_account_id = ? ORDER BY episode_uid
        """,
        [plan.source_account_id],
    ).fetchall()
    expected = sorted((state.episode_uid, state.prior_status) for state in plan.states)
    if stored != expected:
        raise ValueError(
            "operational episodes do not exactly match the v2 reconciliation basis"
        )


def persist_schwab_journal_lifecycle_reconciliation(
    db_path: Path,
    assembly: SchwabPhase1EvidenceAssembly,
    *,
    reconciled_at: datetime | None = None,
) -> SchwabJournalLifecycleReconciliationPlan:
    """Persist one additive episode-state projection or verify exact replay."""

    persisted = load_schwab_phase1_evidence_assembly_v2(
        db_path, assembly_uid=assembly.assembly_uid
    )
    if persisted.result_fingerprint != assembly.result_fingerprint:
        raise ValueError("database does not contain the exact supplied v2 assembly")
    plan = build_schwab_journal_lifecycle_reconciliation(assembly)
    timestamp = _utc_naive(reconciled_at or datetime.now(UTC))
    con = duckdb.connect(str(db_path))
    began = False
    try:
        _database_contract(con)
        _verify_operational_basis(con, plan)
        existing = con.execute(
            """
            SELECT contract_version, assembly_uid, source_materialization_uid,
                   source_account_id, asof_date, episode_count, closed_count,
                   open_count, review_required_count, terminal_event_count,
                   terminal_event_leg_count, matched_terminal_event_leg_count,
                   final_status, result_fingerprint
            FROM phase1_journal_lifecycle_reconciliation_runs
            WHERE reconciliation_uid = ?
            """,
            [plan.reconciliation_uid],
        ).fetchone()
        expected_run = (
            plan.contract_version,
            plan.assembly_uid,
            plan.source_materialization_uid,
            plan.source_account_id,
            plan.asof,
            len(plan.states),
            plan.closed_count,
            plan.open_count,
            plan.review_required_count,
            plan.terminal_event_count,
            plan.terminal_event_leg_count,
            plan.matched_terminal_event_leg_count,
            plan.final_status,
            plan.result_fingerprint,
        )
        expected_states = [
            (
                state.episode_uid,
                state.prior_status,
                state.reconciled_status,
                state.lifecycle_quality,
                state.reason_code,
                state.position_reconciliation_status,
                state.matched_terminal_event_count,
                state.state_fingerprint,
            )
            for state in plan.states
        ]
        if existing is not None:
            if existing != expected_run:
                raise ValueError("journal lifecycle reconciliation identity conflict")
            stored_states = con.execute(
                """
                SELECT episode_uid, prior_status, reconciled_status,
                       lifecycle_quality, reason_code,
                       position_reconciliation_status,
                       matched_terminal_event_count, state_fingerprint
                FROM phase1_journal_episode_lifecycle_states
                WHERE reconciliation_uid = ? ORDER BY episode_uid
                """,
                [plan.reconciliation_uid],
            ).fetchall()
            if stored_states != expected_states:
                raise ValueError("stored journal lifecycle states differ")
            return plan

        con.execute("BEGIN TRANSACTION")
        began = True
        con.execute(
            """
            INSERT INTO phase1_journal_lifecycle_reconciliation_runs VALUES (
              ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            [plan.reconciliation_uid, *expected_run, timestamp],
        )
        con.executemany(
            """
            INSERT INTO phase1_journal_episode_lifecycle_states VALUES (
              ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            [
                (plan.reconciliation_uid, *state)
                for state in expected_states
            ],
        )
        con.execute("COMMIT")
        began = False
        return plan
    except Exception:
        if began:
            con.execute("ROLLBACK")
        raise
    finally:
        con.close()
