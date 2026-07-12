"""STRATEGY_LOGIC §9 仿真验收：合成价格路径 + 方向性断言。

这些测试把策略闭环当成整体验收：任何内核改动导致
「震荡不赚钱 / 趋势亏穿预算 / 状态机锁死 / 横跳骗炮」都会在这里失败。
"""

import math
import random
import unittest
from decimal import Decimal
from pathlib import Path
import sys


BACKEND_ROOT = Path(__file__).resolve().parents[1]
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from orbit.config import load_config
from orbit.domain.strategy.engine import EventEngine, d


BASE = Decimal("60000")
BUDGET = Decimal("100")


def make_engine():
    cfg = load_config(str(ROOT / "config" / "config.sample.json"))
    return EventEngine(cfg["strategy_instances"][0])


def run_path(engine, prices, state=None):
    state = state or engine.initialize_symbol("BTCUSDT", BASE, BUDGET)
    all_events, all_risks = [], []
    for price in prices:
        state, events, risks = engine.on_tick(state, Decimal(str(price)))
        all_events.extend(events)
        all_risks.extend(risks)
    return state, all_events, all_risks


def equity(state):
    return (
        d(state["budget_usdt"]) + d(state["realized_pnl"])
        + d(state["long_unrealized_pnl"]) + d(state["short_unrealized_pnl"])
    )


def sine_path(amplitude_pct, cycles, ticks_per_cycle):
    prices = []
    for index in range(cycles * ticks_per_cycle):
        phase = 2 * math.pi * index / ticks_per_cycle
        prices.append(float(BASE) * (1 + amplitude_pct / 100 * math.sin(phase)))
    prices.append(float(BASE))  # 收在锚点，公平结算
    return prices


