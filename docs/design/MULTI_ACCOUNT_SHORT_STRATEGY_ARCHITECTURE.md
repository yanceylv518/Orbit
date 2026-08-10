# Orbit 多账户短线策略平台升级架构

状态：`PROPOSED`（目标架构，尚未实现）
最后更新：2026-08-10

本文定义 Orbit 从单一 TB4/旧策略运行闭环升级为多账户短线策略研究、回测、Paper 与 Live 平台的正式目标架构。本文不是当前能力声明；凡标记为目标组件、目标表或目标状态机的内容，在迁移完成并通过验收前均不得对外宣称已可用。

## 1. 已确认的产品目标

目标用户是平台管理员。管理员研发、冻结、验证并挂载平台策略；业务用户仅是交易账户归属方，不自行编写或运行策略。

目标场景：

- Binance USDT 永续合约。
- 持仓周期约数分钟、数十分钟至数小时。
- 首批策略族为突破/动量与超跌反弹。
- 支持做多、做空；目标杠杆为 3–5 倍，但必须经过分阶段准入。
- 系统每日按历史时点可见的流动性自动生成币池。
- 一个交易账户在任一时刻只允许运行一个激活的策略实例。
- 多个交易账户可并行运行不同策略或同一策略的不同实例。
- 每个账户最多同时持有 3 个非零币种仓位；这是硬上限，不是目标持仓数。
- 满 3 仓时，新信号不抢占、不排队、不强制换仓；名额释放后按最新行情重新计算。

产品成功标准不是“回测盈利”，而是同一冻结定义能够在回测、Shadow、Paper 和 Live 中得到可解释、可对账、可恢复的行为，并能可靠拒绝没有证据或不可成交的策略。

## 2. 范围与非目标

### 2.1 本次目标范围

- 分钟级事件驱动研究与运行，底层至少保存 1m K 线，并支持 5m/15m 信号周期。
- 动态流动性币池的历史重建、每日冻结和线上消费。
- 策略定义、策略实例、账户绑定和运行状态的版本化持久化。
- 账户级三仓名额、资金、杠杆和风险控制。
- 多账户并行调度、故障隔离、租约认领和重启恢复。
- 可重放的组合级回测，以及与 Paper/Live 同源的策略决策内核。
- Binance 公共行情共享接入、账户私有流隔离和全局限频协调。
- 订单意图、交易所订单、成交、对账和审计的完整链路。

### 2.2 明确非目标

- 秒级抢单、做市、盘口排队优势或其他高频交易。
- 同一账户同时运行多个策略。
- 第一版自动换仓抢占；满仓信号仅记录为容量拒绝。
- 马丁格尔、无限网格、亏损无限加仓。
- 业务用户上传任意策略代码或在生产进程执行任意脚本。
- 依赖当前仍存活币种回推历史币池。
- 将无杠杆收益简单乘以杠杆作为合约回测。
- 在研究通过后自动解锁真实资金交易。

若未来需要同账户多策略、秒级高频或第三方策略插件，必须另立架构决策，不得绕过本文不变量。

## 3. 约束与待确认项

已确认约束：

- 所有正式路径使用真实数据，不允许 Mock 或硬编码币池进入生产。
- 一个账户最多一个 `ACTIVE` 或 `STOPPING` 策略绑定。
- 一个账户最多 3 个非零币种仓位；人工仓位和未知归属仓位也计入。
- 同一账户同一币种只允许一个净方向，第一版禁止多空对锁。
- 平仓未确认、仓位未归零前不得释放名额。
- 行情、账户流、订单状态或持仓状态不确定时，停止新增风险。
- 3–5 倍是待准入目标，不是默认启用值。

尚待产品确认：

- Paper 与小额 Live 的资金规模。
- 单笔、单日、账户总风险预算的最终冻结数值。
- 动态币池目标数量、上市最短天数、深度金额档位和点差阈值。
- 是否存在共享同一资金来源的账户；若存在，需启用跨账户全局风险上限。

这些待确认项必须作为版本化策略或风险配置保存，不得散落为代码常量。

## 4. 架构原则与关键决策

### ADR-01：一个账户只绑定一个激活策略实例

数据库唯一约束和领域规则共同保证 `exchange_account_id` 最多存在一个 `ACTIVE`/`STOPPING` 绑定。策略切换必须先停止旧实例、撤销开仓订单、处理旧仓并完成对账，再激活新实例。

