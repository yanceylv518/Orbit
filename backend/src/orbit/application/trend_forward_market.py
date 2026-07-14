from __future__ import annotations

import hashlib
import json
from typing import Any

from orbit.domain.strategy.trend_basket_runner import TB4_SPEC


class TrendForwardMarketDriver:
    """Build synchronized 12-market close events and drive TB4 forward paper state."""

    def __init__(self, feed: Any, service: Any):
        self.feed = feed
        self.service = service

    def initialize(self, *, code_commit: str, protocol_sha256: str) -> dict[str, Any]:
        required = TB4_SPEC.warmup_ticks + 1
        by_symbol = {
            symbol: self.feed.closed_klines(symbol, "4h", required + 2)
            for symbol in TB4_SPEC.symbols
        }
        common_times = sorted(set.intersection(*(
            {int(item["close_time"]) for item in rows}
            for rows in by_symbol.values()
        )))
        contiguous = self._latest_contiguous(common_times)
        if len(contiguous) < required:
            raise RuntimeError("Binance does not provide enough synchronized TB4 warmup closes")
        times = contiguous[-required:]
        rows_by_symbol = {
            symbol: {int(item["close_time"]): item for item in rows}
            for symbol, rows in by_symbol.items()
        }
        funding = self._funding_by_period(times[0] - TB4_SPEC.interval_ms, times[-1])
        warmup = []
        previous_time = times[0] - TB4_SPEC.interval_ms
        for close_time in times:
            warmup.append({
                "close_time_ms": close_time,
                "closes": {
                    symbol: float(rows_by_symbol[symbol][close_time]["close"])
                    for symbol in TB4_SPEC.symbols
                },
                "funding_rates": self._period_funding(funding, previous_time, close_time),
            })
            previous_time = close_time
        fingerprints = {
            symbol: hashlib.sha256(json.dumps(
                {
                    "klines": [rows_by_symbol[symbol][time] for time in times],
                    "funding": funding[symbol],
                },
                sort_keys=True, separators=(",", ":"),
            ).encode("utf-8")).hexdigest()
            for symbol in TB4_SPEC.symbols
        }
        return self.service.initialize(
            start_time_ms=times[-1] + TB4_SPEC.interval_ms,
            warmup_closes=warmup,
            input_fingerprints=fingerprints,
            code_commit=code_commit,
            protocol_sha256=protocol_sha256,
        )

    def poll_once(self) -> dict[str, Any]:
        if not self.service.runner.times:
            raise RuntimeError("TB4 forward must be initialized before polling")
        last_time = self.service.runner.times[-1]
        by_symbol = {
            symbol: self.feed.closed_klines(symbol, "4h", 3)
            for symbol in TB4_SPEC.symbols
        }
        common_times = sorted(set.intersection(*(
            {int(item["close_time"]) for item in rows}
            for rows in by_symbol.values()
        )))
        pending_times = [time for time in common_times if time > last_time]
        if not pending_times:
            return {"ticks": 0, "snapshot": self.service.snapshot()}
        if pending_times[0] - last_time != TB4_SPEC.interval_ms:
            raise RuntimeError("TB4 market feed has a 4h continuity gap")
        rows_by_symbol = {
            symbol: {int(item["close_time"]): item for item in rows}
            for symbol, rows in by_symbol.items()
        }
        funding = self._funding_by_period(last_time, pending_times[-1])
        ticks = 0
        previous_time = last_time
        for close_time in pending_times:
            result = self.service.ingest_close(
                close_time,
                {
                    symbol: float(rows_by_symbol[symbol][close_time]["close"])
                    for symbol in TB4_SPEC.symbols
                },
                self._period_funding(funding, previous_time, close_time),
            )
            if not result["duplicate"]:
                ticks += 1
            previous_time = close_time
        return {"ticks": ticks, "snapshot": self.service.snapshot()}

    def _funding_by_period(self, start_time: int, end_time: int) -> dict[str, list[dict[str, Any]]]:
        return {
            symbol: self.feed.funding_rates(symbol, start_time, end_time)
            for symbol in TB4_SPEC.symbols
        }

    @staticmethod
    def _period_funding(
        funding: dict[str, list[dict[str, Any]]],
        previous_time: int,
        current_time: int,
    ) -> dict[str, float]:
        return {
            symbol: sum(
                float(item["funding_rate"])
                for item in rows
                if previous_time < int(item["funding_time_ms"]) <= current_time
            )
            for symbol, rows in funding.items()
        }

    @staticmethod
    def _latest_contiguous(times: list[int]) -> list[int]:
        current: list[int] = []
        for value in times:
            if current and value - current[-1] != TB4_SPEC.interval_ms:
                current = []
            current.append(value)
        return current
