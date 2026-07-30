# Orbit 策略中心产品与技术设计

状态：**设计提案，待评审，尚未实现**

版本：V1

日期：2026-07-30

目标页面：`#strategy`

首个接入策略：`TB4_TREND_BASKET_V1`

---

## 0. 决策摘要

Orbit 新增独立“策略中心”，作为正式策略的认知与证据入口。它回答四个问题：

1. 当前正式运行的策略是什么；
2. 策略为什么产生当前仓位；
3. 历史回测和样本外证据如何；
4. 策略现在处于研究、paper、受限实盘还是停止状态。

策略中心与现有页面边界如下：

| 页面 | 负责 | 不负责 |
|---|---|---|
| 策略中心 | 已准入策略的定义、冻结参数、证据和运行摘要 | 调参、下单、创建实验 |
| 研究平台 | 未准入候选、数据集、预注册、锁箱与 verdict | 生产策略配置、实盘控制 |
| 前向实盘 | 冻结目标、自动执行、成交、滑点和持仓核对 | 解释完整研究历史 |
| 风控中心 | 拦截、协议停机、急停和审计 | 修改策略定义 |
| 执行计划 / 币种视图 | 旧双网格运营与生命周期观察 | TB4 指令与信号解释 |

本设计正式取代 `ARCHITECTURE.md` 与 `UI_PAGES.md` 中“策略不设置独立页面”的旧决策。旧页面被删除是因为它只是静态卡片；新页面必须由后端冻结定义、结构化证据和运行账本驱动，不恢复旧实现。

---

## 1. 目标与非目标

### 1.1 目标

- 用户进入页面后 30 秒内能说清当前策略、交易对象、信号、仓位、成本和风险上限。
- 所有展示参数来自后端唯一冻结源，不在 Vue 中复制 `TB4_SPEC`。
- 回测结果可追溯到结构化报告、数据指纹、代码版本和证据哈希。
- 明确区分历史回测、walk-forward、paper 前向和真实实盘，禁止混成一条“收益”。
- 当前信号能解释“为什么 LONG / SHORT / FLAT”，且与实际下单使用同一实现。
- 页面只读；任何启用、急停和交易动作仍在相应运营页面执行。

### 1.2 非目标

- 不在策略中心自由编辑参数。
- 不提供任意 Python、SQL 或命令执行入口。
- 不从策略中心直接下单或修改账户。
- 不将 PASS 表述为收益保证。
- 不把旧双网格状态、TB4 趋势信号和研究候选混为同一策略。
- V1 不建立多策略组合调度器；但数据模型必须允许以后增加第二个正式策略。

---

## 2. 用户与使用场景

### 2.1 管理员

- 查看完整策略定义、证据、当前信号和全局运行状态。
- 跳转前向实盘、风控中心和研究平台。
- 查看部署代码版本、证据哈希和异常状态。

### 2.2 业务用户

- 只查看与自己账户关联的策略状态、目标与实盘对照。
- 不读取其他账户 ID、资金、订单或执行报告。
- 不看到管理员运维动作和全局部署细节。

### 2.3 匿名用户

- 不返回策略定义、信号、证据和账户状态。

---

## 3. 信息架构

导航调整为：

```text
运营
├── 工作台
└── 用户与账户

策略
├── 策略中心
├── 研究平台
└── 前向实盘

旧网格运营
├── 执行计划
└── 币种视图

治理
├── 风控中心
└── 报表
```

路由：

- `#strategy`：策略中心；
- `#research`：研究平台；
- `#forward`：前向实盘；
- 删除 `strategy → dashboard` 的旧路由别名；
- 旧书签 `#plans`、`#symbol` 保持可用。

---

## 4. 页面结构

### 4.1 策略页头

展示：

- 策略名称、策略 ID、版本；
- 冻结定义哈希；
- 证据等级；
- 生命周期状态；
- 运行模式；
- 部署 commit；
- 最近一次有效再平衡和下一次预计再平衡；
- “查看前向实盘”“查看风控”“查看研究来源”三个只读跳转。

状态枚举：

```text
RESEARCH_ONLY
BACKTEST_CONFIRMED
PAPER_FORWARD
LIVE_PILOT
PROTOCOL_STOPPED
RETIRED
```

