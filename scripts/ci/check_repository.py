#!/usr/bin/env python3
"""Fail closed when tracked files contain private or runtime artifacts.

This check intentionally examines Git's tracked-file set. It is suitable for a
clean CI checkout and does not depend on private broker data, local runtime
directories, staged changes, or the production journal database.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path, PurePosixPath


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MAX_TEXT_SCAN_BYTES = 5 * 1024 * 1024

SECRET_SIGNATURES: tuple[tuple[str, re.Pattern[bytes]], ...] = (
    (
        "private key",
        re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    ),
    ("AWS access key", re.compile(rb"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    (
        "GitHub token",
        re.compile(rb"\b(?:gh[oprsu]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b"),
    ),
    ("Slack token", re.compile(rb"\bxox[baprs]-[A-Za-z0-9-]{20,}\b")),
    (
        "OpenAI API key",
        re.compile(rb"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{32,}\b"),
    ),
)


def tracked_path_violation(path: str) -> str | None:
    """Return the violated policy for a tracked repository-relative path."""

    normalized = path.replace("\\", "/")
    if normalized.startswith("./"):
        normalized = normalized[2:]
    pure_path = PurePosixPath(normalized)
    parts = pure_path.parts
    filename = pure_path.name.lower()

    if normalized.startswith("data/raw/"):
        return "raw broker/import evidence must not be tracked"
    if normalized.startswith("output/"):
        return "generated output must not be tracked"
    if (
        normalized.startswith("data/normalized/fills/")
        and normalized != "data/normalized/fills/.gitkeep"
    ):
        return "generated normalized-fill artifacts must not be tracked"
    if normalized.startswith("data/journal/backups/"):
        return "journal database backups must not be tracked"
    if (
        normalized.startswith("data/journal/")
        and (filename.endswith(".duckdb") or filename.endswith(".duckdb.wal"))
    ):
        return "runtime journal databases must not be tracked"
    if (
        filename == ".env"
        or filename.startswith(".env.")
        or filename.endswith(".env")
    ):
        return "private environment files must not be tracked"
    if "tokens" in (part.lower() for part in parts):
        return "token directories must not be tracked"
    if re.search(r"(?:^|[_-])token(?:s)?(?:[_-].*)?\.json$", filename):
        return "token JSON files must not be tracked"
    if filename == ".ds_store":
        return "operating-system metadata must not be tracked"
    return None


def secret_violations(content: bytes) -> list[str]:
    """Return high-confidence secret signatures found in file content."""

    return [
        description
        for description, pattern in SECRET_SIGNATURES
        if pattern.search(content)
    ]


def git_tracked_paths(project_root: Path = PROJECT_ROOT) -> list[str]:
    """Return repository tracked paths using NUL-delimited Git output."""

    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=project_root,
        check=True,
        capture_output=True,
    )
    return [
        raw_path.decode("utf-8")
        for raw_path in result.stdout.split(b"\0")
        if raw_path
    ]


def inspect_repository(project_root: Path = PROJECT_ROOT) -> list[str]:
    """Inspect all tracked files and return every policy violation."""

    failures: list[str] = []
    for relative_path in git_tracked_paths(project_root):
        path_failure = tracked_path_violation(relative_path)
        if path_failure:
            failures.append(f"{relative_path}: {path_failure}")
            continue

        absolute_path = project_root / relative_path
        if not absolute_path.is_file():
            failures.append(f"{relative_path}: tracked file is missing from checkout")
            continue
        if absolute_path.stat().st_size > MAX_TEXT_SCAN_BYTES:
            continue

        content = absolute_path.read_bytes()
        if b"\0" in content:
            continue
        for description in secret_violations(content):
            failures.append(
                f"{relative_path}: contains a high-confidence {description} signature"
            )
    return failures


def main() -> int:
    print("===== OneJournal tracked repository guard =====")
    print(f"ROOT      : {PROJECT_ROOT}")
    print("SCOPE     : Git tracked files")
    print("PRIVATE   : broker data, runtime DBs, tokens, env files")

    try:
        tracked_paths = git_tracked_paths()
        failures = inspect_repository()
    except (OSError, subprocess.CalledProcessError) as exc:
        print("STATUS    : FAIL")
        print(f"FAIL      : unable to inspect tracked files: {exc}")
        return 1

    print(f"TRACKED   : {len(tracked_paths)}")
    if failures:
        print("STATUS    : FAIL")
        for failure in failures:
            print(f"FAIL      : {failure}")
        return 1

    print("STATUS    : OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
