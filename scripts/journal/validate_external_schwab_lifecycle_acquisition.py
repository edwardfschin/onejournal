#!/usr/bin/env python3
"""Validate one transferred Schwab lifecycle bundle without side effects."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from hashlib import sha256
import json
from pathlib import Path
import stat
import sys
from typing import Sequence


PROJECT_DIR = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from onejournal.brokers.schwab.account_binding import (  # noqa: E402
    load_schwab_account_private_binding_bytes,
    schwab_account_private_binding_sha256,
)
from onejournal.provider_connectors import (  # noqa: E402
    EXTERNAL_PROVIDER_ACQUISITION_MANIFEST_FILENAME,
    SCHWAB_LIFECYCLE_EXTERNAL_ACQUISITION_PROFILE,
    convert_external_schwab_lifecycle,
    load_external_provider_acquisition,
    load_provider_usage_policy,
)


MARKETDATA_CONFIG_PATH = PROJECT_DIR / "config" / "marketdata.yaml"
MAX_MANIFEST_BYTES = 256 * 1024
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
MAX_BINDING_BYTES = 64 * 1024


class ExternalSchwabLifecycleIntakeError(RuntimeError):
    """Raised before unsafe lifecycle evidence is accepted."""


def _instant(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("timestamp must include a timezone")
    return parsed.astimezone(UTC)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate transferred Schwab lifecycle evidence without provider, "
            "credential, private-write, migration, or database capability"
        )
    )
    parser.add_argument("--acquisition-root", required=True, type=Path)
    parser.add_argument("--acknowledgement", required=True, type=Path)
    parser.add_argument("--account-binding", required=True, type=Path)
    parser.add_argument("--expected-run-uid", required=True)
    parser.add_argument("--expected-approval-id", required=True)
    parser.add_argument("--expected-owner-uid", required=True)
    parser.add_argument("--expected-owner-epoch-uid", required=True)
    parser.add_argument("--evaluated-at", required=True, type=_instant)
    return parser


def _require_private_directory(path: Path, field: str) -> Path:
    if not path.is_absolute() or path.is_symlink() or not path.is_dir():
        raise ExternalSchwabLifecycleIntakeError(
            f"{field} must be an existing absolute non-symlink directory"
        )
    if stat.S_IMODE(path.stat().st_mode) != 0o700:
        raise ExternalSchwabLifecycleIntakeError(f"{field} must have mode 0700")
    return path


def _read_private_file(path: Path, field: str, *, maximum_bytes: int) -> bytes:
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise ExternalSchwabLifecycleIntakeError(
            f"{field} must be an existing absolute non-symlink file"
        )
    if stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise ExternalSchwabLifecycleIntakeError(f"{field} must have mode 0600")
    size = path.stat().st_size
    if not 0 < size <= maximum_bytes:
        raise ExternalSchwabLifecycleIntakeError(
            f"{field} size is outside the accepted bound"
        )
    return path.read_bytes()


def _response_filenames(manifest_bytes: bytes) -> tuple[str, str]:
    try:
        document = json.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExternalSchwabLifecycleIntakeError(
            "acquisition manifest is not readable JSON"
        ) from exc
    requests = document.get("requests") if isinstance(document, dict) else None
    if not isinstance(requests, list) or len(requests) != 2:
        raise ExternalSchwabLifecycleIntakeError(
            "lifecycle acquisition manifest must contain exactly two requests"
        )
    names: list[str] = []
    for index, request in enumerate(requests):
        name = request.get("response_filename") if isinstance(request, dict) else None
        if (
            not isinstance(name, str)
            or Path(name).name != name
            or not name.endswith(".json")
            or name in names
        ):
            raise ExternalSchwabLifecycleIntakeError(
                f"lifecycle response filename {index} is unsafe"
            )
        names.append(name)
    return names[0], names[1]


def _load_bundle(acquisition_root: Path) -> tuple[bytes, dict[str, bytes]]:
    root = _require_private_directory(acquisition_root, "acquisition root")
    manifest_path = root / EXTERNAL_PROVIDER_ACQUISITION_MANIFEST_FILENAME
    manifest_bytes = _read_private_file(
        manifest_path,
        "acquisition manifest",
        maximum_bytes=MAX_MANIFEST_BYTES,
    )
    response_names = _response_filenames(manifest_bytes)
    expected_names = {EXTERNAL_PROVIDER_ACQUISITION_MANIFEST_FILENAME, *response_names}
    actual_names = {item.name for item in root.iterdir()}
    if actual_names != expected_names:
        raise ExternalSchwabLifecycleIntakeError(
            "acquisition bundle files do not exactly match the manifest"
        )
    return manifest_bytes, {
        name: _read_private_file(
            root / name,
            f"provider response {name}",
            maximum_bytes=MAX_RESPONSE_BYTES,
        )
        for name in response_names
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    manifest_bytes, response_bytes = _load_bundle(args.acquisition_root)
    acknowledgement_bytes = _read_private_file(
        args.acknowledgement,
        "provider-use acknowledgement",
        maximum_bytes=MAX_MANIFEST_BYTES,
    )
    binding_bytes = _read_private_file(
        args.account_binding,
        "private account binding",
        maximum_bytes=MAX_BINDING_BYTES,
    )
    binding = load_schwab_account_private_binding_bytes(binding_bytes)
    acquisition = load_external_provider_acquisition(
        manifest_bytes,
        response_bytes=response_bytes,
        acknowledgement_bytes=acknowledgement_bytes,
        usage_policy=load_provider_usage_policy(MARKETDATA_CONFIG_PATH),
        evaluated_at_utc=args.evaluated_at,
        expected_acquisition_run_uid=args.expected_run_uid,
        expected_acquisition_approval_id=args.expected_approval_id,
        expected_owner_uid=args.expected_owner_uid,
        expected_owner_epoch_uid=args.expected_owner_epoch_uid,
    )
    if acquisition.manifest.profile != SCHWAB_LIFECYCLE_EXTERNAL_ACQUISITION_PROFILE:
        raise ExternalSchwabLifecycleIntakeError(
            "acquisition profile is not the approved lifecycle profile"
        )
    if binding.connection_uid != acquisition.manifest.connection_uid:
        raise ExternalSchwabLifecycleIntakeError("private account binding mismatch")
    converted = convert_external_schwab_lifecycle(
        acquisition,
        provider_account_hash=binding.provider_account_hash,
        provider_account_number=binding.provider_account_number,
        source_account_id=binding.source_account_id,
    )
    print(
        json.dumps(
            {
                "schema": "onejournal.external-schwab-lifecycle-intake-audit.v1",
                "acquisition_run_uid": acquisition.manifest.acquisition_run_uid,
                "acquisition_manifest_sha256": acquisition.manifest_sha256,
                "account_binding_sha256": schwab_account_private_binding_sha256(
                    binding_bytes
                ),
                "provider": acquisition.manifest.provider,
                "connection_uid": acquisition.manifest.connection_uid,
                "source_account_id_sha256": sha256(
                    binding.source_account_id.encode("utf-8")
                ).hexdigest(),
                "window_start_date": converted.window_start_date.isoformat(),
                "window_end_date": converted.window_end_date.isoformat(),
                "order_count": converted.order_stats.top_level_orders,
                "transaction_count": converted.transaction_stats.transactions,
                "currency_consensus_evidence_item_count": (
                    converted.transaction_stats.currency_consensus_evidence_items
                ),
                "currency_consensus_code": (
                    converted.transaction_stats.currency_consensus_code
                ),
                "currency_consensus_resolved_records": (
                    converted.transaction_stats.currency_consensus_resolved_records
                ),
                "order_fill_rows": len(converted.order_rows),
                "transaction_fill_rows": len(converted.transaction_rows),
                "lifecycle_event_rows": len(converted.lifecycle_events),
                "lifecycle_event_leg_rows": len(converted.lifecycle_event_legs),
                "excluded_out_of_window_order_fill_rows": (
                    converted.excluded_out_of_window_order_fill_rows
                ),
                "excluded_out_of_window_transaction_fill_rows": (
                    converted.excluded_out_of_window_transaction_fill_rows
                ),
                "excluded_out_of_window_lifecycle_events": (
                    converted.excluded_out_of_window_lifecycle_events
                ),
                "excluded_out_of_window_lifecycle_event_legs": (
                    converted.excluded_out_of_window_lifecycle_event_legs
                ),
                "matched_fill_rows": converted.reconciliation.matched_rows,
                "only_order_fill_rows": converted.reconciliation.only_order_rows,
                "only_transaction_fill_rows": (
                    converted.reconciliation.only_transaction_rows
                ),
                "reconciliation_status": (
                    "exact" if converted.reconciliation.exact else "pending"
                ),
                "final_status": "validated_external_lifecycle_unmaterialized",
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
