from __future__ import annotations

import math
from typing import Sequence

"""π̂ 估计与几何扫描（STRATEGY_LOGIC §2 / §10.1 的离线标定内核）。

策略的品种准入条件：π > 1 − (a − c) / θ
其中 π = "偏离锚点 a% 的行情在触及 θ% 前回归"的概率，
a = 偏斜触发幅度，θ = 趋势确认幅度，c = 一来一回成本率。

本模块只做纯计算：锚点重演统计、Wilson 置信区间、期望值与扫描。
数据获取与 CLI 在 backend/tools/ 下。
"""


def excursion_outcomes(
    closes: Sequence[float],
    a_pct: float,
    theta_pct: float,
    reversion_pct: float = 0.25,
) -> tuple[int, int]:
    """锚点重演：返回 (回归次数, 延伸次数)。

    规则（与策略语义一致的一阶简化）：
    - 锚点 = 当前段起点；|m| 首次 ≥ a 记一次 excursion（方向锁定）；
    - 之后同方向 |m| ≥ θ → 延伸（趋势确认，偏斜押注止损）；
    - |m| 回落到 ≤ reversion_pct（近似回到锚点）→ 回归（偏斜押注获利）；
    - 每次结束在当前价重锚，继续统计。
    """
    if a_pct <= 0 or theta_pct <= a_pct:
        raise ValueError("需要 0 < a < θ")
    reversions = 0
    extensions = 0
    anchor: float | None = None
    direction = 0  # 0=无 excursion，+1 向上，-1 向下

    for price in closes:
        if price <= 0:
            continue
        if anchor is None:
            anchor = price
            continue
        move_pct = (price / anchor - 1) * 100
        if direction == 0:
            if abs(move_pct) >= a_pct:
                direction = 1 if move_pct > 0 else -1
            continue
        directed = move_pct * direction
        if directed >= theta_pct:
            extensions += 1
            anchor = price
            direction = 0
        elif directed <= reversion_pct:
            reversions += 1
            anchor = price
            direction = 0
    return reversions, extensions


def wilson_interval(successes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    if total <= 0:
        return 0.0, 0.0
    phat = successes / total
    denom = 1 + z * z / total
    centre = phat + z * z / (2 * total)
    margin = z * math.sqrt(phat * (1 - phat) / total + z * z / (4 * total * total))
    return max(0.0, (centre - margin) / denom), min(1.0, (centre + margin) / denom)


def pi_required(a_pct: float, theta_pct: float, cost_pct: float) -> float:
    """盈亏平衡回归概率：π > 1 − (a − c)/θ。"""
    return 1 - (a_pct - cost_pct) / theta_pct


def expected_value_per_bet(pi: float, a_pct: float, theta_pct: float, cost_pct: float) -> float:
    """单次偏斜押注期望（单位：占名义的 %）：E = π·a − (1−π)(θ−a) − c。"""
    return pi * a_pct - (1 - pi) * (theta_pct - a_pct) - cost_pct


def estimate(
    closes: Sequence[float],
    a_pct: float,
    theta_pct: float,
    cost_pct: float,
    *,
    reversion_pct: float = 0.25,
) -> dict:
    reversions, extensions = excursion_outcomes(closes, a_pct, theta_pct, reversion_pct)
    total = reversions + extensions
    pi_hat = reversions / total if total else 0.0
    low, high = wilson_interval(reversions, total)
    required = pi_required(a_pct, theta_pct, cost_pct)
    return {
        "a_pct": a_pct,
        "theta_pct": theta_pct,
        "cost_pct": cost_pct,
        "excursions": total,
        "reversions": reversions,
        "extensions": extensions,
        "pi_hat": pi_hat,
        "pi_ci_low": low,
        "pi_ci_high": high,
        "pi_required": required,
        # C8 准入：置信下界必须显著高于盈亏平衡线
        "admitted": total >= 30 and low > required,
        "expected_value_pct": expected_value_per_bet(pi_hat, a_pct, theta_pct, cost_pct),
    }


def geometry_scan(
    closes: Sequence[float],
    a_grid: Sequence[float],
    theta_grid: Sequence[float],
    cost_pct: float,
) -> list[dict]:
    """(a, θ) 几何扫描：对每个组合估计 π̂ 与单注期望，供选择最优触发几何。"""
    rows = []
    for a_pct in a_grid:
        for theta_pct in theta_grid:
            if theta_pct <= a_pct:
                continue
            rows.append(estimate(closes, a_pct, theta_pct, cost_pct))
    return sorted(rows, key=lambda row: row["expected_value_pct"], reverse=True)
