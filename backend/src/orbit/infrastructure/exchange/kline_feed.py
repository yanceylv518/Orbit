from __future__ import annotations

import json
import threading
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
    def __init__(self, message: str, *, category: str = "HTTP_ERROR", status_code: int | None = None, retry_after_seconds: float | None = None):
        super().__init__(message)
        self.category = category
        self.status_code = status_code
        self.retry_after_seconds = retry_after_seconds


class BinanceWeightLimiter:
    """Process-wide rolling weight budget with room left for other strategies."""

    def __init__(self, weight_per_minute: int = 1200, *, clock=time.monotonic, sleeper=time.sleep):
        self.capacity = max(1, int(weight_per_minute))
        self.clock = clock
        self.sleeper = sleeper
        self._window_started = float(clock())
        self._used = 0
        self._blocked_until = 0.0
        self._lock = threading.Lock()

    def acquire(self, weight: int) -> None:
        weight = max(1, int(weight))
        while True:
            with self._lock:
                now = float(self.clock())
                if now - self._window_started >= 60:
                    self._window_started, self._used = now, 0
                blocked = max(0.0, self._blocked_until - now)
                if blocked:
                    raise MarketFeedError("Binance rate-limit backoff is active", category="RATE_LIMIT", retry_after_seconds=blocked)
                wait = 0.0
                if self._used + weight <= self.capacity:
                    self._used += weight
                    return
                wait = max(0.01, 60 - (now - self._window_started))
            self.sleeper(wait)

    def backoff(self, seconds: float) -> None:
        with self._lock:
            self._blocked_until = max(self._blocked_until, float(self.clock()) + max(0.0, float(seconds)))


GLOBAL_BINANCE_LIMITER = BinanceWeightLimiter()


class BinanceKlineFeed:
    def __init__(self, *, base_url: str = FAPI_PUBLIC_BASE_URL, timeout: float = 8, limiter: BinanceWeightLimiter | None = None):
        self.base_url = base_url
        self.timeout = timeout
        self.limiter = limiter or GLOBAL_BINANCE_LIMITER
        self._rate_limit_failures = 0

    def closed_klines(self, symbol: str, interval: str, limit: int) -> list[dict[str, Any]]:
        if interval not in INTERVAL_MS:
            raise MarketFeedError(f"Unsupported kline interval: {interval}")
        wanted = max(1, int(limit))
        rows: dict[int, dict[str, Any]] = {}
        end_time_ms = None
        while len(rows) < wanted:
            request_limit = min(1500, max(2, wanted - len(rows) + 1))
            page = self._request_klines(symbol, interval, request_limit, end_time_ms=end_time_ms)
            if not page:
                break
            rows.update({int(row["close_time"]): row for row in page})
            oldest_open = min(int(row["open_time"]) for row in page)
            next_end = oldest_open - 1
            if end_time_ms is not None and next_end >= end_time_ms:
                break
            end_time_ms = next_end
            if len(page) < request_limit - 1:
                break
        return [rows[key] for key in sorted(rows)][-wanted:]

    def _request_klines(self, symbol: str, interval: str, request_limit: int, *, end_time_ms: int | None) -> list[dict[str, Any]]:
        self.limiter.acquire(self._kline_weight(request_limit))
        parameters = {
            "symbol": symbol,
            "interval": interval,
            "limit": request_limit,
        }
        if end_time_ms is not None:
            parameters["endTime"] = int(end_time_ms)
        query = urlencode(parameters)
        request = Request(f"{self.base_url}/fapi/v1/klines?{query}", method="GET")
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw = json.loads(response.read().decode("utf-8"))
            self._rate_limit_failures = 0
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            retry_after = self._retry_after(exc)
            category = "RATE_LIMIT" if exc.code in (418, 429) else "HTTP_ERROR"
            if category == "RATE_LIMIT":
                self._rate_limit_failures += 1
                retry_after = max(retry_after, min(15 * (2 ** (self._rate_limit_failures - 1)), 300))
                self.limiter.backoff(retry_after)
            raise MarketFeedError(f"Kline HTTP {exc.code}: {detail}", category=category, status_code=exc.code, retry_after_seconds=retry_after) from exc
        except URLError as exc:
            reason = str(exc.reason)
            category = "TIMEOUT" if "timed out" in reason.lower() else "NETWORK_ERROR"
            raise MarketFeedError(f"Kline network error: {reason}", category=category) from exc

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
                "quote_volume": float(row[7]),
            })
        return klines

    @staticmethod
    def _kline_weight(limit: int) -> int:
        if limit < 100:
            return 1
        if limit < 500:
            return 2
        if limit <= 1000:
            return 5
        return 10

    @staticmethod
    def _retry_after(exc: HTTPError) -> float:
        raw = exc.headers.get("Retry-After") if exc.headers else None
        try:
            return max(1.0, float(raw))
        except (TypeError, ValueError):
            return 120.0 if exc.code == 418 else 60.0

    def perpetual_symbols(self) -> list[str]:
        request = Request(f"{self.base_url}/fapi/v1/exchangeInfo", method="GET")
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise MarketFeedError(f"Exchange info HTTP {exc.code}") from exc
        except URLError as exc:
            raise MarketFeedError(f"Exchange info network error: {exc.reason}") from exc
        return sorted(
            str(row["symbol"])
            for row in raw.get("symbols", [])
            if row.get("status") == "TRADING"
            and row.get("contractType") == "PERPETUAL"
            and row.get("quoteAsset") == "USDT"
        )

    def funding_rates(
        self,
        symbol: str,
        start_time_ms: int,
        end_time_ms: int,
        *,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        query = urlencode({
            "symbol": symbol,
            "startTime": int(start_time_ms) + 1,
            "endTime": int(end_time_ms),
            "limit": min(1000, max(1, int(limit))),
        })
        request = Request(f"{self.base_url}/fapi/v1/fundingRate?{query}", method="GET")
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise MarketFeedError(f"Funding HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise MarketFeedError(f"Funding network error: {exc.reason}") from exc
        return [
            {
                "funding_time_ms": int(row["fundingTime"]),
                "funding_rate": float(row["fundingRate"]),
            }
            for row in raw
            if start_time_ms < int(row["fundingTime"]) <= end_time_ms
        ]
