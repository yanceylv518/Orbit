from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from typing import Any, Callable

from orbit.domain.strategy.trend_basket_runner import TB4_SPEC, tb4_spec_fingerprint


TB4_STRATEGY_ID = "TB4_TREND_BASKET_V1"


def tb4_spec_payload() -> dict[str, Any]:
    """Serialize the frozen runner specification without introducing UI defaults."""
    return {
        "symbols": list(TB4_SPEC.symbols),
        "interval_ms": TB4_SPEC.interval_ms,
        "momentum_lookbacks": list(TB4_SPEC.momentum_lookbacks),
        "volatility_lookback": TB4_SPEC.volatility_lookback,
        "rebalance_ticks": TB4_SPEC.rebalance_ticks,
        "target_portfolio_vol": TB4_SPEC.target_portfolio_vol,
        "gross_cap": TB4_SPEC.gross_cap,
        "roundtrip_cost_pct": TB4_SPEC.roundtrip_cost_pct,
    }


def _definition_hash() -> str:
    payload = {
        "id": TB4_STRATEGY_ID,
        "version": "1",
        "implementation": "orbit.domain.strategy.trend_basket_runner",
        "spec": tb4_spec_payload(),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _period_days(ticks: int) -> float:
    return ticks * TB4_SPEC.interval_ms / 86_400_000


@dataclass(frozen=True)
class StrategyDefinition:
    id: str
    name: str
    version: str
    definition_hash: str
    spec_sha256: str
    summary: str
    mechanics: tuple[dict[str, str], ...]
    known_risks: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        spec = tb4_spec_payload()
        return {
            "id": self.id,
            "strategy_id": self.id,
            "name": self.name,
            "version": self.version,
            "implementation": "orbit.domain.strategy.trend_basket_runner",
            "supersedes": None,
            "definition_hash": self.definition_hash,
            "spec_sha256": self.spec_sha256,
            "summary": self.summary,
            "mechanics": [dict(item) for item in self.mechanics],
            "known_risks": list(self.known_risks),
            "spec": spec,
            "display": {
                "interval_hours": TB4_SPEC.interval_ms / 3_600_000,
                "momentum_lookback_days": [
                    _period_days(ticks) for ticks in TB4_SPEC.momentum_lookbacks
                ],
                "volatility_lookback_days": _period_days(TB4_SPEC.volatility_lookback),
                "rebalance_days": _period_days(TB4_SPEC.rebalance_ticks),
                "target_portfolio_vol_pct": TB4_SPEC.target_portfolio_vol * 100,
                "gross_cap_pct": TB4_SPEC.gross_cap * 100,
            },
        }


TB4_DEFINITION = StrategyDefinition(
    id=TB4_STRATEGY_ID,
    name="多周期趋势",
    version="1",
    definition_hash=_definition_hash(),
    spec_sha256=tb4_spec_fingerprint(),
    summary=(
        "在 12 个 USDT 永续合约上，根据多个时间尺度的价格趋势决定做多或做空，"
        "再按近期波动率分配仓位并每 7 天再平衡。"
    ),
    mechanics=(
        {
            "title": "何时观察",
            "body": "只使用已经收盘的 4 小时 K 线；未收盘行情不会进入信号。",
        },
        {
            "title": "如何判断方向",
            "body": "综合 14、28、56、84、168 天动量；综合结果为正做多，为负做空。",
        },
        {
            "title": "如何决定仓位",
            "body": "使用 28 天波动率进行风险分配，组合目标年化波动率为 10%，总敞口不超过 100%。",
        },
        {
            "title": "何时买卖",
            "body": "每 7 天生成一次目标仓位，并在下一根 4 小时 K 线执行；交易是目标仓位差额，而非主观择时。",
        },
        {
            "title": "如何计算成本",
            "body": "研究基准计入 0.14% 往返成本和实际 Funding；实盘中心另外记录真实手续费、滑点与成交偏差。",
        },
        {
            "title": "何时停止新增风险",
            "body": "paper 或 live 从各自基准回撤达到 30% 时，实盘协议拒绝继续执行。",
        },
    ),
    known_risks=(
        "当前市场集合存在历史幸存者偏差。",
        "样本外区间可能偏向强趋势阶段。",
        "500 USDT 不能完整表达所有 12 币目标。",
        "固定 0.14% 成本不等于未来真实成本。",
        "趋势策略在震荡市场可能持续亏损。",
        "paper 与 live 样本量仍有限。",
        "Binance 下线、交易规则和市场流动性会变化。",
    ),
)


class StrategyCatalogService:
    """Read-only catalog for frozen strategy definitions and sanitized lifecycle state."""

    def __init__(
        self,
        trend_forward_snapshot: Callable[[], dict[str, Any]],
        live_execution_snapshot: Callable[[], dict[str, Any]],
        *,
        live_capital_usdt: float,
        live_configured: bool = False,
    ):
        self._trend_forward_snapshot = trend_forward_snapshot
        self._live_execution_snapshot = live_execution_snapshot
        self._live_capital_usdt = float(live_capital_usdt)
        self._live_configured = bool(live_configured)

    def strategies(self) -> list[dict[str, Any]]:
        item = self.strategy(TB4_STRATEGY_ID)
        return [{
            "id": item["id"],
            "name": item["name"],
            "version": item["version"],
            "definition_hash": item["definition_hash"],
            "lifecycle": item["lifecycle"],
        }]

    def strategy(self, strategy_id: str) -> dict[str, Any]:
        if strategy_id != TB4_STRATEGY_ID:
            raise KeyError(strategy_id)
        result = TB4_DEFINITION.as_dict()
        result["lifecycle"] = self._lifecycle()
        result["evidence"] = {
            "status": "NOT_STRUCTURED",
            "message": "结构化证据尚未接入（待 SC-1 bundle + SC-4）；原始研究档案仍保留在研究平台。",
        }
        return deepcopy(result)

    def _lifecycle(self) -> dict[str, Any]:
        forward = self._trend_forward_snapshot() or {}
        live = self._live_execution_snapshot() or {}
        forward_status = str(forward.get("status") or "NOT_STARTED")
        live_status = str(live.get("status") or "DISABLED")
        live_configured = self._live_configured or bool(live.get("account_id"))

        phases = ["BACKTEST_CONFIRMED"]
        if forward_status != "NOT_STARTED":
            phases.append("PAPER_FORWARD")
        if live_configured:
            phases.append("LIVE_PILOT")

        primary = phases[-1]
        return {
            "primary": primary,
            "phases": phases,
            "paper_forward": {
                "status": forward_status,
                "elapsed_days": forward.get("elapsed_days"),
                "minimum_forward_days": forward.get("minimum_forward_days"),
                "progress_ratio": forward.get("progress_ratio"),
                "verdict": forward.get("verdict"),
            },
            "live_pilot": {
                "configured": live_configured,
                "status": live_status,
                "capital_usdt": self._live_capital_usdt if live_configured else None,
            },
        }
