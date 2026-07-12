# Dynamic Dual Grid V1 项目进度

最后更新：2026-07-10

## 当前目标

第一阶段目标是尽快打通可实盘测试的只读闭环：

1. 管理员维护业务用户与交易账户。
2. 管理员或账户所属用户为交易账户配置 Binance API Key / Secret。
3. 系统同步 Binance 合约账户真实余额、持仓和 Hedge Mode。
4. 基于真实持仓生成 `plan_only` 执行计划。
5. 在风控审计下手动查看、确认或导出计划。

第一阶段默认免登录，`auth.login_required=false`，默认操作者为 `admin_001`。

## 产品原则

- 本系统的使用者是管理员：管理员运行整个平台。业务用户只是交易账户的归属方（提供账号/API 凭证），策略由平台提供并由管理员挂载运行，业务用户不设计、不维护、不运行策略。
- 管理员不属于业务用户。
- API Key / Secret 跟随交易账户和所属业务用户，不属于管理员。
- 用户账户页只承载业务用户和交易账户关系，不放策略实例、运行配置等策略维护内容。
- 策略是系统维护的，应放在策略配置、执行计划、币种详情、风控中心等独立页面。
- 页面设计应对齐最初的控制台设计图：清晰的侧边导航、顶部指标、主表/主图、事件时间线和管理员风控中心，而不是堆叠式后台表格。

## 已完成

### 后端

- 支持 MySQL 存储，并通过 `config.local.json` 使用本地 MySQL 配置。
- 支持免登录模式和默认管理员操作者。
- 支持用户会话、管理员/业务用户权限过滤。
- 支持 Binance API Key / Secret 使用 Windows DPAPI 加密保存。
- 支持 Binance 合约账户只读同步：
  - 账户信息
  - 持仓风险
  - Hedge Mode
  - 真实余额与未实现盈亏
- 支持基于真实持仓生成第一阶段执行计划：
  - 利润搬运
  - 仓位恢复
  - 单边趋势确认下的亏损腿减仓
  - `plan_only` 风控拦截
- 支持执行计划人工确认与导出审计：
  - `/api/execution-plans/confirm`
  - `/api/execution-plans/export`
  - 确认和导出均写入管理员审计日志
- 已完成第一轮架构骨架切换：
  - 旧 `backend/src/ddg/` 包已移除
  - 唯一后端包为 `backend/src/orbit/`
  - 入口、测试、脚本均改为引用 `orbit.*`
  - 代码按 `api`、`application`、`domain`、`infrastructure` 分层目录组织
- 已新增应用层权限单点：
  - `orbit.application.permissions.PermissionPolicy`
  - HTTP 层与应用层账户权限判断统一委托该策略
