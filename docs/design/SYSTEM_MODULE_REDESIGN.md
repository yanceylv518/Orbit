# Orbit 系统模块重划分设计

状态：`ACCEPTED`（2026-08-11 用户确认 §17 五项决策,全部按 Claude 评审建议：① 一级导航七项「数据/研究/策略/实盘/复盘/风控/账户」,概览暂缓;② 执行首期为实盘二级页;③ M0/F1/G1/G2 归历史研究档案;④ 首个研究主题命名「量价关系」;⑤ MOD-1 为第一个实施任务,与 R-0 并行、互不阻塞。架构与迁移规划获批,不代表功能已实现）  
版本：`MODULAR-1`  
最后更新：2026-08-11

## 1. 文档目的与效力

本文定义 Orbit 从“以现有页面和单个策略为中心”迁移为“以业务能力和策略生命周期为中心”的目标模块边界。它回答：

1. 系统应划分为哪些业务模块；
2. 每个模块拥有哪些事实、允许依赖谁、禁止承担什么；
3. 历史研究数据与实盘行情如何统一标准但隔离运行；
4. 现有 TB4 如何在零行为变化的前提下迁入新结构；
5. 前端、API、应用服务和持久化应按什么顺序渐进迁移；
6. 每一阶段必须提供什么验收证据，失败时如何回退。

本文在模块边界、页面信息架构和迁移顺序上作为新的总纲。出现冲突时：

- `TB4_FORWARD.md`、`TB4_OPERATIONS.md`、`LIVE_SMALL.md` 继续定义 TB4 冻结运行与实盘纪律；
- `DATA1R_SHORTLINE_DATASET.md` 继续定义 DATA-1R 的数据内容和质量规则；
- `STRATEGY_CENTER.md` 继续定义策略中心的只读证据要求；
- `MULTI_ACCOUNT_SHORT_STRATEGY_ARCHITECTURE.md` 继续定义多账户短线执行目标；
- 本文只重新确定这些能力分别属于哪个模块、通过什么契约协作。

本设计不授权切换 TB4 数据源、不授权重置 TB4 前向、不授权扩大实盘范围，也不授权删除任何历史证据。

## 2. 当前问题

当前工程已经具备 API、Application、Domain、Infrastructure 的技术分层，但产品模块和业务事实仍存在交叉。

### 2.1 页面按“已有功能”拼装，而非按用户任务组织

当前“策略”页面同时包含：

- TB4 正式策略定义与证据；
- M0/F1/G1/G2 研究候选；
- DATA-1R 全市场数据下载；
- 单市场数据拉取；
- 数据任务与策略评估的混合历史；
- 研究结果解释。

用户无法从页面层级判断自己是在准备数据、研究理论、冻结策略，还是观察一个运行实例。

### 2.2 数据按历史用途形成多份缓存

现状同时存在：

- TB4/TB1 专用的 4h 与 Funding JSON；
- M0/F1/G1/G2 使用的校准 JSON；
- DATA-1R 的全市场 15m、Funding、1h/4h 派生分区；
- TB4 实时前向的近期预热数据和只追加账本。

其中前三类都是研究数据，却没有统一的数据版本、质量查询和访问契约。页面把 K 线行数、Funding 事件数和 manifest 归档条目相加，形成没有统一单位的“总记录数”。

### 2.3 策略定义、运行实例和执行账户概念混合

TB4 是冻结的 `StrategyDefinition`；TB4 Paper 和 LIVE-SMALL 是不同的运行/执行实例；3 倍目标是 Live 投影政策，不是新的研究策略。现有页面和部分状态投影没有稳定表达这些区别。

### 2.4 长任务共用一个研究运行概念

数据索引、数据下载、数据构建和候选评估共用研究运行列表。程序成功、研究通过、数据完整和任务可恢复是不同维度，却容易被一个状态标签混为一谈。

### 2.5 组合根仍然过重

