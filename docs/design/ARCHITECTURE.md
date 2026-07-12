# Orbit 技术架构说明

最后更新：2026-07-10

本文是项目的工程边界说明书，不是愿景稿。它回答四个问题：

1. 系统由哪些子系统组成。
2. 每一层负责什么、禁止做什么。
3. 代码依赖只能往哪个方向走。
4. 当前哪些代码不符合目标架构，必须被拆掉。

## 1. 架构结论

Orbit 第一阶段只做一条实盘测试闭环：

管理员维护业务用户与交易账户 -> 保存账户 API 凭证 -> 同步 Binance 合约真实数据 -> 校验 Hedge Mode -> 读取余额和持仓 -> 生成 `plan_only` 执行计划 -> 风控审计 -> 人工确认或导出计划。

业务定位固定如下：

- 管理员是系统使用者和操作者。
- 业务用户不是管理员，业务用户只是交易账户归属方。
- API Key / Secret 跟随交易账户，不跟随管理员。
- 策略由平台维护，业务用户不设计、不维护、不运行策略。
- 用户账户页只放“业务用户”和“交易账户”，不放策略配置。

技术架构固定如下：

```text
Web Admin Console
        |
        v
API Layer
        |
        v
Application Use Cases
        |
        +--------> Domain Rules
        |
        +--------> Ports
                       ^
                       |
                Infrastructure Adapters
```

这意味着：API 不写业务规则，Domain 不做 I/O，Infrastructure 不反向污染业务语义。

## 2. 子系统边界

### 2.1 身份与账户

职责：

- 管理员、业务用户、交易账户的建模。
- 管理员查看全量业务用户与账户。
- 业务用户只能查看自己名下账户。
- 账户新增、编辑、禁用、归属变更。

归属代码：

- `application/accounts.py`
- `application/permissions.py`
- `domain/accounts/`
- `ports/repositories.py`

禁止：

- 不在账户页维护策略实例。
- 不把管理员当作业务用户。

### 2.2 凭证与交易所同步

职责：

- 保存 API Key / Secret 的引用和指纹。
- 通过 `CredentialVault` 处理加密、解密或环境变量引用。
- 通过 `ExchangeGateway` 同步账户信息、持仓、Hedge Mode。
- 把同步错误返回到账户行内。

归属代码：

- `application/credentials.py`
- `application/sync.py`
- `application/ports/credential_vault.py`
- `application/ports/account_connection_inspector.py`
- `ports/exchange.py`
- `infrastructure/exchange/binance.py`
- `infrastructure/credentials/`

禁止：

- 不在页面或 API 响应中回显 Secret 明文。
- 不让 Binance SDK 细节进入应用层和领域层。

### 2.3 策略配置

职责：

- 平台维护 Dynamic Dual Grid V1 策略。
- 管理三类事件参数：利润搬运、仓位恢复、亏损腿减仓。
- 管理账户挂载和运行配置。

归属代码：

- `application/strategies.py`
- `domain/strategy/`
- `domain/strategy/rules/`

禁止：

- 不把策略配置塞进“用户与账户”页面。
- 不让业务用户决定系统策略结构。

### 2.4 执行计划与风控

职责：

- 基于真实 Binance 快照生成只读执行计划。
- 执行 `plan_only` 风控检查。
- 记录人工确认和导出审计。
- 后续从 `plan_only` 扩展到 `paper`、`live` 时，仍复用同一套规则和 guard。

策略数学模型：

- `docs/design/STRATEGY_LOGIC.md` 负责定义净敞口 Δ、趋势生命周期状态机、vol 归一化触发、参数一致性约束和仿真验收规范。
- 本文只规定工程落点：策略模型落到 `EventRule`、`RiskGuard`、`PlanningPolicy` 等领域对象，不直接塞回 `AppState` 或 HTTP handler。

归属代码：

- `application/execution_plans.py`
- `application/risk.py`
- `domain/planning/`
- `domain/strategy/rules/`
- `domain/risk/`

已开始落地：

