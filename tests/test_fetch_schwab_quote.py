from __future__ import annotations

import importlib.util
import json
import stat
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import UTC, datetime
from decimal import Decimal
from io import StringIO
from pathlib import Path
from unittest.mock import Mock, patch


PROJECT_DIR = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_DIR / "scripts/journal/fetch_schwab_quote.py"
FIXTURE = PROJECT_DIR / "docs/examples/schwab_quotes_json/quotes_sample.json"
SPEC = importlib.util.spec_from_file_location("onejournal_schwab_quote_fetch", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
quote_fetch = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = quote_fetch
SPEC.loader.exec_module(quote_fetch)


class _FakeClient:
    def __init__(self, body: bytes) -> None:
        self.body = body
        self.calls: list[str] = []

    def fetch_one(self, symbol: str):
        self.calls.append(symbol)
        return quote_fetch.CapturedQuoteResponse(
            payload=json.loads(self.body, parse_float=Decimal),
            body=self.body,
            received_at=datetime(2026, 8, 11, 14, 30, 1, tzinfo=UTC),
        )


class _FakeResponse:
    def __init__(self, body: bytes, status_code: int = 200) -> None:
        self.content = body
        self.status_code = status_code
        self.headers = {"Content-Type": "application/json"}


class _FakeSession:
    def __init__(self, response: _FakeResponse) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def get(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        return self.response


class _FakeAuth:
    def __init__(self) -> None:
        self.refresh_count = 0

    def get_access_token(self) -> str:
        return "test-token"

    def refresh(self) -> None:
        self.refresh_count += 1


class SchwabQuoteFetchTests(unittest.TestCase):
    def base_args(self) -> list[str]:
        return [
            "--symbol",
            "AAPL",
            "--instrument-key",
            "stock|AAPL",
            "--asset-class",
            "stock",
            "--currency",
            "USD",
            "--asof",
            "2026-08-11",
            "--connection-uid",
            "local-schwab-primary",
        ]

    def test_default_mode_is_plan_only_before_client_or_file_access(self) -> None:
        with patch.object(
            quote_fetch,
            "build_live_client",
            side_effect=AssertionError("client must not be built"),
        ):
            with redirect_stdout(StringIO()) as output:
                result = quote_fetch.main(self.base_args(), environ={})

        self.assertEqual(result, 0)
        self.assertIn("plan only; no credentials, network, or files accessed", output.getvalue())

    def test_execute_requires_both_approval_records_before_client_access(self) -> None:
        args = [*self.base_args(), "--execute-read-only"]
        with patch.object(
            quote_fetch,
            "build_live_client",
            side_effect=AssertionError("client must not be built"),
        ):
            with redirect_stdout(StringIO()):
                with self.assertRaisesRegex(ValueError, "approval_id"):
                    quote_fetch.main(args, environ={})

        args.extend(["--approval-id", "PNL-02B-owner-approval"])
        with patch.object(
            quote_fetch,
            "build_live_client",
            side_effect=AssertionError("client must not be built"),
        ):
            with redirect_stdout(StringIO()):
                with self.assertRaisesRegex(ValueError, "terms_acknowledgement_id"):
                    quote_fetch.main(args, environ={})

    def test_transport_uses_only_exact_quote_get_without_redirects(self) -> None:
        body = FIXTURE.read_bytes()
        session = _FakeSession(_FakeResponse(body))
        auth = _FakeAuth()
        client = quote_fetch.SchwabQuoteReadOnlyClient(auth=auth, session=session)

        captured = client.fetch_one("AAPL")

        self.assertEqual(captured.body, body)
        self.assertEqual(len(session.calls), 1)
        call = session.calls[0]
        self.assertEqual(call["url"], quote_fetch.QUOTES_URL)
        self.assertEqual(call["params"], {"symbols": "AAPL", "fields": "quote,reference"})
        self.assertFalse(call["allow_redirects"])
        self.assertEqual(auth.refresh_count, 0)

    def test_http_error_suppresses_response_body(self) -> None:
        body = b'{"secret":"must-not-appear"}'
        client = quote_fetch.SchwabQuoteReadOnlyClient(
            auth=_FakeAuth(),
            session=_FakeSession(_FakeResponse(body, status_code=403)),
        )
        with self.assertRaisesRegex(RuntimeError, "body suppressed") as caught:
            client.fetch_one("AAPL")
        self.assertNotIn("must-not-appear", str(caught.exception))

    def test_approved_execute_writes_exact_private_raw_only(self) -> None:
        body = FIXTURE.read_bytes()
        fake_client = _FakeClient(body)
        with tempfile.TemporaryDirectory() as temporary_dir:
            project_dir = Path(temporary_dir)
            raw_root = project_dir / "data/raw/schwab"
            token_path = project_dir / "private/tokens/schwab.json"
            token_path.parent.mkdir(parents=True)
            token_path.write_text("{}\n", encoding="utf-8")
            token_path.chmod(0o600)
            args = [
                *self.base_args(),
                "--token-path",
                str(token_path),
                "--approval-id",
                "PNL-02B-owner-approval",
                "--terms-acknowledgement-id",
                "schwab-owner-terms-v1",
                "--expected-repository-commit",
                "a" * 40,
                "--execute-read-only",
            ]
            with patch.object(quote_fetch, "PROJECT_DIR", project_dir), patch.object(
                quote_fetch, "RAW_ROOT", raw_root
            ), patch.object(
                quote_fetch, "build_live_client", return_value=fake_client
            ), patch.object(
                quote_fetch, "validate_repository_provenance", return_value="a" * 40
            ):
                with redirect_stdout(StringIO()) as output:
                    result = quote_fetch.main(
                        args,
                        environ={"ONEJOURNAL_SCHWAB_CLIENT_ID": "test-client"},
                    )

            self.assertEqual(result, 0, output.getvalue())
            self.assertEqual(fake_client.calls, ["AAPL"])
            json_files = list(raw_root.rglob("*.json"))
            self.assertEqual(len(json_files), 2)
            manifest_path = next(
                path for path in json_files if path.name.endswith(".capture-v1.json")
            )
            raw_path = next(path for path in json_files if path != manifest_path)
            self.assertEqual(raw_path.read_bytes(), body)
            self.assertEqual(stat.S_IMODE(raw_path.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(manifest_path.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(raw_path.parent.stat().st_mode), 0o700)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["authorization"]["approval_id"], "PNL-02B-owner-approval")
            self.assertEqual(manifest["repository"]["commit"], "a" * 40)
            self.assertTrue(manifest["repository"]["working_tree_clean_before_capture"])
            self.assertEqual(manifest["validation"]["database_writes"], 0)
            self.assertTrue(manifest["capture"]["exact_response_bytes_retained"])
            self.assertEqual(list(project_dir.rglob("*.duckdb")), [])
            self.assertIn("DATABASE_WRITES   : 0", output.getvalue())

    def test_machine_identifiers_reject_output_injection_before_network(self) -> None:
        args = [
            *self.base_args(),
            "--approval-id",
            "approved\nSTATUS:OK",
            "--terms-acknowledgement-id",
            "schwab-owner-terms-v1",
            "--expected-repository-commit",
            "a" * 40,
            "--execute-read-only",
        ]
        with patch.object(
            quote_fetch,
            "build_live_client",
            side_effect=AssertionError("client must not be built"),
        ):
            with redirect_stdout(StringIO()):
                with self.assertRaisesRegex(ValueError, "opaque machine identifier"):
                    quote_fetch.main(args, environ={})

    def test_execute_rejects_public_or_symlinked_token_before_network(self) -> None:
        args = [
            *self.base_args(),
            "--approval-id",
            "PNL-02B-owner-approval",
            "--terms-acknowledgement-id",
            "schwab-owner-terms-v1",
            "--expected-repository-commit",
            "a" * 40,
            "--execute-read-only",
        ]
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            token_path = root / "token.json"
            token_path.write_text("{}\n", encoding="utf-8")
            token_path.chmod(0o644)
            public_args = [*args, "--token-path", str(token_path)]
            with patch.object(
                quote_fetch,
                "validate_repository_provenance",
                return_value="a" * 40,
            ):
                with redirect_stdout(StringIO()):
                    with self.assertRaisesRegex(RuntimeError, "no group/other permissions"):
                        quote_fetch.main(
                            public_args,
                            environ={"ONEJOURNAL_SCHWAB_CLIENT_ID": "test-client"},
                        )

            token_path.chmod(0o600)
            symlink_path = root / "linked-token.json"
            symlink_path.symlink_to(token_path)
            linked_args = [*args, "--token-path", str(symlink_path)]
            with patch.object(
                quote_fetch,
                "validate_repository_provenance",
                return_value="a" * 40,
            ):
                with redirect_stdout(StringIO()):
                    with self.assertRaisesRegex(RuntimeError, "symlinked"):
                        quote_fetch.main(
                            linked_args,
                            environ={"ONEJOURNAL_SCHWAB_CLIENT_ID": "test-client"},
                        )

    def test_nonproduction_api_override_is_rejected_before_client_access(self) -> None:
        args = [
            *self.base_args(),
            "--approval-id",
            "PNL-02B-owner-approval",
            "--terms-acknowledgement-id",
            "schwab-owner-terms-v1",
            "--expected-repository-commit",
            "a" * 40,
            "--execute-read-only",
        ]
        with patch.object(
            quote_fetch.fetcher,
            "SCHWAB_BASE",
            "https://example.invalid",
        ), patch.object(
            quote_fetch,
            "build_live_client",
            side_effect=AssertionError("client must not be built"),
        ):
            with redirect_stdout(StringIO()):
                with self.assertRaisesRegex(RuntimeError, "Refusing non-production"):
                    quote_fetch.main(args, environ={})

    def test_repository_provenance_rejects_mismatch_and_dirty_tree(self) -> None:
        clean = Mock(stdout="b" * 40 + "\n")
        dirty = Mock(stdout=" M unrelated.txt\n")
        with patch.object(quote_fetch.subprocess, "run", side_effect=[clean, dirty]):
            with self.assertRaisesRegex(RuntimeError, "commit mismatch"):
                quote_fetch.validate_repository_provenance("a" * 40)

        matching = Mock(stdout="a" * 40 + "\n")
        dirty = Mock(stdout=" M unrelated.txt\n")
        with patch.object(quote_fetch.subprocess, "run", side_effect=[matching, dirty]):
            with self.assertRaisesRegex(RuntimeError, "working tree must be clean"):
                quote_fetch.validate_repository_provenance("a" * 40)


if __name__ == "__main__":
    unittest.main()
