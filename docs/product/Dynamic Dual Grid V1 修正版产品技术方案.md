# Dynamic Dual Grid V1 修正版产品技术方案

## 1. 文档目的

本文档是在原始需求文档《Dynamic Dual Grid V1 开发需求》的基础上，结合后续讨论后的修正版产品技术方案。

本次修正明确了三个关键变化：

1. 数据库使用 MySQL，而不是 SQLite。
2. 系统需要有用户、交易账户、管理员角色和权限边界。
3. 策略核心收束为三类可配置事件：利润搬运、搬运后的仓位恢复、单边趋势确认后的亏损仓位减仓。

V1 的目标不是追求策略收益最大化，而是构建一套可实盘小资金验证、可审计、可追溯、可调参、可风控的双向动态仓位系统。

## 2. 产品定位

Dynamic Dual Grid V1 是一个面向合约市场的小资金实盘验证系统。

它不是传统网格，也不是预测型交易系统。它的核心思想是：

1. 同一币种同时维护 Long 和 Short 两侧仓位。
2. 当某一侧产生利润时，通过减仓实现利润。
3. 将实现后的利润额度用于恢复或增加另一侧仓位。
4. 当行情确认进入单边趋势时，停止逆势恢复，并逐步削减亏损侧仓位。
5. 所有动作必须可配置、可追踪、可复盘。

系统外围包含用户、交易账户、管理员、风控、报表、审计等能力。策略内核只关注仓位事件和资金变化。

## 3. V1 核心目标

P0 目标：

1. 支持多用户、多交易账户、多策略实例的数据模型。
2. 支持管理员查看所有用户账号和策略运行情况。
3. 支持 Binance USDT 永续合约的 dry_run 模拟运行。
4. 支持基于配置的利润搬运事件。
5. 支持搬运后的仓位恢复事件。
6. 支持单边趋势确认后的亏损仓位减仓事件。
7. 完整记录手续费、滑点、Funding 预留字段、仓位变化、已实现盈亏、未实现盈亏。
8. 使用 MySQL 存储状态、快照、交易事件、报表和审计日志。
9. 每日生成 Markdown 报告和曲线图。
10. 默认禁止无确认实盘，V1 优先完成 dry_run。

P0 非目标：

1. 不追求复杂预测指标。
2. 不做参数自动优化。
3. 不做 AI 市场判断。
4. 不做复杂多交易所接入。
5. 不允许绕过风控直接实盘。

## 4. 核心业务对象

系统对象层级如下：

```text
Admin 管理员
  -> 查看和管理所有用户、账户、策略、风控、报表

User 用户
  -> ExchangeAccount 交易账户
    -> StrategyInstance 策略实例
      -> SymbolAllocation 单币种资金池
        -> SymbolState / MarketSnapshot / StrategyEvent / TradeEvent
```

### 4.1 User 用户

用户是系统使用者，拥有自己的交易账户和策略实例。

V1 可以先支持本地创建用户，不要求完整登录系统，但数据库和接口必须从第一天保留 `user_id`。

### 4.2 Admin 管理员

管理员是系统级角色，可以查看所有用户的账户情况、策略状态、风险状态和报表。

管理员允许：

1. 查看所有用户。
2. 查看所有交易账户的运行状态。
3. 查看账户权益、持仓、策略状态、异常日志。
4. 暂停用户、账户、策略或单个币种。
5. 触发全局 emergency stop。
6. 导出用户报表和事件日志。

管理员不允许：

1. 查看 API Secret 明文。
2. 绕过用户的 live_confirm。
3. 绕过风控执行交易。
4. 删除交易事件和审计日志。
5. 默认替用户手动开仓或加仓。

### 4.3 ExchangeAccount 交易账户

交易账户代表一个 Binance Futures 账户或 dry_run 模拟账户。

账户需要记录：

1. 所属用户。
2. 交易所名称。
3. 是否 testnet。
4. 是否 dry_run。
5. API Key 指纹。
6. API Secret 加密引用。
7. 是否开启 Hedge Mode。
8. 账户状态。

### 4.4 StrategyInstance 策略实例

策略实例代表某个用户在某个交易账户上运行的一套 Dynamic Dual Grid 配置。

同一个用户可以有多个策略实例，例如：

1. BTC/ETH 测试实例。
2. SOL 单币种实例。
3. testnet 实例。
4. live_small 实例。

### 4.5 SymbolAllocation 单币种资金池

每个策略实例下，每个 symbol 都有独立资金池。

例如：

```yaml
symbol_budget_usdt:
  BTCUSDT: 100
  ETHUSDT: 100
```

单币种内独立记录：

1. 预算。
2. 基础仓位。
3. Long 当前仓位。
4. Short 当前仓位。
5. 当前状态。
6. 价格基准。
7. 阶段高点和低点。
8. 已实现盈亏。
9. 未实现盈亏。
10. 手续费、滑点、Funding。
11. 事件次数和冷却状态。

## 5. 角色与权限模型

V1 可以采用简化 RBAC。

角色：

```text
user
admin
super_admin
```

推荐权限：

```text
user.account.read_own
user.strategy.create_own
user.strategy.control_own
user.report.read_own

admin.users.read_all
admin.accounts.read_all
admin.strategies.read_all
admin.risk.pause_any
admin.reports.read_all

super_admin.system.configure
super_admin.roles.manage
```

V1 可先在 `users.role` 中实现简单角色，后续再拆成完整 RBAC 表。

所有管理员动作必须写入 `admin_audit_logs`。

## 6. 策略核心设计

> 注：本章及 §10、§11、§12 存在若干已知逻辑缺口和待补规则，详见 §21「V1 已知策略逻辑缺口与待补设计」。

修正版策略核心只有三类事件：

1. 利润搬运事件。
2. 搬运后的仓位恢复事件。
3. 单边趋势确认后的亏损仓位减仓事件。

这三类事件都必须可配置。代码只负责解释配置、计算仓位、检查风控、执行动作、记录结果。

