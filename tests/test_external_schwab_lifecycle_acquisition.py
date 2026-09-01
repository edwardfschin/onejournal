from __future__ import annotations

from contextlib import redirect_stdout
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from io import StringIO
import json
from pathlib import Path
import tempfile
from types import MappingProxyType
import unittest

from onejournal.brokers.schwab.account_binding import (
    SCHWAB_ACCOUNT_PRIVATE_BINDING_SCHEMA,
    SchwabAccountPrivateBinding,
    SchwabAccountPrivateBindingError,
    load_schwab_account_private_binding_bytes,
    schwab_account_private_binding_bytes,
)
from onejournal.provider_connectors.external_acquisition import (
    EXTERNAL_PROVIDER_ACQUISITION_SCHEMA,
    SCHWAB_ACCOUNT_ORDERS_URL_TEMPLATE,
    SCHWAB_ACCOUNT_TRANSACTIONS_URL_TEMPLATE,
    SCHWAB_LIFECYCLE_EXTERNAL_ACQUISITION_PROFILE,
    SCHWAB_LIFECYCLE_MAX_RESULTS,
    SCHWAB_LIFECYCLE_TRANSACTION_TYPES,
    ExternalAcquisitionControls,
    ExternalAcquisitionProviderUse,
    ExternalAcquisitionQueryParameter,
    ExternalAcquisitionRequest,
    ExternalAcquisitionSourceArtifact,
    ExternalAcquisitionSourceOwner,
    ExternalProviderAcquisitionError,
    ExternalProviderAcquisitionManifest,
    convert_external_schwab_lifecycle,
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
from scripts.journal.validate_external_schwab_lifecycle_acquisition import (
    ExternalSchwabLifecycleIntakeError,
    main as lifecycle_intake_main,
)


CONNECTION_UID = "connection:schwab:external-owner"
SOURCE_ACCOUNT_ID = "account:owner:primary"
RUN_UID = "PNL-03L-EXTERNAL-LIFECYCLE-0001"
APPROVAL_ID = "PNL-03L-EXTERNAL-APPROVAL-0001"
OWNER_UID = "onebot-owner-primary"
OWNER_EPOCH_UID = "onebot-owner-epoch-0001"
PROVIDER_ACCOUNT_HASH = "synthetic-high-entropy-account-hash"
PROVIDER_ACCOUNT_NUMBER = "SYNTHETIC-ACCOUNT"
WINDOW_START = date(2026, 8, 31)
WINDOW_END = date(2026, 8, 31)
OPTION_SYMBOL = "AAPL  260918C00200000"


def canonical_json_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def order_document() -> list[dict[str, object]]:
    return [
        {
            "accountNumber": PROVIDER_ACCOUNT_NUMBER,
            "orderId": 12345,
            "enteredTime": "2026-08-31T13:00:00Z",
            "destinationLinkName": "AUTO",
            "orderLegCollection": [
                {
                    "legId": 1,
                    "instruction": "BUY_TO_OPEN",
                    "positionEffect": "OPENING",
                    "instrument": {
                        "assetType": "OPTION",
                        "symbol": OPTION_SYMBOL,
                        "underlyingSymbol": "AAPL",
                        "putCall": "CALL",
                        "optionDeliverables": [{"deliverableUnits": 100}],
                    },
                }
            ],
            "orderActivityCollection": [
                {
                    "activityId": 987,
                    "executionType": "FILL",
                    "executionLegs": [
                        {
                            "legId": 1,
                            "quantity": 2,
                            "price": "5.25",
                            "time": "2026-08-31T13:01:00Z",
                        }
                    ],
                }
            ],
        }
    ]


def transaction_document() -> list[dict[str, object]]:
    return [
        {
            "accountNumber": PROVIDER_ACCOUNT_NUMBER,
            "activityId": 987,
            "orderId": 12345,
            "positionId": 555,
            "type": "TRADE",
            "status": "VALID",
            "tradeDate": "2026-08-31T13:01:00Z",
            "time": "2026-08-31T13:01:00Z",
            "transferItems": [
                {
                    "amount": 2,
                    "price": "5.25",
                    "positionEffect": "OPENING",
                    "instrument": {
                        "assetType": "OPTION",
                        "symbol": OPTION_SYMBOL,
                        "underlyingSymbol": "AAPL",
                        "putCall": "CALL",
                        "optionPremiumMultiplier": 100,
                    },
                },
                {
                    "amount": "-1.30",
                    "cost": "1.30",
                    "feeType": "COMMISSION",
                    "instrument": {"assetType": "CURRENCY", "symbol": "USD"},
                },
            ],
        }
    ]


class ExternalSchwabLifecycleAcquisitionTests(unittest.TestCase):
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
            creation_approval_id="PNL-03L-ACK-CREATION-0001",
        )
        self.acknowledgement_uid = acknowledgement.acknowledgement_uid
        self.order_body = canonical_json_bytes(order_document())
        self.transaction_body = canonical_json_bytes(transaction_document())
        self.started_at = datetime(2026, 8, 31, 14, 0, tzinfo=UTC)
        self.received_at = self.started_at + timedelta(seconds=1)
        self.completed_at = self.received_at + timedelta(seconds=1)
        digest = sha256(PROVIDER_ACCOUNT_HASH.encode("utf-8")).hexdigest()
        start = "2026-08-31T00:00:00.000Z"
        end = "2026-08-31T23:59:59.999Z"
        self.order_request = self.make_request(
            request_uid="schwab-lifecycle-orders-0001",
            operation="orders",
            url=SCHWAB_ACCOUNT_ORDERS_URL_TEMPLATE,
            query=(
                ExternalAcquisitionQueryParameter("fromEnteredTime", start),
                ExternalAcquisitionQueryParameter("toEnteredTime", end),
                ExternalAcquisitionQueryParameter(
                    "maxResults", str(SCHWAB_LIFECYCLE_MAX_RESULTS)
                ),
            ),
            filename="orders.json",
            body=self.order_body,
            account_digest=digest,
        )
        self.transaction_request = self.make_request(
            request_uid="schwab-lifecycle-transactions-0001",
            operation="transactions",
            url=SCHWAB_ACCOUNT_TRANSACTIONS_URL_TEMPLATE,
            query=(
                ExternalAcquisitionQueryParameter("startDate", start),
                ExternalAcquisitionQueryParameter("endDate", end),
                ExternalAcquisitionQueryParameter(
                    "types", SCHWAB_LIFECYCLE_TRANSACTION_TYPES
                ),
            ),
            filename="transactions.json",
            body=self.transaction_body,
            account_digest=digest,
        )
        self.manifest = self.make_manifest()

    def make_request(
        self,
        *,
        request_uid: str,
        operation: str,
        url: str,
        query: tuple[ExternalAcquisitionQueryParameter, ...],
        filename: str,
        body: bytes,
        account_digest: str,
    ) -> ExternalAcquisitionRequest:
        return ExternalAcquisitionRequest(
            request_uid=request_uid,
            operation=operation,
            method="GET",
            url=url,
            query=query,
            approved_market_date=WINDOW_END,
            requested_at_utc=self.started_at,
            received_at_utc=self.received_at,
            status_code=200,
            content_type="application/json",
            response_filename=filename,
            response_byte_count=len(body),
            response_sha256=sha256(body).hexdigest(),
            attempt_count=1,
            redirects_followed=0,
            provider_account_hash_sha256=account_digest,
            window_start_date=WINDOW_START,
            window_end_date=WINDOW_END,
        )

    def make_manifest(
        self,
        *,
        order_request: ExternalAcquisitionRequest | None = None,
        transaction_request: ExternalAcquisitionRequest | None = None,
    ) -> ExternalProviderAcquisitionManifest:
        terms_profile = self.usage_policy.active_profiles["schwab"]
        return ExternalProviderAcquisitionManifest(
            schema=EXTERNAL_PROVIDER_ACQUISITION_SCHEMA,
            profile=SCHWAB_LIFECYCLE_EXTERNAL_ACQUISITION_PROFILE,
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
                    "producer", "onebot-lifecycle-producer-v1", "a" * 64
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
            operation_allowlist=("orders", "transactions"),
            requests=(
                order_request or self.order_request,
                transaction_request or self.transaction_request,
            ),
            controls=ExternalAcquisitionControls(
                provider_get_count=2,
                oauth_refresh_count=0,
                refresh_approval_id=None,
                account_endpoint_calls=0,
                position_endpoint_calls=0,
                transaction_endpoint_calls=1,
                order_endpoint_calls=1,
                database_writes=0,
                request_body_count=0,
                response_count=2,
            ),
            completed_at_utc=self.completed_at,
            final_status="complete",
            manifest_written_last=True,
        )

    def account_binding(self) -> SchwabAccountPrivateBinding:
        return SchwabAccountPrivateBinding(
            schema=SCHWAB_ACCOUNT_PRIVATE_BINDING_SCHEMA,
            connection_uid=CONNECTION_UID,
            source_account_id=SOURCE_ACCOUNT_ID,
            provider_account_hash=PROVIDER_ACCOUNT_HASH,
            provider_account_number=PROVIDER_ACCOUNT_NUMBER,
        )

    def load(self, *, manifest=None, order_body=None, transaction_body=None):
        selected_manifest = manifest or self.manifest
        selected_order_body = self.order_body if order_body is None else order_body
        selected_transaction_body = (
            self.transaction_body if transaction_body is None else transaction_body
        )
        return load_external_provider_acquisition(
            external_provider_acquisition_manifest_bytes(selected_manifest),
            response_bytes={
                "orders.json": selected_order_body,
                "transactions.json": selected_transaction_body,
            },
            acknowledgement_bytes=self.acknowledgement_bytes,
            usage_policy=self.usage_policy,
            evaluated_at_utc=self.completed_at + timedelta(seconds=1),
            expected_acquisition_run_uid=RUN_UID,
            expected_acquisition_approval_id=APPROVAL_ID,
            expected_owner_uid=OWNER_UID,
            expected_owner_epoch_uid=OWNER_EPOCH_UID,
        )

    def convert(self, acquisition=None, **changes):
        values = {
            "provider_account_hash": PROVIDER_ACCOUNT_HASH,
            "provider_account_number": PROVIDER_ACCOUNT_NUMBER,
            "source_account_id": SOURCE_ACCOUNT_ID,
        }
        values.update(changes)
        return convert_external_schwab_lifecycle(acquisition or self.load(), **values)

    def test_paired_profile_converts_and_reconciles_deterministically(self) -> None:
        acquisition = self.load()
        first = self.convert(acquisition)
        replay = self.convert(acquisition)

        self.assertEqual(first, replay)
        self.assertEqual(len(first.order_rows), 1)
        self.assertEqual(len(first.transaction_rows), 1)
        self.assertTrue(first.reconciliation.exact)
        self.assertEqual(first.reconciliation.matched_rows, 1)
        self.assertEqual(first.order_rows[0]["source_account_id"], SOURCE_ACCOUNT_ID)
        self.assertEqual(
            first.transaction_rows[0]["source_account_id"], SOURCE_ACCOUNT_ID
        )
        self.assertEqual(first.transaction_rows[0]["multiplier"], "100")
        self.assertEqual(first.transaction_rows[0]["currency"], "USD")
        self.assertEqual(first.excluded_out_of_window_order_records, 0)
        self.assertEqual(first.excluded_out_of_window_order_fill_rows, 0)
        self.assertEqual(first.excluded_out_of_window_transaction_fill_rows, 0)
        self.assertEqual(first.excluded_out_of_window_lifecycle_events, 0)
        self.assertEqual(first.excluded_out_of_window_lifecycle_event_legs, 0)

    def test_record_membership_and_exact_row_timestamps_are_distinct(self) -> None:
        execution_inside = order_document()[0]
        execution_inside["enteredTime"] = "2026-08-30T13:00:00Z"

        old_child = order_document()[0]
        old_child["orderId"] = 12346
        old_child["enteredTime"] = "2024-08-30T13:00:00Z"
        old_child["orderActivityCollection"][0]["activityId"] = 988
        old_child["orderActivityCollection"][0]["executionLegs"][0]["time"] = (
            "2024-08-30T13:01:00Z"
        )
        close_inside_parent = {
            "accountNumber": PROVIDER_ACCOUNT_NUMBER,
            "orderId": 12347,
            "enteredTime": "2024-08-30T13:00:00Z",
            "closeTime": "2026-08-31T14:00:00Z",
            "orderStrategyType": "OCO",
            "childOrderStrategies": [old_child],
        }
        repeated_outside_parent = {
            **close_inside_parent,
            "orderId": 12349,
            "closeTime": "2026-09-01T14:00:00Z",
        }
        orders = [execution_inside, close_inside_parent, repeated_outside_parent]

        outside_event = {
            "accountNumber": PROVIDER_ACCOUNT_NUMBER,
            "activityId": 989,
            "orderId": 12348,
            "positionId": 557,
            "type": "TRADE",
            "status": "VALID",
            "activityType": "EXPIRATION",
            "tradeDate": "2026-09-01T00:01:00Z",
            "time": "2026-08-31T23:59:00Z",
            "transferItems": [
                {
                    "amount": -1,
                    "positionEffect": "CLOSING",
                    "instrument": {
                        "assetType": "OPTION",
                        "symbol": OPTION_SYMBOL,
                        "underlyingSymbol": "AAPL",
                        "putCall": "CALL",
                        "optionPremiumMultiplier": 100,
                    },
                }
            ],
        }
        transactions = [*transaction_document(), outside_event]
        order_body = canonical_json_bytes(orders)
        transaction_body = canonical_json_bytes(transactions)
        order_request = replace(
            self.order_request,
            response_byte_count=len(order_body),
            response_sha256=sha256(order_body).hexdigest(),
        )
        transaction_request = replace(
            self.transaction_request,
            response_byte_count=len(transaction_body),
            response_sha256=sha256(transaction_body).hexdigest(),
        )
        acquisition = self.load(
            manifest=self.make_manifest(
                order_request=order_request,
                transaction_request=transaction_request,
            ),
            order_body=order_body,
            transaction_body=transaction_body,
        )

        converted = self.convert(acquisition)

        self.assertEqual(len(converted.order_rows), 1)
        self.assertEqual(len(converted.transaction_rows), 1)
        self.assertEqual(converted.reconciliation.matched_rows, 1)
        self.assertEqual(converted.excluded_out_of_window_order_records, 1)
        self.assertEqual(converted.excluded_out_of_window_order_fill_rows, 1)
        self.assertEqual(converted.excluded_out_of_window_transaction_fill_rows, 0)
        self.assertEqual(converted.excluded_out_of_window_lifecycle_events, 1)
        self.assertEqual(converted.excluded_out_of_window_lifecycle_event_legs, 1)
        self.assertEqual(converted.order_stats.fill_rows, 1)
        self.assertEqual(converted.transaction_stats.fill_rows, 1)

    def test_provider_currency_consensus_resolves_one_missing_trade_currency(self) -> None:
        transactions = transaction_document()
        transactions.append(
            {
                "accountNumber": PROVIDER_ACCOUNT_NUMBER,
                "activityId": 988,
                "positionId": 556,
                "type": "TRADE",
                "status": "VALID",
                "tradeDate": "2026-08-31T13:02:00Z",
                "time": "2026-08-31T13:02:00Z",
                "transferItems": [
                    {
                        "amount": 1,
                        "price": "200",
                        "cost": "200",
                        "positionEffect": "OPENING",
                        "instrument": {
                            "assetType": "EQUITY",
                            "symbol": "MSFT",
                        },
                    }
                ],
            }
        )
        body = canonical_json_bytes(transactions)
        request = replace(
            self.transaction_request,
            response_byte_count=len(body),
            response_sha256=sha256(body).hexdigest(),
        )
        acquisition = self.load(
            manifest=self.make_manifest(transaction_request=request),
            transaction_body=body,
        )

        converted = self.convert(acquisition)

        self.assertEqual(len(converted.transaction_rows), 2)
        self.assertEqual(converted.transaction_rows[1]["currency"], "USD")
        self.assertEqual(converted.transaction_stats.currency_consensus_code, "USD")
        self.assertEqual(
            converted.transaction_stats.currency_consensus_evidence_items, 1
        )
        self.assertEqual(
            converted.transaction_stats.currency_consensus_resolved_records, 1
        )
        self.assertEqual(converted.reconciliation.matched_rows, 1)
        self.assertEqual(converted.reconciliation.only_order_rows, 0)
        self.assertEqual(converted.reconciliation.only_transaction_rows, 1)

    def test_manifest_is_canonical_and_omits_raw_account_identifiers(self) -> None:
        body = external_provider_acquisition_manifest_bytes(self.manifest)
        self.assertNotIn(PROVIDER_ACCOUNT_HASH.encode("utf-8"), body)
        self.assertNotIn(PROVIDER_ACCOUNT_NUMBER.encode("utf-8"), body)
        document = json.loads(body)
        self.assertEqual(
            [item["operation"] for item in document["requests"]],
            ["orders", "transactions"],
        )
        self.assertEqual(
            document["requests"][0]["provider_account_hash_sha256"],
            sha256(PROVIDER_ACCOUNT_HASH.encode("utf-8")).hexdigest(),
        )
        self.assertEqual(
            external_provider_acquisition_manifest_bytes(self.load().manifest), body
        )

    def test_endpoint_window_and_control_scope_fail_closed(self) -> None:
        bad_order_requests = (
            replace(self.order_request, method="POST"),
            replace(self.order_request, url="https://example.invalid/orders"),
            replace(
                self.order_request,
                query=(ExternalAcquisitionQueryParameter("maxResults", "3000"),),
            ),
            replace(self.order_request, attempt_count=2),
            replace(self.order_request, redirects_followed=1),
            replace(self.order_request, window_start_date=date(2026, 8, 1)),
        )
        for request in bad_order_requests:
            with self.subTest(request=request), self.assertRaises(
                ExternalProviderAcquisitionError
            ):
                external_provider_acquisition_manifest_bytes(
                    self.make_manifest(order_request=request)
                )

        mismatched_transaction = replace(
            self.transaction_request,
            window_start_date=date(2026, 8, 30),
            query=(
                ExternalAcquisitionQueryParameter(
                    "startDate", "2026-08-30T00:00:00.000Z"
                ),
                self.transaction_request.query[1],
                self.transaction_request.query[2],
            ),
        )
        with self.assertRaisesRegex(ExternalProviderAcquisitionError, "same account"):
            external_provider_acquisition_manifest_bytes(
                self.make_manifest(transaction_request=mismatched_transaction)
            )

        for controls in (
            replace(self.manifest.controls, account_endpoint_calls=1),
            replace(self.manifest.controls, position_endpoint_calls=1),
            replace(self.manifest.controls, transaction_endpoint_calls=0),
            replace(self.manifest.controls, order_endpoint_calls=0),
            replace(self.manifest.controls, database_writes=1),
            replace(self.manifest.controls, request_body_count=1),
        ):
            with self.subTest(controls=controls), self.assertRaises(
                ExternalProviderAcquisitionError
            ):
                external_provider_acquisition_manifest_bytes(
                    replace(self.manifest, controls=controls)
                )

    def test_tamper_account_window_and_truncation_fail_closed(self) -> None:
        with self.assertRaisesRegex(ExternalProviderAcquisitionError, "checksum"):
            self.load(order_body=self.order_body + b" ")
        with self.assertRaisesRegex(
            ExternalProviderAcquisitionError, "account hash binding"
        ):
            self.convert(provider_account_hash="different-private-account-hash")

        wrong_account_orders = order_document()
        wrong_account_orders[0]["accountNumber"] = "OTHER-ACCOUNT"
        wrong_body = canonical_json_bytes(wrong_account_orders)
        wrong_request = replace(
            self.order_request,
            response_byte_count=len(wrong_body),
            response_sha256=sha256(wrong_body).hexdigest(),
        )
        acquisition = self.load(
            manifest=self.make_manifest(order_request=wrong_request),
            order_body=wrong_body,
        )
        with self.assertRaisesRegex(ExternalProviderAcquisitionError, "account binding"):
            self.convert(acquisition)

        outside_orders = order_document()
        outside_orders[0]["enteredTime"] = "2026-08-30T13:00:00Z"
        outside_orders[0]["orderActivityCollection"][0]["executionLegs"][0][
            "time"
        ] = "2026-08-30T13:01:00Z"
        outside_body = canonical_json_bytes(outside_orders)
        outside_request = replace(
            self.order_request,
            response_byte_count=len(outside_body),
            response_sha256=sha256(outside_body).hexdigest(),
        )
        acquisition = self.load(
            manifest=self.make_manifest(order_request=outside_request),
            order_body=outside_body,
        )
        converted = self.convert(acquisition)
        self.assertEqual(converted.excluded_out_of_window_order_records, 1)
        self.assertEqual(converted.order_rows, ())
        self.assertEqual(len(converted.transaction_rows), 1)

        truncated_body = canonical_json_bytes(
            order_document() * SCHWAB_LIFECYCLE_MAX_RESULTS
        )
        truncated_request = replace(
            self.order_request,
            response_byte_count=len(truncated_body),
            response_sha256=sha256(truncated_body).hexdigest(),
        )
        acquisition = self.load(
            manifest=self.make_manifest(order_request=truncated_request),
            order_body=truncated_body,
        )
        with self.assertRaisesRegex(ExternalProviderAcquisitionError, "truncated"):
            self.convert(acquisition)

    def test_empty_paired_window_is_valid_and_not_false_activity(self) -> None:
        empty = b"[]\n"
        order_request = replace(
            self.order_request,
            response_byte_count=len(empty),
            response_sha256=sha256(empty).hexdigest(),
        )
        transaction_request = replace(
            self.transaction_request,
            response_byte_count=len(empty),
            response_sha256=sha256(empty).hexdigest(),
        )
        acquisition = self.load(
            manifest=self.make_manifest(
                order_request=order_request,
                transaction_request=transaction_request,
            ),
            order_body=empty,
            transaction_body=empty,
        )
        converted = self.convert(acquisition)
        self.assertEqual(converted.order_rows, ())
        self.assertEqual(converted.transaction_rows, ())
        self.assertTrue(converted.reconciliation.exact)

    def test_private_account_binding_is_canonical_and_fail_closed(self) -> None:
        binding = self.account_binding()
        body = schwab_account_private_binding_bytes(binding)
        self.assertEqual(load_schwab_account_private_binding_bytes(body), binding)
        self.assertIn(PROVIDER_ACCOUNT_HASH.encode("utf-8"), body)
        self.assertIn(PROVIDER_ACCOUNT_NUMBER.encode("utf-8"), body)

        with self.assertRaisesRegex(
            SchwabAccountPrivateBindingError, "not canonical"
        ):
            load_schwab_account_private_binding_bytes(json.dumps(json.loads(body)).encode())
        document = json.loads(body)
        document["access_token"] = "synthetic-forbidden-token"
        with self.assertRaisesRegex(SchwabAccountPrivateBindingError, "fields"):
            load_schwab_account_private_binding_bytes(canonical_json_bytes(document))

    def test_validation_operator_is_private_secret_free_and_non_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            acquisition_root = root / "acquisition"
            acquisition_root.mkdir(mode=0o700)
            acquisition_root.chmod(0o700)
            for name, body in {
                "acquisition-manifest.json": external_provider_acquisition_manifest_bytes(
                    self.manifest
                ),
                "orders.json": self.order_body,
                "transactions.json": self.transaction_body,
            }.items():
                path = acquisition_root / name
                path.write_bytes(body)
                path.chmod(0o600)
            acknowledgement = root / "provider-usage-acknowledgement.json"
            acknowledgement.write_bytes(self.acknowledgement_bytes)
            acknowledgement.chmod(0o600)
            binding = root / "private-account-binding.json"
            binding.write_bytes(
                schwab_account_private_binding_bytes(self.account_binding())
            )
            binding.chmod(0o600)
            common = [
                "--acquisition-root",
                str(acquisition_root),
                "--acknowledgement",
                str(acknowledgement),
                "--account-binding",
                str(binding),
                "--expected-run-uid",
                RUN_UID,
                "--expected-approval-id",
                APPROVAL_ID,
                "--expected-owner-uid",
                OWNER_UID,
                "--expected-owner-epoch-uid",
                OWNER_EPOCH_UID,
                "--evaluated-at",
                (self.completed_at + timedelta(seconds=1)).isoformat(),
            ]
            output = StringIO()
            before = {item.name for item in root.iterdir()}
            with redirect_stdout(output):
                self.assertEqual(lifecycle_intake_main(common), 0)
            audit = json.loads(output.getvalue())
            self.assertEqual(
                audit["final_status"],
                "validated_external_lifecycle_unmaterialized",
            )
            self.assertEqual(audit["reconciliation_status"], "exact")
            self.assertEqual(audit["matched_fill_rows"], 1)
            self.assertEqual(audit["currency_consensus_code"], "USD")
            self.assertEqual(audit["currency_consensus_evidence_item_count"], 1)
            self.assertEqual(audit["currency_consensus_resolved_records"], 0)
            self.assertEqual(audit["excluded_out_of_window_order_records"], 0)
            self.assertEqual(audit["excluded_out_of_window_order_fill_rows"], 0)
            self.assertEqual(
                audit["excluded_out_of_window_transaction_fill_rows"], 0
            )
            self.assertEqual(audit["excluded_out_of_window_lifecycle_events"], 0)
            self.assertEqual(
                audit["excluded_out_of_window_lifecycle_event_legs"], 0
            )
            self.assertEqual({item.name for item in root.iterdir()}, before)
            self.assertNotIn(PROVIDER_ACCOUNT_HASH, output.getvalue())
            self.assertNotIn(PROVIDER_ACCOUNT_NUMBER, output.getvalue())
            self.assertNotIn(OPTION_SYMBOL, output.getvalue())

            binding.chmod(0o644)
            with self.assertRaisesRegex(ExternalSchwabLifecycleIntakeError, "0600"):
                lifecycle_intake_main(common)

    def test_operator_has_no_provider_credential_database_or_write_capability(self) -> None:
        source = (
            Path(__file__).resolve().parents[1]
            / "scripts/journal/validate_external_schwab_lifecycle_acquisition.py"
        ).read_text(encoding="utf-8")
        for forbidden in (
            "import requests",
            "import httpx",
            "import duckdb",
            "Authorization",
            "access_token",
            "refresh_token",
            "subprocess",
            "socket",
            "urllib",
            "write_bytes(",
            "write_text(",
            "mkdir(",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
