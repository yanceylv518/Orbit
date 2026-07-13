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


StreamKey = tuple[str, str]


class MarketFeedService:
    """Poll closed klines and advance account-symbol state per configured interval."""

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
            "intervals": [],
            "last_poll_at": None,
            "last_tick_at": None,
            "last_error": None,
            "tick_count": 0,
            "symbols": [],
            "streams": [],
        }

    @property
    def status(self) -> dict[str, Any]:
        return self.runtime_state["market_feed"]

    def tracked_streams(self) -> dict[StreamKey, set[str]]:
        run_config_by_account = {
            item.get("account_id"): item
            for item in self.run_configs.all()
            if item.get("account_id")
        }
        tracked: dict[StreamKey, set[str]] = {}
        for account in self.accounts.accounts():
            account_id = str(account.get("id", ""))
            run_config = run_config_by_account.get(account_id)
            if not run_config or not run_config.get("enabled", False):
                continue
            snapshot = self.snapshots.get(account_id)
            if not snapshot or snapshot.get("status") != "synced":
                continue
            interval = str(run_config.get("interval") or self.interval)
            for raw_symbol in run_config.get("symbols", []):
                symbol = str(raw_symbol).strip().upper()
                if symbol:
                    tracked.setdefault((interval, symbol), set()).add(account_id)
        return tracked

    def poll(self) -> dict[StreamKey, list[dict[str, Any]]]:
        tracked = self.tracked_streams()
        self.status["symbols"] = sorted({symbol for _, symbol in tracked})
        self.status["intervals"] = sorted({interval for interval, _ in tracked})
        self.status["streams"] = sorted(f"{interval}:{symbol}" for interval, symbol in tracked)
        self.status["last_poll_at"] = now_iso()
        klines_by_stream: dict[StreamKey, list[dict[str, Any]]] = {}
        errors: list[str] = []
        for interval, symbol in tracked:
            try:
                klines_by_stream[(interval, symbol)] = self.feed.closed_klines(symbol, interval, self.limit)
            except Exception as exc:
                errors.append(f"{interval}:{symbol}: {exc}")
        self.status["last_error"] = "; ".join(errors) if errors else None
        return klines_by_stream

    def apply(self, klines_by_stream: dict[StreamKey, list[dict[str, Any]]]) -> dict[str, Any]:
        tracked = self.tracked_streams()
        states = self.states.all()
        changed_accounts: set[str] = set()
        ticks = 0
        for (interval, symbol), klines in klines_by_stream.items():
            for account_id in tracked.get((interval, symbol), set()):
                state = states.get(plan_state_key(account_id, symbol))
                if not state:
                    continue
                last_close = int(state.get("last_kline_close_time") or 0)
                for kline in klines:
                    close_time = int(kline["close_time"])
                    if close_time <= last_close:
                        continue
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
