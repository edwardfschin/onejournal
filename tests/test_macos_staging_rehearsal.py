from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import yaml

from onejournal.provider_connectors.macos_staging_rehearsal import (
    MACOS_STAGING_REHEARSAL_CONTRACT_VERSION,
    MacOSStagingRehearsalError,
    macos_staging_rehearsal_bytes,
    run_macos_provider_staging_rehearsal,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = PROJECT_ROOT / "config" / "marketdata.yaml"
SCRIPT_PATH = PROJECT_ROOT / "scripts/journal/rehearse_macos_provider_staging.py"
SPEC = importlib.util.spec_from_file_location("onejournal_macos_staging_rehearsal", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
script = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = script
SPEC.loader.exec_module(script)

COMMIT = "4203cf624f242df870a7271183fb57f0f615bd21"
HOST_UID = "macos-t15-staging-host-20260829"
OBSERVED = datetime(2026, 8, 29, 17, 0, tzinfo=UTC)


class MacOSStagingRehearsalTests(unittest.TestCase):
    def test_disabled_policy_produces_canonical_secret_free_result(self) -> None:
        result = run_macos_provider_staging_rehearsal(
            policy_path=POLICY_PATH,
            artifact_commit=COMMIT,
            host_uid=HOST_UID,
            observed_at_utc=OBSERVED,
        )

        self.assertEqual(result.contract_version, MACOS_STAGING_REHEARSAL_CONTRACT_VERSION)
        self.assertEqual(result.final_status, "provider_disabled_rehearsal_passed")
        self.assertFalse(result.keychain_accessed)
        self.assertFalse(result.provider_calls_enabled)
        self.assertFalse(result.journal_database_mounted)
        body = macos_staging_rehearsal_bytes(result)
        self.assertEqual(body, macos_staging_rehearsal_bytes(result))
        self.assertNotIn(b"access_token", body)
        self.assertEqual(json.loads(body)["host_uid"], HOST_UID)

    def test_enabled_or_invalid_policy_fails_before_result(self) -> None:
        document = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "marketdata.yaml"
            document["marketdata"]["pnl02_t15_staging"]["enabled"] = True
            path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
            with self.assertRaisesRegex(
                MacOSStagingRehearsalError, "provider-disabled rehearsal"
            ):
                run_macos_provider_staging_rehearsal(
                    policy_path=path,
                    artifact_commit=COMMIT,
                    host_uid=HOST_UID,
                    observed_at_utc=OBSERVED,
                )

    def test_result_rejects_enabled_capability_or_invalid_identity(self) -> None:
        result = run_macos_provider_staging_rehearsal(
            policy_path=POLICY_PATH,
            artifact_commit=COMMIT,
            host_uid=HOST_UID,
            observed_at_utc=OBSERVED,
        )
        with self.assertRaisesRegex(MacOSStagingRehearsalError, "enabled capability"):
            macos_staging_rehearsal_bytes(replace(result, provider_calls_enabled=True))
        with self.assertRaisesRegex(MacOSStagingRehearsalError, "full lowercase"):
            run_macos_provider_staging_rehearsal(
                policy_path=POLICY_PATH,
                artifact_commit="not-a-commit",
                host_uid=HOST_UID,
                observed_at_utc=OBSERVED,
            )

    def test_cli_resolves_only_a_clean_local_git_artifact(self) -> None:
        completed = (
            subprocess.CompletedProcess(("git", "rev-parse", "HEAD"), 0, COMMIT + "\n", ""),
            subprocess.CompletedProcess(("git", "status"), 0, "", ""),
        )
        with patch("subprocess.run", side_effect=completed) as run:
            self.assertEqual(script.current_clean_artifact_commit(PROJECT_ROOT), COMMIT)
        self.assertEqual(
            [call.args[0] for call in run.call_args_list],
            [
                ("git", "rev-parse", "HEAD"),
                ("git", "status", "--porcelain", "--untracked-files=all"),
            ],
        )

        dirty = (
            subprocess.CompletedProcess(("git", "rev-parse", "HEAD"), 0, COMMIT + "\n", ""),
            subprocess.CompletedProcess(("git", "status"), 0, " M config/marketdata.yaml\n", ""),
        )
        with patch("subprocess.run", side_effect=dirty):
            with self.assertRaisesRegex(MacOSStagingRehearsalError, "not clean"):
                script.current_clean_artifact_commit(PROJECT_ROOT)

    def test_script_has_no_keychain_network_database_listener_or_write_import(self) -> None:
        source = SCRIPT_PATH.read_text(encoding="utf-8")
        for forbidden in (
            "requests",
            "urllib",
            "socket",
            "duckdb",
            "sqlite3",
            "security ",
            "write_text",
            "write_bytes",
        ):
            self.assertNotIn(forbidden, source)
        self.assertIn("(\"git\", \"rev-parse\", \"HEAD\")", source)
        self.assertIn("(\"git\", \"status\", \"--porcelain", source)


if __name__ == "__main__":
    unittest.main()
