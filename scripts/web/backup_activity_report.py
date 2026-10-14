#!/usr/bin/env python3
"""Private Terminal entry point for encrypted activity-draft recovery."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'src'))
from onejournal.activity_report_backup import main

if __name__ == '__main__':
    raise SystemExit(main())
