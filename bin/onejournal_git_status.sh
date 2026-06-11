#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

git_top="$(git rev-parse --show-toplevel 2>/dev/null || true)"
project_name="$(basename "$PROJECT_DIR")"

echo "===== ONEJOURNAL GIT IDENTITY ====="
echo "PROJECT_DIR=$PROJECT_DIR"
echo "GIT_TOP=$git_top"
echo "BRANCH=$(git branch --show-current 2>/dev/null || true)"
echo "LATEST=$(git log --oneline -1 2>/dev/null || true)"
echo

if [ "$project_name" != "onejournal" ]; then
  echo "FAIL wrong project folder: $project_name"
  exit 1
fi

if [ "$git_top" != "$PROJECT_DIR" ]; then
  echo "FAIL git top-level mismatch"
  exit 1
fi

echo "===== ONEJOURNAL GIT STATUS ====="
git status --short
echo
echo "ONEJOURNAL_GIT_GUARD=PASS"