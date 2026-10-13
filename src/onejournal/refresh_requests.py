"""Durable owner refresh requests; no broker, journal or publication capability.

A separately activated credential-owner worker claims a request once. A crash
leaves it claimed for operator reconciliation, never automatic redispatch.
Refresh is additive: no reset/rebuild/replace mode is accepted. Current-position
captures are complete dated observations, not quantities to add to older holdings.
Financial append/deduplication remains the downstream import/release boundary.
"""
from datetime import datetime, timezone
from contextlib import contextmanager
import os
from pathlib import Path
import re
import sqlite3
from uuid import UUID

from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict
from onejournal.local_web import private_file

PREFIX = '/api/v1/local-owner/data-refresh'
CONTRACT = 'onejournal.data-refresh.v1'
SCHEMA = '''
PRAGMA application_id=1330268742;
PRAGMA user_version=1;
CREATE TABLE requests (
 id TEXT PRIMARY KEY, provider TEXT NOT NULL, requested_at TEXT NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('queued','capturing','captured','closed','failed')),
 manifest_sha256 TEXT
);
CREATE UNIQUE INDEX one_active_request ON requests((1)) WHERE state IN ('queued','capturing','captured');
'''


class RefreshBusy(ValueError):
    pass


class RefreshRequests:
    def __init__(self, path: Path, provider: str):
        self.path = private_file(path, 'refresh requests', private_parent=True)
        if not re.fullmatch('[a-z][a-z0-9_]{1,31}', provider):
            raise ValueError('Invalid configured provider.')
        self.provider = provider
        with self.connection() as con:
            if con.execute('PRAGMA application_id').fetchone()[0] != 1330268742 or con.execute('PRAGMA user_version').fetchone()[0] != 1:
                raise ValueError('Refresh store has an unsupported schema.')
            if con.execute('SELECT 1 FROM requests WHERE provider!=? LIMIT 1', (provider,)).fetchone():
                raise ValueError('Refresh store belongs to another provider.')

    @classmethod
    def initialize(cls, path: Path, provider: str):
        # Explicit private setup only; runtime startup never creates a store.
        parent = path.parent
        if not path.is_absolute() or parent.is_symlink() or parent.stat().st_mode & 0o777 != 0o700 or parent.stat().st_uid != os.getuid():
            raise ValueError('Use an owner-private directory.')
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        con = sqlite3.connect(path)
        try:
            con.executescript(SCHEMA)
        finally:
            con.close()
        return cls(path, provider)

    @contextmanager
    def connection(self):
        # Recheck permissions and refuse symlinks on each operation.
        private_file(self.path, 'refresh requests', private_parent=True)
        con = sqlite3.connect(self.path.as_uri() + '?mode=rw', uri=True, timeout=5)
        try:
            with con:
                yield con
        finally:
            con.close()

    @staticmethod
    def public(row):
        return None if row is None else dict(zip(('request_id', 'provider', 'requested_at', 'state'), row[:4]))

    def status(self):
        with self.connection() as con:
            row = con.execute('SELECT id,provider,requested_at,state FROM requests ORDER BY rowid DESC LIMIT 1').fetchone()
        return {'contract_version': CONTRACT, 'enabled': True, 'provider': self.provider, 'latest': self.public(row)}

    def request(self, request_id: str):
        if str(UUID(request_id)) != request_id:
            raise ValueError('Use a canonical request UUID.')
        with self.connection() as con:
            con.execute('BEGIN IMMEDIATE')
            prior = con.execute('SELECT id,provider,requested_at,state FROM requests WHERE id=?', (request_id,)).fetchone()
            if prior:
                return self.public(prior)
            if con.execute("SELECT 1 FROM requests WHERE state IN ('queued','capturing','captured')").fetchone():
                raise RefreshBusy('A refresh is already pending.')
            now = datetime.now(timezone.utc).isoformat()
            con.execute('INSERT INTO requests VALUES (?,?,?,\'queued\',NULL)', (request_id, self.provider, now))
            return self.public((request_id, self.provider, now, 'queued'))

    def claim(self):
        """Private worker handoff; the browser cannot call this method."""
        with self.connection() as con:
            con.execute('BEGIN IMMEDIATE')
            row = con.execute("SELECT id,provider,requested_at,state FROM requests WHERE state='queued'").fetchone()
            if row is None:
                return None
            con.execute("UPDATE requests SET state='capturing' WHERE id=?", (row[0],))
            # This is a current-position request, never a history range or order.
            return {**self.public((*row[:3], 'capturing')), 'scope': 'current_positions'}

    def captured(self, request_id: str, acquisition, *, expected_connection_uid: str):
        """Worker records validated acquisition receipt; this is NOT publication.

        The adapter supplies the existing checksum/owner/terms-verified bundle
        and its configured private connection binding, never browser input.
        Only the private store gets the manifest hash, never the browser.
        """
        from onejournal.provider_connectors.external_acquisition import (
            VerifiedExternalProviderAcquisition, SCHWAB_POSITION_EXTERNAL_ACQUISITION_PROFILE)
        if not isinstance(acquisition, VerifiedExternalProviderAcquisition):
            raise ValueError('A verified acquisition bundle is required.')
        manifest = acquisition.manifest
        # Explicit implemented adapter. Future brokers need their own verified
        # profile; generic request/state machinery must not admit them silently.
        if (self.provider != 'schwab' or manifest.provider != self.provider
                or manifest.profile != SCHWAB_POSITION_EXTERNAL_ACQUISITION_PROFILE
                or manifest.acquisition_run_uid != request_id
                or manifest.connection_uid != expected_connection_uid):
            raise ValueError('Acquisition differs from the requested scope.')
        manifest_sha256 = acquisition.manifest_sha256
        if not re.fullmatch('[a-f0-9]{64}', manifest_sha256):
            raise ValueError('Exact acquisition receipt hash is required.')
        with self.connection() as con:
            changed = con.execute("UPDATE requests SET state='captured',manifest_sha256=? WHERE id=? AND state='capturing'",
                                  (manifest_sha256, request_id)).rowcount
            if changed != 1:
                raise ValueError('Request must be claimed before recording capture.')

    def fail(self, request_id: str):
        """Operator fails an interrupted request; never retry automatically.

        Captured evidence and its receipt remain retained. Publication is handled
        by existing financial acceptance, backup and release commands.
        """
        with self.connection() as con:
            changed = con.execute("UPDATE requests SET state='failed' WHERE id=? AND state IN ('queued','capturing')", (request_id,)).rowcount
            if changed != 1:
                raise ValueError('Only an unfinished acquisition can be failed.')

    def finish_review(self, request_id: str):
        """Explicit operator close after review, without claiming publication."""
        with self.connection() as con:
            if con.execute("UPDATE requests SET state='closed' WHERE id=? AND state='captured'", (request_id,)).rowcount != 1:
                raise ValueError('Only captured evidence can complete review.')


class RefreshRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: UUID


def register_routes(app, queue: RefreshRequests | None = None):
    @app.get(PREFIX)
    def status():
        if queue is None:
            return {'contract_version': CONTRACT, 'enabled': False, 'provider': 'schwab', 'latest': None}
        try:
            return queue.status()
        except (OSError, sqlite3.Error, ValueError):
            raise HTTPException(503, 'Refresh status is unavailable.') from None

    @app.post(PREFIX, status_code=202)
    def request_refresh(body: RefreshRequest, request: Request):
        # Even an accidentally unprotected legacy API cannot enqueue work.
        if getattr(request.app.state, 'passkey_access', None) is None:
            raise HTTPException(403, 'Protected owner access is required.')
        if queue is None:
            raise HTTPException(503, 'The broker refresh connection is not activated.')
        try:
            return queue.request(str(body.request_id))
        except RefreshBusy:
            raise HTTPException(409, 'A refresh is already pending. Check its status.') from None
        except (OSError, sqlite3.Error, ValueError):
            raise HTTPException(503, 'Refresh request could not be saved. Check its status before retrying.') from None