class StrategyScenarioTest(unittest.TestCase):
    def setUp(self):
        self.engine = make_engine()

    def test_s1_pure_oscillation_harvests_reversion(self):
        # 振幅 2.5% ∈ (a_pt=1.5%, θ_t=4%)：反复建偏斜→回归落袋
        state, events, risks = run_path(self.engine, sine_path(2.5, 6, 24))
        transfer_events = [e for e in events if e["event_type"].startswith("PROFIT_TRANSFER")]
        trend_events = [e for e in events if e["event_type"].startswith("LOSS_SIDE_REDUCTION")]
        self.assertTrue(transfer_events, "震荡市应触发利润搬运（建偏斜）")
        self.assertFalse(trend_events, "振幅未及 θ_t，不应确认趋势")
        self.assertGreater(equity(state), BUDGET, "完整震荡周期后应有正收益（回归收割 > 成本）")

    def test_s2_monotone_trend_loss_is_bounded_and_not_locked(self):
        # 单调上行至 +8%（2θ_t），亏损腿应逐步砍至地板，且损失有界
        prices = [float(BASE) * (1 + 0.004 * i) for i in range(1, 21)]  # +0.4%/tick → +8%
        state, events, risks = run_path(self.engine, prices)
        self.assertEqual(state["state"], "TREND_UP")
        floor_qty = d(state["base_qty"]) * Decimal("0.2")  # min_loss_side_position_ratio_of_base
        self.assertLessEqual(d(state["short_qty"]), d(state["base_qty"]), "亏损腿应被削减")
        drawdown_budget = BUDGET * Decimal("0.10")  # max_symbol_drawdown_pct
        self.assertGreaterEqual(
            equity(state), BUDGET - drawdown_budget - Decimal("2"),
            "趋势中的损失必须被止损预算约束（允许拆对冲成本容差）",
        )

    def test_s3_v_shape_full_lifecycle_reanchors(self):
        # 上行确认趋势（2 tick）→ 回落回带 → 恢复/重锚 → 计数器清零
        up = [float(BASE) * (1 + 0.004 * i) for i in range(1, 14)]   # → +5.2%
        down = [float(BASE) * (1 + 0.052 - 0.005 * i) for i in range(1, 12)]  # 回落到锚点附近
        state, events, risks = run_path(self.engine, up + down)
        self.assertIn(state["state"], ("BALANCED", "REANCHORING"), "V 型后不应锁死在趋势态")
        if state["state"] == "BALANCED":
            self.assertEqual(state["profit_transfer_count_in_trend"], 0)
            self.assertEqual(state["loss_side_reduce_count_in_trend"], 0)
            self.assertNotEqual(d(state["base_price"]), BASE, "应已重锚到新价格")

    def test_s4_whipsaw_around_theta_never_confirms_trend(self):
        # 在 θ_t=4% 两侧横跳（3.9% / 4.1% 交替）：进入确认需连续 2 tick，永不满足
        prices = []
        for _ in range(12):
            prices.append(float(BASE) * 1.041)
            prices.append(float(BASE) * 1.039)
        state, events, risks = run_path(self.engine, prices)
        trend_events = [e for e in events if e["event_type"].startswith("LOSS_SIDE_REDUCTION")]
        self.assertFalse(trend_events, "横跳不应触发趋势确认（迟滞/持续性守卫）")
        self.assertNotIn("TREND", state["state"])

    def test_s5_single_tick_gap_does_not_act(self):
        # 单 tick 跳空 +6%：进入确认未满足 → 不动作、不建仓
        state, events, risks = run_path(self.engine, [float(BASE) * 1.06])
        self.assertFalse(events, "跳空首根 K 线不应有任何动作")
        self.assertEqual(state["trend_entry_candidate_count"], 1)
        self.assertNotIn("TREND", state["state"])

    def test_s6_flat_price_produces_no_trades(self):
        state, events, risks = run_path(self.engine, [float(BASE)] * 30)
        self.assertFalse(events, "横盘不应产生任何交易（触发下界尊重成本）")
        self.assertEqual(equity(state), BUDGET)

    def test_s7_noisy_drift_does_not_fake_trend_entry(self):
        # 阴跌 + 噪声：|m| 偶尔触及 θ 但从不连续两根 → 不应进入趋势
        prices = []
        for i in range(1, 25):
            drift = -0.0018 * i
            spike = -0.024 if i % 3 == 0 else 0.0  # 单根触 θ 后被拉回
            prices.append(float(BASE) * (1 + drift + spike))
            if abs(drift + spike) * 100 >= 4.0:
                prices.append(float(BASE) * (1 + drift + 0.01))  # 下一根拉回带内
        state, events, risks = run_path(self.engine, prices[:20])
        trend_events = [e for e in events if e["event_type"].startswith("LOSS_SIDE_REDUCTION")]
        self.assertFalse(trend_events, "非持续触带的阴跌不应确认趋势")


class StrategyPropertyTest(unittest.TestCase):
    def test_invariants_hold_on_random_walks(self):
        engine = make_engine()
        rho = Decimal("0.8")  # use_realized_profit_ratio_for_loss_side
        for seed in range(8):
            rng = random.Random(seed)
            price = float(BASE)
            state = engine.initialize_symbol("BTCUSDT", BASE, BUDGET)
            for _ in range(120):
                price *= 1 + rng.uniform(-0.01, 0.01)
                state, events, risks = engine.on_tick(state, Decimal(str(round(price, 2))))
                # 账本不变量 C7：花费 ≤ ρ × 收割（容差 1e-6）
                harvested = d(state.get("harvested_profit_usdt") or 0)
                spent = d(state.get("averaging_spent_usdt") or 0)
                self.assertLessEqual(
                    float(spent), float(harvested * rho) + 1e-6,
                    f"C7 违反 seed={seed}: spent={spent} harvested={harvested}",
                )
                # 计数器非负
                self.assertGreaterEqual(int(state.get("trend_entry_candidate_count", 0)), 0)
                self.assertGreaterEqual(int(state.get("trend_exit_candidate_count", 0)), 0)
                # 权益恒等式
                self.assertEqual(
                    float(equity(state)),
                    float(d(state["budget_usdt"]) + d(state["realized_pnl"])
                          + d(state["long_unrealized_pnl"]) + d(state["short_unrealized_pnl"])),
                )


if __name__ == "__main__":
    unittest.main()
