from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping


FIELDS = (
    ("liquidity_minimum", ("market", "liquidity", "minimum_median_daily_quote_volume_usdt"), "币池", "可交易性门槛", "30 日成交额中位数至少达到该金额。", "float", 100_000, 1_000_000_000, None),
    ("liquidity_days", ("market", "liquidity", "lookback_complete_utc_days"), "币池", "成交额回看天数", "只使用完整 UTC 日，历史不足不会进入币池。", "int", 2, 90, None),
    ("breakout_channel", ("signals", "BREAKOUT_MOMENTUM", "channel_lookback_candles"), "突破", "突破通道长度", "当前收盘需要突破此前多少根 15 分钟 K 线。", "int", 4, 384, None),
    ("breakout_volume", ("signals", "BREAKOUT_MOMENTUM", "minimum_relative_quote_volume"), "突破", "最低放量倍数", "当前成交额相对滚动均值至少放大多少倍。", "float", 0.5, 20, None),
    ("pullback_drop", ("signals", "OVERSOLD_REBOUND", "minimum_drop_fraction"), "高位回调", "最低急跌幅度", "观察窗内至少下跌该比例才继续判断企稳。", "float", 0.01, 0.80, None),
    ("pullback_return_candles", ("signals", "OVERSOLD_REBOUND", "return_lookback_candles"), "高位回调", "急跌观察长度", "用多少根 15 分钟 K 线衡量这次急跌。", "int", 2, 384, None),
    ("pullback_cycle", ("signals", "OVERSOLD_REBOUND", "required_long_cycle_state"), "高位回调", "允许的长周期状态", "只有匹配该长周期状态时才产生回调信号。", "choice", None, None, ("UP", "RANGE", "DOWN")),
    ("collapse_days", ("signals", "OVERSOLD_REBOUND", "collapse_lookback_days"), "高位回调", "崩塌判断窗口", "用多少天高点判断市场是否已经中期崩塌。", "int", 2, 90, None),
    ("collapse_drawdown", ("signals", "OVERSOLD_REBOUND", "maximum_drawdown_from_high"), "高位回调", "崩塌回撤上限", "当前价距崩塌窗口高点达到该比例时停止提醒。", "float", 0.05, 0.95, None),
    ("pullback_start_days", ("signals", "OVERSOLD_REBOUND", "pullback_start_high_lookback_days"), "高位回调", "急跌起点高位窗口", "用较短窗口判断这次急跌是否真的从高位开始。", "int", 1, 30, None),
    ("pullback_start_drawdown", ("signals", "OVERSOLD_REBOUND", "maximum_start_drawdown_from_high"), "高位回调", "急跌起点回撤上限", "急跌起点距短窗口高点不得超过该比例。", "float", 0.01, 0.90, None),
    ("strength_quantile", ("signals", "SUSTAINED_STRENGTH", "trend_strength_quantile"), "持续强势", "趋势强度分位", "要求方向对齐趋势强度处于历史分布的高分位。", "float", 0.50, 0.99, None),
    ("strength_short_volume_days", ("signals", "SUSTAINED_STRENGTH", "short_volume_days"), "持续强势", "近期量能窗口", "计算近期平均成交额使用的天数。", "int", 1, 30, None),
    ("strength_long_volume_days", ("signals", "SUSTAINED_STRENGTH", "long_volume_days"), "持续强势", "基准量能窗口", "计算基准平均成交额使用的天数。", "int", 2, 90, None),
    ("strength_volume_ratio", ("signals", "SUSTAINED_STRENGTH", "minimum_volume_ratio"), "持续强势", "最低持续量比", "近期均量除以基准均量至少达到该倍数。", "float", 1, 10, None),
    ("strength_high_days", ("signals", "SUSTAINED_STRENGTH", "high_lookback_days"), "持续强势", "价格高位窗口", "用多少天高点判断价格是否仍处于强势区。", "int", 2, 90, None),
    ("strength_high_distance", ("signals", "SUSTAINED_STRENGTH", "maximum_distance_from_high"), "持续强势", "距高点比例上限", "当前价距高位窗口最高价不得超过该比例。", "float", 0, 0.50, None),
    ("strength_cooldown_hours", ("signals", "SUSTAINED_STRENGTH", "symbol_cooldown_hours"), "持续强势", "同币种冷却小时", "同一币种在该时间内不重复提醒。", "int", 1, 168, None),
    ("daily_candidate_limit", ("workload", "daily_candidate_limit"), "通用", "每日处理上限", "每天最多展示给人工处理的信号数量。", "int", 1, 500, None),
    ("daily_push_limit", ("notifications", "daily_success_limit"), "通用", "每日推送上限", "每天最多成功发送到手机的提醒数量。", "int", 0, 100, None),
)