- 执行计划生成、确认、导出用例已从 `AppState` 抽到 `backend/src/orbit/application/execution_plans.py`。
- `plan_only` 计划生成已开始复用 `backend/src/orbit/domain/strategy/exposure.py` 的净敞口 Δ / 目标净敞口 Δ* 内核。
- `backend/src/orbit/domain/planning/plans.py` 不再使用旧的三段式计划函数，而是先计算 Δ*，再按差值生成计划动作。
- `backend/src/orbit/domain/strategy/engine.py` 的 dry_run 模拟事件也已切到同一套 Δ* 内核，不再调用旧的 `try_profit_transfer` / `try_position_recovery` / `try_loss_side_reduction` 三段式分支。

禁止：

- 不在 HTTP handler 里写计划生成逻辑。
- 不让风控只生成日志却不阻断动作。

### 2.5 审计与报表

职责：

- 管理员写操作统一落审计。
- 执行计划确认、导出、Binance 同步、配置修改都必须可追溯。
- 日报只消费已落库的快照和事件，不反向修改策略状态。

归属代码：

- `application/audit.py`
- `application/reporting.py`
- `infrastructure/reporting/`

禁止：

- 不在各个 handler 中随手拼审计结构。
- 不让报表生成影响交易状态。

### 2.6 运行时与调度

职责：

- 后台 tick、同步、日报任务由 scheduler 管。
- HTTP 请求只触发用例，不承载长期循环。
- 第一阶段真实账户只读，默认不自动下单。

归属代码：

- `application/runtime.py`
- `ports/clock.py`
- `ports/scheduler.py`
- `infrastructure/scheduler/`

禁止：

- 不把后台循环塞在状态容器里无限扩展。

## 3. 分层规则

### API Layer

允许做：

- HTTP 路由。
- 请求解析。
- 当前用户解析。
- 调用应用服务。
- 响应 DTO 序列化。

禁止做：

- 直接访问数据库。
- 直接访问 Binance。
- 直接生成策略或执行计划。
- 直接写审计细节。

目标文件：

- `api/app.py`
- `api/deps.py`
- `api/routers/*.py`
- `api/schemas/*.py`

### Application Layer

允许做：

- 一个用例一个 service。
- 编排权限、事务、领域规则、端口调用。
- 生成审计事件。
- 决定错误码和业务错误。

禁止做：

- 直接拼 SQL。
- 直接依赖 Binance SDK。
- 存储密钥明文。
- 写页面展示逻辑。

目标文件：

- `application/accounts.py`
- `application/credentials.py`
- `application/sync.py`
- `application/strategies.py`
- `application/execution_plans.py`
- `application/risk.py`
- `application/reporting.py`
- `application/permissions.py`

### Domain Layer

允许做：

- 纯业务规则。
- 策略事件判断。
- 风控 guard 判断。
- 金额、价格、数量、币种等 value object。

禁止做：

- 任何网络 I/O。
- 任何数据库 I/O。
- 读取配置文件。
- 依赖 HTTP、MySQL、Binance、DPAPI。

目标文件：

- `domain/strategy/engine.py`
- `domain/strategy/rules/*.py`
- `domain/planning/*.py`
- `domain/risk/*.py`
- `domain/accounts/*.py`
- `domain/value_objects.py`

### Ports Layer

允许做：

- 定义抽象接口。
- 定义 repository、gateway、vault、clock、scheduler、event bus。

禁止做：

- 写具体实现。

目标文件：

- `ports/repositories.py`
- `ports/unit_of_work.py`
- `ports/exchange.py`
- `application/ports/credential_vault.py`
- `application/ports/account_connection_inspector.py`
- `ports/clock.py`
- `ports/events.py`

### Infrastructure Layer

允许做：

- MySQL repository。
- Alembic migration。
- Binance gateway。
- CredentialVault 实现。
- Scheduler runner。
- 报表文件输出。

禁止做：

- 决定业务规则。
- 决定用户权限。
- 决定策略动作。

目标文件：

- `infrastructure/db/`
- `infrastructure/exchange/binance.py`
- `infrastructure/credentials/`
- `infrastructure/scheduler/`
- `infrastructure/reporting/`

