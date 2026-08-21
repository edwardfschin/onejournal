#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$PROJECT_DIR"

git_top="$(git rev-parse --show-toplevel 2>/dev/null || true)"

echo "===== ONEJOURNAL GIT IDENTITY ====="
echo "PROJECT_DIR=$PROJECT_DIR"
echo "GIT_TOP=$git_top"
echo "BRANCH=$(git branch --show-current 2>/dev/null || true)"
echo "LATEST=$(git log --oneline -1 2>/dev/null || true)"
echo

if [ "$git_top" != "$PROJECT_DIR" ]; then
  echo "FAIL git top-level mismatch"
  exit 1
fi

if [ -e "$PROJECT_DIR/.git/index.lock" ]; then
  echo "FAIL stale git index lock exists: $PROJECT_DIR/.git/index.lock"
  echo "ACTION: confirm no git process is running, then remove .git/index.lock"
  exit 1
fi

echo "===== ONEJOURNAL GIT STATUS ====="
echo "SKIPPED full git status by default because cloud-synced folders can hang."
echo "Run this manually only when needed:"
echo "  git status --short"
echo

if [ "${ONEJOURNAL_FULL_GIT_STATUS:-0}" = "1" ]; then
  echo "===== ONEJOURNAL FULL GIT STATUS ====="
  git status --short
  echo
fi

echo "ONEJOURNAL_GIT_GUARD=PASS"
