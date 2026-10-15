"""One synthetic capture through private staging and copy-only position append."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from onejournal.api.broker_current_position_contracts import (
    BROKER_CURRENT_FINANCIAL_RELEASE_AUTHORIZATION_VERSION,
    BrokerCurrentFinancialReleaseAuthorization,
)
from onejournal.brokers.schwab.position_binding import schwab_position_private_binding_bytes
from onejournal.journal.broker_current_position_valuation_repository import (
    calculate_broker_current_position_result_fingerprint,
    persist_broker_current_position_valuation_run,
)
from onejournal.journal.migrations import apply_schema_migrations
from onejournal.manual_capture_upload import ManualCaptureIntake
from onejournal.pnl.broker_current_position_valuation import build_broker_current_position_valuation
from onejournal.provider_connectors.external_acquisition import (
    convert_external_schwab_positions, external_provider_acquisition_manifest_bytes,
)
from onejournal.refresh_capture_authorization import AUTHORIZATION_VERSION
from onejournal.staged_position_rehearsal import rehearse_staged_position
import test_external_schwab_position_acquisition as fixture_module


class StagedPositionRehearsalTests(unittest.TestCase):
    def test_exact_capture_appends_on_copy_and_stale_capture_holds(self):
        fixture = fixture_module.ExternalSchwabPositionAcquisitionTests()
        fixture.setUp()
        incomplete_body = fixture.body
        document = json.loads(fixture.body)
        document["securitiesAccount"]["positions"][0]["taxLotAverageLongPrice"] = 190.25
        fixture.body = (json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n").encode()
        fixture.request = replace(
            fixture.request, response_byte_count=len(fixture.body),
            response_sha256=sha256(fixture.body).hexdigest(),
        )
        fixture.manifest = fixture.make_manifest()
        binding = fixture.private_binding()
        current = convert_external_schwab_positions(
            fixture.load(), provider_account_hash=binding.provider_account_hash,
            provider_account_number=binding.provider_account_number,
            source_account_id=binding.source_account_id, mappings=binding.mappings,
        ).snapshot
        previous_snapshot = replace(
            current, snapshot_uid="broker-position-snapshot:" + "0" * 64,
            retrieved_at=current.retrieved_at - timedelta(minutes=1),
            provider_observed_at=None,
        )
        prior_run = build_broker_current_position_valuation(
            broker_snapshot=previous_snapshot,
            evaluated_at=previous_snapshot.retrieved_at,
            max_snapshot_age_seconds=120,
            currency_quantum_by_currency={"USD": Decimal("0.01")},
        )
        authorization = BrokerCurrentFinancialReleaseAuthorization(
            contract_version=BROKER_CURRENT_FINANCIAL_RELEASE_AUTHORIZATION_VERSION,
            owner_acceptance_uid="synthetic-accepted-position-0001",
            valuation_run_uid=prior_run.run_uid,
            result_fingerprint=calculate_broker_current_position_result_fingerprint(prior_run),
            accepted_at=prior_run.evaluated_at + timedelta(seconds=1), decision="accepted",
        )
        with tempfile.TemporaryDirectory() as directory:
            private = Path(directory)
            db = private / "journal.duckdb"
            apply_schema_migrations(db)
            persist_broker_current_position_valuation_run(
                db, run=prior_run, broker_snapshot=previous_snapshot
            )
            db.chmod(0o600)
            staging = private / "staging"
            staging.mkdir(mode=0o700)
            manifest = external_provider_acquisition_manifest_bytes(fixture.manifest)
            digest = sha256(manifest).hexdigest()
            paths = dict(
                authorization=private / "capture-authorization.json",
                acknowledgement=private / "acknowledgement.json",
                binding=private / "position-binding.json",
            )
            def write(path, body):
                path.write_bytes(body)
                path.chmod(0o600)
            write(paths["authorization"], json.dumps(dict(
                contract_version=AUTHORIZATION_VERSION,
                capture_scope="current_positions", manifest_sha256=digest,
                acquisition_run_uid=fixture.manifest.acquisition_run_uid,
                acquisition_approval_id=fixture_module.APPROVAL_ID,
                owner_uid=fixture_module.OWNER_UID,
                owner_epoch_uid=fixture_module.OWNER_EPOCH_UID,
            )).encode())
            write(paths["acknowledgement"], fixture.acknowledgement_bytes)
            write(paths["binding"], schwab_position_private_binding_bytes(binding))
            intake = ManualCaptureIntake(
                authorization_path=paths["authorization"],
                acknowledgement_path=paths["acknowledgement"],
                account_binding_path=paths["binding"],
                usage_policy=fixture.usage_policy,
                staging_root=staging,
                project_root=Path(__file__).resolve().parents[1],
            )
            with patch("socket.socket.connect", side_effect=AssertionError("Network forbidden")):
                intake.stage({"acquisition-manifest.json": manifest, "positions.json": fixture.body})
                before = db.read_bytes()
                result = rehearse_staged_position(
                    intake=intake, manifest_sha256=digest, source_db=db,
                    current_authorization=authorization,
                    evaluated_at=fixture.completed_at + timedelta(seconds=1),
                )
                self.assertEqual(result["status"], "copy_position_ready")
                self.assertEqual(result["position_count"], 1)
                self.assertFalse(result["live_journal_written"])
                self.assertFalse(result["financial_publication_authorized"])
                self.assertEqual(db.read_bytes(), before)
                fixture.body = incomplete_body
                fixture.request = replace(
                    fixture.request, response_byte_count=len(incomplete_body),
                    response_sha256=sha256(incomplete_body).hexdigest(),
                )
                fixture.manifest = fixture.make_manifest()
                incomplete_manifest = external_provider_acquisition_manifest_bytes(fixture.manifest)
                incomplete_digest = sha256(incomplete_manifest).hexdigest()
                write(paths["authorization"], json.dumps(dict(
                    contract_version=AUTHORIZATION_VERSION,
                    capture_scope="current_positions", manifest_sha256=incomplete_digest,
                    acquisition_run_uid=fixture.manifest.acquisition_run_uid,
                    acquisition_approval_id=fixture_module.APPROVAL_ID,
                    owner_uid=fixture_module.OWNER_UID,
                    owner_epoch_uid=fixture_module.OWNER_EPOCH_UID,
                )).encode())
                intake.stage({"acquisition-manifest.json": incomplete_manifest,
                              "positions.json": incomplete_body})
                held = rehearse_staged_position(
                    intake=intake, manifest_sha256=incomplete_digest, source_db=db,
                    current_authorization=authorization,
                    evaluated_at=fixture.completed_at + timedelta(seconds=1),
                )
                self.assertEqual(held["status"], "held_for_financial_review")
                self.assertFalse(held["financial_publication_authorized"])
                self.assertEqual(db.read_bytes(), before)
                with self.assertRaises(ValueError):
                    rehearse_staged_position(
                        intake=intake, manifest_sha256=incomplete_digest, source_db=db,
                        current_authorization=authorization,
                        evaluated_at=fixture.completed_at + timedelta(days=1),
                    )
                self.assertEqual(db.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
