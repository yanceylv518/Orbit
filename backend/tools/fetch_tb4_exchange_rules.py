"""Fetch and atomically persist Binance rules for the frozen TB4 universe.

No account or API key is required. Run this before enabling LIVE-SMALL and
refresh it before the configured snapshot expires.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import urllib.request


BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from orbit.application.trend_execution_checklist import (  # noqa: E402
    build_tb4_exchange_rules,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default="https://fapi.binance.com",
        help="Binance Futures public API base URL",
    )
    parser.add_argument(
        "--out",
        default="var/forward/live-small/tb4_exchange_rules.json",
    )
    parser.add_argument("--refresh-after-days", type=int, default=30)
    args = parser.parse_args()
    if args.refresh_after_days <= 0:
        parser.error("--refresh-after-days must be positive")

    url = f"{args.base_url.rstrip('/')}/fapi/v1/exchangeInfo"
    with urllib.request.urlopen(url, timeout=30) as response:
        exchange_info = json.loads(response.read().decode("utf-8"))
    fetched_at = (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
    payload = build_tb4_exchange_rules(
        exchange_info,
        fetched_at=fetched_at,
        source=url,
        refresh_after_days=args.refresh_after_days,
    )
    destination = Path(args.out)
    if not destination.is_absolute():
        destination = PROJECT_ROOT / destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(destination)
    print(f"saved TB4 exchange rules -> {destination}")


if __name__ == "__main__":
    main()
