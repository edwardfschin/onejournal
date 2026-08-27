#!/usr/bin/env python3
"""Guarded single-symbol Schwab quote evidence capture operator.

The default mode is plan-only: no credential access, network, or file write.
Live execution requires a separate approval identifier, a terms-
acknowledgement identifier, and ``--execute-read-only``. Even then, this
operator can issue only one GET to Schwab's production market-data quotes
endpoint (plus a token refresh if the existing token requires it).

The exact response bytes are captured atomically under ``data/raw/schwab``.
Normalization and freshness assessment happen in memory only. This operator
never opens DuckDB and has no order endpoint or order method.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
import re
import stat
import subprocess
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Iterator, Mapping, Sequence

import requests


PROJECT_DIR = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from onejournal.brokers.schwab.quotes_json import (  # noqa: E402
    SchwabQuoteRequest,
    normalized_quotes_from_payload,
)
from onejournal.market_data import assess_quote_freshness  # noqa: E402


FETCHER_PATH = PROJECT_DIR / "scripts/journal/fetch_schwab_raw_history.py"
RAW_ROOT = PROJECT_DIR / "data/raw/schwab"
SCHWAB_PRODUCTION_BASE = "https://api.schwabapi.com"
QUOTES_URL = f"{SCHWAB_PRODUCTION_BASE}/marketdata/v1/quotes"
MAX_RESPONSE_BYTES = 5 * 1024 * 1024
_SYMBOL_RE = re.compile(r"[A-Za-z0-9$./:_ -]{1,64}")
_MACHINE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")


def _load_fetcher() -> Any:
    spec = importlib.util.spec_from_file_location(
        "onejournal_schwab_raw_fetcher_for_quotes", FETCHER_PATH
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load Schwab credential boundary: {FETCHER_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


fetcher = _load_fetcher()


@dataclass(frozen=True)
class CapturedQuoteResponse:
    payload: dict[str, Any]
    body: bytes
    received_at: datetime


@dataclass
class SchwabQuoteReadOnlyClient:
    """Exact-byte, GET-only transport for one Schwab quote request."""

    auth: Any
    session: requests.Session
    timeout: int = 30

    def _headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.auth.get_access_token()}",
            "Accept": "application/json",
            "Schwab-Resource-Version": fetcher.RESOURCE_VERSION,
            "Schwab-Client-CorrelId": "onejournal-quote-capture",
        }
        return headers

    def _get(self, symbol: str) -> Any:
        return self.session.get(
            QUOTES_URL,
            headers=self._headers(),
            params={"symbols": symbol, "fields": "quote,reference"},
            timeout=self.timeout,
            allow_redirects=False,
        )

    def fetch_one(self, symbol: str) -> CapturedQuoteResponse:
        response = self._get(symbol)
        if response.status_code == 401:
            self.auth.refresh()
            response = self._get(symbol)
        if not (200 <= response.status_code < 300):
            raise RuntimeError(
                f"Schwab quote GET failed with HTTP {response.status_code}; "
                "response body suppressed"
            )
        content_type = str(response.headers.get("Content-Type", "")).lower()
        if "application/json" not in content_type:
            raise RuntimeError("Schwab quote GET returned a non-JSON content type")
        body = bytes(response.content)
        if not body:
            raise RuntimeError("Schwab quote GET returned an empty response")
        if len(body) > MAX_RESPONSE_BYTES:
            raise RuntimeError("Schwab quote response exceeds the 5 MiB safety limit")
        try:
            payload = json.loads(
                body,
                parse_float=Decimal,
                parse_constant=lambda value: (_ for _ in ()).throw(
                    ValueError(f"invalid non-finite JSON number: {value}")
                ),
            )
        except Exception as exc:
            raise RuntimeError("Schwab quote GET returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("Schwab quote GET returned a non-object payload")
        return CapturedQuoteResponse(
            payload=payload,
            body=body,
            received_at=datetime.now(tz=UTC),
        )


def _parse_ymd(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"invalid date {value!r}; expected YYYY-MM-DD"
        ) from exc


def _provider_symbol(value: str) -> str:
    symbol = value.strip()
    if not _SYMBOL_RE.fullmatch(symbol) or "," in symbol:
        raise argparse.ArgumentTypeError(
            "symbol must be 1-64 safe provider-symbol characters and contain no comma"
        )
    return symbol


def _nonempty(value: str, field_name: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field_name} is required")
    return cleaned


def _machine_id(value: str, field_name: str) -> str:
    cleaned = _nonempty(value, field_name)
    if not _MACHINE_ID_RE.fullmatch(cleaned):
        raise ValueError(
            f"{field_name} must be a 1-128 character opaque machine identifier"
        )
    return cleaned


def _validate_production_boundary() -> None:
    if fetcher.SCHWAB_BASE != SCHWAB_PRODUCTION_BASE:
        raise RuntimeError(
            "Refusing non-production or overridden ONEJOURNAL_SCHWAB_BASE for quote capture"
        )
    if QUOTES_URL != "https://api.schwabapi.com/marketdata/v1/quotes":
        raise RuntimeError("Schwab quote endpoint boundary changed unexpectedly")


def validate_repository_provenance(expected_commit: str) -> str:
    """Require the exact approved clean repository revision before provider access."""

    expected = expected_commit.strip().lower()
    if not re.fullmatch(r"[0-9a-f]{40}", expected):
        raise RuntimeError("expected_repository_commit must be a full 40-character SHA")
    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_DIR,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip().lower()
        status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=normal"],
            cwd=PROJECT_DIR,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError("unable to establish repository provenance") from exc
    if head != expected:
        raise RuntimeError(
            f"repository commit mismatch: expected {expected}, found {head}"
        )
    if status.strip():
        raise RuntimeError("repository working tree must be clean before provider access")
    return head


@contextmanager
def single_operator_lock(token_path: Path) -> Iterator[None]:
    """Serialize quote capture with the guarded raw-history backfill operator."""

    lock_path = token_path.parent / ".schwab_raw_history_backfill.lock"
    with lock_path.open("a+", encoding="utf-8") as handle:
        os.chmod(lock_path, 0o600)
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("another Schwab quote capture holds the operator lock") from exc
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def validate_token_file(token_path: Path) -> None:
    """Reject missing, linked, non-file, or publicly accessible token paths."""

    if token_path.is_symlink():
        raise RuntimeError("refusing symlinked Schwab token path")
    if not token_path.exists() or not token_path.is_file():
        raise RuntimeError("Schwab token path must be an existing regular file")
    mode = stat.S_IMODE(token_path.stat().st_mode)
    if mode & 0o077 or not mode & 0o400:
        raise RuntimeError(
            "Schwab token file must be owner-readable with no group/other permissions"
        )


def build_live_client(
    token_path: Path,
    environ: Mapping[str, str],
) -> SchwabQuoteReadOnlyClient:
    client_id = environ.get("ONEJOURNAL_SCHWAB_CLIENT_ID", "").strip()
    if not client_id:
        raise RuntimeError("ONEJOURNAL_SCHWAB_CLIENT_ID is required")
    auth = fetcher.SchwabAuth(
        store=fetcher.TokenStore(token_path),
        client_id=client_id,
        client_secret=environ.get("ONEJOURNAL_SCHWAB_CLIENT_SECRET", "").strip(),
        redirect_uri=environ.get(
            "ONEJOURNAL_SCHWAB_REDIRECT_URI",
            "https://127.0.0.1:8182/callback",
        ).strip(),
    )
    return SchwabQuoteReadOnlyClient(auth=auth, session=requests.Session())


def _raw_quote_path(root: Path, asof: date, received_at: datetime, symbol: str) -> Path:
    timestamp = received_at.astimezone(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    symbol_digest = hashlib.sha256(symbol.upper().encode("utf-8")).hexdigest()[:12]
    return root / asof.isoformat() / "quotes" / f"quote_{timestamp}_{symbol_digest}.json"


def _secure_exact_write(path: Path, body: bytes) -> None:
    if path.exists():
        raise FileExistsError(f"refusing to overwrite existing raw quote: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    with NamedTemporaryFile(
        "wb",
        delete=False,
        dir=str(path.parent),
        prefix=path.name + ".",
        suffix=".tmp",
    ) as temporary:
        temporary.write(body)
        temporary.flush()
        os.fsync(temporary.fileno())
        temporary_path = Path(temporary.name)
    os.chmod(temporary_path, 0o600)
    os.replace(temporary_path, path)
    os.chmod(path, 0o600)


def _manifest_body(
    *,
    request: SchwabQuoteRequest,
    connection_uid: str,
    asof: date,
    received_at: datetime,
    approval_id: str,
    acknowledgement_id: str,
    repository_commit: str,
    raw_path: str,
    raw_sha256: str,
    quote_uid: str,
    adapter_version: str,
    freshness_status: str,
    valuation_allowed: bool,
) -> bytes:
    payload = {
        "schema_version": 1,
        "provider": "schwab",
        "endpoint": QUOTES_URL,
        "request": {
            "provider_symbol": request.provider_symbol,
            "instrument_key": request.instrument_key,
            "asset_class": request.asset_class,
            "currency": request.currency,
            "connection_uid": connection_uid,
            "asof": asof.isoformat(),
        },
        "authorization": {
            "approval_id": approval_id,
            "terms_acknowledgement_id": acknowledgement_id,
        },
        "repository": {
            "commit": repository_commit,
            "working_tree_clean_before_capture": True,
        },
        "capture": {
            "received_at_utc": received_at.astimezone(UTC).isoformat().replace(
                "+00:00", "Z"
            ),
            "raw_path": raw_path,
            "raw_sha256": raw_sha256,
            "exact_response_bytes_retained": True,
        },
        "validation": {
            "normalized_quote_uid": quote_uid,
            "adapter_version": adapter_version,
            "freshness_status": freshness_status,
            "valuation_allowed": valuation_allowed,
            "database_writes": 0,
        },
    }
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _relative_raw_path(path: Path) -> str:
    try:
        return path.relative_to(PROJECT_DIR).as_posix()
    except ValueError as exc:
        raise RuntimeError("raw quote path must remain under the OneJournal project") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Plan or execute one guarded read-only Schwab quote capture."
    )
    parser.add_argument("--symbol", required=True, type=_provider_symbol)
    parser.add_argument("--instrument-key", required=True)
    parser.add_argument("--asset-class", required=True, choices=("stock", "option"))
    parser.add_argument("--currency", required=True)
    parser.add_argument("--asof", required=True, type=_parse_ymd)
    parser.add_argument("--connection-uid", required=True)
    parser.add_argument("--token-path", default=str(fetcher.DEFAULT_TOKEN_PATH))
    parser.add_argument("--approval-id", default="")
    parser.add_argument("--terms-acknowledgement-id", default="")
    parser.add_argument("--expected-repository-commit", default="")
    parser.add_argument(
        "--execute-read-only",
        action="store_true",
        help="Enable the separately approved one-symbol GET and private raw write.",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> int:
    args = build_parser().parse_args(argv)
    values = os.environ if environ is None else environ
    token_path = Path(args.token_path).expanduser()

    request = SchwabQuoteRequest(
        provider_symbol=args.symbol,
        instrument_key=args.instrument_key,
        asset_class=args.asset_class,
        currency=args.currency,
    )
    connection_uid = _machine_id(args.connection_uid, "connection_uid")
    fetcher.validate_runtime_boundary(token_path, values)

    print("===== Schwab quote capture =====")
    print(
        "MODE              : execute read-only"
        if args.execute_read_only
        else "MODE              : plan only"
    )
    print(
        "PROVIDER_CALLS    : one GET maximum"
        if args.execute_read_only
        else "PROVIDER_CALLS    : disabled"
    )
    print("ORDER_ENDPOINTS   : unavailable")
    print("ACCOUNT_ENDPOINTS : unavailable")
    print("DUCKDB            : unavailable")
    print("SYMBOL_COUNT      : 1")
    print(f"ASOF              : {args.asof.isoformat()}")

    if not args.execute_read_only:
        print("STATUS            : OK")
        print("ACTION            : plan only; no credentials, network, or files accessed")
        return 0

    approval_id = _machine_id(args.approval_id, "approval_id")
    acknowledgement_id = _machine_id(
        args.terms_acknowledgement_id,
        "terms_acknowledgement_id",
    )
    _validate_production_boundary()
    repository_commit = validate_repository_provenance(
        args.expected_repository_commit
    )
    if not values.get("ONEJOURNAL_SCHWAB_CLIENT_ID", "").strip():
        raise RuntimeError("ONEJOURNAL_SCHWAB_CLIENT_ID is required")
    validate_token_file(token_path)

    try:
        with single_operator_lock(token_path):
            client = build_live_client(token_path, values)
            captured = client.fetch_one(request.provider_symbol)
            raw_path = _raw_quote_path(
                RAW_ROOT,
                args.asof,
                captured.received_at,
                request.provider_symbol,
            )
            _secure_exact_write(raw_path, captured.body)

        raw_sha256 = hashlib.sha256(captured.body).hexdigest()
        (quote,) = normalized_quotes_from_payload(
            captured.payload,
            requests=(request,),
            connection_uid=connection_uid,
            asof=args.asof,
            received_at=captured.received_at,
            raw_path=_relative_raw_path(raw_path),
            raw_sha256=raw_sha256,
        )
        freshness = assess_quote_freshness(
            quote,
            evaluated_at=captured.received_at,
        )
        manifest_path = raw_path.with_name(
            raw_path.stem + ".capture-v1.json"
        )
        _secure_exact_write(
            manifest_path,
            _manifest_body(
                request=request,
                connection_uid=connection_uid,
                asof=args.asof,
                received_at=captured.received_at,
                approval_id=approval_id,
                acknowledgement_id=acknowledgement_id,
                repository_commit=repository_commit,
                raw_path=_relative_raw_path(raw_path),
                raw_sha256=raw_sha256,
                quote_uid=quote.quote_uid,
                adapter_version=quote.adapter_version,
                freshness_status=freshness.status,
                valuation_allowed=freshness.valuation_allowed,
            ),
        )
    except Exception as exc:
        print("STATUS            : FAIL")
        print(f"ERROR_TYPE        : {type(exc).__name__}")
        print(f"ERROR             : {str(exc)[:300]}")
        return 1

    print(f"APPROVAL_ID       : {approval_id}")
    print(f"ACKNOWLEDGEMENT_ID: {acknowledgement_id}")
    print(f"REPOSITORY_COMMIT : {repository_commit}")
    print(f"RAW_PATH          : {_relative_raw_path(raw_path)}")
    print(f"RAW_SHA256        : {raw_sha256}")
    print(f"MANIFEST_PATH     : {_relative_raw_path(manifest_path)}")
    print("NORMALIZED_COUNT  : 1")
    print(f"FRESHNESS_STATUS  : {freshness.status}")
    print(f"VALUATION_ALLOWED : {str(freshness.valuation_allowed).lower()}")
    print("DATABASE_WRITES   : 0")
    print("STATUS            : OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
