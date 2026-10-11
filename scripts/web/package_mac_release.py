#!/usr/bin/env python3
"""Build a public, checkout-independent Mac candidate; never activate it."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))
from onejournal.static_web import static_routes
from scripts.ci.check_repository import inspect_repository, secret_violations


def run(command, cwd, **kwargs):
    return subprocess.run(command, cwd=cwd, check=True, capture_output=True, **kwargs).stdout


def copy_snapshot(root, target):
    """Only committed public application/build inputs, never ignored local files."""
    archive = run(["git", "archive", "HEAD", "src", "web", "scripts/journal/migrations", "pyproject.toml",
                   "requirements.lock", "requirements-security.lock"], root)
    with tarfile.open(fileobj=io.BytesIO(archive)) as source:
        for member in source.getmembers():
            relative = Path(member.name)
            if relative.is_absolute() or ".." in relative.parts or not (member.isdir() or member.isfile()):
                raise ValueError("Source snapshot contains an unsafe path or link.")
            path = target / relative
            if member.isdir():
                path.mkdir(parents=True, exist_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(source.extractfile(member).read())


def release_files(root):
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not (path.is_dir() or path.is_file()):
            raise ValueError("Release contains a link or special file.")
        if path.is_file():
            name = path.relative_to(root).as_posix()
            if secret_violations(path.read_bytes()):
                raise ValueError("Release contains a private-key or token signature.")
            result[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def package(root, destination):
    root = root.resolve()
    destination = destination.expanduser().absolute()
    if destination.resolve().is_relative_to(root) or destination.exists() or destination.is_symlink():
        raise ValueError("Use a new destination outside the checkout; existing files are never replaced.")
    if not destination.name.endswith(".tar.gz") or not destination.parent.is_dir():
        raise ValueError("Use a .tar.gz destination in an existing directory.")
    if run(["git", "status", "--porcelain"], root).strip():
        raise ValueError("Commit the focused source changes before packaging.")
    if inspect_repository(root):
        raise ValueError("Tracked repository privacy validation failed.")
    commit = run(["git", "rev-parse", "HEAD"], root, text=True).strip()
    npm = shutil.which("npm")
    dependencies = root / "web/node_modules"
    if not npm or not dependencies.is_dir():
        raise ValueError("Existing frontend build dependencies are required; packaging never installs them.")
    # Every build input comes from HEAD. Reuse installed build tooling only,
    # not checkout .env files, old dist output or untracked public assets.
    with tempfile.TemporaryDirectory(prefix="onejournal-package-", dir=destination.parent) as temporary:
        temporary = Path(temporary)
        source = temporary / "source"
        source.mkdir()
        copy_snapshot(root, source)
        (source / "web/node_modules").symlink_to(dependencies, target_is_directory=True)
        environment = {key: value for key, value in os.environ.items()
                       if key in {"PATH", "HOME", "TMPDIR", "LANG", "LC_ALL"}}
        run([npm, "run", "build"], source / "web", env=environment)
        static_routes(source / "web/dist")
        release = temporary / "onejournal-mac-release"
        release.mkdir()
        shutil.copytree(source / "web/dist", release / "static")
        run([sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation",
             "--no-index", "--wheel-dir", str(release), str(source)], source)
        wheels = list(release.glob("*.whl"))
        if len(wheels) != 1:
            raise ValueError("Expected exactly one application wheel.")
        for name in ("requirements.lock", "requirements-security.lock"):
            shutil.copyfile(source / name, release / name)
        (release / "INSTALL.txt").write_text(
            "Prepared Mac-only candidate, not activated or hosted acceptance.\n"
            "Requires Python 3.11-3.13 and network/package-cache access for pinned dependencies.\n"
            "Create a NEW virtual environment outside Git/private data. From this folder:\n"
            "  python -m pip install -r requirements-security.lock\n"
            f"  python -m pip install --no-deps {wheels[0].name}\n"
            "After separately approved Mac handover, invoke that environment's onejournal-mac-site:\n"
            "  --web-config PRIVATE_CONFIG --security-db PRIVATE_SECURITY_DB\n"
            "  --tls-cert PRIVATE_CERT --tls-key PRIVATE_KEY --static-dir ABSOLUTE_STATIC_DIR --owner-local\n"
            "Use existing owner-only files, journal binding and exact release authorizations.\n"
            "No Node runtime, checkout, automatic migration, provisioning or service takeover.\n"
            "Keep the previous environment and launcher for rollback; stop only the owned process.\n"
            "This archive contains no journal, access state, TLS keys, enrollment codes or broker evidence.\n"
            "Exact SQL migration definitions are bundled for checksum validation; startup never applies them.\n"
            "Operator scripts are NOT bundled; use the reviewed source checkout separately.\n"
        )
        manifest = {"contract_version": "onejournal.mac-release.v1", "source_commit": commit,
                    "scope": "prepared_mac_loopback_only", "files_sha256": release_files(release)}
        (release / "release-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        archive = temporary / "candidate.tar.gz"
        with tarfile.open(archive, "w:gz") as output:
            output.add(release, arcname=release.name)
        # Atomic exclusive publication: even a racing destination is not overwritten.
        os.link(archive, destination)
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        manifest = package(ROOT, args.destination)
    except (ValueError, OSError, subprocess.SubprocessError):
        print("Release not created: check clean committed source, public inputs, existing build tools and a new external destination. No runtime was changed.", file=sys.stderr)
        return 1
    print(f"Prepared Mac release verified: {len(manifest['files_sha256'])} public files, commit {manifest['source_commit'][:12]}. No activation or private-state change.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
