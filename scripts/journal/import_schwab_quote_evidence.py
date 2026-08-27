#!/usr/bin/env python3
"""Verify and normalize a transferred OneBot Schwab quote-evidence bundle.

This operator is intentionally credential-free and read-only. It has no
network, provider, token, database, migration, or evidence-write capability.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import re
import stat
import sys
from typing import Any, Mapping, Sequence


PROJECT_DIR = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from onejournal.brokers.schwab.quotes_json import (  # noqa: E402
    SchwabQuoteRequest,
    normalized_quotes_from_payload,
)
from onejournal.market_data import (  # noqa: E402
    QuoteCaptureEnvelope,
    QuoteEvidenceSource,
    QuoteInstrumentRequest,
    assess_quote_freshness,
    load_market_data_policy,
    validate_quote_capture,
)


CAPTURE_SCHEMA = "onebot.schwab.quote-evidence-capture.v1"
PRODUCTION_QUOTES_URL = "https://api.schwabapi.com/marketdata/v1/quotes"
REQUEST_FIELDS = "quote,reference"
RAW_FILENAME = "quote-response.json"
MANIFEST_FILENAME = "capture-v1.json"
MAX_RESPONSE_BYTES = 5 * 1024 * 1024
MARKETDATA_CONFIG_PATH = PROJECT_DIR / "config" / "marketdata.yaml"

_MACHINE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")
_SYMBOL_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ./$:-]{0,63}")
_FULL_SHA_RE = re.compile(r"[0-9a-f]{40}")
_DIGEST_RE = re.compile(r"[0-9a-f]{64}")


class QuoteEvidenceImportError(RuntimeError):
    """The transferred evidence bundle failed a required trust gate."""


@dataclass(frozen=True)
class VerifiedBundle:
    capture_id: str
    symbol: str
    market_date: date
    started_at: datetime
    received_at: datetime
    raw_path: Path
    raw_sha256: str
    payload: dict[str, Any]
    source_repository_commit: str


def _machine_id(value: Any, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or value != value.strip()
        or not _MACHINE_ID_RE.fullmatch(value)
    ):
        raise QuoteEvidenceImportError(
            f"{field_name} must be an opaque machine identifier"
        )
    return value.strip()


def _full_sha(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not _FULL_SHA_RE.fullmatch(value):
        raise QuoteEvidenceImportError(f"{field_name} must be a full lowercase Git SHA")
    return value


def _mapping(value: Any, field_name: str, exact_keys: set[str]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise QuoteEvidenceImportError(f"{field_name} must be an object")
    if set(value) != exact_keys:
        raise QuoteEvidenceImportError(f"{field_name} fields do not match schema")
    return value


def _parse_utc(value: Any, field_name: str) -> datetime:
    if not isinstance(value, str):
        raise QuoteEvidenceImportError(f"{field_name} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise QuoteEvidenceImportError(
            f"{field_name} must be an ISO-8601 timestamp"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise QuoteEvidenceImportError(f"{field_name} must include a timezone")
    return parsed.astimezone(UTC)


def _require_private_dir(path: Path, field_name: str) -> None:
    if path.is_symlink() or not path.is_dir():
        raise QuoteEvidenceImportError(f"{field_name} must be a non-symlink directory")
    if stat.S_IMODE(path.stat().st_mode) != 0o700:
        raise QuoteEvidenceImportError(f"{field_name} must have mode 0700")


def _require_private_file(path: Path, field_name: str) -> None:
    if path.is_symlink() or not path.is_file():
        raise QuoteEvidenceImportError(f"{field_name} must be a non-symlink regular file")
    if stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise QuoteEvidenceImportError(f"{field_name} must have mode 0600")


def _validate_bundle_location(private_vault_root: Path, bundle_dir: Path) -> None:
    if not private_vault_root.is_absolute() or not bundle_dir.is_absolute():
        raise QuoteEvidenceImportError("vault and bundle paths must be explicit absolute paths")
    _require_private_dir(private_vault_root, "private_vault_root")
    _require_private_dir(bundle_dir, "bundle_dir")
    root_resolved = private_vault_root.resolve(strict=True)
    bundle_resolved = bundle_dir.resolve(strict=True)
    if root_resolved not in bundle_resolved.parents:
        raise QuoteEvidenceImportError("bundle_dir must be below private_vault_root")
    try:
        relative_bundle = bundle_dir.relative_to(private_vault_root)
    except ValueError as exc:
        raise QuoteEvidenceImportError(
            "bundle_dir must be lexically below private_vault_root"
        ) from exc
    current = private_vault_root
    for part in relative_bundle.parts:
        current = current / part
        if current.is_symlink():
            raise QuoteEvidenceImportError("bundle path must not contain symlinks")


def _parse_payload(body: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(
            body.decode("utf-8"),
            parse_float=Decimal,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"non-finite JSON number: {value}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise QuoteEvidenceImportError("raw quote is not valid finite JSON") from exc
    if not isinstance(payload, dict):
        raise QuoteEvidenceImportError("raw quote must be a JSON object")
    return payload


def verify_bundle(
    *,
    private_vault_root: Path,
    bundle_dir: Path,
    expected_approval_id: str,
    expected_terms_acknowledgement_id: str,
    expected_onebot_commit: str,
    expected_connection_uid: str,
    expected_symbol: str,
    expected_asof: date,
) -> VerifiedBundle:
    _validate_bundle_location(private_vault_root, bundle_dir)
    approval_id = _machine_id(expected_approval_id, "expected_approval_id")
    terms_id = _machine_id(
        expected_terms_acknowledgement_id,
        "expected_terms_acknowledgement_id",
    )
    connection_uid = _machine_id(expected_connection_uid, "expected_connection_uid")
    onebot_commit = _full_sha(expected_onebot_commit, "expected_onebot_commit")
    symbol = expected_symbol.strip().upper()
    if not _SYMBOL_RE.fullmatch(symbol) or "," in symbol:
        raise QuoteEvidenceImportError("expected_symbol must identify exactly one symbol")

    expected_files = {RAW_FILENAME, MANIFEST_FILENAME}
    if {path.name for path in bundle_dir.iterdir()} != expected_files:
        raise QuoteEvidenceImportError("bundle must contain exactly the two contract files")
    raw_path = bundle_dir / RAW_FILENAME
    manifest_path = bundle_dir / MANIFEST_FILENAME
    _require_private_file(raw_path, "raw quote")
    _require_private_file(manifest_path, "capture manifest")

    manifest_bytes = manifest_path.read_bytes()
    if len(manifest_bytes) > 256 * 1024:
        raise QuoteEvidenceImportError("capture manifest exceeds 256 KiB")
    try:
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QuoteEvidenceImportError("capture manifest is not valid JSON") from exc
    manifest = _mapping(
        manifest,
        "manifest",
        {
            "schema", "capture_id", "provider", "authorization", "token_owner",
            "request", "source", "capture", "controls",
        },
    )
    if manifest["schema"] != CAPTURE_SCHEMA or manifest["provider"] != "schwab":
        raise QuoteEvidenceImportError("unsupported capture schema or provider")
    capture_id = _machine_id(manifest["capture_id"], "capture_id")
    if capture_id != bundle_dir.name:
        raise QuoteEvidenceImportError("capture_id must match the bundle directory")

    authorization = _mapping(
        manifest["authorization"],
        "authorization",
        {"approval_id", "terms_acknowledgement_id"},
    )
    if authorization != {
        "approval_id": approval_id,
        "terms_acknowledgement_id": terms_id,
    }:
        raise QuoteEvidenceImportError("approval or terms acknowledgement mismatch")

    token_owner = _mapping(
        manifest["token_owner"], "token_owner", {"system", "connection_uid"}
    )
    if token_owner != {"system": "onebot", "connection_uid": connection_uid}:
        raise QuoteEvidenceImportError("OneBot token-owner identity mismatch")

    request = _mapping(
        manifest["request"],
        "request",
        {"method", "url", "query", "market_date", "redirects_allowed", "attempt_count"},
    )
    query = _mapping(request["query"], "request.query", {"symbols", "fields"})
    if (
        request["method"] != "GET"
        or request["url"] != PRODUCTION_QUOTES_URL
        or query != {"symbols": symbol, "fields": REQUEST_FIELDS}
        or request["redirects_allowed"] is not False
        or type(request["attempt_count"]) is not int
        or request["attempt_count"] != 1
    ):
        raise QuoteEvidenceImportError("capture request boundary mismatch")
    if request["market_date"] != expected_asof.isoformat():
        raise QuoteEvidenceImportError("capture market_date does not match --asof")

    source = _mapping(
        manifest["source"],
        "source",
        {"system", "repository_commit", "working_tree_clean_before_capture"},
    )
    if (
        source["system"] != "onebot"
        or _full_sha(source["repository_commit"], "source.repository_commit") != onebot_commit
        or source["working_tree_clean_before_capture"] is not True
    ):
        raise QuoteEvidenceImportError("OneBot source provenance mismatch")

    controls = _mapping(
        manifest["controls"],
        "controls",
        {"oauth_refresh_performed", "provider_get_count", "account_endpoint_calls", "order_endpoint_calls", "database_writes"},
    )
    if (
        controls["oauth_refresh_performed"] is not False
        or type(controls["provider_get_count"]) is not int
        or controls["provider_get_count"] != 1
        or any(
            type(controls[field_name]) is not int or controls[field_name] != 0
            for field_name in (
                "account_endpoint_calls",
                "order_endpoint_calls",
                "database_writes",
            )
        )
    ):
        raise QuoteEvidenceImportError("capture control counts or refresh state are unsafe")

    capture = _mapping(
        manifest["capture"],
        "capture",
        {"started_at", "received_at", "http_status", "content_type", "body_bytes", "body_sha256", "raw_file", "exact_response_bytes_retained"},
    )
    started_at = _parse_utc(capture["started_at"], "capture.started_at")
    received_at = _parse_utc(capture["received_at"], "capture.received_at")
    if received_at < started_at:
        raise QuoteEvidenceImportError("capture received_at precedes started_at")
    digest = capture["body_sha256"]
    if not isinstance(digest, str) or not _DIGEST_RE.fullmatch(digest):
        raise QuoteEvidenceImportError("capture.body_sha256 is invalid")
    if (
        type(capture["http_status"]) is not int
        or capture["http_status"] != 200
        or not isinstance(capture["content_type"], str)
        or "application/json" not in capture["content_type"].lower()
        or capture["raw_file"] != RAW_FILENAME
        or capture["exact_response_bytes_retained"] is not True
    ):
        raise QuoteEvidenceImportError("capture response metadata is unsafe")

    raw_body = raw_path.read_bytes()
    if not raw_body or len(raw_body) > MAX_RESPONSE_BYTES:
        raise QuoteEvidenceImportError("raw quote size is outside the contract")
    if (
        type(capture["body_bytes"]) is not int
        or capture["body_bytes"] != len(raw_body)
        or sha256(raw_body).hexdigest() != digest
    ):
        raise QuoteEvidenceImportError("raw quote bytes do not match the capture manifest")
    payload = _parse_payload(raw_body)
    if {str(key).strip().upper() for key in payload} != {symbol}:
        raise QuoteEvidenceImportError("raw quote symbol scope does not match approval")

    return VerifiedBundle(
        capture_id=capture_id,
        symbol=symbol,
        market_date=expected_asof,
        started_at=started_at,
        received_at=received_at,
        raw_path=raw_path,
        raw_sha256=digest,
        payload=payload,
        source_repository_commit=onebot_commit,
    )


def _parse_evaluated_at(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("evaluation timestamp must include a timezone")
    return parsed.astimezone(UTC)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify and normalize a transferred OneBot quote-evidence bundle"
    )
    parser.add_argument("--private-vault-root", required=True, type=Path)
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--instrument-key", required=True)
    parser.add_argument("--asset-class", required=True, choices=("stock", "option"))
    parser.add_argument("--currency", required=True)
    parser.add_argument("--connection-uid", required=True)
    parser.add_argument("--asof", required=True, type=date.fromisoformat)
    parser.add_argument("--evaluated-at", required=True, type=_parse_evaluated_at)
    parser.add_argument("--approval-id", required=True)
    parser.add_argument("--terms-acknowledgement-id", required=True)
    parser.add_argument("--expected-onebot-commit", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    bundle = verify_bundle(
        private_vault_root=args.private_vault_root,
        bundle_dir=args.bundle,
        expected_approval_id=args.approval_id,
        expected_terms_acknowledgement_id=args.terms_acknowledgement_id,
        expected_onebot_commit=args.expected_onebot_commit,
        expected_connection_uid=args.connection_uid,
        expected_symbol=args.symbol,
        expected_asof=args.asof,
    )
    request = SchwabQuoteRequest(
        provider_symbol=bundle.symbol,
        instrument_key=args.instrument_key,
        asset_class=args.asset_class,
        currency=args.currency,
    )
    logical_raw_path = f"data/raw/schwab/external/{bundle.capture_id}/{RAW_FILENAME}"
    (quote,) = normalized_quotes_from_payload(
        bundle.payload,
        requests=(request,),
        connection_uid=args.connection_uid,
        asof=args.asof,
        received_at=bundle.received_at,
        raw_path=logical_raw_path,
        raw_sha256=bundle.raw_sha256,
    )
    policy = load_market_data_policy(MARKETDATA_CONFIG_PATH)
    source_locator = bundle.raw_path.relative_to(args.private_vault_root).as_posix()
    capture = QuoteCaptureEnvelope(
        quote_run_uid=bundle.capture_id,
        provider="schwab",
        connection_uid=args.connection_uid,
        asof=args.asof,
        started_at=bundle.started_at,
        received_at=bundle.received_at,
        evaluated_at=args.evaluated_at,
        requests=(
            QuoteInstrumentRequest(
                instrument_key=args.instrument_key,
                provider_instrument_id=bundle.symbol,
                asset_class=args.asset_class,
                currency=args.currency.strip().upper(),
            ),
        ),
        source=QuoteEvidenceSource(
            storage_kind="external_private_vault",
            locator=source_locator,
            raw_sha256=bundle.raw_sha256,
        ),
        adapter_version=quote.adapter_version,
        quotes=(quote,),
    )
    validate_quote_capture(capture, policy=policy.freshness)
    freshness = assess_quote_freshness(
        quote,
        evaluated_at=args.evaluated_at,
        policy=policy.freshness,
    )
    summary = {
        "schema": "onejournal.schwab.quote-evidence-import-summary.v1",
        "capture_id": bundle.capture_id,
        "quote_uid": quote.quote_uid,
        "adapter_version": quote.adapter_version,
        "source_onebot_commit": bundle.source_repository_commit,
        "raw_sha256": bundle.raw_sha256,
        "capture_contract_version": capture.contract_version,
        "marketdata_policy_version": policy.contract_version,
        "freshness_status": freshness.status,
        "valuation_allowed": freshness.valuation_allowed,
        "database_writes": 0,
    }
    print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
