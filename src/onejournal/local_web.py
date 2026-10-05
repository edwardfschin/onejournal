"""Private configuration and foreground supervision for the local website.

No provider, migration, import, calculation, daemon, or persistent PID state.
The application factory remains the authority for journal/release validation.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import getpass
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import stat
import subprocess
import sys
import time
from typing import Any
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener


CONFIG_VERSION = "onejournal.local-web.v1"
LOCAL_PAGES = {"/local/journal", "/local/trades", "/local/portfolio", "/local/reports"}
CONFIG_FIELDS = {
    "contract_version", "journal_db_path", "broker_current_authorization",
    "reporting_authorization", "web_port", "api_port", "start_page",
}


class LocalWebError(ValueError):
    """An actionable error that contains no private values or paths."""


@dataclass(frozen=True)
class LocalWebConfig:
    journal_db: Path
    broker_authorization: Path | None = None
    reporting_authorization: Path | None = None
    web_port: int = 4173
    api_port: int = 8765
    start_page: str = "/local/journal"

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.web_port}{self.start_page}"


def private_file(path: Path, label: str, *, private_parent: bool = False) -> Path:
    try:
        if not path.is_absolute() or path.is_symlink():
            raise LocalWebError(f"{label} must be an absolute, non-symlink file.")
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600:
            raise LocalWebError(f"{label} must be a regular file with mode 0600.")
        if info.st_uid != os.getuid():
            raise LocalWebError(f"{label} must belong to the current Mac user.")
        if private_parent and (
            path.parent.is_symlink()
            or stat.S_IMODE(path.parent.stat().st_mode) != 0o700
            or path.parent.stat().st_uid != os.getuid()
        ):
            raise LocalWebError(f"The {label} directory must be owner-only with mode 0700.")
    except OSError:
        raise LocalWebError(f"{label} is missing or unreadable. Check its private location.") from None
    return path.resolve()


def parse_config(document: Any) -> LocalWebConfig:
    if not isinstance(document, dict) or set(document) - CONFIG_FIELDS:
        raise LocalWebError("Local website configuration has unknown or invalid fields.")
    if document.get("contract_version") != CONFIG_VERSION:
        raise LocalWebError("Local website configuration has an unsupported contract version.")

    def file_field(name: str, required: bool = False) -> Path | None:
        value = document.get(name)
        if value is None and not required:
            return None
        if not isinstance(value, str) or not value.strip():
            raise LocalWebError(f"Configuration field {name} must name an existing private file.")
        return private_file(Path(value).expanduser(), name, private_parent=name != "journal_db_path")

    db = file_field("journal_db_path", required=True)
    broker = file_field("broker_current_authorization")
    report = file_field("reporting_authorization")
    ports = [document.get("web_port", 4173), document.get("api_port", 8765)]
    if any(type(port) is not int or not 1024 <= port <= 65535 for port in ports):
        raise LocalWebError("Website and API ports must be integers between 1024 and 65535.")
    if ports[0] == ports[1]:
        raise LocalWebError("Website and API ports must be different.")
    default_page = "/local/reports" if report else "/local/portfolio" if broker else "/local/journal"
    page = document.get("start_page", default_page)
    if not isinstance(page, str) or page not in LOCAL_PAGES:
        raise LocalWebError("start_page must be a canonical local Journal, Trades, Portfolio, or Reports path.")
    assert db is not None
    return LocalWebConfig(db, broker, report, ports[0], ports[1], page)


def load_config(path: Path, project_root: Path) -> LocalWebConfig:
    path = path.expanduser().absolute()
    if path.resolve().is_relative_to(project_root.resolve()):
        raise LocalWebError("Keep local website configuration outside the Git checkout.")
    path = private_file(path, "local website configuration", private_parent=True)
    try:
        if path.stat().st_size > 65536:
            raise ValueError
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        raise LocalWebError("Local website configuration is not valid JSON.") from None
    return parse_config(document)


def configured_app(config: LocalWebConfig) -> Any:
    try:
        from onejournal.api.broker_current_position_contracts import load_broker_current_financial_release_authorization
        from onejournal.api.local_owner_journal import create_local_owner_journal_app
        from onejournal.journal.phase1_reporting_repository import load_reporting_release_authorization
        broker = load_broker_current_financial_release_authorization(config.broker_authorization) if config.broker_authorization else None
        report = load_reporting_release_authorization(config.reporting_authorization) if config.reporting_authorization else None
        return create_local_owner_journal_app(
            journal_db_path=config.journal_db,
            broker_current_authorization=broker,
            reporting_authorization=report,
        )
    except ImportError:
        raise LocalWebError("Python dependencies are missing. Complete the documented project setup in the OneJournal environment.") from None
    except Exception:
        raise LocalWebError("API validation failed. Check the journal's existing migrations and exact release authorizations; no migration or repair was attempted.") from None


def node_runtime(project_root: Path) -> tuple[str, Path]:
    node = shutil.which(os.environ.get("ONEJOURNAL_NODE", "node"))
    if node is None:
        raise LocalWebError("Node.js is missing. Activate a supported Node installation or set ONEJOURNAL_NODE.")
    try:
        result = subprocess.run([node, "-p", "process.versions.node"], capture_output=True, text=True, timeout=5, check=True)
        version = tuple(int(part) for part in result.stdout.strip().split("."))
        if version < (22, 13, 0):
            raise ValueError
    except (OSError, ValueError, subprocess.SubprocessError):
        raise LocalWebError("Node.js 22.13 or newer is required; check ONEJOURNAL_NODE.") from None
    cli = project_root / "web/node_modules/vinext/dist/cli.js"
    if not cli.is_file():
        raise LocalWebError("Website dependencies are missing. Run npm ci in the web folder; the launcher never installs packages automatically.")
    return node, cli


def free_ports(config: LocalWebConfig) -> None:
    sockets = []
    try:
        for label, port in (("website", config.web_port), ("API", config.api_port)):
            probe = socket.socket()
            sockets.append(probe)
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                raise LocalWebError(f"The {label} port {port} is occupied or unavailable. No existing process was stopped; close its owning terminal only when ready.") from None
    finally:
        for probe in sockets:
            probe.close()


def child_environment(project_root: Path, node: str) -> dict[str, str]:
    # Do not pass unrelated broker/provider secrets to the frontend process.
    env = {key: os.environ[key] for key in ("HOME", "PATH", "LANG", "LC_ALL", "TMPDIR", "CODEX_SANDBOX") if key in os.environ}
    env["PATH"] = str(Path(node).parent) + os.pathsep + env.get("PATH", os.defpath)
    env["PYTHONPATH"] = str(project_root / "src")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


class LocalWebSession:
    """Own only newly spawned process groups; no port/PID-file takeover."""

    def __init__(self) -> None:
        self.children: list[subprocess.Popen] = []

    def spawn(self, command: list[str], cwd: Path, env: dict[str, str]) -> subprocess.Popen:
        try:
            child = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                     start_new_session=True)
        except OSError:
            raise LocalWebError("A local service could not be started. Check the configured runtime and dependencies.") from None
        self.children.append(child)
        return child

    def ready(self, child: subprocess.Popen, port: int, label: str, page: str | None = None, timeout: float = 45) -> None:
        deadline = time.monotonic() + timeout
        http = build_opener(ProxyHandler({}))
        while time.monotonic() < deadline:
            if child.poll() is not None:
                raise LocalWebError(f"The {label} exited before startup completed. Run --check to verify dependencies and private configuration.")
            try:
                if page:
                    with http.open(f"http://127.0.0.1:{port}{page}", timeout=1) as response:
                        if response.status == 200 and b"OneJournal" in response.read():
                            return
                else:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                        return
            except (OSError, URLError):
                pass
            time.sleep(0.1)
        raise LocalWebError(f"The {label} did not become ready. No existing process was replaced.")

    def stop(self) -> None:
        # A crashed parent can leave its descendants; signal its owned group too.
        for child in self.children:
            try:
                os.killpg(child.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        deadline = time.monotonic() + 3
        for child in self.children:
            try:
                child.wait(timeout=max(0.01, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                pass
        for child in self.children:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.wait()
        self.children.clear()


def run_session(config: LocalWebConfig, config_path: Path, project_root: Path, *, open_browser: bool) -> None:
    free_ports(config)
    node, cli = node_runtime(project_root)
    env = child_environment(project_root, node)
    env["ONEJOURNAL_LOCAL_API_URL"] = f"http://127.0.0.1:{config.api_port}"
    session = LocalWebSession()
    try:
        api = session.spawn([sys.executable, str(project_root / "scripts/web/run_local_owner_website.py"),
                             "--config", str(config_path), "--api-child"], project_root, env)
        session.ready(api, config.api_port, "API")
        web = session.spawn([node, str(cli), "dev", "--port", str(config.web_port), "--hostname", "127.0.0.1"], project_root / "web", env)
        session.ready(web, config.web_port, "website", config.start_page)
        if api.poll() is not None or web.poll() is not None:
            raise LocalWebError("A service stopped during startup; both managed services were stopped.")
        print(f"OneJournal is ready: {config.url}", flush=True)
        print("Local-only. Keep this terminal open; Ctrl-C stops both managed services.", flush=True)
        if open_browser:
            try:
                subprocess.run(["/usr/bin/open", config.url], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
            except (OSError, subprocess.SubprocessError):
                print("The browser could not be opened automatically; use the URL above.", flush=True)
        while True:
            if any(child.poll() is not None for child in session.children):
                raise LocalWebError("A managed service stopped unexpectedly; its companion was stopped too.")
            time.sleep(0.2)
    finally:
        session.stop()


def configure(path: Path, project_root: Path) -> None:
    path = path.expanduser().absolute()
    if path.resolve().is_relative_to(project_root.resolve()):
        raise LocalWebError("Keep local website configuration outside the Git checkout.")
    if path.exists() or path.is_symlink():
        raise LocalWebError("Configuration already exists; it was not overwritten. Use --check or a different private --config location.")
    print("Enter the existing approved file locations in this terminal, not in chat. Input is hidden.")
    document: dict[str, Any] = {"contract_version": CONFIG_VERSION}
    document["journal_db_path"] = getpass.getpass("Journal database file: ").strip()
    for key, label in (("broker_current_authorization", "Current-portfolio authorization (blank to withhold)"),
                       ("reporting_authorization", "Reporting authorization (blank to withhold)")):
        value = getpass.getpass(label + ": ").strip()
        if value:
            document[key] = value
    config = parse_config(document)
    configured_app(config)  # Read-only startup validation; no financial audit reads.
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.parent.is_symlink() or stat.S_IMODE(path.parent.stat().st_mode) != 0o700 or path.parent.stat().st_uid != os.getuid():
        raise LocalWebError("The configuration directory must be owner-only with mode 0700; no permissions were changed.")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as output:
        json.dump(document, output, indent=2)
        output.write("\n")
    print("Private configuration saved. No service started and no journal data changed.")


def main(project_root: Path, argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Start the Mac-only OneJournal website and API together; Ctrl-C stops both.")
    parser.add_argument("action", nargs="?", choices=["start", "configure"], default="start")
    parser.add_argument("--config", type=Path, default=Path.home() / ".onejournal/local-web/config.json", help="Owner-private JSON outside Git (default: ~/.onejournal/local-web/config.json).")
    parser.add_argument("--check", action="store_true", help="Read-only setup/API validation; start nothing.")
    parser.add_argument("--no-browser", action="store_true", help="Do not open the browser automatically.")
    parser.add_argument("--api-child", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.action == "configure" and (args.check or args.api_child):
        parser.error("configure cannot be combined with --check or internal API mode")
    if not (3, 11) <= sys.version_info[:2] < (3, 14):
        print("OneJournal did not start: use the supported Python 3.11–3.13 environment.", file=sys.stderr)
        return 1
    config_path = args.config.expanduser().absolute()
    old_handler = signal.getsignal(signal.SIGTERM)

    def interrupted(signum: int, frame: Any) -> None:
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupted)
    try:
        if args.action == "configure":
            configure(config_path, project_root)
            return 0
        config = load_config(config_path, project_root)
        if args.api_child:
            import uvicorn
            uvicorn.run(configured_app(config), host="127.0.0.1", port=config.api_port, log_level="warning")
        elif args.check:
            node_runtime(project_root)
            configured_app(config)
            print("Configuration and read-only API startup checks passed. No services started.")
        else:
            run_session(config, config_path, project_root, open_browser=not args.no_browser)
        return 0
    except KeyboardInterrupt:
        print("Stopped. Existing unrelated services were left alone.")
        return 0
    except LocalWebError as exc:
        print(f"OneJournal did not start: {exc}", file=sys.stderr)
        return 1
    except Exception:
        print("OneJournal did not start: local setup failed. Check file access and runtime dependencies; private details are not logged.", file=sys.stderr)
        return 1
    finally:
        signal.signal(signal.SIGTERM, old_handler)
