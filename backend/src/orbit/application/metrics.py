from __future__ import annotations

from typing import Any

from orbit.application.ports.metric_history_repository import MetricHistoryRepository
from orbit.domain.strategy.engine import now_iso


class MetricHistoryService:
    def __init__(self, repository: MetricHistoryRepository):
        self.repository = repository

    def record(self, *, tick: int, symbols: list[dict[str, Any]], totals: dict[str, float]) -> None:
        timestamp = now_iso()
        self.repository.append_total({
            "tick": tick,
            "timestamp": timestamp,
            "total_equity": totals["total_equity"],
            "total_fee": totals["total_fees"],
            "total_slippage": totals["total_slippage"],
            "profit_transfer_count": sum(item["profit_transfer_count"] for item in symbols),
            "loss_side_reduce_count": sum(item["loss_side_reduce_count"] for item in symbols),
            "position_recovery_count": sum(item["recovery_count"] for item in symbols),
        })
        for symbol in symbols:
            self.repository.append_symbol(symbol["symbol"], {
                "tick": tick,
                "timestamp": timestamp,
                "equity": symbol["equity"],
                "long_notional": symbol["long_qty"] * symbol["price"],
                "short_notional": symbol["short_qty"] * symbol["price"],
                "net_exposure": symbol["net_exposure"],
                "gross_exposure": symbol["gross_exposure"],
                "fee_total": symbol["fee_total"],
            })