## 7. 事件引擎模型

每个事件按统一生命周期执行：

```text
trigger -> guard -> sizing -> risk_check -> action_plan -> execute -> accounting -> audit
```

含义：

1. `trigger`: 判断是否达到事件触发条件。
2. `guard`: 判断是否允许执行，例如冷却、次数限制、趋势过强限制。
3. `sizing`: 计算本次减仓和加仓数量。
4. `risk_check`: 执行前风控检查。
5. `action_plan`: 生成可执行动作列表。
6. `execute`: dry_run 模拟成交或实盘下单。
7. `accounting`: 更新 PnL、费用、仓位成本。
8. `audit`: 写入父事件、子事件、快照和 reason。

事件本身不应该直接依赖 Binance API。事件只生成动作意图，交易执行层负责模拟成交或真实下单。

## 8. 三大核心事件

### 8.1 利润搬运事件

利润搬运不是单纯账本划转，而是一组真实仓位动作。

上涨方向：

```text
Long 盈利达到阈值
-> 减少一部分 Long
-> 实现净利润
-> 使用净利润额度恢复或增加 Short
```

下跌方向：

```text
Short 盈利达到阈值
-> 减少一部分 Short
-> 实现净利润
-> 使用净利润额度恢复或增加 Long
```

关键原则：

1. 必须先减盈利侧仓位。
2. 必须用已实现净利润计算可搬运额度。
3. 不允许直接用未实现浮盈给亏损侧加仓。
4. 趋势确认过强后，禁止继续给亏损侧加仓。
5. `PROFIT_TRANSFER` 是父事件，实际订单是子事件。

父子事件示例：

```text
PROFIT_TRANSFER_UP
  -> REDUCE_PROFIT_SIDE_LONG
  -> REALIZE_PROFIT
  -> ADD_LOSS_SIDE_SHORT
```

配置示例：

```yaml
events:
  profit_transfer:
    enabled: true
    priority: 30
    trigger:
      min_profit_pct_of_symbol_budget: 3.0
      min_price_move_pct_from_base: 2.0
    guard:
      cooldown_ticks: 10
      max_times_per_trend: 3
      skip_if_trend_confirmed: true
      skip_if_price_extended_pct_from_base: 5.0
    sizing:
      reduce_profit_side_ratio: 0.2
      use_realized_profit_ratio_for_loss_side: 0.8
      max_add_loss_side_ratio_of_base_position: 0.3
      min_net_profit_usdt: 0.5
    risk_limits:
      max_gross_exposure_ratio: 2.0
      max_symbol_drawdown_pct: 10
    reason: profit_side_reduce_and_loss_side_restore
```

### 8.2 搬运后的仓位恢复事件

利润搬运后，Long 和 Short 仓位可能不再平衡。仓位恢复事件负责在价格回调或反弹时逐步恢复目标结构。

上涨后回调：

```text
价格从阶段高点回调
-> 亏损侧 Short 压力下降
-> 逐步补回被减掉的 Long
-> 调整 Short 到目标比例
-> Long / Short 接近基础仓位后回到 BALANCE
```

下跌后反弹：

```text
价格从阶段低点反弹
-> 亏损侧 Long 压力下降
-> 逐步补回被减掉的 Short
-> 调整 Long 到目标比例
-> Long / Short 接近基础仓位后回到 BALANCE
```

配置示例：

```yaml
events:
  position_recovery:
    enabled: true
    priority: 40
    trigger:
      pullback_pct_from_trend_extreme: 1.5
      min_position_distance_pct_from_base: 0.1
    sizing:
      restore_profit_side_ratio: 0.15
      normalize_loss_side_ratio: 0.1
      max_restore_per_tick_ratio: 0.2
    target:
      target_balance_position_distance_pct: 0.1
      target_price_distance_pct_from_base: 0.5
    reason: pullback_position_recovery
```

仓位恢复不能一次性重置，必须逐步执行，避免回调失败后再次被趋势带走。

### 8.3 单边趋势确认后的亏损仓位减仓事件

这是系统最重要的保护事件，用于防止亏损腿无限扛单。

上涨趋势确认：

```text
价格持续上涨
-> Short 是亏损腿
-> 停止给 Short 加仓
-> 按 step 逐步减少 Short
-> 最低保留基础 Short 仓位的一定比例
```

下跌趋势确认：

```text
价格持续下跌
-> Long 是亏损腿
-> 停止给 Long 加仓
-> 按 step 逐步减少 Long
-> 最低保留基础 Long 仓位的一定比例
```

配置示例：

```yaml
events:
  loss_side_reduction:
    enabled: true
    priority: 20
    trigger:
      trend_confirm_move_pct_from_base: 4.0
      reduce_step_pct: 1.0
    sizing:
      reduce_loss_side_ratio: 0.1
      min_loss_side_position_ratio_of_base: 0.2
    guard:
      block_profit_transfer_after_trend_confirmed: true
      cooldown_ticks: 5
    reason: confirmed_trend_reduce_loss_side
```

一旦趋势确认，该事件优先级高于利润搬运。

## 9. 每个 Tick 的事件优先级

每个 symbol 独立执行事件判断。

建议顺序：

```text
1. 系统风控和 emergency stop
2. 行情有效性检查
3. 单边趋势确认后的亏损仓位减仓
4. 利润搬运
5. 搬运后的仓位恢复
6. 回到平衡状态检查
7. 写入行情快照
```

原因：

1. 风控永远最高优先级。
2. 单边趋势确认后，不能继续逆势加仓。
3. 利润搬运只适合震荡或未确认单边的阶段。
4. 仓位恢复必须在搬运后和回调确认后逐步执行。

## 10. 状态模型

状态建议保持简洁，避免把每个事件都做成状态。

> 注：`base_price`、`high_since_base`、`low_since_base` 及各 `*_count_in_trend` 计数器的重锚/清零规则见 §21.1，当前实现未落地这些重置，属已知缺口。

