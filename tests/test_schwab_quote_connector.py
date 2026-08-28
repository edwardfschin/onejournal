from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
import ast
import stat
import tempfile
import unittest

from onejournal.market_data import QuoteInstrumentRequest, load_market_data_policy
from onejournal.provider_connectors import (
    PROVIDER_USAGE_ACKNOWLEDGEMENT_CONTRACT_VERSION,
    InMemoryConnectorOwnerLeaseRegistry,
    InMemoryCredentialStore,
    LocalPrivateRawCaptureStore,
    PrivateRawCaptureError,
    ProviderUsageAcknowledgement,
    SchwabQuoteCaptureRequest,
    SchwabQuoteConnector,
    SchwabQuoteConnectorError,
    SchwabQuoteTransportRequest,
    SchwabQuoteTransportResponse,
    build_provider_usage_acknowledgement_uid,
    load_provider_usage_policy,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = PROJECT_ROOT / "config" / "marketdata.yaml"
FIXTURE = PROJECT_ROOT / "docs/examples/schwab_quotes_json/quotes_sample.json"
CONNECTOR_PATH = PROJECT_ROOT / "src/onejournal/provider_connectors/schwab_quotes.py"


class StaticQuoteTransport:
    def __init__(self, *, response: SchwabQuoteTransportResponse) -> None:
        self.response = response
        self.calls: list[SchwabQuoteTransportRequest] = []

    def fetch_quotes(self, *, request, credential_use):
        self.calls.append(request)
        return self.response


class RotatingQuoteTransport(StaticQuoteTransport):
    def __init__(self, *, response, store: InMemoryCredentialStore) -> None:
        super().__init__(response=response)
        self.store = store

    def fetch_quotes(self, *, request, credential_use):
        response = super().fetch_quotes(request=request, credential_use=credential_use)
        self.store.rotate_for_test(generation_uid="offline-credential-generation-0002")
        return response


class SchwabQuoteConnectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.usage_policy = load_provider_usage_policy(POLICY_PATH)
        self.freshness_policy = load_market_data_policy(POLICY_PATH).freshness
        self.profile = self.usage_policy.active_profiles["schwab"]
        self.started_at = datetime(2026, 8, 28, 14, 29, 59, tzinfo=UTC)
        self.received_at = datetime(2026, 8, 28, 14, 30, 1, tzinfo=UTC)
        self.evaluated_at = datetime(2026, 8, 28, 14, 30, 2, tzinfo=UTC)
        self.store = InMemoryCredentialStore()
        self.leases = InMemoryConnectorOwnerLeaseRegistry()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.private_root = Path(self.temp_dir.name) / "private-evidence"
        self.private_root.mkdir(mode=0o700)
        self.private_root.chmod(0o700)
        self.raw_body = FIXTURE.read_bytes().replace(
            b"1786458600000", b"1787927400000"
        )
        self.response = SchwabQuoteTransportResponse(
            status_code=200,
            content_type="application/json; charset=utf-8",
            body=self.raw_body,
            received_at=self.received_at,
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def acknowledgement(self, **changes: object) -> ProviderUsageAcknowledgement:
        base = ProviderUsageAcknowledgement(
            contract_version=PROVIDER_USAGE_ACKNOWLEDGEMENT_CONTRACT_VERSION,
            acknowledgement_uid="pending",
            provider="schwab",
            connection_uid="local-schwab-primary",
            terms_profile_id=self.profile.profile_id,
            notice_version=self.profile.notice_version,
            operating_scope=self.profile.operating_scope,
            accepted_at_utc=self.profile.reviewed_at_utc + timedelta(minutes=1),
            product_version="onejournal-0.1.0",
            raw_evidence_policy_id=self.profile.raw_evidence_lifecycle.policy_id,
            declarations=self.profile.required_declarations,
        )
        changed = replace(base, **changes)
        if "acknowledgement_uid" in changes:
            return changed
        return replace(
            changed,
            acknowledgement_uid=build_provider_usage_acknowledgement_uid(changed),
        )

    def request(self, **changes: object) -> SchwabQuoteCaptureRequest:
        return replace(
            SchwabQuoteCaptureRequest(
                quote_run_uid="schwab-quote-run-0001",
                connection_uid="local-schwab-primary",
                approval_id="PNL-02-T12-APPROVAL",
                asof=date(2026, 8, 28),
                started_at=self.started_at,
                evaluated_at=self.evaluated_at,
                requests=(
                    QuoteInstrumentRequest(
                        instrument_key="stock|AAPL",
                        provider_instrument_id="AAPL",
                        asset_class="stock",
                        currency="USD",
                    ),
                ),
                acknowledgement=self.acknowledgement(),
            ),
            **changes,
        )

    def connector(self, transport) -> SchwabQuoteConnector:
        return SchwabQuoteConnector(
            usage_policy=self.usage_policy,
            freshness_policy=self.freshness_policy,
            credential_store=self.store,
            owner_leases=self.leases,
            transport=transport,
            private_capture_store=LocalPrivateRawCaptureStore(
                private_root=self.private_root
            ),
        )

    def test_exact_synthetic_response_becomes_private_uningested_complete_capture(self) -> None:
        transport = StaticQuoteTransport(response=self.response)

        result = self.connector(transport).capture(self.request())

        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(transport.calls[0].operation, "quote_capture")
        self.assertEqual(transport.calls[0].provider_symbols, ("AAPL",))
        self.assertEqual(result.capture.provider, "schwab")
        self.assertEqual(result.capture.source.storage_kind, "external_private_vault")
        self.assertEqual(
            result.capture.source.locator,
            "schwab/2026-08-28/quote-captures/"
            "schwab-quote-run-0001/quote-response.json",
        )
        self.assertEqual(result.capture.source.raw_sha256, result.audit.raw_sha256)
        self.assertEqual(result.raw_response_bytes, self.raw_body)
        self.assertEqual(result.audit.final_status, "captured_private_uningested")
        self.assertEqual(result.audit.attempt_count, 1)
        self.assertEqual(result.audit.requested_instrument_count, 1)
        self.assertTrue(result.authorization.provider_reported_entitlement_required)
        self.assertEqual(result.capture.quotes[0].provider_instrument_id, "AAPL")
        self.assertEqual(
            result.capture.quotes[0].raw_path,
            "data/raw/schwab/2026-08-28/quote-captures/"
            "schwab-quote-run-0001/quote-response.json",
        )
        raw_path = self.private_root / result.capture.source.locator
        manifest_path = raw_path.with_name("capture-manifest.json")
        envelope_path = raw_path.with_name("capture-envelope.json")
        self.assertEqual(raw_path.read_bytes(), self.raw_body)
        self.assertEqual(stat.S_IMODE(raw_path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(manifest_path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(envelope_path.stat().st_mode), 0o600)
        with self.assertRaisesRegex(PrivateRawCaptureError, "private capture"):
            self.connector(transport).capture(self.request())

    def test_bad_authorization_fails_before_owner_lease_or_transport(self) -> None:
        transport = StaticQuoteTransport(response=self.response)
        request = self.request(
            acknowledgement=self.acknowledgement(connection_uid="other-connection")
        )

        with self.assertRaisesRegex(SchwabQuoteConnectorError, "authorization"):
            self.connector(transport).capture(request)

        self.assertEqual(transport.calls, [])

    def test_active_owner_lease_and_stale_generation_fail_closed(self) -> None:
        transport = StaticQuoteTransport(response=self.response)
        held = self.leases.acquire(provider="schwab", connection_uid="local-schwab-primary")
        try:
            with self.assertRaisesRegex(SchwabQuoteConnectorError, "owner lease"):
                self.connector(transport).capture(self.request())
        finally:
            self.leases.release(held)
        self.assertEqual(transport.calls, [])

        rotating = RotatingQuoteTransport(response=self.response, store=self.store)
        with self.assertRaisesRegex(SchwabQuoteConnectorError, "generation changed"):
            self.connector(rotating).capture(self.request())
        self.assertEqual(len(rotating.calls), 1)

    def test_transport_and_response_scope_fail_without_capture(self) -> None:
        unsafe_response = replace(self.response, status_code=500)
        transport = StaticQuoteTransport(response=unsafe_response)
        with self.assertRaisesRegex(SchwabQuoteConnectorError, "HTTP 200"):
            self.connector(transport).capture(self.request())

        mismatched = self.request(evaluated_at=self.started_at - timedelta(seconds=1))
        with self.assertRaisesRegex(SchwabQuoteConnectorError, "evaluated_at"):
            self.connector(transport).capture(mismatched)
        self.assertEqual(len(transport.calls), 1)

    def test_connector_module_has_no_network_or_database_implementation(self) -> None:
        module = ast.parse(CONNECTOR_PATH.read_text(encoding="utf-8"))
        imported = {
            alias.name.split(".")[0]
            for node in ast.walk(module)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        self.assertFalse(
            imported
            & {"duckdb", "sqlite3", "requests", "urllib", "socket"}
        )
        method_names = {
            node.attr for node in ast.walk(module) if isinstance(node, ast.Attribute)
        }
        self.assertFalse(method_names & {"connect"})


if __name__ == "__main__":
    unittest.main()