备选方案是同账户多策略和订单净额化。该方案需要组合资金分配、信号冲突和归因系统，当前没有产品必要性，拒绝采用。

### ADR-02：共享行情，隔离策略与账户执行

公共行情按交易所和市场流只接收一次并持久化，多个策略实例消费同一不可变事件；私有账户流、凭据、订单、持仓、风险和消费位置按账户/实例隔离。

备选方案是每账户独立拉取全部行情。它会重复消耗限频、产生不同步数据并放大连接故障，拒绝采用。

### ADR-03：持久化租约取代进程内线程所有权

运行 worker 通过数据库租约认领策略实例。一个实例同一时刻只能由一个 worker 持有；租约丢失后旧 worker 必须停止产生动作，新 worker 先对账再恢复。

第一阶段允许以 MySQL 租约表和事务实现，不强制引入外部消息系统。若吞吐或可用性证据证明不足，再通过端口替换为专用队列。禁止把现有进程内 `Lock` 当作多 worker 一致性保证。

### ADR-04：订单采用“至少一次驱动 + 幂等副作用”

跨网络无法承诺端到端 exactly-once。系统持久化 `OrderIntent`，生成稳定客户端订单 ID，发送超时后先查询交易所状态，再决定重试。事件可以重复消费，但同一意图不得产生重复交易所订单。

### ADR-05：组合级事件回测是唯一准入收益口径

单信号统计仅用于诊断。准入必须使用账户级事件回测，真实执行每日币池、三仓上限、资金占用、信号排序、费用、资金费、点差、滑点、部分成交、退出和保证金规则。

### ADR-06：第一版满仓不自动换仓

满 3 仓时，新开仓意图记录为 `BLOCKED_BY_POSITION_LIMIT`，不排队。名额释放后只允许基于最新事件重新生成意图。被阻止信号作为反事实证据保存，不计入账户实际收益。

自动换仓属于后续候选政策，只有在独立样本证明扣除双边成本后仍有增益时才能新增版本。

## 5. 目标系统边界

```text
                         Web Admin Console
                                  |
                                  v
                         Control Plane API
                                  |
          +-----------------------+-----------------------+
          |                       |                       |
          v                       v                       v
 Strategy Registry       Account/Binding Service    Admission Service
          |                       |                       |
          +-----------------------+-----------------------+
                                  |
                         Persistent Control State

 Binance Public Streams -> Market Data Gateway -> Market Event Store
                                      |                    |
                                      v                    v
                               Universe Builder       Replay Reader
                                      |                    |
                                      +---------+----------+
                                                |
                                                v
                                      Strategy Runtime Workers
                                      (lease-owned instances)
                                                |
                                      Decision + Risk Kernel
                                                |
                                      Order Intent / Outbox
                                                |
                         +----------------------+----------------------+
                         |                                             |
                         v                                             v
              Account Execution Gateway                     Paper Execution
                         |
                 Binance Private API/Stream
                         |
                  Reconciliation Service
```

### 5.1 控制面

职责：

- 管理策略定义、冻结版本和证据状态。
- 管理账户与策略实例绑定。
- 启动、停止、恢复、切换和急停实例。
- 展示运行状态、错误、风险和对账结果。

控制面不执行长期循环，不直接下单，不保存凭证明文。

### 5.2 市场数据面

职责：

- 接收 Binance 公共 WebSocket 行情。
- 保存原始事件、接收时间、交易所事件时间和序列信息。
- 检测缺口、乱序、重复、延迟和连接降级。
- 使用 REST 回补可回补的数据，并标记不可恢复区间。
- 向实时 runner 和历史 replay 提供相同规范化事件模型。

第一版最少数据：1m OHLCV、成交笔数/主动成交量（若上游提供）、最佳买卖价与数量、资金费率、标记价格、交易规则和合约状态。仅有 K 线收盘价不足以验证短线可成交性。

### 5.3 币池服务

币池由版本化 `UniversePolicy` 生成每日不可变 `UniverseSnapshot`：

- 只使用 `source_data_cutoff` 之前可见的数据。
- 检查 USDT 永续可交易状态、上市时长、历史成交额中位数、数据完整率、点差、深度、冲击成本和交易规则。
- 使用进入/退出双阈值和每日换入换出上限降低抖动。
- 新入选只表示“可观察和可开仓”，不表示必须持仓。
- 已持仓币被移出时进入 `MANAGE_ONLY`：不加仓，继续执行退出和风险动作。
- 构建失败时默认 `NO_NEW_ENTRY`，不得静默复用过期币池；若未来允许有限期沿用，必须显式配置最大陈旧时间并审计。