推荐状态：

```text
BALANCE
TREND_UP
TREND_DOWN
TREND_UP_REDUCING_SHORT
TREND_DOWN_REDUCING_LONG
RECOVERING_FROM_UP
RECOVERING_FROM_DOWN
PAUSED
STOP_ONLY_REDUCE
```

状态只描述当前市场和仓位阶段。真正动作由事件驱动。

关键字段：

```text
base_price
high_since_base
low_since_base
trend_extreme_price
last_transfer_price
last_loss_reduce_price
profit_transfer_count_in_trend
loss_side_reduce_count_in_trend
recovery_count_in_trend
```

## 11. 仓位与资金原则

### 11.1 基础仓位

每个 symbol 有基础仓位：

```text
base_position_usdt
```

初始开仓：

```text
Long notional = base_position_usdt
Short notional = base_position_usdt
```

### 11.2 预算限制

每个 symbol 有独立预算：

```text
budget_usdt
```

任何时刻不得超过该 symbol 的风险限制：

```text
gross_exposure <= budget_usdt * max_gross_exposure_ratio
symbol_drawdown <= budget_usdt * max_symbol_drawdown_pct
```

### 11.3 盈亏计算

Long 未实现盈亏：

```text
(current_price - long_entry_price) * long_qty
```

Short 未实现盈亏：

```text
(short_entry_price - current_price) * short_qty
```

减仓时才产生已实现盈亏。

### 11.4 手续费和滑点

V1 默认按 taker 费率计算：

```text
fee = notional * taker_fee_rate
```

滑点：

```text
buy_fill_price = price * (1 + slippage_bps / 10000)
sell_fill_price = price * (1 - slippage_bps / 10000)
```

利润搬运必须使用扣除费用和滑点后的净利润。

## 12. 风控设计

> 注：当前实现的风控只做「检测」，未做「阻断」，且缺少终极止损/拆对冲出口，详见 §21.3、§21.4。

风控按四层执行：

```text
Global 全局
User 用户
Account 交易账户
Strategy 策略实例
Symbol 单币种
```

### 12.1 Global 风控

1. 全局 emergency stop。
2. 行情源异常。
3. 数据库异常。
4. 系统连续错误。

### 12.2 User 风控

1. 用户整体暂停。
2. 用户总回撤限制。
3. 用户所有策略只允许减仓。

### 12.3 Account 风控

1. API 认证异常。
2. API 权限不足。
3. Hedge Mode 未开启。
4. 账户权益异常。
5. 连续下单失败。

### 12.4 Strategy 风控

1. 策略最大总回撤。
2. 策略最大 gross exposure。
3. 策略运行状态暂停。
4. live_small 未确认禁止运行。

### 12.5 Symbol 风控

1. 单币种最大亏损。
2. 单币种最大 gross exposure。
3. 单币种连续失败暂停。
4. 单币种价格异常暂停。
5. 单币种只允许减仓。

### 12.6 Emergency Stop 文件机制

建议支持多级 stop 文件：

```text
runtime/stop.global
runtime/stop.user.{user_id}
runtime/stop.account.{exchange_account_id}
runtime/stop.strategy.{strategy_instance_id}
runtime/stop.symbol.{strategy_instance_id}.{symbol}
```

检测到 stop 后：

1. 禁止新开仓。
2. 禁止增加亏损侧仓位。
3. 只允许减仓和平仓。
4. 写入风控事件。

## 13. 系统架构

推荐模块结构：

```text
dynamic-dual-grid/
  config.yaml
  requirements.txt
  README.md
  backend/
    main.py
    src/orbit/
      api/
      application/
      domain/
      infrastructure/
      ports/
    scripts/
    sql/
    tests/
  frontend/
    index.html
    package.json
    vite.config.js
    src/
      main.js
      App.vue
      api/
      components/
      core/
      domain/
      pages/
      stores/
      styles/
  config/
  docs/
  var/
```

核心依赖方向：

```text
strategy -> domain
execution -> exchange
accounting -> domain
risk -> domain
storage -> domain
runner -> strategy + risk + execution + storage + reporting
```

策略模块不直接访问数据库，不直接调用交易所。

## 14. MySQL 数据库设计

建议使用 MySQL 8.0+。

金额、价格、数量字段使用 `DECIMAL`，不使用浮点类型。

推荐精度：

```text
price: DECIMAL(28, 12)
qty: DECIMAL(28, 12)
notional/usdt/pnl/fee: DECIMAL(28, 8)
rate/pct: DECIMAL(18, 10)
```

### 14.1 users

```sql
CREATE TABLE users (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  external_id VARCHAR(64) NOT NULL UNIQUE,
  name VARCHAR(128) NOT NULL,
  email VARCHAR(255) NULL,
  role VARCHAR(32) NOT NULL DEFAULT 'user',
  status VARCHAR(32) NOT NULL DEFAULT 'active',
  created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  INDEX idx_users_role (role),
  INDEX idx_users_status (status)
);
```

### 14.2 exchange_accounts

```sql
CREATE TABLE exchange_accounts (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  external_id VARCHAR(64) NOT NULL UNIQUE,
  user_id BIGINT NOT NULL,
  exchange_name VARCHAR(64) NOT NULL,
  market_type VARCHAR(64) NOT NULL,
  account_label VARCHAR(128) NOT NULL,
  testnet BOOLEAN NOT NULL DEFAULT TRUE,
  dry_run BOOLEAN NOT NULL DEFAULT TRUE,
  api_key_ref VARCHAR(255) NULL,
  api_key_fingerprint VARCHAR(64) NULL,
  secret_ref VARCHAR(255) NULL,
  permissions_json JSON NULL,
  hedge_mode_enabled BOOLEAN NOT NULL DEFAULT FALSE,
  status VARCHAR(32) NOT NULL DEFAULT 'active',
  created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  CONSTRAINT fk_exchange_accounts_user FOREIGN KEY (user_id) REFERENCES users(id),
  INDEX idx_exchange_accounts_user (user_id),
  INDEX idx_exchange_accounts_status (status)
);
```

