#!/usr/bin/env python3
"""Repository entry point for the Mac-only foreground website launcher."""

from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
# Select this checkout's code, not a different editable installation.
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from onejournal.local_web import main


if __name__ == "__main__":
    raise SystemExit(main(PROJECT_ROOT))
