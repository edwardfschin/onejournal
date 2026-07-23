from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_DIR / "scripts/journal/fetch_schwab_raw_history.py"
SPEC = importlib.util.spec_from_file_location("onejournal_schwab_raw_history", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
raw_history = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = raw_history
SPEC.loader.exec_module(raw_history)


class SchwabRawHistoryBoundaryTests(unittest.TestCase):
    def test_default_token_path_is_onejournal_scoped(self) -> None:
        token_path = raw_history.default_token_path({})
        self.assertEqual(
            token_path,
            Path.home() / ".onejournal/tokens/schwab_tokens.json",
        )

    def test_explicit_onejournal_token_path_is_used(self) -> None:
        token_path = raw_history.default_token_path(
            {"ONEJOURNAL_SCHWAB_TOKEN_PATH": "~/private/onejournal-schwab.json"}
        )
        self.assertEqual(token_path, Path("~/private/onejournal-schwab.json").expanduser())

    def test_legacy_generic_configuration_is_rejected(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "TOKEN_PATH"):
            raw_history.validate_runtime_boundary(
                Path.home() / ".onejournal/tokens/schwab_tokens.json",
                {"TOKEN_PATH": "~/.onebot/tokens/schwab_tokens.json"},
            )

    def test_onebot_token_path_is_rejected(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "OneBot token path"):
            raw_history.validate_runtime_boundary(
                Path.home() / ".onebot/tokens/schwab_tokens.json",
                {},
            )

    def test_onejournal_configuration_is_accepted(self) -> None:
        raw_history.validate_runtime_boundary(
            Path.home() / ".onejournal/tokens/schwab_tokens.json",
            {"ONEJOURNAL_SCHWAB_CLIENT_ID": "placeholder"},
        )


if __name__ == "__main__":
    unittest.main()
