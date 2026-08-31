#!/usr/bin/env python3
"""Validate or materialize one credential-free external provider acquisition.

The operator reads exact provider bytes already transferred into a private
owner-only directory.  It has no provider, credential, refresh, account,
order, migration, or database capability.  Private materialization requires
an explicit flag and an already provisioned 0700 OneJournal vault root.
"""

from __future__ import annotations

import argparse
from datetime import UTC, date, datetime
import json
from pathlib import Path
import stat
import sys
from typing import Sequence


PROJECT_DIR = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from onejournal.brokers.schwab.market_hours_resolver import (  # noqa: E402
    SCHWAB_EQUITY_OPTION_SCOPE,
    SCHWAB_EQUITY_SCOPE,
    SCHWAB_INDEX_OPTION_SCOPE,
    SchwabMarketHoursResolver,
)
from onejournal.market_data import (  # noqa: E402
    QuoteInstrumentRequest,
    assess_quote_freshness,
    load_market_data_policy,
    resolve_provider_session_authority,
)
from onejournal.provider_connectors import (  # noqa: E402
    EXTERNAL_PROVIDER_ACQUISITION_MANIFEST_FILENAME,
    ExternalSchwabQuoteMapping,
    LocalPrivateRawCaptureStore,
    build_external_schwab_schedule_evidence,
    convert_external_schwab_quotes,
    load_external_provider_acquisition,
    load_provider_usage_policy,
)


MARKETDATA_CONFIG_PATH = PROJECT_DIR / "config" / "marketdata.yaml"
MAX_MANIFEST_BYTES = 256 * 1024
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
_SCOPE_BY_NAME = {
    "equity": SCHWAB_EQUITY_SCOPE,
    "equity_option": SCHWAB_EQUITY_OPTION_SCOPE,
    "index_option": SCHWAB_INDEX_OPTION_SCOPE,
}


class ExternalAcquisitionOperatorError(RuntimeError):
    """Raised before unsafe or incomplete external evidence can be used."""


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
            "Validate or append-only materialize a transferred external provider "
            "acquisition without provider, credential, migration, or database access"
        )
    )
    parser.add_argument("--acquisition-root", required=True, type=Path)
    parser.add_argument("--acknowledgement", required=True, type=Path)
    parser.add_argument("--expected-run-uid", required=True)
    parser.add_argument("--expected-approval-id", required=True)
    parser.add_argument("--expected-owner-uid", required=True)
    parser.add_argument("--expected-owner-epoch-uid", required=True)
    parser.add_argument("--evaluated-at", required=True, type=_instant)
    parser.add_argument("--normal-reference-date", required=True, type=date.fromisoformat)
    parser.add_argument("--schedule-valid-until", required=True, type=_instant)
    parser.add_argument(
        "--quote-mapping",
        action="append",
        nargs=6,
        required=True,
        metavar=(
            "REQUEST_UID",
            "INSTRUMENT_KEY",
            "PROVIDER_SYMBOL",
            "ASSET_CLASS",
            "CURRENCY",
            "SCHEDULE_SCOPE",
        ),
        help=(
            "Exact OneJournal mapping; SCHEDULE_SCOPE is equity, equity_option, "
            "or index_option"
        ),
    )
    parser.add_argument("--private-vault-root", type=Path)
    parser.add_argument(
        "--materialize-private",
        action="store_true",
        help="Append the canonical private capture after all validation and freshness checks",
    )
    parser.add_argument(
        "--require-valuation-allowed",
        action="store_true",
        help="Fail before materialization unless every quote is valuation-eligible",
    )
    return parser


def _require_private_directory(path: Path, field: str) -> Path:
    if not path.is_absolute() or path.is_symlink() or not path.is_dir():
        raise ExternalAcquisitionOperatorError(
            f"{field} must be an existing absolute non-symlink directory"
        )
    if stat.S_IMODE(path.stat().st_mode) != 0o700:
        raise ExternalAcquisitionOperatorError(f"{field} must have mode 0700")
    return path


