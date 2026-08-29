from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
import json
from pathlib import Path
import sys
import types
import unittest

try:
    import yaml  # noqa: F401
except ModuleNotFoundError:
    # The pure contract test does not parse YAML.  This keeps the focused test
    # runnable in a dependency-minimal interpreter without altering runtime code.
    sys.modules["yaml"] = types.SimpleNamespace()
try:
    import duckdb  # noqa: F401
except ModuleNotFoundError:
    # Imported by the market-data package register; this test never opens a DB.
    sys.modules["duckdb"] = types.SimpleNamespace()

from onejournal.brokers.schwab.market_hours_resolver import (
    SCHWAB_EQUITY_SCOPE,
    SchwabMarketHoursResolver,
)
from onejournal.market_data import (
    QuoteFreshnessPolicy,
    QuoteInstrumentRequest,
    assess_quote_freshness,
    resolve_provider_session_authority,
)
from onejournal.provider_connectors.external_acquisition import (
    EXTERNAL_PROVIDER_ACQUISITION_SCHEMA,
    SCHWAB_EXTERNAL_ACQUISITION_PROFILE,
    SCHWAB_MARKET_HOURS_URL,
    SCHWAB_QUOTES_URL,
    ExternalAcquisitionControls,
    ExternalAcquisitionProviderUse,
    ExternalAcquisitionQueryParameter,
    ExternalAcquisitionRequest,
    ExternalAcquisitionSourceArtifact,
    ExternalAcquisitionSourceOwner,
    ExternalProviderAcquisitionError,
    ExternalProviderAcquisitionManifest,
    ExternalSchwabQuoteMapping,
    build_external_schwab_schedule_evidence,
    convert_external_schwab_quotes,
    external_provider_acquisition_manifest_bytes,
    load_external_provider_acquisition,
)
from onejournal.provider_connectors.usage_policy import (
    PROVIDER_USAGE_ACKNOWLEDGEMENT_CONTRACT_VERSION,
    PROVIDER_USAGE_POLICY_CONTRACT_VERSION,
    ProviderUsageAcknowledgement,
    ProviderUsagePolicy,
    ProviderTermsProfile,
    RawEvidenceLifecyclePolicy,
    TermsReference,
    build_provider_usage_acknowledgement_uid,
    provider_usage_acknowledgement_artifact_bytes,
)
from types import MappingProxyType


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONNECTION_UID = "connection:schwab:external-owner"
RUN_UID = "PNL-02-T16-EXTERNAL-ACQUISITION-0001"
APPROVAL_ID = "PNL-02-T16-EXTERNAL-APPROVAL-0001"
OWNER_UID = "onebot-owner-primary"
OWNER_EPOCH_UID = "onebot-owner-epoch-0001"
QUOTE_REQUEST_UID = "schwab-quote-request-0001"
SCHEDULE_REQUEST_UID = "schwab-market-hours-request-0001"
MARKET_DATE = date(2026, 8, 31)


