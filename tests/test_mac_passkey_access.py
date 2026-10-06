"""Real signed synthetic WebAuthn ceremonies; never owner credentials/data."""
from __future__ import annotations

import hashlib
import importlib.util
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import duckdb
from fastapi import FastAPI
from fastapi.testclient import TestClient

AVAILABLE = importlib.util.find_spec("webauthn") is not None
if AVAILABLE:
    import cbor2
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from webauthn.helpers import bytes_to_base64url as encode
    from onejournal.passkey_access import (ABSOLUTE_SECONDS, Access, CHALLENGE_SECONDS,
        COOKIE, IDLE_SECONDS, PREFIX, protect_app, provision, validate_origin)

ORIGIN = "https://localhost:9443"


class SyntheticAuthenticator:
    """Test-only device, using a real ES256 key and authenticator wire format."""
    def __init__(self):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.identifier = secrets.token_bytes(32)
        self.handle = None
        self.counter = 0

    def credential(self, options, *, register=False, origin=ORIGIN, flags=None,
                   rp="localhost", cross_origin=False, bad_signature=False):
        client = json.dumps({"type": "webauthn.create" if register else "webauthn.get",
            "challenge": options["challenge"], "origin": origin, "crossOrigin": cross_origin}).encode()
        self.counter += 1
        auth = hashlib.sha256(rp.encode()).digest() + bytes([flags if flags is not None else (0x45 if register else 0x05)]) + self.counter.to_bytes(4, "big")
        response = {"clientDataJSON": encode(client)}
        if register:
            self.handle = options["user"]["id"]
            numbers = self.key.public_key().public_numbers()
            cose = cbor2.dumps({1: 2, 3: -7, -1: 1, -2: numbers.x.to_bytes(32, "big"), -3: numbers.y.to_bytes(32, "big")})
            auth += bytes(16) + len(self.identifier).to_bytes(2, "big") + self.identifier + cose
            response.update(attestationObject=encode(cbor2.dumps({"fmt": "none", "authData": auth, "attStmt": {}})), transports=["internal"])
        else:
            signature = self.key.sign(auth + hashlib.sha256(client).digest(), ec.ECDSA(hashes.SHA256()))
            response.update(authenticatorData=encode(auth), signature=encode(b"invalid" if bad_signature else signature), userHandle=self.handle)
        return {"id": encode(self.identifier), "rawId": encode(self.identifier), "type": "public-key", "response": response, "clientExtensionResults": {}}


