#!/usr/bin/env python3
from __future__ import annotations

import subprocess
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[2]


REQUIRED_DIRS = [
    "data/raw/schwab",
    "data/raw/ibkr",
    "data/raw/manual_imports",
    "data/normalized/fills",
    "data/journal",
    "data/audit/run_log",
    "output/dashboard",
    "output/reports",
]

REQUIRED_TRACKED_PLACEHOLDERS = [
    "data/normalized/fills/.gitkeep",
]

FORBIDDEN_STAGED_PREFIXES = [
    "output/",
    "data/raw/schwab/",
    "data/raw/ibkr/",
]

FORBIDDEN_STAGED_SUFFIXES = [
    ".duckdb",
    ".duckdb.wal",
]

FORBIDDEN_STAGED_EXACT = {
    "data/journal/onejournal.duckdb",
}


def _git_staged_paths() -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=PROJECT_DIR,
        text=True,
        capture_output=True,
        check=True,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _is_forbidden_staged(path: str) -> bool:
    if path in FORBIDDEN_STAGED_EXACT:
        return True
    if path.startswith("data/normalized/fills/") and path != "data/normalized/fills/.gitkeep":
        return True
    if any(path.startswith(prefix) for prefix in FORBIDDEN_STAGED_PREFIXES):
        return True
    if any(path.endswith(suffix) for suffix in FORBIDDEN_STAGED_SUFFIXES):
        return True
    return False


def main() -> int:
    print("===== ODFS Continuity Guard =====")
    print(f"PROJECT_DIR: {PROJECT_DIR}")
    print("MODE       : read-only")
    print("")

    failures: list[str] = []

    print("===== Required folders =====")
    for rel in REQUIRED_DIRS:
        path = PROJECT_DIR / rel
        if path.is_dir():
            print(f"OK   {rel}")
        else:
            print(f"FAIL {rel} missing")
            failures.append(f"missing required ODFS folder: {rel}")

    print("")
    print("===== Required tracked placeholders =====")
    for rel in REQUIRED_TRACKED_PLACEHOLDERS:
        path = PROJECT_DIR / rel
        if path.is_file():
            print(f"OK   {rel}")
        else:
            print(f"FAIL {rel} missing")
            failures.append(f"missing required tracked placeholder: {rel}")

    print("")
    print("===== Staged runtime/private files =====")
    staged = _git_staged_paths()
    forbidden = [path for path in staged if _is_forbidden_staged(path)]
    if forbidden:
        for path in forbidden:
            print(f"FAIL staged forbidden ODFS runtime/private file: {path}")
            failures.append(f"forbidden staged ODFS runtime/private file: {path}")
    else:
        print("OK   no forbidden ODFS runtime/private files staged")

    print("")
    print("===== Result =====")
    if failures:
        print(f"STATUS    : failed ODFS continuity guard ({len(failures)} issue(s))")
        for failure in failures:
            print(f"FAIL      : {failure}")
        return 1
    print("STATUS    : OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