def _read_private_file(path: Path, field: str, *, maximum_bytes: int) -> bytes:
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise ExternalAcquisitionOperatorError(
            f"{field} must be an existing absolute non-symlink file"
        )
    if stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise ExternalAcquisitionOperatorError(f"{field} must have mode 0600")
    size = path.stat().st_size
    if not 0 < size <= maximum_bytes:
        raise ExternalAcquisitionOperatorError(f"{field} size is outside the accepted bound")
    return path.read_bytes()


def _response_filenames(manifest_bytes: bytes) -> tuple[str, ...]:
    try:
        document = json.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExternalAcquisitionOperatorError(
            "acquisition manifest is not readable JSON"
        ) from exc
    requests = document.get("requests") if isinstance(document, dict) else None
    if not isinstance(requests, list) or not requests:
        raise ExternalAcquisitionOperatorError("acquisition manifest requests are unavailable")
    names: list[str] = []
    for index, request in enumerate(requests):
        name = request.get("response_filename") if isinstance(request, dict) else None
        if (
            not isinstance(name, str)
            or Path(name).name != name
            or not name.endswith(".json")
        ):
            raise ExternalAcquisitionOperatorError(
                f"acquisition response filename {index} is unsafe"
            )
        names.append(name)
    if len(set(names)) != len(names):
        raise ExternalAcquisitionOperatorError("acquisition response filenames are duplicate")
    return tuple(names)


def _load_bundle(acquisition_root: Path) -> tuple[bytes, dict[str, bytes]]:
    root = _require_private_directory(acquisition_root, "acquisition root")
    manifest_path = root / EXTERNAL_PROVIDER_ACQUISITION_MANIFEST_FILENAME
    manifest_bytes = _read_private_file(
        manifest_path,
        "acquisition manifest",
        maximum_bytes=MAX_MANIFEST_BYTES,
    )
    response_names = _response_filenames(manifest_bytes)
    expected_names = {
        EXTERNAL_PROVIDER_ACQUISITION_MANIFEST_FILENAME,
        *response_names,
    }
    actual_names = {item.name for item in root.iterdir()}
    if actual_names != expected_names:
        raise ExternalAcquisitionOperatorError(
            "acquisition bundle files do not exactly match the manifest"
        )
    responses = {
        name: _read_private_file(
            root / name,
            f"provider response {name}",
            maximum_bytes=MAX_RESPONSE_BYTES,
        )
        for name in response_names
    }
    return manifest_bytes, responses


