from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_DIR / "scripts" / "liv" / "validate_readiness.py"
SPEC = importlib.util.spec_from_file_location("validate_liv_readiness", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
validator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validator)


class LivReadinessValidatorTests(unittest.TestCase):
    def make_markdown(self, header: str, rows: list[str]) -> str:
        text = [
            header,
            "|---|---|---|---|---|---|",
            *rows,
            "",
        ]
        tmp = tempfile.NamedTemporaryFile("w", suffix=".md", delete=False)
        with tmp as fh:
            fh.write("\n".join(text))
        return tmp.name

    def make_artifacts(
        self,
        *,
        checklist_rows: list[str],
        evidence_rows: list[str],
    ) -> tuple[str, str]:
        checklist_path = self.make_markdown(
            "| Date (UTC) | LIV item | Evidence artifact | Status | Owner | Notes |",
            checklist_rows,
        )
        evidence_path = self.make_markdown(
            "| Evidence ID | Queue item | Artifact | Status | Owner | Timestamp (UTC) | Notes |",
            evidence_rows,
        )
        return checklist_path, evidence_path

    def test_validate_blocks_when_statuses_not_ok(self) -> None:
        checklist_path, evidence_path = self.make_artifacts(
            checklist_rows=[
                "| 2026-08-09 | LIV-01-1 (Legal) | docs/live_trading_readiness_evidence/legal_readiness_template.md | BLOCKED | Project owner | pending |",
                "| 2026-08-09 | LIV-01-2 (Security) | docs/live_trading_readiness_evidence/security_readiness_template.md | BLOCKED | Project owner | pending |",
                "| 2026-08-09 | LIV-01-3 (Risk) | docs/live_trading_readiness_evidence/risk_readiness_template.md | BLOCKED | Project owner | pending |",
            ],
            evidence_rows=[
                "| EVID-LIV-01-01 | LIV-01 | docs/live_trading_readiness_evidence/legal_readiness_template.md | BLOCKED | Project owner | — | pending |",
                "| EVID-LIV-01-02 | LIV-01 | docs/live_trading_readiness_evidence/security_readiness_template.md | PENDING | Project owner | — | pending |",
                "| EVID-LIV-01-03 | LIV-01 | docs/live_trading_readiness_evidence/risk_readiness_template.md | BLOCKED | Project owner | — | pending |",
            ],
        )
        errors, warnings = validator.validate_readiness(Path(checklist_path), Path(evidence_path))
        self.assertEqual(errors, [])
        self.assertGreaterEqual(len(warnings), 6)
        self.assertTrue(any("is BLOCKED" in issue for issue in warnings))
        self.assertTrue(any("is PENDING" in issue for issue in warnings))

    def test_validate_ok_when_all_ready(self) -> None:
        with tempfile.TemporaryDirectory() as evidence_dir:
            legal = Path(evidence_dir) / "legal.md"
            security = Path(evidence_dir) / "security.md"
            risk = Path(evidence_dir) / "risk.md"
            for path in (legal, security, risk):
                path.write_text(
                    "# evidence\\n\\n"
                    f"EVID-LIV-01-{'01' if path.name=='legal.md' else '02' if path.name=='security.md' else '03'}\\n"
                    "- Approver(s): owner\\n"
                    "- Decision date (UTC): 2026-08-09\\n"
                    "- Notes and constraints: complete\\n",
                    encoding="utf-8",
                )

            checklist_path, evidence_path = self.make_artifacts(
                checklist_rows=[
                    f"| 2026-08-09 | LIV-01-1 (Legal) | {legal.as_posix()} | OK | Project owner | complete |",
                    f"| 2026-08-09 | LIV-01-2 (Security) | {security.as_posix()} | OK | Project owner | complete |",
                    f"| 2026-08-09 | LIV-01-3 (Risk) | {risk.as_posix()} | OK | Project owner | complete |",
                ],
                evidence_rows=[
                    f"| EVID-LIV-01-01 | LIV-01 | {legal.as_posix()} | OK | Project owner | 2026-08-09 | complete |",
                    f"| EVID-LIV-01-02 | LIV-01 | {security.as_posix()} | OK | Project owner | 2026-08-09 | complete |",
                    f"| EVID-LIV-01-03 | LIV-01 | {risk.as_posix()} | OK | Project owner | 2026-08-09 | complete |",
                ],
            )
            errors, warnings = validator.validate_readiness(Path(checklist_path), Path(evidence_path))
            self.assertEqual(errors, [])
            self.assertEqual(warnings, [])

            self.assertEqual(validator.main(["--checklist", checklist_path, "--evidence-pack", evidence_path]), 0)
            self.assertEqual(validator.main(["--checklist", checklist_path, "--evidence-pack", evidence_path, "--strict"]), 0)


    def test_missing_required_rows_is_error(self) -> None:
        checklist_path, evidence_path = self.make_artifacts(
            checklist_rows=[
                "| 2026-08-09 | LIV-01-1 (Legal) | docs/live_trading_readiness_evidence/legal_readiness_template.md | BLOCKED | Project owner | pending |",
            ],
            evidence_rows=[
                "| EVID-LIV-01-01 | LIV-01 | docs/live_trading_readiness_evidence/legal_readiness_template.md | BLOCKED | Project owner | — | pending |",
            ],
        )
        errors, _warnings = validator.validate_readiness(Path(checklist_path), Path(evidence_path))
        self.assertTrue(any("missing row for LIV-01-2 (Security)" in issue for issue in errors))
        self.assertTrue(any("missing row for LIV-01-3 (Risk)" in issue for issue in errors))


if __name__ == "__main__":
    unittest.main()
