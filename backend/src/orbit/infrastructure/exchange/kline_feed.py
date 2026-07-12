from __future__ import annotations

import json
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


# 行情统一取主网公共 K 线（真实价格、无需密钥、免签名限频宽松）。
# testnet 账户的持仓估值仍用其自身快照的 mark price；K 线只驱动生命周期推进。
FAPI_PUBLIC_BASE_URL = "https://fapi.binance.com"

INTERVAL_MS = {
    "1m": 60_000,
    "3m": 180_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
}


class MarketFeedError(RuntimeError):
    pass


class BinanceKlineFeed:
    def __init__(self, *, base_url: str = FAPI_PUBLIC_BASE_URL, timeout: float = 8):
        self.base_url = base_url
        self.timeout = timeout

    def closed_klines(self, symbol: str, interval: str, limit: int) -> list[dict[str, Any]]:
        if interval not in INTERVAL_MS:
            raise MarketFeedError(f"Unsupported kline interval: {interval}")
        query = urlencode({"symbol": symbol, "interval": interval, "limit": max(2, limit + 1)})
        request = Request(f"{self.base_url}/fapi/v1/klines?{query}", method="GET")
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise MarketFeedError(f"Kline HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise MarketFeedError(f"Kline network error: {exc.reason}") from exc

        now_ms = int(time.time() * 1000)
        klines = []
        for row in raw:
            close_time = int(row[6])
            if close_time > now_ms:
                continue  # 只要已收盘的 K 线
            klines.append({
                "open_time": int(row[0]),
                "close_time": close_time,
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[5]),
            })
        return klines[-limit:]
