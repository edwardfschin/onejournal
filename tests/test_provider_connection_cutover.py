from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
import unittest

from onejournal.provider_connectors import (
    PROVIDER_CONNECTION_CUTOVER_CONTRACT_VERSION,
    ProviderConnectionCutoverError,
    ProviderConnectionCutoverEvidence,
    ProviderConnectionCutoverObservation,
    ProviderOwnerCapabilityState,
    validate_provider_connection_cutover,
)


class ProviderConnectionCutoverTests(unittest.TestCase):
    def setUp(self) -> None:
        self.started_at = datetime(2026, 8, 29, 15, 0, tzinfo=UTC)
        self.source_active = ProviderOwnerCapabilityState(
            owner_uid="onebot-schwab-owner",
            host_uid="onebot-vps-host",
            owner_epoch_uid="onebot-owner-epoch-20260829",
            credential_generation_uid="onebot-credential-generation-20260829",
            credential_accessible=True,
            provider_call_enabled=True,
            token_refresh_enabled=True,
        )
        self.source_retired = replace(
            self.source_active,
            credential_accessible=False,
            provider_call_enabled=False,
            token_refresh_enabled=False,
        )
        self.target_absent = ProviderOwnerCapabilityState(
            owner_uid="onejournal-schwab-owner",
            host_uid="onejournal-staging-host",
            owner_epoch_uid=None,
            credential_generation_uid=None,
            credential_accessible=False,
            provider_call_enabled=False,
            token_refresh_enabled=False,
        )
        self.target_provisioned = replace(
            self.target_absent,
            owner_epoch_uid="onejournal-owner-epoch-20260829",
            credential_generation_uid="onejournal-credential-generation-20260829",
            credential_accessible=True,
        )
        self.target_active = replace(
            self.target_provisioned,
            provider_call_enabled=True,
            token_refresh_enabled=True,
        )

    def evidence(self, **changes: object) -> ProviderConnectionCutoverEvidence:
        observations = (
            ProviderConnectionCutoverObservation(
                phase="source_active",
                observed_at_utc=self.started_at,
                source=self.source_active,
                target=self.target_absent,
                evidence_sha256="1" * 64,
            ),
            ProviderConnectionCutoverObservation(
                phase="owner_gap",
                observed_at_utc=self.started_at + timedelta(minutes=1),
                source=self.source_retired,
                target=self.target_absent,
                evidence_sha256="2" * 64,
            ),
            ProviderConnectionCutoverObservation(
                phase="target_provisioned_disabled",
                observed_at_utc=self.started_at + timedelta(minutes=2),
                source=self.source_retired,
                target=self.target_provisioned,
                evidence_sha256="3" * 64,
            ),
            ProviderConnectionCutoverObservation(
                phase="target_active",
                observed_at_utc=self.started_at + timedelta(minutes=3),
                source=self.source_retired,
                target=self.target_active,
                evidence_sha256="4" * 64,
            ),
        )
        return replace(
            ProviderConnectionCutoverEvidence(
                contract_version=PROVIDER_CONNECTION_CUTOVER_CONTRACT_VERSION,
                cutover_uid="PNL-02-T15-CUTOVER-20260829-01",
                direction="forward",
                provider="schwab",
                connection_uid="local-schwab-primary",
                approval_id="PNL-02-T15-CUTOVER-APPROVAL-01",
                hosted_data_authorization_id="PNL-02-T15-HOSTED-DATA-APPROVAL-01",
                provider_usage_acknowledgement_uid="provider-usage-acknowledgement-01",
                target_public_listener_enabled=False,
                target_journal_database_mounted=False,
                observations=observations,
            ),
            **changes,
        )

    def test_forward_break_before_make_sequence_validates(self) -> None:
        result = validate_provider_connection_cutover(self.evidence())

        self.assertEqual(result.direction, "forward")
        self.assertEqual(result.source_owner_uid, "onebot-schwab-owner")
        self.assertEqual(result.target_owner_uid, "onejournal-schwab-owner")
        self.assertEqual(
            result.target_owner_epoch_uid,
            "onejournal-owner-epoch-20260829",
        )

    def test_same_contract_validates_break_before_make_rollback(self) -> None:
        evidence = self.evidence(direction="rollback")

        result = validate_provider_connection_cutover(evidence)

        self.assertEqual(result.direction, "rollback")

    def test_dual_owner_and_missing_gap_fail_closed(self) -> None:
        evidence = self.evidence()
        first = evidence.observations[0]
        dual_target = replace(
            self.target_provisioned,
            provider_call_enabled=True,
            token_refresh_enabled=True,
        )
        dual = replace(
            evidence,
            observations=(replace(first, target=dual_target),) + evidence.observations[1:],
        )
        with self.assertRaisesRegex(ProviderConnectionCutoverError, "dual"):
            validate_provider_connection_cutover(dual)

        gap = evidence.observations[1]
        missing_gap = replace(
            evidence,
            observations=(
                evidence.observations[0],
                replace(gap, target=self.target_provisioned),
            ) + evidence.observations[2:],
        )
        with self.assertRaisesRegex(ProviderConnectionCutoverError, "owner_gap"):
            validate_provider_connection_cutover(missing_gap)

    def test_target_cannot_reuse_source_epoch_or_credential_generation(self) -> None:
        evidence = self.evidence()
        reused = replace(
            self.target_provisioned,
            owner_epoch_uid=self.source_active.owner_epoch_uid,
            credential_generation_uid=self.source_active.credential_generation_uid,
        )
        observations = list(evidence.observations)
        observations[2] = replace(observations[2], target=reused)
        observations[3] = replace(
            observations[3],
            target=replace(
                reused,
                provider_call_enabled=True,
                token_refresh_enabled=True,
            ),
        )
        with self.assertRaisesRegex(ProviderConnectionCutoverError, "new owner epoch"):
            validate_provider_connection_cutover(
                replace(evidence, observations=tuple(observations))
            )

    def test_target_cannot_be_preprovisioned_before_owner_gap_completes(self) -> None:
        evidence = self.evidence()
        observations = list(evidence.observations)
        observations[0] = replace(
            observations[0],
            target=replace(
                self.target_absent,
                owner_epoch_uid="premature-target-owner-epoch",
                credential_generation_uid="premature-target-generation",
            ),
        )

        with self.assertRaisesRegex(ProviderConnectionCutoverError, "before the owner_gap"):
            validate_provider_connection_cutover(
                replace(evidence, observations=tuple(observations))
            )

    def test_identity_time_and_phase_order_fail_closed(self) -> None:
        evidence = self.evidence()
        observations = list(evidence.observations)
        observations[2] = replace(
            observations[2],
            target=replace(self.target_provisioned, host_uid="onebot-vps-host"),
        )
        with self.assertRaisesRegex(ProviderConnectionCutoverError, "hosts"):
            validate_provider_connection_cutover(
                replace(evidence, observations=tuple(observations))
            )

        observations = list(evidence.observations)
        observations[2] = replace(
            observations[2], observed_at_utc=observations[1].observed_at_utc
        )
        with self.assertRaisesRegex(ProviderConnectionCutoverError, "strictly ordered"):
            validate_provider_connection_cutover(
                replace(evidence, observations=tuple(observations))
            )

        observations = list(evidence.observations)
        observations[1] = replace(observations[1], phase="target_provisioned_disabled")
        with self.assertRaisesRegex(ProviderConnectionCutoverError, "out of order"):
            validate_provider_connection_cutover(
                replace(evidence, observations=tuple(observations))
            )

    def test_target_isolation_and_capability_invariants_fail_closed(self) -> None:
        with self.assertRaisesRegex(ProviderConnectionCutoverError, "public listener"):
            validate_provider_connection_cutover(
                self.evidence(target_public_listener_enabled=True)
            )
        with self.assertRaisesRegex(ProviderConnectionCutoverError, "journal database"):
            validate_provider_connection_cutover(
                self.evidence(target_journal_database_mounted=True)
            )

        evidence = self.evidence()
        observations = list(evidence.observations)
        observations[0] = replace(
            observations[0],
            source=replace(self.source_active, credential_accessible=False),
        )
        with self.assertRaisesRegex(ProviderConnectionCutoverError, "without credential"):
            validate_provider_connection_cutover(
                replace(evidence, observations=tuple(observations))
            )

    def test_utc_and_evidence_hashes_are_exact(self) -> None:
        evidence = self.evidence()
        observations = list(evidence.observations)
        observations[0] = replace(
            observations[0],
            observed_at_utc=self.started_at.astimezone(timezone(timedelta(hours=8))),
        )
        with self.assertRaisesRegex(ProviderConnectionCutoverError, "expressed in UTC"):
            validate_provider_connection_cutover(
                replace(evidence, observations=tuple(observations))
            )

        observations = list(evidence.observations)
        observations[1] = replace(observations[1], evidence_sha256="1" * 64)
        with self.assertRaisesRegex(ProviderConnectionCutoverError, "unique"):
            validate_provider_connection_cutover(
                replace(evidence, observations=tuple(observations))
            )


if __name__ == "__main__":
    unittest.main()
