"""Guarded preparation and disposable-copy rehearsal for WEB-W08 releases."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile
from typing import Any

import duckdb

from onejournal.api.broker_current_position_contracts import (
    build_broker_current_position_valuation_response,
    load_broker_current_financial_release_authorization,
)
from onejournal.journal.broker_current_position_valuation_repository import (
    load_broker_current_position_valuation_run,
)
from onejournal.journal.migrations import apply_schema_migrations
from onejournal.journal.phase1_reporting_calculation import (
    RealizedResultAuthorization,
    authorize_realized_result,
    calculate_bounded_realized_result,
    reporting_items,
    reporting_omissions,
)
from onejournal.journal.phase1_reporting_repository import (
    REPORTING_RELEASE_AUTHORIZATION_VERSION,
    ReportingAccount,
    ReportingRelease,
    calculate_report_release_fingerprint,
    load_reporting_release,
    persist_reporting_release,
)


PACKAGE_SCHEMA = "onejournal.phase1-report-release-package.v1"
REHEARSAL_SCHEMA = "onejournal.phase1-report-release-rehearsal.v1"
SUPPORTED_SOURCE_MIGRATION_VERSIONS = {"0025", "0026"}
REHEARSAL_MIGRATION_VERSION = "0026"


class Phase1ReportingPersistenceOperatorError(ValueError):
    """Raised when exact release preparation or rehearsal cannot proceed safely."""


@dataclass(frozen=True)
class ReportingReleaseRehearsal:
    report_release_uid: str
    report_release_fingerprint: str
    source_database_sha256: str
    rehearsal_copy_before_sha256: str
    rehearsal_copy_after_sha256: str
    release_count: int
    account_count: int
    realized_item_count: int
    omission_count: int
    audit_count: int
    identical_replay_verified: bool
    migration_version: str
    unchanged_data_table_count: int


def _utc(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise Phase1ReportingPersistenceOperatorError(
            f"{field} must be a UTC instant"
        )
    return value


def _utc_text(value: datetime) -> str:
    return _utc(value, "timestamp").isoformat().replace("+00:00", "Z")


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _require_private_file(path: Path, label: str) -> Path:
    supplied = path.expanduser()
    if supplied.is_symlink():
        raise Phase1ReportingPersistenceOperatorError(f"{label} must not be a symlink")
    resolved = supplied.resolve()
    if not resolved.is_file():
        raise Phase1ReportingPersistenceOperatorError(f"{label} does not exist")
    if stat.S_IMODE(resolved.stat().st_mode) != 0o600:
        raise Phase1ReportingPersistenceOperatorError(f"{label} must use mode 0600")
    if stat.S_IMODE(resolved.parent.stat().st_mode) != 0o700:
        raise Phase1ReportingPersistenceOperatorError(
            f"{label} directory must use mode 0700"
        )
    return resolved


def _require_empty_reporting_boundary(db_path: Path) -> None:
    with duckdb.connect(str(db_path), read_only=True) as con:
        migration = con.execute(
            """SELECT version FROM schema_migrations
               WHERE status = 'applied'
               ORDER BY CAST(version AS INTEGER) DESC LIMIT 1"""
        ).fetchone()
        if migration is None or migration[0] not in SUPPORTED_SOURCE_MIGRATION_VERSIONS:
            raise Phase1ReportingPersistenceOperatorError(
                "database is not at a supported reporting migration"
            )
        tables = (
            "phase1_reporting_releases",
            "phase1_reporting_release_accounts",
            "phase1_reporting_release_realized_items",
            "phase1_reporting_release_omissions",
            "phase1_reporting_api_audit_events",
        )
        counts = {
            table: int(con.execute(f"SELECT count(*) FROM {table}").fetchone()[0])
            for table in tables
        }
    if any(counts.values()):
        raise Phase1ReportingPersistenceOperatorError(
            "reporting boundary is not empty; existing state requires explicit review"
        )


def prepare_owner_accepted_reporting_release(
    *,
    db_path: Path,
    broker_current_authorization_path: Path,
    account_alias: str,
    expected_realized_result_fingerprint: str,
    realized_owner_acceptance_uid: str,
    realized_owner_accepted_at_utc: datetime,
    report_release_uid: str,
    generated_at_utc: datetime,
    report_owner_acceptance_uid: str,
    report_owner_accepted_at_utc: datetime,
) -> ReportingRelease:
    """Rebuild and bind one exact owner-accepted release without writing the DB."""

    source_db = _require_private_file(db_path, "source database")
    _require_empty_reporting_boundary(source_db)
    generated_at = _utc(generated_at_utc, "generated_at_utc")
    report_accepted_at = _utc(
        report_owner_accepted_at_utc, "report_owner_accepted_at_utc"
    )
    if report_accepted_at < generated_at:
        raise Phase1ReportingPersistenceOperatorError(
            "report owner acceptance predates the release"
        )

    current_authorization = load_broker_current_financial_release_authorization(
        broker_current_authorization_path
    )
    current = load_broker_current_position_valuation_run(
        source_db,
        valuation_run_uid=current_authorization.valuation_run_uid,
    )
    if current is None:
        raise Phase1ReportingPersistenceOperatorError(
            "accepted broker-current valuation is unavailable"
        )
    build_broker_current_position_valuation_response(
        current, authorization=current_authorization
    )

    realized = calculate_bounded_realized_result(source_db)
    if realized.result_fingerprint != expected_realized_result_fingerprint:
        raise Phase1ReportingPersistenceOperatorError(
            "realized result does not match the exact owner-accepted fingerprint"
        )
    if len(realized.authorities) != 1:
        raise Phase1ReportingPersistenceOperatorError(
            "report release requires exactly one active history revision"
        )
    realized_authorization = RealizedResultAuthorization(
        calculation_run_id=realized.calculation_run_id,
        result_fingerprint=expected_realized_result_fingerprint,
        history_revision_uids=tuple(x.revision_uid for x in realized.authorities),
        owner_acceptance_uid=realized_owner_acceptance_uid,
        accepted_at_utc=_utc(
            realized_owner_accepted_at_utc, "realized_owner_accepted_at_utc"
        ),
    )
    authorize_realized_result(realized, realized_authorization)

    expected_account = (current.source_broker, current.source_account_id)
    realized_accounts = {
        (x.source_broker, x.source_account_id) for x in realized.authorities
    }
    realized_accounts.update(
        (x.source_broker, x.source_account_id) for x in realized.items
    )
    realized_accounts.update(
        (x.source_broker, x.source_account_id) for x in realized.omissions
    )
    if realized_accounts != {expected_account}:
        raise Phase1ReportingPersistenceOperatorError(
            "current and realized authorities do not have one identical account scope"
        )

    base = dict(
        report_release_uid=report_release_uid,
        current_valuation_run_uid=current.valuation_run_uid,
        current_result_fingerprint=current.result_fingerprint,
        current_owner_acceptance_uid=current_authorization.owner_acceptance_uid,
        current_owner_accepted_at_utc=current_authorization.accepted_at,
        realized_calculation_run_id=realized.calculation_run_id,
        realized_result_fingerprint=realized.result_fingerprint,
        realized_owner_acceptance_uid=realized_authorization.owner_acceptance_uid,
        realized_owner_accepted_at_utc=realized_authorization.accepted_at_utc,
        history_revision_uid=realized.authorities[0].revision_uid,
        coverage_start_date=realized.coverage_start_date,
        coverage_end_date=realized.coverage_end_date,
        calculation_version=realized.calculation_version,
        generated_at_utc=generated_at,
        release_status="owner_accepted",
        owner_acceptance_uid=report_owner_acceptance_uid,
        owner_accepted_at_utc=report_accepted_at,
        accounts=(ReportingAccount(*expected_account, account_alias),),
        items=reporting_items(realized),
        omissions=reporting_omissions(realized),
    )
    provisional = ReportingRelease(**base, report_release_fingerprint="")
    return ReportingRelease(
        **base,
        report_release_fingerprint=calculate_report_release_fingerprint(
            release=provisional
        ),
    )


def rehearse_reporting_release(
    *, source_db_path: Path, rehearsal_db_path: Path, release: ReportingRelease
) -> ReportingReleaseRehearsal:
    """Persist twice and read back on one new disposable copy only."""

    source = _require_private_file(source_db_path, "source database")
    target = rehearsal_db_path.expanduser()
    if target.exists() or target.is_symlink():
        raise Phase1ReportingPersistenceOperatorError(
            "rehearsal database path must not already exist"
        )
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if stat.S_IMODE(target.parent.stat().st_mode) != 0o700:
        raise Phase1ReportingPersistenceOperatorError(
            "rehearsal database directory must use mode 0700"
        )

    source_before = _sha256_file(source)
    shutil.copy2(source, target)
    target.chmod(0o600)
    copy_before = _sha256_file(target)
    if copy_before != source_before:
        raise Phase1ReportingPersistenceOperatorError(
            "rehearsal copy checksum does not match the source database"
        )

    excluded_tables = {
        "schema_migrations",
        "phase1_reporting_releases",
        "phase1_reporting_release_accounts",
        "phase1_reporting_release_realized_items",
        "phase1_reporting_release_omissions",
        "phase1_reporting_api_audit_events",
    }
    with duckdb.connect(str(target), read_only=True) as con:
        names = tuple(
            row[0]
            for row in con.execute(
                """SELECT table_name FROM information_schema.tables
                   WHERE table_schema = 'main' AND table_type = 'BASE TABLE'
                   ORDER BY table_name"""
            ).fetchall()
            if row[0] not in excluded_tables
        )
        data_counts_before = {
            name: int(con.execute(f"SELECT count(*) FROM {name}").fetchone()[0])
            for name in names
        }
    apply_schema_migrations(target, target_version=REHEARSAL_MIGRATION_VERSION)

    with duckdb.connect(str(target)) as con:
        persist_reporting_release(con, release)
        persist_reporting_release(con, release)
        loaded = load_reporting_release(
            con, report_release_uid=release.report_release_uid
        )
        counts = tuple(
            int(con.execute(f"SELECT count(*) FROM {table}").fetchone()[0])
            for table in (
                "phase1_reporting_releases",
                "phase1_reporting_release_accounts",
                "phase1_reporting_release_realized_items",
                "phase1_reporting_release_omissions",
                "phase1_reporting_api_audit_events",
            )
        )
        migration_version = con.execute(
            """SELECT version FROM schema_migrations WHERE status = 'applied'
               ORDER BY CAST(version AS INTEGER) DESC LIMIT 1"""
        ).fetchone()[0]
        data_counts_after = {
            name: int(con.execute(f"SELECT count(*) FROM {name}").fetchone()[0])
            for name in names
        }
    if loaded != release:
        raise Phase1ReportingPersistenceOperatorError(
            "rehearsal release read-back does not match the prepared release"
        )
    expected_counts = (1, len(release.accounts), len(release.items), len(release.omissions), 0)
    if counts != expected_counts:
        raise Phase1ReportingPersistenceOperatorError(
            "rehearsal reporting table counts do not match the release"
        )
    if migration_version != REHEARSAL_MIGRATION_VERSION:
        raise Phase1ReportingPersistenceOperatorError(
            "rehearsal copy did not reach migration 0026"
        )
    if data_counts_after != data_counts_before:
        raise Phase1ReportingPersistenceOperatorError(
            "non-reporting data changed during rehearsal"
        )
    if _sha256_file(source) != source_before:
        raise Phase1ReportingPersistenceOperatorError(
            "source database changed during disposable-copy rehearsal"
        )
    return ReportingReleaseRehearsal(
        report_release_uid=release.report_release_uid,
        report_release_fingerprint=release.report_release_fingerprint,
        source_database_sha256=source_before,
        rehearsal_copy_before_sha256=copy_before,
        rehearsal_copy_after_sha256=_sha256_file(target),
        release_count=counts[0],
        account_count=counts[1],
        realized_item_count=counts[2],
        omission_count=counts[3],
        audit_count=counts[4],
        identical_replay_verified=True,
        migration_version=migration_version,
        unchanged_data_table_count=len(data_counts_before),
    )


def report_authorization_document(release: ReportingRelease) -> dict[str, Any]:
    return {
        "contract_version": REPORTING_RELEASE_AUTHORIZATION_VERSION,
        "report_release_uid": release.report_release_uid,
        "report_release_fingerprint": release.report_release_fingerprint,
        "owner_acceptance_uid": release.owner_acceptance_uid,
        "decision": "accepted",
        "accepted_scope": "bounded_phase1_reporting",
        "approval_source": "project_owner_explicit_proceed",
    }


def write_private_release_package(
    *, output_dir: Path, release: ReportingRelease, rehearsal: ReportingReleaseRehearsal
) -> None:
    """Atomically write value-free private preparation evidence."""

    target = output_dir.expanduser()
    if target.exists() or target.is_symlink():
        raise Phase1ReportingPersistenceOperatorError(
            "release package directory already exists"
        )
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    target.parent.chmod(0o700)
    authorization = report_authorization_document(release)
    authorization_bytes = (
        json.dumps(authorization, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")
    reasons: dict[str, int] = {}
    for omission in release.omissions:
        reasons[omission.reason_code] = reasons.get(omission.reason_code, 0) + 1
    manifest = {
        "schema": PACKAGE_SCHEMA,
        "report_release_uid": release.report_release_uid,
        "report_release_fingerprint": release.report_release_fingerprint,
        "current_valuation_run_uid": release.current_valuation_run_uid,
        "current_result_fingerprint": release.current_result_fingerprint,
        "current_owner_acceptance_uid": release.current_owner_acceptance_uid,
        "current_owner_accepted_at_utc": _utc_text(
            release.current_owner_accepted_at_utc
        ),
        "realized_calculation_run_id": release.realized_calculation_run_id,
        "realized_result_fingerprint": release.realized_result_fingerprint,
        "realized_owner_acceptance_uid": release.realized_owner_acceptance_uid,
        "realized_owner_accepted_at_utc": _utc_text(
            release.realized_owner_accepted_at_utc
        ),
        "history_revision_uid": release.history_revision_uid,
        "coverage_start_date": release.coverage_start_date.isoformat(),
        "coverage_end_date": release.coverage_end_date.isoformat(),
        "calculation_version": release.calculation_version,
        "generated_at_utc": _utc_text(release.generated_at_utc),
        "release_status": release.release_status,
        "owner_acceptance_uid": release.owner_acceptance_uid,
        "owner_accepted_at_utc": _utc_text(release.owner_accepted_at_utc),
        "account_aliases": [x.account_alias for x in release.accounts],
        "processed_count": len(release.items) + len(release.omissions),
        "available_count": len(release.items),
        "unavailable_count": len(release.omissions),
        "reconciliation_pending_count": 0,
        "reason_counts": dict(sorted(reasons.items())),
        "quality": "incomplete" if release.omissions else "valid",
        "authorization_sha256": sha256(authorization_bytes).hexdigest(),
        "rehearsal": {
            "schema": REHEARSAL_SCHEMA,
            **rehearsal.__dict__,
        },
        "database_write_performed": False,
        "rehearsal_copy_write_performed": True,
        "provider_call_performed": False,
        "credential_access_performed": False,
        "order_api_performed": False,
        "api_restart_performed": False,
    }
    manifest_bytes = (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode(
        "utf-8"
    )

    with tempfile.TemporaryDirectory(prefix=f".{target.name}-", dir=target.parent) as tmp:
        staging = Path(tmp)
        os.chmod(staging, 0o700)
        for name, payload in (
            ("report-release-authorization.json", authorization_bytes),
            ("manifest.json", manifest_bytes),
        ):
            path = staging / name
            path.write_bytes(payload)
            path.chmod(0o600)
        os.replace(staging, target)
