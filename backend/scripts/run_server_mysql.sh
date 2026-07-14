#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)
PYTHON_BIN=${PYTHON_BIN:-python3}

cd "$PROJECT_ROOT"
"$PYTHON_BIN" backend/scripts/use_mysql_storage.py
exec "$PYTHON_BIN" backend/main.py
