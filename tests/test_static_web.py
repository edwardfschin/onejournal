"""Static shell and signed private API integration; disposable evidence only."""
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_mac_passkey_access import AVAILABLE, ORIGIN, SyntheticAuthenticator

if AVAILABLE:
    from onejournal.static_web import serve_static_web, static_routes
    from onejournal.passkey_access import Access, IDLE_SECONDS, PREFIX, protect_app, provision


def artifact(root):
    root.mkdir()
    for name in ("assets", "fonts"):
        (root / name).mkdir()
    (root / "index.html").write_text('<!doctype html><title>OneJournal synthetic shell</title><div id="root"></div>')
    (root / "assets" / "test.js").write_text('console.log("synthetic asset")')
    (root / "fonts" / "font.woff2").write_bytes(b"synthetic font")
    (root / "favicon.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
    names = ("portfolio", "trades", "journal", "reports", "data", "settings")
    document = {"contract_version": "onejournal.static-web.v1", "passkey_required": True,
                "routes": ["/demo", "/local/today"] + [f"/{mode}/{name}" for mode in ("demo", "local") for name in names],
                "redirects": [{"source": source, "destination": destination} for source, destination in
                    {"/": "/demo", **{f"/{name}": f"/demo/{name}" for name in names},
                     **{f"/{name}/local": f"/local/{name}" for name in ("portfolio", "journal", "reports")}}.items()]}
    (root / "onejournal-static-web.json").write_text(json.dumps(document))
    return document


@unittest.skipUnless(AVAILABLE, "Install requirements-security.lock for the private static integration checks.")
class StaticWebTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.root.chmod(0o700)
        self.dist = self.root / "copied-dist"
        self.document = artifact(self.dist)
        self.journal = self.root / "journal.duckdb"
        self.journal.write_bytes(b"synthetic journal sentinel")
        self.journal.chmod(0o600)
        self.store = self.root / "security.duckdb"
        self.grant = self.root / "grant.txt"
        provision(self.store, self.journal, ORIGIN, self.grant)
        self.now = [time.time()]
        self.access = Access(self.store, self.journal, ORIGIN, clock=lambda: self.now[0])
        self.calls = []
        api = FastAPI()
        @api.get("/api/v5/local-owner/journal/search")
        @api.get("/api/v1/local-owner/reports/export.csv")
        def read():
            self.calls.append("read")
            return {"synthetic": True}
        @api.post("/api/v5/local-owner/journal/entries")
        def write():
            self.calls.append("write")
            return {"saved": True}
        self.app = serve_static_web(protect_app(api, self.access), self.dist)
        self.client = TestClient(self.app, base_url=ORIGIN)
        self.client.__enter__()
        self.client_open = True
        self.addCleanup(lambda: self.client.__exit__(None, None, None) if self.client_open else None)
        self.device = SyntheticAuthenticator()
        self.registered = False

    def post(self, suffix, value):
        return self.client.post(PREFIX + "/" + suffix, json=value, headers={"Origin": ORIGIN})

    def login(self):
        device = self.device
        if not self.registered:
            secret = self.grant.read_text().strip()
            options = self.post("register/options", {"enrollment_secret": secret}).json()
            response = self.post("register/verify", {"enrollment_secret": secret, "ceremony": options["ceremony"],
                "credential": device.credential(options["options"], register=True)})
            self.assertEqual(response.status_code, 200, response.text)
            self.registered = True
        options = self.post("login/options", {}).json()
        response = self.post("login/verify", {"ceremony": options["ceremony"], "credential": device.credential(options["options"])})
        self.assertEqual(response.status_code, 200, response.text)
        for flag in ("Secure", "HttpOnly", "SameSite=strict", "Path=/"):
            self.assertIn(flag, response.headers["set-cookie"])
        return self.client.get(PREFIX + "/session").json()["csrf"]

    def test_shell_assets_routes_and_redirects_are_public_but_never_private_state(self):
        for route in self.document["routes"]:
            response = self.client.get(route)
            self.assertEqual(response.status_code, 200, route)
            self.assertIn('id="root"', response.text)
            self.assertEqual(response.headers["cache-control"], "no-store")
            self.assertEqual(self.client.head(route).content, b"")
        for path in ("/assets/test.js", "/fonts/font.woff2", "/favicon.svg"):
            self.assertEqual(self.client.get(path).status_code, 200)
        for entry in self.document["redirects"]:
            response = self.client.get(entry["source"] + "?q=synthetic", follow_redirects=False)
            self.assertEqual(response.status_code, 307)
            self.assertEqual(response.headers["location"], entry["destination"] + "?q=synthetic")
        for path in ("/api/v5/local-owner/journal/search", "/api/v1/local-owner/reports/export.csv", "/api/not-real", "/docs", "/.env", "/onejournal-static-web.json"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 401, path)
            self.assertNotIn('<html', response.text)
        self.assertEqual(self.calls, [])

    def test_signed_access_csrf_logout_and_idle_expiry_survive_static_mount(self):
        csrf = self.login()
        self.assertEqual(self.client.get('/api/v5/local-owner/journal/search').status_code, 200)
        self.assertEqual(self.client.get('/api/v1/local-owner/reports/export.csv').status_code, 200)
        path = '/api/v5/local-owner/journal/entries'
        self.assertEqual(self.client.post(path, json={}, headers={"Origin": ORIGIN}).status_code, 403)
        headers = {"Origin": ORIGIN, "X-OneJournal-CSRF": csrf}
        self.assertEqual(self.client.post(path, json={}, headers=headers).status_code, 200)
        self.assertEqual(self.client.get('/api/not-real').status_code, 404)
        self.assertEqual(self.client.post(PREFIX + '/logout', json={}, headers=headers).status_code, 200)
        self.assertEqual(self.client.get('/api/v5/local-owner/journal/search').status_code, 401)
        self.login()
        self.now[0] += IDLE_SECONDS + 1
        self.assertEqual(self.client.get('/local/reports').status_code, 200)
        self.assertEqual(self.client.get('/api/v1/local-owner/reports/export.csv').status_code, 401)
        self.assertEqual(self.journal.read_bytes(), b"synthetic journal sentinel")

    def test_host_origin_and_asset_traversal_cannot_widen_access(self):
        for path in ('/local/reports', '/assets/test.js', PREFIX + '/session'):
            for headers in ({"Host": "attacker.invalid"}, {"Origin": "https://attacker.invalid"}, {"X-Forwarded-Host": "localhost:9443"}):
                self.assertEqual(self.client.get(path, headers=headers).status_code, 403)
        outside = self.root / 'secret.txt'
        outside.write_text('synthetic outside sentinel')
        (self.dist / 'assets' / 'link.txt').symlink_to(outside)
        for path in ('/assets/link.txt', '/assets/%2e%2e/secret.txt', '/fonts/missing.woff2'):
            response = self.client.get(path)
            self.assertNotEqual(response.status_code, 200)
            self.assertNotIn('synthetic outside sentinel', response.text)

    def test_missing_wrong_or_unprotected_artifact_is_rejected(self):
        with self.assertRaises(ValueError):
            serve_static_web(FastAPI(), self.dist)
        file = self.dist / 'onejournal-static-web.json'
        for changes in ({"passkey_required": False}, {"routes": ["/api/evil"]}, {"redirects": []}, {"contract_version": "unknown"}):
            file.write_text(json.dumps({**self.document, **changes}))
            with self.assertRaises(ValueError):
                static_routes(self.dist)
        file.unlink()
        with self.assertRaises(ValueError):
            static_routes(self.dist)

    def test_mounted_api_lifespan_closes_access_and_revokes_sessions(self):
        self.login()
        with patch.object(self.access, 'close', wraps=self.access.close) as close:
            self.client.__exit__(None, None, None)
            self.client_open = False
            self.assertEqual(close.call_count, 1)
            self.assertEqual(self.access.sessions, {})
        # Cleanup is safe after an already-finished TestClient lifespan.


if __name__ == '__main__':
    unittest.main()
