import base64
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest
from dataclasses import replace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from onejournal.brokers.schwab.position_binding import schwab_position_private_binding_bytes
from onejournal.manual_capture_upload import ManualCaptureIntake, register_manual_capture_routes
from onejournal.provider_connectors.external_acquisition import external_provider_acquisition_manifest_bytes
from onejournal.refresh_capture_authorization import AUTHORIZATION_VERSION
import test_external_schwab_position_acquisition as fixture_module
import test_external_schwab_lifecycle_acquisition as lifecycle_fixture_module


class ManualCaptureUploadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.project = root / "checkout"
        self.project.mkdir()
        private = root / "private"
        private.mkdir(mode=0o700)
        self.staging = private / "staging"
        self.staging.mkdir(mode=0o700)
        self.authority = private / "capture-authorization.json"
        self.ack = private / "acknowledgement.json"
        self.binding = private / "account-binding.json"
        self.fixture = fixture_module.ExternalSchwabPositionAcquisitionTests()
        self.fixture.setUp()
        manifest = external_provider_acquisition_manifest_bytes(self.fixture.manifest)
        self.files = {"acquisition-manifest.json": manifest, "positions.json": self.fixture.body}
        self.digest = sha256(manifest).hexdigest()
        self.authority.write_text(json.dumps({
            "contract_version": AUTHORIZATION_VERSION,
            "capture_scope": "current_positions",
            "manifest_sha256": self.digest,
            "acquisition_run_uid": self.fixture.manifest.acquisition_run_uid,
            "acquisition_approval_id": fixture_module.APPROVAL_ID,
            "owner_uid": fixture_module.OWNER_UID,
            "owner_epoch_uid": fixture_module.OWNER_EPOCH_UID,
        }), encoding="utf-8")
        self.authority.chmod(0o600)
        self.ack.write_bytes(self.fixture.acknowledgement_bytes)
        self.ack.chmod(0o600)
        self.binding.write_bytes(schwab_position_private_binding_bytes(self.fixture.private_binding()))
        self.binding.chmod(0o600)
        self.intake = ManualCaptureIntake(
            authorization_path=self.authority, acknowledgement_path=self.ack,
            account_binding_path=self.binding,
            usage_policy=self.fixture.usage_policy, staging_root=self.staging,
            project_root=self.project,
        )
        self.app = FastAPI()
        register_manual_capture_routes(self.app, self.intake)
        self.client = TestClient(self.app)

    def payload(self, files=None):
        return {"files": [
            {"name": name, "content_base64": base64.b64encode(body).decode("ascii")}
            for name, body in (files or self.files).items()
        ]}

    def test_protected_exact_upload_stages_once_and_replays_without_a_journal(self):
        self.assertFalse(self.client.get("/api/v1/local-owner/manual-capture").json()["enabled"])
        self.assertEqual(self.client.post("/api/v1/local-owner/manual-capture", json=self.payload()).status_code, 403)
        self.app.state.passkey_access = object()
        self.assertTrue(self.client.get("/api/v1/local-owner/manual-capture").json()["enabled"])
        first = self.client.post("/api/v1/local-owner/manual-capture", json=self.payload())
        self.assertEqual(first.status_code, 202)
        self.assertFalse(first.json()["journal_written"])
        self.assertFalse(first.json()["financial_publication_authorized"])
        self.assertFalse(first.json()["replayed"])
        staged = self.staging / self.digest
        self.assertEqual({p.name: p.read_bytes() for p in staged.iterdir()}, self.files)
        self.assertEqual(staged.stat().st_mode & 0o777, 0o700)
        self.assertTrue(all((p.stat().st_mode & 0o777) == 0o600 for p in staged.iterdir()))
        second = self.client.post("/api/v1/local-owner/manual-capture", json=self.payload())
        self.assertEqual(second.status_code, 202)
        self.assertTrue(second.json()["replayed"])
        self.assertEqual([p.name for p in self.staging.iterdir()], [self.digest])

    def test_changed_or_unapproved_package_cannot_stage(self):
        self.app.state.passkey_access = object()
        changed = {**self.files, "positions.json": b"{}"}
        self.assertEqual(self.client.post("/api/v1/local-owner/manual-capture", json=self.payload(changed)).status_code, 422)
        self.assertEqual(list(self.staging.iterdir()), [])
        with_approval = {**self.files, "capture-authorization.json": self.authority.read_bytes()}
        self.assertEqual(self.client.post("/api/v1/local-owner/manual-capture", json=self.payload(with_approval)).status_code, 422)
        self.assertEqual(list(self.staging.iterdir()), [])

    def test_wrong_private_account_binding_cannot_stage(self):
        self.app.state.passkey_access = object()
        wrong = replace(self.fixture.private_binding(), provider_account_number="WRONG-ACCOUNT")
        self.binding.write_bytes(schwab_position_private_binding_bytes(wrong))
        self.assertEqual(self.client.post("/api/v1/local-owner/manual-capture", json=self.payload()).status_code, 422)
        self.assertEqual(list(self.staging.iterdir()), [])

    def test_exact_activity_pair_is_staged_without_financial_publication(self):
        lifecycle = lifecycle_fixture_module.ExternalSchwabLifecycleAcquisitionTests()
        lifecycle.setUp()
        manifest = external_provider_acquisition_manifest_bytes(lifecycle.manifest)
        files = {"acquisition-manifest.json": manifest,
                 "orders.json": lifecycle.order_body,
                 "transactions.json": lifecycle.transaction_body}
        self.ack.write_bytes(lifecycle.acknowledgement_bytes)
        document = json.loads(self.authority.read_text(encoding="utf-8"))
        document.update(capture_scope="activity", manifest_sha256=sha256(manifest).hexdigest(),
                        acquisition_run_uid=lifecycle.manifest.acquisition_run_uid,
                        acquisition_approval_id=lifecycle_fixture_module.APPROVAL_ID)
        self.authority.write_text(json.dumps(document), encoding="utf-8")
        intake = ManualCaptureIntake(
            authorization_path=self.authority, acknowledgement_path=self.ack,
            account_binding_path=self.binding, usage_policy=lifecycle.usage_policy,
            staging_root=self.staging, project_root=self.project,
        )
        receipt = intake.stage(files)
        self.assertEqual(receipt["scope"], "activity")
        self.assertFalse(receipt["journal_written"])
        self.assertEqual({p.name: p.read_bytes() for p in (self.staging / receipt["manifest_sha256"]).iterdir()}, files)

    def test_malformed_or_oversized_request_stops_before_stage(self):
        self.app.state.passkey_access = object()
        self.assertEqual(self.client.post("/api/v1/local-owner/manual-capture", json={"files": []}).status_code, 422)
        self.assertEqual(self.client.post("/api/v1/local-owner/manual-capture", content=b"x" * (12 * 1024 * 1024 + 1),
                                          headers={"content-type": "application/json"}).status_code, 413)
        self.assertEqual(list(self.staging.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