- 已开始拆除 `AppState` 巨类：
  - 执行计划生成、人工确认、导出审计用例已抽到 `orbit.application.execution_plans.ExecutionPlanService`
  - Binance API 拉取实现已移动到 `orbit.infrastructure.exchange.binance_snapshots.BinanceSnapshotFetcher`，应用层通过 `ExchangeSnapshotFetcher` 端口调用
  - 账户目录读侧、账户访问判断和账户脱敏展示已抽到 `orbit.application.accounts.AccountDirectoryService`
  - 业务用户与交易账户新增/编辑已抽到 `orbit.application.accounts.AccountService`
  - Binance API Key / Secret 保存、DPAPI 加密、指纹计算、凭证列持久化写入与快照失效信号已抽到 `orbit.application.credentials.CredentialService`
  - 已新增 `CredentialVault` 与 `AccountConnectionInspector` 端口；账户目录和凭证应用服务不再直接依赖 Binance/DPAPI 实现
  - DPAPI/环境变量凭证实现已移动到 `infrastructure/credentials/local_vault.py`，账户连接检查实现位于 `infrastructure/credentials/account_connection.py`
  - 已新增 `application/ports/account_repository.py` 与 `application/ports/unit_of_work.py`，账户服务和凭证服务不再接收原始用户/账户列表
  - 已新增 `infrastructure/persistence/accounts.py` 与 `infrastructure/persistence/unit_of_work.py`，账户目录写操作通过可回滚 UnitOfWork 提交
  - 凭证保存已并入统一 `persist()`，MySQL 主保存流程会更新加密引用和指纹，不再通过单独 SQL 旁路写入
  - 已新增执行计划与审计 Repository 端口和基础设施适配器，`ExecutionPlanService` 不再接收原始计划列表或账户查询回调
  - 已新增运行配置与 Binance 快照 Repository 端口和基础设施适配器，计划服务与 symbol-state 刷新不再接收原始配置列表或快照字典
  - 运行配置默认值、合并校验、权限检查和审计信息已抽到 `AccountRunConfigService`
  - 同步权限检查、快照落仓、账户指纹/Hedge Mode 更新、计划刷新和审计信息已抽到 `AccountSyncService`
  - 运行配置补齐、symbol-state 刷新和计划重建的共享流程已抽到 `ExecutionPlanRefreshService`
  - 原目录事务与 PlanAudit 事务已合并为统一 `ApplicationUnitOfWork`，覆盖账户目录、运行配置、Binance 快照、symbol state、执行计划和审计，失败时整体回滚
  - MySQL 主保存流程已关闭自动提交并显式 `commit/rollback`，运行状态、计划和审计写入不再逐条自动提交
  - 审计记录 ID、时间、操作者和策略上下文已统一由 `AuditService` 生成，`AppState` 不再拼装审计结构
  - dry-run 策略事件、成交事件和风险事件的上下文补全与限长入仓已抽到 `RuntimeEventService` 和 `EventHistoryRepository`
  - 日报生成用例与日报列表维护已抽到 `DailyReportService`、`ReportGenerator` 和 `ReportRepository`
  - 策略启动、暂停、急停、恢复及账户冻结/解冻已抽到 `StrategyControlService` 和 `StrategyRuntimeRepository`，并进入统一事务
  - MySQL 配置、symbol-state、市场快照、策略/成交事件、管理员审计和日报 SQL 已分别拆到独立 writer；`storage.py` 的主保存流程只负责显式事务和 writer 编排
  - 事件配置合并、校验、审计信息和引擎重建已抽到 `StrategyEventConfigService`；配置更新后 `AppState` 与 `SymbolStateService` 会切换到同一个新引擎
  - 总体/币种指标采样与历史限长已抽到 `MetricHistoryService` 和 `MetricHistoryRepository`
  - 真实仓位行、账户/组合汇总、策略摘要和管理员概览已整体抽到 `PortfolioViewService`，旧的 `AppState` 查询计算实现已删除
  - 控制台快照组装、匿名快照和业务用户账户级权限裁剪已整体抽到 `SnapshotQueryService`，`AppState` 不再维护页面返回结构
  - 独立 composition root 已落到 `orbit/bootstrap.py`，统一装配仓储、凭证、Binance、报表、查询服务和 UOW；`application` 包不再依赖 `bootstrap` 或 `infrastructure`
  - 标准库 `BaseHTTPRequestHandler` 已彻底删除，后端切换到 FastAPI + Uvicorn，并按认证、系统控制、账户、Binance、执行计划拆成五组 routers
  - `ApplicationUnitOfWork` 已覆盖事件历史、日报、策略运行态和指标历史；`AppState` 当前只承担运行状态、锁和用例入口
- 已整理项目根目录的非代码资产：
  - 产品需求与技术方案移动到 `docs/product/`
  - 架构说明和设计图移动到 `docs/design/`
  - 配置样例移动到 `config/config.sample.json`
  - 新环境 JSON fallback 默认写入 `var/data/runtime_state.json`
- 已完成前后端顶层目录切分：
  - 后端 Python 服务端、脚本、SQL、测试移动到 `backend/`
  - 前端静态控制台移动到 `frontend/`
  - 启动入口改为 `backend/main.py`
- 已升级为 Vue 3 + Vite 前端工程：
  - `frontend/src/main.js` 作为 Vue 应用入口
  - `frontend/src/App.vue` 承载控制台外壳、导航、登录与页面切换
  - `frontend/src/stores/appStore.js` 统一前端状态和用例动作
  - `frontend/src/api/client.js` 统一 API 请求
  - `frontend/src/pages/` 承载总览、账户、策略配置、执行计划、币种详情、风控、报表、日志页面
  - `frontend/src/components/` 承载徽标、指标卡、摘要项和 SVG 图表组件
  - 后端生产静态托管指向 `frontend/dist`
