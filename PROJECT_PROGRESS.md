# Dynamic Dual Grid V1 项目进度

最后更新：2026-07-13

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

## 实盘化推进（2026-07-12 起）

三个 P0 设计空洞已定稿并落地（设计见 `docs/design/ARCHITECTURE.md`「实盘化设计决策」）：

1. **D1 状态键账户化**：生命周期状态改键 `account_id::symbol`，双账户同 symbol 锚点/相位独立；MySQL 唯一键含 `exchange_account_ref`，旧库自动迁移。
2. **D2 行情时间轴**：`MarketDataFeed` 端口 + `BinanceKlineFeed`（主网公共 K 线，无需密钥）；tick = 1 根已收盘 K 线；`MarketFeedService` poll(锁外)/apply(锁内) 幂等推进各账户生命周期并自动重建计划；snapshot 暴露 `market_feed` 状态与 `plan_symbol_states` 账户级相位/Δ 摘要。
3. **D3 计划 TTL**：计划带 `expires_at_ms`（900s 可配）；确认双闸——过期拒绝 + 价格漂移 >0.5% 拒绝。

内核风控补全：
- C7 自融资不变量进 RiskGuard（账本 harvested/averaging_spent 随成交更新；同组减仓预估利润计入预算）。
- 趋势进入持续确认 `trend_entry_confirm_ticks`（sample=2），阴跌/单点冲高不再等同暴跌。
- 快照新鲜度 `snapshot_max_age_seconds`（600s）→ SYNC_STALE 拦截。
- 组合级回撤 `max_total_drawdown_pct` 接线 → GLOBAL_STOP 全局拦截（原未接线旋钮消灭）。

S1–S7 仿真验收测试落地（`tests/test_strategy_scenarios.py`）：震荡收割为正、趋势亏损有界、V 型不锁死、横跳/跳空/阴跌防护、C7 随机路径不变量。**126 passed, 1 skipped（Linux）**。

前端接线：计划 TTL 倒计时与过期徽章、币种相位/偏离改由 `plan_symbol_states` 实时驱动、工作台状态行显示行情源健康度。

M3 执行通道已完成（2026-07-12）：
- **paper 模式**（`run_config.mode=paper`）：行情 tick 后由 `PaperExecutionService` 用内核 fills 模型虚拟成交，仓位由内核演进、不被快照覆盖；事件/成交带账户上下文入历史。
- **live 通道（默认全关）**：`OrderExecutionService` 八重闸门（全局开关 default false / 仅管理员 / 已确认计划 / TTL+漂移复检 / mode=live / dry_run=false / 确认短语 / 仅 reduce-only），`POST /api/execution-plans/execute`，每次尝试强制审计；`BinanceFuturesClient.place_order` 落地。

M5 离线标定已完成并跑出**第一批真实结果（2026-07-12）**：
- 工具：`backend/tools/fetch_klines.py`（支持 `--spot-mirror`，本机 fapi 被 451 时经 data-api.binance.vision）+ `backend/tools/calibrate.py`（π̂ 估计/Wilson 区间/几何扫描）；纯逻辑在 `domain/calibration/estimators.py`（9 项单测）。
- **标定结论（诚实的负结果）**：BTCUSDT 1h×180 天与 ETHUSDT 1h×180 天，43 个 (a,θ) 组合全部不过 C8 准入线（BTC 默认参数 π̂=0.559 < 0.660，E=−0.41%/注）；BTCUSDT 15m×60 天 + maker 成本出现正期望组合（最高 +0.12%/注）但置信下界仍不过线。
- **含义**：当前市况+当前无过滤的基线策略不应开 live。下一步按 STRATEGY_LOGIC §10.2 实现 regime gate（只在回归证据存在时开仓）后重新标定，以及积累更长 15m 样本。这正是 Phase B 止损门的设计用途——在真钱之前拦住了负期望配置。

M6 Regime Gate 第一版已完成（2026-07-13）：
- 新增 `domain/strategy/regime.py`：滚动效率比 ER、收益一阶自相关、波动率特征，以及 `RANGE / TRENDING / TRANSITION / UNKNOWN` 四态分类。
- 每个 `account_id::symbol` 独立维护价格窗口、原始判定、稳定判定、候选计数和连续确认；历史不足时安全落入 `UNKNOWN`。
- Gate 已同时接入 `plan_only` 与 Paper 共用内核：只有确认 `RANGE` 才允许利润搬运和双腿重建；趋势减仓、STOP unwind 和已有偏斜回收不被阻断。
- MySQL 既有策略在启动时自动注入 Gate 默认配置，不依赖重新初始化数据库；快照、币种页和计划详情暴露 Gate 状态、ER、自相关与波动率。
- 新增 8 项 Gate 专项测试；完整回归已扩展至 `162 tests OK`。

