#!/usr/bin/env python3
"""Private Mac passkey entry point; owner-local activation must be explicit."""
from pathlib import Path
import argparse
import getpass
import signal
import ssl
import sys
import time
from urllib.request import HTTPSHandler, ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from onejournal.local_web import (LocalWebSession, child_environment, configured_app,
                                  free_ports, load_config, node_runtime, private_file)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Mac-only HTTPS passkey access; no non-local/production activation.")
    parser.add_argument("action", choices=["provision", "recover", "serve", "api"])
    parser.add_argument("--web-config", required=True, type=Path, help="Owner-private launcher configuration outside Git.")
    parser.add_argument("--owner-local", action="store_true", help="Use only after owner approval of the bounded existing-journal Mac switchover; never hosted/VPS authority.")
    parser.add_argument("--security-db", required=True, type=Path)
    parser.add_argument("--enrollment-file", type=Path, help="New owner-private enrollment output; token is never logged.")
    parser.add_argument("--tls-cert", type=Path)
    parser.add_argument("--tls-key", type=Path)
    args = parser.parse_args(argv)
    try:
        from onejournal.passkey_access import Access, protect_app, provision
        config = load_config(args.web_config, ROOT)
        if not args.owner_local and (config.broker_authorization or config.reporting_authorization):
            raise ValueError("Release-authorized local access requires explicit --owner-local and the approved Mac switchover. Nothing was started or changed.")
        for path in (args.security_db, args.enrollment_file, args.tls_cert, args.tls_key):
            if path and path.resolve().is_relative_to(ROOT):
                raise ValueError("Keep all private prototype files outside Git.")
        origin = f"https://localhost:{config.web_port}"
        if args.action in {"provision", "recover"}:
            if args.enrollment_file is None:
                raise ValueError("Choose a new private enrollment output file.")
            if args.action == "recover" and getpass.getpass("Stop the protected site, then type REPLACE PASSKEYS to revoke all old credentials: ") != "REPLACE PASSKEYS":
                raise ValueError("Recovery was not confirmed; nothing changed.")
            provision(args.security_db, config.journal_db, origin, args.enrollment_file, recover=args.action == "recover")
            print("Private security setup saved. The enrollment file expires in 10 minutes and becomes unusable after registration. No journal change or service startup.")
            return 0
        if args.action == "api":
            import uvicorn
            access = Access(args.security_db, config.journal_db, origin)
            try:
                app = protect_app(configured_app(config), access)
            except Exception:
                access.close()
                raise
            uvicorn.run(app, host="127.0.0.1", port=config.api_port, access_log=False, log_level="critical")
            return 0
        if args.tls_cert is None or args.tls_key is None:
            raise ValueError("Explicit local TLS certificate and private key are required; no HTTP fallback.")
        private_file(args.tls_cert, "local TLS certificate", private_parent=True)
        private_file(args.tls_key, "local TLS key", private_parent=True)
        configured_app(config)  # Existing validation, read-only.
        access = Access(args.security_db, config.journal_db, origin)
        access.close()  # Validate the binding before starting anything.
        free_ports(config)
        node, cli = node_runtime(ROOT)
        env = child_environment(ROOT, node)
        env.update(ONEJOURNAL_LOCAL_API_URL=f"http://127.0.0.1:{config.api_port}",
                   ONEJOURNAL_PASSKEY_MODE="1", ONEJOURNAL_TEST_TLS_CERT=str(args.tls_cert),
                   ONEJOURNAL_TEST_TLS_KEY=str(args.tls_key))
        session = LocalWebSession()
        previous = signal.getsignal(signal.SIGTERM)

        def stop(signum, frame):
            raise KeyboardInterrupt

        signal.signal(signal.SIGTERM, stop)
        try:
            api = session.spawn([sys.executable, str(Path(__file__).resolve()), "api", "--web-config", str(args.web_config),
                                 "--security-db", str(args.security_db), *(["--owner-local"] if args.owner_local else [])], ROOT, env)
            session.ready(api, config.api_port, "protected API")
            web = session.spawn([node, str(cli), "dev", "--hostname", "127.0.0.1", "--port", str(config.web_port)], ROOT / "web", env)
            # Test TLS must be trusted by the test client/browser explicitly.
            # Do not disable certificate verification or modify system trust.
            opener = build_opener(ProxyHandler({}), HTTPSHandler(context=ssl.create_default_context(cafile=str(args.tls_cert))))
            deadline = time.monotonic() + 45
            while True:
                if api.poll() is not None or web.poll() is not None:
                    raise ValueError("A prototype service stopped during startup.")
                try:
                    with opener.open(origin + config.start_page, timeout=1) as response:
                        if response.status == 200 and b"OneJournal" in response.read():
                            break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise ValueError("The HTTPS prototype did not become ready.") from None
                    time.sleep(.2)
            print(f"Passkey-protected Mac site ready: {origin}{config.start_page}", flush=True)
            print("Approved Mac-only owner scope. Ctrl-C stops both managed services." if args.owner_local else
                  "Disposable Mac test only. Use explicit certificate trust. Ctrl-C stops both managed services.", flush=True)
            while True:
                if api.poll() is not None or web.poll() is not None:
                    raise ValueError("A prototype service stopped; its companion was stopped too.")
                time.sleep(.2)
        finally:
            session.stop()
            signal.signal(signal.SIGTERM, previous)
    except KeyboardInterrupt:
        print("Prototype stopped; unrelated services were left alone.")
        return 0
    except ImportError:
        print("Prototype not started: install the optional locked security environment.", file=sys.stderr)
        return 1
    except ValueError as error:
        # Our validation errors contain labels, not private paths or values.
        print(f"Prototype did not complete: {error}", file=sys.stderr)
        return 1
    except Exception:
        print("Prototype did not complete. Check private permissions, binding, certificate and runtime setup. Private details are not logged.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