`application/app_state.py`、`bootstrap.py` 和前端 `appStore.js` 承担了大量跨模块装配和状态聚合。装配根可以知道所有模块，但业务用例不能通过装配根相互调用，也不能把装配根继续扩展成事实所有者。

## 3. 架构决策

Orbit 划分为八个业务模块：

```text
数据 Data
  -> 研究 Research
      -> 策略 Strategy
          -> 运行 Runtime
              -> 执行 Execution
                  -> 复盘 Review

风险 Risk ---------> 运行 / 执行
账户 Accounts -----> 运行 / 执行
```

箭头表示主要业务产物的流向，不表示模块可以直接读取对方数据库。跨模块协作必须通过应用端口、版本化 DTO 或不可变事件完成。

八个模块分别回答：

| 模块 | 核心问题 | 主要产物 |
|---|---|---|
| 数据 | 市场事实是什么，质量是否足够？ | 数据版本、市场事件、质量报告 |
| 研究 | 某种关系是否存在且可重复？ | 假设、实验、统计证据、研究结论 |
| 策略 | 证据如何冻结成完整交易规则？ | 策略定义、证据包、准入状态 |
| 运行 | 某个策略实例现在处于什么状态？ | 实例状态、信号决策、目标仓位、运行账本 |
| 执行 | 目标仓位如何变成真实订单和持仓？ | 调仓意图、订单、成交、对账结果 |
| 风险 | 哪些动作必须被限制或停止？ | 风险判定、停止状态、恢复授权 |
| 复盘 | 理论、计划和真实结果为何不同？ | 归因、权益对照、审计报告 |
| 账户 | 谁可以操作哪个交易账户？ | 用户、账户、凭证引用、权限与绑定 |

## 4. 全局设计原则

### 4.1 数据不属于策略

数据是平台公共事实。禁止新增 `某策略_某周期_数据.json` 作为长期目标模型。策略只能声明数据需求并绑定一个不可变数据版本。

### 4.2 统一标准不等于共享运行依赖

历史研究仓与实盘行情流使用相同字段、时间边界和缺失规则，但必须物理和故障隔离。DATA-1R 下载、重建或损坏不得阻断 TB4 Paper/Live。

### 4.3 研究、策略和运行是三个不同阶段

- 研究假设可以失败、修改后另建版本；
- 策略定义必须绑定证据并冻结；
- 运行实例只能执行冻结策略，不负责调参或重新研究。

### 4.4 一个事实只有一个所有者

例如订单终态由执行模块拥有，风险模块只能引用订单并产生判定；策略模块不能复制一份“当前订单状态”作为自己的事实源。

### 4.5 只追加证据不可覆盖

数据版本、预注册实验、研究结果、策略定义、运行账本、订单与审计记录都必须通过新版本或新记录演进。前端隐藏记录不等于删除事实。

### 4.6 副作用显式隔离

只有执行模块可以发送订单；只有账户模块的凭证端口可以解密凭证；只有数据适配器可以访问公共市场数据源。研究和策略领域代码不得访问 Binance、数据库或凭证。

### 4.7 TB4 零影响优先

任何重构若不能证明 TB4 输入、决策、目标权重、账本和实盘清单 zero-diff，就不能切换 TB4 的读取或写入路径。

## 5. 模块详细边界

### 5.1 数据模块 Data

职责：

- 接入 Binance 公共历史归档和实时公共行情；
- 规范化 Candle、Funding、合约生命周期和交易规则；
- 从完整 15m 子根确定性聚合 1h/4h；
- 检测缺根、重复、乱序、时间漂移和 checksum 变化；
- 生成不可变 `DatasetVersion` 与 `DataQualityReport`；
- 向研究提供点时一致历史查询；
- 向运行提供有限滚动窗口和连续 market cursor。

拥有的事实：

- `Candle`
- `FundingEvent`
- `ContractLifecycle`
- `ExchangeRuleVersion`
- `DatasetVersion`
- `DataPartition`
- `DataQualityReport`
- `MarketCursor`

