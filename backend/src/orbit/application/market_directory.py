from __future__ import annotations

from datetime import datetime, timezone
import json
from threading import RLock
import time
from typing import Any, Callable
from urllib.request import Request, urlopen


MAINSTREAM = {"BTC", "ETH", "BNB", "SOL", "XRP", "DOGE", "ADA", "AVAX", "LINK", "DOT", "LTC", "BCH"}
COMMODITIES = {"XAU", "XAG", "PAXG", "GOLD", "SILVER", "OIL", "WTI", "BRENT"}
STOCKS = {"TSLA", "NVDA", "AAPL", "AMZN", "GOOGL", "META", "MSFT", "COIN", "MSTR"}


class MarketDirectoryService:
    """Current Binance perpetual-contract directory; deliberately independent of history files."""

    def __init__(self, *, base_url: str = "https://fapi.binance.com", minimum_volume_usdt: float = 30_000_000,
                 opener: Callable[..., Any] = urlopen, cache_seconds: int = 60):
        self.base_url = base_url.rstrip("/")
        self.minimum_volume_usdt = minimum_volume_usdt
        self.opener = opener
        self.cache_seconds = cache_seconds
        self._lock = RLock()
        self._cached_at = 0.0
        self._snapshot: dict[str, Any] | None = None

    def current(self, *, refresh: bool = False) -> dict[str, Any]:
        with self._lock:
            if not refresh and self._snapshot and time.monotonic() - self._cached_at < self.cache_seconds:
                return self._snapshot
            exchange = self._get("/fapi/v1/exchangeInfo")
            tickers = self._get("/fapi/v1/ticker/24hr")
            ticker_by_symbol = {row.get("symbol"): row for row in tickers if isinstance(row, dict)}
            now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
            items = []
            for contract in exchange.get("symbols") or []:
                if contract.get("contractType") != "PERPETUAL" or contract.get("quoteAsset") != "USDT":
                    continue
                symbol = str(contract.get("symbol") or "")
                ticker = ticker_by_symbol.get(symbol, {})
                volume = float(ticker.get("quoteVolume") or 0)
                change_24h_pct = float(ticker.get("priceChangePercent") or 0)
                trading = contract.get("status") == "TRADING"
                in_scope = trading and volume >= self.minimum_volume_usdt
                onboard = int(contract.get("onboardDate") or 0)
                items.append({
                    "symbol": symbol,
                    "volume_24h_usdt": volume,
                    "change_24h_pct": change_24h_pct,
                    "last_price": float(ticker.get("lastPrice") or 0),
                    "open_24h": float(ticker.get("openPrice") or 0),
                    "high_24h": float(ticker.get("highPrice") or 0),
                    "low_24h": float(ticker.get("lowPrice") or 0),
                    "weighted_average_24h": float(ticker.get("weightedAvgPrice") or 0),
                    "volume_24h_base": float(ticker.get("volume") or 0),
                    "trade_count_24h": int(ticker.get("count") or 0),
                    "listed_at_ms": onboard or None,
                    "listing_days": max(0, (now_ms - onboard) // 86_400_000) if onboard else None,
                    "category": self._category(symbol),
                    "scan_state": "扫描中" if in_scope else "未扫描",
                    "scan_reason": "" if in_scope else ("未开放交易" if not trading else "24 小时成交额不足"),
                    "status": contract.get("status"),
                })
            items.sort(key=lambda row: (-row["volume_24h_usdt"], row["symbol"]))
            self._snapshot = {"updated_at": datetime.now(timezone.utc).isoformat(), "minimum_volume_usdt": self.minimum_volume_usdt, "items": items}
            self._cached_at = time.monotonic()
            return self._snapshot

    def _get(self, path: str) -> Any:
        request = Request(f"{self.base_url}{path}", headers={"Accept": "application/json", "User-Agent": "Orbit/1.0"})
        with self.opener(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))

    @staticmethod
    def _category(symbol: str) -> str:
        base = symbol.removesuffix("USDT")
        if base in MAINSTREAM:
            return "主流币"
        if base in STOCKS or base.endswith(("STOCK", "EQUITY")):
            return "股票类"
        if base in COMMODITIES or base.startswith(("XAU", "XAG")):
            return "大宗商品"
        return "山寨币"
