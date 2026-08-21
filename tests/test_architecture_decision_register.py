from __future__ import annotations

import re
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DECISIONS_DIR = REPOSITORY_ROOT / "docs" / "architecture" / "decisions"
REGISTER_PATH = REPOSITORY_ROOT / "docs" / "architecture" / "README.md"

STATUS_LINE = re.compile(r"^- Status: (.+)$", re.MULTILINE)
REGISTER_ROW = re.compile(
    r"^\| \[ADR-(\d{4})\]\(decisions/([^)]+\.md)\) \| ([^|]+?) \|",
    re.MULTILINE,
)
SIMPLE_STATUSES = {"Proposed", "Accepted", "Rejected", "Deprecated"}
SUPERSEDED_STATUS = re.compile(r"^Superseded by ADR-\d{4}$")


def _decision_files() -> list[Path]:
    return sorted(
        path
        for path in DECISIONS_DIR.glob("[0-9][0-9][0-9][0-9]-*.md")
        if not path.name.startswith("0000-")
    )


def _file_status(path: Path) -> str:
    match = STATUS_LINE.search(path.read_text(encoding="utf-8"))
    if match is None:
        raise AssertionError(f"missing ADR status line: {path.relative_to(REPOSITORY_ROOT)}")
    return match.group(1).strip()


class ArchitectureDecisionRegisterTests(unittest.TestCase):
    def test_adr_files_use_supported_statuses(self) -> None:
        for path in _decision_files():
            with self.subTest(path=path.name):
                status = _file_status(path)
                self.assertTrue(
                    status in SIMPLE_STATUSES or SUPERSEDED_STATUS.fullmatch(status),
                    f"unsupported ADR status {status!r} in {path.name}",
                )

    def test_register_has_each_adr_once_with_matching_status(self) -> None:
        rows = REGISTER_ROW.findall(REGISTER_PATH.read_text(encoding="utf-8"))
        register: dict[str, str] = {}
        for number, filename, status in rows:
            self.assertTrue(
                filename.startswith(f"{number}-"),
                f"ADR-{number} register link points to {filename}",
            )
            self.assertNotIn(filename, register, f"duplicate ADR register row: {filename}")
            register[filename] = status.strip()

        files = {path.name: _file_status(path) for path in _decision_files()}
        self.assertEqual(set(register), set(files))
        for filename, file_status in files.items():
            with self.subTest(path=filename):
                self.assertEqual(register[filename], file_status)


if __name__ == "__main__":
    unittest.main()