内部必须分成两个故障域：

```text
HistoricalResearchStore
  DATA-1R、长历史、全市场、批处理、版本冻结

LiveMarketWindow
  当前标的、有限预热、增量行情、低延迟、连续性监控
```

二者共享 `MarketDataSchema`，不共享“必须同时可用”的运行条件。

禁止：

- 不定义策略信号；
- 不决定币种是否应交易；
- 不保存账户余额和持仓；
- 不因研究仓故障停止实盘；
- 不把不完整聚合根伪装成正常 OHLCV。

### 5.2 研究模块 Research

职责：

- 管理研究主题，例如“量价关系”；
- 定义可证伪的 `ResearchHypothesis`；
- 定义价格、成交量、波动率、流动性等 `FeatureDefinition`；
- 预注册样本范围、成本、统计方法和及格线；
- 绑定 `DatasetSnapshot`，运行描述性统计和假设检验；
- 保存成功、失败和证据不足的全部实验；
- 输出研究结论，但不直接产生可执行订单。

拥有的事实：

- `ResearchTopic`
- `ResearchHypothesis`
- `FeatureDefinition`
- `ExperimentDefinition`
- `DatasetSnapshot`
- `ExperimentRun`
- `ResearchResult`
- `ResearchVerdict`

建议 verdict 固定为：

- `SUPPORTED`：达到预注册证据门；
- `NOT_SUPPORTED`：正常完成但未达到门槛；
- `INCONCLUSIVE`：样本或统计能力不足；
- `INVALID`：数据或方法违反实验定义。

运行状态必须独立为：`QUEUED/RUNNING/SUCCEEDED/FAILED/CANCELLED`。`SUCCEEDED` 只表示程序完成，不代表研究成立。

禁止：

- 不管理 Paper/Live 生命周期；
- 不把探索阶段最佳参数直接升级为正式策略；
- 不覆盖失败实验；
- 不使用数据截止时间之后才可知的信息。

### 5.3 策略模块 Strategy

职责：

- 把得到支持的研究证据组合为完整可交易定义；
- 冻结信号、退出、仓位、再平衡、成本和所需数据 schema；
- 绑定结构化证据包和不可变 hash；
- 管理从候选到历史确认、Paper准入、Live试点的状态；
- 提供只读策略目录和定义查询。

拥有的事实：

- `StrategyDefinition`
- `StrategyEvidenceBundle`
- `AdmissionDecision`
- `StrategyVersion`

建议准入状态：

```text
DRAFT
-> RESEARCH_SUPPORTED
-> BACKTEST_CONFIRMED
-> PAPER_APPROVED
-> LIVE_PILOT_APPROVED
-> RETIRED
```

每次晋级必须新增 `AdmissionDecision`，不能直接修改历史 verdict。

禁止：

- 不持有当前账户仓位；
- 不直接发送订单；
- 不在正式定义页面调参；
- 不把 Paper/Live 倍数投影伪装成新的策略研究结论。

### 5.4 运行模块 Runtime

职责：

- 创建和管理 `StrategyInstance`；
- 从 LiveMarketWindow 获取所需预热和增量事件；
- 运行与 replay 对齐的冻结决策内核；
- 保存 runner 状态、market cursor、信号和目标仓位；
- 管理 Warmup、Running、Degraded、Stopped 和恢复；
- 区分 Paper 与 Live 实例。

拥有的事实：

- `StrategyInstance`
- `RunnerLease`
- `RunnerCheckpoint`
- `SignalDecision`
- `TargetPortfolio`
- `PaperLedger`

禁止：

- 不下载全市场历史研究数据；
- 不修改策略定义；
- 不发送真实订单；
- 不把实时运行结果写回研究结论。

### 5.5 执行模块 Execution

职责：