def _mappings(
    rows: list[list[str]],
) -> tuple[
    tuple[ExternalSchwabQuoteMapping, ...],
    dict[str, object],
]:
    mappings: list[ExternalSchwabQuoteMapping] = []
    scope_by_request_uid: dict[str, object] = {}
    for row in rows:
        request_uid, instrument_key, provider_symbol, asset_class, currency, scope_name = row
        if request_uid in scope_by_request_uid:
            raise ExternalAcquisitionOperatorError("quote mapping request UIDs are duplicate")
        try:
            scope = _SCOPE_BY_NAME[scope_name]
        except KeyError as exc:
            raise ExternalAcquisitionOperatorError(
                f"unsupported schedule scope: {scope_name}"
            ) from exc
        mappings.append(
            ExternalSchwabQuoteMapping(
                request_uid=request_uid,
                instrument=QuoteInstrumentRequest(
                    instrument_key=instrument_key,
                    provider_instrument_id=provider_symbol,
                    asset_class=asset_class,
                    currency=currency,
                ),
            )
        )
        scope_by_request_uid[request_uid] = scope
    return tuple(mappings), scope_by_request_uid


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.materialize_private and args.private_vault_root is None:
        parser.error("--private-vault-root is required with --materialize-private")
    if not args.materialize_private and args.private_vault_root is not None:
        parser.error("--private-vault-root is accepted only with --materialize-private")

    manifest_bytes, response_bytes = _load_bundle(args.acquisition_root)
    acknowledgement_bytes = _read_private_file(
        args.acknowledgement,
        "provider-use acknowledgement",
        maximum_bytes=MAX_MANIFEST_BYTES,
    )
    usage_policy = load_provider_usage_policy(MARKETDATA_CONFIG_PATH)
    freshness_policy = load_market_data_policy(MARKETDATA_CONFIG_PATH).freshness
    acquisition = load_external_provider_acquisition(
        manifest_bytes,
        response_bytes=response_bytes,
        acknowledgement_bytes=acknowledgement_bytes,
        usage_policy=usage_policy,
        evaluated_at_utc=args.evaluated_at,
        expected_acquisition_run_uid=args.expected_run_uid,
        expected_acquisition_approval_id=args.expected_approval_id,
        expected_owner_uid=args.expected_owner_uid,
        expected_owner_epoch_uid=args.expected_owner_epoch_uid,
    )
    mappings, scope_by_request_uid = _mappings(args.quote_mapping)
    captures = convert_external_schwab_quotes(
        acquisition,
        mappings=mappings,
        evaluated_at_utc=args.evaluated_at,
        freshness_policy=freshness_policy,
    )
    schedules = build_external_schwab_schedule_evidence(
        acquisition,
        normal_reference_date=args.normal_reference_date,
        valid_until_utc=args.schedule_valid_until,
    )

    results: list[dict[str, object]] = []
    for converted in captures:
        scope = scope_by_request_uid[converted.external_request_uid]
        quote = converted.capture.quotes[0]
        authority = resolve_provider_session_authority(
            SchwabMarketHoursResolver(
                connection_uid=acquisition.manifest.connection_uid,
                scope=scope,
                evidence=schedules,
            ),
            quote=quote,
            evaluated_at=args.evaluated_at,
        )
        assessment = assess_quote_freshness(
            quote,
            evaluated_at=args.evaluated_at,
            session_authority=authority,
            policy=freshness_policy,
        )
        if args.require_valuation_allowed and not assessment.valuation_allowed:
            raise ExternalAcquisitionOperatorError(
                f"quote {converted.external_request_uid} is not valuation-eligible: "
                f"{assessment.reason}"
            )
        results.append(
            {
                "external_request_uid": converted.external_request_uid,
                "quote_run_uid": converted.capture.quote_run_uid,
                "quote_uid": quote.quote_uid,
                "instrument_key": quote.instrument_key,
                "provider_instrument_id": quote.provider_instrument_id,
                "source_locator": converted.source.locator,
                "source_raw_sha256": converted.source.raw_sha256,
                "session_authority_uid": authority.authority_uid,
                "freshness_status": assessment.status,
                "valuation_allowed": assessment.valuation_allowed,
                "freshness_reason": assessment.reason,
            }
        )

    if args.materialize_private:
        assert args.private_vault_root is not None
        store = LocalPrivateRawCaptureStore(
            private_root=_require_private_directory(
                args.private_vault_root,
                "private vault root",
            )
        )
        for converted in captures:
            store.commit(
                source=converted.source,
                raw_response_bytes=converted.raw_response_bytes,
                manifest=converted.private_manifest,
                capture=converted.capture,
            )

    summary = {
        "schema": "onejournal.external-provider-acquisition-intake-audit.v1",
        "acquisition_run_uid": acquisition.manifest.acquisition_run_uid,
        "acquisition_manifest_sha256": acquisition.manifest_sha256,
        "provider": acquisition.manifest.provider,
        "connection_uid": acquisition.manifest.connection_uid,
        "evaluated_at_utc": args.evaluated_at.isoformat(),
        "normal_reference_date": args.normal_reference_date.isoformat(),
        "quote_count": len(results),
        "quotes": results,
        "materialized_private": args.materialize_private,
        "final_status": (
            "materialized_private_uningested"
            if args.materialize_private
            else "validated_external_unmaterialized"
        ),
    }
    print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