- 已开始落地策略数学模型：
  - 新增 `backend/src/orbit/domain/strategy/exposure.py`
  - 新增 `backend/src/orbit/domain/strategy/actions.py`
  - 新增 `backend/src/orbit/domain/strategy/rules/event_rules.py`
  - 新增 `backend/src/orbit/domain/strategy/lifecycle.py`
  - 将当前净敞口 `Δ = long_qty - short_qty`、锚点偏离和目标净敞口 `Δ*` 抽成纯领域内核
  - `plan_only` 执行计划生成已改为先计算 `Δ*`，再通过共享动作集生成把 `Δ` 推向 `Δ*` 的动作
  - dry_run 模拟引擎 `EventEngine` 已改为复用同一套 `Δ*` 内核和共享动作集生成利润搬运、亏损腿减仓和仓位恢复事件
  - `execution_plans.trigger` 已携带 `exposure_model=net_exposure_v1`、当前净敞口、目标净敞口和目标差值
  - 已移除 `planning/plans.py` 中不再调用的旧三段式计划函数，避免计划生成继续双写
  - 已移除 `EventEngine` 中旧的 `try_*` 三段式事件分支，模拟与真实计划开始共用同一策略语义
  - 已移除 `EventEngine.preview_reduce` 私有预算函数，利润搬运 sizing 统一由 `strategy/actions.py` 计算
  - 已将冷却、次数、趋势阶梯触发 guard 抽到 `strategy/rules/event_rules.py`，`EventEngine` 不再分三套执行函数
  - 已将事件后状态变更、恢复重锚和计数器清零抽到 `strategy/lifecycle.py`
  - 已新增 `POSITION_REBUILD` 事件：价格回到重锚目标带内、净敞口已平衡但双腿低于 base 时，按 `max_restore_per_tick_ratio` 分批生成 `ADD_LONG` / `ADD_SHORT`
  - `StrategyLifecycle` 重锚时会按新价格重算 `base_qty = base_position_usdt / price`，避免继续追旧锚点仓位
  - 趋势态已开始接入退出判定：维护 `trend_extreme_price` 与 `trend_exit_candidate_count`，趋势态恢复/重建必须满足“从趋势极值回撤 + 回到退出带 + 连续确认 tick”
  - 趋势已确认时，`profit_transfer` 会被规则层拦截，避免趋势过程中继续逆势加仓
  - 真实 `plan_only` 执行计划已开始接入持久化 `symbol_states`：生成计划前用 Binance 最新快照刷新真实仓位/价格，同时保留 `base_price`、`base_qty`、生命周期状态、趋势极值和计数器
  - `plan_only` 计划生成已接入 `StrategyEventRules`：规则拦截会生成可审计的 blocked plan，并在 trigger 中展示 `event_rule`、生命周期状态和趋势退出计数
  - MySQL `symbol_states` 表结构与保存逻辑已补充 `base_qty`、趋势退出计数、tick 与最近事件字段；旧库保存时会自动补列
  - 已新增 `orbit.application.symbol_states.SymbolStateService`，将真实快照刷新计划侧 symbol state 的逻辑从 `AppState` 下沉到应用服务层
  - 已新增 `application/ports/symbol_state_repository.py` 与基础设施适配器 `infrastructure/persistence/symbol_states.py`，`SymbolStateService` 通过 Repository 边界读写 symbol state
- 新增管理员维护接口：
  - `/api/users/upsert`
  - `/api/accounts/upsert`

### 前端

- 用户账户页收敛为两个区域：
  - 用户列表
  - 账户列表
- 账户列表内嵌：
  - 所属用户
  - API 配置状态
  - API Key / Secret 保存入口
  - Binance 同步入口
  - 同步错误提示
  - Hedge Mode 状态
- 执行计划页支持：
  - 账户选择
  - 生成执行计划
  - 查看风控检查
  - 人工确认记录
  - 导出当前筛选计划 JSON，并写入导出审计
