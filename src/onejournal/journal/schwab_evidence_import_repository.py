"""Atomic persistence for versioned Phase 1 Schwab evidence assemblies."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
import json
from pathlib import Path

import duckdb

from onejournal.journal.schwab_evidence_assembly import (
    FAMILY_ORDER,
    SchwabEvidenceFamily,
    SchwabEvidenceReconciliation,
    SchwabPhase1EvidenceAssembly,
    canonical_schwab_evidence_json,
    freeze_schwab_evidence_value,
    validate_schwab_phase1_evidence_assembly,
)


REQUIRED_TABLES = {
    "phase1_schwab_evidence_import_runs",
    "phase1_schwab_evidence_import_families",
}
MIGRATION_VERSION = "0016"
MIGRATION_PATH = (
    Path(__file__).resolve().parents[3]
    / "scripts/journal/migrations/0016_add_phase1_schwab_evidence_assemblies.sql"
)


@dataclass(frozen=True)
class SchwabEvidencePersistenceResult:
    assembly_uid: str
    family_count: int
    normalized_record_count: int
    created: bool
    replayed: bool


def _table_names(connection: duckdb.DuckDBPyConnection) -> set[str]:
    return {row[0] for row in connection.execute("SHOW TABLES").fetchall()}


def _validate_database_contract(connection: duckdb.DuckDBPyConnection) -> None:
    tables = _table_names(connection)
    missing = REQUIRED_TABLES - tables
    if missing:
        raise ValueError(
            "database is missing migration 0016 table(s): "
            + ", ".join(sorted(missing))
        )
    if "schema_migrations" not in tables:
        raise ValueError("database is missing the migration ledger")
    row = connection.execute(
        """
        SELECT migration_name, file_checksum, status
        FROM schema_migrations
        WHERE version = ?
        """,
        [MIGRATION_VERSION],
    ).fetchone()
    expected_checksum = sha256(MIGRATION_PATH.read_bytes()).hexdigest()
    if row != (
        "add_phase1_schwab_evidence_assemblies",
        expected_checksum,
        "applied",
    ):
        raise ValueError("database migration 0016 ledger does not match repository")


def _utc_text(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("assembled_at_utc must include a timezone")
    return value.astimezone(UTC).isoformat()


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def persist_schwab_phase1_evidence_assembly(
    db_path: Path,
    assembly: SchwabPhase1EvidenceAssembly,
) -> SchwabEvidencePersistenceResult:
    """Append one complete assembly atomically; accept only identical replay."""

    validate_schwab_phase1_evidence_assembly(assembly)
    if db_path.is_symlink() or not db_path.is_file():
        raise ValueError("database must be a pre-existing non-symlink file")
    connection = duckdb.connect(str(db_path))
    began = False
    try:
        _validate_database_contract(connection)
        connection.execute("BEGIN TRANSACTION")
        began = True
        existing = connection.execute(
            """
            SELECT contract_version, provider, connection_uid,
                   source_account_id, asof_date, assembled_at_utc,
                   lifecycle_window_start, lifecycle_window_end,
                   matched_fill_rows, order_only_fill_rows,
                   transaction_only_fill_rows, position_count, quote_count,
                   positions_without_quotes, session_count,
                   cash_review_required_rows,
                   all_positions_have_quotes,
                   all_quotes_have_session_authority, final_status,
                   result_fingerprint
            FROM phase1_schwab_evidence_import_runs
            WHERE assembly_uid = ?
            """,
            [assembly.assembly_uid],
        ).fetchone()
        if existing is not None:
            reconciliation = assembly.reconciliation
            expected_run = (
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
            if existing != expected_run:
                raise ValueError("assembly identity conflict: stored content differs")
            stored_families = connection.execute(
                """
                SELECT family, source_manifest_sha256s_json,
                       source_raw_sha256s_json, source_record_count,
                       normalized_record_count, excluded_record_count,
                       exclusion_reasons_json, records_json, family_fingerprint
                FROM phase1_schwab_evidence_import_families
                WHERE assembly_uid = ?
                ORDER BY family
                """,
                [assembly.assembly_uid],
            ).fetchall()
            expected = sorted(
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
            if stored_families != expected:
                raise ValueError("stored assembly family set is incomplete or changed")
            connection.execute("COMMIT")
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

        reconciliation = assembly.reconciliation
        connection.execute(
            """
            INSERT INTO phase1_schwab_evidence_import_runs (
                assembly_uid, contract_version, provider, connection_uid,
                source_account_id, asof_date, assembled_at_utc,
                lifecycle_window_start, lifecycle_window_end,
                matched_fill_rows, order_only_fill_rows,
                transaction_only_fill_rows, position_count, quote_count,
                positions_without_quotes, session_count,
                cash_review_required_rows,
                all_positions_have_quotes,
                all_quotes_have_session_authority, final_status,
                result_fingerprint
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                assembly.assembly_uid,
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
            ],
        )
        connection.executemany(
            """
            INSERT INTO phase1_schwab_evidence_import_families (
                assembly_uid, family, source_manifest_sha256s_json,
                source_raw_sha256s_json, source_record_count,
                normalized_record_count, excluded_record_count,
                exclusion_reasons_json, records_json, family_fingerprint
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    assembly.assembly_uid,
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
            ],
        )
        connection.execute("COMMIT")
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
            connection.execute("ROLLBACK")
        raise
    finally:
        connection.close()


def load_schwab_phase1_evidence_assembly(
    db_path: Path,
    *,
    assembly_uid: str,
) -> SchwabPhase1EvidenceAssembly:
    """Read and revalidate one exact assembly without latest-row fallback."""

    if db_path.is_symlink() or not db_path.is_file():
        raise ValueError("database must be a pre-existing non-symlink file")
    connection = duckdb.connect(str(db_path), read_only=True)
    try:
        _validate_database_contract(connection)
        run = connection.execute(
            """
            SELECT assembly_uid, contract_version, provider, connection_uid,
                   source_account_id, asof_date, assembled_at_utc,
                   lifecycle_window_start, lifecycle_window_end,
                   matched_fill_rows, order_only_fill_rows,
                   transaction_only_fill_rows, position_count, quote_count,
                   positions_without_quotes, session_count,
                   cash_review_required_rows,
                   all_positions_have_quotes,
                   all_quotes_have_session_authority, final_status,
                   result_fingerprint
            FROM phase1_schwab_evidence_import_runs
            WHERE assembly_uid = ?
            """,
            [assembly_uid],
        ).fetchone()
        if run is None:
            raise ValueError("exact Schwab evidence assembly was not found")
        family_rows = connection.execute(
            """
            SELECT family, source_manifest_sha256s_json,
                   source_raw_sha256s_json, source_record_count,
                   normalized_record_count, excluded_record_count,
                   exclusion_reasons_json, records_json, family_fingerprint
            FROM phase1_schwab_evidence_import_families
            WHERE assembly_uid = ?
            """,
            [assembly_uid],
        ).fetchall()
    finally:
        connection.close()

    try:
        family_by_name = {
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
            for row in family_rows
        }
        families = tuple(family_by_name[name] for name in FAMILY_ORDER)
        assembled_at = datetime.fromisoformat(str(run[6]))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("stored Schwab evidence assembly is malformed") from exc
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
