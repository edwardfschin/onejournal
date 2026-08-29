from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
import ast
import json
import stat
import tempfile
import unittest
from unittest.mock import patch

import yaml

from onejournal.provider_connectors import (
    MACOS_KEYCHAIN_CREDENTIAL_SCHEMA,
    MACOS_KEYCHAIN_SERVICE,
    KeychainCommandResult,
    MacOSFileOwnerLeaseRegistry,
    MacOSKeychainCredentialRecord,
    MacOSKeychainCredentialStore,
    MacOSStagingError,
    SubprocessKeychainCommandRunner,
    load_macos_keychain_credential_record_bytes,
    load_macos_staging_policy,
    macos_keychain_credential_record_bytes,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = PROJECT_ROOT / "config" / "marketdata.yaml"
MODULE_PATH = PROJECT_ROOT / "src/onejournal/provider_connectors/macos_staging.py"


class FakeKeychainRunner:
    def __init__(self) -> None:
        self.items: dict[tuple[str, str], bytes] = {}
        self.calls: list[tuple[tuple[str, ...], bytes | None]] = []

    def run(self, argv: tuple[str, ...], *, stdin: bytes | None) -> KeychainCommandResult:
        self.calls.append((argv, stdin))
        account = argv[argv.index("-a") + 1]
        service = argv[argv.index("-s") + 1]
        key = (account, service)
        if argv[1] == "find-generic-password":
            if key not in self.items:
                return KeychainCommandResult(44, b"", b"not found")
            return KeychainCommandResult(0, self.items[key] + b"\n", b"")
        if argv[1] != "add-generic-password" or stdin is None:
            return KeychainCommandResult(2, b"", b"unsupported")
        update = "-U" in argv
        if key in self.items and not update:
            return KeychainCommandResult(45, b"", b"duplicate")
        if key not in self.items and update:
            return KeychainCommandResult(44, b"", b"not found")
        self.items[key] = stdin.rstrip(b"\n")
        return KeychainCommandResult(0, b"", b"")


class MacOSProviderStagingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 8, 29, 16, 0, tzinfo=UTC)
        self.record = MacOSKeychainCredentialRecord(
            schema=MACOS_KEYCHAIN_CREDENTIAL_SCHEMA,
            provider="schwab",
            connection_uid="local-schwab-primary",
            owner_epoch_uid="onejournal-owner-epoch-20260829",
            generation_uid="onejournal-credential-generation-0001",
            client_id="synthetic-client-id",
            client_secret="synthetic-client-secret",
            access_token="synthetic-access-token",
            refresh_token="synthetic-refresh-token",
            access_token_expires_at_utc=self.now + timedelta(hours=1),
        )
        self.runner = FakeKeychainRunner()
        self.repository_policy = load_macos_staging_policy(POLICY_PATH)
        self.enabled_policy = replace(
            self.repository_policy,
            enabled=True,
            credential_installation_enabled=True,
            provider_calls_enabled=True,
            token_refresh_enabled=True,
        )
        self.store = MacOSKeychainCredentialStore(
            runner=self.runner,
            policy=self.enabled_policy,
        )
        self.temp_dir = tempfile.TemporaryDirectory()
        self.lock_root = Path(self.temp_dir.name) / "locks"
        self.lock_root.mkdir(mode=0o700)
        self.lock_root.chmod(0o700)
        self.leases = MacOSFileOwnerLeaseRegistry(
            lock_root=self.lock_root,
            owner_epoch_uid=self.record.owner_epoch_uid,
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_repository_policy_selects_mac_but_remains_fully_disabled(self) -> None:
        policy = load_macos_staging_policy(POLICY_PATH)

        self.assertEqual(policy.target, "local_macos")
        self.assertEqual(policy.credential_backend, "macos_keychain")
        self.assertFalse(policy.enabled)
        self.assertFalse(policy.credential_installation_enabled)
        self.assertFalse(policy.provider_calls_enabled)
        self.assertFalse(policy.token_refresh_enabled)
        self.assertFalse(policy.public_listener_enabled)
        self.assertFalse(policy.journal_database_mounted)

    def test_policy_rejects_activation_or_isolation_drift(self) -> None:
        document = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))
        cases = (
            ("provider_calls_enabled", True, "while staging is disabled"),
            ("token_refresh_enabled", True, "while staging is disabled"),
            ("credential_installation_enabled", True, "while staging is disabled"),
            ("public_listener_enabled", True, "isolation"),
            ("journal_database_mounted", True, "isolation"),
        )
        for field, value, message in cases:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                changed = json.loads(json.dumps(document))
                changed["marketdata"]["pnl02_t15_staging"][field] = value
                path = Path(directory) / "marketdata.yaml"
                path.write_text(yaml.safe_dump(changed, sort_keys=False), encoding="utf-8")
                with self.assertRaisesRegex(MacOSStagingError, message):
                    load_macos_staging_policy(path)

    def test_repository_policy_blocks_keychain_access_and_mutation(self) -> None:
        disabled_store = MacOSKeychainCredentialStore(
            runner=self.runner,
            policy=self.repository_policy,
        )
        lease = self.leases.acquire(
            provider="schwab", connection_uid=self.record.connection_uid
        )
        credential_use = None
        try:
            with self.assertRaisesRegex(MacOSStagingError, "disabled by staging policy"):
                disabled_store.install_new(owner_lease=lease, record=self.record)
            with self.assertRaisesRegex(MacOSStagingError, "disabled by policy"):
                disabled_store.checkout(
                    provider="schwab",
                    connection_uid=self.record.connection_uid,
                    owner_lease=lease,
                )
            credential_use = self.store.install_new(owner_lease=lease, record=self.record)
        finally:
            self.leases.release(lease)
        self.assertIsNone(credential_use)

        self.assertEqual(len(self.runner.calls), 2)

    def test_secret_record_is_canonical_and_repr_is_redacted(self) -> None:
        body = macos_keychain_credential_record_bytes(self.record)

        self.assertEqual(load_macos_keychain_credential_record_bytes(body), self.record)
        self.assertNotIn(self.record.access_token, repr(self.record))
        self.assertNotIn(self.record.client_secret, repr(self.record))
        reformatted = json.dumps(json.loads(body), indent=2).encode("utf-8")
        with self.assertRaisesRegex(MacOSStagingError, "not canonical"):
            load_macos_keychain_credential_record_bytes(reformatted)

    def test_install_checkout_access_and_rotation_use_stdin_not_argv(self) -> None:
        lease = self.leases.acquire(
            provider="schwab", connection_uid=self.record.connection_uid
        )
        try:
            self.store.install_new(owner_lease=lease, record=self.record)
            credential_use = self.store.checkout(
                provider="schwab",
                connection_uid=self.record.connection_uid,
                owner_lease=lease,
            )
            token = self.store.access_token(
                credential_use,
                evaluated_at_utc=self.now,
            )
            self.assertEqual(token, self.record.access_token)

            rotated = replace(
                self.record,
                generation_uid="onejournal-credential-generation-0002",
                access_token="synthetic-access-token-rotated",
                refresh_token="synthetic-refresh-token-rotated",
            )
            self.store.replace_generation(
                owner_lease=lease,
                expected_generation_uid=self.record.generation_uid,
                record=rotated,
            )
            with self.assertRaisesRegex(MacOSStagingError, "generation changed"):
                self.store.assert_current(credential_use)
        finally:
            self.leases.release(lease)

        flattened_argv = " ".join(part for argv, _ in self.runner.calls for part in argv)
        self.assertNotIn(self.record.access_token, flattened_argv)
        self.assertNotIn(self.record.refresh_token, flattened_argv)
        self.assertNotIn(self.record.client_secret, flattened_argv)
        write_calls = [call for call in self.runner.calls if call[0][1] == "add-generic-password"]
        self.assertEqual(len(write_calls), 2)
        self.assertTrue(all(call[0][-1] == "-w" for call in write_calls))
        self.assertTrue(all(call[1] is not None for call in write_calls))

    def test_overwrite_stale_rotation_expiry_and_owner_mismatch_fail_closed(self) -> None:
        lease = self.leases.acquire(
            provider="schwab", connection_uid=self.record.connection_uid
        )
        try:
            self.store.install_new(owner_lease=lease, record=self.record)
            with self.assertRaisesRegex(MacOSStagingError, "installation failed"):
                self.store.install_new(owner_lease=lease, record=self.record)
            with self.assertRaisesRegex(MacOSStagingError, "stale"):
                self.store.replace_generation(
                    owner_lease=lease,
                    expected_generation_uid="wrong-credential-generation",
                    record=replace(
                        self.record,
                        generation_uid="onejournal-credential-generation-0002",
                    ),
                )
            credential_use = self.store.checkout(
                provider="schwab",
                connection_uid=self.record.connection_uid,
                owner_lease=lease,
            )
            with self.assertRaisesRegex(MacOSStagingError, "reauthentication_required"):
                self.store.access_token(
                    credential_use,
                    evaluated_at_utc=self.record.access_token_expires_at_utc,
                )
        finally:
            self.leases.release(lease)

        wrong_epoch = MacOSFileOwnerLeaseRegistry(
            lock_root=self.lock_root,
            owner_epoch_uid="different-owner-epoch-20260829",
        )
        wrong_lease = wrong_epoch.acquire(
            provider="schwab", connection_uid=self.record.connection_uid
        )
        try:
            with self.assertRaisesRegex(MacOSStagingError, "owner epoch"):
                self.store.checkout(
                    provider="schwab",
                    connection_uid=self.record.connection_uid,
                    owner_lease=wrong_lease,
                )
        finally:
            wrong_epoch.release(wrong_lease)

    def test_cross_process_style_lease_is_exclusive_and_private(self) -> None:
        first = self.leases.acquire(
            provider="schwab", connection_uid=self.record.connection_uid
        )
        other_registry = MacOSFileOwnerLeaseRegistry(
            lock_root=self.lock_root,
            owner_epoch_uid=self.record.owner_epoch_uid,
        )
        try:
            with self.assertRaisesRegex(MacOSStagingError, "lease unavailable"):
                other_registry.acquire(
                    provider="schwab", connection_uid=self.record.connection_uid
                )
            lock_files = list(self.lock_root.iterdir())
            self.assertEqual(len(lock_files), 1)
            self.assertEqual(stat.S_IMODE(lock_files[0].stat().st_mode), 0o600)
        finally:
            self.leases.release(first)

        second = other_registry.acquire(
            provider="schwab", connection_uid=self.record.connection_uid
        )
        other_registry.release(second)

    def test_module_has_no_network_database_listener_or_order_capability(self) -> None:
        module = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        imported = {
            alias.name.split(".")[0]
            for node in ast.walk(module)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        self.assertFalse(
            imported
            & {"duckdb", "sqlite3", "requests", "urllib", "socket", "http", "flask"}
        )
        source = MODULE_PATH.read_text(encoding="utf-8")
        self.assertNotIn("/orders", source)
        self.assertNotIn("/accounts", source)
        self.assertEqual(MACOS_KEYCHAIN_SERVICE, "com.onejournal.provider-credentials")

    def test_concrete_runner_rejects_every_command_outside_exact_allowlist(self) -> None:
        runner = SubprocessKeychainCommandRunner()
        forbidden = (
            "/usr/bin/security",
            "delete-generic-password",
            "-a",
            "schwab:local-schwab-primary",
            "-s",
            MACOS_KEYCHAIN_SERVICE,
            "-w",
        )
        with patch("subprocess.run") as subprocess_run:
            with self.assertRaisesRegex(MacOSStagingError, "unsupported"):
                runner.run(forbidden, stdin=None)
            subprocess_run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