- 将 Live 实例的 `TargetPortfolio` 转为调仓差额；
- 应用交易规则、数量舍入和执行政策；
- 创建幂等订单意图并发送交易所订单；
- 跟踪确认、部分成交、未知结果、撤单和拒单；
- 消费账户私有事件并执行周期对账；
- 记录手续费、成交均价和滑点。

拥有的事实：

- `ExecutionPlan`
- `OrderIntent`
- `ExchangeOrder`
- `Fill`
- `PositionObservation`
- `ReconciliationRun`

禁止：

- 不重新计算策略信号；
- 不更改目标仓位来“优化成交”；
- 不绕过风险判定；
- 不把下单超时直接当作订单失败并重下。

### 5.6 风险模块 Risk

职责：

- 管理版本化账户和组合风险政策；
- 在新增风险前同步判定；
- 监控回撤、敞口、杠杆、持仓数量、数据新鲜度和未知仓位；
- 产生 `ALLOW/BLOCK/REDUCE_ONLY/EMERGENCY_STOP`；
- 管理停止原因和经授权的恢复流程。

拥有的事实：

- `RiskPolicy`
- `RiskDecision`
- `RiskIncident`
- `StopState`
- `RecoveryAuthorization`

TB4 legacy 使用冻结兼容政策；新短线实例使用最多三仓等新政策。禁止把新策略政策反向套用到 TB4。

### 5.7 复盘模块 Review

职责：

- 对比研究预期、Paper目标、Live目标、订单和真实持仓；
- 归因价格收益、Funding、手续费、滑点、取整和漏单；
- 展示权益、回撤、执行偏差和风险事件；
- 生成只读报告和审计视图。

拥有的事实：

- `ReviewSnapshot`
- `PerformanceAttribution`
- `ExecutionDeviation`
- `AuditReport`

复盘模块消费其他模块已经落地的事实，不允许反向修改订单、账本或策略。

### 5.8 账户模块 Accounts

职责：

- 管理管理员、业务用户、角色和可见范围；
- 管理交易账户、账户模式和状态；
- 保存凭证引用与指纹，封装 vault；
- 管理账户与策略实例绑定；
- 提供账户快照同步与连接健康状态。

拥有的事实：

- `Operator`
- `BusinessUser`
- `ExchangeAccount`
- `CredentialReference`
- `AccountStrategyBinding`
- `AccountSnapshot`

禁止：

- 不保存策略参数；
- 不计算策略信号；
- 不向前端或日志暴露 Secret；
- 不允许一个账户同时存在冲突的活跃绑定。

## 6. 数据统一设计

### 6.1 统一的是语义和访问契约

研究与实盘共享以下定义：

```text
Candle
- symbol
- interval
- open_time_ms / close_time_ms
- open / high / low / close
- base_volume / quote_volume / trade_count
- completeness
- source
- payload_hash

FundingEvent
- symbol
- funding_time_ms
- funding_rate
- source
- payload_hash

ContractLifecycle
- symbol
- listed_at / delisted_at
- status
- status_source
```

时间戳统一使用 UTC 毫秒；K 线只能在 close 后可见；聚合必须按 UTC 固定边界；缺少任一子根时输出 `INCOMPLETE` 且禁止进入正式 replay 或 Live 信号。

### 6.2 历史研究访问契约

研究只能通过不可变快照读取：

```text
HistoricalMarketDataPort.open_snapshot(dataset_version_id)
HistoricalMarketDataPort.candles(snapshot, symbols, interval, range)
HistoricalMarketDataPort.funding(snapshot, symbols, range)
HistoricalMarketDataPort.contracts(snapshot)
HistoricalMarketDataPort.quality(snapshot)
```

`DatasetSnapshot` 至少冻结：

- dataset version ID 与 fingerprint；
- source cutoff；
- symbol 选择规则及结果；
- interval 与字段 schema 版本；
- 分区 hash；
-质量报告 hash；
- 已知交易所停机窗口。

