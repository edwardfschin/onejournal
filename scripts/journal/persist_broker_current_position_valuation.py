#!/usr/bin/env python3
"""Validate or explicitly persist one accepted broker-current valuation.

Dry-run is the default.  The operator only reads already captured private
evidence and cannot call a provider, access credentials, migrate a database,
or release financial values.  ``--persist`` additionally requires an exact
target digest and a distinct byte-identical private backup.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import stat
import sys
from typing import Mapping, Sequence


PROJECT_DIR = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from onejournal.journal.broker_current_position_persistence_operator import (  # noqa: E402
    ACCEPTANCE_PACKAGE_SCHEMA,
    FINANCIAL_AUTHORIZATION_FILENAME,
    PRIVATE_RESULT_FILENAME,
    PRIVACY_AUDIT_FILENAME,
    RESULT_PACKAGE_SCHEMA,
    SOURCE_LINEAGE_FILENAME,
    BrokerCurrentPersistenceOperatorError,
    execute_broker_current_position_persistence,
    prepare_broker_current_position_persistence,
)
from onejournal.provider_connectors import (  # noqa: E402
    EXTERNAL_PROVIDER_ACQUISITION_MANIFEST_FILENAME,
    load_provider_usage_policy,
)


MARKETDATA_CONFIG_PATH = PROJECT_DIR / "config" / "marketdata.yaml"
MAX_MANIFEST_BYTES = 256 * 1024
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
MAX_PRIVATE_DOCUMENT_BYTES = 1024 * 1024


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate or explicitly persist one checksum-bound, owner-accepted "
            "broker-current valuation; dry-run is the default"
        )
    )
    parser.add_argument("--acquisition-root", required=True, type=Path)
    parser.add_argument("--acknowledgement", required=True, type=Path)
    parser.add_argument("--position-binding", required=True, type=Path)
    parser.add_argument("--result-package-root", required=True, type=Path)
    parser.add_argument("--acceptance-package-root", required=True, type=Path)
    parser.add_argument("--expected-acquisition-run-uid", required=True)
    parser.add_argument("--expected-acquisition-approval-id", required=True)
    parser.add_argument("--expected-owner-uid", required=True)
    parser.add_argument("--expected-owner-epoch-uid", required=True)
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--expected-database-sha256", required=True)
    parser.add_argument(
        "--persist",
        action="store_true",
        help="Append the exact accepted run after every validation passes",
    )
    parser.add_argument(
        "--verified-backup",
        type=Path,
        help="Distinct byte-identical 0600 backup required with --persist",
    )
    return parser


def _require_private_directory(path: Path, field: str) -> Path:
    if not path.is_absolute() or path.is_symlink() or not path.is_dir():
        raise BrokerCurrentPersistenceOperatorError(
            f"{field} must be an absolute non-symlink directory"
        )
    if stat.S_IMODE(path.stat().st_mode) != 0o700:
        raise BrokerCurrentPersistenceOperatorError(f"{field} must have mode 0700")
    return path


def _read_private_file(
    path: Path,
    field: str,
    *,
    maximum_bytes: int,
) -> bytes:
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise BrokerCurrentPersistenceOperatorError(
            f"{field} must be an absolute non-symlink file"
        )
    if stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise BrokerCurrentPersistenceOperatorError(f"{field} must have mode 0600")
    size = path.stat().st_size
    if not 0 < size <= maximum_bytes:
        raise BrokerCurrentPersistenceOperatorError(
            f"{field} size is outside the accepted bound"
        )
    return path.read_bytes()


def _response_filenames(manifest_bytes: bytes) -> tuple[str, ...]:
    try:
        document = json.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BrokerCurrentPersistenceOperatorError(
            "acquisition manifest is not readable JSON"
        ) from exc
    requests = document.get("requests") if isinstance(document, dict) else None
    if not isinstance(requests, list) or len(requests) != 1:
        raise BrokerCurrentPersistenceOperatorError(
            "position acquisition manifest must contain exactly one request"
        )
    request = requests[0]
    name = request.get("response_filename") if isinstance(request, dict) else None
    if not isinstance(name, str) or Path(name).name != name or not name.endswith(".json"):
        raise BrokerCurrentPersistenceOperatorError(
            "position response filename is unsafe"
        )
    return (name,)


def _load_acquisition_bundle(
    root_path: Path,
) -> tuple[bytes, dict[str, bytes]]:
    root = _require_private_directory(root_path, "acquisition root")
    manifest_bytes = _read_private_file(
        root / EXTERNAL_PROVIDER_ACQUISITION_MANIFEST_FILENAME,
        "acquisition manifest",
        maximum_bytes=MAX_MANIFEST_BYTES,
    )
    response_names = _response_filenames(manifest_bytes)
    expected_names = {
        EXTERNAL_PROVIDER_ACQUISITION_MANIFEST_FILENAME,
        *response_names,
    }
    if {item.name for item in root.iterdir()} != expected_names:
        raise BrokerCurrentPersistenceOperatorError(
            "acquisition bundle files do not exactly match the manifest"
        )
    return (
        manifest_bytes,
        {
            name: _read_private_file(
                root / name,
                f"provider response {name}",
                maximum_bytes=MAX_RESPONSE_BYTES,
            )
            for name in response_names
        },
    )


def _load_package(
    root_path: Path,
    *,
    field: str,
    expected_schema: str,
    expected_names: tuple[str, ...],
) -> tuple[bytes, Mapping[str, bytes]]:
    root = _require_private_directory(root_path, field)
    actual_names = {item.name for item in root.iterdir()}
    required_names = {"manifest.json", *expected_names}
    if actual_names != required_names:
        raise BrokerCurrentPersistenceOperatorError(
            f"{field} files do not exactly match the contract"
        )
    manifest_bytes = _read_private_file(
        root / "manifest.json",
        f"{field} manifest",
        maximum_bytes=MAX_PRIVATE_DOCUMENT_BYTES,
    )
    try:
        manifest = json.loads(manifest_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BrokerCurrentPersistenceOperatorError(
            f"{field} manifest is not readable JSON"
        ) from exc
    if not isinstance(manifest, dict) or manifest.get("schema") != expected_schema:
        raise BrokerCurrentPersistenceOperatorError(
            f"{field} schema is unsupported"
        )
    return (
        manifest_bytes,
        {
            name: _read_private_file(
                root / name,
                f"{field} file {name}",
                maximum_bytes=MAX_PRIVATE_DOCUMENT_BYTES,
            )
            for name in expected_names
        },
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.persist and args.verified_backup is None:
        parser.error("--verified-backup is required with --persist")
    if not args.persist and args.verified_backup is not None:
        parser.error("--verified-backup is accepted only with --persist")

    try:
        acquisition_manifest, responses = _load_acquisition_bundle(
            args.acquisition_root
        )
        acknowledgement = _read_private_file(
            args.acknowledgement,
            "provider-use acknowledgement",
            maximum_bytes=MAX_MANIFEST_BYTES,
        )
        position_binding = _read_private_file(
            args.position_binding,
            "private position binding",
            maximum_bytes=MAX_PRIVATE_DOCUMENT_BYTES,
        )
        result_manifest, result_files = _load_package(
            args.result_package_root,
            field="result package",
            expected_schema=RESULT_PACKAGE_SCHEMA,
            expected_names=(
                PRIVATE_RESULT_FILENAME,
                PRIVACY_AUDIT_FILENAME,
                SOURCE_LINEAGE_FILENAME,
            ),
        )
        acceptance_manifest, acceptance_files = _load_package(
            args.acceptance_package_root,
            field="acceptance package",
            expected_schema=ACCEPTANCE_PACKAGE_SCHEMA,
            expected_names=(FINANCIAL_AUTHORIZATION_FILENAME,),
        )
        plan = prepare_broker_current_position_persistence(
            acquisition_manifest_bytes=acquisition_manifest,
            response_bytes=responses,
            acknowledgement_bytes=acknowledgement,
            position_binding_bytes=position_binding,
            result_manifest_bytes=result_manifest,
            result_files=result_files,
            acceptance_manifest_bytes=acceptance_manifest,
            acceptance_files=acceptance_files,
            usage_policy=load_provider_usage_policy(MARKETDATA_CONFIG_PATH),
            expected_acquisition_run_uid=args.expected_acquisition_run_uid,
            expected_acquisition_approval_id=(
                args.expected_acquisition_approval_id
            ),
            expected_owner_uid=args.expected_owner_uid,
            expected_owner_epoch_uid=args.expected_owner_epoch_uid,
        )
        execution = execute_broker_current_position_persistence(
            args.database,
            plan=plan,
            expected_database_sha256=args.expected_database_sha256,
            persist=args.persist,
            verified_backup_path=args.verified_backup,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        raise SystemExit(f"FAIL: {exc}") from exc
    print(
        json.dumps(
            execution.privacy_safe_audit(),
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
