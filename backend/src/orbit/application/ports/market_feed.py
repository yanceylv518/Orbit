from __future__ import annotations

from typing import Any, Protocol


class MarketDataFeed(Protocol):
    """行情源端口：返回已收盘 K 线（升序）。

    真实模式的 tick 语义 = 1 根已收盘 K 线；策略生命周期只由收盘价推进，
    避免盘中未收盘价格反复触发。
    """

    def closed_klines(self, symbol: str, interval: str, limit: int) -> list[dict[str, Any]]:
        """Return ascending closed klines: {open_time, close_time, open, high, low, close, volume}."""
