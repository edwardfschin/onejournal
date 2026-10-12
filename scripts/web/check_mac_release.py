#!/usr/bin/env python3
"""Check pinned public release and optional localhost HTTPS; never repair/start."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from onejournal.mac_release_check import main

if __name__ == '__main__':
    raise SystemExit(main())
