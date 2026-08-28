from __future__ import annotations

from datetime import timedelta
from pathlib import Path
import json
import os
import stat
import tempfile
import unittest

from onejournal.provider_connectors import (
    LocalProviderUsageAcknowledgementStore,
    ProviderUsageAcknowledgementStoreError,
    generate_provider_connection_uid,
    load_provider_usage_policy,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = PROJECT_ROOT / "config" / "marketdata.yaml"
CONNECTION_UID = "connection:schwab:0123456789abcdef0123456789abcdef"


class ProviderUsageAcknowledgementStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = load_provider_usage_policy(POLICY_PATH)
        self.profile = self.policy.active_profiles["schwab"]
        self.accepted_at = self.profile.reviewed_at_utc + timedelta(minutes=1)
        self.evaluated_at = self.accepted_at + timedelta(seconds=1)
        self.temp = tempfile.TemporaryDirectory()
        self.private_root = Path(self.temp.name).resolve() / "private"
        self.private_root.mkdir(mode=0o700)
        os.chmod(self.private_root, 0o700)
        self.store = LocalProviderUsageAcknowledgementStore(
            private_root=self.private_root,
            connection_uid_factory=lambda provider: CONNECTION_UID,
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def create(self):
        return self.store.create(
            policy=self.policy,
            provider="schwab",
            creation_approval_id="PNL-02-T14-TERMS-APPROVAL-0001",
            accepted_at_utc=self.accepted_at,
            evaluated_at_utc=self.evaluated_at,
            product_version="onejournal-0.1.0",
            declarations=self.profile.required_declarations,
        )

    def test_create_and_load_are_private_canonical_and_connection_bound(self) -> None:
        stored = self.create()

        self.assertEqual(stored.authorization.connection_uid, CONNECTION_UID)
        self.assertEqual(
            stored.artifact.acknowledgement.acknowledgement_uid,
            stored.authorization.acknowledgement_uid,
        )
        self.assertEqual(stat.S_IMODE(stored.path.stat().st_mode), 0o600)
        for directory in stored.path.parents:
            if directory == self.private_root.parent:
                break
            self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o700)
        document = json.loads(stored.path.read_text(encoding="utf-8"))
        self.assertEqual(
            document["creation_approval_id"],
            "PNL-02-T14-TERMS-APPROVAL-0001",
        )
        self.assertEqual(
            document["acknowledgement"]["connection_uid"], CONNECTION_UID
        )
        self.assertEqual(
            set(document["acknowledgement"]["declarations"]),
            self.profile.required_declarations,
        )

        loaded = self.store.load(
            path=stored.path,
            policy=self.policy,
            expected_provider="schwab",
            expected_connection_uid=CONNECTION_UID,
            evaluated_at_utc=self.evaluated_at,
            expected_sha256=stored.sha256,
        )
        self.assertEqual(loaded, stored)

    def test_missing_declaration_unsafe_root_and_overwrite_fail_closed(self) -> None:
        with self.assertRaisesRegex(
            ProviderUsageAcknowledgementStoreError, "complete owner-approved"
        ):
            self.store.create(
                policy=self.policy,
                provider="schwab",
                creation_approval_id="PNL-02-T14-TERMS-APPROVAL-0001",
                accepted_at_utc=self.accepted_at,
                evaluated_at_utc=self.evaluated_at,
                product_version="onejournal-0.1.0",
                declarations=self.profile.required_declarations
                - {"authenticated_provider_terms_reviewed"},
            )

        self.create()
        with self.assertRaisesRegex(
            ProviderUsageAcknowledgementStoreError, "overwrite refused"
        ):
            self.create()

        unsafe_root = self.private_root.parent / "unsafe"
        unsafe_root.mkdir(mode=0o755)
        os.chmod(unsafe_root, 0o755)
        unsafe_store = LocalProviderUsageAcknowledgementStore(
            private_root=unsafe_root
        )
        with self.assertRaisesRegex(
            ProviderUsageAcknowledgementStoreError, "mode 0700"
        ):
            unsafe_store.create(
                policy=self.policy,
                provider="schwab",
                creation_approval_id="PNL-02-T14-TERMS-APPROVAL-0001",
                accepted_at_utc=self.accepted_at,
                evaluated_at_utc=self.evaluated_at,
                product_version="onejournal-0.1.0",
                declarations=self.profile.required_declarations,
            )

    def test_checksum_tamper_and_connection_mismatch_fail_closed(self) -> None:
        stored = self.create()
        body = stored.path.read_bytes()
        stored.path.write_bytes(
            body.replace(b"personal_noncommercial", b"hosted_multi_user")
        )
        os.chmod(stored.path, 0o600)

        with self.assertRaisesRegex(
            ProviderUsageAcknowledgementStoreError, "invalid"
        ):
            self.store.load(
                path=stored.path,
                policy=self.policy,
                expected_provider="schwab",
                expected_connection_uid=CONNECTION_UID,
                evaluated_at_utc=self.evaluated_at,
                expected_sha256=stored.sha256,
            )

        other_root = self.private_root.parent / "other-private"
        other_root.mkdir(mode=0o700)
        os.chmod(other_root, 0o700)
        other_store = LocalProviderUsageAcknowledgementStore(
            private_root=other_root,
            connection_uid_factory=lambda provider: CONNECTION_UID,
        )
        other = other_store.create(
            policy=self.policy,
            provider="schwab",
            creation_approval_id="PNL-02-T14-TERMS-APPROVAL-0002",
            accepted_at_utc=self.accepted_at,
            evaluated_at_utc=self.evaluated_at,
            product_version="onejournal-0.1.0",
            declarations=self.profile.required_declarations,
        )
        with self.assertRaisesRegex(
            ProviderUsageAcknowledgementStoreError, "invalid"
        ):
            other_store.load(
                path=other.path,
                policy=self.policy,
                expected_provider="schwab",
                expected_connection_uid=(
                    "connection:schwab:ffffffffffffffffffffffffffffffff"
                ),
                evaluated_at_utc=self.evaluated_at,
                expected_sha256=other.sha256,
            )

    def test_load_rejects_valid_bytes_outside_the_canonical_path(self) -> None:
        stored = self.create()
        misplaced = self.private_root / "misplaced-acknowledgement.json"
        misplaced.write_bytes(stored.path.read_bytes())
        os.chmod(misplaced, 0o600)

        with self.assertRaisesRegex(
            ProviderUsageAcknowledgementStoreError, "canonical path"
        ):
            self.store.load(
                path=misplaced,
                policy=self.policy,
                expected_provider="schwab",
                expected_connection_uid=CONNECTION_UID,
                evaluated_at_utc=self.evaluated_at,
                expected_sha256=stored.sha256,
            )

    def test_generated_connection_uid_has_provider_scope_and_128_bit_payload(self) -> None:
        generated = generate_provider_connection_uid("schwab")
        prefix, provider, random_hex = generated.split(":")
        self.assertEqual(prefix, "connection")
        self.assertEqual(provider, "schwab")
        self.assertEqual(len(random_hex), 32)
        int(random_hex, 16)


if __name__ == "__main__":
    unittest.main()