状态由后端根据冻结登记和运行账本计算，前端不得自行推断。

### 4.2 策略如何工作

用两层内容展示：

1. 普通语言摘要；
2. 可审计的冻结规则表。

TB4 V1 必须展示：

| 分类 | 字段 |
|---|---|
| 市场 | 12 个冻结 USDT 永续市场 |
| 数据 | 4h 已收盘 K 线、Funding |
| 信号 | 14/28/56/84/168 日动量符号等权集成 |
| 仓位 | vol28 逆波动率定仓 |
| 风险 | 目标年化波动 10%，gross cap 1.0 |
| 调仓 | 每 7 天，下一根 K 线执行 |
| 成本 | 往返 0.14% + 实际 Funding |
| 停机 | paper 或 live 回撤达到 30% |

参数值必须由 `TB4_SPEC` 序列化生成。解释性文案可由版本化策略元数据提供，但不得覆盖参数值。

### 4.3 当前信号解释

每个市场一行：

| 字段 | 含义 |
|---|---|
| symbol | 冻结市场 |
| close_time | 信号使用的最后一根已收盘 K 线 |
| close_price | 信号参考收盘价 |
| momentum_14d ... momentum_168d | 各周期收益及方向 |
| positive_votes / negative_votes | 多空周期票数 |
| ensemble_signal | 冻结综合信号 |
| volatility_28d | 定仓波动率 |
| raw_weight | 风险缩放前权重 |
| target_weight | gross cap 后冻结目标权重 |
| target_direction | LONG / SHORT / FLAT |
| target_quantity | LIVE-SMALL 资金对应目标数量 |
| actual_quantity | 真实账户数量（有权限时） |
| reconciliation_status | MATCH / DEVIATION / EXPECTED_FLAT / UNEXPECTED_POSITION |

信号解释不得由前端重算。`FrozenTrendBasketRunner` 应新增只读诊断投影，复用生产信号和定仓函数；禁止为页面另写一套近似公式。

### 4.4 回测与证据

分为四个独立证据标签：

1. 历史总览；
2. walk-forward 窗口；
3. 参数稳健性；
4. 成本与市场贡献。

历史总览指标：

- 测试时间区间；
- 初始/期末归一化权益；
- 累计、年化收益；
- 最大回撤；
- Calmar、Sortino；
- 最差滚动 12 个月收益；
- 正滚动 12 个月比例；
- 最长回撤时间；
- 换手和交易成本；
- Funding；
- 数据市场覆盖。

图表：

- 归一化权益；
- underwater 回撤；
- walk-forward 窗口收益；
- 逐市场收益或风险贡献；
- 成本分解；
- 参数邻域稳健性。

所有图表必须标注测试区间和证据等级。回测区固定显示：

> 历史结果不保证未来收益；当前证据等级为 BACKTEST_CONFIRMATION，并存在幸存者偏差与市场状态覆盖不足。

### 4.5 Paper 与实盘对照

展示三条互不替代的序列：

```text
历史回测权益
TB4 paper 前向权益
LIVE-SMALL 真实权益
```

实盘归因：

- 信号收盘价到下单时间的延迟成本；
- 实际成交滑点；
- 手续费；
- Funding；
- 数量取整和最低名义金额；
- 未成交/部分成交；
- 剩余不可归因偏差。

策略中心只展示摘要；点击进入前向实盘查看逐单账本。

### 4.6 已知风险

固定展示并允许后端版本化：

- 当前市场集合的历史幸存者偏差；
- OOS 区间可能偏向强趋势阶段；
- 500 USDT 不能完整表达所有 12 币目标；
- 固定 0.14% 成本不等于未来真实成本；
- 趋势策略在震荡市场可能持续亏损；
- paper 与 live 样本量仍有限；
- Binance 下线、规则和流动性会变化。

风险不能因策略处于 `LIVE_PILOT` 而隐藏。

---

## 5. 后端领域与应用设计

### 5.1 `StrategyDefinition`

不可变策略定义：

```json
{
  "strategy_id": "TB4_TREND_BASKET_V1",
  "name": "TB4 多周期趋势篮子",
  "version": "1",
  "implementation": "orbit.domain.strategy.trend_basket_runner",
  "spec": {},
  "definition_hash": "sha256",
  "supersedes": null
}
```

