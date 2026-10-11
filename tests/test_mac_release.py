"""Focused packaging guards and opt-in installed HTTPS rehearsal; synthetic only."""
from contextlib import redirect_stderr
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import signal
import socket
import ssl
import subprocess
import tarfile
import tempfile
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

from onejournal.local_web import LocalWebConfig
from onejournal.mac_static_site import main
from scripts.web.package_mac_release import package, release_files
from test_mac_passkey_access import AVAILABLE, SyntheticAuthenticator

ROOT = Path(__file__).resolve().parents[1]


class MacReleaseGuards(unittest.TestCase):
    def test_new_external_destination_and_committed_source_required(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            existing = root / "existing.tar.gz"
            existing.write_bytes(b"preserve")
            for target in (ROOT / "candidate.tar.gz", existing, root / "wrong.zip"):
                with self.assertRaises(ValueError):
                    package(ROOT, target)
            with patch("scripts.web.package_mac_release.run", return_value=b" M tracked.py"):
                with self.assertRaisesRegex(ValueError, "Commit"):
                    package(ROOT, root / "new.tar.gz")
            self.assertEqual(existing.read_bytes(), b"preserve")

    def test_release_rejects_links_and_records_exact_hashes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            file = root / "public.txt"
            file.write_bytes(b"public")
            self.assertEqual(release_files(root), {"public.txt": hashlib.sha256(b"public").hexdigest()})
            (root / "link").symlink_to(file)
            with self.assertRaises(ValueError):
                release_files(root)

    def arguments(self, root):
        return ["--web-config", str(root / "config.json"), "--security-db", str(root / "security.duckdb"),
                "--tls-cert", str(root / "cert.pem"), "--tls-key", str(root / "key.pem"),
                "--static-dir", str(root / "static")]

    def test_no_implicit_activation(self):
        with patch("onejournal.mac_static_site.load_config") as load, redirect_stderr(io.StringIO()):
            self.assertEqual(main(self.arguments(Path("/synthetic"))), 1)
            load.assert_not_called()

    @unittest.skipUnless(AVAILABLE, "Security extra required.")
    def test_occupied_port_fails_before_journal_or_security_open(self):
        with tempfile.TemporaryDirectory() as temporary, socket.socket() as listener:
            root = Path(temporary)
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            config = LocalWebConfig(root / "journal.duckdb", web_port=listener.getsockname()[1])
            with patch("onejournal.mac_static_site.load_config", return_value=config), \
                 patch("onejournal.mac_static_site.private_file"), \
                 patch("onejournal.mac_static_site.static_routes"), \
                 patch("onejournal.mac_static_site.configured_app") as api, redirect_stderr(io.StringIO()):
                self.assertEqual(main(self.arguments(root) + ["--owner-local"]), 1)
                api.assert_not_called()

    @unittest.skipUnless(AVAILABLE, "Security extra required.")
    def test_private_files_cannot_be_placed_in_public_static_tree(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = LocalWebConfig(root / "static/journal.duckdb")
            with patch("onejournal.mac_static_site.load_config", return_value=config), \
                 patch("onejournal.mac_static_site.configured_app") as api, redirect_stderr(io.StringIO()):
                self.assertEqual(main(self.arguments(root) + ["--owner-local"]), 1)
                api.assert_not_called()


@unittest.skipUnless(AVAILABLE and os.environ.get("ONEJOURNAL_RELEASE_PYTHON") and
                     os.environ.get("ONEJOURNAL_RELEASE_ARCHIVE"), "Opt-in installed release rehearsal.")
class InstalledMacRelease(unittest.TestCase):
    def test_relocated_installed_service_real_https_and_signed_private_journal(self):
        import httpx
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.x509.oid import NameOID
        from onejournal.passkey_access import PREFIX, provision
        from scripts.journal.init_journal_db import init_schema

        python = Path(os.environ["ONEJOURNAL_RELEASE_PYTHON"])
        with tempfile.TemporaryDirectory(prefix="onejournal-installed-rehearsal-") as temporary:
            root = Path(temporary)
            root.chmod(0o700)
            with tarfile.open(os.environ["ONEJOURNAL_RELEASE_ARCHIVE"]) as archive:
                archive.extractall(root, filter="data")
            release = root / "onejournal-mac-release"
            manifest = json.loads((release / "release-manifest.json").read_text())
            hashes_found = release_files(release)
            hashes_found.pop("release-manifest.json")
            self.assertEqual(hashes_found, manifest["files_sha256"])
            # -I and a working directory outside Git prove this is not an editable import.
            installed = subprocess.check_output([str(python), "-I", "-c",
                "import onejournal.mac_static_site as m; print(m.__file__)"], cwd=root, text=True).strip()
            self.assertTrue(Path(installed).is_relative_to(python.parent.parent))
            self.assertNotIn("/src/", installed)
            private = root / "private"
            private.mkdir(mode=0o700)
            journal = private / "journal.duckdb"
            init_schema(journal)
            journal.chmod(0o600)
            journal_before = hashlib.sha256(journal.read_bytes()).hexdigest()
            with socket.socket() as check:
                check.bind(("127.0.0.1", 0))
                port = check.getsockname()[1]
            origin = f"https://localhost:{port}"
            store, grant = private / "access.duckdb", private / "grant.txt"
            provision(store, journal, origin, grant)
            key = ec.generate_private_key(ec.SECP256R1())
            name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
            now = datetime.now(timezone.utc)
            cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
                .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=1))
                .not_valid_after(now + timedelta(days=1))
                .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
                .sign(key, hashes.SHA256()))
            certificate, key_file = private / "cert.pem", private / "key.pem"
            certificate.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
            key_file.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
            config = private / "config.json"
            config.write_text(json.dumps({"contract_version": "onejournal.local-web.v1",
                "journal_db_path": str(journal), "web_port": port, "api_port": 8765}))
            for file in (certificate, key_file, config):
                file.chmod(0o600)
            command = [str(python.parent / "onejournal-mac-site"), "--web-config", str(config),
                "--security-db", str(store), "--tls-cert", str(certificate), "--tls-key", str(key_file),
                "--static-dir", str(release / "static"), "--owner-local"]
            environment = {"PATH": str(python.parent), "LANG": "en_US.UTF-8"}
            process = subprocess.Popen(command, cwd=root, env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                context = ssl.create_default_context(cafile=str(certificate))
                with httpx.Client(base_url=origin, verify=context, trust_env=False, timeout=5) as client:
                    last_error = None
                    for _ in range(300):
                        if process.poll() is not None:
                            self.fail("Installed service exited before readiness: " + process.communicate()[1].decode())
                        try:
                            response = client.get("/local/reports")
                            break
                        except httpx.TransportError as error:
                            last_error = error
                            time.sleep(0.1)
                    else:
                        self.fail(f"Installed service did not become ready: {last_error}")
                    self.assertEqual(response.status_code, 200)
                    self.assertIn('id="root"', response.text)
                    self.assertEqual(hashlib.sha256(journal.read_bytes()).hexdigest(), journal_before)
                    path = "/api/v5/local-owner/journal/search"
                    self.assertEqual(client.get(path).status_code, 401)
                    device = SyntheticAuthenticator()
                    def post(suffix, value, headers=None):
                        return client.post(PREFIX + "/" + suffix, json=value,
                            headers={"Origin": origin, **(headers or {})})
                    secret = grant.read_text().strip()
                    options = post("register/options", {"enrollment_secret": secret}).json()
                    self.assertEqual(post("register/verify", {"enrollment_secret": secret,
                        "ceremony": options["ceremony"], "credential": device.credential(options["options"], register=True, origin=origin)}).status_code, 200)
                    options = post("login/options", {}).json()
                    self.assertEqual(post("login/verify", {"ceremony": options["ceremony"],
                        "credential": device.credential(options["options"], origin=origin)}).status_code, 200)
                    self.assertEqual(client.get(path).status_code, 200)
                    csrf = client.get(PREFIX + "/session").json()["csrf"]
                    entry_path = "/api/v5/local-owner/journal/entries"
                    payload = {"entry_type": "note", "title": "Synthetic rehearsal", "body": "Disposable only"}
                    self.assertEqual(client.post(entry_path, json=payload, headers={"Origin": origin}).status_code, 403)
                    headers = {"Origin": origin, "X-OneJournal-CSRF": csrf, "X-OneJournal-Operation-Id": str(uuid4())}
                    written = client.post(entry_path, json=payload, headers=headers)
                    self.assertEqual(written.status_code, 200, written.text)
                    self.assertEqual(client.post(entry_path, json=payload, headers=headers).json()["replayed"], True)
                    self.assertEqual(post("logout", {}, {"X-OneJournal-CSRF": csrf}).status_code, 200)
                    self.assertEqual(client.get(path).status_code, 401)
            finally:
                if process.poll() is None:
                    process.send_signal(signal.SIGINT)
                try:
                    output, errors = process.communicate(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()  # Only this Popen-owned disposable process.
                    output, errors = process.communicate(timeout=5)
                if process.returncode != 0:
                    print("Disposable service output:", output.decode(), errors.decode())
            self.assertEqual(process.returncode, 0)
