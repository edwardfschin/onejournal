from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
import tempfile
import unittest

import yaml

from onejournal.provider_connectors import (
    PROVIDER_USAGE_ACKNOWLEDGEMENT_CONTRACT_VERSION,
    ProviderUsageAcknowledgement,
    ProviderUsagePolicyError,
    authorize_raw_evidence_deletion,
    build_provider_usage_acknowledgement_uid,
    load_provider_usage_policy,
    validate_provider_usage_acknowledgement,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = PROJECT_ROOT / "config" / "marketdata.yaml"


class ProviderUsagePolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = load_provider_usage_policy(POLICY_PATH)
        self.profile = self.policy.active_profiles["schwab"]
        self.evaluated_at = datetime(2026, 8, 28, 1, 0, tzinfo=UTC)

    def _acknowledgement(self, **changes: object) -> ProviderUsageAcknowledgement:
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

    def _load_mutated_policy(self, mutate) -> None:
        config = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))
        mutate(config)
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "marketdata.yaml"
            path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
            load_provider_usage_policy(path)

    def test_repository_policy_is_local_personal_and_fail_closed(self) -> None:
        profile = self.profile

        self.assertEqual(profile.operating_scope, "owner_operated_local_connection")
        self.assertEqual(profile.permitted_use, "personal_noncommercial")
        self.assertTrue(profile.requires_authenticated_provider_terms_confirmation)
        self.assertTrue(profile.provider_reported_entitlement_required)
        self.assertFalse(profile.redistribution_allowed)
        self.assertFalse(profile.public_display_allowed)
        self.assertFalse(profile.hosted_storage_allowed)
        self.assertEqual(len(profile.official_terms), 3)
        lifecycle = profile.raw_evidence_lifecycle
        self.assertFalse(lifecycle.automatic_deletion_enabled)
        self.assertIsNone(lifecycle.fixed_retention_period_days)
        self.assertTrue(lifecycle.deletion_requires_explicit_approval)
        self.assertTrue(lifecycle.deletion_audit_required)
        self.assertTrue(lifecycle.provider_rule_change_requires_new_profile)

    def test_exact_current_acknowledgement_authorizes_retrieval_boundary(self) -> None:
        acknowledgement = self._acknowledgement()

        authorization = validate_provider_usage_acknowledgement(
            acknowledgement,
            policy=self.policy,
            expected_provider="schwab",
            expected_connection_uid="local-schwab-primary",
            evaluated_at_utc=self.evaluated_at,
        )

        self.assertEqual(authorization.provider, "schwab")
        self.assertEqual(authorization.connection_uid, "local-schwab-primary")
        self.assertEqual(
            authorization.acknowledgement_uid,
            build_provider_usage_acknowledgement_uid(acknowledgement),
        )
        self.assertTrue(authorization.provider_reported_entitlement_required)

    def test_acknowledgement_cannot_substitute_for_active_profile_or_scope(self) -> None:
        cases = (
            ("terms_profile_id", "schwab-superseded-profile.v0", "not active"),
            ("notice_version", "onejournal-old-notice.v0", "not active"),
            ("operating_scope", "hosted_multi_user", "scope mismatch"),
            ("raw_evidence_policy_id", "raw-policy-old.v0", "policy mismatch"),
        )
        for field, value, message in cases:
            with self.subTest(field=field):
                acknowledgement = self._acknowledgement(**{field: value})
                with self.assertRaisesRegex(ProviderUsagePolicyError, message):
                    validate_provider_usage_acknowledgement(
                        acknowledgement,
                        policy=self.policy,
                        expected_provider="schwab",
                        expected_connection_uid="local-schwab-primary",
                        evaluated_at_utc=self.evaluated_at,
                    )

    def test_request_provider_and_connection_must_match_acknowledgement(self) -> None:
        acknowledgement = self._acknowledgement()
        with self.assertRaisesRegex(ProviderUsagePolicyError, "provider mismatch"):
            validate_provider_usage_acknowledgement(
                acknowledgement,
                policy=self.policy,
                expected_provider="ibkr",
                expected_connection_uid="local-schwab-primary",
                evaluated_at_utc=self.evaluated_at,
            )
        with self.assertRaisesRegex(ProviderUsagePolicyError, "connection mismatch"):
            validate_provider_usage_acknowledgement(
                acknowledgement,
                policy=self.policy,
                expected_provider="schwab",
                expected_connection_uid="different-connection",
                evaluated_at_utc=self.evaluated_at,
            )

    def test_missing_declaration_and_changed_identity_fail_closed(self) -> None:
        missing = self._acknowledgement(
            declarations=self.profile.required_declarations
            - {"authenticated_provider_terms_reviewed"}
        )
        with self.assertRaisesRegex(ProviderUsagePolicyError, "declarations"):
            validate_provider_usage_acknowledgement(
                missing,
                policy=self.policy,
                expected_provider="schwab",
                expected_connection_uid="local-schwab-primary",
                evaluated_at_utc=self.evaluated_at,
            )

        tampered = self._acknowledgement(acknowledgement_uid="provider-usage-ack:wrong")
        with self.assertRaisesRegex(ProviderUsagePolicyError, "identity mismatch"):
            validate_provider_usage_acknowledgement(
                tampered,
                policy=self.policy,
                expected_provider="schwab",
                expected_connection_uid="local-schwab-primary",
                evaluated_at_utc=self.evaluated_at,
            )

    def test_pre_review_and_future_acknowledgements_fail_closed(self) -> None:
        before_review = self._acknowledgement(
            accepted_at_utc=self.profile.reviewed_at_utc - timedelta(seconds=1)
        )
        with self.assertRaisesRegex(ProviderUsagePolicyError, "predates"):
            validate_provider_usage_acknowledgement(
                before_review,
                policy=self.policy,
                expected_provider="schwab",
                expected_connection_uid="local-schwab-primary",
                evaluated_at_utc=self.evaluated_at,
            )

        future = self._acknowledgement(
            accepted_at_utc=self.evaluated_at + timedelta(seconds=1)
        )
        with self.assertRaisesRegex(ProviderUsagePolicyError, "future"):
            validate_provider_usage_acknowledgement(
                future,
                policy=self.policy,
                expected_provider="schwab",
                expected_connection_uid="local-schwab-primary",
                evaluated_at_utc=self.evaluated_at,
            )

    def test_policy_cannot_enable_redistribution_or_automatic_deletion(self) -> None:
        with self.assertRaisesRegex(ProviderUsagePolicyError, "operating scope"):
            self._load_mutated_policy(
                lambda config: config["marketdata"]["provider_usage"][
                    "active_profiles"
                ]["schwab"].update(redistribution_allowed=True)
            )

        with self.assertRaisesRegex(ProviderUsagePolicyError, "weakens"):
            self._load_mutated_policy(
                lambda config: config["marketdata"]["provider_usage"][
                    "active_profiles"
                ]["schwab"]["raw_evidence_lifecycle"].update(
                    automatic_deletion_enabled=True
                )
            )

    def test_raw_deletion_requires_manual_approval_and_audit(self) -> None:
        authorization = validate_provider_usage_acknowledgement(
            self._acknowledgement(),
            policy=self.policy,
            expected_provider="schwab",
            expected_connection_uid="local-schwab-primary",
            evaluated_at_utc=self.evaluated_at,
        )
        with self.assertRaisesRegex(ProviderUsagePolicyError, "automatic"):
            authorize_raw_evidence_deletion(
                authorization,
                approval_id="PNL-02-T11-DELETE-APPROVAL",
                audit_recording_ready=True,
                automatic=True,
                authorized_at_utc=self.evaluated_at,
            )
        with self.assertRaisesRegex(ProviderUsagePolicyError, "audited"):
            authorize_raw_evidence_deletion(
                authorization,
                approval_id="PNL-02-T11-DELETE-APPROVAL",
                audit_recording_ready=False,
                automatic=False,
                authorized_at_utc=self.evaluated_at,
            )

        deletion = authorize_raw_evidence_deletion(
            authorization,
            approval_id="PNL-02-T11-DELETE-APPROVAL",
            audit_recording_ready=True,
            automatic=False,
            authorized_at_utc=self.evaluated_at,
        )
        self.assertTrue(
            deletion.deletion_authorization_uid.startswith("raw-evidence-deletion:")
        )
        self.assertEqual(deletion.acknowledgement_uid, authorization.acknowledgement_uid)


if __name__ == "__main__":
    unittest.main()