`spec` 从冻结对象导出。`definition_hash` 使用规范 JSON 计算。

### 5.2 `StrategyEvidenceBundle`

回测证据采用只追加、内容寻址的结构化文件：

```json
{
  "schema": "ORBIT_STRATEGY_EVIDENCE_V1",
  "strategy_id": "TB4_TREND_BASKET_V1",
  "definition_hash": "sha256",
  "evidence_level": "BACKTEST_CONFIRMATION",
  "generated_at": "UTC",
  "code_commit": "git sha",
  "datasets": [{"id": "...", "sha256": "..."}],
  "summary": {},
  "walk_forward_windows": [],
  "equity_curve": [],
  "drawdown_curve": [],
  "market_contributions": [],
  "cost_attribution": {},
  "robustness": {},
  "known_limitations": [],
  "bundle_hash": "sha256"
}
```

首个 bundle 应由现有 TB-R 结构化结果转换生成，转换器必须校验冻结参数和原报告哈希。不能从 Markdown 抓数字，也不能在前端硬编码历史指标。

部署时证据文件作为版本化只读资源随代码发布；本地 `var/calibration` 报告仍是原始研究产物，不作为生产页面唯一依赖。

### 5.3 `StrategyRuntimeProjection`

运行投影聚合：

- `trend_forward`；
- 冻结 runner 诊断；
- `live_execution`；
- `live_reconciliation`；
- paper/live equity ledger；
- 当前部署 commit。

查询服务只读，不写 runner、账本、账户或订单。

### 5.4 Repository 与服务

新增端口：

- `StrategyDefinitionRepository`
- `StrategyEvidenceRepository`
- `StrategyRuntimeReader`

新增应用服务：

- `StrategyCatalogService`：列出正式策略；
- `StrategyDetailQueryService`：定义 + 证据摘要；
- `StrategyRuntimeQueryService`：信号与运行投影；
- `StrategyComparisonService`：回测/paper/live 归一化对照。

文件实现可用于不可变定义和证据；账户相关运行态继续走现有 repository/ledger。不要把大型曲线塞进 `AppState` 内存主快照。

---

## 6. API 设计

所有接口只读并要求登录。

### 6.1 列表

```http
GET /api/strategies
```

返回策略身份、状态、证据等级和摘要，不返回大曲线。

### 6.2 定义与摘要

```http
GET /api/strategies/{strategy_id}
```

返回定义、冻结哈希、证据摘要、风险和运行摘要。

### 6.3 证据

```http
GET /api/strategies/{strategy_id}/evidence
GET /api/strategies/{strategy_id}/evidence/equity?cursor=...
GET /api/strategies/{strategy_id}/evidence/windows
GET /api/strategies/{strategy_id}/evidence/contributions
```

曲线分页或降采样；服务端保留原始点，前端不得通过删掉亏损区间改善图形。

### 6.4 当前运行

```http
GET /api/strategies/{strategy_id}/runtime
```

返回当前信号、目标权重、下一再平衡、paper/live摘要和可见账户核对。业务用户按账户过滤；管理员读取全量。

### 6.5 错误契约

- `404 STRATEGY_NOT_FOUND`
- `409 DEFINITION_EVIDENCE_MISMATCH`
- `409 EVIDENCE_INTEGRITY_ERROR`
- `503 RUNTIME_NOT_INITIALIZED`
- `403 ACCOUNT_NOT_VISIBLE`

证据哈希或定义哈希不一致时 fail closed：页面显示完整性错误，不展示可能失配的绩效数字。

---

## 7. 前端设计

新增：

- `pages/StrategyCenterPage.vue`
- `components/strategy/StrategyIdentity.vue`
- `components/strategy/StrategyMechanics.vue`
- `components/strategy/SignalTable.vue`
- `components/strategy/EvidenceSummary.vue`
- `components/strategy/WalkForwardTable.vue`
- `components/strategy/BacktestCharts.vue`
- `components/strategy/RuntimeComparison.vue`
- `components/strategy/KnownLimitations.vue`

前端状态使用独立 strategy store，按需读取证据和曲线，不扩大现有全量 `/api/state`。