M6 walk-forward 重标定已完成（2026-07-13）：
- `domain/calibration/estimators.py` 新增无未来数据泄漏的滚动训练/验证、Gate on/off 对照、每折参数选择、实际收益加权汇总、交易频率与回撤指标。
- `backend/tools/calibrate.py` 新增 `--walk-forward`、训练/验证窗口、步长和 JSON 报告输出；新增 5 项校准专项测试。
- BTCUSDT 15m×180 天（5 折，训练 5760 根、验证 1920 根）的真实公共 K 线结果：Gate off 为 28 笔、总收益 `-16.42%`、单笔期望 `-0.586%`、最差单折回撤 `11.48%`；Gate on 为 15 笔、总收益 `-8.60%`、单笔期望 `-0.573%`、最差单折回撤 `6.56%`。
- **阶段结论**：Gate 明显减少交易暴露和绝对亏损，但没有把该周期/参数网格变为正期望，5 折仅 1 折盈利；当前配置继续拒绝 testnet/live 准入，下一步先扩展多币种、多周期与 Gate 参数联合标定。
- 新增 `backend/tools/calibrate_matrix.py` 与组合阶段门，按各折实际交易收益汇总，不对市场百分比做简单平均；准入同时要求 Wilson/C8、组合正期望以及盈利市场过半。
- BTCUSDT/ETHUSDT × 15m/1h（各 5 折）组合结果：Gate off 363 笔、总收益 `-86.32%`、单笔期望 `-0.238%`；Gate on 241 笔、总收益 `-42.74%`、单笔期望 `-0.177%`；盈利市场均为 `0/4`，组合阶段门 `FAIL`。
- **约束**：禁止直接根据验证集调 Gate 阈值。Gate 参数必须仅在训练窗选择，再交给后续验证窗判定，防止以“调到通过”为目标产生过拟合。
- Gate 嵌套调参已实现：每折先在训练窗选择几何参数，再从 18 组 Gate 配置中按最低交易覆盖与 `Wilson 下界 - π_required` 排序；验证窗完全隔离，并有“修改验证价格不改变已选参数”的自动测试。
- 新增 `gate_deploy` 口径：训练期 Gate 未通过 C8 的折直接空仓，不再拿“最不差参数”模拟部署。4 市场共 20 折中仅 BTCUSDT 1h 的少量折获得训练准入，外样本 9 笔、总收益 `-2.76%`、单笔期望 `-0.307%`，部署阶段门仍为 `FAIL`。
- 负期望归因已完成：每份报告拆分几何毛收益、手续费拖累、Gate 过滤交易的反事实收益和盈亏平衡成本。Gate on 组合毛收益 `-11.50%`、手续费 `-37.52%`、净收益 `-49.02%`；被 Gate 过滤交易的反事实净收益为 `-37.30%`，说明 Gate 有效避开坏交易，但放行交易在零手续费下仍为负。
- **模型判断**：当前失败首先来自 excursion 触发几何的负毛期望，手续费是第二层放大因素，Regime Gate 不是主要根因。由于现有标定器是固定 payoff 的简化数学代理，不能据此直接否定包含双腿仓位、利润搬运、恢复和趋势减仓的完整引擎；下一阶段必须用真实领域引擎做逐 K 线事件与现金流回放。

