#!/usr/bin/env python3
"""Run the secret-free provider-disabled macOS staging rehearsal.

The command prints one canonical JSON result. It does not use Keychain, a network,
provider credentials, DuckDB, a listener, or any evidence-file output.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path
import subprocess
import sys
from typing import Sequence


PROJECT_DIR = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from onejournal.provider_connectors.macos_staging_rehearsal import (  # noqa: E402
    MacOSStagingRehearsalError,
    macos_staging_rehearsal_bytes,
    run_macos_provider_staging_rehearsal,
)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Prove a local macOS T15 staging artifact remains provider-disabled; "
            "makes no Keychain, network, DuckDB, listener, or evidence-file action."
        )
    )
    parser.add_argument(
        "--host-uid",
        required=True,
        help="Opaque local staging-host identifier; it is recorded but not persisted.",
    )
    parser.add_argument(
        "--policy-path",
        type=Path,
        default=PROJECT_DIR / "config" / "marketdata.yaml",
        help="Read-only market-data policy path.",
    )
    return parser.parse_args(argv)


def current_clean_artifact_commit(project_dir: Path) -> str:
    """Resolve the exact local Git artifact and reject any uncommitted source."""

    try:
        head = subprocess.run(
            ("git", "rev-parse", "HEAD"),
            cwd=project_dir,
            text=True,
            capture_output=True,
            check=False,
        )
        status = subprocess.run(
            ("git", "status", "--porcelain", "--untracked-files=all"),
            cwd=project_dir,
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        raise MacOSStagingRehearsalError("local Git artifact is unavailable") from exc
    if head.returncode != 0 or status.returncode != 0:
        raise MacOSStagingRehearsalError("local Git artifact is unavailable")
    artifact_commit = head.stdout.strip()
    if status.stdout:
        raise MacOSStagingRehearsalError("rehearsal artifact worktree is not clean")
    return artifact_commit


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = run_macos_provider_staging_rehearsal(
            policy_path=args.policy_path,
            artifact_commit=current_clean_artifact_commit(PROJECT_DIR),
            host_uid=args.host_uid,
            observed_at_utc=datetime.now(UTC),
        )
        sys.stdout.buffer.write(macos_staging_rehearsal_bytes(result))
    except MacOSStagingRehearsalError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
