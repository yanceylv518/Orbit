"""Fetch Binance USD-M perpetual historical funding rates without credentials."""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def read_json_with_retries(url: str, *, attempts: int = 4) -> list:
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except (TimeoutError, urllib.error.URLError):
            if attempt == attempts:
                raise
            time.sleep(2 ** (attempt - 1))
    return []


def fetch_funding(symbol: str, days: int, base_url: str) -> list[dict]:
    end_ms = int(time.time() * 1000)
    cursor = end_ms - days * 86_400_000
    points = []
    while cursor < end_ms:
        query = urllib.parse.urlencode({
            "symbol": symbol, "startTime": cursor, "endTime": end_ms, "limit": 1000,
        })
        batch = read_json_with_retries(
            f"{base_url.rstrip('/')}/fapi/v1/fundingRate?{query}"
        )
        if not batch:
            break
        points.extend({
            "funding_time_ms": int(item["fundingTime"]),
            "funding_rate": float(item["fundingRate"]),
            "mark_price": float(item["markPrice"]) if item.get("markPrice") else None,
        } for item in batch)
        next_cursor = int(batch[-1]["fundingTime"]) + 1
        if next_cursor <= cursor or len(batch) < 1000:
            break
        cursor = next_cursor
        time.sleep(0.2)
    return points


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--days", type=int, default=180)
    parser.add_argument("--base-url", default="https://fapi.binance.com")
    parser.add_argument("--out")
    args = parser.parse_args()
    symbol = args.symbol.upper()
    points = fetch_funding(symbol, args.days, args.base_url)
    output = Path(args.out) if args.out else Path("var/calibration") / f"{symbol}_funding.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(points), encoding="utf-8")
    print(f"saved {len(points)} funding points -> {output.resolve()}")


if __name__ == "__main__":
    main()
