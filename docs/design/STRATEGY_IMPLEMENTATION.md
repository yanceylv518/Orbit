# Dynamic Dual Grid 策略内核实现方案

> 把 `design/STRATEGY_LOGIC.md` 的数学模型落成代码的具体实现策略。
> 定位：工程实施蓝图（模块、数据结构、算法、阶段、测试）；不含最优参数值（参数由 Phase B 标定产出）。
> 上游：STRATEGY_LOGIC（策略规格）、ARCHITECTURE §4.2/§4.3（工程落点）。

最后更新：2026-07-08

---

## 0. 实现原则

1. **内核纯函数化**：`on_tick(state, price, features, cfg) → (state', actions, events)`，无 I/O、无全局、无系统时钟。仿真、plan_only、paper、live 共用同一内核，只换外壳。
2. **测试先行**：先写 LOGIC §9 的七场景仿真测试（全红），再实现到全绿。测试即验收规格。
3. **表驱动 FSM**：迁移表是数据不是 if 链——每条迁移显式声明触发、动作、**复位清单**。现状"计数器永不清零"的 bug 正是 if 链隐式复位造成的。
4. **双跑切换**：接入期新旧 planning 并行输出 diff 报告；配置开关切换，一键回滚。
5. **标定与运行同口径**：π̂ 估计 / 几何扫描离线重演用的就是这个内核，不另写一套回测逻辑。

---

## 1. 模块划分

按 ARCHITECTURE §5 的目标结构落在 `src/orbit/domain/strategy/`（作为架构采用顺序第 1–2 步的实际落地；迁移完成前与现有 `src/ddg/` 并存，互不依赖）：

```
src/orbit/domain/strategy/
├─ types.py         # 值对象：Price/Qty/Notional(Decimal)、Action、TickResult、事件 VO
├─ config.py        # KernelConfig dataclass（§8 参数映射 + C1–C9 校验器）
├─ features.py      # MarketFeatures：EWMA σ̂、窗口自相关、方差比 VR、斜率 t-stat（O(1) 增量更新）
├─ regime.py        # RegimeClassifier：range / trend / unknown + 持续性去抖 + 迟滞
├─ state.py         # SymbolState：FSM 相位、锚点、极值、档位、计数器、自融资账本
├─ policy.py        # delta_star(m, phase, regime, cfg) → 目标净敞口（LOGIC §3 + §10.2 gate）
├─ transitions.py   # TRANSITION_TABLE + step()：LOGIC §4 迁移表的表驱动实现
├─ guards.py        # 不变量链（LOGIC §7）：每个 guard 返回 allow / block(reason) / clip
├─ fills.py         # 成交模型：taker/maker 费率、滑点（paper 与仿真共用；plan_only 只估成本）
├─ kernel.py        # StrategyKernel.on_tick() 编排（唯一入口，≈50 行）
└─ __init__.py
tools/calibration/
├─ klines.py        # Binance 公共 K 线拉取（无需密钥）
├─ pi_estimator.py  # π̂ 统计 + Wilson 置信区间（C8 准入报告）
└─ geometry_scan.py # (a,θ)×regime-gate 网格扫描 → E、频率、maxDD、whipsaw 计数表
tests/unit/strategy/
├─ paths.py         # 合成路径生成器：sine/ramp/vshape/whipsaw/gap/flat/drift
├─ test_scenarios.py    # S1–S7（LOGIC §9）
├─ test_invariants.py   # C5/C6/C7 账本、吸收态、重锚清零、Δ 方向一致性
└─ test_features.py, test_regime.py, test_transitions.py, test_guards.py
```

依赖方向：`kernel → {policy, transitions, guards} → {state, features, regime, types, config}`。全包 zero 外部依赖（标准库 + Decimal）。

---

## 2. 核心数据结构

```python
class Phase(Enum):
    BALANCED, SKEWED_LONG, SKEWED_SHORT, TREND_UP, TREND_DOWN, REANCHORING, PAUSED, STOPPED

@dataclass(frozen=True)
class Ledger:                      # 自融资账本（C7）
    harvested: Decimal             # 累计已实现收割利润（平偏斜的净实现）
    spent_on_averaging: Decimal    # 累计加亏损腿名义
    # 不变量: spent ≤ ρ_f × harvested，guard 层强制

@dataclass(frozen=True)
class SymbolState:
    symbol: str
    phase: Phase
    anchor_price: Decimal          # P_b，仅在 REANCHORING 完成时改写
    anchor_tick: int
    hi_since_anchor: Decimal
    lo_since_anchor: Decimal
    trend_extreme: Decimal | None  # TREND 相位内极值
    long_qty: Decimal
    short_qty: Decimal             # Δ = long_qty − short_qty（派生，不落存储）
    skew_rungs: int                # 当前逆势档位 ∈ [0, N]
    counters: Counters             # transfers/reduces/recoveries —— 作用域=两次重锚之间
    ledger: Ledger
    rebuild_batch: int             # REANCHORING 进度（0..k）
    cooldowns: Cooldowns           # 各事件最近触发 tick
    last_update_tick: int

@dataclass(frozen=True)
class Action:
    kind: Literal["ADD_LONG","ADD_SHORT","REDUCE_LONG","REDUCE_SHORT","CLOSE_ALL"]
    qty: Decimal
    reason: str                    # 具名迁移，即审计事件名
    est_cost: Decimal              # 按 fills.py 估计（C2 两程口径）
```

