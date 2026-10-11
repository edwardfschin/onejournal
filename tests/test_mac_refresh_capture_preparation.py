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
import stat
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
PYTHON_EXECUTABLE = Path("/synthetic/bin/python3.12")
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

    def test_capture_guard_separates_utc_acquisition_day_from_market_date(self):
        from zoneinfo import ZoneInfo
        values = namespace(prepare_capture_runner(SOURCE, specification()))
        guard = values["_REFRESH_require_capture_day"]
        guard(datetime(2026, 10, 9, 8, tzinfo=UTC))
        instant = datetime(2026, 10, 9, 2, tzinfo=UTC)
        self.assertEqual(instant.astimezone(ZoneInfo("America/New_York")).date(), date(2026, 10, 8))
        guard(instant)
        guard(instant.astimezone(ZoneInfo("America/New_York")))
        winter = namespace(prepare_capture_runner(SOURCE, replace(specification(), asof=date(2026, 12, 1))))
        winter["_REFRESH_require_capture_day"](datetime(2026, 12, 1, 4, tzinfo=UTC))
        for instant in (datetime(2026, 10, 8, 23, 59, tzinfo=UTC), datetime(2026, 10, 10, 1, tzinfo=UTC),
                        datetime(2026, 10, 9, 8)):
            with self.assertRaises(values["CaptureError"]): guard(instant)

    def test_response_can_cross_new_york_midnight_but_not_approved_utc_day(self):
        values = namespace(prepare_capture_runner(SOURCE, specification()))
        class Clock:
            instants = iter(())
            @classmethod
            def now(cls, _): return next(cls.instants)
        class Session:
            calls = 0
            def get(self):
                self.calls += 1
                return "synthetic-response"
        values["datetime"] = Clock
        session = Session()
        Clock.instants = iter((datetime(2026, 10, 9, 3, 59, tzinfo=UTC), datetime(2026, 10, 9, 4, tzinfo=UTC)))
        self.assertEqual(values["_fetch"](session), "synthetic-response")
        Clock.instants = iter((datetime(2026, 10, 9, 23, 59, tzinfo=UTC), datetime(2026, 10, 10, 0, tzinfo=UTC)))
        with self.assertRaises(values["CaptureError"]): values["_fetch"](session)
        self.assertEqual(session.calls, 2)  # One call per attempt, never a retry.

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

    def test_isolated_runtime_rebinds_only_the_explicit_executable_and_rejects_shared_runtime(self):
        python = PurePosixPath("/synthetic/private/capture-runtime/python-env/bin/python3.12")
        prepared = prepare_capture_runner(SOURCE, replace(specification(), capture_python=python))
        values = namespace(prepared)
        self.assertEqual(str(values["PYTHON_EXECUTABLE"]), str(python))
        main = next(node for node in ast.parse(prepared).body if isinstance(node, ast.FunctionDef) and node.name == "main")
        self.assertEqual([node.value.func.id for node in main.body[:3]],
                         ["_REFRESH_require_capture_day", "_REFRESH_require_isolated_runtime", "_REFRESH_require_transport"])
        with self.assertRaises(values["CaptureError"]):
            values["_REFRESH_require_isolated_runtime"]()
        for invalid in (PurePosixPath("relative/bin/python3.12"), PurePosixPath("/synthetic/private/captures/new-run/bin/python3.12")):
            with self.assertRaises(CapturePreparationError):
                prepare_capture_runner(SOURCE, replace(specification(), capture_python=invalid))

    def test_current_proposed_windows_and_expired_previous_day(self):
        spec = replace(specification("history"), asof=date(2026, 10, 11), window_start=date(2026, 10, 5), window_end=date(2026, 10, 11))
        values = namespace(prepare_capture_runner(SOURCE, spec))
        self.assertEqual(values["END_TIMESTAMP"], "2026-10-11T23:59:59.999Z")
        guard = values["_REFRESH_require_capture_day"]
        guard(datetime(2026, 10, 11, 4, tzinfo=UTC))
        guard(datetime(2026, 10, 11, 2, tzinfo=UTC))
        for instant in (datetime(2026, 10, 10, 23, tzinfo=UTC), datetime(2026, 10, 12, 0, tzinfo=UTC)):
            with self.assertRaises(values["CaptureError"]): guard(instant)

    def test_isolated_runtime_accepts_only_private_no_shared_packages_and_matching_module_origins(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            python = root / "bin/python3.12"
            configuration = root / "pyvenv.cfg"
            configuration.write_text("include-system-site-packages = false\n")
            values = namespace(prepare_capture_runner(SOURCE, replace(specification(), capture_python=PurePosixPath(str(python)))))
            requests = SimpleNamespace(__file__=str(root / "lib/requests/__init__.py"), __version__="2.33.0")
            urllib3 = SimpleNamespace(__file__=str(root / "lib/urllib3/__init__.py"), __version__="2.8.0")
            with patch("sys.flags", SimpleNamespace(isolated=1)), patch("sys.executable", str(python)), patch("sys.prefix", str(root)), patch("site.ENABLE_USER_SITE", False), patch.dict("sys.modules", {"requests": requests, "urllib3": urllib3}), patch("importlib.metadata.version", side_effect=lambda name: {"requests":"2.33.0","urllib3":"2.8.0"}[name]):
                values["_REFRESH_require_isolated_runtime"]()
                requests.__file__ = "/synthetic/shared/requests/__init__.py"
                with self.assertRaises(values["CaptureError"]): values["_REFRESH_require_isolated_runtime"]()
                requests.__file__ = str(root / "lib/requests/__init__.py")
                configuration.write_text("include-system-site-packages = true\n")
                with self.assertRaises(values["CaptureError"]): values["_REFRESH_require_isolated_runtime"]()

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
