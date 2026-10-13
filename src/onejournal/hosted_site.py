"""Independent hosted entry point. No migrations, imports or brokers at startup."""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import json
import re
from pathlib import Path

from onejournal.journal.storage import PostgresTarget, validate_runtime_role
from onejournal.local_web import private_file

CONFIG = "onejournal.hosted-site.v1"


@dataclass(frozen=True)
class HostedConfig:
    origin: str
    journal: PostgresTarget
    security: PostgresTarget
    proxy_secret: str = field(repr=False)
    static_directory: Path
    broker_authorization: Path | None
    reporting_authorization: Path | None


def load_config(path: Path) -> HostedConfig:
    from onejournal.hosted_access import validate_hosted_origin
    path = private_file(path, "hosted configuration", private_parent=True)
    if path.stat().st_size > 65536:
        raise ValueError("Hosted configuration is too large.")
    doc = json.loads(path.read_text())
    fields = {"contract_version", "origin", "journal_dsn_file", "security_dsn_file",
              "proxy_secret_file", "static_directory", "broker_authorization", "reporting_authorization"}
    if not isinstance(doc, dict) or set(doc) != fields or doc["contract_version"] != CONFIG:
        raise ValueError("Hosted configuration contract is invalid.")

    def private(name, optional=False):
        value = doc[name]
        if value is None and optional:
            return None
        if not isinstance(value, str):
            raise ValueError("Hosted configuration must name private files.")
        return private_file(Path(value), name, private_parent=True)

    journal = PostgresTarget(private("journal_dsn_file").read_text().strip())
    security = PostgresTarget(private("security_dsn_file").read_text().strip())
    from psycopg.conninfo import conninfo_to_dict
    if conninfo_to_dict(journal.dsn)["dbname"] == conninfo_to_dict(security.dsn)["dbname"]:
        raise ValueError("Hosted journal and access databases must be separate.")
    secret = private("proxy_secret_file").read_text().strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{43,128}", secret) is None:
        raise ValueError("Use a random private proxy secret of 43–128 characters.")
    directory = Path(doc["static_directory"])
    if not directory.is_absolute():
        raise ValueError("Use an absolute static artifact directory.")
    return HostedConfig(validate_hosted_origin(doc["origin"]), journal, security, secret,
                        directory, private("broker_authorization", True), private("reporting_authorization", True))


def configured_app(config: HostedConfig):
    from onejournal.api.broker_current_position_contracts import load_broker_current_financial_release_authorization
    from onejournal.api.local_owner_journal import create_local_owner_journal_app
    from onejournal.hosted_access import HostedAccess
    from onejournal.hosted_schema import validate
    from onejournal.journal.phase1_reporting_repository import load_reporting_release_authorization
    from onejournal.passkey_access import protect_app
    from onejournal.static_web import serve_static_web
    validate(config.journal)
    validate_runtime_role(config.journal)
    # Existing financial authorization/read-back still applies on PostgreSQL.
    broker = load_broker_current_financial_release_authorization(config.broker_authorization) if config.broker_authorization else None
    reporting = load_reporting_release_authorization(config.reporting_authorization) if config.reporting_authorization else None
    api = create_local_owner_journal_app(journal_db_path=config.journal,
            broker_current_authorization=broker, reporting_authorization=reporting)
    access = HostedAccess(config.security, config.journal, config.origin, config.proxy_secret)
    try:
        app = serve_static_web(protect_app(api, access), config.static_directory)
    except Exception:
        access.close()
        raise
    app.state.hosted = True
    from fastapi.responses import JSONResponse
    from onejournal.static_web import PUBLIC_HEADERS

    @app.middleware("http")
    async def private_failure_boundary(request, call_next):
        try:
            return await call_next(request)
        except Exception:
            # Server/database exception text may contain private row identities
            # or parameter values. Emit a fixed signal, never that traceback.
            print("OneJournal hosted request failed; operator attention required.")
            return JSONResponse({"detail": "Private service unavailable. No result is substituted."},
                                status_code=503, headers=PUBLIC_HEADERS)
    from collections import deque
    import time
    arrivals = deque()

    @app.middleware("http")
    async def request_budget(request, call_next):
        # Global single-owner burst budget; does not retain IPs, URLs or filters.
        now = time.monotonic()
        while arrivals and arrivals[0] <= now - 10:
            arrivals.popleft()
        if len(arrivals) >= 128:
            return JSONResponse({"detail": "Request limit reached. Try again shortly."}, status_code=429,
                                headers={**PUBLIC_HEADERS, "Retry-After": "10"})
        arrivals.append(now)
        return await call_next(request)
    return app


def main():
    parser = argparse.ArgumentParser(description="Run the separate private hosted API behind its approved HTTPS proxy.")
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    try:
        import uvicorn
        app = configured_app(load_config(args.config))
    except Exception:
        print("Hosted startup refused. Check private configuration, schema and exact release/access bindings; no repair was attempted.")
        return 1
    # Do not trust arbitrary forwarded client/scheme headers. Caddy overwrites a
    # private proxy header, strips forwarding headers and preserves the exact Host.
    uvicorn.run(app, host="127.0.0.1", port=8766, workers=1, proxy_headers=False,
                access_log=False, log_level="warning", limit_concurrency=20,
                timeout_keep_alive=5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
