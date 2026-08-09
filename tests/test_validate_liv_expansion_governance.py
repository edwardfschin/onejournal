from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import importlib.util

PROJECT_DIR = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_DIR / "scripts" / "liv" / "validate_expansion_governance.py"
SPEC = importlib.util.spec_from_file_location("validate_liv_expansion_governance", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
validator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validator)


class LivExpansionGovernanceValidatorTests(unittest.TestCase):
    def make_markdown(self, header: str, rows: list[str]) -> str:
        text = [
            header,
            "|---|---|---|---|---|---|---|---|",
            *rows,
            "",
        ]
        tmp = tempfile.NamedTemporaryFile("w", suffix=".md", delete=False)
        with tmp as fh:
            fh.write("\n".join(text))
        return tmp.name

    def make_artifacts(self, *, decision_rows: list[str], evidence_rows: list[str]) -> tuple[str, str]:
        decision_path = self.make_markdown(
            "| Date (UTC) | Queue item | Decision status | Artifact(s) | Approver | Approver role | Rationale / constraints | Next action |",
            decision_rows,
        )
        evidence_path = self.make_markdown(
            "| Evidence ID | Queue item | Artifact | Status | Owner | Timestamp (UTC) | Notes |",
            evidence_rows,
        )
        return decision_path, evidence_path

    def test_schema_validation_only_warnings_on_deferred(self) -> None:
        decision_path, evidence_path = self.make_artifacts(
            decision_rows=[
                "| 2026-08-09 | LIV-05 | DEFERRED | docs/live_trading_control_contract.md | — | — | Expansion gates are pending. | Prepare staged decision with two-owner approval. |",
                "| 2026-08-09 | LIV-04 | COMPLETED | docs/live_trading_control_contract.md | owner | Owner | Reconciliation checks implemented for checks. | Continue evidence collection. |",
            ],
            evidence_rows=[
                "| EVID-LIV-05-01 | LIV-05 | docs/live_trading_control_contract.md | PENDING | Project owner | — | Expansion gates are documented but not approved. |",
                "| EVID-LIV-04-02 | LIV-04 | docs/liv/... | OK | Project owner | — | Reconciliation validator added. |",
            ],
        )
        errors, warnings = validator.validate_governance(Path(decision_path), Path(evidence_path))
        self.assertEqual(errors, [])
        self.assertTrue(any("LIV-05 remains deferred" in issue for issue in warnings))

    def test_invalid_queue_is_error(self) -> None:
        decision_path, evidence_path = self.make_artifacts(
            decision_rows=[
                "| 2026-08-09 | LIV-99 | DEFERRED | docs/live_trading_control_contract.md | — | — | Bad queue test | Next action. |",
            ],
            evidence_rows=[
                "| EVID-LIV-05-01 | LIV-05 | docs/live_trading_control_contract.md | PENDING | Project owner | — | Expansion gate pending. |",
            ],
        )
        errors, _warnings = validator.validate_governance(Path(decision_path), Path(evidence_path))
        self.assertTrue(any("invalid queue" in issue for issue in errors))

    def test_completed_requires_approver_role(self) -> None:
        decision_path, evidence_path = self.make_artifacts(
            decision_rows=[
                "| 2026-08-09 | LIV-05 | COMPLETED | docs/live_trading_readiness_decision_log.md | | | Completed but missing approver identity. | Finalize. |",
            ],
            evidence_rows=[
                "| EVID-LIV-05-01 | LIV-05 | docs/live_trading_control_contract.md | PENDING | Project owner | — | Pending. |",
            ],
        )
        errors, _warnings = validator.validate_governance(Path(decision_path), Path(evidence_path))
        self.assertTrue(any("COMPLETED requires approver and approver role" in issue for issue in errors))

    def test_cli_strict_fails_on_warnings(self) -> None:
        decision_path, evidence_path = self.make_artifacts(
            decision_rows=[
                "| 2026-08-09 | LIV-05 | DEFERRED | docs/live_trading_control_contract.md | — | — | Expansion gates are pending. | Prepare staged decision with two-owner approval. |",
            ],
            evidence_rows=[
                "| EVID-LIV-05-01 | LIV-05 | docs/live_trading_control_contract.md | PENDING | Project owner | — | Pending. |",
            ],
        )
        self.assertEqual(validator.main(["--decision-log", decision_path, "--evidence-pack", evidence_path]), 0)
        self.assertEqual(validator.main(["--decision-log", decision_path, "--evidence-pack", evidence_path, "--strict"]), 1)


if __name__ == "__main__":
    unittest.main()
