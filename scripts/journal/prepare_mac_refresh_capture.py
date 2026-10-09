#!/usr/bin/env python3
"""Prepare one reviewed owner-side capture script, without broker access."""

from __future__ import annotations

import argparse
from datetime import date
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import stat
import sys
from typing import Sequence

PROJECT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_DIR / "src"))
from onejournal.provider_connectors.capture_preparation import (  # noqa: E402
    CapturePreparation, CapturePreparationError, prepare_capture_runner,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--reviewed-source-sha256", required=True)
    parser.add_argument("--kind", choices=("position", "history"), required=True)
    parser.add_argument("--asof", type=date.fromisoformat, required=True)
    parser.add_argument("--window-start", type=date.fromisoformat)
    parser.add_argument("--window-end", type=date.fromisoformat)
    parser.add_argument("--run-uid", required=True)
    parser.add_argument("--proposed-approval-id", required=True)
    parser.add_argument("--owner-run-root", type=PurePosixPath, required=True)
    parser.add_argument("--auth-sha256", required=True)
    parser.add_argument("--conf-sha256", required=True)
    parser.add_argument("--runtime-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if (not args.source.is_absolute() or args.source.is_symlink() or not args.source.is_file()
            or stat.S_IMODE(args.source.stat().st_mode) != 0o600
            or not 0 < args.source.stat().st_size <= 96 * 1024):
            raise CapturePreparationError("reviewed source must be an absolute 0600 non-symlink file within 96 KiB")
        if (not args.output.is_absolute() or not args.output.parent.is_dir()
            or any(parent.is_symlink() for parent in (args.output.parent, *args.output.parents))
            or stat.S_IMODE(args.output.parent.stat().st_mode) != 0o700
            or args.output.name != f"onejournal_mac_refresh_{args.kind}.py"):
            raise CapturePreparationError("output must name the fixed runner in an existing absolute 0700 non-symlink directory")
        prepared = prepare_capture_runner(args.source.read_bytes(), CapturePreparation(
            kind=args.kind, asof=args.asof, run_uid=args.run_uid,
            proposed_approval_id=args.proposed_approval_id, owner_run_root=args.owner_run_root,
            reviewed_source_sha256=args.reviewed_source_sha256, auth_sha256=args.auth_sha256,
            conf_sha256=args.conf_sha256, runtime_sha256=args.runtime_sha256,
            window_start=args.window_start, window_end=args.window_end,
        ))
        descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(prepared)
            handle.flush()
            os.fsync(handle.fileno())
        if args.output.read_bytes() != prepared:
            raise CapturePreparationError("prepared script read-back differs")
    except (CapturePreparationError, OSError) as exc:
        # No private source content, paths, identifiers or OS exception text.
        reason = str(exc) if isinstance(exc, CapturePreparationError) else "private file operation failed; nothing was overwritten"
        print(f"Preparation failed: {reason}", file=sys.stderr)
        return 1
    print(json.dumps({"status": "prepared_not_authorized", "kind": args.kind,
        "asof": args.asof.isoformat(), "runner_sha256": sha256(prepared).hexdigest(),
        "proposed_provider_get_count": 1 if args.kind == "position" else 2,
        "provider_get_count": 0, "database_write_count": 0}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
