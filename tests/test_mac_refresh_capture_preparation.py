from __future__ import annotations

import ast
from dataclasses import replace
from datetime import UTC, date, datetime
from hashlib import sha256
from pathlib import PurePosixPath
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from onejournal.provider_connectors.capture_preparation import (
    CapturePreparation, CapturePreparationError, prepare_capture_runner,
)


SOURCE = b'''
from datetime import UTC, datetime
from pathlib import Path
import sys
RUN_UID = "synthetic-old-run"
APPROVAL_ID = "synthetic-old-approval"
OUTPUT_PARENT = Path("/synthetic/private/captures")
RUN_ROOT = OUTPUT_PARENT / RUN_UID
ACQUISITION_ROOT = RUN_ROOT / "acquisition"
RUNNER_PATH = RUN_ROOT / "old.py"
EXPECTED_AUTH_SHA256 = "old-auth"
EXPECTED_CONF_SHA256 = "old-conf"
EXPECTED_PYTHON_SHA256 = "old-runtime"
OWNER_UID = "synthetic-owner"
OWNER_EPOCH_UID = "synthetic-epoch"
EXPECTED_ACK_SHA256 = "synthetic-ack"
WINDOW_START = "2026-09-01"
WINDOW_END = "2026-09-04"
START_TIMESTAMP = "2026-09-01T00:00:00.000Z"
END_TIMESTAMP = "2026-09-04T23:59:59.999Z"
class CaptureError(RuntimeError): pass
def _fetch(session):
    requested_at = datetime.now(UTC)
    response = session.get()
    received_at = datetime.now(UTC)
    return response
def main():
    source_contract = {"owner_refresh_before_capture_count": 1}
    raise RuntimeError("synthetic-private-provider-url")
if __name__ == "__main__":
    raise SystemExit(main())
'''


def specification(kind="position"):
    return CapturePreparation(kind=kind, asof=date(2026, 10, 9), run_uid="synthetic-fresh-run",
        proposed_approval_id="synthetic-proposed-approval", owner_run_root=PurePosixPath("/synthetic/private/captures/new-run"),
        reviewed_source_sha256=sha256(SOURCE).hexdigest(), auth_sha256="a" * 64,
        conf_sha256="b" * 64, runtime_sha256="c" * 64,
        window_start=date(2026, 9, 5) if kind == "history" else None,
        window_end=date(2026, 10, 4) if kind == "history" else None)


def namespace(prepared):
    value = {"__name__": "synthetic_runner"}
    exec(compile(prepared, "synthetic_runner", "exec"), value)
    return value