### 14.3 strategy_instances

```sql
CREATE TABLE strategy_instances (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  external_id VARCHAR(64) NOT NULL UNIQUE,
  user_id BIGINT NOT NULL,
  exchange_account_id BIGINT NOT NULL,
  strategy_name VARCHAR(128) NOT NULL,
  strategy_version VARCHAR(64) NOT NULL,
  mode VARCHAR(32) NOT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'created',
  config_version VARCHAR(64) NOT NULL,
  config_json JSON NOT NULL,
  live_confirm VARCHAR(128) NULL,
  started_at TIMESTAMP(6) NULL,
  stopped_at TIMESTAMP(6) NULL,
  created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  CONSTRAINT fk_strategy_instances_user FOREIGN KEY (user_id) REFERENCES users(id),
  CONSTRAINT fk_strategy_instances_account FOREIGN KEY (exchange_account_id) REFERENCES exchange_accounts(id),
  INDEX idx_strategy_instances_user (user_id),
  INDEX idx_strategy_instances_account (exchange_account_id),
  INDEX idx_strategy_instances_status (status)
);
```

### 14.4 symbol_allocations

```sql
CREATE TABLE symbol_allocations (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  strategy_instance_id BIGINT NOT NULL,
  symbol VARCHAR(32) NOT NULL,
  budget_usdt DECIMAL(28, 8) NOT NULL,
  base_position_usdt DECIMAL(28, 8) NOT NULL,
  max_symbol_drawdown_pct DECIMAL(18, 10) NOT NULL,
  max_gross_exposure_ratio DECIMAL(18, 10) NOT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'active',
  created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  CONSTRAINT fk_symbol_allocations_strategy FOREIGN KEY (strategy_instance_id) REFERENCES strategy_instances(id),
  UNIQUE KEY uk_symbol_allocations_strategy_symbol (strategy_instance_id, symbol),
  INDEX idx_symbol_allocations_status (status)
);
```

### 14.5 symbol_states

```sql
CREATE TABLE symbol_states (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  strategy_instance_id BIGINT NOT NULL,
  symbol VARCHAR(32) NOT NULL,
  state VARCHAR(64) NOT NULL,
  base_price DECIMAL(28, 12) NOT NULL,
  high_since_base DECIMAL(28, 12) NULL,
  low_since_base DECIMAL(28, 12) NULL,
  trend_extreme_price DECIMAL(28, 12) NULL,
  last_price DECIMAL(28, 12) NULL,
  long_qty DECIMAL(28, 12) NOT NULL DEFAULT 0,
  short_qty DECIMAL(28, 12) NOT NULL DEFAULT 0,
  long_entry_price DECIMAL(28, 12) NULL,
  short_entry_price DECIMAL(28, 12) NULL,
  realized_pnl DECIMAL(28, 8) NOT NULL DEFAULT 0,
  long_unrealized_pnl DECIMAL(28, 8) NOT NULL DEFAULT 0,
  short_unrealized_pnl DECIMAL(28, 8) NOT NULL DEFAULT 0,
  fee_total DECIMAL(28, 8) NOT NULL DEFAULT 0,
  slippage_total DECIMAL(28, 8) NOT NULL DEFAULT 0,
  funding_total DECIMAL(28, 8) NOT NULL DEFAULT 0,
  profit_transfer_count_in_trend INT NOT NULL DEFAULT 0,
  loss_side_reduce_count_in_trend INT NOT NULL DEFAULT 0,
  recovery_count_in_trend INT NOT NULL DEFAULT 0,
  last_transfer_price DECIMAL(28, 12) NULL,
  last_loss_reduce_price DECIMAL(28, 12) NULL,
  last_event_at TIMESTAMP(6) NULL,
  created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  CONSTRAINT fk_symbol_states_strategy FOREIGN KEY (strategy_instance_id) REFERENCES strategy_instances(id),
  UNIQUE KEY uk_symbol_states_strategy_symbol (strategy_instance_id, symbol),
  INDEX idx_symbol_states_state (state)
);
```

### 14.6 market_snapshots

```sql
CREATE TABLE market_snapshots (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  timestamp TIMESTAMP(6) NOT NULL,
  user_id BIGINT NOT NULL,
  exchange_account_id BIGINT NOT NULL,
  strategy_instance_id BIGINT NOT NULL,
  symbol VARCHAR(32) NOT NULL,
  price DECIMAL(28, 12) NOT NULL,
  mark_price DECIMAL(28, 12) NULL,
  state VARCHAR(64) NOT NULL,
  high_since_base DECIMAL(28, 12) NULL,
  low_since_base DECIMAL(28, 12) NULL,
  long_qty DECIMAL(28, 12) NOT NULL,
  short_qty DECIMAL(28, 12) NOT NULL,
  long_entry_price DECIMAL(28, 12) NULL,
  short_entry_price DECIMAL(28, 12) NULL,
  long_unrealized_pnl DECIMAL(28, 8) NOT NULL,
  short_unrealized_pnl DECIMAL(28, 8) NOT NULL,
  realized_pnl DECIMAL(28, 8) NOT NULL,
  net_exposure DECIMAL(28, 8) NOT NULL,
  gross_exposure DECIMAL(28, 8) NOT NULL,
  free_cash DECIMAL(28, 8) NULL,
  equity DECIMAL(28, 8) NULL,
  created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  INDEX idx_market_snapshots_strategy_symbol_time (strategy_instance_id, symbol, timestamp),
  INDEX idx_market_snapshots_user_time (user_id, timestamp)
);
```

### 14.7 strategy_events

`strategy_events` 记录策略父事件，例如一次利润搬运。

