from __future__ import annotations

import unittest
import subprocess
import tempfile
from pathlib import Path

from scripts.ci.check_repository import (
    inspect_repository,
    secret_violations,
    tracked_path_violation,
)


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
