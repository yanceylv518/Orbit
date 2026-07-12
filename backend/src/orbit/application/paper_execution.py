from __future__ import annotations

from typing import Any

from orbit.application.ports.run_config_repository import RunConfigRepository
from orbit.application.ports.symbol_state_repository import SymbolStateRepository
from orbit.application.runtime_events import RuntimeEventService
from orbit.domain.strategy.engine import EventEngine, d


class PaperExecutionService:
    """paper 模式：行情 tick 推进生命周期后，对 mode=paper 的账户执行虚拟成交。

    虚拟仓位/账本完全由内核 fills 模型演进，不再被交易所快照覆盖——
    与 live 共用同一套决策、规则与 guard，只是成交是模拟的。
    """

    def __init__(
        self,
        engine: EventEngine,
        run_configs: RunConfigRepository,
        states: SymbolStateRepository,
        runtime_events: RuntimeEventService,
    ):
        self.engine = engine
        self.run_configs = run_configs
        self.states = states
        self.runtime_events = runtime_events

    def paper_account_ids(self) -> set[str]:
        return {
            str(item.get("account_id"))
            for item in self.run_configs.all()
            if item.get("account_id")
            and item.get("enabled", False)
            and item.get("mode") == "paper"
        }

    def on_market_tick(self, changed_account_ids: set[str]) -> dict[str, Any]:
        targets = self.paper_account_ids() & {str(item) for item in changed_account_ids}
        if not targets:
            return {"events": 0, "risk_events": 0, "accounts": set()}

        states = self.states.all()
        total_events = 0
        total_risks = 0
        touched: set[str] = set()
        for state in states.values():
            account_id = str(state.get("account_id") or "")
            if account_id not in targets:
                continue
            price = d(state.get("last_price") or 0)
            if price <= 0:
                continue
            events, risks = self.engine.execute_paper_tick(state, price)
            if events or risks:
                self.runtime_events.record_engine_results(
                    events, risks, account_id=account_id,
                )
                total_events += len(events)
                total_risks += len(risks)
                touched.add(account_id)
        if touched:
            self.states.replace_all(states)
        return {"events": total_events, "risk_events": total_risks, "accounts": touched}