M6 完整领域引擎历史回放第一版已完成（2026-07-13）：
- 新增 `domain/calibration/replay.py`，直接复用生产 `EventEngine.on_tick()`，不复制策略逻辑；逐 K 线推进双腿持仓、成交均价、利润搬运、恢复、趋势减仓、Regime Gate、风险状态、手续费与滑点。
- 新增 `backend/tools/replay_klines.py` 和 `backend/tools/replay_matrix.py`；支持整段回放、独立验证折、期末强制平仓、多市场汇总与阶段门。
- 回放对初始双腿开仓和期末双腿平仓都计入手续费/滑点；报告同时记录期末清算前净值、清算后已实现净值、峰值回撤、相对初始预算最大亏损和账务恒等误差。
- BTC/ETH × 15m/1h 的 20 个独立验证折结果：合计净收益 `-7.68 USDT`（每折 100 USDT）、平均 `-0.384%/折`、盈利折 6/20、盈利市场 1/4、最差折 `-1.82%`、最差峰值回撤 `3.86%`，阶段门 `FAIL`。
- 整段回放曾全部为正，但分段独立初始化与清算后结论转负，证明整段结果存在趋势区间和终点依赖，不能用于准入。
- Funding 历史序列尚未接入，报告明确标记 `funding_complete=false`，并作为阶段门硬阻断项；不会用零 Funding 冒充完整成本。
- 新增事件收益归因与基准变体对照。完整策略 20 折中：利润搬运直接已实现 `+17.91 USDT`，趋势减仓 `-47.12 USDT`，恢复 `-7.02 USDT`，重建手续费损失 `-0.54 USDT`；直接收益不等于最终贡献，因此同时使用关闭模块的反事实对照。
- 基准对照：完整策略 `-7.68`；利润搬运只减盈利腿、不补亏损腿 `-5.37`；关闭利润搬运 `-6.08`；关闭恢复/重建 `-13.69`；仅趋势减仓 `-9.66`；纯中性持有（仅建仓/平仓成本）`-2.18 USDT`。
- **关键诊断**：关闭趋势减仓后为 `-1.35 USDT`、盈利折 14/20（完整策略 6/20），四市场分别为 `+0.34/-0.21/-0.88/-0.59`。说明当前趋势减仓触发/比例是最主要的可疑负贡献，但该结论来自验证样本，只能用于生成候选，禁止直接据此修改生产默认值。
- 趋势减仓嵌套选择已实现：候选包括默认、4% 轻减仓/极轻减仓、5%/6% 延后轻减仓和关闭；外层每折只用训练窗选择，验证窗完全隔离。简单训练累计收益选择得到外样本 `-4.87 USDT`、盈利折 10/20；训练窗再切三段按稳定性选择后为 `-7.19 USDT`、盈利折 7/20、盈利市场 0/4。
- **停止条件**：训练窗无法稳定预测哪种趋势减仓配置在下一验证窗有效。事后固定关闭的 `-1.35` 不能转化为可部署规则，因此停止继续扫描此参数族，优先补 Funding 与 OHLC 路径数据后再评估。
- OHLC/Funding 数据层已落地：`history.py` 同时兼容旧 `[time, close]`、新 OHLC 对象和 Binance/归一化 Funding 格式；`fetch_klines.py --ohlc` 与 `fetch_funding.py` 已生成 BTC/ETH 的 15m/1h OHLC 及 360 天 Funding 缓存。
- Funding 已按结算时间、当时实际多空数量和收盘价写入领域引擎已实现收益：`cashflow=(short_qty-long_qty)×price×rate`，并提供覆盖完整性与账务恒等测试。四市场 20 折同窗对照：无 Funding `-9.2744 USDT`，含真实 Funding `-9.2996 USDT`，Funding 净影响约 `-0.0252 USDT`；对冲结构使多空 Funding 大致抵消，它不是当前负收益根因。
- 新 OHLC 当前仅使用 close 驱动策略，high/low 尚未参与盘中触发；这是刻意分阶段验证，不能把现结果称为 OHLC 回测。
- OHLC 盘中回放第一版已接入：生产 `EventEngine` 新增 `on_intrabar_price()`，盘中价格可触发持仓管理/风险动作，但不会推进 `tick_count`、Regime 历史或趋势连续确认；每根收盘仍只调用一次正常 `on_tick()`。
- 每根 K 线从同一状态模拟 `O-H-L-C` 与 `O-L-H-C`，选择该根收盘权益较低的分支继续。该模型是**逐 K 局部不利压力测试**，不是全局最坏路径（局部低权益状态可能改变后续仓位并最终少亏）。
- 四市场真实 OHLC + Funding 的 20 折结果：`-5.93 USDT`、盈利折 6/20、盈利市场 1/4、最差折 `-2.78%`、1113 笔策略成交、Funding `+0.0385 USDT`，阶段门 `FAIL`。相比 close-only 同窗 `-9.30`，总亏损缩小但交易数和尾部单折亏损上升，说明盘中路径显著改变事件时序，不能再用 close-only 结论替代。
- 路径敏感性对照已完成：固定 `O-H-L-C` 为 `-7.2340 USDT`、盈利折 5/20、1217 笔；固定 `O-L-H-C` 为 `-6.6168`、盈利折 6/20、943 笔；逐 K 局部低权益为 `-5.9295`、盈利折 6/20、1113 笔。三种路径全部 `FAIL`，结果区间约 `1.30 USDT`，路径显著影响成交频率和尾部但不改变拒绝准入结论。
- **路径搜索停止条件**：所有规范路径均远离准入线，暂不增加高复杂度 beam 搜索；beam 只能细化压力区间，当前不会改变产品阶段决策。优先处理在所有路径下反复出现的高频事件与负贡献模块。
- OHLC+Funding 跨路径模块消融完成：关闭趋势减仓相对完整策略在固定 OHLC、固定 OLHC、myopic 下分别改善约 `+6.92/+6.10/+8.29 USDT`；对应总收益为 `-0.317/-0.513/+2.359`。该负贡献方向跨路径一致，但仍只有 2/4 盈利市场，固定路径未转正，不能进入 paper。
- 关闭利润搬运为 `-14.51`、关闭恢复为 `-14.73`（三条路径结果一致且显著恶化）；利润搬运只减盈利腿在三条路径也均差于完整策略。OHLC 口径下，利润搬运与恢复的组合价值存在，主要问题集中在趋势减仓。
- 时间尺度诊断：关闭趋势减仓后，BTC/ETH 1h 在三条路径均为正，15m 在三条路径均为负。当前 cooldown、连续确认与阶梯减仓以 tick 计数，同一配置跨 15m/1h 代表不同实际时长；策略运行 interval 必须成为显式配置和标定边界。
- 独立旧历史复核完成：新拉取 720 天 1h OHLC/Funding，排除最近 8640 根，仅用未参与当前诊断的更早约 360 天测试预先确定的“1h + 关闭趋势减仓”候选。固定 OHLC `+7.59 USDT`（7/10 折、2/2 市场），固定 OLHC `+5.11`（6/10、2/2），myopic `+3.51`（7/10）但 ETH `-0.74`、仅 1/2 市场。
- **外部复核结论**：候选在独立旧历史总体为正且固定路径稳定，但 myopic 下未满足市场覆盖，仍为研究候选而非 paper 配置；旧区间是反向时间外样本，不等同未来 forward test。
- 运行 interval 已进入策略实例和账户运行配置，支持 Binance 周期白名单归一化；`MarketFeedService` 改为按 `(interval, symbol)` 分流，同币种不同周期会独立拉取、只推进对应账户。MySQL `account_run_configs.kline_interval` 已进入基准 schema。