## 4. 依赖规则

唯一允许方向：

```text
api -> application -> domain
api -> application -> ports
application -> domain
application -> ports
infrastructure -> ports
infrastructure -> domain value objects
```

禁止方向：

```text
domain -> application
domain -> infrastructure
domain -> api
application -> api
api -> infrastructure
web -> database
web -> exchange
```

当前仍存在的架构债：

- `backend/src/orbit/application/app_state.py` 已收敛为运行状态、锁和用例入口；页面查询、权限投影与具体基础设施装配均已移出。
- API 已切换到 FastAPI + Uvicorn，并按认证、系统控制、账户、Binance、执行计划拆为独立 routers。
- 主要写用例已建立应用端口并进入 `ApplicationUnitOfWork`，策略运行态也可事务回滚；MySQL 配置、symbol-state、市场快照、事件、审计、日报 SQL 均已拆成独立 writer。
- `domain/strategy/engine.py` 和 `domain/planning/plans.py` 已共用 `domain/strategy/exposure.py`、`domain/strategy/actions.py`、`domain/strategy/rules/event_rules.py`、`domain/strategy/lifecycle.py` 与 `domain/risk/guards.py`；剩余策略架构债主要是趋势结束判定、亏损腿重建和迟滞/持续确认尚未完整落地。

这些不是要长期兼容的旧结构，而是拆除清单。

## 5. 目标目录

```text
backend/src/orbit/
  api/
    app.py
    deps.py
    routers/
    schemas/
  application/
    accounts.py
    account_runtime.py
    account_sync.py
    audit.py
    credentials.py
    strategies.py
    execution_plans.py
    risk.py
    reporting.py
    runtime_events.py
    strategy_control.py
    strategy_config.py
    metrics.py
    permissions.py
    ports/
      account_repository.py
      account_connection_inspector.py
      account_snapshot_repository.py
      audit_repository.py
      credential_vault.py
      execution_plan_repository.py
      exchange_snapshot_fetcher.py
      event_history_repository.py
      report_generator.py
      report_repository.py
      metric_history_repository.py
      run_config_repository.py
      symbol_state_repository.py
      strategy_runtime_repository.py
      unit_of_work.py
  domain/
    accounts/
    planning/
    risk/
    strategy/
      engine.py
      rules/
    value_objects.py
  infrastructure/
    persistence/
      accounts.py
      account_snapshots.py
      audits.py
      execution_plans.py
      event_history.py
      reports.py
      metrics.py
      run_configs.py
      strategy_runtime.py
      symbol_states.py
      unit_of_work.py
      storage.py
      mysql_event_writer.py
      mysql_audit_writer.py
      mysql_report_writer.py
    exchange/
      binance_snapshots.py
    credentials/
      local_vault.py
      account_connection.py
    scheduler/
    reporting/
```

## 6. 第一阶段主流程

### 6.1 配置账户 API

```text
POST /api/accounts/upsert
POST /api/binance/credentials
```

应用用例：

- `AccountService.upsert_account`
- `CredentialService.save_exchange_credentials`

端口：

- `AccountRepository`
- `CredentialVault`
- `AuditRepository`

### 6.2 同步 Binance

```text
POST /api/binance/sync
```

应用用例：

- `BinanceSnapshotFetcher.sync_account`
- `AccountSyncService.fetch/apply`
- `ExecutionPlanRefreshService.refresh`

端口：

- `ExchangeGateway`
- `AccountSnapshotRepository`
- `AuditRepository`

领域规则：

- Hedge Mode 必须通过。
- 同步失败必须记录错误，展示到账户行内。

### 6.3 生成执行计划

```text
POST /api/execution-plans/generate
```

应用用例：

- `ExecutionPlanService.build_for_accounts`

领域规则：

- `PlanningPolicy`
- `EventRule`
- `RiskGuard`

端口：

- `ExecutionPlanRepository`
- `AccountSnapshotRepository`
- `AuditRepository`

### 6.4 人工确认与导出

```text
POST /api/execution-plans/confirm
POST /api/execution-plans/export
```

