from dataclasses import replace
from datetime import timedelta
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest

from onejournal.provider_connectors.external_acquisition import (
    external_provider_acquisition_manifest_bytes,
)
from onejournal.refresh_capture_authorization import (
    AUTHORIZATION_VERSION,
    ManualRefreshAuthorizationError,
    load_private_capture_authorization,
    verify_authorized_capture,
)
import test_external_schwab_position_acquisition as fixture_module


class ManualCaptureAuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.checkout = self.root / "checkout"
        self.checkout.mkdir()
        self.private = self.root / "private"
        self.private.mkdir(mode=0o700)
        self.record = self.private / "capture-authorization.json"
        self.fixture = fixture_module.ExternalSchwabPositionAcquisitionTests()
        self.fixture.setUp()
        self.manifest = external_provider_acquisition_manifest_bytes(self.fixture.manifest)
        self.files = {"acquisition-manifest.json": self.manifest, "positions.json": self.fixture.body}
        self.document = {
            "contract_version": AUTHORIZATION_VERSION,
            "capture_scope": "current_positions",
            "manifest_sha256": sha256(self.manifest).hexdigest(),
            "acquisition_run_uid": self.fixture.manifest.acquisition_run_uid,
            "acquisition_approval_id": fixture_module.APPROVAL_ID,
            "owner_uid": fixture_module.OWNER_UID,
            "owner_epoch_uid": fixture_module.OWNER_EPOCH_UID,
        }
        self.save()

    def save(self):
        self.record.write_text(json.dumps(self.document), encoding="utf-8")
        self.record.chmod(0o600)

    def authority(self):
        return load_private_capture_authorization(self.record, project_root=self.checkout)

    def verify(self, **changes):
        args = dict(
            authorization=self.authority(),
            acknowledgement_bytes=self.fixture.acknowledgement_bytes,
            usage_policy=self.fixture.usage_policy,
            evaluated_at_utc=self.fixture.completed_at + timedelta(seconds=1),
        )
        args.update(changes)
        return verify_authorized_capture(self.files, **args)

    def test_exact_private_record_authorizes_only_its_verified_package(self):
        checked = self.verify()
        self.assertEqual(checked.manifest_sha256, self.document["manifest_sha256"])
        self.assertEqual(checked.response_bytes["positions.json"], self.fixture.body)
        changed_body = self.fixture.body + b" "
        with self.assertRaises(ManualRefreshAuthorizationError):
            verify_authorized_capture(
                {**self.files, "positions.json": changed_body},
                authorization=self.authority(),
                acknowledgement_bytes=self.fixture.acknowledgement_bytes,
                usage_policy=self.fixture.usage_policy,
                evaluated_at_utc=self.fixture.completed_at + timedelta(seconds=1),
            )
        changed_manifest = external_provider_acquisition_manifest_bytes(
            replace(self.fixture.manifest, acquisition_run_uid="different-run-0001")
        )
        with self.assertRaisesRegex(ManualRefreshAuthorizationError, "differs"):
            verify_authorized_capture(
                {**self.files, "acquisition-manifest.json": changed_manifest},
                authorization=self.authority(),
                acknowledgement_bytes=self.fixture.acknowledgement_bytes,
                usage_policy=self.fixture.usage_policy,
                evaluated_at_utc=self.fixture.completed_at + timedelta(seconds=1),
            )

    def test_private_record_cannot_be_uploaded_or_placed_in_checkout(self):
        self.record.chmod(0o644)
        with self.assertRaises(ValueError):
            self.authority()
        self.record.chmod(0o600)
        copied = self.checkout / "capture-authorization.json"
        copied.write_bytes(self.record.read_bytes())
        copied.chmod(0o600)
        with self.assertRaisesRegex(ManualRefreshAuthorizationError, "outside"):
            load_private_capture_authorization(copied, project_root=self.checkout)
        self.files["capture-authorization.json"] = self.record.read_bytes()
        with self.assertRaisesRegex(ManualRefreshAuthorizationError, "count"):
            self.verify()

    def test_self_consistent_but_unapproved_manifest_is_rejected(self):
        self.document["manifest_sha256"] = "0" * 64
        self.save()
        with self.assertRaisesRegex(ManualRefreshAuthorizationError, "differs"):
            self.verify()
        self.document["manifest_sha256"] = sha256(self.manifest).hexdigest()
        self.document["owner_uid"] = "another-owner-0001"
        self.save()
        with self.assertRaisesRegex(ManualRefreshAuthorizationError, "validation failed"):
            self.verify()
        self.document["owner_uid"] = fixture_module.OWNER_UID
        self.document["capture_scope"] = "activity"
        self.save()
        with self.assertRaises(ManualRefreshAuthorizationError):
            self.verify()


if __name__ == "__main__":
    unittest.main()