### 6.3 实盘访问契约

运行只能通过实时端口读取：

```text
LiveMarketDataPort.warmup(requirement)
LiveMarketDataPort.subscribe(streams, after_cursor)
LiveMarketDataPort.latest_exchange_rules(symbols)
LiveMarketDataPort.health(streams)
```

实盘预热只加载策略所需窗口。例如 TB4 最长168天动量、4h周期，需要至少1008根完整4h K线及安全余量；不读取829个合约的全历史。

### 6.4 TB4旧研究数据迁移

TB4已有研究证据继续绑定原始文件指纹。DATA-1R不能静默替换它。后续可新增等价性证据：

1. 从 DATA-1R 固定快照选择 TB4 的12个市场；
2. 对齐原TB4历史区间；
3. 比较每根4h OHLC、Funding时点和值；
4. 使用同一冻结 runner 比较每个信号、目标权重、净收益和再平衡；
5. 生成不可变 `DatasetEquivalenceReport`；
6. 只有逐字段及运行输出达到冻结要求，才可登记为等价数据来源。

这份等价报告只增加证据，不改变旧报告 hash，也不自动切换 TB4 前向数据源。

## 7. 模块依赖与通信

### 7.1 允许的领域依赖

```text
Research -> Data ports
Strategy -> Research evidence DTO
Runtime  -> Strategy definition DTO + Live Data ports
Execution -> Runtime target DTO + Accounts ports + Risk ports
Risk -> Accounts/Execution只读快照
Review -> 各模块只读投影或不可变事件
```

模块之间禁止：

- 直接读取对方持久化表或文件目录；
- 引用对方基础设施实现；
- 通过前端 store 反向形成业务耦合；
- 同一事实跨模块双写且没有校验；
- 通过通用 `dict` 长期传递未版本化核心事实。

### 7.2 同步命令与异步事件

同步调用只用于需要立即判定的流程，例如执行前风险检查。长任务和事实传播使用不可变事件：

- `DatasetVersionPublished`
- `ExperimentCompleted`
- `StrategyAdmissionGranted`
- `TargetPortfolioPublished`
- `RiskIncidentRaised`
- `OrderStateChanged`
- `ReconciliationCompleted`

事件至少包含稳定 ID、schema version、发生时间、因果 ID、主体 ID 和 payload hash。

### 7.3 任务中心与业务结果分离

建立平台级 `Job` 投影，只表达计算过程：

```text
job_type: DATA_INDEX / DATA_SYNC / DATA_BUILD / DATA_VERIFY /
          EXPERIMENT_RUN / REPLAY / REPORT_BUILD
status: QUEUED / RUNNING / SUCCEEDED / FAILED / CANCELLED
progress: phase + completed + total + unit
result_ref: 可选的业务结果引用
```

数据完整性由 `DatasetVersion.state` 表达，研究成立与否由 `ResearchVerdict` 表达，策略准入由 `AdmissionDecision` 表达。禁止再用一个“评估完成/失败”标签代替三者。

## 8. API边界

目标 API 按业务模块分组：

```text
/api/data/*
/api/research/*
/api/strategies/*
/api/runtime/*
/api/execution/*
/api/risk/*
/api/review/*
/api/accounts/*
/api/jobs/*
```

关键规则：

- `/api/data` 不返回策略结论；
- `/api/research` 只能引用数据版本，不能接受任意服务器路径；
- `/api/strategies` 的正式定义默认只读；
- `/api/runtime` 操作实例，不修改策略定义；
- `/api/execution` 的写操作必须带账户、实例、目标版本和幂等键；
- `/api/risk` 的恢复动作必须鉴权并写审计；
- `/api/review` 只读；
- `/api/jobs` 只控制可取消的长任务，不承载业务 verdict。

迁移期允许旧 API 通过适配器读取新应用服务，但新模块不得反向依赖旧 router 或 `AppState`。

## 9. 前端信息架构