FIELD_MAP = {row[0]: row for row in FIELDS}


def effective_spec(base: Mapping[str, Any], events: list[Mapping[str, Any]]) -> dict[str, Any]:
    result = deepcopy(dict(base))
    for event in events:
        if event.get("event_type") == "SIGNAL_CONFIGURATION_CHANGED":
            apply_values(result, event.get("values") or {})
    return result


def apply_values(spec: dict[str, Any], values: Mapping[str, Any]) -> None:
    for key, value in values.items():
        field = FIELD_MAP.get(str(key))
        if not field:
            continue
        target = spec
        for part in field[1][:-1]:
            target = target.setdefault(part, {})
        target[field[1][-1]] = value


def validate_values(values: Mapping[str, Any], current: Mapping[str, Any]) -> dict[str, Any]:
    if not values:
        raise ValueError("请至少修改一个参数")
    clean: dict[str, Any] = {}
    for raw_key, raw_value in values.items():
        key = str(raw_key)
        field = FIELD_MAP.get(key)
        if not field:
            raise ValueError("包含页面不支持的参数")
        _, _, _, label, _, kind, minimum, maximum, choices = field
        if kind == "choice":
            value = str(raw_value).strip().upper()
            if value not in choices:
                raise ValueError(f"“{label}”不是允许的选项")
        else:
            try:
                number = float(raw_value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"“{label}”必须填写数字") from exc
            if number < minimum or number > maximum:
                raise ValueError(f"“{label}”允许范围是 {minimum:g} 到 {maximum:g}")
            if kind == "int" and not number.is_integer():
                raise ValueError(f"“{label}”必须填写整数")
            value = int(number) if kind == "int" else number
        clean[key] = value
    merged = dict(configuration_values(current)) | clean
    if merged["strength_short_volume_days"] >= merged["strength_long_volume_days"]:
        raise ValueError("“近期量能窗口”必须小于“基准量能窗口”")
    return clean


def configuration_values(spec: Mapping[str, Any]) -> dict[str, Any]:
    result = {}
    for key, path, *_ in FIELDS:
        value: Any = spec
        for part in path:
            value = value.get(part) if isinstance(value, Mapping) else None
        kind = FIELD_MAP[key][5]
        if value is not None and kind == "int":
            value = int(value)
        elif value is not None and kind == "float":
            value = float(value)
        result[key] = value
    return result


def public_configuration(spec: Mapping[str, Any], revision: int) -> dict[str, Any]:
    values = configuration_values(spec)
    fields = []
    for key, _, group, label, help_text, kind, minimum, maximum, choices in FIELDS:
        fields.append({"key": key, "group": group, "label": label, "help": help_text, "kind": kind, "value": values[key], "minimum": minimum, "maximum": maximum, "choices": list(choices or ())})
    return {"revision": revision, "scope_version": scope_version(revision), "fields": fields}


def scope_version(revision: int) -> str:
    return "SIG3_SCOPE_V1" if revision <= 0 else f"SIG3B_SCOPE_V{revision}"
