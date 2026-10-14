#!/usr/bin/env python3
"""Guarded activity report rehearsal/persistence; no runtime activation."""
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'))
from onejournal.activity_publication import main

if __name__=='__main__':
    raise SystemExit(main())
