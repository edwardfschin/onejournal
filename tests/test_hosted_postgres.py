"""Actual PostgreSQL integration. Only unique synthetic databases are created.

Set ONEJOURNAL_TEST_PG_DSN to an operator on a disposable local cluster.
Absent PostgreSQL is an explicit skip, never claimed as rehearsal acceptance.
"""
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
import os
from pathlib import Path
import secrets
import tempfile
import unittest
from uuid import uuid4

import duckdb
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo, conninfo_to_dict
from fastapi.testclient import TestClient

from onejournal.api.local_owner_journal import create_local_owner_journal_app
from onejournal.api.broker_current_position_contracts import BrokerCurrentFinancialReleaseAuthorization
from onejournal.hosted_access import HostedAccess, provision, validate_hosted_origin
from onejournal.hosted_schema import install_empty, validate, schema_bytes
from onejournal.journal.storage import PostgresTarget, connect, _postgres_sql, validate_runtime_role
from onejournal.journal.migrations import apply_schema_migrations
from onejournal.journal.broker_current_position_valuation_repository import persist_broker_current_position_valuation_run, calculate_broker_current_position_result_fingerprint
from onejournal.journal.phase1_reporting_repository import persist_reporting_release, load_reporting_release, calculate_report_release_fingerprint, ReportingReleaseAuthorization
from onejournal.instruments import InstrumentIdentity
from onejournal.pnl.position_reconciliation import BrokerPositionRecord, BrokerPositionSnapshot
from onejournal.pnl.broker_current_position_valuation import build_broker_current_position_valuation
from onejournal.passkey_access import PREFIX, protect_app, IDLE_SECONDS
from onejournal.static_web import serve_static_web
from test_static_web import artifact
from test_mac_passkey_access import SyntheticAuthenticator
import test_phase1_reporting_repository as reporting_fixture
from scripts.web.prepare_hosted_schema import compile_schema

ADMIN = os.environ.get("ONEJOURNAL_TEST_PG_DSN")
ORIGIN = "https://journal.example.test"
PROXY = "synthetic-proxy-header-" + "x" * 43


