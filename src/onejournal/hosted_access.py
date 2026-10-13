"""Hosted private-owner access; independent PostgreSQL store and fresh RP binding.

One worker is deliberate: sessions/challenges are ephemeral and a PostgreSQL
lease rejects a second worker. Restart/recovery invalidates every session.
"""
from __future__ import annotations

import hmac
import ipaddress
import os
from pathlib import Path
import re
import secrets
import stat
from threading import RLock
import time
from urllib.parse import urlsplit

from onejournal.journal.storage import PostgresTarget, connect, validate_runtime_role
from onejournal.passkey_access import Access, ENROLLMENT_SECONDS, digest

CONTRACT = "onejournal.hosted-passkey.v1"
LEASE = 731022
SECURITY_SQL = """
CREATE SCHEMA main;
SET search_path=main,pg_catalog;
CREATE TABLE access_meta (version text, origin text, journal_digest text,
    user_handle bytea, enrollment_hash text, enrollment_expires double precision, generation bigint);
CREATE TABLE passkeys (credential_id text PRIMARY KEY, public_key bytea NOT NULL, sign_count bigint NOT NULL);
CREATE TABLE access_failures (occurred_at double precision NOT NULL);
CREATE TABLE access_audit (occurred_at double precision NOT NULL, action text NOT NULL, outcome text NOT NULL);
CREATE TABLE access_denial_counts (minute bigint NOT NULL, action text NOT NULL, event_count bigint NOT NULL,
    PRIMARY KEY (minute, action));
"""


def validate_hosted_origin(origin: str) -> str:
    try:
        p = urlsplit(origin)
        host = p.hostname or ""
        if (p.scheme != "https" or p.port is not None or p.username or p.password
                or p.path or p.query or p.fragment or origin != "https://" + host
                or len(host) > 253 or "." not in host or host.endswith(".localhost")
                or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in host.split("."))):
            raise ValueError
        try:
            ipaddress.ip_address(host)
        except ValueError:
            return origin
    except (ValueError, TypeError):
        pass
    raise ValueError("Hosted access requires one exact HTTPS DNS origin without a port.")


def journal_binding(target: PostgresTarget) -> str:
    with connect(target, read_only=True) as con:
        rows = con.execute("SELECT binding_uid FROM hosted_schema_meta").fetchall()
    if len(rows) != 1:
        raise ValueError("Hosted journal binding is unavailable.")
    return digest(str(rows[0][0]))


def provision(target: PostgresTarget, journal: PostgresTarget, origin: str,
              enrollment_file: Path, *, recover=False):
    """Explicit offline operation; never run during startup or request handling."""
    validate_hosted_origin(origin)
    from psycopg.conninfo import conninfo_to_dict
    if conninfo_to_dict(target.dsn)["dbname"] == conninfo_to_dict(journal.dsn)["dbname"]:
        raise ValueError("Use separate journal and security databases.")
    binding = journal_binding(journal)
    parent = enrollment_file.parent
    if (parent.is_symlink() or not parent.is_dir() or parent.stat().st_uid != os.getuid()
            or stat.S_IMODE(parent.stat().st_mode) != 0o700):
        raise ValueError("Use an existing owner-only enrollment directory (0700).")
    if not enrollment_file.is_absolute() or enrollment_file.exists() or enrollment_file.is_symlink():
        raise ValueError("Enrollment output must be a new owner-only file.")
    token = secrets.token_urlsafe(32)
    fd = os.open(enrollment_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    try:
        with connect(target) as con:
            if not con.execute("SELECT pg_try_advisory_lock(?)", [LEASE]).fetchone()[0]:
                raise ValueError("Stop the hosted service before provisioning or recovery.")
            con.execute("BEGIN")
            if recover:
                rows = con.execute("SELECT version, origin, journal_digest FROM access_meta").fetchall()
                if rows != [(CONTRACT, origin, binding)]:
                    raise ValueError("Recovery binding does not match.")
                con.execute("DELETE FROM passkeys")
                con.execute("DELETE FROM access_failures")
                con.execute("UPDATE access_meta SET enrollment_hash=?, enrollment_expires=?, generation=generation+1",
                            [digest(token), time.time() + ENROLLMENT_SECONDS])
            else:
                # CREATE SCHEMA fails on an existing store: nothing is overwritten.
                con.execute(SECURITY_SQL)
                con.execute("INSERT INTO access_meta VALUES (?, ?, ?, ?, ?, ?, 1)",
                    [CONTRACT, origin, binding, secrets.token_bytes(32), digest(token), time.time()+ENROLLMENT_SECONDS])
            con.execute("INSERT INTO access_audit VALUES (?, ?, 'accepted')",
                        [time.time(), "offline_recovery" if recover else "offline_provision"])
            with os.fdopen(fd, "w", encoding="utf-8") as out:
                fd = -1
                out.write(token + "\n")
                out.flush()
                os.fsync(out.fileno())
            con.execute("COMMIT")
    except Exception:
        if fd >= 0:
            os.close(fd)
        enrollment_file.unlink(missing_ok=True)
        raise


class HostedAccess(Access):
    contract = CONTRACT
    rp_name = "OneJournal private workspace"

    def audit(self, action, outcome):
        if outcome == "denied":
            count = self.con.execute("INSERT INTO access_denial_counts VALUES (?, ?, 1) ON CONFLICT (minute,action) DO UPDATE SET event_count=access_denial_counts.event_count+1 RETURNING event_count",
                                     [int(self.clock() // 60), action]).fetchone()[0]
            if count != 1:
                return
        super().audit(action, outcome)

    def __init__(self, target: PostgresTarget, journal: PostgresTarget, origin: str,
                 proxy_secret: str, *, clock=time.time):
        validate_runtime_role(target, security=True)
        self.origin = validate_hosted_origin(origin)
        self.host = urlsplit(origin).netloc
        self.rp_id = self.host
        if not isinstance(proxy_secret, str) or re.fullmatch(r"[A-Za-z0-9_-]{43,128}", proxy_secret) is None:
            raise ValueError("A private random proxy secret is required.")
        self.proxy_secret = proxy_secret
        self.clock, self.lock = clock, RLock()
        self.con = connect(target)
        try:
            if not self.con.execute("SELECT pg_try_advisory_lock(?)", [LEASE]).fetchone()[0]:
                raise ValueError("Hosted access permits exactly one worker.")
            rows = self.con.execute("SELECT version, origin, journal_digest, user_handle FROM access_meta").fetchall()
            if len(rows) != 1 or rows[0][:3] != (CONTRACT, origin, journal_binding(journal)):
                raise ValueError("Hosted access binding does not match.")
            self.user_handle = bytes(rows[0][3])
            if len(self.user_handle) != 32:
                raise ValueError("Hosted owner binding is invalid.")
        except Exception:
            self.con.close()
            raise
        self.sessions, self.ceremonies = {}, {}

    def request_allowed(self, request):
        return (super().request_allowed(request)
                and request.client is not None and request.client.host in {"127.0.0.1", "::1"}
                and hmac.compare_digest(request.headers.get("x-onejournal-proxy", "").encode(), self.proxy_secret.encode()))