```sql
CREATE TABLE strategy_events (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  event_uid VARCHAR(64) NOT NULL UNIQUE,
  parent_event_id BIGINT NULL,
  timestamp TIMESTAMP(6) NOT NULL,
  user_id BIGINT NOT NULL,
  exchange_account_id BIGINT NOT NULL,
  strategy_instance_id BIGINT NOT NULL,
  symbol VARCHAR(32) NOT NULL,
  event_type VARCHAR(64) NOT NULL,
  direction VARCHAR(16) NULL,
  state_before VARCHAR(64) NOT NULL,
  state_after VARCHAR(64) NULL,
  trigger_json JSON NULL,
  guard_json JSON NULL,
  sizing_json JSON NULL,
  risk_check_json JSON NULL,
  action_plan_json JSON NULL,
  realized_pnl DECIMAL(28, 8) NOT NULL DEFAULT 0,
  fee_total DECIMAL(28, 8) NOT NULL DEFAULT 0,
  slippage_total DECIMAL(28, 8) NOT NULL DEFAULT 0,
  funding_fee DECIMAL(28, 8) NOT NULL DEFAULT 0,
  reason VARCHAR(255) NOT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'planned',
  error_message TEXT NULL,
  created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  INDEX idx_strategy_events_strategy_symbol_time (strategy_instance_id, symbol, timestamp),
  INDEX idx_strategy_events_type (event_type),
  INDEX idx_strategy_events_parent (parent_event_id)
);
```

### 14.8 trade_events

`trade_events` 记录具体下单或模拟成交动作。

```sql
CREATE TABLE trade_events (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  trade_uid VARCHAR(64) NOT NULL UNIQUE,
  strategy_event_id BIGINT NULL,
  timestamp TIMESTAMP(6) NOT NULL,
  user_id BIGINT NOT NULL,
  exchange_account_id BIGINT NOT NULL,
  strategy_instance_id BIGINT NOT NULL,
  symbol VARCHAR(32) NOT NULL,
  event_type VARCHAR(64) NOT NULL,
  side VARCHAR(16) NOT NULL,
  position_side VARCHAR(16) NOT NULL,
  action VARCHAR(32) NOT NULL,
  order_type VARCHAR(32) NULL,
  price DECIMAL(28, 12) NOT NULL,
  fill_price DECIMAL(28, 12) NOT NULL,
  qty DECIMAL(28, 12) NOT NULL,
  notional DECIMAL(28, 8) NOT NULL,
  fee DECIMAL(28, 8) NOT NULL DEFAULT 0,
  slippage_cost DECIMAL(28, 8) NOT NULL DEFAULT 0,
  funding_fee DECIMAL(28, 8) NOT NULL DEFAULT 0,
  realized_pnl DECIMAL(28, 8) NOT NULL DEFAULT 0,
  unrealized_pnl_before DECIMAL(28, 8) NOT NULL DEFAULT 0,
  unrealized_pnl_after DECIMAL(28, 8) NOT NULL DEFAULT 0,
  state_before VARCHAR(64) NOT NULL,
  state_after VARCHAR(64) NULL,
  exchange_order_id VARCHAR(128) NULL,
  client_order_id VARCHAR(128) NULL,
  reason VARCHAR(255) NOT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'filled',
  error_message TEXT NULL,
  created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  CONSTRAINT fk_trade_events_strategy_event FOREIGN KEY (strategy_event_id) REFERENCES strategy_events(id),
  INDEX idx_trade_events_strategy_symbol_time (strategy_instance_id, symbol, timestamp),
  INDEX idx_trade_events_user_time (user_id, timestamp),
  INDEX idx_trade_events_strategy_event (strategy_event_id)
);
```

### 14.9 daily_reports

```sql
CREATE TABLE daily_reports (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  report_date DATE NOT NULL,
  user_id BIGINT NOT NULL,
  exchange_account_id BIGINT NOT NULL,
  strategy_instance_id BIGINT NOT NULL,
  symbol VARCHAR(32) NULL,
  start_equity DECIMAL(28, 8) NULL,
  end_equity DECIMAL(28, 8) NULL,
  daily_pnl DECIMAL(28, 8) NOT NULL DEFAULT 0,
  daily_pnl_pct DECIMAL(18, 10) NOT NULL DEFAULT 0,
  gross_profit DECIMAL(28, 8) NOT NULL DEFAULT 0,
  gross_loss DECIMAL(28, 8) NOT NULL DEFAULT 0,
  fee_total DECIMAL(28, 8) NOT NULL DEFAULT 0,
  slippage_total DECIMAL(28, 8) NOT NULL DEFAULT 0,
  funding_total DECIMAL(28, 8) NOT NULL DEFAULT 0,
  net_pnl DECIMAL(28, 8) NOT NULL DEFAULT 0,
  max_drawdown DECIMAL(28, 8) NOT NULL DEFAULT 0,
  long_max_qty DECIMAL(28, 12) NOT NULL DEFAULT 0,
  short_max_qty DECIMAL(28, 12) NOT NULL DEFAULT 0,
  max_net_exposure DECIMAL(28, 8) NOT NULL DEFAULT 0,
  max_gross_exposure DECIMAL(28, 8) NOT NULL DEFAULT 0,
  profit_transfer_count INT NOT NULL DEFAULT 0,
  loss_side_reduce_count INT NOT NULL DEFAULT 0,
  position_recovery_count INT NOT NULL DEFAULT 0,
  rebalance_count INT NOT NULL DEFAULT 0,
  trade_count INT NOT NULL DEFAULT 0,
  markdown_path VARCHAR(512) NULL,
  created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  UNIQUE KEY uk_daily_reports_scope (report_date, strategy_instance_id, symbol),
  INDEX idx_daily_reports_user_date (user_id, report_date)
);
```

### 14.10 risk_events

