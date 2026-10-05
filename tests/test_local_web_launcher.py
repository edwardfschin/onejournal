from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from hashlib import sha256
from io import StringIO
import json
import os
from pathlib import Path
import select
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch
from urllib.request import ProxyHandler, build_opener

import duckdb

from onejournal import local_web as runner
from scripts.journal.init_journal_db import init_schema


ROOT = Path(__file__).resolve().parents[1]


class LocalWebLauncherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.private = Path(self.tmp.name).resolve()
        self.private.chmod(0o700)
        self.db = self.private / "journal.duckdb"
        self.db.write_bytes(b"synthetic placeholder")
        self.db.chmod(0o600)
        self.config_path = self.private / "local-web.json"
        self.document = {"contract_version": runner.CONFIG_VERSION, "journal_db_path": str(self.db)}
        self.write_config()

    def write_config(self) -> None:
        self.config_path.write_text(json.dumps(self.document), encoding="utf-8")
        self.config_path.chmod(0o600)

    def test_defaults_and_canonical_route_match_shared_registry(self) -> None:
        config = runner.load_config(self.config_path, ROOT)
        self.assertEqual(config.url, "http://127.0.0.1:4173/local/journal")
        source = (ROOT / "web/lib/routes.ts").read_text()
        for page in runner.LOCAL_PAGES:
            self.assertIn(f"'{page}'", source)
        self.assertIn("strictPort: true", (ROOT / "web/vite.config.ts").read_text())

    def test_reports_default_only_when_explicit_authorization_is_configured(self) -> None:
        auth = self.private / "report.json"
        auth.write_text("{}")
        auth.chmod(0o600)
        self.document["reporting_authorization"] = str(auth)
        self.assertEqual(runner.parse_config(self.document).start_page, "/local/reports")

    def test_config_rejects_unknown_hosts_ports_and_nonlocal_urls(self) -> None:
        changes = [
            {"host": "0.0.0.0"}, {"api_url": "https://example.invalid"},
            {"web_port": True}, {"api_port": 1023}, {"web_port": "4173"},
            {"web_port": 8765}, {"start_page": "https://example.invalid"},
            {"start_page": "/portfolio/local"}, {"contract_version": "unknown"},
        ]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(runner.LocalWebError):
                runner.parse_config({**self.document, **change})

    def test_private_permissions_symlink_and_checkout_location_fail_closed(self) -> None:
        self.config_path.chmod(0o644)
        with self.assertRaises(runner.LocalWebError):
            runner.load_config(self.config_path, ROOT)
        self.config_path.chmod(0o600)
        link = self.private / "linked.json"
        link.symlink_to(self.config_path)
        with self.assertRaises(runner.LocalWebError):
            runner.load_config(link, ROOT)
        with self.assertRaises(runner.LocalWebError):
            runner.load_config(self.config_path, self.private)
        self.private.chmod(0o755)
        with self.assertRaises(runner.LocalWebError):
            runner.load_config(self.config_path, ROOT)

    def test_missing_file_and_malformed_json_never_echo_private_paths(self) -> None:
        self.document["journal_db_path"] = str(self.private / "private-account-do-not-log")
        self.write_config()
        with self.assertRaises(runner.LocalWebError) as error:
            runner.load_config(self.config_path, ROOT)
        self.assertNotIn(str(self.private), str(error.exception))
        self.assertNotIn("private-account-do-not-log", str(error.exception))
        self.config_path.write_text("not JSON private-do-not-log")
        with self.assertRaises(runner.LocalWebError) as error:
            runner.load_config(self.config_path, ROOT)
        self.assertNotIn("private-do-not-log", str(error.exception))

    def test_occupied_port_does_not_spawn_or_stop_anything(self) -> None:
        with socket.socket() as busy:
            busy.bind(("127.0.0.1", 0))
            port = busy.getsockname()[1]
            config = runner.LocalWebConfig(self.db, web_port=port)
            with patch.object(runner, "LocalWebSession") as session, self.assertRaises(runner.LocalWebError):
                runner.run_session(config, self.config_path, ROOT, open_browser=False)
            session.assert_not_called()
            # The unrelated listener remains owned by this test.
            busy.listen()
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                pass

    def test_missing_old_node_and_missing_web_dependencies_are_actionable(self) -> None:
        with patch.object(runner.shutil, "which", return_value=None), self.assertRaisesRegex(runner.LocalWebError, "Node.js is missing"):
            runner.node_runtime(ROOT)
        with patch.object(runner.shutil, "which", return_value="node"), patch.object(runner.subprocess, "run", return_value=Mock(stdout="20.0.0")), self.assertRaisesRegex(runner.LocalWebError, "22.13"):
            runner.node_runtime(ROOT)
        with patch.object(runner.shutil, "which", return_value="node"), patch.object(runner.subprocess, "run", return_value=Mock(stdout="24.0.0")), self.assertRaisesRegex(runner.LocalWebError, "npm ci"):
            runner.node_runtime(self.private)

    def test_child_environment_does_not_copy_provider_secrets(self) -> None:
        with patch.dict(os.environ, {"BROKER_TOKEN": "private", "VITE_PRIVATE_VALUE": "private", "ONEJOURNAL_LOCAL_API_URL": "https://invalid"}):
            env = runner.child_environment(ROOT, "/opt/bin/node")
        self.assertNotIn("BROKER_TOKEN", env)
        self.assertNotIn("VITE_PRIVATE_VALUE", env)
        self.assertNotIn("ONEJOURNAL_LOCAL_API_URL", env)
        self.assertEqual(env["PYTHONPATH"], str(ROOT / "src"))

    def test_spawn_owns_new_group_and_does_not_stream_child_output(self) -> None:
        session = runner.LocalWebSession()
        with patch.object(runner.subprocess, "Popen") as popen:
            child = session.spawn(["synthetic"], ROOT, {})
        self.assertEqual(session.children, [child])
        self.assertTrue(popen.call_args.kwargs["start_new_session"])
        self.assertEqual(popen.call_args.kwargs["stderr"], subprocess.DEVNULL)

    def test_failed_child_readiness_does_not_probe_financial_api(self) -> None:
        child = Mock()
        child.poll.return_value = 1
        with patch.object(runner.socket, "create_connection") as connect, self.assertRaises(runner.LocalWebError):
            runner.LocalWebSession().ready(child, 8765, "API")
        connect.assert_not_called()

    def test_partial_startup_failure_always_cleans_managed_companion(self) -> None:
        api = Mock()
        session = Mock()
        session.spawn.side_effect = [api, runner.LocalWebError("synthetic web startup failure")]
        with patch.object(runner, "free_ports"), patch.object(runner, "node_runtime", return_value=("node", Path("cli"))), patch.object(runner, "LocalWebSession", return_value=session), self.assertRaises(runner.LocalWebError):
            runner.run_session(runner.LocalWebConfig(self.db), self.config_path, ROOT, open_browser=False)
        session.stop.assert_called_once()
        command = session.spawn.call_args_list[0].args[0]
        self.assertNotIn(str(self.db), command)
        self.assertIn("--api-child", command)

    def test_companion_crash_after_readiness_stops_both(self) -> None:
        api, web = Mock(), Mock()
        api.poll.return_value = None
        web.poll.side_effect = [None, 1]
        session = Mock(children=[api, web])
        session.spawn.side_effect = [api, web]
        with patch.object(runner, "free_ports"), patch.object(runner, "node_runtime", return_value=("node", Path("cli"))), patch.object(runner, "LocalWebSession", return_value=session), redirect_stdout(StringIO()), self.assertRaisesRegex(runner.LocalWebError, "unexpectedly"):
            runner.run_session(runner.LocalWebConfig(self.db), self.config_path, ROOT, open_browser=False)
        session.stop.assert_called_once()

    def test_stop_targets_only_recorded_groups_even_when_a_parent_has_exited(self) -> None:
        session = runner.LocalWebSession()
        session.children = [Mock(pid=101), Mock(pid=202)]
        with patch.object(runner.os, "killpg") as kill:
            session.stop()
        self.assertEqual(kill.call_args_list[0].args, (101, signal.SIGTERM))
        self.assertEqual(kill.call_args_list[1].args, (202, signal.SIGTERM))
        self.assertEqual({call.args[0] for call in kill.call_args_list}, {101, 202})
        self.assertEqual(session.children, [])

    def test_check_uses_existing_api_validation_without_a_database_write(self) -> None:
        self.db.unlink()  # This test owns only its disposable placeholder.
        init_schema(self.db)
        self.db.chmod(0o600)
        before = sha256(self.db.read_bytes()).hexdigest()
        with patch.object(runner, "node_runtime"), patch.object(runner, "run_session") as start, redirect_stdout(StringIO()):
            self.assertEqual(runner.main(ROOT, ["--config", str(self.config_path), "--check"]), 0)
        start.assert_not_called()
        self.assertEqual(sha256(self.db.read_bytes()).hexdigest(), before)
        with duckdb.connect(str(self.db), read_only=True) as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM local_owner_api_audit_events").fetchone()[0], 0)

    def test_configure_refuses_overwrite_before_requesting_private_input(self) -> None:
        before = self.config_path.read_bytes()
        with patch.object(runner.getpass, "getpass") as prompt, self.assertRaises(runner.LocalWebError):
            runner.configure(self.config_path, ROOT)
        prompt.assert_not_called()
        self.assertEqual(self.config_path.read_bytes(), before)

    def test_configure_creates_private_config_without_logging_inputs(self) -> None:
        destination = self.private / "new-config.json"
        with patch.object(runner.getpass, "getpass", side_effect=[str(self.db), "", ""]), patch.object(runner, "configured_app"), redirect_stdout(StringIO()) as output:
            runner.configure(destination, ROOT)
        self.assertNotIn(str(self.db), output.getvalue())
        self.assertEqual(destination.stat().st_mode & 0o777, 0o600)
        self.assertEqual(runner.load_config(destination, ROOT).journal_db, self.db)

    def test_check_cannot_write_configuration(self) -> None:
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit) as error:
            runner.main(ROOT, ["configure", "--check"])
        self.assertEqual(error.exception.code, 2)

    def test_configure_uses_a_private_subfolder_without_changing_existing_parent(self) -> None:
        container = self.private / "existing-container"
        container.mkdir(mode=0o755)
        container.chmod(0o755)
        destination = container / "local-web" / "config.json"
        with patch.object(runner.getpass, "getpass", side_effect=[str(self.db), "", ""]), patch.object(runner, "configured_app"), redirect_stdout(StringIO()):
            runner.configure(destination, ROOT)
        self.assertEqual(container.stat().st_mode & 0o777, 0o755)
        self.assertEqual(destination.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(destination.stat().st_mode & 0o777, 0o600)
        self.assertEqual(runner.load_config(destination, ROOT).journal_db, self.db)

    def test_validation_error_is_private_and_returns_failure(self) -> None:
        with redirect_stderr(StringIO()) as output:
            self.assertEqual(runner.main(ROOT, ["--config", str(self.private / "do-not-log.json"), "--check"]), 1)
        self.assertNotIn(str(self.private), output.getvalue())


@unittest.skipUnless(os.environ.get("ONEJOURNAL_WEB_SMOKE") == "1", "Opt-in real frontend smoke; not required for ordinary offline Python CI")
class LocalWebRealSmokeTests(unittest.TestCase):
    def test_real_local_website_proxy_and_ctrl_c_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            private = Path(directory).resolve()
            private.chmod(0o700)
            db = private / "journal.duckdb"
            init_schema(db)
            db.chmod(0o600)
            with socket.socket() as a, socket.socket() as b:
                a.bind(("127.0.0.1", 0))
                b.bind(("127.0.0.1", 0))
                web_port, api_port = a.getsockname()[1], b.getsockname()[1]
            path = private / "local-web.json"
            path.write_text(json.dumps({"contract_version": runner.CONFIG_VERSION, "journal_db_path": str(db), "web_port": web_port, "api_port": api_port}))
            path.chmod(0o600)
            proc = subprocess.Popen([sys.executable, str(ROOT / "scripts/web/run_local_owner_website.py"), "--config", str(path), "--no-browser"], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                assert proc.stdout is not None
                deadline = time.monotonic() + 60
                ready = False
                while time.monotonic() < deadline:
                    if proc.poll() is not None:
                        break
                    if select.select([proc.stdout], [], [], 0.2)[0]:
                        if "OneJournal is ready:" in proc.stdout.readline():
                            ready = True
                            break
                self.assertTrue(ready, "Launcher did not reach readiness with disposable state")
                http = build_opener(ProxyHandler({}))
                with http.open(f"http://127.0.0.1:{web_port}/api/v5/local-owner/journal/search", timeout=5) as response:
                    body = json.load(response)
                self.assertEqual(body["metadata"]["contract_version"], "onejournal.local-owner-journal.v5")
                self.assertEqual(body["episodes"], [])
                proc.send_signal(signal.SIGINT)
                stdout, stderr = proc.communicate(timeout=15)
                self.assertEqual(proc.returncode, 0, stderr)
                self.assertIn("Stopped.", stdout)
                self.assertNotIn(str(private), stdout + stderr)
                for port in (web_port, api_port):
                    with self.assertRaises(OSError):
                        socket.create_connection(("127.0.0.1", port), timeout=0.2)
            finally:
                if proc.poll() is None:
                    proc.terminate()
                    proc.communicate(timeout=15)


if __name__ == "__main__":
    unittest.main()
