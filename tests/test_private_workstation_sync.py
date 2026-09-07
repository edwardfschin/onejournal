from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_ROOT / "scripts/private/sync_onejournal_private_state.py"
SPEC = importlib.util.spec_from_file_location("private_sync", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
private_sync = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = private_sync
SPEC.loader.exec_module(private_sync)


class PrivateWorkstationSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "OneJournal"
        self.root.mkdir(mode=0o700)

    def write_private(self, relative: str, body: bytes) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        for parent in (path.parent, *path.parents):
            if parent == self.root.parent:
                break
            parent.chmod(0o700)
        path.write_bytes(body)
        path.chmod(0o600)
        return path

    def inventory(self):
        return private_sync.inspect_local_vault(
            self.root,
            handle_counter=lambda _path: 0,
        )

    def test_inventory_requires_private_modes_and_rejects_wal(self) -> None:
        self.write_private(private_sync.DATABASE_RELATIVE_PATH, b"db")
        artifact = self.write_private("evidence/run/manifest.json", b"{}")
        first = self.inventory()
        second = self.inventory()
        self.assertEqual(first, second)

        artifact.chmod(0o644)
        with self.assertRaisesRegex(private_sync.PrivateStateSyncError, "0600"):
            self.inventory()
        artifact.chmod(0o600)
        self.write_private(private_sync.DATABASE_RELATIVE_PATH + ".wal", b"wal")
        with self.assertRaisesRegex(private_sync.PrivateStateSyncError, "WAL"):
            self.inventory()

    def test_runtime_cache_and_empty_duckdb_temp_directory_are_excluded(self) -> None:
        self.write_private(private_sync.DATABASE_RELATIVE_PATH, b"db")
        cache = self.root / "evidence" / "__pycache__"
        cache.mkdir(parents=True, mode=0o755)
        (self.root / "evidence").chmod(0o700)
        cached = cache / "helper.pyc"
        cached.write_bytes(b"cache")
        cached.chmod(0o644)
        temporary = self.root / (private_sync.DATABASE_RELATIVE_PATH + ".tmp")
        temporary.mkdir(mode=0o755)

        inventory = self.inventory()
        self.assertNotIn("evidence/__pycache__/helper.pyc", inventory.files)

        transient = temporary / "active-block"
        transient.write_bytes(b"active")
        with self.assertRaisesRegex(private_sync.PrivateStateSyncError, "not empty"):
            self.inventory()

    def test_plan_is_additive_preserves_target_only_and_blocks_conflict(self) -> None:
        record_a = private_sync.FileRecord("a" * 64, 1)
        record_b = private_sync.FileRecord("b" * 64, 1)
        database = private_sync.FileRecord("d" * 64, 10)
        source = private_sync.VaultInventory(
            files={
                private_sync.DATABASE_RELATIVE_PATH: database,
                "shared": record_a,
                "source-only": record_b,
            },
            fingerprint="1" * 64,
        )
        target = private_sync.VaultInventory(
            files={"shared": record_a, "target-only": record_b},
            fingerprint="2" * 64,
        )
        plan = private_sync.build_sync_plan(
            direction="push",
            remote="imac-onejournal",
            source=source,
            target=target,
        )
        self.assertEqual(plan.immutable_additions, ("source-only",))
        self.assertEqual(plan.target_only_files, ("target-only",))
        self.assertEqual(plan.conflicts, ())
        self.assertEqual(
            plan,
            private_sync.build_sync_plan(
                direction="push",
                remote="imac-onejournal",
                source=source,
                target=target,
            ),
        )
        alternate_route = private_sync.build_sync_plan(
            direction="push",
            remote="imac-onejournal",
            source=source,
            target=target,
            ssh_hostname="192.0.2.10",
            host_key_alias="trusted-imac",
        )
        self.assertNotEqual(plan.plan_fingerprint, alternate_route.plan_fingerprint)

        conflict_target = private_sync.VaultInventory(
            files={"shared": record_b}, fingerprint="3" * 64
        )
        conflict = private_sync.build_sync_plan(
            direction="push",
            remote="imac-onejournal",
            source=source,
            target=conflict_target,
        )
        self.assertEqual(conflict.conflicts, ("shared",))
        self.assertEqual(
            private_sync._plan_document(conflict)["status"],
            "blocked_conflict",
        )

    def test_local_database_finalization_is_atomic_and_keeps_backup(self) -> None:
        current = self.write_private(
            private_sync.DATABASE_RELATIVE_PATH,
            b"old-database",
        )
        transfer_id = "a" * 24
        private_sync._acquire_local_lock(self.root, transfer_id)
        self.addCleanup(
            lambda: (
                private_sync._release_local_lock(self.root, transfer_id)
                if (self.root / private_sync.LOCK_DIRECTORY_NAME).exists()
                else None
            )
        )
        incoming = private_sync._prepare_local_incoming(
            self.root,
            transfer_id,
            private_sync._file_sha256(current),
        )
        incoming.write_bytes(b"new-database")
        incoming.chmod(0o600)

        created = private_sync._finalize_local_database(
            self.root,
            transfer_id=transfer_id,
            expected_source_sha=private_sync._file_sha256(incoming),
            expected_target_sha=private_sync._file_sha256(current),
            stamp="20260907T000000Z",
        )
        self.assertTrue(created)
        self.assertEqual(current.read_bytes(), b"new-database")
        backups = list((current.parent / "transfer-backups").glob("*.duckdb"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), b"old-database")
        self.assertEqual(backups[0].stat().st_mode & 0o777, 0o600)

    def test_new_immutable_parents_are_forced_private(self) -> None:
        artifact = self.write_private("evidence/new/run.json", b"{}")
        artifact.parent.chmod(0o755)
        artifact.parent.parent.chmod(0o755)
        transfer_id = "9" * 24
        private_sync._acquire_local_lock(self.root, transfer_id)
        self.addCleanup(
            lambda: (
                private_sync._release_local_lock(self.root, transfer_id)
                if (self.root / private_sync.LOCK_DIRECTORY_NAME).exists()
                else None
            )
        )

        private_sync._secure_local_additions(
            self.root,
            transfer_id,
            ("evidence/new/run.json", "evidence/new/not-yet-copied.json"),
        )

        self.assertEqual(artifact.stat().st_mode & 0o777, 0o600)
        self.assertEqual(artifact.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(artifact.parent.parent.stat().st_mode & 0o777, 0o700)

    def test_lock_owner_and_stale_plan_fail_closed(self) -> None:
        transfer_id = "b" * 24
        private_sync._acquire_local_lock(self.root, transfer_id)
        with self.assertRaisesRegex(private_sync.PrivateStateSyncError, "another"):
            private_sync._validate_lock(
                self.root / private_sync.LOCK_DIRECTORY_NAME,
                "c" * 24,
            )
        private_sync._release_local_lock(self.root, transfer_id)

        with patch.object(private_sync, "_read_endpoints") as endpoints:
            database = private_sync.FileRecord("d" * 64, 10)
            inventory = private_sync.VaultInventory(
                files={private_sync.DATABASE_RELATIVE_PATH: database},
                fingerprint="f" * 64,
            )
            endpoints.return_value = (inventory, inventory)
            with self.assertRaisesRegex(private_sync.PrivateStateSyncError, "stale"):
                private_sync.apply_sync_plan(
                    expected_plan_fingerprint="0" * 64,
                    direction="push",
                    remote="imac-onejournal",
                    local_root=self.root,
                    remote_root=str(self.root),
                )

    def test_remote_inventory_contract_is_checksum_bound(self) -> None:
        files = {"evidence": {"sha256": "a" * 64, "size": 4}}
        document = {
            "files": files,
            "fingerprint": private_sync._digest(files),
        }
        inventory = private_sync._inventory_from_document(document)
        self.assertEqual(inventory.files["evidence"].size, 4)
        tampered = json.loads(json.dumps(document))
        tampered["files"]["evidence"]["size"] = 5
        with self.assertRaisesRegex(private_sync.PrivateStateSyncError, "fingerprint"):
            private_sync._inventory_from_document(tampered)

    def test_database_rsync_endpoints_follow_explicit_direction(self) -> None:
        completed = private_sync.subprocess.CompletedProcess([], 0, "", "")
        with patch.object(private_sync.subprocess, "run", return_value=completed) as run:
            private_sync._rsync(
                direction="push",
                remote="imac-onejournal",
                local_root=self.root,
                remote_root=str(self.root),
                local_file="/local/database",
                remote_file="/remote/incoming",
            )
            command = run.call_args.args[0]
            self.assertIn("--rsync-path=umask 077 && rsync", command)
            self.assertEqual(run.call_args.kwargs["umask"], 0o077)
            self.assertEqual(
                command[-2:],
                ["/local/database", "imac-onejournal:/remote/incoming"],
            )

            private_sync._rsync(
                direction="pull",
                remote="imac-onejournal",
                local_root=self.root,
                remote_root=str(self.root),
                local_file="/local/incoming",
                remote_file="/remote/database",
            )
            command = run.call_args.args[0]
            self.assertEqual(
                command[-2:],
                ["imac-onejournal:/remote/database", "/local/incoming"],
            )

    def test_alternate_route_requires_safe_existing_host_identity(self) -> None:
        with self.assertRaisesRegex(private_sync.PrivateStateSyncError, "requires"):
            private_sync._validate_remote(
                "imac-onejournal",
                "/private/vault",
                host_key_alias="trusted-imac",
            )
        private_sync._validate_remote(
            "imac-onejournal",
            "/private/vault",
            ssh_hostname="192.0.2.10",
            host_key_alias="trusted-imac",
        )
        self.assertEqual(
            private_sync._ssh_options(
                ssh_hostname="192.0.2.10",
                host_key_alias="trusted-imac",
            )[-4:],
            ("-o", "Hostname=192.0.2.10", "-o", "HostKeyAlias=trusted-imac"),
        )

    def test_remote_helper_emits_the_same_private_inventory_contract(self) -> None:
        self.write_private(private_sync.DATABASE_RELATIVE_PATH, b"db")
        self.write_private("evidence/run/manifest.json", b"{}")
        request = {
            "action": "inventory",
            "root": str(self.root),
            "allowed_lock_id": None,
        }
        result = private_sync.subprocess.run(
            [sys.executable, "-c", private_sync.REMOTE_HELPER],
            input=private_sync._canonical_json(request) + "\n",
            check=True,
            capture_output=True,
            text=True,
        )
        remote = private_sync._inventory_from_document(json.loads(result.stdout))
        self.assertEqual(remote, self.inventory())


if __name__ == "__main__":
    unittest.main()