```sql
CREATE TABLE risk_events (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  timestamp TIMESTAMP(6) NOT NULL,
  user_id BIGINT NULL,
  exchange_account_id BIGINT NULL,
  strategy_instance_id BIGINT NULL,
  symbol VARCHAR(32) NULL,
  risk_level VARCHAR(32) NOT NULL,
  risk_type VARCHAR(64) NOT NULL,
  action_taken VARCHAR(64) NOT NULL,
  message TEXT NOT NULL,
  context_json JSON NULL,
  created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  INDEX idx_risk_events_time (timestamp),
  INDEX idx_risk_events_strategy_symbol (strategy_instance_id, symbol)
);
```

### 14.11 admin_audit_logs

```sql
CREATE TABLE admin_audit_logs (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  admin_user_id BIGINT NOT NULL,
  action_type VARCHAR(64) NOT NULL,
  target_user_id BIGINT NULL,
  target_account_id BIGINT NULL,
  target_strategy_id BIGINT NULL,
  target_symbol VARCHAR(32) NULL,
  before_value_json JSON NULL,
  after_value_json JSON NULL,
  reason VARCHAR(255) NOT NULL,
  created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  CONSTRAINT fk_admin_audit_logs_admin FOREIGN KEY (admin_user_id) REFERENCES users(id),
  INDEX idx_admin_audit_logs_admin_time (admin_user_id, created_at),
  INDEX idx_admin_audit_logs_target_user (target_user_id)
);
```

## 15. 配置文件设计

V1 仍可使用单个 `config.yaml`，但结构按多用户、多账户、多策略设计。

```yaml
users:
  - id: admin_001
    name: admin
    role: admin

  - id: user_001
    name: local_user
    role: user

exchange_accounts:
  - id: binance_dry_run_001
    user_id: user_001
    exchange: binance
    market_type: futures
    testnet: true
    dry_run: true
    hedge_mode_required: true
    account_label: binance dry run

strategy_instances:
  - id: orbit_v1_local_test
    user_id: user_001
    exchange_account_id: binance_dry_run_001
    strategy_name: dynamic_dual_grid
    strategy_version: v1
    mode: dry_run
    status: running
    runtime:
      tick_interval_seconds: 60
      live_confirm: ""
    symbols:
      - BTCUSDT
      - ETHUSDT
      - SOLUSDT
    symbol_budget_usdt:
      BTCUSDT: 100
      ETHUSDT: 100
      SOLUSDT: 100
    strategy:
      base_position_usdt: 20
      costs:
        taker_fee_rate: 0.0005
        maker_fee_rate: 0.0002
        slippage_bps: 2
      risk:
        max_symbol_drawdown_pct: 10
        max_total_drawdown_pct: 20
        max_gross_exposure_ratio: 2.0
        emergency_stop: true
      events:
        loss_side_reduction:
          enabled: true
          priority: 20
          trigger:
            trend_confirm_move_pct_from_base: 4.0
            reduce_step_pct: 1.0
          sizing:
            reduce_loss_side_ratio: 0.1
            min_loss_side_position_ratio_of_base: 0.2
          guard:
            block_profit_transfer_after_trend_confirmed: true
            cooldown_ticks: 5

        profit_transfer:
          enabled: true
          priority: 30
          trigger:
            min_profit_pct_of_symbol_budget: 3.0
            min_price_move_pct_from_base: 2.0
          guard:
            cooldown_ticks: 10
            max_times_per_trend: 3
            skip_if_trend_confirmed: true
            skip_if_price_extended_pct_from_base: 5.0
          sizing:
            reduce_profit_side_ratio: 0.2
            use_realized_profit_ratio_for_loss_side: 0.8
            max_add_loss_side_ratio_of_base_position: 0.3
            min_net_profit_usdt: 0.5

        position_recovery:
          enabled: true
          priority: 40
          trigger:
            pullback_pct_from_trend_extreme: 1.5
            min_position_distance_pct_from_base: 0.1
          sizing:
            restore_profit_side_ratio: 0.15
            normalize_loss_side_ratio: 0.1
            max_restore_per_tick_ratio: 0.2
          target:
            target_balance_position_distance_pct: 0.1
            target_price_distance_pct_from_base: 0.5
```

实盘模式必须增加确认：

```yaml
mode: live_small
runtime:
  live_confirm: "I_UNDERSTAND_THE_RISK"
```

没有确认字符串时，系统禁止实盘下单。

## 16. 运行流程

单个 tick 流程：

```text
1. 读取配置和策略实例
2. 检查用户、账户、策略、symbol 状态
3. 检查 emergency stop
4. 获取市场价格
5. 校验行情数据
6. 读取 symbol_state
7. 计算当前 PnL、敞口、费用
8. 写入 market_snapshot
9. 运行事件引擎
10. 生成 action_plan
11. 风控检查 action_plan
12. dry_run 模拟成交或实盘下单
13. 写入 strategy_events 和 trade_events
14. 更新 symbol_state
15. 记录风险事件和异常
```

## 17. 报表设计

每日生成 Markdown 报告：

```text
reports/{strategy_instance_id}/YYYY-MM-DD.md
```

图表路径：

```text
reports/{strategy_instance_id}/charts/
```

报告内容：

1. 总账户权益变化。
2. 每个用户和账户的策略状态。
3. 每个 symbol 的收益。
4. Long / Short 仓位变化。
5. 净敞口和总敞口变化。
6. 利润搬运次数和金额。
7. 仓位恢复次数。
8. 亏损腿减仓次数。
9. 手续费、滑点、Funding。
10. 最大回撤。
11. 风控事件。
12. 关键策略事件列表。
13. 异常日志摘要。

必须输出的图：

1. 总权益曲线。
2. 每个 symbol 权益曲线。
3. Long / Short 仓位曲线。
4. 净敞口曲线。
5. 总敞口曲线。
6. 累计手续费曲线。
7. Profit Transfer 累计曲线。
8. 每日 PnL 柱状图。

## 18. 开发优先级

### P0: Dry Run 核心闭环