目标一级导航：

```text
概览
数据
研究
策略
运行
执行
复盘
风控
账户
```

首轮可暂不增加“概览”，先将现有五项迁移为：

```text
数据 | 研究 | 策略 | 实盘 | 复盘 | 风控 | 账户
```

页面职责：

### 数据

- 数据版本与截止时间；
- 全市场合约、分区、时间覆盖和质量；
- DATA-1R任务控制；
- 实时行情健康，但不展示账户持仓；
- 数据异常和历史任务分开呈现。

数据卡片必须显示单位，禁止把 K 线、Funding 和归档文件相加为一个“总记录数”。

### 研究

- 研究主题；
- 假设与变量；
- 实验预注册；
- 实验运行；
- 研究证据和结论。

默认主线为“量价关系”，M0/F1/G1/G2 进入历史研究档案，不再占据首页主流程。

### 策略

- 正式策略目录；
- 冻结定义与 hash；
- 证据包；
- 准入状态和已知风险；
- 不提供启动、下单或调参按钮。

### 运行/实盘

- Paper与Live实例；
- 预热、运行、降级和停止状态；
- 当前信号和目标仓位；
- 实盘账户绑定和执行入口。

### 执行

初期可以作为实盘页二级页，展示计划、订单、成交和对账；当多策略、多账户并行后再升级为一级导航。

### 复盘、风控、账户

保持现有用户心智，但改为消费各自模块 API，不再从一个全量 snapshot 推导全部业务事实。

## 10. 目标代码结构

长期目标按业务模块组织，同时在每个模块内部保持 domain/application/ports/adapters 分层：

```text
backend/src/orbit/
  modules/
    data/
      domain/
      application/
      ports/
      adapters/
    research/
    strategy/
    runtime/
    execution/
    risk/
    review/
    accounts/
  api/
    routers/
    schemas/
  bootstrap.py
```

这不是要求一次性移动所有文件。迁移期允许现有 `application/`、`domain/`、`infrastructure/` 目录继续存在；先通过模块端口和测试建立边界，再做机械移动，避免“大搬家但依赖不变”。

前端长期目标：

```text
frontend/src/
  modules/
    data/
    research/
    strategy/
    runtime/
    execution/
    risk/
    review/
    accounts/
  shell/
  shared/
```

每个前端模块拥有自己的 API client、store、routes、pages 和领域展示转换。全局 store 最终只保留认证、导航和全局健康摘要。

## 11. 现有能力映射

| 现有能力/文件 | 目标模块 | 迁移说明 |
|---|---|---|
| `shortline_dataset.py`、DATA-1R | Data | 保持算法，提取数据应用服务和查询 API |
| `research/catalog.py` 中数据扫描 | Data | 从研究目录扫描拆为版本化数据目录 |
| `research/protocols.py` | Research | 协议转为实验模板，不视为正式策略 |
| `research/runs.py` | Research + Jobs | 数据任务与实验任务拆账本/投影 |
| `strategy_catalog.py` | Strategy | 继续作为只读策略定义入口 |
| `trend_basket_runner.py` | Runtime/Strategy | 冻结 spec 归 Strategy，runner 归 Runtime；首期不移动代码 |
| `trend_forward.py`、账本 | Runtime | 保持写入语义和前向起点 |
| `live_execution.py`、`order_execution.py` | Execution | 订单副作用唯一入口 |
| `live_risk.py`、`domain/risk` | Risk | 整合风险政策和事件，不改TB4阈值 |
| `portfolio_views.py`、ReviewPage | Review | 拆成只读归因与审计投影 |
| `accounts.py`、credentials | Accounts | 继续持有账户与凭证边界 |
| `AppState` | Composition/legacy facade | 逐步只保留兼容转发与进程生命周期 |
| `appStore.js` | Frontend shell/legacy facade | 按模块拆 store，最后移除业务聚合 |

## 12. TB4保护边界

