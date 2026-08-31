from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import stat
import tempfile
from types import MappingProxyType
import unittest

from onejournal.brokers.schwab.position_binding import (
    SCHWAB_POSITION_PRIVATE_BINDING_SCHEMA,
    SchwabPositionPrivateBinding,
    SchwabPositionPrivateBindingError,
    load_schwab_position_private_binding_bytes,
    schwab_position_private_binding_bytes,
)
from onejournal.brokers.schwab.positions_json import SchwabPositionMapping
from onejournal.instruments import InstrumentIdentity
from onejournal.provider_connectors.external_acquisition import (
    EXTERNAL_PROVIDER_ACQUISITION_SCHEMA,
    SCHWAB_POSITION_ACCOUNT_URL_TEMPLATE,
    SCHWAB_POSITION_EXTERNAL_ACQUISITION_PROFILE,
    ExternalAcquisitionControls,
    ExternalAcquisitionProviderUse,
    ExternalAcquisitionQueryParameter,
    ExternalAcquisitionRequest,
    ExternalAcquisitionSourceArtifact,
    ExternalAcquisitionSourceOwner,
    ExternalProviderAcquisitionError,
    ExternalProviderAcquisitionManifest,
    convert_external_schwab_positions,
    external_provider_acquisition_manifest_bytes,
    load_external_provider_acquisition,
)
from onejournal.provider_connectors.usage_policy import (
    PROVIDER_USAGE_ACKNOWLEDGEMENT_CONTRACT_VERSION,
    PROVIDER_USAGE_POLICY_CONTRACT_VERSION,
    ProviderTermsProfile,
    ProviderUsageAcknowledgement,
    ProviderUsagePolicy,
    RawEvidenceLifecyclePolicy,
    TermsReference,
    build_provider_usage_acknowledgement_uid,
    provider_usage_acknowledgement_artifact_bytes,
)
from scripts.journal.validate_external_schwab_position_acquisition import (
    ExternalSchwabPositionIntakeError,
    main as position_intake_main,
)


CONNECTION_UID = "connection:schwab:external-owner"
SOURCE_ACCOUNT_ID = "account:owner:primary"
RUN_UID = "PNL-03G-EXTERNAL-POSITION-0001"
APPROVAL_ID = "PNL-03G-EXTERNAL-APPROVAL-0001"
OWNER_UID = "onebot-owner-primary"
OWNER_EPOCH_UID = "onebot-owner-epoch-0001"
REQUEST_UID = "schwab-position-request-0001"
MARKET_DATE = date(2026, 8, 31)
PROVIDER_ACCOUNT_HASH = "synthetic-high-entropy-account-hash"
PROVIDER_ACCOUNT_NUMBER = "SYNTHETIC-ACCOUNT"