**运维注意**：本 Linux 主机访问 fapi.binance.com 返回 451（区域封锁）；行情源 base_url 已可配（`runtime.market_feed.base_url`），生产运行需部署在 Binance 可服务的网络环境（如用户本机）。

**待办（下一轮）**：补 MySQL 既有库 interval migration 与运行配置 writer/read model；前端账户运行配置显示 interval。随后为“1h + 关闭趋势减仓”建立只记录不成交的 shadow/paper 候选，不绕过 Funding/path 阶段门。

## Regime Gate 审查修复计划（2026-07-13，交付 Codex 执行）

对提交 `0e1bbd3 feat(strategy): add regime gate and full replay validation` 做了代码审查。结论：方向正确、无阻断性 bug、`188 passed / 1 skipped`，可合入；以下为审查发现的待修复项与开发计划。**本计划交由 Codex 执行，每个任务完成后由 Claude 对其提交做 review。**

### 全局约束（所有任务通用）

1. 每个任务独立提交，提交信息用 conventional commits（如 `fix(strategy): ...`）。
2. 全程保持测试绿：`cd backend && python3 -m pytest tests/ -q`（当前基线 188 passed / 1 skipped）。
3. 不改动 live 通道任何默认开关（默认全关不变）。
4. 遵守 walk-forward 纪律：**禁止为“让某次回放/验证集通过”而调参**；阈值只能在训练窗/历史样本上选择。
5. 每个任务完成后，在本文件对应条目登记结果（含关键数据），保持进度不滞后于代码。

### 任务 R1：为被 regime / 规则拦截的决策补审计痕迹（优先级：高）