在独立切换任务获批前，下列对象不得改变：

- `TB4_SPEC` 的12市场、4h周期、14/28/56/84/168天动量、vol28、目标波动10%、7天再平衡、gross cap 1.0、往返成本0.14%；
- spec fingerprint 和策略 definition hash；
- Paper manifest、初始化时间、market cursor 和只追加哈希链账本；
- LIVE-SMALL 的500 USDT授权边界、TB4目标3倍投影、逐仓3x与12市场映射；
- 当前行情拉取、预热、信号、目标、执行清单和对账路径；
- 风险停止线、急停语义和恢复纪律；
- 已有历史研究报告及其数据指纹。

模块重构期间的强制回归证据：

1. `verify_tb4_alignment.py` 仍为 `TB4_ALIGNMENT_PASS`；
2. 固定输入回放的每根目标权重和净收益误差为0；
3. 相同状态快照生成的原始TB4目标、3倍Live目标和执行清单逐项一致；
4. Paper与Live账本没有被重建、截断或重排；
5. DATA-1R停止、损坏模拟和数据任务重启均不影响TB4 runtime健康；
6. 数据统一阶段不触发TB4服务重启或前向重新初始化。

任何一项失败都必须停止迁移切换，保留旧读取路径并记录失败证据。

## 13. 分阶段迁移计划

### MOD-0：冻结基线

交付：

- 保存当前导航、API和模块依赖清单；
- 固定 TB4 spec、definition、Paper manifest和Live协议 hash；
- 建立 DATA-1R 与 TB4 runtime 故障隔离测试；
- 建立术语表：数据版本、实验、策略定义、实例、执行、verdict。

验收：现有测试、前端构建和TB4对齐全部通过；不改变生产行为。

### MOD-1：先拆前端信息架构

交付：

- 新增独立“数据”和“研究”入口；
- “策略”页只保留正式策略；
- DATA-1R面板迁至数据页；
- 研究候选、预注册和结果迁至研究页；
- 历史任务按数据任务和实验任务分类；
- 修正混合记录数和 `dataset_manifest` 展示。

实现方式：首期复用现有API，只调整页面组合和投影，不改TB4后端。

验收：所有原功能可达；历史记录和数据不丢失；TB4页面数据zero-diff。

### MOD-2：建立数据模块契约

交付：

- `MarketDataSchema v1`；
- `DatasetVersion`、质量报告和分区查询 DTO；
- `/api/data/versions`、`/quality`、`/jobs`；
- DATA-1R从研究workflow移入数据应用服务；
- 普通校准JSON以legacy dataset adapter只读接入。

验收：同一DATA-1R manifest得到稳定版本和fingerprint；数据任务失败不产生研究 verdict；TB4不调用新接口。

### MOD-3：重建研究工作流

交付：

- `ResearchTopic/Hypothesis/ExperimentDefinition/ExperimentRun/ResearchResult`；
- 量价关系作为首个正式研究主题；
- 研究实验绑定DatasetSnapshot而非任意文件路径；
- M0/F1/G1/G2作为legacy experiment只读导入；
- 程序状态与研究verdict分离。

验收：实验可复现；数据指纹漂移会阻止运行；失败实验永久保留；不产生Paper/Live授权。

### MOD-4：策略目录与准入

交付：

- 统一 `StrategyDefinition/StrategyEvidenceBundle/AdmissionDecision`；
- TB4作为legacy冻结策略只读投影；
- 候选升级为策略需要显式准入任务；
- 策略页不再读取研究内部文件结构。

验收：TB4两个冻结hash与现状相同；旧研究报告可追溯；无调参写接口。

### MOD-5：运行与执行解耦

交付：

- `StrategyInstance`、`TargetPortfolio` 与运行状态API；
- Paper和Live实例明确分账；
- Execution只消费已发布目标和RiskDecision；
- 账户绑定、订单幂等和对账事实归位。

