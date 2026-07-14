#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)
PYTHON_BIN=${PYTHON_BIN:-python3}

cd "$PROJECT_ROOT"
"$PYTHON_BIN" -m unittest discover -s backend/tests

if [ "${BACKEND_ONLY:-0}" = "1" ]; then
  echo "Frontend verification skipped because BACKEND_ONLY=1."
  exit 0
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "npm is required for frontend verification; install Node.js or run BACKEND_ONLY=1." >&2
  exit 1
fi

(
  cd frontend
  npm ci
  npm run check
  npm run build
)