class MacRefreshCapturePreparationTests(unittest.TestCase):
    def test_deterministic_rebinding_preserves_owner_and_acknowledgement(self):
        spec = specification()
        prepared = prepare_capture_runner(SOURCE, spec)
        self.assertEqual(prepared, prepare_capture_runner(SOURCE, spec))
        values = namespace(prepared)
        self.assertEqual(values["RUN_UID"], spec.run_uid)
        self.assertEqual(values["OWNER_UID"], "synthetic-owner")
        self.assertEqual(values["OWNER_EPOCH_UID"], "synthetic-epoch")
        self.assertEqual(values["EXPECTED_ACK_SHA256"], "synthetic-ack")
        self.assertEqual(str(values["RUNNER_PATH"]), "/synthetic/private/captures/new-run/onejournal_mac_refresh_position.py")
        dictionaries = [node for node in ast.walk(ast.parse(prepared)) if isinstance(node, ast.Dict)]
        self.assertIn(0, [ast.literal_eval(node)["owner_refresh_before_capture_count"] for node in dictionaries])

    def test_history_window_is_exact_and_bounded(self):
        values = namespace(prepare_capture_runner(SOURCE, specification("history")))
        self.assertEqual(values["START_TIMESTAMP"], "2026-09-05T00:00:00.000Z")
        self.assertEqual(values["END_TIMESTAMP"], "2026-10-04T23:59:59.999Z")
        for invalid in (replace(specification("history"), window_end=date(2026, 10, 5)),
                        replace(specification("history"), window_end=date(2026, 10, 10)),
                        replace(specification("history"), window_start=None)):
            with self.assertRaises(CapturePreparationError): prepare_capture_runner(SOURCE, invalid)

    def test_checksum_scope_and_historical_identity_mismatch_stop_preparation(self):
        for invalid in (replace(specification(), reviewed_source_sha256="d" * 64),
                        replace(specification(), runtime_sha256="unknown"),
                        replace(specification(), run_uid="synthetic-old-run"),
                        replace(specification(), proposed_approval_id="synthetic-old-approval"),
                        replace(specification(), owner_run_root=PurePosixPath("/other/private/new"))):
            with self.assertRaises(CapturePreparationError): prepare_capture_runner(SOURCE, invalid)

    def test_capture_guard_requires_matching_utc_and_new_york_dates(self):
        values = namespace(prepare_capture_runner(SOURCE, specification()))
        guard = values["_REFRESH_require_capture_day"]
        guard(datetime(2026, 10, 9, 8, tzinfo=UTC))
        for instant in (datetime(2026, 10, 9, 2, tzinfo=UTC), datetime(2026, 10, 10, 1, tzinfo=UTC),
                        datetime(2026, 10, 9, 8)):
            with self.assertRaises(values["CaptureError"]): guard(instant)

    def test_expired_date_stops_before_main_or_get(self):
        values = namespace(prepare_capture_runner(SOURCE, specification()))
        class ExpiredClock:
            @staticmethod
            def now(_): return datetime(2026, 10, 10, 8, tzinfo=UTC)
        values["datetime"] = ExpiredClock
        class Session:
            def get(self): raise AssertionError("GET must not be attempted")
        with self.assertRaises(values["CaptureError"]): values["main"]()
        with self.assertRaises(values["CaptureError"]): values["_fetch"](Session())

    def test_runtime_failure_hides_private_exception_details(self):
        prepared = prepare_capture_runner(SOURCE, specification())
        class Clock(datetime):
            @classmethod
            def now(cls, _): return datetime(2026, 10, 9, 8, tzinfo=UTC)
        import io
        output = io.StringIO()
        with patch("datetime.datetime", Clock), patch("importlib.metadata.version", return_value="3.0.0"), patch("sys.stderr", output), self.assertRaises(SystemExit) as result:
            exec(compile(prepared, "synthetic_runner", "exec"), {"__name__": "__main__"})
        self.assertEqual(result.exception.code, 1)
        self.assertNotIn("synthetic-private-provider-url", output.getvalue())
        self.assertIn("no automatic retry", output.getvalue())

    def test_outdated_or_missing_transport_stops_before_main_side_effects(self):
        from importlib.metadata import PackageNotFoundError
        values = namespace(prepare_capture_runner(SOURCE, specification()))
        guard = values["_REFRESH_require_transport"]
        for versions in (("2.31.0", "2.0.7"), ("2.33.0", "2.7.0"), ("2.33.0", "2.8.0rc1")):
            with patch("importlib.metadata.version", side_effect=versions), self.assertRaises(values["CaptureError"]):
                guard()
        with patch("importlib.metadata.version", side_effect=PackageNotFoundError), self.assertRaises(values["CaptureError"]):
            guard()
        with patch("importlib.metadata.version", side_effect=("2.33.0", "2.8.0")):
            guard()
        class Clock:
            @staticmethod
            def now(_): return datetime(2026, 10, 9, 8, tzinfo=UTC)
        values["datetime"] = Clock
        with patch("importlib.metadata.version", return_value="2.0.7"), self.assertRaises(values["CaptureError"]):
            values["main"]()

    def test_preparing_a_prepared_runner_is_rejected(self):
        prepared = prepare_capture_runner(SOURCE, specification())
        with self.assertRaisesRegex(CapturePreparationError, "retained source"):
            prepare_capture_runner(prepared, replace(specification(), reviewed_source_sha256=sha256(prepared).hexdigest()))

    def test_operator_writes_private_source_once_and_rejects_overwrite(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            source = root / "retained.py"
            source.write_bytes(SOURCE)
            source.chmod(0o600)
            output = root / "onejournal_mac_refresh_position.py"
            project = Path(__file__).resolve().parents[1]
            command = [sys.executable, "-B", str(project / "scripts/journal/prepare_mac_refresh_capture.py"),
                "--source", str(source), "--reviewed-source-sha256", sha256(SOURCE).hexdigest(),
                "--kind", "position", "--asof", "2026-10-09", "--run-uid", "synthetic-fresh-run",
                "--proposed-approval-id", "synthetic-proposed-approval", "--owner-run-root", "/synthetic/private/captures/new-run",
                "--auth-sha256", "a" * 64, "--conf-sha256", "b" * 64, "--runtime-sha256", "c" * 64,
                "--output", str(output)]
            first = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(first.returncode, 0, first.stderr)
            original = output.read_bytes()
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            self.assertIn('"status": "prepared_not_authorized"', first.stdout)
            second = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(second.returncode, 1)
            self.assertEqual(output.read_bytes(), original)
            self.assertNotIn(str(root), second.stderr)


if __name__ == "__main__": unittest.main()