页面首屏优先级：

```text
身份与状态
→ 普通语言原理
→ 冻结参数
→ 当前信号
→ 回测证据
→ paper/live 对照
→ 已知风险
```

移动端允许横向滚动信号表；桌面端冻结 symbol 列。所有百分比、年化和时间区间统一格式化。

---

## 8. 一致性与安全约束

1. 前端不保存任何策略参数副本。
2. 当前信号与订单必须来自同一冻结 runner/清单。
3. 证据 bundle 的 `definition_hash` 必须等于运行定义哈希。
4. 回测数据与 live 数据视觉上必须明确分区。
5. 页面无参数编辑、启用、下单和恢复按钮。
6. 页面不得返回 API 凭证、订单签名信息或其他账户数据。
7. 业务用户权限按账户过滤，不能依赖前端隐藏。
8. 证据文件损坏时不降级到 Markdown 或静态默认值。
9. 新策略接入必须提供定义、证据 bundle 和风险说明，不能只注册一个名称。
10. `TB4_SPEC`、TB4 账本和 LIVE-3 执行协议在本任务中保持不变。

---

## 9. 迁移与实施顺序

### SC-1：后端只读策略目录

- 定义 schema、repository 和 API；
- 从 `TB4_SPEC` 导出 `StrategyDefinition`；
- 生成并校验首个 TB4 evidence bundle；
- 增加权限与完整性测试。

### SC-2：策略中心首屏

- 导航、路由与页面骨架；
- 身份、原理、冻结参数、证据摘要和风险；
- 替换旧 `strategy → dashboard` 别名。

### SC-3：当前信号

- runner 增加只读诊断投影；
- 展示五周期动量、vol28、目标权重和方向；
- 与冻结执行清单做恒等测试。

### SC-4：证据图表

- 权益、回撤、walk-forward、贡献和成本图表；
- 分页/降采样；
- 指标与源报告逐项对齐测试。

### SC-5：paper/live 对照

- 聚合现有前向、执行、核对和权益账本；
- 管理员与业务用户权限测试；
- 前向实盘深链。

旧执行计划和币种视图暂不删除，只移动到“旧网格运营”分组。确认无用户依赖后再提出独立退役决策。

---

## 10. 验收标准

### 数据与一致性

- `StrategyDefinition.spec` 与 `TB4_SPEC` 字段逐项相等。
- 定义、证据或数据指纹被修改时接口拒绝展示证据。
- 页面显示的目标权重与同一时点 TB4 冻结清单逐市场相等。
- 回测摘要与原结构化报告逐项一致，允许误差为序列化精度范围内的零误差。
- 无任何指标从 Markdown 或 Vue 常量读取。

### 权限

- 匿名请求返回 401。
- 管理员可看完整策略和运行态。
- 业务用户只能看自己账户的实盘核对。
- 任何响应不包含 API Key、Secret 或凭证引用。

### 产品

- 首屏可识别当前正式策略、证据等级、运行模式和最近再平衡。
- 用户可以从普通语言解释追溯到冻结参数。
- 用户可以从目标方向追溯到五周期信号和定仓数据。
- 回测、paper 和 live 不使用同一含混指标或曲线名称。
- 已知风险始终可见。
- “查看前向实盘”“查看研究来源”“查看风控”跳转正确。

### 工程

- 默认配置不改变现有交易行为。
- 不修改 `TB4_SPEC`、TB4账本或LIVE-3自动执行协议。
- 后端单元/API权限/完整性测试全绿。
- 前端检查、生产构建和浏览器桌面/窄屏冒烟通过。
- `git diff --check` 通过。

---

## 11. 待补证据与上线阻断项

在策略中心可以被称为“完整证据入口”之前，必须补齐：

1. 可随代码发布的 TB4 结构化 evidence bundle；
2. TB-R 原报告到 bundle 的可复算转换与哈希校验；
3. 当前五周期信号的生产同源诊断接口；
4. 回测、paper、live 的统一时间和归一化定义；
5. 业务用户与管理员的账户级权限契约；
6. 500 USDT 下不可执行币种对组合偏差的结构化归因。

这些缺口不能用静态前端数字、手抄 Markdown 指标或简化信号公式代替。