- 页面设计已开始重新对齐最初设计图：
  - 总览页：顶部指标 + 系统策略表 + 币种状态表
  - 策略事件配置页：三类事件参数卡片
  - 币种详情页：顶部币种指标条 + 仓位概览 + 图表 + 事件时间线
  - 风控中心：风控 KPI + 系统风险告警 + 计划风控检查 + 审计日志 + 快捷操作
  - 已清理账户页之外的旧 Binance 大面板和账户运行配置卡片残留

## 最近验证

- `npm run check` 通过。
- `npm run build` 通过。
- Python 单元测试及 API 契约测试：`104 tests OK`。
- `git diff --check` 通过。
- Vite 前端开发服务 `http://127.0.0.1:5173/` 冒烟通过。
- 后端生产服务入口为 `backend/main.py`；MySQL 模式推荐使用 `backend/scripts/run_server_mysql.ps1` 启动。本轮未保留后台常驻后端进程。

## Git 管理

- 已初始化 Git 仓库，默认分支为 `main`。
- 已建立首个提交：`4dc389e chore: initialize project git repository`。
- 已关联远程仓库：
  - `origin`: `https://github.com/yanceylv518/Orbit.git`
- 已配置 `.gitignore`，排除本地敏感配置和运行产物：
  - `config.local.json`
  - `var/`
  - `data/`
  - `runtime/`
  - `tmp/`
  - `reports/`
  - `.agents/`
  - `.codex/`
- 已配置 `.gitattributes`，统一文本文件行尾并标记图片/PDF 为二进制。
- 已同步远程最新提交：`d24cae9 docs: 策略逻辑数学化重构设计`。
- 远程新增策略设计文档已纳入新目录结构：`docs/design/STRATEGY_LOGIC.md`。

## 当前风险与注意事项

- 不要泄露 `config.local.json` 中的真实 MySQL 密码或任何真实 API Secret。
- API Key / Secret 页面不应回显明文。
- 当前仍以 `plan_only` / `read_only` 为主，不应直接下单。
- 后续设计调整应以最初设计图为准，避免再次退化成堆表格页面。
- Binance 网络同步失败时要把错误明确展示到账户行内，不要吞掉。

### 策略逻辑已知缺口（详见技术方案 §21）

- **趋势生命周期仍需继续完善（最高优先级）**：`StrategyLifecycle` 已接管事件后状态变更、恢复重锚、计数器清零、趋势退出候选计数和亏损腿重建；但趋势进入的持续确认、斜率/波动率维度、趋势退出参数的回测标定仍未完整落地。
- **风控剩余维度未补齐**：`RiskGuard` 已接入 `plan_only` 计划生成和 dry-run 引擎，`MAX_SYMBOL_DRAWDOWN` 会转为 `STOPPED` 拆对冲全平，gross 超限会进入 `ONLY_REDUCE`；但组合级回撤、C7 自融资账本、快照新鲜度/暂停态仍未落地。
- **趋势确认进入条件仍无斜率/时间维度**：趋势退出已有连续 tick 确认，但进入 TREND 仍主要依赖相对 base 的单点位移；慢速阴跌与暴跌仍可能被同等对待。
- **利润搬运口径待澄清**：`restore_loss_side_only_to_base=true` 且亏损腿已到 base 时，整次搬运（含减盈利腿止盈）被跳过；「用利润恢复亏损腿」是仓位定量口径而非资金划转。
- **成本项待补**：Funding 在失衡对冲中是方向性成本（当前恒为 0）；高频小额搬运有手续费 churn 风险，`min_net_profit` 应覆盖下一次反向平仓成本。

### 平台与文档差异（详见技术方案 §22）

- **本地凭证加密仅 Windows**：当前 `LocalCredentialVault` 使用 Windows DPAPI，Linux 环境调用 `protect()` 会抛 `CredentialVaultError`；读取 `env:` 引用仍可跨平台使用，后续可新增 Linux Vault adapter。
- **运维脚本仅 Windows**：`backend/scripts/` 只有 `.cmd`/`.ps1`，README 为 PowerShell + `C:\Users\...` 路径；Linux 环境未装 `node`，`node --check frontend/src/main.js` 无法复现，需补 bash 说明。
- **配置格式为 JSON**：技术方案 §13/§15 写的是 `config.yaml`，实际使用 `config/config.sample.json` / `config.local.json`。
- **深层分层仍待继续拆实**：应用服务、查询投影、composition root 和 FastAPI routers 已建立清晰边界；剩余重点是为接口补 Pydantic 请求模型与统一业务错误映射，并继续收敛 `storage.py` 的读取与 schema 辅助职责。
- **第一阶段范围**：技术方案 P0 是完整 dry_run 闭环，当前收窄为 `plan_only` 只读优先，以本文件「当前目标」为准。

