from __future__ import annotations

from typing import Any

from orbit.application.ports.account_repository import AccountRepository
from orbit.application.ports.account_snapshot_repository import AccountSnapshotRepository
from orbit.application.ports.market_feed import MarketDataFeed
from orbit.application.ports.run_config_repository import RunConfigRepository
from orbit.application.ports.symbol_state_repository import SymbolStateRepository
from orbit.application.symbol_states import SymbolStateService
from orbit.domain.strategy.engine import now_iso
from orbit.domain.strategy.state_keys import plan_state_key


class MarketFeedService:
    """真实模式的行情循环：拉已收盘 K 线，按账户推进 symbol 生命周期状态。

    分两阶段以便调用方控制锁边界：
    - poll(): 网络 I/O，锁外执行
    - apply(): 状态推进，锁内执行
    """

    def __init__(
        self,
        feed: MarketDataFeed,
        accounts: AccountRepository,
        run_configs: RunConfigRepository,
        snapshots: AccountSnapshotRepository,
        states: SymbolStateRepository,
        symbol_states: SymbolStateService,
        runtime_state: dict[str, Any],
        *,
        interval: str = "1m",
        limit: int = 3,
    ):
        self.feed = feed
        self.accounts = accounts
        self.run_configs = run_configs
        self.snapshots = snapshots
        self.states = states
        self.symbol_states = symbol_states
        self.runtime_state = runtime_state
        self.interval = interval
        self.limit = limit
        self.runtime_state["market_feed"] = {
            "enabled": True,
            "interval": interval,
            "last_poll_at": None,
            "last_tick_at": None,
            "last_error": None,
            "tick_count": 0,
            "symbols": [],
        }

    @property
    def status(self) -> dict[str, Any]:
        return self.runtime_state["market_feed"]

    def tracked_symbols(self) -> dict[str, set[str]]:
        """symbol -> 需要推进该 symbol 的账户集合（run_config 启用且账户已同步过）。"""
        run_config_by_account = {
            item.get("account_id"): item
            for item in self.run_configs.all()
            if item.get("account_id")
        }
        tracked: dict[str, set[str]] = {}
        for account in self.accounts.accounts():
            account_id = str(account.get("id", ""))
            run_config = run_config_by_account.get(account_id)
            if not run_config or not run_config.get("enabled", False):
                continue
            snapshot = self.snapshots.get(account_id)
            if not snapshot or snapshot.get("status") != "synced":
                continue
            for symbol in run_config.get("symbols", []):
                symbol = str(symbol).strip().upper()
                if symbol:
                    tracked.setdefault(symbol, set()).add(account_id)
        return tracked

    def poll(self) -> dict[str, list[dict[str, Any]]]:
        """网络阶段（锁外）：拉取所有被跟踪 symbol 的已收盘 K 线。"""
        tracked = self.tracked_symbols()
        self.status["symbols"] = sorted(tracked)
        self.status["last_poll_at"] = now_iso()
        klines_by_symbol: dict[str, list[dict[str, Any]]] = {}
        errors: list[str] = []
        for symbol in tracked:
            try:
                klines_by_symbol[symbol] = self.feed.closed_klines(symbol, self.interval, self.limit)
            except Exception as exc:  # 单 symbol 失败不影响其他
                errors.append(f"{symbol}: {exc}")
        self.status["last_error"] = "; ".join(errors) if errors else None
        return klines_by_symbol

    def apply(self, klines_by_symbol: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
        """状态推进阶段（锁内）：对每根未处理过的收盘 K 线推进一 tick。"""
        tracked = self.tracked_symbols()
        states = self.states.all()
        changed_accounts: set[str] = set()
        ticks = 0

        for symbol, klines in klines_by_symbol.items():
            account_ids = tracked.get(symbol) or set()
            for account_id in account_ids:
                key = plan_state_key(account_id, symbol)
                state = states.get(key)
                if not state:
                    continue  # 生命周期状态由同步创建；行情只推进已存在的
                last_close = int(state.get("last_kline_close_time") or 0)
                for kline in klines:
                    close_time = int(kline["close_time"])
                    if close_time <= last_close:
                        continue  # 幂等：同一根 K 线不重复推进
                    self.symbol_states.advance_state_with_price(
                        state,
                        price=kline["close"],
                        close_time=close_time,
                    )
                    last_close = close_time
                    ticks += 1
                    changed_accounts.add(account_id)

        if ticks:
            self.states.replace_all(states)
            self.status["last_tick_at"] = now_iso()
            self.status["tick_count"] = int(self.status.get("tick_count", 0)) + ticks
        return {"ticks": ticks, "changed_account_ids": changed_accounts}