- **问题**：`backend/src/orbit/domain/strategy/engine.py` 的 `apply_target_exposure_event`（约 431–454 行）在 `regime_result.allowed=False` 或 `rule_result.allowed=False` 时静默 `return None`，且 `regime_result.context` 被丢弃。复盘时看不到“本该产生动作，但被 regime/规则拦截”，违反“每次决策可解释、可复盘”的验收目标。
- **涉及文件**：`backend/src/orbit/domain/strategy/engine.py`；`backend/src/orbit/application/runtime_events.py`（或现有 blocked-plan / risk_event 记录路径）；`backend/src/orbit/domain/planning/plans.py`（plan_only 计划详情）。
- **改动**：当 `decision.has_action` 为真但被 regime 或 event_rule 拦截时，产出一条轻量 blocked 记录（复用现有 blocked plan / risk_event 结构，不新造模型），携带 `code`、`reason`，以及 regime 上下文（`regime` / `regime_raw` / `regime_stable`、ER、自相关、波动率）或规则拦截原因。该记录进入 dry_run/paper 事件历史与 `plan_only` 计划详情。**不产生任何成交。**
- **验收**：新增测试——① 在 TRENDING regime 且存在目标动作时，`on_tick` 结果包含一条 regime-blocked 记录，且 `long_qty` / `short_qty` / `realized_pnl` 不变；② `plan_only` 生成的计划详情中含 regime 拦截原因字段。
- **约束**：只补记录，不改变实际成交/仓位行为。

### 任务 R2：厘清并修正 RANGE 自相关阈值语义（优先级：中，先出结论再改）

- **问题**：`backend/src/orbit/domain/strategy/regime.py` 的 `classify_regime`（约 95–99 行）中 RANGE 分支要求 `return_autocorrelation <= range_max_autocorrelation`，默认 `0.95`。一阶自相关几乎不会超过 0.95，该条件近乎恒真，**RANGE 实际退化为“仅 `efficiency_ratio <= range_efficiency_ratio(0.35)`”**，自相关未参与判定。若本意是“震荡=低/负收益持续性”，阈值过松。
- **涉及文件**：`backend/src/orbit/domain/strategy/regime.py`；`config/config.sample.json`（`strategy.regime_gate`）；`backend/tests/test_regime.py`；分析用 `backend/tools/calibrate_matrix.py` / `backend/tools/replay_matrix.py`。
- **改动分两步**：
  1. **先分析、后决策**：用现有回放/标定工具在**训练窗**对比“收紧 RANGE 自相关阈值（如要求 `autocorr <= 0.2`）”与现状对 RANGE 命中率和外样本收益的影响，把结论（数据）写回本文件。
  2. 依据结论二选一：**要么**保留 `0.95` 但在代码加注释说明它只是病态值保险；**要么**改默认阈值收紧 RANGE 语义，并附训练窗对照数据。
- **验收**：`test_regime.py` 增加“低 ER + 高自相关”与“低 ER + 低自相关”两类样本的分类断言，把当前语义钉死；若改默认值，须附训练窗（非验证窗）对照数据。
- **约束**：严禁按验证集/某次回放结果反推阈值。

### 任务 R3：收敛 paper 收盘推进与引擎单一入口（优先级：低，维护）

- **问题**：`backend/src/orbit/application/symbol_states.py` 的 `advance_state_with_price`（约 83–102 行）手工重复了 `tick_count / high_since_base / low_since_base / regime_gate.update / lifecycle.update_trend_tracking / resolve_state` 这套收盘推进逻辑，与 `engine._on_price` 重复，且已有细微差异（`_on_price` 仅在收盘 tick 自增 `tick_count`，而 `advance_state_with_price` 每次都自增）。两条路径未来容易漂移。
- **涉及文件**：`backend/src/orbit/application/symbol_states.py`；`backend/src/orbit/domain/strategy/engine.py`。
- **改动**：在 `EventEngine` 暴露一个只做“推进指标 + 生命周期，不决策不成交”的收盘推进方法（如 `advance_close(state, price, close_time)`），让 `advance_state_with_price` 复用它，消除重复；paper 决策仍由 `execute_paper_tick` 承担。
- **验收**：现有 paper 相关测试（`test_market_data` / `test_account_runtime` / paper 执行）保持绿；新增测试断言 `advance_state_with_price` 与引擎收盘推进对 `regime_*` / 生命周期字段结果一致。
- **约束**：不改变 paper 决策与成交时序。

### 已在本文档登记、无需 Codex 改码的观察