1. MySQL 初始化和迁移。
2. 配置读取和校验。
3. 用户、账户、管理员基础模型。
4. 策略实例和 symbol allocation 初始化。
5. symbol_state 持久化。
6. MockExchange 和 dry_run 成交模拟。
7. 手续费和滑点计算。
8. PnL 计算。
9. 利润搬运事件。
10. 仓位恢复事件。
11. 亏损腿减仓事件。
12. 风控引擎。
13. strategy_events 和 trade_events 记录。
14. market_snapshots 记录。
15. Markdown 日报。
16. 基础图表。

### P1: Binance Testnet

1. Binance Futures testnet 行情接入。
2. Binance Futures testnet 下单。
3. Hedge Mode 检查。
4. API 异常和订单状态确认。
5. Funding 接口接入。
6. testnet 连续运行验证。

### P2: Live Small

1. live_confirm 强制确认。
2. 小仓位实盘。
3. 实盘订单幂等处理。
4. 下单失败恢复。
5. 管理员后台页面。
6. 用户账户页面。

### P3: 策略增强

1. 参数回测。
2. 趋势强度识别。
3. 前高前低结构识别。
4. 单 symbol 独立参数。
5. 更细粒度风控。

## 19. 验收标准

V1 dry_run 运行一天后必须能看到：

1. 所有用户、账户、策略实例。
2. 管理员可以查看所有用户账户情况。
3. 每个 symbol 当前状态。
4. Long / Short 当前仓位。
5. 当前浮盈浮亏。
6. 已实现盈亏。
7. 手续费累计。
8. 滑点累计。
9. Funding 字段和日志预留。
10. 利润搬运事件及其子交易事件。
11. 仓位恢复事件。
12. 亏损腿减仓事件。
13. 所有事件都有 reason。
14. 所有仓位变化都能从 trade_events 追溯。
15. 总权益曲线。
16. 每个 symbol 收益曲线。
17. 每日 Markdown 报告。
18. 异常日志。
19. 风控事件。
20. 可通过配置切换 dry_run / live_small，但 live_small 必须确认后才允许。

## 20. 核心结论

Dynamic Dual Grid V1 的正确实现方式不是把策略写成固定流程，而是把策略设计为可配置事件系统。

策略核心可以概括为：

```text
震荡或未确认单边时：
  盈利腿减仓实现利润
  使用实现后的利润额度恢复亏损腿

价格回调或反弹时：
  逐步恢复仓位结构
  让 Long / Short 回到目标平衡

单边趋势确认时：
  停止逆势加仓
  逐步削减亏损腿
  保留最低仓位观察市场
```

外围系统必须围绕这个核心服务：

1. 用户和账户用于隔离资金和权限。
2. 管理员用于查看和暂停风险。
3. MySQL 用于持久化状态、事件、报表和审计。
4. 风控用于确保任何动作都不能突破预算和敞口限制。
5. 报表用于复盘每一次策略动作是否合理。

V1 成功的标准不是盈利，而是每一次利润搬运、仓位恢复和亏损腿减仓都能被解释、被配置、被追溯、被复盘。

## 21. V1 已知策略逻辑缺口与待补设计

本节记录在当前引擎实现（`backend/src/orbit/domain/strategy/engine.py`）与前面章节（§8、§10、§11、§12）比对后发现的逻辑缺口，以及需要补齐的设计规则。这些是策略层面必须先在设计上定义清楚、再落地代码的问题，优先级从高到低排列。

### 21.1 趋势生命周期与状态重置（最高优先级，§8、§10 补充）

问题：

1. `base_price`、`high_since_base`、`low_since_base` 在 symbol 初始化后从不更新。
2. 所有触发判断都是「相对初始 `base_price` 的百分比位移」。价格一旦单边走过 `trend_confirm_move_pct_from_base`，`move_pct` 会永久 ≥ 阈值，symbol 会**永久锁定在 `TREND_UP_REDUCING_SHORT` / `TREND_DOWN_REDUCING_LONG`**，再也回不到 `BALANCE` 触发利润搬运。
3. `profit_transfer_count_in_trend`、`loss_side_reduce_count_in_trend`、`recovery_count_in_trend` 命名含「in_trend」，但从不清零，导致 `max_times_per_trend` 退化为**整个生命周期的总次数上限**，而非每段趋势上限。

需要补的设计规则：

1. 明确定义「一段趋势结束 / 回到 BALANCE」的判定条件（例如：价格回到 `base` 附近某带宽内，且 Long/Short 都回到 base 附近）。
2. 趋势结束时执行**状态重锚**：`base_price = 当前价`、重置 `high_since_base` / `low_since_base` / `trend_extreme_price`、清零三个 `*_count_in_trend` 计数器。
3. §10 的关键字段清单需要补上「何时重锚、何时清零」的显式规则，否则字段语义与实现不一致。

### 21.2 被削减的亏损腿缺少重建规则（§8.2 补充）

问题：

1. 上涨趋势中 `loss_side_reduction` 会把 Short 削减到 `min_loss_side_position_ratio_of_base * base` 以下。
2. `position_recovery` 的回调分支只在 `loss_side_qty > base` 时才「归一化减仓」，**没有任何分支把被砍到 base 以下的亏损腿补回**。
3. 后果：一波上涨后回调，结构变为 Long≈base、Short 很小；若价格继续回落，几乎没有 Short 对冲，双向结构失效。

需要补的设计规则：

1. 在 §8.2 增加「趋势结束后重建亏损腿到 base」的恢复规则，与 21.1 的重锚一并触发。
2. 明确重建的节奏（逐步 vs 一次），避免趋势假结束时被再次带走。

### 21.3 风控只检测、不阻断（§12 补充）

原问题：

1. 风控 `check_risk` 会产出 `MAX_GROSS_EXPOSURE(ONLY_REDUCE)`、`MAX_SYMBOL_DRAWDOWN(PAUSE_SYMBOL)` 等事件，但事件层（利润搬运、仓位恢复）不读取风控结果，也没有对应 guard。
2. 目前唯一真实生效的硬约束是加仓时的 gross 上限检查。单币种最大回撤触发后，加仓类动作仍可执行，`PAUSE_SYMBOL` 并不会真的暂停。

