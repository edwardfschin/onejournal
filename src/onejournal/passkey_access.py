"""Single-owner Mac prototype: WebAuthn, revocable sessions, offline recovery.

The dedicated security store is NOT the journal database. This entry point is
localhost/HTTPS only and does not authorize production, providers, or orders.
"""
from __future__ import annotations

from contextlib import contextmanager, asynccontextmanager
from dataclasses import dataclass
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
from threading import RLock
import time
from urllib.parse import urlsplit

import duckdb
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from webauthn import (generate_authentication_options, generate_registration_options,
                      options_to_json, verify_authentication_response, verify_registration_response)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.exceptions import WebAuthnException
from webauthn.helpers.structs import (AuthenticatorSelectionCriteria, ResidentKeyRequirement,
                                     UserVerificationRequirement, PublicKeyCredentialDescriptor)

from onejournal.local_web import private_file

CONTRACT = "onejournal.mac-passkey.v1"
PREFIX = "/api/v1/local-owner/access"
COOKIE = "__Host-onejournal_session"
IDLE_SECONDS = 15 * 60
ABSOLUTE_SECONDS = 8 * 60 * 60
CHALLENGE_SECONDS = 120
ENROLLMENT_SECONDS = 10 * 60
MAX_CEREMONIES = 32
MAX_SESSIONS = 32


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def same_origin_credential(credential):
    # The library validates signed origin/challenge but not embedding policy.
    data = json.loads(base64url_to_bytes(credential["response"]["clientDataJSON"]))
    if not isinstance(data, dict) or data.get("crossOrigin", False) is not False or "topOrigin" in data:
        raise ValueError("Embedded authentication is not allowed")


def validate_origin(origin: str) -> str:
    parsed = urlsplit(origin)
    if (parsed.scheme != "https" or parsed.hostname != "localhost" or
        parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment or
        parsed.port is None or not 1024 <= parsed.port <= 65535 or
        origin != f"https://localhost:{parsed.port}"):
        raise ValueError("Passkey prototype requires one exact https://localhost:PORT origin.")
    return origin


