from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from hashlib import sha256
from io import StringIO

from onejournal.market_data import (
    ProviderMarketSessionAuthority,
    QuoteCaptureContractError,
    build_provider_session_authority_uid,
)


PROJECT_DIR = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_DIR / "scripts/journal/import_schwab_quote_evidence.py"
FIXTURE = PROJECT_DIR / "docs/examples/schwab_quotes_json/quotes_sample.json"
SPEC = importlib.util.spec_from_file_location("onejournal_quote_evidence_import", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
quote_import = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = quote_import
SPEC.loader.exec_module(quote_import)


ONEBOT_COMMIT = "a" * 40
APPROVAL_ID = "PNL-02B-OWNER-APPROVAL-2026-08-27"
TERMS_ID = "SCHWAB-MARKET-DATA-TERMS-V1-2026-08-27"
CONNECTION_UID = "owner-schwab-primary"
CAPTURE_ID = "PNL-02B-AAPL-20260827"


class QuoteEvidenceImportTests(unittest.TestCase):
    def make_bundle(self, root: Path) -> Path:
        root.mkdir(mode=0o700)
        root.chmod(0o700)
        bundle = root / CAPTURE_ID
        bundle.mkdir(mode=0o700)
        body = FIXTURE.read_bytes().replace(b"1786458600000", b"1787841000000")
        raw = bundle / quote_import.RAW_FILENAME
        raw.write_bytes(body)
        raw.chmod(0o600)
        manifest = {
            "schema": quote_import.CAPTURE_SCHEMA,
            "capture_id": CAPTURE_ID,
            "provider": "schwab",
            "authorization": {"approval_id": APPROVAL_ID, "terms_acknowledgement_id": TERMS_ID},
            "token_owner": {"system": "onebot", "connection_uid": CONNECTION_UID},
            "request": {
                "method": "GET",
                "url": quote_import.PRODUCTION_QUOTES_URL,
                "query": {"symbols": "AAPL", "fields": quote_import.REQUEST_FIELDS},
                "market_date": "2026-08-27",
                "redirects_allowed": False,
                "attempt_count": 1,
            },
            "source": {
                "system": "onebot",
                "repository_commit": ONEBOT_COMMIT,
                "working_tree_clean_before_capture": True,
            },
            "capture": {
                "started_at": "2026-08-27T14:30:00+00:00",
                "received_at": "2026-08-27T14:30:01+00:00",
                "http_status": 200,
                "content_type": "application/json",
                "body_bytes": len(body),
                "body_sha256": sha256(body).hexdigest(),
                "raw_file": quote_import.RAW_FILENAME,
                "exact_response_bytes_retained": True,
            },
            "controls": {
                "oauth_refresh_performed": False,
                "provider_get_count": 1,
                "account_endpoint_calls": 0,
                "order_endpoint_calls": 0,
                "database_writes": 0,
            },
        }
        manifest_path = bundle / quote_import.MANIFEST_FILENAME
        manifest_path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")
        manifest_path.chmod(0o600)
        return bundle

    def base_args(self, root: Path, bundle: Path) -> list[str]:
        return [
            "--private-vault-root", str(root),
            "--bundle", str(bundle),
            "--symbol", "AAPL",
            "--instrument-key", "stock|AAPL",
            "--asset-class", "stock",
            "--currency", "USD",
            "--connection-uid", CONNECTION_UID,
            "--asof", "2026-08-27",
            "--evaluated-at", "2026-08-27T14:30:01Z",
            "--approval-id", APPROVAL_ID,
            "--terms-acknowledgement-id", TERMS_ID,
            "--expected-onebot-commit", ONEBOT_COMMIT,
        ]

    def mutate_manifest(self, bundle: Path, callback) -> None:
        path = bundle / quote_import.MANIFEST_FILENAME
        manifest = json.loads(path.read_text(encoding="utf-8"))
        callback(manifest)
        path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")
        path.chmod(0o600)

    def remove_quote_session(self, bundle: Path) -> None:
        raw_path = bundle / quote_import.RAW_FILENAME
        payload = json.loads(raw_path.read_text(encoding="utf-8"))
        payload["AAPL"]["quote"].pop("marketSession")
        body = (json.dumps(payload, sort_keys=True) + "\n").encode("utf-8")
        raw_path.write_bytes(body)
        raw_path.chmod(0o600)

        def update_capture(manifest) -> None:
            manifest["capture"]["body_bytes"] = len(body)
            manifest["capture"]["body_sha256"] = sha256(body).hexdigest()

        self.mutate_manifest(bundle, update_capture)

    def provider_session_resolver(self):
        class Resolver:
            def resolve(self, *, quote, evaluated_at):
                authority = ProviderMarketSessionAuthority(
                    authority_uid="pending",
                    provider=quote.provider,
                    connection_uid=quote.connection_uid,
                    quote_uid=quote.quote_uid,
                    instrument_key=quote.instrument_key,
                    provider_instrument_id=quote.provider_instrument_id,
                    schedule_scope_id="schwab-equity-us",
                    mic=None,
                    venue_timezone="America/New_York",
                    provider_quote_at=quote.provider_quote_at,
                    evaluated_at=evaluated_at,
                    quote_market_date=date(2026, 8, 27),
                    evaluation_market_date=date(2026, 8, 27),
                    quote_market_session="regular",
                    evaluation_market_session="regular",
                    quote_trading_day_kind="regular",
                    evaluation_trading_day_kind="regular",
                    quote_phase_started_at=datetime(
                        2026, 8, 27, 13, 30, tzinfo=UTC
                    ),
                    quote_phase_ends_at=datetime(2026, 8, 27, 20, 0, tzinfo=UTC),
                    evaluation_phase_started_at=datetime(
                        2026, 8, 27, 13, 30, tzinfo=UTC
                    ),
                    evaluation_phase_ends_at=datetime(
                        2026, 8, 27, 20, 0, tzinfo=UTC
                    ),
                    retrieved_at=evaluated_at - timedelta(seconds=1),
                    resolved_at=evaluated_at,
                    valid_until=evaluated_at + timedelta(minutes=1),
                    source_response_type="market_hours",
                    provider_source_version=None,
                    raw_path=(
                        "data/raw/schwab/external/PNL-02B-AAPL-20260827/"
                        "market-hours-response.json"
                    ),
                    raw_sha256="b" * 64,
                    adapter_version="schwab-market-hours-v1",
                )
                return replace(
                    authority,
                    authority_uid=build_provider_session_authority_uid(authority),
                )

        return Resolver()

    def test_valid_bundle_normalizes_and_assesses_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir) / "vault"
            bundle = self.make_bundle(root)
            before = sorted(path.relative_to(root) for path in root.rglob("*"))
            with redirect_stdout(StringIO()) as output:
                result = quote_import.main(self.base_args(root, bundle))
            after = sorted(path.relative_to(root) for path in root.rglob("*"))
            self.assertEqual(result, 0)
            self.assertEqual(before, after)
            summary = json.loads(output.getvalue())
            self.assertEqual(summary["capture_id"], CAPTURE_ID)
            self.assertEqual(summary["adapter_version"], "schwab-quote-json-v2")
            self.assertEqual(
                summary["capture_contract_version"],
                "onejournal.market-data.quote-capture.v1",
            )
            self.assertEqual(summary["marketdata_policy_version"], 1)
            self.assertEqual(summary["freshness_status"], "live_fresh")
            self.assertTrue(summary["valuation_allowed"])
            self.assertEqual(summary["database_writes"], 0)

    def test_injected_provider_resolver_qualifies_missing_quote_session(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir) / "vault"
            bundle = self.make_bundle(root)
            self.remove_quote_session(bundle)
            before = sorted(path.relative_to(root) for path in root.rglob("*"))

            with redirect_stdout(StringIO()) as output:
                result = quote_import.main(
                    self.base_args(root, bundle),
                    session_resolver=self.provider_session_resolver(),
                )

            after = sorted(path.relative_to(root) for path in root.rglob("*"))
            summary = json.loads(output.getvalue())
            self.assertEqual(result, 0)
            self.assertEqual(before, after)
            self.assertEqual(
                summary["schema"],
                "onejournal.schwab.quote-evidence-import-summary.v2",
            )
            self.assertEqual(summary["freshness_status"], "live_fresh")
            self.assertTrue(summary["valuation_allowed"])
            self.assertEqual(summary["quote_session_source"], "authority")
            self.assertEqual(summary["evaluation_session_source"], "authority")
            self.assertEqual(
                summary["session_authority_contract_version"],
                "onejournal.provider-market-session-authority.v2",
            )
            self.assertTrue(
                summary["session_authority_uid"].startswith(
                    "provider-session-authority:"
                )
            )

    def test_hash_and_byte_tampering_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir) / "vault"
            bundle = self.make_bundle(root)
            raw = bundle / quote_import.RAW_FILENAME
            raw.write_bytes(raw.read_bytes() + b" ")
            raw.chmod(0o600)
            with self.assertRaisesRegex(quote_import.QuoteEvidenceImportError, "bytes do not match"):
                quote_import.main(self.base_args(root, bundle))

    def test_approval_terms_commit_and_connection_are_bound(self) -> None:
        mutations = [
            lambda item: item["authorization"].update(approval_id="wrong"),
            lambda item: item["authorization"].update(terms_acknowledgement_id="wrong"),
            lambda item: item["source"].update(repository_commit="b" * 40),
            lambda item: item["token_owner"].update(connection_uid="other"),
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary_dir:
                root = Path(temporary_dir) / "vault"
                bundle = self.make_bundle(root)
                self.mutate_manifest(bundle, mutation)
                with self.assertRaises(quote_import.QuoteEvidenceImportError):
                    quote_import.main(self.base_args(root, bundle))

    def test_request_refresh_counts_and_symbol_scope_fail_closed(self) -> None:
        mutations = [
            lambda item: item["request"].update(url="https://example.invalid"),
            lambda item: item["request"]["query"].update(fields="quote"),
            lambda item: item["request"].update(attempt_count=2),
            lambda item: item["controls"].update(oauth_refresh_performed=True),
            lambda item: item["controls"].update(provider_get_count=2),
            lambda item: item["controls"].update(provider_get_count=True),
            lambda item: item["controls"].update(order_endpoint_calls=1),
            lambda item: item["controls"].update(order_endpoint_calls=False),
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary_dir:
                root = Path(temporary_dir) / "vault"
                bundle = self.make_bundle(root)
                self.mutate_manifest(bundle, mutation)
                with self.assertRaises(quote_import.QuoteEvidenceImportError):
                    quote_import.main(self.base_args(root, bundle))

    def test_bundle_path_modes_symlinks_and_extra_files_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir) / "vault"
            bundle = self.make_bundle(root)
            (bundle / "extra.txt").write_text("unexpected", encoding="utf-8")
            with self.assertRaisesRegex(quote_import.QuoteEvidenceImportError, "exactly"):
                quote_import.main(self.base_args(root, bundle))
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir) / "vault"
            bundle = self.make_bundle(root)
            (bundle / quote_import.RAW_FILENAME).chmod(0o644)
            with self.assertRaisesRegex(quote_import.QuoteEvidenceImportError, "0600"):
                quote_import.main(self.base_args(root, bundle))
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir) / "vault"
            bundle = self.make_bundle(root)
            linked = root / "linked"
            linked.symlink_to(bundle, target_is_directory=True)
            with self.assertRaisesRegex(quote_import.QuoteEvidenceImportError, "non-symlink"):
                quote_import.main(self.base_args(root, linked))

    def test_received_time_and_explicit_evaluation_drive_freshness(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir) / "vault"
            bundle = self.make_bundle(root)
            args = self.base_args(root, bundle)
            args[args.index("2026-08-27T14:30:01Z")] = "2026-08-27T15:30:01Z"
            with redirect_stdout(StringIO()) as output:
                quote_import.main(args)
            summary = json.loads(output.getvalue())
            self.assertEqual(summary["freshness_status"], "live_stale")
            self.assertFalse(summary["valuation_allowed"])

    def test_provider_quote_time_must_match_explicit_market_date(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir) / "vault"
            bundle = self.make_bundle(root)
            self.mutate_manifest(
                bundle,
                lambda item: item["request"].update(market_date="2026-08-26"),
            )
            args = self.base_args(root, bundle)
            args[args.index("2026-08-27")] = "2026-08-26"
            with self.assertRaisesRegex(
                QuoteCaptureContractError,
                "market date",
            ):
                quote_import.main(args)

    def test_importer_has_no_credential_network_or_database_capability(self) -> None:
        source = SCRIPT_PATH.read_text(encoding="utf-8")
        for value in (
            "import requests", "TokenStore", "AuthClient", "access_token",
            "refresh_token", "duckdb", "subprocess",
        ):
            with self.subTest(value=value):
                self.assertNotIn(value, source)
        self.assertNotIn("write_bytes(", source)
        self.assertNotIn("write_text(", source)


if __name__ == "__main__":
    unittest.main()