需要补的设计规则：

1. 明确风控结果到动作的映射：`ONLY_REDUCE` 时禁止所有 ADD 类动作；`STOPPED` 时整个 symbol 终止普通策略事件，只允许终极止损拆对冲动作。
2. §12 的四层风控要区分「检测」与「阻断」两个阶段，落地时阻断必须作为事件引擎前置 guard。

工程状态（2026-07-13）：`domain/risk/guards.py` 已成为 `plan_only` 计划生成和 dry-run 引擎的共用动作前置风控，覆盖 gross `ONLY_REDUCE`、计划模式/加仓开关、symbol 级 `STOPPED`、组合级回撤 `GLOBAL_STOP` 与 C7 自融资账本；计划生成同时按 `snapshot_max_age_seconds` 拦截陈旧账户快照。剩余项是 STOP 后人工复核恢复流程及这些状态的完整 UI 投影。

### 21.4 缺少终极止损 / 拆对冲出口（§12.5 补充）

问题：亏损腿只能减到 `min_loss_side_position_ratio_of_base` 就停住扛单，没有「认输全平」的档位。强单边行情里这条腿会长期在地板价位流血。

需要补的设计规则：在 §12.5 增加 symbol 级硬止损：当单币种回撤触及上限时，**拆对冲全平（long / short 均减到 0）而不是仅暂停**，并写入风控事件。

工程状态（2026-07-09）：dry-run 引擎已实现 `STOPPED_UNWIND`，计划生成已实现 `MAX_SYMBOL_DRAWDOWN_STOP` 只读执行计划。

### 21.5 趋势确认应引入斜率/时间维度（§8.3 补充）

原问题：趋势确认只看「相对固定 base 的价位位移」，无法区分慢速阴跌 4% 和数分钟暴跌 4%。叠加 21.1 的陈旧 base，系统会长期把普通漂移误判为趋势。

需要补的设计规则：在 §8.3 的 `trigger` 中增加时间/斜率维度（例如 N 个 tick 内的位移，或用 ATR 归一化的位移），作为趋势确认的附加条件。

工程状态（2026-07-13）：已增加最近 `k` 个 close tick 的位移速度门，默认阈值为 0 时保持原 level + 连续 tick 行为；首轮训练窗不支持翻默认，后续按周期独立标定。

### 21.6 利润搬运的口径澄清（§8.1 补充）

需要在 §8.1 明确两点，避免实盘对接误解：

1. 「用实现后的利润额度恢复亏损腿」是**仓位定量口径（sizing 启发式）**，不是账本资金划转；合约加仓占用的是保证金，已实现利润不会被「花掉」。
2. 新 Δ* 动作模型已删除 `restore_loss_side_only_to_base` 布尔语义。减盈利腿按目标净敞口独立生成，加亏损腿只在剩余目标差额与利润预算允许时追加；亏损腿已达或超过 base 不会阻止减盈利腿止盈。

### 21.7 Funding 在失衡对冲中的方向性（§11 补充）

当前 `funding_fee` 恒为 0（P1 才接入）。设计上需在 §11 说明：双腿平衡时 funding 近似中性，但趋势减仓造成 Long/Short 失衡后，funding 会变成**方向性的持续成本/收益**，不能按可忽略处理。

### 21.8 手续费 churn 风险（§11.4 补充）

每次利润搬运包含减盈利腿与可选加亏损腿；base 小、阈值低时高频小额搬运容易被费用吃光。当前可用 `require_add_leg_roundtrip_coverage` 要求减腿净利润同时覆盖加仓腿预估往返成本，默认关闭；首轮训练窗未出现边际样本，后续在成本或最低利润参数变化时重新标定。

## 22. 实现现状与文档差异说明

本节记录当前实现与本文档、原始需求文档之间的差异，供后续对接和文档校准使用。

### 22.1 配置格式：JSON 而非 YAML

§13、§15 使用 `config.yaml`（YAML）描述配置，但实际实现采用 JSON：`config/config.sample.json`、`config.local.json`。后续按 JSON 对接，§15 的 YAML 示例仅作字段结构参考。

### 22.2 模块结构：已切换到 orbit 分层包

V1 已从旧扁平包 `backend/src/ddg/` 切换为唯一后端包 `backend/src/orbit/`，并按 `api`、`application`、`domain`、`infrastructure` 组织目录。当前仍只是第一轮骨架切换：`AppState` 巨类、事务化 repository、`EventRule`、`RiskGuard`、`CredentialVault` 等深层抽象仍需继续拆实。

### 22.3 第一阶段范围：plan_only 只读优先

§18 的 P0 是完整 dry_run 闭环（MockExchange 模拟成交、事件执行、accounting、日报、图表）。当前第一阶段先收窄为 `plan_only` 只读闭环：接入 Binance 真实持仓、生成 `plan_only` 执行计划、人工查看/确认/导出，dry_run 模拟成交顺延。以 `PROJECT_PROGRESS.md` 的「当前目标」为准。

### 22.4 凭证加密平台限制

Binance API Key/Secret 的本地加密使用 Windows DPAPI（`backend/src/orbit/infrastructure/exchange/binance.py`），**仅在 Windows 可用**。当前开发/部署环境为 Linux，保存加密 Secret 会抛 `CredentialError`，对应单测在非 Windows 上被跳过。Linux 环境需另做跨平台凭证后端，或改用环境变量引用（`env:` 前缀）模式。

### 22.5 运维脚本平台限制

`backend/scripts/` 下仅有 `.cmd` / `.ps1`（Windows），README 启动命令为 PowerShell + `C:\Users\...` 路径；当前 Linux 环境无对应 bash 脚本，且未安装 `node`（进度文档中的 `node --check frontend/src/main.js` 验证在 Linux 上无法复现）。需要补一套 Linux/bash 启动与校验说明。
