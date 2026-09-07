"""Fail-closed operator boundary for accepted broker-current persistence.

The module consumes already captured private evidence.  It has no provider,
credential, migration, deletion, or implicit-latest capability.  Persistence
requires an explicit flag at the script boundary, the exact target database
digest, and an independent byte-identical backup.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
from pathlib import Path
import re
import stat
from typing import Any, Mapping

import duckdb

from onejournal.brokers.schwab.position_binding import (
    load_schwab_position_private_binding_bytes,
    schwab_position_private_binding_sha256,
)
from onejournal.journal.broker_current_position_valuation_repository import (
    BrokerCurrentPositionValuationReadBack,
    REQUIRED_TABLES,
    broker_current_position_valuation_run_document,
    calculate_broker_current_position_result_fingerprint,
    calculate_broker_position_snapshot_fingerprint,
    load_broker_current_position_valuation_run,
    persist_broker_current_position_valuation_run,
)
from onejournal.pnl.broker_current_position_valuation import (
    BrokerCurrentPositionValuationRun,
    build_broker_current_position_valuation,
)
from onejournal.pnl.position_reconciliation import BrokerPositionSnapshot
from onejournal.provider_connectors import (
    ProviderUsagePolicy,
    SCHWAB_POSITION_EXTERNAL_ACQUISITION_PROFILE,
    convert_external_schwab_positions,
    load_external_provider_acquisition,
)


PRIVATE_RESULT_FILENAME = "broker-current-position-valuation-private.json"
PRIVACY_AUDIT_FILENAME = "privacy-safe-audit.json"
SOURCE_LINEAGE_FILENAME = "source-lineage.json"
FINANCIAL_AUTHORIZATION_FILENAME = "financial-release-authorization.json"
RESULT_PACKAGE_SCHEMA = "onejournal.broker-current-position-valuation-package.v2"
PRIVATE_RESULT_SCHEMA = "onejournal.broker-current-position-valuation-private-result.v2"
SOURCE_LINEAGE_SCHEMA = "onejournal.broker-current-position-valuation-lineage.v2"
ACCEPTANCE_PACKAGE_SCHEMA = "onejournal.broker-current-owner-acceptance-package.v1"
AUTHORIZATION_CONTRACT_VERSION = (
    "onejournal.broker-current-financial-release-authorization.v1"
)
REQUIRED_MIGRATION_VERSION = "0023"
MIGRATION_PATH = (
    Path(__file__).resolve().parents[3]
    / "scripts/journal/migrations/0023_widen_broker_current_decimal_precision.sql"
)
MAX_PRIVATE_DOCUMENT_BYTES = 1024 * 1024
_DIGEST_RE = re.compile(r"[0-9a-f]{64}")


class BrokerCurrentPersistenceOperatorError(RuntimeError):
    """Raised before unsafe, ambiguous, or incomplete persistence."""


@dataclass(frozen=True)
class BrokerCurrentOwnerAcceptance:
    owner_acceptance_uid: str
    valuation_run_uid: str
    result_fingerprint: str
    accepted_at: datetime


@dataclass(frozen=True)
class BrokerCurrentPersistencePlan:
    run: BrokerCurrentPositionValuationRun
    broker_snapshot: BrokerPositionSnapshot
    owner_acceptance: BrokerCurrentOwnerAcceptance
    acquisition_manifest_sha256: str
    position_binding_sha256: str
    result_manifest_sha256: str
    acceptance_manifest_sha256: str


@dataclass(frozen=True)
class BrokerCurrentPersistenceExecution:
    plan: BrokerCurrentPersistencePlan
    target_state_before: str
    database_sha256_before: str
    database_sha256_after: str
    write_requested: bool
    created: bool
    replayed: bool

    def privacy_safe_audit(self) -> dict[str, object]:
        """Return exact lineage and counts without private financial values."""

        run = self.plan.run
        return {
            "schema": "onejournal.broker-current-persistence-operator-audit.v1",
            "valuation_run_uid": run.run_uid,
            "snapshot_uid": run.snapshot_uid,
            "result_fingerprint": (
                calculate_broker_current_position_result_fingerprint(run)
            ),
            "owner_acceptance_uid": self.plan.owner_acceptance.owner_acceptance_uid,
            "source_broker": run.source_broker,
            "source_account_id_sha256": sha256(
                run.source_account_id.encode("utf-8")
            ).hexdigest(),
            "asof": run.asof.isoformat(),
            "evaluated_at": run.evaluated_at.isoformat(),
            "position_count": run.position_count,
            "cost_basis_available_count": run.cost_basis_available_count,
            "market_value_available_count": run.market_value_available_count,
            "unrealized_pnl_available_count": run.unrealized_pnl_available_count,
            "complete_portfolio_cost_basis_available": (
                run.complete_portfolio_cost_basis_available
            ),
            "complete_portfolio_market_value_available": (
                run.complete_portfolio_market_value_available
            ),
            "complete_portfolio_unrealized_pnl_available": (
                run.complete_portfolio_unrealized_pnl_available
            ),
            "acquisition_manifest_sha256": (
                self.plan.acquisition_manifest_sha256
            ),
            "position_binding_sha256": self.plan.position_binding_sha256,
            "result_manifest_sha256": self.plan.result_manifest_sha256,
            "acceptance_manifest_sha256": self.plan.acceptance_manifest_sha256,
            "target_state_before": self.target_state_before,
            "database_sha256_before": self.database_sha256_before,
            "database_sha256_after": self.database_sha256_after,
            "write_requested": self.write_requested,
            "database_write_performed": self.created,
            "created": self.created,
            "replayed": self.replayed,
            "private_financial_values_emitted": False,
            "raw_instrument_identifiers_emitted": False,
            "final_status": (
                "persisted"
                if self.created
                else "identical_replay"
                if self.replayed
                else "validated_dry_run"
            ),
        }


def _digest(body: bytes) -> str:
    return sha256(body).hexdigest()


def _canonical_json_document(body: bytes, field: str) -> dict[str, Any]:
    if not isinstance(body, bytes) or not 0 < len(body) <= MAX_PRIVATE_DOCUMENT_BYTES:
        raise BrokerCurrentPersistenceOperatorError(
            f"{field} byte size is outside the accepted bound"
        )
    try:
        document = json.loads(
            body.decode("utf-8"),
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise BrokerCurrentPersistenceOperatorError(
            f"{field} is not finite JSON"
        ) from exc
    if not isinstance(document, dict):
        raise BrokerCurrentPersistenceOperatorError(f"{field} must be an object")
    canonical = (
        json.dumps(
            document,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        + "\n"
    ).encode("utf-8")
    if body != canonical:
        raise BrokerCurrentPersistenceOperatorError(f"{field} is not canonical")
    return document


def _exact_fields(
    document: object,
    expected: set[str],
    field: str,
) -> dict[str, Any]:
    if not isinstance(document, dict) or set(document) != expected:
        raise BrokerCurrentPersistenceOperatorError(
            f"{field} fields do not match the contract"
        )
    return document


def _require_digest(value: object, field: str) -> str:
    if not isinstance(value, str) or _DIGEST_RE.fullmatch(value) is None:
        raise BrokerCurrentPersistenceOperatorError(
            f"{field} must be lowercase SHA-256"
        )
    return value


def _utc_instant(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise BrokerCurrentPersistenceOperatorError(f"{field} must be a UTC instant")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise BrokerCurrentPersistenceOperatorError(
            f"{field} must be a UTC instant"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise BrokerCurrentPersistenceOperatorError(f"{field} must be a UTC instant")
    return parsed.astimezone(UTC)


def _currency_quanta(value: object) -> dict[str, Decimal]:
    if not isinstance(value, dict) or not value:
        raise BrokerCurrentPersistenceOperatorError(
            "currency quantum mapping is invalid"
        )
    parsed: dict[str, Decimal] = {}
    for currency, quantum in value.items():
        if not isinstance(currency, str) or not currency:
            raise BrokerCurrentPersistenceOperatorError(
                "currency quantum mapping is invalid"
            )
        if not isinstance(quantum, str):
            raise BrokerCurrentPersistenceOperatorError(
                "currency quantum mapping is invalid"
            )
        try:
            amount = Decimal(quantum)
        except InvalidOperation as exc:
            raise BrokerCurrentPersistenceOperatorError(
                "currency quantum mapping is invalid"
            ) from exc
        if not amount.is_finite() or amount <= 0 or format(amount, "f") != quantum:
            raise BrokerCurrentPersistenceOperatorError(
                "currency quantum mapping is invalid"
            )
        parsed[currency] = amount
    return dict(sorted(parsed.items()))


def _validate_package_files(
    manifest: Mapping[str, Any],
    files: Mapping[str, bytes],
    expected_names: tuple[str, ...],
    field: str,
) -> None:
    if set(files) != set(expected_names):
        raise BrokerCurrentPersistenceOperatorError(
            f"{field} file set does not match the contract"
        )
    expected_records = [
        {"filename": name, "mode": "0600", "sha256": _digest(files[name])}
        for name in expected_names
    ]
    if manifest.get("files") != expected_records:
        raise BrokerCurrentPersistenceOperatorError(
            f"{field} file manifest does not match exact bytes"
        )


def _result_policy(
    private_result_bytes: bytes,
) -> tuple[dict[str, Any], datetime, int, dict[str, Decimal]]:
    private_result = _exact_fields(
        _canonical_json_document(private_result_bytes, "private result"),
        {"schema", "result_fingerprint", "run"},
        "private result",
    )
    if private_result["schema"] != PRIVATE_RESULT_SCHEMA:
        raise BrokerCurrentPersistenceOperatorError(
            "private result schema is unsupported"
        )
    _require_digest(private_result["result_fingerprint"], "result fingerprint")
    run_document = private_result["run"]
    if not isinstance(run_document, dict):
        raise BrokerCurrentPersistenceOperatorError(
            "private result run must be an object"
        )
    evaluated_at = _utc_instant(run_document.get("evaluated_at"), "evaluated_at")
    max_age = run_document.get("max_snapshot_age_seconds")
    if type(max_age) is not int or max_age < 0:
        raise BrokerCurrentPersistenceOperatorError(
            "max_snapshot_age_seconds must be a non-negative integer"
        )
    quanta = _currency_quanta(run_document.get("currency_quantum_by_currency"))
    if run_document.get("financial_acceptance") is not False:
        raise BrokerCurrentPersistenceOperatorError(
            "calculation result must not impersonate owner acceptance"
        )
    return private_result, evaluated_at, max_age, quanta


def _validate_result_package(
    *,
    run: BrokerCurrentPositionValuationRun,
    broker_snapshot: BrokerPositionSnapshot,
    acquisition_manifest_sha256: str,
    position_binding_sha256: str,
    result_manifest_bytes: bytes,
    result_files: Mapping[str, bytes],
) -> tuple[str, dict[str, Any]]:
    manifest = _exact_fields(
        _canonical_json_document(result_manifest_bytes, "result manifest"),
        {
            "schema",
            "package_version",
            "supersedes_package",
            "files",
            "run_uid",
            "snapshot_uid",
            "result_fingerprint",
            "position_count",
            "cost_basis_available_count",
            "market_value_available_count",
            "unrealized_pnl_available_count",
            "complete_portfolio_cost_basis_available",
            "complete_portfolio_market_value_available",
            "complete_portfolio_unrealized_pnl_available",
            "financial_acceptance",
            "final_status",
            "historical_evidence_preserved",
            "provider_call_performed",
            "credential_access_performed",
            "database_write_performed",
            "manifest_written_last",
        },
        "result manifest",
    )
    _validate_package_files(
        manifest,
        result_files,
        (
            PRIVATE_RESULT_FILENAME,
            PRIVACY_AUDIT_FILENAME,
            SOURCE_LINEAGE_FILENAME,
        ),
        "result package",
    )
    private_result, _, _, _ = _result_policy(
        result_files[PRIVATE_RESULT_FILENAME]
    )
    result_fingerprint = calculate_broker_current_position_result_fingerprint(run)
    expected_private_result = {
        "schema": PRIVATE_RESULT_SCHEMA,
        "result_fingerprint": result_fingerprint,
        "run": broker_current_position_valuation_run_document(run),
    }
    if private_result != expected_private_result:
        raise BrokerCurrentPersistenceOperatorError(
            "private result does not exactly replay from source evidence"
        )

    expected_audit = run.privacy_safe_audit()
    expected_audit.update(
        {
            "acquisition_manifest_sha256": acquisition_manifest_sha256,
            "position_binding_sha256": position_binding_sha256,
            "adapter_version": broker_snapshot.adapter_version,
            "raw_sha256": broker_snapshot.raw_sha256,
            "result_fingerprint": result_fingerprint,
        }
    )
    audit = _canonical_json_document(
        result_files[PRIVACY_AUDIT_FILENAME], "privacy-safe audit"
    )
    if audit != expected_audit:
        raise BrokerCurrentPersistenceOperatorError(
            "privacy-safe audit does not match the replayed result"
        )

    supersedes = manifest["supersedes_package"]
    if not isinstance(supersedes, str) or not supersedes:
        raise BrokerCurrentPersistenceOperatorError(
            "result supersession lineage is invalid"
        )
    expected_lineage = {
        "schema": SOURCE_LINEAGE_SCHEMA,
        "valuation_contract_version": run.contract_version,
        "basis_method": run.basis_method,
        "snapshot_uid": run.snapshot_uid,
        "adapter_version": broker_snapshot.adapter_version,
        "raw_sha256": broker_snapshot.raw_sha256,
        "acquisition_manifest_sha256": acquisition_manifest_sha256,
        "position_binding_sha256": position_binding_sha256,
        "currency_quantum_by_currency": {
            key: format(value, "f")
            for key, value in sorted(run.currency_quantum_by_currency.items())
        },
        "result_fingerprint": result_fingerprint,
        "supersedes_package": supersedes,
        "historical_evidence_preserved": True,
        "financial_acceptance": False,
        "provider_call_performed": False,
        "credential_access_performed": False,
        "database_write_performed": False,
    }
    lineage = _canonical_json_document(
        result_files[SOURCE_LINEAGE_FILENAME], "source lineage"
    )
    if lineage != expected_lineage:
        raise BrokerCurrentPersistenceOperatorError(
            "source lineage does not match the replayed result"
        )

    expected_manifest = {
        "schema": RESULT_PACKAGE_SCHEMA,
        "package_version": 2,
        "supersedes_package": supersedes,
        "files": [
            {
                "filename": name,
                "mode": "0600",
                "sha256": _digest(result_files[name]),
            }
            for name in (
                PRIVATE_RESULT_FILENAME,
                PRIVACY_AUDIT_FILENAME,
                SOURCE_LINEAGE_FILENAME,
            )
        ],
        "run_uid": run.run_uid,
        "snapshot_uid": run.snapshot_uid,
        "result_fingerprint": result_fingerprint,
        "position_count": run.position_count,
        "cost_basis_available_count": run.cost_basis_available_count,
        "market_value_available_count": run.market_value_available_count,
        "unrealized_pnl_available_count": run.unrealized_pnl_available_count,
        "complete_portfolio_cost_basis_available": (
            run.complete_portfolio_cost_basis_available
        ),
        "complete_portfolio_market_value_available": (
            run.complete_portfolio_market_value_available
        ),
        "complete_portfolio_unrealized_pnl_available": (
            run.complete_portfolio_unrealized_pnl_available
        ),
        "financial_acceptance": False,
        "final_status": run.final_status,
        "historical_evidence_preserved": True,
        "provider_call_performed": False,
        "credential_access_performed": False,
        "database_write_performed": False,
        "manifest_written_last": True,
    }
    if manifest != expected_manifest:
        raise BrokerCurrentPersistenceOperatorError(
            "result manifest does not match the replayed result"
        )
    return _digest(result_manifest_bytes), manifest


def _validate_acceptance_package(
    *,
    run: BrokerCurrentPositionValuationRun,
    result_manifest_sha256: str,
    acceptance_manifest_bytes: bytes,
    acceptance_files: Mapping[str, bytes],
) -> tuple[BrokerCurrentOwnerAcceptance, str]:
    manifest = _exact_fields(
        _canonical_json_document(
            acceptance_manifest_bytes, "acceptance manifest"
        ),
        {
            "schema",
            "accepted_result_manifest_sha256",
            "financial_release_authorization_sha256",
            "files",
            "owner_acceptance_uid",
            "valuation_run_uid",
            "result_fingerprint",
            "accepted_scope",
            "decision",
            "fifo_history_reinterpreted",
            "provider_call_performed",
            "credential_access_performed",
            "database_write_performed",
            "manifest_written_last",
            "final_status",
        },
        "acceptance manifest",
    )
    _validate_package_files(
        manifest,
        acceptance_files,
        (FINANCIAL_AUTHORIZATION_FILENAME,),
        "acceptance package",
    )
    authorization = _exact_fields(
        _canonical_json_document(
            acceptance_files[FINANCIAL_AUTHORIZATION_FILENAME],
            "financial release authorization",
        ),
        {
            "contract_version",
            "owner_acceptance_uid",
            "valuation_run_uid",
            "result_fingerprint",
            "accepted_at",
            "accepted_scope",
            "approval_source",
            "decision",
            "fifo_history_reinterpreted",
        },
        "financial release authorization",
    )
    owner_uid = authorization["owner_acceptance_uid"]
    if not isinstance(owner_uid, str) or not 0 < len(owner_uid) <= 256:
        raise BrokerCurrentPersistenceOperatorError(
            "owner acceptance identity is invalid"
        )
    accepted_at = _utc_instant(authorization["accepted_at"], "accepted_at")
    result_fingerprint = calculate_broker_current_position_result_fingerprint(run)
    expected_authorization = {
        "contract_version": AUTHORIZATION_CONTRACT_VERSION,
        "owner_acceptance_uid": owner_uid,
        "valuation_run_uid": run.run_uid,
        "result_fingerprint": result_fingerprint,
        "accepted_at": authorization["accepted_at"],
        "accepted_scope": "broker_reconciled_current_position",
        "approval_source": "project_owner_explicit_proceed",
        "decision": "accepted",
        "fifo_history_reinterpreted": False,
    }
    if authorization != expected_authorization:
        raise BrokerCurrentPersistenceOperatorError(
            "financial release authorization does not match the replayed result"
        )
    if accepted_at < run.evaluated_at:
        raise BrokerCurrentPersistenceOperatorError(
            "owner acceptance predates the replayed result"
        )
    expected_manifest = {
        "schema": ACCEPTANCE_PACKAGE_SCHEMA,
        "accepted_result_manifest_sha256": result_manifest_sha256,
        "financial_release_authorization_sha256": _digest(
            acceptance_files[FINANCIAL_AUTHORIZATION_FILENAME]
        ),
        "files": [
            {
                "filename": FINANCIAL_AUTHORIZATION_FILENAME,
                "mode": "0600",
                "sha256": _digest(
                    acceptance_files[FINANCIAL_AUTHORIZATION_FILENAME]
                ),
            }
        ],
        "owner_acceptance_uid": owner_uid,
        "valuation_run_uid": run.run_uid,
        "result_fingerprint": result_fingerprint,
        "accepted_scope": "broker_reconciled_current_position",
        "decision": "accepted",
        "fifo_history_reinterpreted": False,
        "provider_call_performed": False,
        "credential_access_performed": False,
        "database_write_performed": False,
        "manifest_written_last": True,
        "final_status": "owner_accepted",
    }
    if manifest != expected_manifest:
        raise BrokerCurrentPersistenceOperatorError(
            "acceptance manifest does not bind the exact result"
        )
    return (
        BrokerCurrentOwnerAcceptance(
            owner_acceptance_uid=owner_uid,
            valuation_run_uid=run.run_uid,
            result_fingerprint=result_fingerprint,
            accepted_at=accepted_at,
        ),
        _digest(acceptance_manifest_bytes),
    )


def _accepted_evidence_evaluation_instant(
    acceptance_files: Mapping[str, bytes],
) -> datetime:
    """Return when the owner approved the completed evidence package.

    The valuation retains the earlier provider-response receipt time.  This
    later instant is used only to validate that the manifest-last acquisition
    package was complete and authorized before owner acceptance.
    """

    authorization = _exact_fields(
        _canonical_json_document(
            acceptance_files.get(FINANCIAL_AUTHORIZATION_FILENAME, b""),
            "financial release authorization",
        ),
        {
            "contract_version",
            "owner_acceptance_uid",
            "valuation_run_uid",
            "result_fingerprint",
            "accepted_at",
            "accepted_scope",
            "approval_source",
            "decision",
            "fifo_history_reinterpreted",
        },
        "financial release authorization",
    )
    return _utc_instant(authorization["accepted_at"], "accepted_at")


def prepare_broker_current_position_persistence(
    *,
    acquisition_manifest_bytes: bytes,
    response_bytes: Mapping[str, bytes],
    acknowledgement_bytes: bytes,
    position_binding_bytes: bytes,
    result_manifest_bytes: bytes,
    result_files: Mapping[str, bytes],
    acceptance_manifest_bytes: bytes,
    acceptance_files: Mapping[str, bytes],
    usage_policy: ProviderUsagePolicy,
    expected_acquisition_run_uid: str,
    expected_acquisition_approval_id: str,
    expected_owner_uid: str,
    expected_owner_epoch_uid: str,
) -> BrokerCurrentPersistencePlan:
    """Rebuild and bind one accepted result without filesystem or DB writes."""

    _, evaluated_at, _, _ = _result_policy(
        result_files.get(PRIVATE_RESULT_FILENAME, b"")
    )
    acquisition_evaluated_at = _accepted_evidence_evaluation_instant(
        acceptance_files
    )
    if acquisition_evaluated_at < evaluated_at:
        raise BrokerCurrentPersistenceOperatorError(
            "owner acceptance predates the valuation result"
        )
    acquisition = load_external_provider_acquisition(
        acquisition_manifest_bytes,
        response_bytes=response_bytes,
        acknowledgement_bytes=acknowledgement_bytes,
        usage_policy=usage_policy,
        evaluated_at_utc=acquisition_evaluated_at,
        expected_acquisition_run_uid=expected_acquisition_run_uid,
        expected_acquisition_approval_id=expected_acquisition_approval_id,
        expected_owner_uid=expected_owner_uid,
        expected_owner_epoch_uid=expected_owner_epoch_uid,
    )
    if acquisition.manifest.profile != SCHWAB_POSITION_EXTERNAL_ACQUISITION_PROFILE:
        raise BrokerCurrentPersistenceOperatorError(
            "acquisition profile is not the approved position profile"
        )
    binding = load_schwab_position_private_binding_bytes(position_binding_bytes)
    if binding.connection_uid != acquisition.manifest.connection_uid:
        raise BrokerCurrentPersistenceOperatorError(
            "private binding connection does not match acquisition"
        )
    converted = convert_external_schwab_positions(
        acquisition,
        provider_account_hash=binding.provider_account_hash,
        provider_account_number=binding.provider_account_number,
        source_account_id=binding.source_account_id,
        mappings=binding.mappings,
    )
    binding_sha256 = schwab_position_private_binding_sha256(
        position_binding_bytes
    )
    return validate_broker_current_position_persistence_packages(
        broker_snapshot=converted.snapshot,
        acquisition_manifest_sha256=acquisition.manifest_sha256,
        position_binding_sha256=binding_sha256,
        result_manifest_bytes=result_manifest_bytes,
        result_files=result_files,
        acceptance_manifest_bytes=acceptance_manifest_bytes,
        acceptance_files=acceptance_files,
    )


def validate_broker_current_position_persistence_packages(
    *,
    broker_snapshot: BrokerPositionSnapshot,
    acquisition_manifest_sha256: str,
    position_binding_sha256: str,
    result_manifest_bytes: bytes,
    result_files: Mapping[str, bytes],
    acceptance_manifest_bytes: bytes,
    acceptance_files: Mapping[str, bytes],
) -> BrokerCurrentPersistencePlan:
    """Rebuild and bind accepted packages from one validated broker snapshot."""

    acquisition_digest = _require_digest(
        acquisition_manifest_sha256, "acquisition manifest SHA-256"
    )
    binding_digest = _require_digest(
        position_binding_sha256, "position binding SHA-256"
    )
    private_result, evaluated_at, max_age, quanta = _result_policy(
        result_files.get(PRIVATE_RESULT_FILENAME, b"")
    )
    run = build_broker_current_position_valuation(
        broker_snapshot=broker_snapshot,
        evaluated_at=evaluated_at,
        max_snapshot_age_seconds=max_age,
        currency_quantum_by_currency=quanta,
    )
    if broker_current_position_valuation_run_document(run) != private_result.get(
        "run"
    ):
        raise BrokerCurrentPersistenceOperatorError(
            "replayed valuation differs from the accepted private result"
        )
    result_manifest_sha256, _ = _validate_result_package(
        run=run,
        broker_snapshot=broker_snapshot,
        acquisition_manifest_sha256=acquisition_digest,
        position_binding_sha256=binding_digest,
        result_manifest_bytes=result_manifest_bytes,
        result_files=result_files,
    )
    owner_acceptance, acceptance_manifest_sha256 = (
        _validate_acceptance_package(
            run=run,
            result_manifest_sha256=result_manifest_sha256,
            acceptance_manifest_bytes=acceptance_manifest_bytes,
            acceptance_files=acceptance_files,
        )
    )
    return BrokerCurrentPersistencePlan(
        run=run,
        broker_snapshot=broker_snapshot,
        owner_acceptance=owner_acceptance,
        acquisition_manifest_sha256=acquisition_digest,
        position_binding_sha256=binding_digest,
        result_manifest_sha256=result_manifest_sha256,
        acceptance_manifest_sha256=acceptance_manifest_sha256,
    )


def _require_private_database(path: Path, field: str) -> Path:
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise BrokerCurrentPersistenceOperatorError(
            f"{field} must be an absolute non-symlink file"
        )
    if stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise BrokerCurrentPersistenceOperatorError(f"{field} must have mode 0600")
    if stat.S_IMODE(path.parent.stat().st_mode) != 0o700:
        raise BrokerCurrentPersistenceOperatorError(
            f"{field} directory must have mode 0700"
        )
    return path


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _assert_read_back_matches(
    read_back: BrokerCurrentPositionValuationReadBack,
    run: BrokerCurrentPositionValuationRun,
) -> None:
    result_fingerprint = calculate_broker_current_position_result_fingerprint(run)
    header = (
        read_back.valuation_run_uid,
        read_back.contract_version,
        read_back.basis_method,
        read_back.snapshot_uid,
        read_back.source_broker,
        read_back.connection_uid,
        read_back.source_account_id,
        read_back.asof,
        read_back.retrieved_at_utc,
        read_back.evaluated_at_utc,
        read_back.max_snapshot_age_seconds,
        read_back.snapshot_age_seconds,
        dict(read_back.currency_quantum_by_currency),
        read_back.position_count,
        read_back.cost_basis_available_count,
        read_back.market_value_available_count,
        read_back.unrealized_pnl_available_count,
        read_back.complete_portfolio_cost_basis_available,
        read_back.complete_portfolio_market_value_available,
        read_back.complete_portfolio_unrealized_pnl_available,
        read_back.financial_acceptance,
        read_back.result_fingerprint,
        read_back.final_status,
    )
    expected_header = (
        run.run_uid,
        run.contract_version,
        run.basis_method,
        run.snapshot_uid,
        run.source_broker,
        run.connection_uid,
        run.source_account_id,
        run.asof,
        run.retrieved_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        run.evaluated_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        run.max_snapshot_age_seconds,
        run.snapshot_age_seconds,
        dict(run.currency_quantum_by_currency),
        run.position_count,
        run.cost_basis_available_count,
        run.market_value_available_count,
        run.unrealized_pnl_available_count,
        run.complete_portfolio_cost_basis_available,
        run.complete_portfolio_market_value_available,
        run.complete_portfolio_unrealized_pnl_available,
        False,
        result_fingerprint,
        run.final_status,
    )
    if header != expected_header:
        raise BrokerCurrentPersistenceOperatorError(
            "persisted broker-current run header differs from accepted result"
        )

    expected_positions = tuple(
        {
            "instrument_key": item.identity.key,
            "asset_class": item.identity.asset_class,
            "market_scope": item.identity.market_scope,
            "currency": item.identity.currency,
            "symbol": item.identity.symbol,
            "underlying_symbol": item.identity.underlying_symbol,
            "expiry": item.identity.expiry,
            "option_right": item.identity.option_right,
            "strike": item.identity.strike,
            "multiplier": item.identity.multiplier,
            "quantity": item.quantity,
            "tax_lot_average_price": item.tax_lot_average_price,
            "open_cost_basis": item.open_cost_basis,
            "broker_market_value": item.broker_market_value,
            "broker_reported_unrealized_pnl": (
                item.broker_reported_unrealized_pnl
            ),
            "unrealized_pnl": item.unrealized_pnl,
            "unrealized_reconciliation_difference": (
                item.unrealized_reconciliation_difference
            ),
            "cost_basis_status": item.cost_basis_status,
            "market_value_status": item.market_value_status,
            "unrealized_pnl_status": item.unrealized_pnl_status,
            "position_status": item.status,
            "reason_codes_json": json.dumps(
                list(item.reason_codes), separators=(",", ":")
            ),
        }
        for item in sorted(run.positions, key=lambda value: value.identity.key)
    )
    if read_back.positions != expected_positions:
        raise BrokerCurrentPersistenceOperatorError(
            "persisted broker-current positions differ from accepted result"
        )

    currencies = sorted(run.currency_quantum_by_currency)
    expected_totals = tuple(
        {
            "currency": currency,
            "portfolio_cost_basis": (
                (run.portfolio_cost_basis_by_currency or {}).get(currency)
            ),
            "portfolio_market_value": (
                (run.portfolio_market_value_by_currency or {}).get(currency)
            ),
            "portfolio_unrealized_pnl": (
                (run.portfolio_unrealized_pnl_by_currency or {}).get(currency)
            ),
        }
        for currency in currencies
    )
    if read_back.portfolio_totals != expected_totals:
        raise BrokerCurrentPersistenceOperatorError(
            "persisted broker-current totals differ from accepted result"
        )


def _database_contract(
    con: duckdb.DuckDBPyConnection,
) -> None:
    tables = {str(row[0]) for row in con.execute("SHOW TABLES").fetchall()}
    required = set(REQUIRED_TABLES) | {
        "schema_migrations",
        "local_owner_financial_api_audit_events",
    }
    missing = required - tables
    if missing:
        raise BrokerCurrentPersistenceOperatorError(
            "database is missing required table(s): " + ", ".join(sorted(missing))
        )
    expected_checksum = sha256(MIGRATION_PATH.read_bytes()).hexdigest()
    migration = con.execute(
        "SELECT migration_name, file_checksum, status "
        "FROM schema_migrations WHERE version = ?",
        (REQUIRED_MIGRATION_VERSION,),
    ).fetchone()
    if migration != (
        "widen_broker_current_decimal_precision",
        expected_checksum,
        "applied",
    ):
        raise BrokerCurrentPersistenceOperatorError(
            "database migration 0023 ledger does not match repository"
        )
    latest = con.execute(
        "SELECT MAX(version) FROM schema_migrations WHERE status = 'applied'"
    ).fetchone()[0]
    if latest != REQUIRED_MIGRATION_VERSION:
        raise BrokerCurrentPersistenceOperatorError(
            "database schema version is not exactly 0023"
        )


def _inspect_target(
    db_path: Path,
    plan: BrokerCurrentPersistencePlan,
) -> str:
    snapshot_fingerprint = calculate_broker_position_snapshot_fingerprint(
        plan.broker_snapshot
    )
    result_fingerprint = calculate_broker_current_position_result_fingerprint(
        plan.run
    )
    with duckdb.connect(str(db_path), read_only=True) as con:
        _database_contract(con)
        prior_snapshot = con.execute(
            "SELECT snapshot_fingerprint FROM broker_position_snapshot_runs "
            "WHERE snapshot_uid = ?",
            (plan.broker_snapshot.snapshot_uid,),
        ).fetchone()
        if prior_snapshot is not None and prior_snapshot[0] != snapshot_fingerprint:
            raise BrokerCurrentPersistenceOperatorError(
                "target contains a conflicting broker snapshot replay"
            )
        prior_run = con.execute(
            "SELECT result_fingerprint FROM pnl_broker_current_valuation_runs "
            "WHERE valuation_run_uid = ?",
            (plan.run.run_uid,),
        ).fetchone()
        if prior_run is not None and prior_run[0] != result_fingerprint:
            raise BrokerCurrentPersistenceOperatorError(
                "target contains a conflicting broker-current valuation replay"
            )
        if prior_run is None:
            return "would_create"
    read_back = load_broker_current_position_valuation_run(
        db_path,
        valuation_run_uid=plan.run.run_uid,
    )
    if read_back is None:
        raise BrokerCurrentPersistenceOperatorError(
            "target run disappeared during read-only inspection"
        )
    _assert_read_back_matches(read_back, plan.run)
    return "identical_replay"


def execute_broker_current_position_persistence(
    db_path: Path,
    *,
    plan: BrokerCurrentPersistencePlan,
    expected_database_sha256: str,
    persist: bool = False,
    verified_backup_path: Path | None = None,
) -> BrokerCurrentPersistenceExecution:
    """Validate by default; append only with an exact backup and explicit flag."""

    target = _require_private_database(db_path, "database")
    expected_digest = _require_digest(
        expected_database_sha256, "expected database SHA-256"
    )
    if Path(str(target) + ".wal").exists():
        raise BrokerCurrentPersistenceOperatorError(
            "database WAL exists; target is not quiescent"
        )
    before_digest = _file_sha256(target)
    if before_digest != expected_digest:
        raise BrokerCurrentPersistenceOperatorError(
            "database checksum differs from the approved target"
        )
    if persist:
        if verified_backup_path is None:
            raise BrokerCurrentPersistenceOperatorError(
                "--persist requires a verified backup"
            )
        backup = _require_private_database(verified_backup_path, "verified backup")
        if target.samefile(backup):
            raise BrokerCurrentPersistenceOperatorError(
                "verified backup must be a distinct file"
            )
        if _file_sha256(backup) != before_digest:
            raise BrokerCurrentPersistenceOperatorError(
                "verified backup is not byte-identical to the approved target"
            )
    elif verified_backup_path is not None:
        raise BrokerCurrentPersistenceOperatorError(
            "verified backup is accepted only with --persist"
        )

    target_state = _inspect_target(target, plan)
    if not persist:
        after_digest = _file_sha256(target)
        if after_digest != before_digest:
            raise BrokerCurrentPersistenceOperatorError(
                "dry-run changed the database"
            )
        return BrokerCurrentPersistenceExecution(
            plan=plan,
            target_state_before=target_state,
            database_sha256_before=before_digest,
            database_sha256_after=after_digest,
            write_requested=False,
            created=False,
            replayed=False,
        )

    result = persist_broker_current_position_valuation_run(
        target,
        run=plan.run,
        broker_snapshot=plan.broker_snapshot,
    )
    read_back = load_broker_current_position_valuation_run(
        target,
        valuation_run_uid=plan.run.run_uid,
    )
    if read_back is None:
        raise BrokerCurrentPersistenceOperatorError(
            "persisted run is unavailable on exact read-back"
        )
    _assert_read_back_matches(read_back, plan.run)
    after_digest = _file_sha256(target)
    return BrokerCurrentPersistenceExecution(
        plan=plan,
        target_state_before=target_state,
        database_sha256_before=before_digest,
        database_sha256_after=after_digest,
        write_requested=True,
        created=result.created,
        replayed=result.replayed,
    )