## 下一步

### 工程架构

1. 按 `docs/design/ARCHITECTURE.md` 的拆除顺序继续拆 `AppState`：
   - 账户目录与凭证保存的 Repository / UnitOfWork 已完成
   - 执行计划与审计 Repository / UnitOfWork 已完成
   - 账户运行配置与 Binance 快照 Repository 已完成，并已合并为统一 ApplicationUnitOfWork
   - Binance 同步后状态更新与计划刷新编排已完成
   - CredentialVault 与账户连接检查端口已完成
   - 统一审计服务、历史事件与报表应用层 Repository 已完成
   - 策略控制服务和 MySQL 事件/审计/日报 writer 已完成
   - 事件配置更新与指标历史服务已完成
   - 配置、writer、查询服务、composition root 和 FastAPI routers 已完成；下一步补请求模型与业务错误映射
2. 继续收敛趋势生命周期：事件后状态变更、恢复重锚、趋势退出候选计数和亏损腿重建已进入 `StrategyLifecycle`；下一步补趋势进入的持续确认、斜率/波动率维度和趋势退出参数标定。
3. 补齐账户新增/编辑的更多校验与更友好的错误提示。
4. 强化 Binance 同步后的真实持仓展示：
   - 按账户筛选
   - 按币种筛选
   - 标记 Hedge Mode 不通过的账户
5. 执行计划页补更完整的计划详情抽屉或展开行，展示触发上下文和原始持仓快照。
6. 风控中心继续细化计划风险分类，区分账户同步风险、Hedge Mode 风险、计划动作风险。

### 策略逻辑设计落地

设计提案已成文：`docs/design/STRATEGY_LOGIC.md`；实现方案已成文：`docs/design/STRATEGY_IMPLEMENTATION.md`。2026-07-08 评审已确定阈值单位 σ 化、固定 k₂/k₁ 几何关系、结构化锚点与入场调制器两项 K 线回测对比，以及趋势结束三条件、现价重锚、分批重建三项生命周期决策。

当前 `plan_only` 计划生成和 dry_run 模拟引擎已切到 `Δ*` 内核，并共用策略动作集、事件触发规则、基础生命周期与 `RiskGuard`；dry_run 引擎已接入趋势退出候选计数和亏损腿分批重建，真实 `plan_only` 也已开始接入持久化 symbol state 与事件规则。趋势进入的持续性/斜率确认、参数约束、自融资账本与组合级风控仍待继续落地。

1. 为 FastAPI routers 增加 Pydantic 请求模型、统一业务错误映射和更完整的账户级权限契约测试。
2. 补趋势进入的持续确认、斜率/波动率维度，区分慢速漂移和快速趋势。
3. 扩展 `RiskGuard`：补组合级回撤、C7 自融资账本、快照新鲜度暂停态，以及 `STOPPED` 后的人工复核恢复流程。
4. 趋势确认增加斜率/时间维度，区分慢速阴跌和快速趋势。
5. 澄清并按需拆分利润搬运的止盈/加仓逻辑，补 Funding 与手续费 churn 的成本约束。

### 前端页面重构

页面结构重构设计已成文：`docs/design/UI_PAGES.md`（菜单 8→7、工作台改主流程漏斗驾驶舱、币种视图上墙相位/Δ/锚点/触发进度、计划详情展开行、风控拦截三桶、报表与日志合并；分两批交付，第一批全部基于现有后端数据）。其中已吸收上方「工程架构」下一步的第 4、5、6 项。

### 项目文件与运维

1. 校准产品技术方案中关于配置格式和目录结构的旧描述：当前以 JSON 配置和 `backend/`、`frontend/`、`docs/`、`config/` 顶层结构为准。
2. Linux 下补跨平台凭证方案（或统一走 `env:` 引用），并补 bash 启动/校验脚本。
3. 每轮开发完成后更新本文件，避免进度记录滞后于代码结构。