def provision(path: Path, journal: Path, origin: str, enrollment_file: Path, *, recover: bool = False) -> None:
    """Offline-only provisioning. A running process holds the DB write lock."""
    validate_origin(origin)
    private_file(journal, "journal")
    if path.resolve() == journal.resolve() or not path.is_absolute() or path.is_symlink():
        raise ValueError("Use a separate absolute security-store location.")
    if enrollment_file.exists() or enrollment_file.is_symlink() or not enrollment_file.is_absolute():
        raise ValueError("Enrollment output must be a new private file.")
    for folder in {path.parent, enrollment_file.parent}:
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        if folder.is_symlink() or folder.stat().st_mode & 0o777 != 0o700 or folder.stat().st_uid != os.getuid():
            raise ValueError("Security and enrollment directories must be owner-only (0700).")
    if recover:
        private_file(path, "security store", private_parent=True)
    elif path.exists():
        raise ValueError("Security store already exists; nothing was overwritten.")
    token = secrets.token_urlsafe(32)
    # Reserve owner-only output before any durable change; never print the token.
    fd = os.open(enrollment_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    try:
        with duckdb.connect(str(path)) as con:
            path.chmod(0o600)
            con.execute("BEGIN TRANSACTION")
            if not recover:
                con.execute("CREATE TABLE access_meta (version VARCHAR, origin VARCHAR, journal_digest VARCHAR, user_handle BLOB, enrollment_hash VARCHAR, enrollment_expires DOUBLE, generation BIGINT)")
                con.execute("CREATE TABLE passkeys (credential_id VARCHAR PRIMARY KEY, public_key BLOB, sign_count BIGINT)")
                con.execute("CREATE TABLE access_failures (occurred_at DOUBLE)")
                con.execute("CREATE TABLE access_audit (occurred_at DOUBLE, action VARCHAR, outcome VARCHAR)")
                con.execute("INSERT INTO access_meta VALUES (?, ?, ?, ?, ?, ?, 1)", [CONTRACT, origin, digest(str(journal.resolve())), secrets.token_bytes(32), digest(token), time.time() + ENROLLMENT_SECONDS])
            else:
                rows = con.execute("SELECT version, origin, journal_digest FROM access_meta").fetchall()
                if len(rows) != 1 or rows[0] != (CONTRACT, origin, digest(str(journal.resolve()))):
                    raise ValueError("Recovery does not match the existing owner/journal/origin binding.")
                con.execute("DELETE FROM passkeys")
                con.execute("DELETE FROM access_failures")
                con.execute("UPDATE access_meta SET enrollment_hash=?, enrollment_expires=?, generation=generation+1", [digest(token), time.time()+ENROLLMENT_SECONDS])
            con.execute("INSERT INTO access_audit VALUES (?, ?, 'accepted')", [time.time(), "offline_recovery" if recover else "offline_provision"])
            with os.fdopen(fd, "w", encoding="utf-8") as output:
                fd = -1
                output.write(token + "\n")
                output.flush()
                os.fsync(output.fileno())
            con.execute("COMMIT")
    except Exception:
        # Our newly reserved file only; preserve an existing store and audit.
        if fd >= 0:
            os.close(fd)
        enrollment_file.unlink(missing_ok=True)
        raise


@dataclass
class Session:
    csrf: str
    created: float
    last_used: float


class Access:
    def __init__(self, path: Path, journal: Path, origin: str, *, clock=time.time):
        self.origin = validate_origin(origin)
        self.host = urlsplit(origin).netloc
        private_file(path, "security store", private_parent=True)
        if path.resolve() == journal.resolve():
            raise ValueError("Security store must not be the journal.")
        self.lock = RLock()
        self.clock = clock
        self.con = duckdb.connect(str(path))
        try:
            rows = self.con.execute("SELECT version, origin, journal_digest, user_handle FROM access_meta").fetchall()
            if len(rows) != 1:
                raise ValueError("Security store requires exactly one owner binding.")
            row = rows[0]
            if row[:3] != (CONTRACT, origin, digest(str(journal.resolve()))) or not isinstance(row[3], bytes) or len(row[3]) != 32:
                raise ValueError("Security store binding does not match this entry point.")
            self.user_handle = bytes(row[3])
        except Exception:
            self.con.close()
            raise
        self.sessions: dict[str, Session] = {}
        self.ceremonies: dict[str, tuple[float, str, bytes, str | None]] = {}

    def close(self):
        self.sessions.clear()
        self.ceremonies.clear()
        self.con.close()

    @contextmanager
    def transaction(self):
        with self.lock:
            self.con.execute("BEGIN TRANSACTION")
            try:
                yield
                self.con.execute("COMMIT")
            except Exception:
                self.con.execute("ROLLBACK")
                raise

    def audit(self, action: str, outcome: str):
        self.con.execute("INSERT INTO access_audit VALUES (?, ?, ?)", [self.clock(), action, outcome])

    def budget(self):
        self.con.execute("DELETE FROM access_failures WHERE occurred_at < ?", [self.clock()-900])
        if self.con.execute("SELECT COUNT(*) FROM access_failures").fetchone()[0] >= 5:
            raise HTTPException(429, "Access attempt limit reached. Try again later.")

    def failure(self, action: str):
        self.con.execute("INSERT INTO access_failures VALUES (?)", [self.clock()])
        self.audit(action, "denied")

    def enrollment(self, value: str):
        row = self.con.execute("SELECT enrollment_hash, enrollment_expires FROM access_meta").fetchone()
        if (not isinstance(value, str) or not 32 <= len(value) <= 128 or
            row[0] is None or self.clock() >= row[1] or not hmac.compare_digest(digest(value), row[0])):
            raise ValueError("Enrollment unavailable")
        return row[0]

    def challenge(self, kind: str, binding: str | None):
        self.ceremonies = {k: v for k, v in self.ceremonies.items() if v[0] > self.clock()}
        if len(self.ceremonies) >= MAX_CEREMONIES:
            raise HTTPException(429, "Too many pending access attempts.")
        uid, challenge = secrets.token_urlsafe(32), secrets.token_bytes(32)
        self.ceremonies[uid] = (self.clock()+CHALLENGE_SECONDS, kind, challenge, binding)
        return uid, challenge

    def consume(self, uid: str, kind: str, binding: str | None):
        if not isinstance(uid, str) or len(uid) > 128:
            raise ValueError("Access challenge unavailable")
        item = self.ceremonies.pop(uid, None)  # Consume even an invalid/replayed attempt.
        if item is None or item[0] <= self.clock() or item[1] != kind or item[3] != binding:
            raise ValueError("Access challenge unavailable")
        return item[2]

    def session(self, token: str | None, *, touch: bool = False):
        key = digest(token) if token and len(token) <= 128 else ""
        session = self.sessions.get(key)
        if session and (self.clock()-session.last_used >= IDLE_SECONDS or self.clock()-session.created >= ABSOLUTE_SECONDS):
            self.sessions.pop(key, None)
            session = None
        if session and touch:
            session.last_used = self.clock()
        return session


def protect_app(app: FastAPI, access: Access) -> FastAPI:
    """Deny before existing routes, including exports, legacy paths and docs."""
    previous_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application):
        try:
            async with previous_lifespan(application):
                yield
        finally:
            access.close()

    app.router.lifespan_context = lifespan
    app.state.passkey_access = access
    public = {PREFIX+"/session", PREFIX+"/login/options", PREFIX+"/login/verify",
              PREFIX+"/register/options", PREFIX+"/register/verify"}

    @app.middleware("http")
    async def owner_gate(request: Request, call_next):
        try:
            if (request.headers.get("host") != access.host or
                any(key in request.headers for key in ("forwarded", "x-forwarded-host", "x-forwarded-proto")) or
                request.headers.get("sec-fetch-site") in {"cross-site", "same-site"} or
                ("origin" in request.headers and request.headers["origin"] != access.origin)):
                raise HTTPException(403, "Request origin is not allowed.")
            method = request.method
            if method not in {"GET", "HEAD"}:
                if request.headers.get("origin") != access.origin:
                    raise HTTPException(403, "Request origin is required.")
                if method == "POST" and not request.headers.get("content-type", "").startswith("application/json"):
                    raise HTTPException(415, "JSON is required.")
            with access.lock:
                session = access.session(request.cookies.get(COOKIE), touch=False)
                if request.url.path not in public:
                    if session is None:
                        raise HTTPException(401, "Sign in to OneJournal.")
                    if method not in {"GET", "HEAD"} and not hmac.compare_digest(request.headers.get("x-onejournal-csrf", ""), session.csrf):
                        raise HTTPException(403, "Request verification failed.")
                    access.session(request.cookies.get(COOKIE), touch=True)
            response = await call_next(request)
        except HTTPException as error:
            with access.transaction():
                access.audit("request", "denied")
            response = JSONResponse({"detail": error.detail}, status_code=error.status_code)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    async def body(request: Request):
        # Bound chunked input too, not just a client-supplied Content-Length.
        data = bytearray()
        async for part in request.stream():
            data.extend(part)
            if len(data) > 16384:
                raise HTTPException(413, "Access request is too large.")
        try:
            value = json.loads(data)
            if not isinstance(value, dict):
                raise ValueError
            return value
        except (ValueError, UnicodeError):
            raise HTTPException(400, "Access request is invalid.") from None

    @app.get(PREFIX+"/session", include_in_schema=False)
    def session_status(request: Request):
        with access.lock:
            session = access.session(request.cookies.get(COOKIE))
            count = access.con.execute("SELECT COUNT(*) FROM passkeys").fetchone()[0]
            return {"contract_version": CONTRACT, "authenticated": session is not None,
                    "enrollment_required": count == 0, "passkey_count": count if session else None,
                    "csrf": session.csrf if session else None}

    @app.post(PREFIX+"/register/options", include_in_schema=False)
    async def register_options(request: Request):
        value = await body(request)
        with access.transaction():
            access.budget()
            try:
                session = access.session(request.cookies.get(COOKIE))
                if session and access.clock()-session.created <= 300:
                    if not hmac.compare_digest(request.headers.get("x-onejournal-csrf", ""), session.csrf):
                        raise ValueError
                    binding = digest(request.cookies[COOKIE])
                else:
                    binding = access.enrollment(value.get("enrollment_secret"))
                if access.con.execute("SELECT COUNT(*) FROM passkeys").fetchone()[0] >= 5:
                    raise ValueError
                uid, challenge = access.challenge("register", binding)
                excluded = [PublicKeyCredentialDescriptor(id=base64url_to_bytes(row[0])) for row in access.con.execute("SELECT credential_id FROM passkeys").fetchall()]
                options = generate_registration_options(rp_id="localhost", rp_name="OneJournal Mac test", user_id=access.user_handle,
                    user_name="OneJournal owner", challenge=challenge, exclude_credentials=excluded,
                    authenticator_selection=AuthenticatorSelectionCriteria(resident_key=ResidentKeyRequirement.REQUIRED, user_verification=UserVerificationRequirement.REQUIRED), timeout=CHALLENGE_SECONDS*1000)
            except ValueError:
                access.failure("register_options")
                return JSONResponse({"detail": "Enrollment is unavailable."}, status_code=403)
            return {"ceremony": uid, "options": json.loads(options_to_json(options))}

    @app.post(PREFIX+"/register/verify", include_in_schema=False)
    async def register_verify(request: Request):
        value = await body(request)
        with access.transaction():
            access.budget()
            try:
                session = access.session(request.cookies.get(COOKIE))
                if session and not hmac.compare_digest(request.headers.get("x-onejournal-csrf", ""), session.csrf):
                    raise ValueError
                binding = digest(request.cookies[COOKIE]) if session and access.clock()-session.created <= 300 else access.enrollment(value.get("enrollment_secret"))
                challenge = access.consume(value.get("ceremony"), "register", binding)
                same_origin_credential(value.get("credential"))
                verified = verify_registration_response(credential=value.get("credential"), expected_challenge=challenge,
                    expected_rp_id="localhost", expected_origin=access.origin, require_user_verification=True)
                identifier = bytes_to_base64url(verified.credential_id)
                if (access.con.execute("SELECT COUNT(*) FROM passkeys").fetchone()[0] >= 5 or
                    access.con.execute("SELECT 1 FROM passkeys WHERE credential_id=?", [identifier]).fetchone()):
                    raise ValueError
            except (ValueError, TypeError, KeyError, WebAuthnException):
                access.failure("register")
                return JSONResponse({"detail": "Passkey verification failed."}, status_code=403)
            access.con.execute("INSERT INTO passkeys VALUES (?, ?, ?)", [identifier, verified.credential_public_key, verified.sign_count])
            access.con.execute("UPDATE access_meta SET enrollment_hash=NULL, enrollment_expires=0")
            access.audit("register", "accepted")
            return {"registered": True}

    @app.post(PREFIX+"/login/options", include_in_schema=False)
    def login_options():
        with access.transaction():
            access.budget()
            uid, challenge = access.challenge("login", None)
            options = generate_authentication_options(rp_id="localhost", challenge=challenge,
                user_verification=UserVerificationRequirement.REQUIRED, timeout=CHALLENGE_SECONDS*1000)
            return {"ceremony": uid, "options": json.loads(options_to_json(options))}

    @app.post(PREFIX+"/login/verify", include_in_schema=False)
    async def login_verify(request: Request, response: Response):
        value = await body(request)
        with access.transaction():
            access.budget()
            try:
                challenge = access.consume(value.get("ceremony"), "login", None)
                credential = value.get("credential")
                same_origin_credential(credential)
                row = access.con.execute("SELECT public_key, sign_count FROM passkeys WHERE credential_id=?", [credential["id"]]).fetchone()
                if row is None or base64url_to_bytes(credential["response"]["userHandle"]) != access.user_handle:
                    raise ValueError
                verified = verify_authentication_response(credential=credential, expected_challenge=challenge,
                    expected_rp_id="localhost", expected_origin=access.origin, credential_public_key=bytes(row[0]),
                    credential_current_sign_count=row[1], require_user_verification=True)
                now = access.clock()
                access.sessions = {key: entry for key, entry in access.sessions.items()
                    if now-entry.last_used < IDLE_SECONDS and now-entry.created < ABSOLUTE_SECONDS}
                old_token = request.cookies.get(COOKIE)
                replacing = bool(old_token and digest(old_token) in access.sessions)
                if len(access.sessions) - int(replacing) >= MAX_SESSIONS:
                    raise ValueError
            except (ValueError, TypeError, KeyError, WebAuthnException):
                access.failure("login")
                return JSONResponse({"detail": "Passkey verification failed."}, status_code=403)
            access.con.execute("UPDATE passkeys SET sign_count=? WHERE credential_id=?", [verified.new_sign_count, credential["id"]])
            access.audit("login", "accepted")
        # Establish authority only after durable verification state commits.
        with access.lock:
            if old_token:
                access.sessions.pop(digest(old_token), None)
            token = secrets.token_urlsafe(32)
            access.sessions[digest(token)] = Session(secrets.token_urlsafe(32), now, now)
        response.set_cookie(COOKIE, token, secure=True, httponly=True, samesite="strict", path="/", max_age=ABSOLUTE_SECONDS)
        return {"authenticated": True}

    @app.post(PREFIX+"/logout", include_in_schema=False)
    def logout(request: Request, response: Response):
        with access.transaction():
            access.sessions.pop(digest(request.cookies[COOKIE]), None)
            access.audit("logout", "accepted")
        response.delete_cookie(COOKIE, secure=True, httponly=True, samesite="strict", path="/")
        return {"authenticated": False}

    return app
