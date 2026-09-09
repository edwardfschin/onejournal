"""Guarded preparation, rehearsal, and persistence for WEB-W08 releases."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
import json
import os
from pathlib import Path
import re
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
    authorize_reporting_release,
    calculate_report_release_fingerprint,
    load_reporting_release_authorization,
    load_reporting_release,
    persist_reporting_release,
    validate_reporting_release,
)


PACKAGE_SCHEMA = "onejournal.phase1-report-release-package.v1"
REHEARSAL_SCHEMA = "onejournal.phase1-report-release-rehearsal.v1"
PERSISTENCE_AUDIT_SCHEMA = "onejournal.phase1-report-release-persistence-audit.v1"
SUPPORTED_SOURCE_MIGRATION_VERSIONS = {"0025", "0026"}
REHEARSAL_MIGRATION_VERSION = "0026"
PERSISTENCE_MIGRATION_VERSION = "0026"
AUTHORIZATION_FILENAME = "report-release-authorization.json"
MANIFEST_FILENAME = "manifest.json"
_DIGEST_RE = re.compile(r"[0-9a-f]{64}")
MAX_PACKAGE_DOCUMENT_BYTES = 1024 * 1024


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


@dataclass(frozen=True)
class ReportingReleasePersistenceExecution:
    release: ReportingRelease
    target_state_before: str
    database_sha256_before: str
    database_sha256_after: str
    write_requested: bool
    created: bool
    replayed: bool
    release_count: int
    account_count: int
    realized_item_count: int
    omission_count: int
    audit_count: int

    def privacy_safe_audit(self) -> dict[str, object]:
        """Return persistence evidence without values or private identities."""

        return {
            "schema": PERSISTENCE_AUDIT_SCHEMA,
            "report_release_uid": self.release.report_release_uid,
            "report_release_fingerprint": (
                self.release.report_release_fingerprint
            ),
            "owner_acceptance_uid": self.release.owner_acceptance_uid,
            "account_aliases": [x.account_alias for x in self.release.accounts],
            "processed_count": len(self.release.items)
            + len(self.release.omissions),
            "available_count": len(self.release.items),
            "unavailable_count": len(self.release.omissions),
            "quality": "incomplete" if self.release.omissions else "valid",
            "migration_version": PERSISTENCE_MIGRATION_VERSION,
            "target_state_before": self.target_state_before,
            "database_sha256_before": self.database_sha256_before,
            "database_sha256_after": self.database_sha256_after,
            "write_requested": self.write_requested,
            "created": self.created,
            "replayed": self.replayed,
            "reporting_table_counts": {
                "releases": self.release_count,
                "accounts": self.account_count,
                "realized_items": self.realized_item_count,
                "omissions": self.omission_count,
                "audit_events": self.audit_count,
            },
            "provider_call_performed": False,
            "credential_access_performed": False,
            "order_api_performed": False,
            "api_restart_performed": False,
        }


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


def _require_digest(value: str, label: str) -> str:
    if _DIGEST_RE.fullmatch(value) is None:
        raise Phase1ReportingPersistenceOperatorError(
            f"{label} must be lowercase SHA-256 hex"
        )
    return value


def _require_private_file(path: Path, label: str) -> Path:
    supplied = path.expanduser()
    if not supplied.is_absolute() or supplied.is_symlink():
        raise Phase1ReportingPersistenceOperatorError(
            f"{label} must be an absolute non-symlink file"
        )
    resolved = supplied.resolve()
    if not resolved.is_file():
        raise Phase1ReportingPersistenceOperatorError(f"{label} does not exist")
    if resolved.stat().st_size <= 0:
        raise Phase1ReportingPersistenceOperatorError(f"{label} must not be empty")
    if stat.S_IMODE(resolved.stat().st_mode) != 0o600:
        raise Phase1ReportingPersistenceOperatorError(f"{label} must use mode 0600")
    if stat.S_IMODE(resolved.parent.stat().st_mode) != 0o700:
        raise Phase1ReportingPersistenceOperatorError(
            f"{label} directory must use mode 0700"
        )
    return resolved


def _require_private_directory(path: Path, label: str) -> Path:
    supplied = path.expanduser()
    if not supplied.is_absolute() or supplied.is_symlink():
        raise Phase1ReportingPersistenceOperatorError(
            f"{label} must be an absolute non-symlink directory"
        )
    resolved = supplied.resolve()
    if not resolved.is_dir():
        raise Phase1ReportingPersistenceOperatorError(f"{label} does not exist")
    if stat.S_IMODE(resolved.stat().st_mode) != 0o700:
        raise Phase1ReportingPersistenceOperatorError(
            f"{label} must use mode 0700"
        )
    return resolved


def _latest_migration(con: duckdb.DuckDBPyConnection) -> str:
    row = con.execute(
        """SELECT version FROM schema_migrations
           WHERE status = 'applied'
           ORDER BY CAST(version AS INTEGER) DESC LIMIT 1"""
    ).fetchone()
    if row is None:
        raise Phase1ReportingPersistenceOperatorError(
            "database has no applied migration"
        )
    return str(row[0])


def _reporting_counts(
    con: duckdb.DuckDBPyConnection,
) -> tuple[int, int, int, int, int]:
    return tuple(
        int(con.execute(f"SELECT count(*) FROM {table}").fetchone()[0])
        for table in (
            "phase1_reporting_releases",
            "phase1_reporting_release_accounts",
            "phase1_reporting_release_realized_items",
            "phase1_reporting_release_omissions",
            "phase1_reporting_api_audit_events",
        )
    )


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
    release = ReportingRelease(
        **base,
        report_release_fingerprint=calculate_report_release_fingerprint(
            release=provisional
        ),
    )
    validate_reporting_release(release)
    return release


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


def _load_package_json(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    private_path = _require_private_file(path, label)
    if private_path.stat().st_size > MAX_PACKAGE_DOCUMENT_BYTES:
        raise Phase1ReportingPersistenceOperatorError(
            f"{label} exceeds the accepted size"
        )
    payload = private_path.read_bytes()
    try:
        document = json.loads(payload)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise Phase1ReportingPersistenceOperatorError(
            f"{label} is not valid JSON"
        ) from exc
    if not isinstance(document, dict):
        raise Phase1ReportingPersistenceOperatorError(
            f"{label} must contain one JSON object"
        )
    return document, payload


def _parse_utc_text(value: object, label: str) -> datetime:
    if not isinstance(value, str):
        raise Phase1ReportingPersistenceOperatorError(
            f"{label} must be a UTC timestamp"
        )
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise Phase1ReportingPersistenceOperatorError(
            f"{label} must be a UTC timestamp"
        ) from exc
    return _utc(parsed, label)


def prepare_reporting_release_from_package(
    *,
    db_path: Path,
    broker_current_authorization_path: Path,
    package_dir: Path,
) -> ReportingRelease:
    """Rebuild and validate the exact value-free prepared package."""

    package = _require_private_directory(package_dir, "prepared package")
    if {item.name for item in package.iterdir()} != {
        MANIFEST_FILENAME,
        AUTHORIZATION_FILENAME,
    }:
        raise Phase1ReportingPersistenceOperatorError(
            "prepared package files do not exactly match the contract"
        )
    manifest, _ = _load_package_json(
        package / MANIFEST_FILENAME, "prepared package manifest"
    )
    authorization_path = package / AUTHORIZATION_FILENAME
    _, authorization_bytes = _load_package_json(
        authorization_path, "prepared report authorization"
    )
    expected_fields = {
        "schema",
        "report_release_uid",
        "report_release_fingerprint",
        "current_valuation_run_uid",
        "current_result_fingerprint",
        "current_owner_acceptance_uid",
        "current_owner_accepted_at_utc",
        "realized_calculation_run_id",
        "realized_result_fingerprint",
        "realized_owner_acceptance_uid",
        "realized_owner_accepted_at_utc",
        "history_revision_uid",
        "coverage_start_date",
        "coverage_end_date",
        "calculation_version",
        "generated_at_utc",
        "release_status",
        "owner_acceptance_uid",
        "owner_accepted_at_utc",
        "account_aliases",
        "processed_count",
        "available_count",
        "unavailable_count",
        "reconciliation_pending_count",
        "reason_counts",
        "quality",
        "authorization_sha256",
        "rehearsal",
        "database_write_performed",
        "rehearsal_copy_write_performed",
        "provider_call_performed",
        "credential_access_performed",
        "order_api_performed",
        "api_restart_performed",
    }
    if set(manifest) != expected_fields or manifest.get("schema") != PACKAGE_SCHEMA:
        raise Phase1ReportingPersistenceOperatorError(
            "prepared package manifest does not match the contract"
        )
    if (
        manifest["database_write_performed"] is not False
        or manifest["rehearsal_copy_write_performed"] is not True
        or manifest["provider_call_performed"] is not False
        or manifest["credential_access_performed"] is not False
        or manifest["order_api_performed"] is not False
        or manifest["api_restart_performed"] is not False
    ):
        raise Phase1ReportingPersistenceOperatorError(
            "prepared package safety flags are invalid"
        )
    aliases = manifest["account_aliases"]
    if (
        not isinstance(aliases, list)
        or len(aliases) != 1
        or not isinstance(aliases[0], str)
    ):
        raise Phase1ReportingPersistenceOperatorError(
            "prepared package must bind exactly one account alias"
        )
    if manifest["authorization_sha256"] != sha256(authorization_bytes).hexdigest():
        raise Phase1ReportingPersistenceOperatorError(
            "prepared report authorization checksum mismatch"
        )
    for field in (
        "report_release_fingerprint",
        "current_result_fingerprint",
        "realized_result_fingerprint",
    ):
        if not isinstance(manifest[field], str):
            raise Phase1ReportingPersistenceOperatorError(
                f"prepared package {field} is invalid"
            )
        _require_digest(manifest[field], f"prepared package {field}")

    release = prepare_owner_accepted_reporting_release(
        db_path=db_path,
        broker_current_authorization_path=broker_current_authorization_path,
        account_alias=aliases[0],
        expected_realized_result_fingerprint=manifest[
            "realized_result_fingerprint"
        ],
        realized_owner_acceptance_uid=manifest[
            "realized_owner_acceptance_uid"
        ],
        realized_owner_accepted_at_utc=_parse_utc_text(
            manifest["realized_owner_accepted_at_utc"],
            "realized_owner_accepted_at_utc",
        ),
        report_release_uid=manifest["report_release_uid"],
        generated_at_utc=_parse_utc_text(
            manifest["generated_at_utc"], "generated_at_utc"
        ),
        report_owner_acceptance_uid=manifest["owner_acceptance_uid"],
        report_owner_accepted_at_utc=_parse_utc_text(
            manifest["owner_accepted_at_utc"], "owner_accepted_at_utc"
        ),
    )
    reasons: dict[str, int] = {}
    for omission in release.omissions:
        reasons[omission.reason_code] = reasons.get(omission.reason_code, 0) + 1
    expected_bindings = {
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
    }
    if any(manifest[key] != value for key, value in expected_bindings.items()):
        raise Phase1ReportingPersistenceOperatorError(
            "prepared package does not match the rebuilt exact release"
        )
    rehearsal = manifest["rehearsal"]
    if (
        not isinstance(rehearsal, dict)
        or rehearsal.get("schema") != REHEARSAL_SCHEMA
        or rehearsal.get("report_release_uid") != release.report_release_uid
        or rehearsal.get("report_release_fingerprint")
        != release.report_release_fingerprint
        or rehearsal.get("release_count") != 1
        or rehearsal.get("account_count") != len(release.accounts)
        or rehearsal.get("realized_item_count") != len(release.items)
        or rehearsal.get("omission_count") != len(release.omissions)
        or rehearsal.get("audit_count") != 0
        or rehearsal.get("identical_replay_verified") is not True
        or rehearsal.get("migration_version") != REHEARSAL_MIGRATION_VERSION
    ):
        raise Phase1ReportingPersistenceOperatorError(
            "prepared package rehearsal evidence is invalid"
        )
    authorization = load_reporting_release_authorization(authorization_path)
    authorize_reporting_release(release, authorization)
    return release


def _inspect_persistence_target(
    target: Path, release: ReportingRelease
) -> tuple[str, tuple[int, int, int, int, int]]:
    with duckdb.connect(str(target), read_only=True) as con:
        if _latest_migration(con) != PERSISTENCE_MIGRATION_VERSION:
            raise Phase1ReportingPersistenceOperatorError(
                "database must be exactly at migration 0026"
            )
        counts = _reporting_counts(con)
        if counts == (0, 0, 0, 0, 0):
            return "would_create", counts
        if counts[:4] != (
            1,
            len(release.accounts),
            len(release.items),
            len(release.omissions),
        ):
            raise Phase1ReportingPersistenceOperatorError(
                "reporting boundary contains unexpected existing state"
            )
        loaded = load_reporting_release(
            con, report_release_uid=release.report_release_uid
        )
    if loaded != release:
        raise Phase1ReportingPersistenceOperatorError(
            "target contains a conflicting report release"
        )
    return "identical_replay", counts


def execute_reporting_release_persistence(
    db_path: Path,
    *,
    release: ReportingRelease,
    authorization_path: Path,
    expected_database_sha256: str,
    expected_report_release_fingerprint: str,
    persist: bool = False,
    verified_backup_path: Path | None = None,
) -> ReportingReleasePersistenceExecution:
    """Validate by default; persist only with exact hashes and a backup."""

    target = _require_private_file(db_path, "database")
    expected_database_digest = _require_digest(
        expected_database_sha256, "expected database SHA-256"
    )
    expected_release_digest = _require_digest(
        expected_report_release_fingerprint,
        "expected report release fingerprint",
    )
    if release.report_release_fingerprint != expected_release_digest:
        raise Phase1ReportingPersistenceOperatorError(
            "rebuilt report release fingerprint differs from the approved target"
        )
    validate_reporting_release(release)
    authorization = load_reporting_release_authorization(authorization_path)
    authorize_reporting_release(release, authorization)
    if Path(str(target) + ".wal").exists():
        raise Phase1ReportingPersistenceOperatorError(
            "database WAL exists; target is not quiescent"
        )
    before_digest = _sha256_file(target)
    if before_digest != expected_database_digest:
        raise Phase1ReportingPersistenceOperatorError(
            "database checksum differs from the approved target"
        )
    backup: Path | None = None
    if persist:
        if verified_backup_path is None:
            raise Phase1ReportingPersistenceOperatorError(
                "persistence requires a verified backup"
            )
        backup = _require_private_file(verified_backup_path, "verified backup")
        if target.samefile(backup):
            raise Phase1ReportingPersistenceOperatorError(
                "verified backup must be a distinct file"
            )
        if _sha256_file(backup) != before_digest:
            raise Phase1ReportingPersistenceOperatorError(
                "verified backup is not byte-identical to the approved target"
            )
    elif verified_backup_path is not None:
        raise Phase1ReportingPersistenceOperatorError(
            "verified backup is accepted only with persistence"
        )

    target_state, counts = _inspect_persistence_target(target, release)
    if not persist:
        after_digest = _sha256_file(target)
        if after_digest != before_digest:
            raise Phase1ReportingPersistenceOperatorError(
                "dry-run changed the database"
            )
        return ReportingReleasePersistenceExecution(
            release=release,
            target_state_before=target_state,
            database_sha256_before=before_digest,
            database_sha256_after=after_digest,
            write_requested=False,
            created=False,
            replayed=False,
            release_count=counts[0],
            account_count=counts[1],
            realized_item_count=counts[2],
            omission_count=counts[3],
            audit_count=counts[4],
        )

    with duckdb.connect(str(target)) as con:
        if _latest_migration(con) != PERSISTENCE_MIGRATION_VERSION:
            raise Phase1ReportingPersistenceOperatorError(
                "database migration changed before persistence"
            )
        current_counts = _reporting_counts(con)
        if current_counts != counts:
            raise Phase1ReportingPersistenceOperatorError(
                "reporting state changed before persistence"
            )
        persist_reporting_release(con, release)
        loaded = load_reporting_release(
            con, report_release_uid=release.report_release_uid
        )
        counts_after = _reporting_counts(con)
    if loaded != release:
        raise Phase1ReportingPersistenceOperatorError(
            "persisted release failed exact read-back"
        )
    expected_counts = (
        1,
        len(release.accounts),
        len(release.items),
        len(release.omissions),
        counts[4],
    )
    if counts_after != expected_counts:
        raise Phase1ReportingPersistenceOperatorError(
            "persisted reporting table counts are invalid"
        )
    if backup is None or _sha256_file(backup) != before_digest:
        raise Phase1ReportingPersistenceOperatorError(
            "verified backup changed during persistence"
        )
    return ReportingReleasePersistenceExecution(
        release=release,
        target_state_before=target_state,
        database_sha256_before=before_digest,
        database_sha256_after=_sha256_file(target),
        write_requested=True,
        created=target_state == "would_create",
        replayed=target_state == "identical_replay",
        release_count=counts_after[0],
        account_count=counts_after[1],
        realized_item_count=counts_after[2],
        omission_count=counts_after[3],
        audit_count=counts_after[4],
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