### 5.4 策略运行面

每个激活绑定对应一个 `StrategyInstance`。runner 只消费已确认、顺序明确的市场事件，并输出纯领域 `SignalDecision`，不直接访问 Binance 或数据库。

突破/动量和超跌反弹共享运行协议，但各自拥有独立的：

- 数据需求；
- 信号定义；
- 参数和版本；
- 最长持仓、止盈、止损、时间退出和异常退出；
- 信号有效期；
- 证据包与准入状态。

同一份冻结决策内核必须被 replay、Shadow、Paper 和 Live 适配器复用。环境差异只能位于行情时钟、成交适配器和外部端口。

### 5.5 风险与名额服务

账户级 `PortfolioRiskPolicy` 在任何开仓意图落 outbox 前同步判定：

- 非零币种仓位 + 预留开仓名额不得超过 3。
- 人工仓位和未知归属仓位占用名额并触发 `NO_NEW_ENTRY`。
- 同币种仅允许一个净方向。
- 校验单笔计划亏损、账户总计划亏损、总敞口、有效杠杆、日亏损、连续亏损、强平距离、数据新鲜度和流动性。
- 风控拒绝必须持久化原因，不得只写日志。

名额使用数据库行锁/原子条件更新预留。开仓意图创建、名额预留和 outbox 写入处于同一事务；订单终态失败可释放预留，实际成交则转为持仓占用。

### 5.6 执行与对账面

职责：

- 将已批准 `OrderIntent` 转为交易所订单参数。
- 从实时 `exchangeInfo`/版本化规则读取 tick size、step size、最小数量和最小名义金额。
- 使用账户维度幂等键和客户端订单 ID。
- 持久化请求、响应、未知结果、成交和费用。
- 消费账户私有流，并以周期 REST 对账作为恢复机制。
- 对部分成交、撤单冲突、响应超时和交易所拒绝提供显式状态。

第一版不得无条件使用市价单。每个策略版本必须冻结执行政策，例如可成交限价、有效期、撤单条件和是否允许受限市价退出。风险退出可以拥有高于普通开仓的执行优先级，但仍需记录实际滑点。

## 6. 核心数据模型

下列为逻辑模型；字段类型、索引和分区在实现 ADR 中确定。

```text
StrategyDefinition
- id, family, version, status
- signal_spec, exit_spec, execution_policy
- required_data_schema_version
- definition_hash, created_at

StrategyEvidenceBundle
- strategy_definition_id
- dataset_fingerprints
- replay_engine_version
- metrics, verdict, admission_state
- immutable_hash, created_at

StrategyInstance
- id, strategy_definition_id
- configuration, configuration_hash
- state, state_version
- last_market_cursor, last_decision_at
- created_at, updated_at

AccountStrategyBinding
- id, exchange_account_id, strategy_instance_id
- status, activated_at, deactivated_at
- stop_mode, failure_reason

RunnerLease
- strategy_instance_id
- owner_id, fencing_token
- lease_until, heartbeat_at

UniversePolicy
- id, version, schedule
- observation_windows, eligibility_rules
- ranking_formula, entry_rank, exit_rank
- policy_hash

UniverseSnapshot
- id, policy_id, effective_from, effective_until
- source_data_cutoff, status
- selected_symbols, excluded_reasons
- metrics_by_symbol, dataset_hash

MarketEvent
- stream, symbol, event_type
- exchange_time, received_time, sequence
- payload_schema_version, payload_hash

PortfolioRiskPolicy
- id, version
- max_open_symbols = 3
- exposure, leverage, loss and liquidity limits
- policy_hash

PositionSlot
- account_id, symbol
- state: RESERVED / OPEN / CLOSING / UNKNOWN / RELEASED
- strategy_instance_id, order_intent_id
- state_version, updated_at

SignalDecision
- id, strategy_instance_id, symbol
- market_cursor, side, score, expires_at
- input_hash, decision_hash, status
- rejection_reason

OrderIntent
- id, account_id, strategy_instance_id
- signal_decision_id, symbol, side, purpose
- requested_quantity, execution_policy
- idempotency_key, status, expires_at

ExchangeOrder
- account_id, order_intent_id
- client_order_id, exchange_order_id
- status, requested_qty, executed_qty
- average_price, fees, last_exchange_update

Fill
- account_id, exchange_order_id, trade_id
- quantity, price, fee, event_time

ReconciliationRun
- account_id, started_at, completed_at
- observed_positions, observed_orders
- mismatch_summary, status, recovery_action
```