- **regime 冷启动静默期**：累计到 `min_samples`(默认 20) 根收盘前，regime 为 `UNKNOWN`，而 `UNKNOWN / TRANSITION / TRENDING` 均禁止利润搬运与双腿重建。`interval=1h` 时新 symbol 约 20 小时内不会有搬运；`regime_price_history` 存入 state，重启不丢，但新初始化的 symbol 会重新预热。此为**预期行为**，paper/live 上线首日需据此设期望（见下方「策略逻辑已知缺口」）。

## 最近验证

- `npm run check` 通过。
- `npm run build` 通过。
- Python 单元测试及 API 契约测试：`189 tests OK`。
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
- **Regime Gate 审查发现（2026-07-13，修复计划见上方「Regime Gate 审查修复计划」）**：
  - 被 regime / 规则拦截的决策静默返回、无审计痕迹（待办 R1）。
  - RANGE 自相关阈值 `0.95` 近乎恒真，RANGE 退化为仅看效率比（待办 R2）。
  - regime 冷启动静默期：`min_samples` 根收盘前禁止利润搬运/重建（`interval=1h` 约 20 小时），属预期行为，paper/live 上线首日需据此设期望。
  - paper 收盘推进（`advance_state_with_price`）与引擎 `_on_price` 逻辑重复、`tick_count` 自增条件已有差异，需收敛单一入口（待办 R3）。

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

第一批已实现（2026-07-12）：
- 导航 8→7：`EventsPage → StrategyPage`（策略中心，含平台策略卡、账户挂载表、未生效参数标注、内核状态），`LogsPage` 并入报表页 Tab；旧锚点 `#events/#logs` 重定向。
- 工作台重做：主流程漏斗 KPI（账户同步/Hedge/待确认/拦截/无动作，逐格点击直达）+ 待办区（问题账户重试同步、待确认计划前 5）+ 系统状态行。
- 顶栏模式感知：只读模式显示「同步全部账户 / 生成执行计划」，Tick/暂停/重置仅 mock 模式渲染；新增风控状态徽章直达风控中心。
- 币种视图：卡片头上墙相位 badge、锚点价、偏离、触发进度条（0—a_pt—θ_t，新组件 `TriggerProgress`）、Δ 净敞口与 Δ* 目标（数据来自 `execution_plans[].trigger` 的 `net_exposure_v1` 上下文）；列表加 Δ 列与账户筛选。
- 执行计划页：详情展开行（触发快照 + 生命周期上下文 + 风控/动作逐条 + 原始 trigger JSON）、相位与 Δ→Δ* 列、拦截原因前置。
- 风控中心：拦截三桶（账户同步 / Hedge Mode / 计划动作）。
- `appStore` 新增 `syncFunnel/planFunnel/aggregateSymbols/syncAllAccounts` 派生状态与动作。

验证说明：本轮在 Linux 环境完成（无 node），已做 import/export 交叉验证与 script 块配平静态检查；`npm run check`/`npm run build` 需在 Windows 侧复验。

视觉重做（2026-07-12，应「风格不够大气、页面粗糙」反馈）：
- 整体切换为**深色交易终端设计系统**（`styles/app.css` 全量重写）：深蓝黑表面体系、tabular-nums 数字排版、克制的结构色 + 状态/盈亏专用色、卡片渐变与柔和阴影、sticky 毛玻璃顶栏。
- 品牌升级为 **ORBIT**：轨道环 logo（纯 CSS）、登录页深色渐变 + 轨道环装饰、`index.html` 标题与 `color-scheme: dark`。
- 侧栏重构：运营/策略/治理三分组 + 内联 SVG 线性图标（新组件 `NavIcon.vue`，零依赖）。
- 图表深色适配：轴线弱化；双线图色对 `#19A862/#AD3B48` 与价格线 `#3987E5` 按 dataviz 规范在面板色 `#111B2E` 上做了 CVD（Machado）与对比度校验（CVD ΔE 13.6 通过），并按 relief 规则为多空双线图补图例直标。
- 类名体系保持兼容，页面模板基本未动；已做全模板类名覆盖核对（无缺失）。

### 项目文件与运维

1. 校准产品技术方案中关于配置格式和目录结构的旧描述：当前以 JSON 配置和 `backend/`、`frontend/`、`docs/`、`config/` 顶层结构为准。
2. Linux 下补跨平台凭证方案（或统一走 `env:` 引用），并补 bash 启动/校验脚本。
3. 每轮开发完成后更新本文件，避免进度记录滞后于代码结构。