State 一律 **frozen dataclass，演进即替换**（`state' = replace(state, ...)`）——消除现状 `deepcopy` + 就地改字典的写法，天然可快照、可重放。

---

## 3. 内核算法（on_tick 编排）

```python
def on_tick(state, price, features, cfg, tick) -> TickResult:
    # 1. 观测更新（纯计算）
    m = price / state.anchor_price - 1
    state = track_extremes(state, price)

    # 2. 市况判定（含迟滞与去抖）
    regime = classify(features, cfg)                    # range | trend | unknown

    # 3. FSM 迁移（表驱动；含重锚与复位）
    state, transition_events = step(state, m, regime, price, cfg, tick)

    # 4. 目标净敞口
    target = delta_star(m, state.phase, regime, cfg)    # LOGIC §3；unknown ⇒ 不开新偏斜

    # 5. 生成动作：把 Δ 推向 target（分档步进、冷却、REANCHORING 分批）
    raw = plan_delta_move(state, target, price, cfg, tick)

    # 6. 守卫链（LOGIC §7）：逐条 allow / block / clip
    actions, guard_events = run_guards(raw, state, price, cfg)

    # 7. 应用动作：更新仓位、账本、计数器、冷却
    state = apply_actions(state, actions, price, cfg, tick)

    return TickResult(state, actions, transition_events + guard_events)
```

要点：
- **第 3 步先于第 5 步**：迁移（如趋势确认的"先平偏斜止损"）本身产生动作，由迁移表声明，不散落在规则函数里。
- **guard 在动作序列化之后、应用之前**：这就是"风控前置阻断"的准确位置（修 §21.3）。
- plan_only 模式 = 跑完 1–6 步、**跳过第 7 步**，把 actions 输出为 ExecutionPlan——规划与执行天然同一逻辑。

### 迁移表形态（transitions.py）

```python
TRANSITION_TABLE: list[Transition] = [
    Transition(
        from_phases={Phase.TREND_UP, Phase.TREND_DOWN},
        guard=trend_ended,                       # 回撤≥p_t 且 |m|<θ_out 持续 T_e
        to=Phase.REANCHORING,
        emit="TREND_END",
        actions=freeze_all,
        resets=(),                               # 复位延迟到重锚完成
    ),
    Transition(
        from_phases={Phase.REANCHORING},
        guard=rebuild_complete,
        to=Phase.BALANCED,
        emit="REANCHORED",
        actions=(),
        resets=("hi_lo_since_anchor", "counters", "skew_rungs", "trend_extreme"),  # §21.1 的修复点，显式声明
    ),
    ...
]
```

---

## 4. 各模块实现要点

| 模块 | 要点 |
|---|---|
| features | 环形缓冲 + EWMA，全部 O(1) 增量；σ̂_H = σ̂·√H；窗口不足时输出 `insufficient`，regime 判 unknown |
| regime | 三态 + 持续计数去抖；`unknown` 是安全默认（只管旧仓，不开新仓）；gate 统计量从自相关起步（最易实现验证），VR/Hurst 作为 Phase B 对比项 |
| policy | 纯查表式分段函数，≤30 行；§10.2 gate 即 regime 参数的一个分支 |
| guards | 顺序链，短路 block；`ONLY_REDUCE` 语义实现为谓词 `reduces_abs_delta(a) or reduces_gross(a)`；STOPPED 吸收态在链首 |
| fills | 双成本模型：taker（现行）与 maker+超时转 taker（§10.4），配置切换；C2 的两程成本估计在此单点实现 |
| config | 载入时跑 C1–C9 校验器，**违反一致性约束的配置直接拒绝启动**——参数纪律代码化 |

---

## 5. 与现有代码的映射