class HostedBoundaryUnitTests(unittest.TestCase):
    def test_exact_rp_and_parameter_conversion(self):
        self.assertEqual(validate_hosted_origin(ORIGIN), ORIGIN)
        for value in ("http://journal.example.test", "https://localhost:4173", "https://127.0.0.1", "https://journal.example.test/", "https://Journal.example.test", "https://journal.example.test:443"):
            with self.assertRaises(ValueError):
                validate_hosted_origin(value)
        self.assertEqual(_postgres_sql("SELECT '?', ? -- ?\n, '50%'", True), "SELECT '?', %s -- ?\n, '50%%'")
        with self.assertRaises(ValueError):
            PostgresTarget("host=remote.example dbname=test user=test")

    def test_baseline_is_reproducible_and_history_extension_is_excluded(self):
        self.assertEqual(compile_schema().encode(), schema_bytes())
        self.assertNotIn(b"historical_activity_observations", schema_bytes())
        self.assertIn(b"supersedes_review_uid) REFERENCES journal_reviews", schema_bytes())
        self.assertIn(b"previous_activation_uid) REFERENCES phase1_journal_history_revision_activations", schema_bytes())

    @unittest.skipUnless(os.environ.get("ONEJOURNAL_TEST_CADDY_BIN"), "Local Caddy binary required for proxy rehearsal.")
    def test_actual_proxy_overwrites_authority_and_removes_forwarding_headers(self):
        import json
        import socket
        import subprocess
        import threading
        import time
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from urllib.request import Request, urlopen
        class Echo(BaseHTTPRequestHandler):
            def do_GET(self):
                data = json.dumps(dict(self.headers)).encode()
                self.send_response(200)
                self.end_headers()
                self.wfile.write(data)
            def log_message(self, *_):
                pass
        backend = ThreadingHTTPServer(('127.0.0.1', 0), Echo)
        thread = threading.Thread(target=backend.serve_forever, daemon=True)
        thread.start()
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        with tempfile.TemporaryDirectory(prefix="onejournal-proxy-test-") as tmp:
            root = Path(tmp)
            template = (Path(__file__).resolve().parents[1] / 'config/hosted/Caddyfile.example').read_text()
            config = root / 'Caddyfile'
            config.write_text(template.replace('{$ONEJOURNAL_DOMAIN} {', f'http://journal.example.test:{port} {{\n    bind 127.0.0.1').replace('127.0.0.1:8766', f'127.0.0.1:{backend.server_port}'))
            environment = {**os.environ, 'ONEJOURNAL_DOMAIN': 'journal.example.test', 'ONEJOURNAL_PROXY_SECRET': PROXY,
                           'XDG_DATA_HOME': str(root / 'data'), 'XDG_CONFIG_HOME': str(root / 'config')}
            process = subprocess.Popen([os.environ['ONEJOURNAL_TEST_CADDY_BIN'], 'run', '--config', str(config), '--adapter', 'caddyfile'],
                                       env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                result = None
                for _ in range(30):
                    try:
                        request = Request(f'http://127.0.0.1:{port}/', headers={'Host': 'journal.example.test', 'X-OneJournal-Proxy': 'forged',
                            'Forwarded': 'for=attacker', 'X-Forwarded-Proto': 'https', 'X-Forwarded-Host': 'attacker.invalid', 'X-Forwarded-For': '1.2.3.4'})
                        with urlopen(request, timeout=2) as response:
                            result = {k.lower(): v for k, v in json.load(response).items()}
                        break
                    except OSError:
                        time.sleep(.1)
                self.assertIsNotNone(result, 'Temporary proxy did not start.')
                self.assertEqual(result['host'], 'journal.example.test')
                self.assertEqual(result['x-onejournal-proxy'], PROXY)
                for name in ['forwarded', 'x-forwarded-for', 'x-forwarded-host', 'x-forwarded-proto']:
                    self.assertNotIn(name, result)
            finally:
                process.terminate()
                process.wait(timeout=5)
                backend.shutdown()
                backend.server_close()


@unittest.skipUnless(ADMIN, "Requires an actual disposable PostgreSQL cluster.")
class HostedPostgresTests(unittest.TestCase):
    def setUp(self):
        PostgresTarget(ADMIN)  # Refuse a remote cluster before any write.
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.root.chmod(0o700)
        self.suffix = uuid4().hex
        self.names = ["oj_test_j_" + self.suffix, "oj_test_s_" + self.suffix]
        self.roles = ["oj_test_jr_" + self.suffix, "oj_test_sr_" + self.suffix]
        self.passwords = [secrets.token_urlsafe(32), secrets.token_urlsafe(32)]
        with psycopg.connect(ADMIN, autocommit=True) as admin:
            for name in self.names:
                admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
            for name, password in zip(self.roles, self.passwords):
                admin.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(sql.Identifier(name), sql.Literal(password)))
        self.addCleanup(self.drop_synthetic_targets)
        self.operator_targets = [PostgresTarget(make_conninfo(ADMIN, dbname=name)) for name in self.names]
        self.runtime_targets = [PostgresTarget(make_conninfo(ADMIN, dbname=name, user=role, password=password))
                                for name, role, password in zip(self.names, self.roles, self.passwords)]
        self.journal, self.security = self.runtime_targets
        install_empty(self.operator_targets[0])
        self.source = self.root / "synthetic.duckdb"
        apply_schema_migrations(self.source, target_version="0028")
        self.source.chmod(0o600)
        # Exercise activated append-only views, not only legacy/empty fallback.
        from onejournal.journal.schwab_evidence_assembly import SCHWAB_PHASE1_EVIDENCE_ASSEMBLY_VERSION, SCHWAB_PHASE1_EVIDENCE_ASSEMBLY_V2
        from tests.test_schwab_phase1_evidence_import import synthetic_assembly
        from onejournal.journal.schwab_evidence_import_repository import persist_schwab_phase1_evidence_assembly
        from onejournal.journal.schwab_evidence_materialization import persist_schwab_journal_materialization
        from onejournal.journal.schwab_execution_projection import persist_schwab_execution_projection
        from onejournal.journal.schwab_evidence_v2_repository import persist_schwab_phase1_evidence_assembly_v2, persist_schwab_journal_lifecycle_reconciliation
        from onejournal.journal.schwab_history_revision import persist_schwab_history_revision
        v1 = synthetic_assembly(assembly_version=SCHWAB_PHASE1_EVIDENCE_ASSEMBLY_VERSION)
        persist_schwab_phase1_evidence_assembly(self.source, v1)
        legacy = persist_schwab_journal_materialization(self.source, v1)
        persist_schwab_execution_projection(self.source, materialization_uid=legacy.materialization_uid)
        v2 = synthetic_assembly(assembly_version=SCHWAB_PHASE1_EVIDENCE_ASSEMBLY_V2)
        persist_schwab_phase1_evidence_assembly_v2(self.source, v2)
        persist_schwab_journal_lifecycle_reconciliation(self.source, v2)
        persist_schwab_history_revision(self.source, v2, predecessor_materialization_uid=legacy.materialization_uid)
        instant = datetime(2026, 1, 31, 20, tzinfo=UTC)
        snapshot = BrokerPositionSnapshot(snapshot_uid="synthetic-snapshot", source_broker="schwab",
            connection_uid="synthetic-connection", source_account_id="private-account-id", asof=date(2026, 1, 31),
            retrieved_at=instant, raw_path="synthetic/never-a-live-file", raw_sha256="a"*64,
            account_complete=True, adapter_version="synthetic", positions=(BrokerPositionRecord(
                identity=InstrumentIdentity(asset_class="equity", market_scope="US", currency="USD", symbol="ABC"),
                quantity=Decimal("100"), broker_market_value=Decimal("15000"), broker_unrealized_pnl=Decimal("5000"),
                broker_tax_lot_average_price=Decimal("100")),))
        run = build_broker_current_position_valuation(broker_snapshot=snapshot, evaluated_at=instant,
            max_snapshot_age_seconds=0, currency_quantum_by_currency={"USD": Decimal("0.01")})
        persist_broker_current_position_valuation_run(self.source, run=run, broker_snapshot=snapshot)
        self.broker_auth = BrokerCurrentFinancialReleaseAuthorization(owner_acceptance_uid="synthetic-acceptance",
            valuation_run_uid=run.run_uid, result_fingerprint=calculate_broker_current_position_result_fingerprint(run), accepted_at=instant)
        provisional = replace(reporting_fixture.Phase1ReportingRepositoryTests()._release(), current_valuation_run_uid=run.run_uid,
                              current_result_fingerprint=self.broker_auth.result_fingerprint)
        self.release = replace(provisional, report_release_fingerprint=calculate_report_release_fingerprint(release=provisional))
        self.report_auth = ReportingReleaseAuthorization(self.release.report_release_uid, self.release.report_release_fingerprint, self.release.owner_acceptance_uid)
        with duckdb.connect(str(self.source)) as source:
            persist_reporting_release(source, self.release)
            source.execute("INSERT INTO trade_episodes (episode_uid,source_broker,source_account_id,primary_symbol,asset_class,strategy_type,strategy_label,opened_at,status,fill_count,leg_count,updated_at) VALUES ('episode-1','manual_csv','synthetic-account','ABC','stock','stock_long','Stock Long',TIMESTAMP '2026-01-01 10:00:00','closed',2,1,TIMESTAMP '2026-01-02 10:00:00')")
            with connect(self.operator_targets[0]) as target:
                target.execute("BEGIN")
                target.execute("SET CONSTRAINTS ALL DEFERRED")
                for name, in source.execute("SELECT table_name FROM duckdb_tables() WHERE schema_name='main' ORDER BY table_name").fetchall():
                    rows = source.execute(f'SELECT * FROM "{name}"').fetchall()
                    if rows:
                        placeholders = ','.join('?' for _ in rows[0])
                        target.executemany(f'INSERT INTO "{name}" VALUES ({placeholders})', rows)
                    self.assertEqual(target.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0], len(rows))
                target.execute("COMMIT")
                for name, in source.execute("SELECT view_name FROM duckdb_views() WHERE schema_name='main' AND NOT internal").fetchall():
                    self.assertEqual(target.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0], source.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0], name)
        self.grant = self.root / "grant.txt"
        provision(self.operator_targets[1], self.operator_targets[0], ORIGIN, self.grant)
        for target, role, security in zip(self.operator_targets, self.roles, [False, True]):
            with psycopg.connect(target.dsn, autocommit=True) as con:
                con.execute(sql.SQL("GRANT USAGE ON SCHEMA main TO {}").format(sql.Identifier(role)))
                con.execute(sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA main TO {}").format(sql.Identifier(role)))
                tables = ["access_audit", "access_failures", "passkeys", "access_denial_counts"] if security else ["journal_entries", "journal_entry_revisions", "journal_reviews", "local_owner_api_operation_receipts", "local_owner_api_audit_events", "local_owner_financial_api_audit_events", "phase1_reporting_api_audit_events", "manual_reviews"]
                con.execute(sql.SQL("GRANT INSERT ON {} TO {}").format(sql.SQL(',').join(sql.Identifier('main', name) for name in tables), sql.Identifier(role)))
                con.execute(sql.SQL("GRANT UPDATE ON {} TO {}").format(sql.SQL(',').join(sql.Identifier('main', name) for name in (["access_meta", "passkeys", "access_denial_counts"] if security else ["manual_reviews"])), sql.Identifier(role)))
                if security:
                    con.execute(sql.SQL("GRANT DELETE ON main.access_failures TO {}").format(sql.Identifier(role)))
        self.now = [instant.timestamp() + 3600]  # Access enrollment uses wall time.
        import time
        self.now[0] = time.time()

    def drop_synthetic_targets(self):
        with psycopg.connect(ADMIN, autocommit=True) as admin:
            for name in self.names:
                admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
            for role in self.roles:
                admin.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))

    def api(self, target):
        return create_local_owner_journal_app(journal_db_path=target,
            broker_current_authorization=self.broker_auth, reporting_authorization=self.report_auth)

    def test_guarded_migration_exact_copy_refusals_and_atomic_rollback(self):
        from hashlib import sha256
        from unittest.mock import patch
        from onejournal.hosted_migration import rehearse, relation_proof
        name = 'oj_rehearsal_' + self.suffix
        with psycopg.connect(ADMIN, autocommit=True) as admin:
            admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
        self.names.append(name)
        target = PostgresTarget(make_conninfo(ADMIN, dbname=name))
        install_empty(target)
        pinned = sha256(self.source.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError, 'hash differs'):
            rehearse(self.source, '0' * 64, target)
        with self.assertRaisesRegex(ValueError, 'disposable rehearsal'):
            rehearse(self.source, pinned, self.operator_targets[0])
        with self.assertRaisesRegex(ValueError, 'temporary rehearsal'):
            rehearse(self.source, pinned, PostgresTarget(make_conninfo(ADMIN, host='127.0.0.1', dbname=name)))
        # Reject an extended ledger instead of silently dropping its history.
        import shutil
        extended = self.root / 'extended.duckdb'
        shutil.copyfile(self.source, extended)
        extended.chmod(0o600)
        with duckdb.connect(str(extended)) as con:
            con.execute("UPDATE schema_migrations SET version='0029' WHERE version='0028'")
        with self.assertRaisesRegex(ValueError, 'history is separate'):
            rehearse(extended, sha256(extended.read_bytes()).hexdigest(), target)
        # Force a post-insert mismatch; every target insert must roll back.
        with patch('onejournal.hosted_migration.relation_proof', side_effect=[{}, {'different': True}]):
            with self.assertRaisesRegex(ValueError, 'read-back differs'):
                rehearse(self.source, pinned, target)
        with connect(target, read_only=True) as con:
            tables = con.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='main' AND table_type='BASE TABLE' AND table_name!='hosted_schema_meta'").fetchall()
            for table, in tables:
                self.assertEqual(con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0], 0)
        result = rehearse(self.source, pinned, target)
        self.assertFalse(result['activated'])
        self.assertEqual(sha256(self.source.read_bytes()).hexdigest(), pinned)
        self.assertGreater(len(result['exact_relations']), len(tables))
        with self.assertRaisesRegex(ValueError, 'must be empty'):
            rehearse(self.source, pinned, target)
        with connect(target, read_only=True) as con:
            for table, proof in result['exact_relations'].items():
                self.assertEqual(relation_proof(con.connection, table), proof)
        local, hosted = TestClient(self.api(self.source)), TestClient(self.api(target))
        for path in ['/api/v1/local-owner/portfolio/current',
                     '/api/v1/local-owner/reports/current/accounts',
                     '/api/v1/local-owner/reports/current/positions.csv',
                     '/api/v5/local-owner/journal/search']:
            a, b = local.get(path), hosted.get(path)
            self.assertEqual(a.status_code, 200, a.text)
            self.assertEqual(b.status_code, 200, b.text)
            self.assertEqual(a.content, b.content)

    def test_financial_json_csv_journal_revisions_and_replay_match_duckdb(self):
        validate(self.journal)
        validate_runtime_role(self.journal)
        local, hosted = TestClient(self.api(self.source)), TestClient(self.api(self.journal))
        paths = ["/api/v1/local-owner/portfolio/current", "/api/v1/local-owner/reports/current/accounts",
            "/api/v1/local-owner/reports/current/symbols", "/api/v1/local-owner/reports/current/positions.csv",
            "/api/v1/local-owner/reports/realized-history?from_date=2026-01-01&to_date=2026-01-31",
            "/api/v1/local-owner/reports/realized-history.csv?from_date=2026-01-01&to_date=2026-01-31",
            "/api/v5/local-owner/journal/search", "/api/v5/local-owner/journal/review-queues", "/api/v5/local-owner/journal/trades/episode-1"]
        for path in paths:
            a, b = local.get(path), hosted.get(path)
            self.assertEqual(a.status_code, 200, a.text)
            self.assertEqual(b.status_code, 200, b.text)
            self.assertEqual(a.content, b.content, path)
        entries = "/api/v5/local-owner/journal/entries"
        operation = str(uuid4())
        payload = {"entry_type": "lesson", "episode_uid": "episode-1", "body": "Synthetic learned lesson"}
        headers = {"X-OneJournal-Operation-Id": operation}
        created = hosted.post(entries, json=payload, headers=headers)
        self.assertEqual(created.status_code, 200, created.text)
        self.assertFalse(created.json()["replayed"])
        self.assertTrue(hosted.post(entries, json=payload, headers=headers).json()["replayed"])
        self.assertEqual(hosted.post(entries, json={**payload, "body": "changed"}, headers=headers).status_code, 409)
        uid = created.json()["resource_uid"]
        revised = hosted.post(entries + "/" + uid + "/revisions", json={**payload, "body": "Synthetic revised lesson", "change_reason": "clarified"}, headers={"X-OneJournal-Operation-Id": str(uuid4())})
        self.assertEqual(revised.status_code, 200, revised.text)
        self.assertEqual(revised.json()["revision_no"], 2)
        with connect(self.journal) as con:
            self.assertEqual(load_reporting_release(con, report_release_uid=self.release.report_release_uid), self.release)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM journal_entry_revisions WHERE entry_uid=?", [uid]).fetchone()[0], 2)
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                con.execute("DELETE FROM journal_entry_revisions")

    def test_signed_hosted_access_proxy_csrf_replay_expiry_and_recovery(self):
        access = HostedAccess(self.security, self.journal, ORIGIN, PROXY, clock=lambda: self.now[0])
        dist = self.root / "dist"
        artifact(dist)
        client = TestClient(serve_static_web(protect_app(self.api(self.journal), access), dist), base_url=ORIGIN, client=("127.0.0.1", 51000), headers={"X-OneJournal-Proxy": PROXY})
        with client:
            private = "/api/v1/local-owner/reports/current/positions.csv"
            self.assertEqual(client.get(private).status_code, 401)
            self.assertEqual(client.get("/local/reports").status_code, 200)
            for headers in ({"Host": "attacker.invalid"}, {"X-OneJournal-Proxy": "wrong"}, {"X-Forwarded-Proto": "https"}, {"Origin": "https://attacker.invalid"}):
                self.assertEqual(client.get("/local/reports", headers=headers).status_code, 403)
            with self.assertRaises(ValueError):
                HostedAccess(self.security, self.journal, ORIGIN, PROXY)
            with self.assertRaises(ValueError):
                provision(self.operator_targets[1], self.operator_targets[0], ORIGIN, self.root / "blocked.txt", recover=True)
            device = SyntheticAuthenticator()
            secret = self.grant.read_text().strip()
            def post(suffix, value, headers=None):
                return client.post(PREFIX + "/" + suffix, json=value, headers={"Origin": ORIGIN, **(headers or {})})
            options = post("register/options", {"enrollment_secret": secret}).json()
            registered = post("register/verify", {"enrollment_secret": secret, "ceremony": options["ceremony"], "credential": device.credential(options["options"], register=True, origin=ORIGIN, rp="journal.example.test")})
            self.assertEqual(registered.status_code, 200, registered.text)
            options = post("login/options", {}).json()
            value = {"ceremony": options["ceremony"], "credential": device.credential(options["options"], origin=ORIGIN, rp="journal.example.test")}
            self.assertEqual(post("login/verify", value).status_code, 200)
            self.assertEqual(client.get(private).status_code, 200)
            self.assertEqual(post("login/verify", value).status_code, 403)
            csrf = client.get(PREFIX+"/session").json()["csrf"]
            self.assertEqual(post("logout", {}).status_code, 403)
            self.assertEqual(post("logout", {}, {"X-OneJournal-CSRF": csrf}).status_code, 200)
            self.assertEqual(client.get(private).status_code, 401)
            options = post("login/options", {}).json()
            self.assertEqual(post("login/verify", {"ceremony": options["ceremony"], "credential": device.credential(options["options"], origin=ORIGIN, rp="journal.example.test")}).status_code, 200)
            self.now[0] += IDLE_SECONDS + 1
            self.assertEqual(client.get(private).status_code, 401)
        recovery = self.root / "recovery.txt"
        provision(self.operator_targets[1], self.operator_targets[0], ORIGIN, recovery, recover=True)
        with connect(self.operator_targets[1]) as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM passkeys").fetchone()[0], 0)
            self.assertGreater(con.execute("SELECT COUNT(*) FROM access_audit").fetchone()[0], 0)
        with self.assertRaises(Exception):
            install_empty(self.operator_targets[0])
        validate(self.journal)  # Failed duplicate setup left the previous schema intact.

    def test_encrypted_dump_restore_exactness_tamper_and_nonempty_guard(self):
        from onejournal.hosted_backup import create, restore, decrypt
        password = "synthetic-only backup password with unrelated words"
        backup = self.root / "synthetic-backup.onj"
        binary_dir = Path(os.environ["ONEJOURNAL_TEST_PG_BIN"])
        create(self.journal, self.security, backup, password, binary_directory=binary_dir)
        with self.assertRaises(ValueError):
            restore(self.operator_targets[0], self.operator_targets[1], backup, password,
                    self.root / "would-not-overwrite", binary_directory=binary_dir)
        restored_names = ["oj_test_rj_" + self.suffix, "oj_test_rs_" + self.suffix]
        with psycopg.connect(ADMIN, autocommit=True) as admin:
            for name in restored_names:
                admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        self.names.extend(restored_names)
        targets = [PostgresTarget(make_conninfo(ADMIN, dbname=name)) for name in restored_names]
        result = restore(*targets, backup, password, self.root / "companions", binary_directory=binary_dir)
        self.assertEqual(result, {"restored": True, "exact_relations": True, "activated": False})
        with connect(targets[0], read_only=True) as con:
            self.assertEqual(load_reporting_release(con, report_release_uid=self.release.report_release_uid), self.release)
        damaged = self.root / "tampered.onj"
        data = bytearray(backup.read_bytes())
        data[64] ^= 1
        damaged.write_bytes(data)
        damaged.chmod(0o600)
        for image, secret in ((damaged, password), (backup, "wrong synthetic password of sufficient length")):
            with self.assertRaises(Exception):
                decrypt(image, self.root / "unauthenticated.tar", secret)
            self.assertFalse((self.root / "unauthenticated.tar").exists())
        existing = self.root / "existing-file"
        existing.write_bytes(b"must survive refused overwrite")
        with self.assertRaises(FileExistsError):
            decrypt(backup, existing, password)
        self.assertEqual(existing.read_bytes(), b"must survive refused overwrite")

    def test_complete_hosted_factory_redacts_failures_and_bounds_request_bursts(self):
        from contextlib import redirect_stdout
        import io
        from fastapi.routing import APIRoute
        from onejournal.hosted_site import HostedConfig, configured_app
        dist = self.root / "full-dist"
        artifact(dist)
        config = HostedConfig(ORIGIN, self.journal, self.security, PROXY, dist, None, None)
        app = configured_app(config)
        def failure():
            raise RuntimeError("synthetic private database value must not escape")
        app.router.routes.insert(0, APIRoute("/synthetic-failure", failure))
        output = io.StringIO()
        with TestClient(app, base_url=ORIGIN, client=("127.0.0.1", 51001), headers={"X-OneJournal-Proxy": PROXY}) as client, redirect_stdout(output):
            response = client.get("/synthetic-failure")
            self.assertEqual(response.status_code, 503)
            self.assertNotIn("database value", response.text)
            self.assertNotIn("database value", output.getvalue())
            self.assertEqual(client.get(PREFIX + "/session").json()["contract_version"], "onejournal.hosted-passkey.v1")
            for _ in range(129):
                last = client.get("/favicon.svg")
            self.assertEqual(last.status_code, 429)
            self.assertEqual(last.headers["retry-after"], "10")


if __name__ == "__main__":
    unittest.main()
