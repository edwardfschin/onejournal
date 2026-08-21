from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.ci.check_repository import (
    inspect_repository,
    secret_violations,
    tracked_path_violation,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
GIT_IDENTITY_GUARD = PROJECT_ROOT / "bin/onejournal_git_status.sh"


class RepositoryGuardTests(unittest.TestCase):
    def test_allows_safe_source_and_odfs_placeholders(self) -> None:
        safe_paths = [
            "src/onejournal/brokers/base.py",
            "data/journal/reviews/manual_reviews.csv",
            "data/normalized/fills/.gitkeep",
            "docs/onejournal_data_contract_v1.md",
        ]

        for path in safe_paths:
            with self.subTest(path=path):
                self.assertIsNone(tracked_path_violation(path))

    def test_rejects_private_and_runtime_paths(self) -> None:
        rejected_paths = [
            "data/raw/ibkr/2026-07-23/fills.json",
            "data/raw/schwab/2026-07-23/orders.json",
            "data/normalized/fills/2026-07-23_fills.csv",
            "data/journal/onejournal.duckdb",
            "data/journal/onejournal.duckdb.wal",
            "data/journal/backups/onejournal.duckdb",
            "output/dashboard/latest.json",
            ".env",
            ".env.local",
            ".env.production",
            "config/.env.staging",
            "config/private.env",
            "tokens/schwab.json",
            "runtime/access_token.json",
            ".DS_Store",
        ]

        for path in rejected_paths:
            with self.subTest(path=path):
                self.assertIsNotNone(tracked_path_violation(path))

    def test_detects_high_confidence_secret_signatures(self) -> None:
        samples = [
            b"-----BEGIN " + b"PRIVATE KEY-----",
            b"AKIA" + (b"A" * 16),
            b"ghp_" + (b"a" * 36),
            b"xoxb-" + (b"a" * 24),
            b"sk-proj-" + (b"a" * 40),
        ]

        for sample in samples:
            with self.subTest(sample=sample[:12]):
                self.assertTrue(secret_violations(sample))

    def test_does_not_flag_placeholders_or_variable_names(self) -> None:
        safe_content = (
            b"SCHWAB_CLIENT_SECRET=${SCHWAB_CLIENT_SECRET}\n"
            b"Authorization: Bearer ${ACCESS_TOKEN}\n"
            b"example_token=replace-me\n"
        )

        self.assertEqual(secret_violations(safe_content), [])

    def test_inspects_the_tracked_set_in_a_clean_repository(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory)
            raw_file = repository / "data/raw/ibkr/2026-07-23/fills.json"
            secret_file = repository / "safe-looking.txt"
            raw_file.parent.mkdir(parents=True)
            raw_file.write_text("{}\n", encoding="utf-8")
            secret_file.write_bytes(b"AKIA" + (b"A" * 16) + b"\n")

            subprocess.run(
                ["git", "init", "--quiet"],
                cwd=repository,
                check=True,
            )
            subprocess.run(
                ["git", "add", "--force", "."],
                cwd=repository,
                check=True,
            )

            failures = inspect_repository(repository)

        self.assertTrue(
            any("data/raw/ibkr" in failure for failure in failures),
            failures,
        )
        self.assertTrue(
            any("AWS access key" in failure for failure in failures),
            failures,
        )

    def test_gitignore_covers_dot_env_variants(self) -> None:
        for path in (".env", ".env.local", ".env.production", ".env.staging"):
            with self.subTest(path=path):
                result = subprocess.run(
                    ["git", "check-ignore", "--quiet", "--no-index", path],
                    cwd=PROJECT_ROOT,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, path)


class GitIdentityGuardTests(unittest.TestCase):
    def run_guard(self, repository: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(repository / "bin/onejournal_git_status.sh")],
            cwd=repository,
            check=False,
            capture_output=True,
            text=True,
        )

    def create_guarded_repository(self, repository: Path) -> None:
        (repository / "bin").mkdir(parents=True)
        shutil.copy2(GIT_IDENTITY_GUARD, repository / "bin/onejournal_git_status.sh")
        subprocess.run(["git", "init", "--quiet"], cwd=repository, check=True)

    def test_canonical_repository_passes(self) -> None:
        result = self.run_guard(PROJECT_ROOT)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(f"PROJECT_DIR={PROJECT_ROOT}", result.stdout)
        self.assertIn("ONEJOURNAL_GIT_GUARD=PASS", result.stdout)

    def test_checkout_folder_name_does_not_define_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory) / "RenamedCheckout"
            self.create_guarded_repository(repository)

            result = self.run_guard(repository)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("ONEJOURNAL_GIT_GUARD=PASS", result.stdout)

    def test_rejects_script_below_a_different_git_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            git_root = Path(temporary_directory)
            subprocess.run(["git", "init", "--quiet"], cwd=git_root, check=True)
            repository = git_root / "nested" / "OneJournal"
            (repository / "bin").mkdir(parents=True)
            shutil.copy2(
                GIT_IDENTITY_GUARD,
                repository / "bin/onejournal_git_status.sh",
            )

            result = self.run_guard(repository)

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("FAIL git top-level mismatch", result.stdout)