| 现有 | 去向 |
|---|---|
| `engine.py` `try_profit_transfer / try_position_recovery / try_loss_side_reduction` | 删除——语义被 policy（Δ*）+ transitions（迁移表）吸收 |
| `engine.py` `apply_trade / fill_price / mark_to_market` | 成本与成交部分收敛进 `fills.py`；mark-to-market 成为 state 的派生计算 |
| `engine.py` `resolve_state` | 删除——相位由 FSM 唯一维护，不再从价格反推 |
| `planning.py` 整个规则复制 | 变薄 adapter：真实持仓快照 → `SymbolState` → `on_tick(plan_only)` → actions → ExecutionPlan DTO（消除双写） |
| `app_state.py` 中 symbol_states dict | 序列化 `SymbolState`（版本号字段 `kernel_version` 进 ExecutionPlan 审计） |
| config 事件参数 | 按 LOGIC §8 映射表转 `KernelConfig`，未接线旋钮在此消灭 |

---

## 6. 分阶段实施

### Phase A — 内核 + 仿真测试（纯新增，不碰现网）
1. `tests/unit/strategy/paths.py` 路径生成器 + S1–S7 测试（先行，全红）。
2. types / config(+校验器) / state → features / regime → policy / transitions / guards / fills → kernel。
3. 性质测试：任意随机路径下 C5/C6/C7、吸收态、重锚清零恒成立。

**验收：S1–S7 全绿 + 性质测试通过。** 规模预估：内核 ~1200 行 + 测试 ~800 行。

### Phase B — 标定（离线工具）
1. `klines.py`：Binance `/fapi/v1/klines` 公共接口（无密钥），本地缓存。
2. `pi_estimator.py`：用内核 FSM 离线重演历史，统计 a-偏离中"回归 vs 触 θ"比例，Wilson 区间；输出 per-symbol C8 准入报告。
3. `geometry_scan.py`：(k₁,k₂) × gate on/off 网格 → E、频率、maxDD、whipsaw 计数热图；产出**出厂参数**。

**验收：≥1 个 symbol 的 π̂ 显著过 C8 门槛，且几何扫描给出非平凡最优区。**（若全军覆没——这是有价值的负结果，止损于此，不进 Phase C。）

### Phase C — plan_only 接入（双跑）
1. planning adapter + 配置开关 `planner: legacy | kernel | both`。
2. `both` 模式输出新旧 diff 报告（结构化，进管理员风控中心展示）。
3. UI 执行计划补 `phase / regime / Δ / Δ* / 触发迁移` 字段。

**验收：双跑 diff 可解释收敛，人工评审通过后切 `kernel`，legacy 保留一个版本周期。**

### Phase D — paper → live（另立验收文档）
paper：`fills.py` 模拟撮合 + 虚拟账本；live：动作经 ARCHITECTURE §4.3 guard 链 + ExchangeGateway 下单，maker 执行策略（限价 + 超时转市价）。**live 的前置条件：paper 连续运行期 + 全部 P0 工程项（ARCHITECTURE §12）完成。**

---

## 7. 测试规格摘录

场景测试形态（S3 为例——现状锁死 bug 的回归测试）：

```python
def test_s3_v_shape_full_lifecycle():
    cfg = default_test_config()
    path = ramp(to=cfg.theta_t * 1.2, ticks=200) + reverse_to_anchor(ticks=200)
    result = run_path(kernel, path, cfg)
    assert result.phases_visited >= [BALANCED, TREND_UP, REANCHORING, BALANCED]  # 不锁死
    assert result.final.counters == Counters.zero()                             # 重锚清零
    assert abs(result.final.delta) < cfg.delta_epsilon                          # 回到平衡
    assert result.total_pnl > -cfg.budget * (cfg.beta + cfg.gamma)              # 损失 ≤ C5+C6 预算
```

性质测试（随机游走路径 × 1000 seed）：
- `ledger.spent ≤ ρ_f · ledger.harvested`（C7）
- `gross ≤ budget × max_gross_ratio` 恒成立
- 进入 STOPPED 后无任何非平仓动作（吸收性）
- 每次 REANCHORED 事件后 counters/skew_rungs 为零
- 每个 Action 的方向与其所属迁移的 Δ 语义一致（LOGIC §1 表）

---

## 8. 风险与回滚

| 风险 | 对策 |
|---|---|
| 新内核与旧逻辑结论不一致 | Phase C 双跑 diff，人工评审；不一致默认按新内核为准记录、按旧输出执行，直至评审切换 |
| 标定结果否定策略（π̂ 不过线） | Phase B 是显式止损门，负结果照样交付报告 |
| 参数配置违反 C1–C9 | config 校验器拒绝启动，错误信息指向具体约束 |
| 内核演进破坏历史计划可解释性 | `kernel_version` 写入每份 ExecutionPlan 与审计日志 |
| 回滚 | 配置开关切回 `legacy`，无数据迁移（SymbolState 新旧命名空间隔离） |
