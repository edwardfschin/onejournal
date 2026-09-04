#!/usr/bin/env bash
# Activate the canonical machine-local OneJournal Python environment.
# Source this file from a shell; it intentionally changes to the repository root.

if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
  SCRIPT_PATH="${BASH_SOURCE[0]}"
else
  SCRIPT_PATH="$0"
fi

SCRIPT_DIR="$(cd "$(dirname "$SCRIPT_PATH")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_DIR="${ONEJOURNAL_VENV_DIR:-/Users/edward/python-envs/onejournal-env}"

if [[ ! -x "$ENV_DIR/bin/python" ]]; then
  echo "FAIL: OneJournal Python environment not found at $ENV_DIR" >&2
  return 1 2>/dev/null || exit 1
fi

source "$ENV_DIR/bin/activate"
export ONEJOURNAL_VENV_DIR="$ENV_DIR"
cd "$PROJECT_DIR" || return 1
echo "OneJournal project: $PROJECT_DIR"
echo "OneJournal environment: $ENV_DIR"