强制约束：

- 每个账户最多一条活跃或停止中的绑定。
- `OrderIntent.idempotency_key` 全局唯一，至少包含账户、实例、决策和动作语义。
- `ExchangeOrder(account_id, client_order_id)` 唯一。
- `Fill(account_id, trade_id)` 唯一。
- 每个实例的租约 fencing token 单调递增；过期 token 的 worker 禁止写运行副作用。
- 持仓名额的 `RESERVED/OPEN/CLOSING/UNKNOWN` 数量不得超过 3；风险退出不因名额上限被阻断。

## 7. 状态机

### 7.1 策略实例运行状态

```text
PENDING -> STARTING -> WARMING_UP -> RUNNING
              |             |          |
              v             v          v
            FAILED        DEGRADED <- RECOVERING
                                          |
RUNNING -> STOPPING -> STOPPED <-----------+
   |
   +-> EMERGENCY_STOP -> STOPPING
```

- `STARTING`：校验绑定、凭据引用、账户模式、交易规则、风险政策和租约。
- `WARMING_UP`：读取足够历史，但不允许产生 Live 开仓。
- `RUNNING`：数据新鲜、账户已对账且风险政策有效。
- `DEGRADED`：公共行情部分延迟等可观察故障；默认禁止新开仓。
- `RECOVERING`：租约接管或重启后重放状态并对账。
- `STOPPING`：停止开仓、处理挂单和旧仓；期间仍占账户唯一绑定。

### 7.2 订单状态

```text
CREATED -> APPROVED -> DISPATCHING -> ACKNOWLEDGED
                |            |              |
                v            v              v
             REJECTED      UNKNOWN       PARTIALLY_FILLED
                                |              |
                                v              v
                           RECONCILING -> FILLED / CANCELED / REJECTED
```

`UNKNOWN` 不是失败。处于该状态时必须查询账户流和订单接口；禁止直接创建替代订单。

### 7.3 策略切换

```text
旧实例 NO_NEW_ENTRY
-> 撤销未成交开仓意图
-> 旧仓按 stop_mode 平仓或 MANAGE_ONLY
-> 对账确认订单终态且仓位归零
-> 旧绑定 INACTIVE
-> 新绑定 STARTING
```

任何一步失败都保持旧绑定占用，不能并行激活新实例。

## 8. 关键运行流程

### 8.1 每日币池生成

1. 调度器创建带唯一业务键的构建任务。
2. 读取截止时点之前的历史市场、合约状态和规则。
3. 计算资格、流动性、点差、深度与数据质量。
4. 应用进入/退出迟滞和换入换出上限。
5. 在事务中写入不可变快照、明细、排除原因和 hash。
6. 运行实例只在 `effective_from` 到达后切换到该快照。
7. 构建失败时保留失败记录并切换为 `NO_NEW_ENTRY`，提供人工恢复入口。

### 8.2 信号与三仓仲裁

1. runner 消费一个已确认市场事件。
2. 对当前有效币池计算候选信号和退出信号。
3. 退出和减仓先于开仓。
4. 开仓候选按冻结评分排序，处理同币冲突。
5. 风险服务读取真实持仓、未知仓位和名额预留。
6. 满仓候选保存为 `BLOCKED_BY_POSITION_LIMIT`，不得进入延迟队列。
7. 有名额的候选在同一事务内预留 slot、写 `OrderIntent` 和 outbox。
8. 名额释放后等待下一有效市场事件重新计算，不重放旧候选。

### 8.3 重启恢复

1. worker 获得新 fencing token。
2. 加载最后持久化策略状态与市场 cursor。
3. 回放 cursor 之后的不可变市场事件，只生成尚未存在的决策 ID。
4. 查询交易所当前仓位、开放订单和近期成交。
5. 对账本地 slot、订单和交易所事实。
6. 存在未知差异时进入 `DEGRADED/NO_NEW_ENTRY`，只允许风险降低动作。
7. 对账通过后进入 `RUNNING`。

## 9. 回测、Shadow、Paper 与 Live 一致性

```text
MarketEvent + UniverseSnapshot + Frozen StrategyDefinition
                         |
                         v
                Shared Decision Kernel
                         |
                         v
                  SignalDecision
                         |
             +-----------+-----------+
             |           |           |
             v           v           v
       Replay Fill   Paper Fill   Live Order Adapter
```