@unittest.skipUnless(AVAILABLE, "Install requirements-security.lock to run security tests; CI does so.")
class MacPasskeyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.root.chmod(0o700)
        self.journal = self.root / "journal.duckdb"
        self.journal.write_bytes(b"synthetic journal sentinel")
        self.journal.chmod(0o600)
        self.store = self.root / "access.duckdb"
        self.grant = self.root / "enrollment.txt"
        provision(self.store, self.journal, ORIGIN, self.grant)
        self.secret = self.grant.read_text().strip()
        self.now = [time.time()]
        self.access = Access(self.store, self.journal, ORIGIN, clock=lambda: self.now[0])
        self.calls = []
        app = FastAPI()
        @app.get("/private")
        @app.get("/export.csv")
        def read():
            self.calls.append("read")
            return {"synthetic": True}
        @app.post("/private")
        def write():
            self.calls.append("write")
            return {"saved": True}
        self.client = TestClient(protect_app(app, self.access), base_url=ORIGIN)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.device = SyntheticAuthenticator()

    def post(self, suffix, value=None, **kwargs):
        headers = {"Origin": ORIGIN, **kwargs.pop("headers", {})}
        return self.client.post(PREFIX+"/"+suffix, json={} if value is None else value, headers=headers, **kwargs)

    def register(self, device=None, **credential_options):
        device = device or self.device
        state = self.client.get(PREFIX+"/session").json()
        headers = {"X-OneJournal-CSRF": state["csrf"]} if state["authenticated"] else {}
        grant = {} if state["authenticated"] else {"enrollment_secret": self.secret}
        options = self.post("register/options", grant, headers=headers)
        self.assertEqual(options.status_code, 200, options.text)
        options = options.json()
        return self.post("register/verify", {**grant, "ceremony": options["ceremony"],
            "credential": device.credential(options["options"], register=True, **credential_options)}, headers=headers)

    def login(self, **credential_options):
        options = self.post("login/options")
        self.assertEqual(options.status_code, 200, options.text)
        options = options.json()
        value = {"ceremony": options["ceremony"], "credential": self.device.credential(options["options"], **credential_options)}
        return self.post("login/verify", value), value

    def ready(self):
        self.assertEqual(self.register().status_code, 200)
        result, _ = self.login()
        self.assertEqual(result.status_code, 200, result.text)
        return self.client.get(PREFIX+"/session").json()["csrf"]

    def test_signed_login_session_csrf_logout_and_replay(self):
        self.assertEqual(self.client.get("/private").status_code, 401)
        self.assertEqual(self.client.get("/export.csv").status_code, 401)
        self.assertEqual(self.client.get("/openapi.json").status_code, 401)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.register().status_code, 200)
        result, value = self.login()
        self.assertEqual(result.status_code, 200, result.text)
        cookie = result.headers["set-cookie"]
        for attribute in ("Secure", "HttpOnly", "SameSite=strict", "Path=/"):
            self.assertIn(attribute, cookie)
        self.assertNotIn("Domain=", cookie)
        self.assertEqual(self.client.get("/private").status_code, 200)
        self.assertEqual(self.client.post("/private", json={}, headers={"Origin": ORIGIN}).status_code, 403)
        csrf = self.client.get(PREFIX+"/session").json()["csrf"]
        self.assertEqual(self.client.get(PREFIX+"/session").json()["expires_in_seconds"], IDLE_SECONDS)
        self.assertEqual(self.client.post("/private", json={}, headers={"Origin": ORIGIN, "X-OneJournal-CSRF": csrf}).status_code, 200)
        self.assertEqual(self.post("login/verify", value).status_code, 403)
        self.assertEqual(self.post("logout", headers={"X-OneJournal-CSRF": csrf}).status_code, 200)
        self.assertEqual(self.client.get("/private").status_code, 401)
        self.assertEqual(self.access.sessions, {})
        self.assertEqual(self.journal.read_bytes(), b"synthetic journal sentinel")

    def test_invalid_signed_identity_origin_uv_rp_and_signature(self):
        self.assertEqual(self.register().status_code, 200)
        for changes in ({"origin": "https://attacker.invalid"}, {"flags": 1},
                        {"rp": "attacker.invalid"}, {"cross_origin": True}, {"bad_signature": True}):
            with self.subTest(changes=changes):
                self.assertEqual(self.login(**changes)[0].status_code, 403)
                self.assertFalse(self.client.get(PREFIX+"/session").json()["authenticated"])
        self.assertEqual(self.post("login/options").status_code, 429)
        self.now[0] += 901
        self.device.handle = encode(b"wrong owner")
        self.assertEqual(self.login()[0].status_code, 403)
        self.assertEqual(self.calls, [])

    def test_registration_origin_uv_embedding_and_grant_validation(self):
        for changes in ({"origin": "https://attacker.invalid"}, {"flags": 0x41}, {"cross_origin": True}):
            self.assertEqual(self.register(**changes).status_code, 403)
        self.assertEqual(self.post("register/options", {"enrollment_secret": "x"*43}).status_code, 403)
        self.now[0] += 601
        self.assertEqual(self.post("register/options", {"enrollment_secret": self.secret}).status_code, 403)
        self.assertEqual(self.access.con.execute("SELECT COUNT(*) FROM passkeys").fetchone()[0], 0)

    def test_host_origin_fetch_site_and_request_limits(self):
        for headers in ({"Host": "127.0.0.1:9443"}, {"Origin": "https://localhost:9444"},
                        {"Sec-Fetch-Site": "cross-site"}, {"X-Forwarded-Host": "localhost:9443"}):
            self.assertEqual(self.client.get(PREFIX+"/session", headers=headers).status_code, 403)
        self.assertEqual(self.client.post(PREFIX+"/login/options", json={}).status_code, 403)
        self.assertEqual(self.client.post(PREFIX+"/login/options", data="x", headers={"Origin": ORIGIN}).status_code, 415)
        self.assertEqual(self.post("login/verify", {"padding": "x"*16385}).status_code, 413)
        self.assertEqual(self.post("login/verify", {"ceremony": [], "credential": None}).status_code, 403)

    def test_expiry_polling_does_not_keep_session_alive_and_absolute_limit(self):
        self.ready()
        self.now[0] += IDLE_SECONDS-1
        state = self.client.get(PREFIX+"/session").json()
        self.assertTrue(state["authenticated"])
        self.assertEqual(state["expires_in_seconds"], 1)
        self.now[0] += 1
        self.assertEqual(self.client.get("/private").status_code, 401)
        self.assertIsNone(self.client.get(PREFIX+"/session").json()["expires_in_seconds"])
        self.assertEqual(self.login()[0].status_code, 200)
        for _ in range(ABSOLUTE_SECONDS // 600):
            self.now[0] += 600
            result = self.client.get("/private")
        self.assertEqual(result.status_code, 401)

    def test_expired_challenge_consumed_grant_duplicate_and_backup_csrf(self):
        pending = self.post("register/options", {"enrollment_secret": self.secret}).json()
        self.now[0] += CHALLENGE_SECONDS
        self.assertEqual(self.post("register/verify", {"enrollment_secret": self.secret, "ceremony": pending["ceremony"],
            "credential": self.device.credential(pending["options"], register=True)}).status_code, 403)
        self.ready()
        self.assertEqual(self.post("register/options").status_code, 403)
        self.assertEqual(self.register().status_code, 403)  # Duplicate cannot abort audit transaction.
        self.assertEqual(self.register(SyntheticAuthenticator()).status_code, 200)
        self.assertIsNone(self.access.con.execute("SELECT enrollment_hash FROM access_meta").fetchone()[0])
        self.now[0] += 301
        csrf = self.client.get(PREFIX+"/session").json()["csrf"]
        self.assertEqual(self.post("register/options", headers={"X-OneJournal-CSRF": csrf}).status_code, 403)

    def test_store_binding_permissions_and_no_overwrite(self):
        with self.assertRaises(ValueError):
            provision(self.store, self.journal, ORIGIN, self.root/"another.txt")
        for origin in ("http://localhost:9443", "https://127.0.0.1:9443", "https://localhost:9443/"):
            with self.assertRaises(ValueError): validate_origin(origin)
        with self.assertRaises(ValueError): Access(self.store, self.journal, "https://localhost:9444")
        self.store.chmod(0o644)
        with self.assertRaises(ValueError): Access(self.store, self.journal, ORIGIN)
        self.store.chmod(0o600)
        self.assertEqual(self.grant.stat().st_mode & 0o777, 0o600)

    def test_recovery_revocation_restart_and_value_free_audit(self):
        self.ready()
        # DuckDB's cross-process writer lock prevents the operator CLI resetting
        # an active server. Never use same-process helpers for active recovery.
        script = "from pathlib import Path; from onejournal.passkey_access import provision; import sys; provision(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], Path(sys.argv[4]), recover=True)"
        attempt = subprocess.run([sys.executable, "-c", script, str(self.store), str(self.journal), ORIGIN,
            str(self.root/"blocked-recovery.txt")], capture_output=True, timeout=10)
        self.assertNotEqual(attempt.returncode, 0)
        self.assertFalse((self.root/"blocked-recovery.txt").exists())
        self.access.close()
        # Recovery runs offline; a new process cannot inherit old sessions.
        output = self.root/"recovery.txt"
        provision(self.store, self.journal, ORIGIN, output, recover=True)
        self.access = Access(self.store, self.journal, ORIGIN)
        # The wrapper still owns the original Access; close the fresh reader explicitly.
        try:
            self.assertEqual(self.access.sessions, {})
            self.assertEqual(self.access.con.execute("SELECT COUNT(*) FROM passkeys").fetchone()[0], 0)
            audit = self.access.con.execute("SELECT action, outcome FROM access_audit").fetchall()
            self.assertIn(("offline_recovery", "accepted"), audit)
            self.assertTrue(all(action in {"offline_provision", "register", "login", "offline_recovery"} and outcome == "accepted" for action, outcome in audit))
            self.assertNotEqual(self.secret, output.read_text().strip())
        finally:
            self.access.close()

    def test_existing_journal_api_is_denied_before_financial_or_audit_work(self):
        from scripts.journal.init_journal_db import init_schema
        from onejournal.api.local_owner_journal import create_local_owner_journal_app
        journal = self.root/"real-schema.duckdb"
        init_schema(journal)
        journal.chmod(0o600)
        state = self.root/"real-schema-access.duckdb"
        provision(state, journal, ORIGIN, self.root/"real-schema-grant.txt")
        original = journal.read_bytes()
        with TestClient(protect_app(create_local_owner_journal_app(journal_db_path=journal), Access(state, journal, ORIGIN)), base_url=ORIGIN) as client:
            for path in ("/api/v5/local-owner/entries", "/api/v1/local-owner/portfolio/current", "/api/v1/local-owner/reports/realized-history.csv", "/docs"):
                self.assertEqual(client.get(path).status_code, 401)
        self.assertEqual(journal.read_bytes(), original)

    def test_backup_limit_is_rechecked_when_pending_registration_finishes(self):
        csrf = self.ready()
        headers = {"X-OneJournal-CSRF": csrf}
        pending = []
        for _ in range(5):
            options = self.post("register/options", headers=headers).json()
            device = SyntheticAuthenticator()
            pending.append({"ceremony": options["ceremony"], "credential": device.credential(options["options"], register=True)})
        for value in pending[:4]:
            self.assertEqual(self.post("register/verify", value, headers=headers).status_code, 200)
        self.assertEqual(self.post("register/verify", pending[4], headers=headers).status_code, 403)
        self.assertEqual(self.access.con.execute("SELECT COUNT(*) FROM passkeys").fetchone()[0], 5)

    def test_release_authority_requires_explicit_owner_local_mode_before_provision(self):
        from scripts.web import run_mac_passkey_prototype as launcher
        config = SimpleNamespace(broker_authorization=self.root/"synthetic-authority.json",
            reporting_authorization=None, web_port=9443, journal_db=self.journal)
        args = ["provision", "--web-config", str(self.root/"synthetic-config.json"),
                "--security-db", str(self.root/"new-security.duckdb"),
                "--enrollment-file", str(self.root/"new-enrollment.txt")]
        with patch.object(launcher, "load_config", return_value=config), \
                patch("onejournal.passkey_access.provision") as provision_mock, \
                redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
            self.assertEqual(launcher.main(args), 1)
            provision_mock.assert_not_called()
            self.assertEqual(launcher.main([*args, "--owner-local"]), 0)
            provision_mock.assert_called_once()
        self.assertFalse((self.root/"new-security.duckdb").exists())
        self.assertFalse((self.root/"new-enrollment.txt").exists())


if __name__ == "__main__":
    unittest.main()