def quote_body() -> bytes:
    quote_time = int(
        datetime(2026, 8, 31, 14, 0, tzinfo=UTC).timestamp() * 1000
    )
    return (
        json.dumps(
            {
                "AAPL": {
                    "assetMainType": "EQUITY",
                    "quote": {
                        "askPrice": 200.10,
                        "bidPrice": 199.90,
                        "lastPrice": 200.00,
                        "marketSession": "REGULAR",
                        "quoteTime": quote_time,
                        "securityStatus": "Normal",
                    },
                    "realtime": True,
                    "symbol": "AAPL",
                }
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def schedule_body() -> bytes:
    payload = {
        "equity": {
            "EQ": {
                "date": MARKET_DATE.isoformat(),
                "marketType": "EQUITY",
                "product": "EQ",
                "productName": "equity",
                "isOpen": True,
                "sessionHours": {
                    "preMarket": [
                        {
                            "start": "2026-08-31T07:00:00-04:00",
                            "end": "2026-08-31T09:30:00-04:00",
                        }
                    ],
                    "regularMarket": [
                        {
                            "start": "2026-08-31T09:30:00-04:00",
                            "end": "2026-08-31T16:00:00-04:00",
                        }
                    ],
                    "postMarket": [
                        {
                            "start": "2026-08-31T16:00:00-04:00",
                            "end": "2026-08-31T20:00:00-04:00",
                        }
                    ],
                },
            }
        },
        "option": {
            "EQO": {
                "date": MARKET_DATE.isoformat(),
                "marketType": "OPTION",
                "product": "EQO",
                "productName": "equity option",
                "isOpen": True,
                "sessionHours": {
                    "regularMarket": [
                        {
                            "start": "2026-08-31T09:30:00-04:00",
                            "end": "2026-08-31T16:00:00-04:00",
                        }
                    ]
                },
            },
            "IND": {
                "date": MARKET_DATE.isoformat(),
                "marketType": "OPTION",
                "product": "IND",
                "productName": "index option",
                "isOpen": True,
                "sessionHours": {
                    "regularMarket": [
                        {
                            "start": "2026-08-31T09:30:00-04:00",
                            "end": "2026-08-31T16:15:00-04:00",
                        }
                    ]
                },
            },
        },
    }
    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


class ExternalProviderAcquisitionTests(unittest.TestCase):
    def setUp(self) -> None:
        lifecycle = RawEvidenceLifecyclePolicy(
            policy_id="onejournal-local-raw-market-data-lifecycle.v1",
            mode="retain_until_explicit_approved_deletion_or_provider_requirement",
            automatic_deletion_enabled=False,
            fixed_retention_period_days=None,
            deletion_requires_explicit_approval=True,
            deletion_audit_required=True,
            provider_rule_change_requires_new_profile=True,
        )
        required_declarations = frozenset(
            {
                "authorized_connection",
                "applicable_terms_accepted",
                "authenticated_provider_terms_reviewed",
                "required_entitlements_maintained",
                "personal_noncommercial_use_only",
                "no_redistribution_or_public_exposure",
                "onejournal_does_not_grant_market_data_rights",
                "raw_evidence_lifecycle_accepted",
            }
        )
        profile = ProviderTermsProfile(
            provider="schwab",
            profile_id="schwab-local-owner-market-data-2026-08-28.v1",
            notice_version="onejournal-schwab-local-owner-notice.v1",
            operating_scope="owner_operated_local_connection",
            permitted_use="personal_noncommercial",
            reviewed_at_utc=datetime(2026, 8, 28, tzinfo=UTC),
            official_terms=(
                TermsReference(
                    reference_id="schwab-online-services-agreement",
                    title="Schwab Online Services Agreement",
                    url="https://www.schwab.com/legal/terms",
                ),
            ),
            requires_authenticated_provider_terms_confirmation=True,
            provider_reported_entitlement_required=True,
            redistribution_allowed=False,
            public_display_allowed=False,
            hosted_storage_allowed=False,
            required_declarations=required_declarations,
            raw_evidence_lifecycle=lifecycle,
        )
        self.usage_policy = ProviderUsagePolicy(
            contract_version=PROVIDER_USAGE_POLICY_CONTRACT_VERSION,
            active_profiles=MappingProxyType({"schwab": profile}),
        )
        self.freshness_policy = QuoteFreshnessPolicy()
        profile = self.usage_policy.active_profiles["schwab"]
        acknowledgement = ProviderUsageAcknowledgement(
            contract_version=PROVIDER_USAGE_ACKNOWLEDGEMENT_CONTRACT_VERSION,
            acknowledgement_uid="pending",
            provider="schwab",
            connection_uid=CONNECTION_UID,
            terms_profile_id=profile.profile_id,
            notice_version=profile.notice_version,
            operating_scope=profile.operating_scope,
            accepted_at_utc=profile.reviewed_at_utc + timedelta(minutes=1),
            product_version="onejournal-0.1.0",
            raw_evidence_policy_id=profile.raw_evidence_lifecycle.policy_id,
            declarations=profile.required_declarations,
        )
        acknowledgement = replace(
            acknowledgement,
            acknowledgement_uid=build_provider_usage_acknowledgement_uid(acknowledgement),
        )
        self.acknowledgement_bytes = provider_usage_acknowledgement_artifact_bytes(
            acknowledgement,
            creation_approval_id="PNL-02-T16-ACK-CREATION-0001",
        )
        self.acknowledgement_uid = acknowledgement.acknowledgement_uid
        self.quote = quote_body()
        self.schedule = schedule_body()
        self.started_at = datetime(2026, 8, 31, 14, 0, tzinfo=UTC)
        self.completed_at = self.started_at + timedelta(seconds=3)
        self.evaluated_at = self.completed_at + timedelta(seconds=1)
        self.manifest = self.make_manifest()

    def request(
        self,
        *,
        request_uid: str,
        operation: str,
        body: bytes,
        received_offset: int,
    ) -> ExternalAcquisitionRequest:
        if operation == "quote":
            url = SCHWAB_QUOTES_URL
            query = (
                ExternalAcquisitionQueryParameter("symbols", "AAPL"),
                ExternalAcquisitionQueryParameter("fields", "quote,reference"),
            )
            filename = "quote-aapl.json"
        else:
            url = SCHWAB_MARKET_HOURS_URL
            query = (
                ExternalAcquisitionQueryParameter("markets", "equity"),
                ExternalAcquisitionQueryParameter("markets", "option"),
                ExternalAcquisitionQueryParameter("date", MARKET_DATE.isoformat()),
            )
            filename = "market-hours-2026-08-31.json"
        requested_at = self.started_at + timedelta(seconds=received_offset - 1)
        return ExternalAcquisitionRequest(
            request_uid=request_uid,
            operation=operation,
            method="GET",
            url=url,
            query=query,
            approved_market_date=MARKET_DATE,
            requested_at_utc=requested_at,
            received_at_utc=requested_at + timedelta(seconds=1),
            status_code=200,
            content_type="application/json; charset=utf-8",
            response_filename=filename,
            response_byte_count=len(body),
            response_sha256=sha256(body).hexdigest(),
            attempt_count=1,
            redirects_followed=0,
        )

    def make_manifest(self) -> ExternalProviderAcquisitionManifest:
        profile = self.usage_policy.active_profiles["schwab"]
        requests = (
            self.request(
                request_uid=QUOTE_REQUEST_UID,
                operation="quote",
                body=self.quote,
                received_offset=1,
            ),
            self.request(
                request_uid=SCHEDULE_REQUEST_UID,
                operation="market_hours",
                body=self.schedule,
                received_offset=2,
            ),
        )
        return ExternalProviderAcquisitionManifest(
            schema=EXTERNAL_PROVIDER_ACQUISITION_SCHEMA,
            profile=SCHWAB_EXTERNAL_ACQUISITION_PROFILE,
            provider="schwab",
            connection_uid=CONNECTION_UID,
            source_owner=ExternalAcquisitionSourceOwner(
                source_system="onebot",
                owner_uid=OWNER_UID,
                owner_epoch_uid=OWNER_EPOCH_UID,
                operating_identity_uid="onebot-vps-operating-user",
            ),
            source_artifacts=(
                ExternalAcquisitionSourceArtifact(
                    "producer", "onebot-external-producer-v1", "a" * 64
                ),
                ExternalAcquisitionSourceArtifact(
                    "provider_client_boundary",
                    "onebot-schwab-client-v1",
                    "b" * 64,
                ),
            ),
            acquisition_run_uid=RUN_UID,
            acquisition_approval_id=APPROVAL_ID,
            acknowledgement_uid=self.acknowledgement_uid,
            acknowledgement_sha256=sha256(self.acknowledgement_bytes).hexdigest(),
            provider_use=ExternalAcquisitionProviderUse(
                terms_profile_id=profile.profile_id,
                notice_version=profile.notice_version,
                operating_scope=profile.operating_scope,
                raw_evidence_policy_id=profile.raw_evidence_lifecycle.policy_id,
            ),
            operation_allowlist=("quote", "market_hours"),
            requests=requests,
            controls=ExternalAcquisitionControls(
                provider_get_count=2,
                oauth_refresh_count=0,
                refresh_approval_id=None,
                account_endpoint_calls=0,
                position_endpoint_calls=0,
                transaction_endpoint_calls=0,
                order_endpoint_calls=0,
                database_writes=0,
                request_body_count=0,
                response_count=2,
            ),
            completed_at_utc=self.completed_at,
            final_status="complete",
            manifest_written_last=True,
        )

    def load(self, *, manifest=None, responses=None):
        manifest = manifest or self.manifest
        return load_external_provider_acquisition(
            external_provider_acquisition_manifest_bytes(manifest),
            response_bytes=responses or {
                "quote-aapl.json": self.quote,
                "market-hours-2026-08-31.json": self.schedule,
            },
            acknowledgement_bytes=self.acknowledgement_bytes,
            usage_policy=self.usage_policy,
            evaluated_at_utc=self.evaluated_at,
            expected_acquisition_run_uid=RUN_UID,
            expected_acquisition_approval_id=APPROVAL_ID,
            expected_owner_uid=OWNER_UID,
            expected_owner_epoch_uid=OWNER_EPOCH_UID,
        )

    def test_exact_bundle_converts_deterministically_without_side_effects(self) -> None:
        acquisition = self.load()
        mapping = ExternalSchwabQuoteMapping(
            request_uid=QUOTE_REQUEST_UID,
            instrument=QuoteInstrumentRequest(
                instrument_key="stock|AAPL",
                provider_instrument_id="AAPL",
                asset_class="stock",
                currency="USD",
            ),
        )
        first = convert_external_schwab_quotes(
            acquisition,
            mappings=(mapping,),
            evaluated_at_utc=self.evaluated_at,
            freshness_policy=self.freshness_policy,
        )
        replay = convert_external_schwab_quotes(
            acquisition,
            mappings=(mapping,),
            evaluated_at_utc=self.evaluated_at,
            freshness_policy=self.freshness_policy,
        )

        self.assertEqual(first, replay)
        self.assertEqual(len(first), 1)
        converted = first[0]
        self.assertEqual(converted.raw_response_bytes, self.quote)
        self.assertEqual(converted.capture.quotes[0].symbol, "AAPL")
        self.assertEqual(converted.capture.quotes[0].entitlement_status, "entitled")
        self.assertEqual(converted.private_manifest.final_status, "captured_private_uningested")
        self.assertTrue(converted.capture.quote_run_uid.startswith("external-acquisition:"))
        self.assertEqual(converted.external_manifest_sha256, acquisition.manifest_sha256)

    def test_schedule_conversion_preserves_exact_manifest_lineage(self) -> None:
        acquisition = self.load()
        mapping = ExternalSchwabQuoteMapping(
            request_uid=QUOTE_REQUEST_UID,
            instrument=QuoteInstrumentRequest(
                instrument_key="stock|AAPL",
                provider_instrument_id="AAPL",
                asset_class="stock",
                currency="USD",
            ),
        )
        converted = convert_external_schwab_quotes(
            acquisition,
            mappings=(mapping,),
            evaluated_at_utc=self.evaluated_at,
            freshness_policy=self.freshness_policy,
        )[0]
        evidence = build_external_schwab_schedule_evidence(
            acquisition,
            normal_reference_date=MARKET_DATE,
            valid_until_utc=self.evaluated_at + timedelta(days=1),
        )
        resolver = SchwabMarketHoursResolver(
            connection_uid=CONNECTION_UID,
            scope=SCHWAB_EQUITY_SCOPE,
            evidence=evidence,
        )
        authority = resolve_provider_session_authority(
            resolver,
            quote=converted.capture.quotes[0],
            evaluated_at=self.evaluated_at,
        )
        assessment = assess_quote_freshness(
            converted.capture.quotes[0],
            evaluated_at=self.evaluated_at,
            session_authority=authority,
            policy=self.freshness_policy,
        )

        self.assertEqual(evidence.manifest_raw_sha256, acquisition.manifest_sha256)
        self.assertEqual(evidence.schedules[0].response.market_date, MARKET_DATE)
        self.assertEqual(evidence.schedules[0].raw_sha256, sha256(self.schedule).hexdigest())
        self.assertEqual(authority.raw_sha256, acquisition.manifest_sha256)
        self.assertEqual(assessment.status, "live_fresh")
        self.assertTrue(assessment.valuation_allowed)

    def test_noncanonical_manifest_and_tampered_response_fail_closed(self) -> None:
        canonical = external_provider_acquisition_manifest_bytes(self.manifest)
        noncanonical = json.dumps(json.loads(canonical)).encode("utf-8")
        with self.assertRaisesRegex(ExternalProviderAcquisitionError, "not canonical"):
            load_external_provider_acquisition(
                noncanonical,
                response_bytes={
                    "quote-aapl.json": self.quote,
                    "market-hours-2026-08-31.json": self.schedule,
                },
                acknowledgement_bytes=self.acknowledgement_bytes,
                usage_policy=self.usage_policy,
                evaluated_at_utc=self.evaluated_at,
                expected_acquisition_run_uid=RUN_UID,
                expected_acquisition_approval_id=APPROVAL_ID,
                expected_owner_uid=OWNER_UID,
                expected_owner_epoch_uid=OWNER_EPOCH_UID,
            )
        with self.assertRaisesRegex(ExternalProviderAcquisitionError, "checksum"):
            self.load(
                responses={
                    "quote-aapl.json": self.quote + b" ",
                    "market-hours-2026-08-31.json": self.schedule,
                }
            )

    def test_owner_acknowledgement_scope_and_completeness_fail_closed(self) -> None:
        mutations = (
            replace(
                self.manifest,
                source_owner=replace(
                    self.manifest.source_owner,
                    owner_epoch_uid="other-owner-epoch",
                ),
            ),
            replace(self.manifest, acknowledgement_sha256="f" * 64),
            replace(self.manifest, final_status="incomplete"),
            replace(self.manifest, manifest_written_last=False),
        )
        for manifest in mutations:
            with self.subTest(manifest=manifest), self.assertRaises(
                ExternalProviderAcquisitionError
            ):
                self.load(manifest=manifest)

    def test_forbidden_endpoints_counts_refresh_and_query_shapes_fail_closed(self) -> None:
        quote_request, schedule_request = self.manifest.requests
        mutations = (
            replace(quote_request, url="https://example.invalid"),
            replace(quote_request, method="POST"),
            replace(quote_request, query=(ExternalAcquisitionQueryParameter("symbols", "AAPL"),)),
            replace(
                schedule_request,
                query=(
                    ExternalAcquisitionQueryParameter("markets", "equity,option"),
                    ExternalAcquisitionQueryParameter(
                        "date", MARKET_DATE.isoformat()
                    ),
                ),
            ),
        )
        for request in mutations:
            requests = (
                (request, schedule_request)
                if request.operation == "quote"
                else (quote_request, request)
            )
            with self.subTest(request=request), self.assertRaises(ExternalProviderAcquisitionError):
                external_provider_acquisition_manifest_bytes(
                    replace(self.manifest, requests=requests)
                )

        forbidden_controls = replace(self.manifest.controls, order_endpoint_calls=1)
        with self.assertRaises(ExternalProviderAcquisitionError):
            external_provider_acquisition_manifest_bytes(
                replace(self.manifest, controls=forbidden_controls)
            )
        silent_refresh = replace(self.manifest.controls, oauth_refresh_count=1)
        with self.assertRaises(ExternalProviderAcquisitionError):
            external_provider_acquisition_manifest_bytes(
                replace(self.manifest, controls=silent_refresh)
            )

    def test_mapping_mismatch_and_missing_schedule_validity_fail_closed(self) -> None:
        acquisition = self.load()
        wrong_mapping = ExternalSchwabQuoteMapping(
            request_uid=QUOTE_REQUEST_UID,
            instrument=QuoteInstrumentRequest("stock|MSFT", "MSFT", "stock", "USD"),
        )
        with self.assertRaisesRegex(ExternalProviderAcquisitionError, "mapping differs"):
            convert_external_schwab_quotes(
                acquisition,
                mappings=(wrong_mapping,),
                evaluated_at_utc=self.evaluated_at,
                freshness_policy=self.freshness_policy,
            )
        with self.assertRaisesRegex(ExternalProviderAcquisitionError, "validity"):
            build_external_schwab_schedule_evidence(
                acquisition,
                normal_reference_date=MARKET_DATE,
                valid_until_utc=self.started_at,
            )

    def test_module_has_no_provider_credential_database_or_write_capability(self) -> None:
        source = (
            PROJECT_ROOT / "src/onejournal/provider_connectors/external_acquisition.py"
        ).read_text(encoding="utf-8")
        for forbidden in (
            "import requests", "import duckdb", "TokenStore", "access_token",
            "refresh_token", "Authorization", "write_bytes(", "write_text(",
            "subprocess", "socket", "urllib",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
