"""Installed, foreground Mac static-site service. No provisioning or migration."""
from pathlib import Path
import argparse
import socket
import sys

from onejournal.local_web import configured_app, load_config, private_file
from onejournal.static_web import serve_static_web, static_routes


def main(argv=None, *, project_root=None):
    parser = argparse.ArgumentParser(description="Serve the static website and protected API together on Mac loopback HTTPS; no Node runtime.")
    parser.add_argument("--web-config", required=True, type=Path)
    parser.add_argument("--security-db", required=True, type=Path)
    parser.add_argument("--tls-cert", required=True, type=Path)
    parser.add_argument("--tls-key", required=True, type=Path)
    parser.add_argument("--static-dir", required=True, type=Path)
    parser.add_argument("--owner-local", action="store_true", help="Explicit authority for the bounded Mac activation, not hosted/VPS authority.")
    args = parser.parse_args(argv)
    public_root = Path(project_root).resolve() if project_root else Path(__file__).resolve().parent
    try:
        if not args.owner_local:
            raise ValueError("Explicit --owner-local and approved Mac activation are required. Nothing was started.")
        from onejournal.passkey_access import Access, protect_app
        import uvicorn
        config = load_config(args.web_config, public_root)
        for path in (args.web_config, config.journal_db, config.broker_authorization,
                     config.reporting_authorization, args.security_db, args.tls_cert, args.tls_key):
            if path is not None and any(path.resolve().is_relative_to(root) for root in (public_root, args.static_dir.resolve())):
                raise ValueError("Keep private files outside public code and static assets.")
        for path in (args.security_db, args.tls_cert, args.tls_key):
            private_file(path, "private access/TLS file", private_parent=True)
        static_routes(args.static_dir)
        with socket.socket() as check:
            check.bind(("127.0.0.1", config.web_port))
        api = configured_app(config)
        access = Access(args.security_db, config.journal_db, f"https://localhost:{config.web_port}")
        try:
            app = serve_static_web(protect_app(api, access), args.static_dir)
            print("Starting the approved Mac static site on loopback HTTPS. Ctrl-C stops this process only.", flush=True)
            uvicorn.run(app, host="127.0.0.1", port=config.web_port,
                        ssl_certfile=str(args.tls_cert), ssl_keyfile=str(args.tls_key),
                        access_log=False, log_level="critical")
        finally:
            access.close()
    except KeyboardInterrupt:
        return 0
    except (ValueError, OSError, ImportError):
        print("Static site not started: check approved activation, artifact, free port, private permissions, binding and TLS/runtime setup. Private values are not logged.", file=sys.stderr)
        return 1
    except Exception:
        print("Static site stopped unexpectedly. Private details are not logged; unrelated services are unchanged.", file=sys.stderr)
        return 1
    return 0