必须一致的内容：币池、信号、排序、三仓上限、退出、风险政策、数量舍入和状态迁移。

允许不同的内容：时钟实现、成交适配器、网络故障和真实交易所响应。

分钟级 replay 必须：

- 信号只使用已经闭合的数据；信号产生后在下一可交易时刻成交。
- 使用当时 bid/ask、费用档位、资金费、深度和延迟假设。
- 模拟部分成交、最小订单规则、保证金和强平边界。
- 同一 K 线同时触及止盈/止损而无法判断顺序时，使用更细数据或保守路径并标记歧义。
- 同时输出信号诊断层与可执行组合层，禁止混合口径。
- 保存被三仓上限拒绝的反事实信号，但不计入账户权益。

## 10. 一致性、并发与限频

- 核心写入采用 MySQL 事务；订单发送等外部副作用通过 transactional outbox 驱动。
- worker 只能处理持有有效租约且 fencing token 匹配的实例。
- 市场事件按 stream cursor 幂等消费，重复事件由稳定事件键去重。
- 同账户的决策/风险/slot 变更串行化；不同账户可并行。
- 公共行情连接共享，账户私有流独立。
- `ExchangeRateLimitCoordinator` 按 Binance 权重、订单限额和账户维度调度；风险退出优先于普通开仓。
- 出现限频压力时先暂停新开仓，不能延迟止损而没有告警。

## 11. 安全与权限

- 凭据只以 vault 引用进入执行 gateway；策略、回测、日志和前端永不接触 Secret。
- 建议交易 Key 禁用提现权限并限制来源 IP；权限检查结果需可审计。
- 账户 ID、策略实例 ID和调用目的进入每条审计记录。
- 后台 worker 使用最小数据库权限；市场数据 worker 不具备读取账户凭据权限。
- 操作员启动 Live、提升杠杆、切换策略、解除急停和处理未知订单均需权限与审计。
- 所有远程响应做 schema、范围和账户归属校验；未知字段兼容保存但不直接驱动领域动作。
- 敏感错误不得包含签名串、请求头、API Key、Secret 或原始 vault 内容。

## 12. 故障处理与恢复策略

| 故障 | 默认行为 | 恢复条件 |
|---|---|---|
| 公共行情断开/过期 | 全部相关实例 `NO_NEW_ENTRY`；已有仓由可用风控路径管理 | 缺口回补、时钟连续并重新暖机 |
| 单账户私有流断开 | 仅该账户停止新开仓 | REST 对账通过且私有流恢复 |
| 下单响应超时 | 意图进入 `UNKNOWN`，不重下 | 查询得到明确终态并对账 |
| 币池生成失败 | 当期禁止新开仓 | 有效快照成功生成并生效 |
| worker 崩溃 | 租约到期后由其他 worker 接管 | 重放、订单和持仓对账通过 |
| 数据库不可用 | 停止产生外部副作用 | 数据库恢复并确认 outbox/租约状态 |
| 人工/未知仓位出现 | 占用名额，账户 `NO_NEW_ENTRY` | 管理员归属或平仓后对账通过 |
| 交易规则变化 | 阻止不满足新规则的订单 | 新规则版本保存、数量重算 |
| 单账户风险超限 | 仅该账户停止开仓或降险 | 满足冻结恢复协议并经授权 |
| 全局风险超限 | 所有受管账户停止新增风险 | 全局风险恢复且管理员授权 |

任何自动重试必须有最大次数、退避、最终状态和人工恢复入口；禁止无限等待或静默失败。

## 13. 部署拓扑与技术选择

逻辑角色：

- `api`：控制面和查询 API。
- `market-data-worker`：公共行情接入、规范化和持久化。
- `universe-worker`：每日币池构建。
- `strategy-worker`：按租约运行多个策略实例。
- `execution-worker`：发送订单并消费私有账户事件。
- `reconciliation-worker`：定期及恢复时对账。
- `replay-worker`：离线组合级回测。

初始部署可以把多个角色放在同一发布包和少量进程中，但逻辑边界、端口、表和租约必须从第一天独立，确保以后水平扩展不需要改写领域模型。

初始持久化继续使用 MySQL，避免无证据引入新的关键基础设施。市场历史数据量增长后，可在保持 `MarketEventRepository` 端口的前提下评估列式存储或对象存储；迁移前必须有容量、查询和恢复测试证据。

