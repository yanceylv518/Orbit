#!/usr/bin/env sh
set -eu

PYTHON_BIN=${PYTHON_BIN:-python3}
ORBIT_URL=${ORBIT_URL:-http://127.0.0.1:8765}

exec "$PYTHON_BIN" -c '
import json
import sys
import urllib.request

url = sys.argv[1].rstrip("/") + "/api/state"
with urllib.request.urlopen(url, timeout=5) as response:
    payload = json.load(response)
if response.status != 200 or "auth" not in payload:
    raise SystemExit("Orbit healthcheck failed")
print(f"Orbit healthcheck OK: {url}")
' "$ORBIT_URL"