验收：同一事件输入的旧/新目标zero-diff；订单不重复；TB4前向起点和账本不变。

### MOD-6：拆除兼容聚合层

交付：

- 前端按模块store读取；
- `AppState`不再拥有跨模块业务事实，只保留兼容facade直至旧API下线；
- 删除已无调用的旧页面、旧别名和重复投影；
- 更新 `ARCHITECTURE.md` 与运行手册为新模块事实。

删除动作必须在独立变更中执行，并先证明旧入口无生产调用。

## 14. 测试与验收矩阵

### 14.1 模块边界

- 静态依赖检查阻止 Research 导入 Execution、Strategy 导入 Binance adapter；
- 模块契约使用版本化 DTO；
- 跨模块数据库读取通过测试或代码检查阻断；
- composition root 只装配，不承载业务判断。

### 14.2 数据

- 同一原始输入重复构建得到相同派生字节和fingerprint；
- 缺15m子根时1h/4h为`INCOMPLETE`；
- 历史查询严格受snapshot cutoff约束；
- Live窗口只加载策略需求，不扫描全市场历史；
- DATA-1R失败不影响LiveMarketWindow。

### 14.3 研究与策略

- 实验定义冻结后不可修改；
- 运行成功与研究SUPPORTED独立；
- 结果绑定实验hash、数据hash和引擎版本；
- 策略准入只能引用不可变证据；
- 研究失败不会删除或覆盖历史。

### 14.4 运行、执行与风险

- runner对相同事件产生确定性决策；
- Risk BLOCK时不能落发送订单的outbox；
- 下单超时进入UNKNOWN并对账，不重复发送；
- Paper与Live状态、权益和账本分离；
- 重启后cursor、runner、订单和真实持仓可恢复对账。

### 14.5 前端

- 用户能在两次点击内到达数据、研究、正式策略和实盘状态；
- 每个统计数字都有单位和来源；
- 历史失败不会覆盖当前有效状态；
- 页面明确区分任务状态、数据状态、研究verdict和策略准入；
- 只读页面没有造成副作用的控件。

## 15. 发布、回退与观测

每阶段采用 expand-and-verify：

1. 先新增模型、API或页面；
2. 旧路径继续作为唯一写入源；
3. 新路径shadow读取并比较；
4. 保存差异报告；
5. 达到验收门后单独切换读取；
6. 观察稳定期后再移除旧路径。

禁止未经校验的双写。若必须双写，必须有统一事务或可证明的outbox、稳定幂等键和逐条一致性报告。

每次发布至少观察：

- 数据任务与实时行情健康是否互相影响；
- TB4 market cursor是否连续；
- Paper/Live目标是否发生非预期变化；
- 订单重复、未知状态和对账差异；
- 模块API错误率与长任务积压；
- 新旧投影差异计数。

回退只切回旧读取/路由，不回滚或删除已经产生的不可变事实。

## 16. 非目标

本轮模块重划分不包含：

- 修改TB4策略参数或市场；
- 使用DATA-1R替换TB4实时数据；
- 开发具体量价入场信号；
- 引入新的数据库或消息队列；
- 扩大Live资金、杠杆或账户范围；
- 删除旧研究数据和失败记录；
- 一次性重写全部后端目录。

## 17. 决策完成标准

本设计进入 `ACCEPTED` 前，需要确认以下产品决策：

1. 一级导航是否采用“数据、研究、策略、实盘、复盘、风控、账户”；
2. “执行”首期作为实盘二级页，还是直接作为一级页；
3. M0/F1/G1/G2是否统一归入“历史研究档案”；
4. 首个新研究主题是否正式命名为“量价关系”；
5. MOD-1是否作为第一个实施任务，且明确只改信息架构与展示口径，不触碰TB4运行路径。

确认后，实施必须按 `MOD-0 -> MOD-1 -> MOD-2...` 建立独立任务、验收记录和提交，不能把模块重构与策略研究混在同一次变更中。
