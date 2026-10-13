#!/usr/bin/env python3
"""Package clean committed public source only; no target connection or activation."""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    target = args.destination
    if not target.is_absolute() or target.exists() or target.is_symlink() or target.resolve().is_relative_to(ROOT.resolve()):
        raise ValueError("Use a new absolute public package directory outside Git.")
    state = subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True)
    if state:
        raise ValueError("Commit validated source before packaging; dirty source is not a release.")
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    target.mkdir(mode=0o700)
    try:
        subprocess.run([sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation",
                        "--wheel-dir", str(target / "wheels"), str(ROOT)], check=True)
        environment = {**os.environ, "ONEJOURNAL_PASSKEY_MODE": "1"}
        subprocess.run(["npm", "run", "build"], cwd=ROOT / "web", env=environment, check=True)
        from onejournal.static_web import static_routes
        static_routes(ROOT / "web" / "dist")
        shutil.copytree(ROOT / "web" / "dist", target / "static", symlinks=False)
        shutil.copytree(ROOT / "config" / "hosted", target / "deployment")
        (target / "commands").mkdir()
        for name in ("prepare_hosted_store.py", "backup_hosted_store.py", "run_hosted_backup.sh"):
            shutil.copyfile(ROOT / "scripts" / "web" / name, target / "commands" / name)
        for name in ("requirements.lock", "requirements-security.lock", "requirements-hosted.lock"):
            shutil.copyfile(ROOT / name, target / name)
        checksums = {str(path.relative_to(target)): sha256(path.read_bytes()).hexdigest()
                     for path in sorted(target.rglob("*")) if path.is_file()}
        (target / "release.json").write_text(json.dumps({"contract_version": "onejournal.hosted-release.v1",
            "source_commit": revision, "files": checksums, "private_data_included": False,
            "linux_environment_required": True, "activated": False}, indent=2, sort_keys=True))
    except Exception:
        # Preserve a failed candidate for diagnosis, never silently promote it.
        print("Public packaging incomplete; candidate was not activated.")
        return 1
    print("Public hosted package prepared from committed source. No private files, server transfer or activation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