def position_body() -> bytes:
    document = {
        "securitiesAccount": {
            "accountNumber": PROVIDER_ACCOUNT_NUMBER,
            "positions": [
                {
                    "longQuantity": 10,
                    "shortQuantity": 0,
                    "averagePrice": 190.25,
                    "marketValue": 2000,
                    "longOpenProfitLoss": 97.5,
                    "shortOpenProfitLoss": 0,
                    "instrument": {
                        "assetType": "EQUITY",
                        "symbol": "AAPL",
                    },
                }
            ],
        }
    }
    return (
        json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


class ExternalSchwabPositionAcquisitionTests(unittest.TestCase):
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
        declarations = frozenset(
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
        terms_profile = ProviderTermsProfile(
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
            required_declarations=declarations,
            raw_evidence_lifecycle=lifecycle,
        )
        self.usage_policy = ProviderUsagePolicy(
            contract_version=PROVIDER_USAGE_POLICY_CONTRACT_VERSION,
            active_profiles=MappingProxyType({"schwab": terms_profile}),
        )
        acknowledgement = ProviderUsageAcknowledgement(
            contract_version=PROVIDER_USAGE_ACKNOWLEDGEMENT_CONTRACT_VERSION,
            acknowledgement_uid="pending",
            provider="schwab",
            connection_uid=CONNECTION_UID,
            terms_profile_id=terms_profile.profile_id,
            notice_version=terms_profile.notice_version,
            operating_scope=terms_profile.operating_scope,
            accepted_at_utc=terms_profile.reviewed_at_utc + timedelta(minutes=1),
            product_version="onejournal-0.1.0",
            raw_evidence_policy_id=lifecycle.policy_id,
            declarations=declarations,
        )
        acknowledgement = replace(
            acknowledgement,
            acknowledgement_uid=build_provider_usage_acknowledgement_uid(
                acknowledgement
            ),
        )
        self.acknowledgement_bytes = provider_usage_acknowledgement_artifact_bytes(
            acknowledgement,
            creation_approval_id="PNL-03G-ACK-CREATION-0001",
        )
        self.acknowledgement_uid = acknowledgement.acknowledgement_uid
        self.body = position_body()
        self.started_at = datetime(2026, 8, 31, 14, 0, tzinfo=UTC)
        self.received_at = self.started_at + timedelta(seconds=1)
        self.completed_at = self.received_at + timedelta(seconds=1)
        self.request = ExternalAcquisitionRequest(
            request_uid=REQUEST_UID,
            operation="position",
            method="GET",
            url=SCHWAB_POSITION_ACCOUNT_URL_TEMPLATE,
            query=(ExternalAcquisitionQueryParameter("fields", "positions"),),
            approved_market_date=MARKET_DATE,
            requested_at_utc=self.started_at,
            received_at_utc=self.received_at,
            status_code=200,
            content_type="application/json",
            response_filename="positions.json",
            response_byte_count=len(self.body),
            response_sha256=sha256(self.body).hexdigest(),
            attempt_count=1,
            redirects_followed=0,
            provider_account_hash_sha256=sha256(
                PROVIDER_ACCOUNT_HASH.encode("utf-8")
            ).hexdigest(),
        )
        self.manifest = self.make_manifest()

    def make_manifest(self) -> ExternalProviderAcquisitionManifest:
        terms_profile = self.usage_policy.active_profiles["schwab"]
        return ExternalProviderAcquisitionManifest(
            schema=EXTERNAL_PROVIDER_ACQUISITION_SCHEMA,
            profile=SCHWAB_POSITION_EXTERNAL_ACQUISITION_PROFILE,
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
                    "producer", "onebot-position-producer-v1", "a" * 64
                ),
                ExternalAcquisitionSourceArtifact(
                    "provider_client_boundary", "onebot-schwab-client-v1", "b" * 64
                ),
            ),
            acquisition_run_uid=RUN_UID,
            acquisition_approval_id=APPROVAL_ID,
            acknowledgement_uid=self.acknowledgement_uid,
            acknowledgement_sha256=sha256(self.acknowledgement_bytes).hexdigest(),
            provider_use=ExternalAcquisitionProviderUse(
                terms_profile_id=terms_profile.profile_id,
                notice_version=terms_profile.notice_version,
                operating_scope=terms_profile.operating_scope,
                raw_evidence_policy_id=terms_profile.raw_evidence_lifecycle.policy_id,
            ),
            operation_allowlist=("position",),
            requests=(self.request,),
            controls=ExternalAcquisitionControls(
                provider_get_count=1,
                oauth_refresh_count=0,
                refresh_approval_id=None,
                account_endpoint_calls=0,
                position_endpoint_calls=1,
                transaction_endpoint_calls=0,
                order_endpoint_calls=0,
                database_writes=0,
                request_body_count=0,
                response_count=1,
            ),
            completed_at_utc=self.completed_at,
            final_status="complete",
            manifest_written_last=True,
        )

    def load(self, *, manifest=None, body=None):
        selected_manifest = manifest or self.manifest
        selected_body = self.body if body is None else body
        return load_external_provider_acquisition(
            external_provider_acquisition_manifest_bytes(selected_manifest),
            response_bytes={"positions.json": selected_body},
            acknowledgement_bytes=self.acknowledgement_bytes,
            usage_policy=self.usage_policy,
            evaluated_at_utc=self.completed_at + timedelta(seconds=1),
            expected_acquisition_run_uid=RUN_UID,
            expected_acquisition_approval_id=APPROVAL_ID,
            expected_owner_uid=OWNER_UID,
            expected_owner_epoch_uid=OWNER_EPOCH_UID,
        )

    @staticmethod
    def mappings() -> tuple[SchwabPositionMapping, ...]:
        return (
            SchwabPositionMapping(
                provider_symbol="AAPL",
                identity=InstrumentIdentity(
                    asset_class="equity",
                    market_scope="US",
                    currency="USD",
                    symbol="AAPL",
                ),
            ),
        )

    def convert(self, acquisition=None, **changes):
        values = {
            "provider_account_hash": PROVIDER_ACCOUNT_HASH,
            "provider_account_number": PROVIDER_ACCOUNT_NUMBER,
            "source_account_id": SOURCE_ACCOUNT_ID,
            "mappings": self.mappings(),
        }
        values.update(changes)
        return convert_external_schwab_positions(
            acquisition or self.load(),
            **values,
        )

    def test_exact_position_profile_converts_deterministically(self) -> None:
        acquisition = self.load()
        first = self.convert(acquisition)
        replay = self.convert(acquisition)

        self.assertEqual(first, replay)
        self.assertEqual(first.raw_response_bytes, self.body)
        self.assertEqual(first.external_request_uid, REQUEST_UID)
        self.assertEqual(first.external_manifest_sha256, acquisition.manifest_sha256)
        self.assertTrue(first.snapshot.account_complete)
        self.assertEqual(first.snapshot.source_account_id, SOURCE_ACCOUNT_ID)
        self.assertEqual(first.snapshot.raw_sha256, sha256(self.body).hexdigest())
        self.assertEqual(first.snapshot.positions[0].quantity, Decimal("10"))
        self.assertEqual(
            first.snapshot.positions[0].broker_unrealized_pnl,
            Decimal("97.5"),
        )

    def test_manifest_is_canonical_and_omits_raw_account_identifiers(self) -> None:
        manifest_bytes = external_provider_acquisition_manifest_bytes(self.manifest)
        self.assertNotIn(PROVIDER_ACCOUNT_HASH.encode("utf-8"), manifest_bytes)
        self.assertNotIn(PROVIDER_ACCOUNT_NUMBER.encode("utf-8"), manifest_bytes)
        document = json.loads(manifest_bytes)
        self.assertEqual(
            document["requests"][0]["url"],
            SCHWAB_POSITION_ACCOUNT_URL_TEMPLATE,
        )
        self.assertEqual(
            document["requests"][0]["provider_account_hash_sha256"],
            sha256(PROVIDER_ACCOUNT_HASH.encode("utf-8")).hexdigest(),
        )
        self.assertEqual(
            external_provider_acquisition_manifest_bytes(self.load().manifest),
            manifest_bytes,
        )

    def test_exact_endpoint_and_activity_scope_fail_closed(self) -> None:
        request_mutations = (
            replace(
                self.request,
                url=(
                    "https://api.schwabapi.com/trader/v1/accounts/"
                    f"{PROVIDER_ACCOUNT_HASH}"
                ),
            ),
            replace(self.request, url="https://example.invalid/trader/v1/accounts/x"),
            replace(self.request, method="POST"),
            replace(
                self.request,
                query=(ExternalAcquisitionQueryParameter("fields", "orders"),),
            ),
            replace(self.request, attempt_count=2),
            replace(self.request, redirects_followed=1),
            replace(self.request, provider_account_hash_sha256=None),
        )
        for request in request_mutations:
            with self.subTest(request=request), self.assertRaises(
                ExternalProviderAcquisitionError
            ):
                external_provider_acquisition_manifest_bytes(
                    replace(self.manifest, requests=(request,))
                )

        control_mutations = (
            replace(self.manifest.controls, account_endpoint_calls=1),
            replace(self.manifest.controls, position_endpoint_calls=0),
            replace(self.manifest.controls, transaction_endpoint_calls=1),
            replace(self.manifest.controls, order_endpoint_calls=1),
            replace(self.manifest.controls, database_writes=1),
            replace(self.manifest.controls, request_body_count=1),
        )
        for controls in control_mutations:
            with self.subTest(controls=controls), self.assertRaises(
                ExternalProviderAcquisitionError
            ):
                external_provider_acquisition_manifest_bytes(
                    replace(self.manifest, controls=controls)
                )

        with self.assertRaisesRegex(
            ExternalProviderAcquisitionError, "exactly one"
        ):
            external_provider_acquisition_manifest_bytes(
                replace(
                    self.manifest,
                    requests=(self.request, replace(self.request, request_uid="other-request")),
                    controls=replace(
                        self.manifest.controls,
                        provider_get_count=2,
                        response_count=2,
                    ),
                )
            )

    def test_tamper_account_and_mapping_mismatches_fail_closed(self) -> None:
        with self.assertRaisesRegex(
            ExternalProviderAcquisitionError, "checksum"
        ):
            self.load(body=self.body + b" ")
        with self.assertRaisesRegex(
            ExternalProviderAcquisitionError, "account hash binding"
        ):
            self.convert(provider_account_hash="different-private-account-hash")
        with self.assertRaisesRegex(
            ExternalProviderAcquisitionError, "adapter contract"
        ):
            self.convert(provider_account_number="OTHER-ACCOUNT")
        with self.assertRaisesRegex(
            ExternalProviderAcquisitionError, "adapter contract"
        ):
            self.convert(mappings=())

    def test_unknown_private_or_credential_fields_are_rejected(self) -> None:
        document = json.loads(
            external_provider_acquisition_manifest_bytes(self.manifest)
        )
        document["provider_account_number"] = PROVIDER_ACCOUNT_NUMBER
        document["access_token"] = "synthetic-forbidden-token"
        manifest_bytes = (
            json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode("utf-8")
        with self.assertRaisesRegex(ExternalProviderAcquisitionError, "fields"):
            load_external_provider_acquisition(
                manifest_bytes,
                response_bytes={"positions.json": self.body},
                acknowledgement_bytes=self.acknowledgement_bytes,
                usage_policy=self.usage_policy,
                evaluated_at_utc=self.completed_at + timedelta(seconds=1),
                expected_acquisition_run_uid=RUN_UID,
                expected_acquisition_approval_id=APPROVAL_ID,
                expected_owner_uid=OWNER_UID,
                expected_owner_epoch_uid=OWNER_EPOCH_UID,
            )

    def private_binding(self) -> SchwabPositionPrivateBinding:
        return SchwabPositionPrivateBinding(
            schema=SCHWAB_POSITION_PRIVATE_BINDING_SCHEMA,
            connection_uid=CONNECTION_UID,
            source_account_id=SOURCE_ACCOUNT_ID,
            provider_account_hash=PROVIDER_ACCOUNT_HASH,
            provider_account_number=PROVIDER_ACCOUNT_NUMBER,
            mappings=self.mappings(),
        )

    def test_private_binding_is_canonical_and_fails_closed(self) -> None:
        binding = self.private_binding()
        body = schwab_position_private_binding_bytes(binding)
        self.assertEqual(load_schwab_position_private_binding_bytes(body), binding)
        self.assertIn(PROVIDER_ACCOUNT_HASH.encode("utf-8"), body)
        self.assertIn(PROVIDER_ACCOUNT_NUMBER.encode("utf-8"), body)

        noncanonical = json.dumps(json.loads(body)).encode("utf-8")
        with self.assertRaisesRegex(
            SchwabPositionPrivateBindingError, "not canonical"
        ):
            load_schwab_position_private_binding_bytes(noncanonical)
        document = json.loads(body)
        document["mappings"][0]["identity"]["symbol"] = "MSFT"
        document["mappings"].append(document["mappings"][0])
        duplicate = (
            json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode("utf-8")
        with self.assertRaisesRegex(SchwabPositionPrivateBindingError, "unique"):
            load_schwab_position_private_binding_bytes(duplicate)

    def test_validation_only_operator_is_private_and_secret_free(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            acquisition_root = root / "acquisition"
            acquisition_root.mkdir(mode=0o700)
            acquisition_root.chmod(0o700)
            for name, body in {
                "acquisition-manifest.json": external_provider_acquisition_manifest_bytes(
                    self.manifest
                ),
                "positions.json": self.body,
            }.items():
                path = acquisition_root / name
                path.write_bytes(body)
                path.chmod(0o600)
            acknowledgement = root / "provider-usage-acknowledgement.json"
            acknowledgement.write_bytes(self.acknowledgement_bytes)
            acknowledgement.chmod(0o600)
            binding = root / "private-position-binding.json"
            binding.write_bytes(schwab_position_private_binding_bytes(self.private_binding()))
            binding.chmod(0o600)
            common = [
                "--acquisition-root", str(acquisition_root),
                "--acknowledgement", str(acknowledgement),
                "--position-binding", str(binding),
                "--expected-run-uid", RUN_UID,
                "--expected-approval-id", APPROVAL_ID,
                "--expected-owner-uid", OWNER_UID,
                "--expected-owner-epoch-uid", OWNER_EPOCH_UID,
                "--evaluated-at", (self.completed_at + timedelta(seconds=1)).isoformat(),
            ]
            output = StringIO()
            before = {item.name for item in root.iterdir()}
            with redirect_stdout(output):
                self.assertEqual(position_intake_main(common), 0)
            audit = json.loads(output.getvalue())
            self.assertEqual(
                audit["final_status"],
                "validated_external_position_unmaterialized",
            )
            self.assertTrue(audit["account_complete"])
            self.assertEqual(audit["position_count"], 1)
            self.assertEqual({item.name for item in root.iterdir()}, before)
            self.assertNotIn(PROVIDER_ACCOUNT_HASH, output.getvalue())
            self.assertNotIn(PROVIDER_ACCOUNT_NUMBER, output.getvalue())
            self.assertNotIn("AAPL", output.getvalue())

            binding.chmod(0o644)
            with self.assertRaisesRegex(ExternalSchwabPositionIntakeError, "0600"):
                position_intake_main(common)
            binding.chmod(0o600)
            wrong_binding = replace(self.private_binding(), connection_uid="connection:other")
            binding.write_bytes(schwab_position_private_binding_bytes(wrong_binding))
            binding.chmod(0o600)
            with self.assertRaisesRegex(
                ExternalSchwabPositionIntakeError, "connection mismatch"
            ):
                position_intake_main(common)

    def test_position_operator_has_no_provider_or_write_capability(self) -> None:
        source = (
            Path(__file__).resolve().parents[1]
            / "scripts/journal/validate_external_schwab_position_acquisition.py"
        ).read_text(encoding="utf-8")
        for forbidden in (
            "import requests", "import httpx", "import duckdb", "Authorization",
            "access_token", "refresh_token", "subprocess", "socket", "urllib",
            "write_bytes(", "write_text(", "mkdir(",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
