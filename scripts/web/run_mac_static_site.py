#!/usr/bin/env python3
"""Source-checkout compatibility wrapper for the installed Mac service."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from onejournal.mac_static_site import main


if __name__ == "__main__":
    raise SystemExit(main(project_root=ROOT))