## 14. 兼容与迁移计划

### 阶段 0：架构基线

- 冻结本文和相应 ADR。
- 为旧 TB4、旧双网格和新短线平台标记明确 bounded context。
- 不改变现有 Live 开关和 TB4 证据。

### 阶段 1：控制面与数据模型

- 新增 StrategyDefinition、StrategyInstance、AccountStrategyBinding、RiskPolicy 和 RunnerLease。
- 将现有 TB4 作为 legacy definition 只读导入，不修改冻结 hash。
- 增加数据库约束，先 shadow 校验账户是否存在冲突绑定。

### 阶段 2：共享市场数据与动态币池

- 建立 WebSocket 接入、缺口检测和 REST 回补。
- 构建点时一致的历史规则与每日币池快照。
- 在不下单条件下验证线上快照与历史重建一致性。

### 阶段 3：组合 replay 与策略 SDK

- 建立共享决策协议、突破/动量和超跌反弹候选。
- 实现三仓名额、信号 TTL、退出规则和真实成本模拟。
- 完成回测/runner 对齐测试后才进入 Shadow。

### 阶段 4：多账户 Shadow/Paper

- 引入租约 worker、账户隔离、Paper 成交和对账。
- 进行多账户并发、故障注入和长期运行。
- 不能因 Paper 成功自动开启 Live。

### 阶段 5：小额 Live

- 先使用低有效敞口验证成交和恢复。
- 3 倍与 5 倍分别建立准入状态和人工审批。
- 任一严重对账、重复订单或跨账户隔离缺陷均回退到 `NO_NEW_ENTRY`。

兼容原则：旧 API 和旧数据读取在迁移窗口内保留适配层；新写入只进入新模型。不得双写两个互不校验的事实源。所有表迁移先扩展、回填、校验，再切换读取，最后在独立版本删除旧字段。

## 15. 验收与证据要求

### 15.1 领域与回测

- 相同输入、定义 hash 和币池快照产生完全相同决策。
- 历史币池不使用生效时间之后的数据。
- 五个同时信号只能按冻结排序批准最多三个。
- 满仓信号被持久化拒绝，名额释放后旧信号不自动执行。
- 已移出币池的持仓进入 `MANAGE_ONLY`。
- 回测、Paper 和 Live runner 对相同事件流的决策逐事件一致。

### 15.2 并发与恢复

- 多账户同币交易不串订单、状态、风险或凭据。
- 两个 worker 竞争同一实例时只有有效 fencing token 能写副作用。
- 下单超时且交易所已成交时不会产生重复订单。
- 部分成交、撤单和重启后 slot 数量与真实仓位一致。
- 单账户故障不会阻塞其他账户；共享行情故障会一致停止相关新增风险。
- 数据库和进程故障恢复后，市场 cursor、策略状态和订单账本可重放对账。

### 15.3 安全与运维

- 凭据不出现在日志、API、报告和测试夹具中。
- Live 启动、杠杆提升、策略切换、急停恢复均有审计。
- 告警覆盖行情陈旧、租约丢失、订单未知、对账差异、币池失败、限频和风险停止。
- 运行手册包含启动、停止、灾难恢复、未知订单处理和交易所故障演练。

### 15.4 发布门

- 相关单元、集成、回放对齐、并发和故障注入测试通过。
- 后端类型/静态检查和前端生产构建通过。
- 数据迁移在生产规模副本完成演练并可回滚。
- 至少完成规定周期的 Shadow 与 Paper 前向观察。
- 所有未验证项、已知风险和准入 verdict 在唯一进度事实源中明确记录。

## 16. 已知风险与未完成证据

- 当前仓库的正式策略目录仍以 TB4 为中心，尚无通用策略注册与运行协议。
- 现有市场数据主要是 REST K 线轮询，尚无本文要求的 WebSocket 行情事件仓。
- 现有成本模型不足以证明低流动性山寨币短线可成交性。
- 当前进程内线程/锁不足以证明多 worker 所有权和恢复安全。
- 尚无动态历史币池、三仓组合 replay、订单 outbox、fencing token 和多账户故障注入证据。
- 资金规模未确认，因此深度阈值、单仓额度和最终风险预算不能冻结。
- 3–5 倍杠杆尚未获得任何新短线策略的准入证据。

在上述证据补齐前，本方案只授权后续工程建设和 Shadow/Paper 验证，不授权真实资金运行。
