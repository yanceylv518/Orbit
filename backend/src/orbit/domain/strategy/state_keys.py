from __future__ import annotations

from typing import Any

# 策略生命周期状态（锚点/相位/计数器）必须按账户隔离：
# 两个账户持有同一 symbol 时，锚点与相位各自独立，键为 "account_id::symbol"。
# dry_run 模拟态没有账户维度，仍使用裸 symbol 键（两种键不会同时出现在同一运行模式）。

PLAN_STATE_KEY_SEPARATOR = "::"


def plan_state_key(account_id: str, symbol: str) -> str:
    return f"{account_id}{PLAN_STATE_KEY_SEPARATOR}{symbol}"


def states_for_account(
    states: dict[str, dict[str, Any]],
    account_id: str,
) -> dict[str, dict[str, Any]]:
    """Return symbol -> state for one account, tolerating legacy plain-symbol keys."""
    result: dict[str, dict[str, Any]] = {}
    for key, state in states.items():
        symbol = str(state.get("symbol") or key.split(PLAN_STATE_KEY_SEPARATOR)[-1])
        owner = state.get("account_id") or state.get("exchange_account_id")
        if owner == account_id:
            result[symbol] = state
        elif owner is None and PLAN_STATE_KEY_SEPARATOR not in key:
            # 旧数据：裸 symbol 键且未标注账户，视为任意账户可读（一次性迁移期）
            result.setdefault(symbol, state)
    return result


def lookup_plan_state(
    states: dict[str, dict[str, Any]],
    account_id: str,
    symbol: str,
) -> dict[str, Any] | None:
    state = states.get(plan_state_key(account_id, symbol))
    if state is not None:
        return state
    legacy = states.get(symbol)
    if legacy is not None:
        owner = legacy.get("account_id") or legacy.get("exchange_account_id")
        if owner in (None, account_id):
            return legacy
    return None