应用用例：

- `ExecutionPlanService.confirm`
- `ExecutionPlanService.record_export`

规则：

- 只有 `planned` 状态可确认。
- 只能操作自己可见账户的计划。
- 确认和导出必须写审计。

## 7. 页面职责

### 总览

展示系统级 KPI、账户同步状态、策略运行状态、最近事件。

### 用户与账户

只展示：

- 业务用户列表。
- 交易账户列表。
- 所属用户。
- API 配置状态。
- 同步入口和同步错误。
- Hedge Mode 状态。

不展示：

- 策略实例。
- 运行配置。
- 事件参数。
- 风控详情。

### 策略中心

展示平台策略、事件参数、账户挂载关系、运行配置。

### 执行计划

展示账户选择、计划生成、计划详情、风控检查、人工确认、导出。

### 币种详情

展示单币种真实持仓、价格、事件时间线、计划来源。

### 风控中心

展示风控 KPI、计划风险、账户同步风险、Hedge Mode 风险、急停与恢复。

### 报表

展示日报、计划导出、审计摘要。

## 8. 拆除顺序

不做“先兼容再慢慢看”的双轨结构。后续改动按下面顺序直接收敛：

1. 继续把 `AppState` 的用例拆到 `application/*`。
   - 已完成：`ExecutionPlanService`
   - 已完成：`AccountService`、`CredentialService`、`SymbolStateService`
   - 已完成：`AccountRunConfigService`、`AccountSyncService`、`ExecutionPlanRefreshService`
   - 已完成：CredentialVault、AccountConnectionInspector、ExchangeSnapshotFetcher 端口
   - 已完成：`AuditService`、`RuntimeEventService`、`DailyReportService`
   - 已完成：`StrategyControlService`、MySQL 事件/审计/日报 writer
   - 已完成：`StrategyEventConfigService`、`MetricHistoryService`
   - 已完成：MySQL 配置/symbol-state/市场快照 writer
   - 已完成：`PortfolioViewService`（真实仓位、账户/组合汇总、策略摘要、管理员概览）
   - 已完成：`SnapshotQueryService`（控制台快照组装、匿名快照、账户级权限投影）
   - 已完成：`orbit/bootstrap.py` 独立 composition root；应用包不再反向依赖装配层或具体基础设施
   - 已完成：FastAPI + Uvicorn 以及认证、系统、账户、Binance、执行计划 routers
   - 下一步：Pydantic 请求模型、统一业务错误映射和接口权限契约扩充
2. 持续补齐 `application/ports/*`，让应用服务只依赖端口。
3. ApplicationUnitOfWork 已覆盖主要写状态，MySQL 主保存流程使用显式事务；配置、symbol-state、市场快照、事件、审计和日报 writer 均已拆出，`storage.py` 仅保留连接、读取、schema/ID 辅助与事务编排。
4. FastAPI routers 已替换 `api/server.py` 大 handler；后续补齐请求 DTO、统一异常映射和 OpenAPI 契约。
5. 把策略逻辑统一成完整领域状态机；目标敞口、动作 sizing、冷却/次数/趋势阶梯触发规则、事件后生命周期变更已抽为共享领域模块，后续继续补趋势结束、亏损腿重建与迟滞/持续确认。`RiskGuard` 已作为计划生成和 dry-run 引擎的共用风控入口，后续补组合级回撤、自融资账本与快照新鲜度 guard。
6. 前端使用 Vue 3 + Vite，页面放在 `frontend/src/pages/*`，共享状态放在 `frontend/src/stores/*`，API client 放在 `frontend/src/api/*`；后端只托管 `frontend/dist` 构建产物。

完成后应满足：

- 新增交易所只需要加 `ExchangeGateway` adapter。
- 新增策略事件只需要加 `EventRule`。
- 从 `plan_only` 切到 `paper/live` 只需要切换 `ExecutionMode` 与下单 adapter，不改计划生成主流程。
- 管理员权限变化只改 `PermissionPolicy`。
- 页面增加功能不需要改后端状态容器。
