# Dynamic Dual Grid V1 项目进度

最后更新：2026-07-14

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

- TB4-B 后端前向启动器已完成（尚未部署、未开始前向计时）：
  - 12 市场共同连续 4h 暖机与增量收盘/Funding 驱动
  - 暖机与计分起点严格分离，首个前向收盘才计入权益
  - 不可变启动清单 + JSONL SHA-256 哈希链账本
  - 每条计分记录追加保存输入、权益、回撤、再平衡和当前 TB3 指标
  - 重启时验链并逐条重放，恢复结果与不中断运行完全一致
  - 期限前 `verdict=null`，参数不可变，live 通道固定不接入
  - 平台完整 snapshot 新增只读 `trend_forward` 投影
  - 独立入口：`python backend/tools/run_tb4_forward.py --initialize`
- TB4-A 冻结趋势组合 runner 已完成并通过硬对齐门：
  - 新增独立 `FrozenTrendBasketRunner`，不复用双网格 `EventEngine` / symbol state
  - 12 市场、4h、`14/28/56/84/168` 日动量集成、vol28、目标波动 10%、gross cap 1.0、7 日再平衡、下一根执行、0.14% 往返成本全部由 `TB4_SPEC` 固定，不接受运行配置覆盖
  - 收益顺序与离线估计器一致：旧权重价格/Funding收益 -> 权重漂移 -> pending 目标成交与成本 -> 新信号排队
  - 正式冻结历史对齐覆盖 `9,940` 个评估周期和 `237` 次再平衡；净收益与目标权重最大误差均为 `0.0`，verdict `TB4_ALIGNMENT_PASS`
  - 前向协议见 `docs/design/TB4_FORWARD.md`；TB4-B 尚未启动，未填写或伪造前向开始时间
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

### 任务 R1：为被 regime / 规则拦截的决策补审计痕迹（已完成，2026-07-13）

- **问题**：`backend/src/orbit/domain/strategy/engine.py` 的 `apply_target_exposure_event`（约 431–454 行）在 `regime_result.allowed=False` 或 `rule_result.allowed=False` 时静默 `return None`，且 `regime_result.context` 被丢弃。复盘时看不到“本该产生动作，但被 regime/规则拦截”，违反“每次决策可解释、可复盘”的验收目标。
- **涉及文件**：`backend/src/orbit/domain/strategy/engine.py`；`backend/src/orbit/application/runtime_events.py`（或现有 blocked-plan / risk_event 记录路径）；`backend/src/orbit/domain/planning/plans.py`（plan_only 计划详情）。
- **改动**：当 `decision.has_action` 为真但被 regime 或 event_rule 拦截时，产出一条轻量 blocked 记录（复用现有 blocked plan / risk_event 结构，不新造模型），携带 `code`、`reason`，以及 regime 上下文（`regime` / `regime_raw` / `regime_stable`、ER、自相关、波动率）或规则拦截原因。该记录进入 dry_run/paper 事件历史与 `plan_only` 计划详情。**不产生任何成交。**
- **验收**：新增测试——① 在 TRENDING regime 且存在目标动作时，`on_tick` 结果包含一条 regime-blocked 记录，且 `long_qty` / `short_qty` / `realized_pnl` 不变；② `plan_only` 生成的计划详情中含 regime 拦截原因字段。
- **约束**：只补记录，不改变实际成交/仓位行为。
- **完成结果**：`EventEngine` 在目标动作被 Regime Gate 或 EventRule 拦截时生成 `info` 级 `risk_event`，统一标记 `status=blocked`、`action_taken=BLOCKED_NO_TRADE`，携带目标敞口、阻断来源/代码、regime 三态、ER、自相关和波动率，且 `trades=[]`；`RuntimeEventService` 沿既有风险事件通道入历史。`plan_only` blocked plan 同步暴露上述 Gate 特征。`PortfolioViewService` 排除 `info` 级决策痕迹，避免把正常 Gate 阻断误报为组合 `watch`。新增领域、计划和投影测试，确认仓位、已实现盈亏与成交行为不变。
- **验收结论（Claude，2026-07-13）：通过。** 两条验收标准均满足；`test_regime_block_is_recorded_without_mutating_positions_or_pnl`、`test_regime_blocked_plan_contains_gate_reason_and_features` 覆盖 dry_run 与 plan_only 两路径；`material_risk_events()` 过滤 `info` 级是超出验收的正确防御。后端 `191 passed / 1 skipped`。合并在 `main`（`35995a5`）。
- **R1.1 收尾项（已完成，2026-07-13）**：blocked 审计此前在「有目标动作但被拦截」时**每个 tick 都 emit 一条 `info` 风险事件**（`apply_target_exposure_event` 无去重）。而 `infrastructure/persistence/event_history.py:37` 的 `add_risk_event` 把风险历史统一 FIFO 截断到 200 条、不分级别。持续 TRENDING（趋势可长达数十上百根 K 线）时，dry_run/paper 实时循环会在不到 200 tick 内把真实 material 风险事件（STOP / 回撤 / SYNC_STALE / gross 超限）全部挤出缓冲区——`material_risk_events()` 只挡显示层翻转，底层是先物理截断后过滤，material 记录已被物理驱逐。此副作用与 R1「强化可追溯」的目标相悖。
  - **涉及文件**：`backend/src/orbit/domain/strategy/engine.py`（`apply_target_exposure_event` / `blocked_decision_event`）；可能 `backend/src/orbit/application/paper_execution.py`、`app_state.py` 实时循环侧。
  - **改动**：blocked 审计改为**按拦截状态转换去重**——仅在进入拦截态、或 `block_code` 变化时记一次，同一拦截持续期间不再逐 tick 记录（可用 symbol state 存 `last_block_code` 判断）。次选：给 blocked 审计单独缓冲，或 `add_risk_event` 截断时优先驱逐 `info` 级。
  - **验收**：新增测试——同一 symbol 在 TRENDING 下连续多个 tick 只应产生 1 条 blocked 风险事件（拦截未变时后续 tick 不再追加）；连续注入 200+ tick 的持续拦截后，先前写入的 material 风险事件仍保留在历史中。
  - **约束**：不改变成交/仓位行为；plan_only 单次生成的 blocked plan 行为不受影响。
  - **完成结果**：symbol state 新增 `last_block_code`，只在首次进入阻断态或 code 变化时生成 blocked 审计；无目标动作、恢复允许或进入 STOPPED 时清空，离开后重新进入会再次记录。250 次持续 TRENDING paper 决策仅 emit 1 条 `info` 记录，历史中预先存在的 critical material 风险仍保留；仓位、已实现盈亏、成交及 plan_only 行为均未改变。该字段随现有 `app_runtime_state.payload_json` 持久化，无需新增 MySQL 投影列。
  - **验收结论（Claude，2026-07-13）：通过。** 去重按拦截码转换实现，`clear_blocked_decision` 在放行/无动作/STOP 三处清零，重入趋势会重新记一次（`block_code` 变化也会重记）——语义正确。`test_sustained_block_does_not_evict_material_risk_history`（250 tick 仅 1 条、material 事件仍在）直接验证修复目的。仓位/成交行为不变，后端 `195 passed / 1 skipped`。合并在 `main`（`74d1ad6`）。

### 任务 R2：厘清并修正 RANGE 自相关阈值语义（已完成，2026-07-13）

- **问题**：`backend/src/orbit/domain/strategy/regime.py` 的 `classify_regime`（约 95–99 行）中 RANGE 分支要求 `return_autocorrelation <= range_max_autocorrelation`，默认 `0.95`。一阶自相关几乎不会超过 0.95，该条件近乎恒真，**RANGE 实际退化为“仅 `efficiency_ratio <= range_efficiency_ratio(0.35)`”**，自相关未参与判定。若本意是“震荡=低/负收益持续性”，阈值过松。
- **涉及文件**：`backend/src/orbit/domain/strategy/regime.py`；`config/config.sample.json`（`strategy.regime_gate`）；`backend/tests/test_regime.py`；分析用 `backend/tools/calibrate_matrix.py` / `backend/tools/replay_matrix.py`。
- **改动分两步**：
  1. **先分析、后决策**：用现有回放/标定工具在**训练窗**对比“收紧 RANGE 自相关阈值（如要求 `autocorr <= 0.2`）”与现状对 RANGE 命中率和外样本收益的影响，把结论（数据）写回本文件。
  2. 依据结论二选一：**要么**保留 `0.95` 但在代码加注释说明它只是病态值保险；**要么**改默认阈值收紧 RANGE 语义，并附训练窗对照数据。
- **验收**：`test_regime.py` 增加“低 ER + 高自相关”与“低 ER + 低自相关”两类样本的分类断言，把当前语义钉死；若改默认值，须附训练窗（非验证窗）对照数据。
- **约束**：严禁按验证集/某次回放结果反推阈值。
- **训练窗对照**：固定预注册候选 `0.95` 与 `0.20`，使用 BTCUSDT/ETHUSDT × 15m/1h 各 5 折；15m 训练/验证为 5760/1920 根，1h 为 2880/960 根。按 20 个训练窗汇总，`0.95` 的已知样本 RANGE 命中率为 `73088/86020 = 84.97%`、完整引擎训练净收益 `+10.54 USDT`；`0.20` 为 `67167/86020 = 78.08%`、训练净收益 `+2.81 USDT`。收紧阈值仅减少 `6.88` 个百分点 RANGE 暴露，却使训练表现下降 `7.74 USDT`。
- **隔离验证（只报告、不据此选参）**：`0.95` 外样本合计 `-7.68 USDT`、盈利折 `6/20`；`0.20` 为 `-8.56 USDT`、盈利折 `5/20`，没有提供反转训练结论的证据。
- **决策**：保留默认 `0.95`。代码已明确其语义是低 ER 条件下的极端正持续性病态保险，RANGE 分类有意以 ER 为主判据，而不是把 `0.95` 误解为有效的第二重过滤器。新增“低 ER + 自相关 >0.95 → TRANSITION”及“低 ER + 低自相关 → RANGE”测试锁定该契约；未改 live 默认开关与任何交易参数。
- **验收结论（Claude，2026-07-13）：通过。** 严格遵守「先分析后决策 / 隔离验证只报告不选参」纪律：训练窗（非验证窗）数据支撑保留 `0.95`，收紧到 `0.20` 在训练窗即劣化，未据验证集反推。R2 只改注释+测试+文档，**零交易行为变更**；`test_low_er_with_extreme_positive_autocorrelation_is_not_range`（autocorr>0.95→TRANSITION）证明该上限是载荷判据、非空条件，契约锁得住。后端 `193 passed / 1 skipped`。合并在 `main`（`6b27cff`）。**注**：训练/验证的具体 USDT 数值为 Codex 标定器产出，我未在本机重跑 20 折矩阵（需数据缓存且本机 fapi 451），因 R2 不触及任何代码路径、重跑矩阵与该改动不成比例。

### 任务 R3：收敛 paper 收盘推进与引擎单一入口（已完成，2026-07-13）

- **问题**：`backend/src/orbit/application/symbol_states.py` 的 `advance_state_with_price`（约 83–102 行）手工重复了 `tick_count / high_since_base / low_since_base / regime_gate.update / lifecycle.update_trend_tracking / resolve_state` 这套收盘推进逻辑，与 `engine._on_price` 重复，且已有细微差异（`_on_price` 仅在收盘 tick 自增 `tick_count`，而 `advance_state_with_price` 每次都自增）。两条路径未来容易漂移。
- **涉及文件**：`backend/src/orbit/application/symbol_states.py`；`backend/src/orbit/domain/strategy/engine.py`。
- **改动**：在 `EventEngine` 暴露一个只做“推进指标 + 生命周期，不决策不成交”的收盘推进方法（如 `advance_close(state, price, close_time)`），让 `advance_state_with_price` 复用它，消除重复；paper 决策仍由 `execute_paper_tick` 承担。
- **验收**：现有 paper 相关测试（`test_market_data` / `test_account_runtime` / paper 执行）保持绿；新增测试断言 `advance_state_with_price` 与引擎收盘推进对 `regime_*` / 生命周期字段结果一致。
- **约束**：不改变 paper 决策与成交时序。
- **完成结果**：`EventEngine.advance_close()` 统一负责 close tick、价格/极值、K 线时间、Regime Gate、mark-to-market、趋势跟踪和生命周期解析；`SymbolStateService.advance_state_with_price()` 已收敛为单行委托。dry_run/replay 的 `_on_price` 复用同一入口，并通过延后生命周期最终解析保持原有“收盘推进 → 决策/成交 → 最终解析”时序；paper 仍由 MarketFeed 推进后交给 `execute_paper_tick` 决策。新增字段对照测试确认应用层与引擎投影一致且仓位/PnL 不变。
- **验收结论（Claude，2026-07-13）：通过。** 行为保持型重构：`_on_price` 收盘路径用 `resolve_lifecycle=False`，状态仍在决策后 resolve，时序不变；`tick_count` 漂移（原 `advance_state_with_price` 每次自增 vs `_on_price` 仅收盘自增）已收敛为单一入口一次自增。`mark_to_market` 与 `update_trend_tracking` 顺序微调不影响结果（两者字段互不依赖）。等价性测试 + 全套 `195 passed / 1 skipped` 确认无回归。合并在 `main`（`7d28698`）。

### 已在本文档登记、无需 Codex 改码的观察

- **regime 冷启动静默期**：累计到 `min_samples`(默认 20) 根收盘前，regime 为 `UNKNOWN`，而 `UNKNOWN / TRANSITION / TRENDING` 均禁止利润搬运与双腿重建。`interval=1h` 时新 symbol 约 20 小时内不会有搬运；`regime_price_history` 存入 state，重启不丢，但新初始化的 symbol 会重新预热。此为**预期行为**，paper/live 上线首日需据此设期望（见下方「策略逻辑已知缺口」）。

## 策略逻辑下一批缺口修复计划（2026-07-13，交付 Codex 执行）

承接 Regime Gate 修复计划，处理「策略逻辑已知缺口」里的下一批。**本计划交由 Codex 执行，每个任务完成后由 Claude 对其提交做 review。**

### 全局约束（所有任务通用）

1. 每个任务独立提交，conventional commits。
2. 全程保持测试绿：`cd backend && python3 -m pytest tests/ -q`（当前基线 195 passed / 1 skipped）。
3. 不改动 live 通道任何默认开关。
4. **凡改变「哪些交易会触发」的改动，一律 config 门控、默认保持现有行为（neutral/off）**；是否翻默认值必须由**训练窗**（非验证窗）walk-forward 对照数据决定，禁止为让某次回放/验证集通过而调参（沿用 R2 纪律）。用 `backend/tools/calibrate_matrix.py` / `replay_matrix.py` 出对照，结论写回本文件。
5. 每个任务完成后在本文件对应条目登记结果（含关键数据）。

### 任务 S1：趋势进入补斜率/时间维度（已完成，2026-07-13）

- **问题**：`backend/src/orbit/domain/strategy/lifecycle.py` 的 `is_trend_entry_candidate`（70–76 行）只判断单点 `|move| ≥ θ_t(trend_confirm_move_pct_from_base)`；`event_rules.py` 的 `loss_side_reduction_rule`（120–131 行）用「连续 N=trend_entry_confirm_ticks 满足该条件」做进入确认。**level + tick 计数，没有速度/斜率维度**：慢速阴跌只要在 base 之外磨够 N 根，就与快速暴跌同等触发亏损腿减仓。标定已多次指出趋势减仓几何是主要负贡献来源，进入过松是其一。
- **涉及文件**：`backend/src/orbit/domain/strategy/lifecycle.py`（`is_trend_entry_candidate`）；`config/config.sample.json`（`events.loss_side_reduction.trigger`）；`backend/tests/test_engine.py` / 新增 `test_lifecycle`。
- **改动**：为进入候选增加一个**速度/ATR 归一化维度**——例如要求最近 `k` 根的位移速率（`|move| / 窗口根数`，或用 `high_since_base/low_since_base` 与 ATR 的比值）达到阈值。新增 config 旋钮（如 `trend_entry_min_velocity_pct_per_tick` 或 `trend_entry_atr_mult`），**默认取中性值使当前行为不变**（旋钮未配置或取 0 时退回现有纯 level+tick 逻辑）。
- **验收**：① 单元测试——同样越过 θ_t 的「慢磨 N 根」与「快速 N 根」两条路径，在速度旋钮开启时前者不进入、后者进入；旋钮关闭（默认）时两者行为与现状一致（现有 `test_loss_side_reduction_after_trend_confirm` 等保持绿）。② 训练窗 walk-forward 对照：默认（off）vs 开启速度门 的 RANGE/TREND 触发数、训练净收益、盈利折，写回本文件；据训练窗结论决定是否翻默认。
- **约束**：默认零行为变更；不据验证集选参。
- **完成结果**：趋势进入新增最近 `k` 个 close tick 的绝对位移速度 `|P_t/P_{t-k}-1|×100/k`，由 `trend_entry_velocity_window_ticks` 与 `trend_entry_min_velocity_pct_per_tick` 控制；阈值缺省或为 `0` 时仍执行原有纯 level + 连续 tick 逻辑。速度历史独立于 Regime Gate 维护，并随初始化、存量状态补全和重锚正确建立或清零；阻断上下文同步暴露当前速度与要求阈值。新增慢磨/快速路径及默认中性行为测试。
- **训练窗对照**：预注册候选为 off（`min_velocity=0`）与开启（`k=3`、`min_velocity=0.5%/tick`）。使用 BTCUSDT/ETHUSDT × 15m/1h 各 5 折，15m 训练/验证窗为 5760/1920 根、1h 为 2880/960 根，仅回放 20 个训练窗。off：RANGE 搬运 `207` 次、TREND 减仓 `469` 次、训练净收益 `+10.545 USDT`、盈利折 `10/20`、手续费/滑点 `3.583/1.433 USDT`；开启：RANGE 搬运 `233` 次、TREND 减仓 `431` 次、训练净收益 `+5.710 USDT`、盈利折 `10/20`、手续费/滑点 `3.659/1.464 USDT`。
- **决策**：速度门确实过滤了 `38` 次趋势减仓，但训练净收益下降 `4.835 USDT`，盈利折无改善且成本略升，因此不翻默认值。保留该能力供后续按周期独立标定，样例配置默认 `trend_entry_min_velocity_pct_per_tick=0.0`，无 live 默认行为变化；未使用验证窗选参。
- **验收结论（Claude，2026-07-13）：通过。** 机制正确：velocity=尾部窗口端点速度 `|P_t/P_{t-k}-1|×100/k`，`min_velocity≤0` 时短路回退到纯 level+tick（默认零行为变更，`test_default_zero_velocity_gate_preserves_level_only_behavior` 证明）。`test_velocity_gate_distinguishes_slow_drift_from_fast_move` 是有效载荷——慢速逼近因尾部窗速度不足被否（滑窗使中途跳空也会归零候选计数），快速路径通过。训练窗对照数据完整、结论诚实（首候选劣化 → 不翻默认、保留供按周期标定），严守「只在训练窗选参」。后端 `197 passed / 1 skipped`。合并在 `main`（`9f088b8`）。**注**：训练窗 USDT 数值为 Codex 标定器产出，未在本机重跑矩阵（需数据缓存/fapi）；因默认 off、零行为变更，重跑与该改动不成比例。

### 任务 S2：利润搬运可行性纳入加仓腿往返成本（已完成，2026-07-13）

- **问题**：`backend/src/orbit/domain/strategy/actions.py` 的 `inverse_skew_actions`（约 100–134 行）用 `projected.net_realized`（只扣**减盈利腿**这一腿的手续费）与 `min_net_profit_usdt(0.05)` 比较来判定搬运是否可行。但同一次搬运还会**加一条亏损腿**（`ADD_LOSS_SIDE`），这条腿将来平仓要再吃一轮手续费+滑点。当前判据没算这条，导致「减腿看着赚 0.05，但配对的加腿未来平仓成本 > 0.05」的高频小额搬运仍会通过——手续费 churn。
- **涉及文件**：`backend/src/orbit/domain/strategy/actions.py`（`inverse_skew_actions`、`preview_reduce`）；`config/config.sample.json`（`events.profit_transfer.sizing`）；`backend/tests/`（actions/engine 测试）。
- **改动**：可行性判据改为 `net_realized ≥ min_net_profit_usdt + 预估加仓腿往返成本`（加仓 notional × (taker_fee_rate×2 + slippage)）。用 config 旗标门控（如 `require_add_leg_roundtrip_coverage`，**默认 false 保持现有行为**）。
- **验收**：① 单元测试——构造「减腿净利略高于 min_net_profit 但不足以覆盖加腿往返成本」的场景，旗标开启时搬运被拒、关闭时通过。② 训练窗对照：开/关旗标的搬运次数、手续费拖累、训练净收益，写回本文件。
- **约束**：默认零行为变更；不据验证集选参。
- **完成结果**：`inverse_skew_actions` 在算出实际 `ADD_LOSS_SIDE` 数量后，按 `add_notional × (taker_fee_rate×2 + slippage_bps/10000)` 估算加仓腿往返成本；`require_add_leg_roundtrip_coverage=true` 时要求 `projected.net_realized ≥ min_net_profit_usdt + estimated_roundtrip_cost`，默认 `false` 时仍使用原门槛。action sizing 新增 `estimated_add_leg_roundtrip_cost` 与 `required_net_profit`，便于计划和事件审计。新增边界测试确认原门槛刚通过但成本覆盖不足时，仅开启旗标会拒绝搬运。
- **训练窗对照**：使用与 S1 相同的 BTCUSDT/ETHUSDT × 15m/1h 共 20 个训练窗，仅切换 `require_add_leg_roundtrip_coverage`。off 与 on 均为搬运 `207` 次、训练净收益 `+10.545 USDT`、盈利折 `10/20`、手续费 `3.583 USDT`、滑点 `1.433 USDT`，四个市场逐项结果完全一致。
- **决策**：当前 `min_net_profit_usdt=0.05` 的训练样本没有落入“原门槛通过但加腿成本覆盖不足”的边际区间，训练数据不支持翻默认；样例配置保持 `false`，零默认行为变化。该开关作为更严格的实盘成本保护保留，后续只有在交易成本或最小利润参数改变时再独立标定；未使用验证窗选参。
- **验收结论（Claude，2026-07-13）：通过。** 判据 reorder 到 add_qty 之后（成本需 add_qty），off 时 `required=min_net_profit`、行为与原先一致（无副作用）；`test_profit_transfer_can_require_add_leg_roundtrip_coverage` 是有效载荷（净利介于 `min_net_profit` 与 `min_net_profit+往返成本` 之间，off 过、on 拒）。训练窗 off/on 逐市场完全一致——诚实反映当前 `min_net_profit=0.05` 下无样本落入边际带，符合「latent 保护、不翻默认」的结论。后端 `198 passed / 1 skipped`。合并在 `main`（`acefab9`）。**非阻断小提示（供未来翻默认时修正）**：`estimate_add_leg_roundtrip_cost` 用 `2×taker_fee + 1×slippage`，而真实往返（开+平加仓腿）滑点应计两腿，当前少算 1×slippage（`slippage_bps=2` 时约 0.02% notional，影响极小）；默认 off 不影响现状，若日后据成本标定开启，建议改为 `2×(taker_fee + slippage)`。

### 任务 S3：清理死配置 + 对账陈旧缺口（已完成，2026-07-13）

- **问题**：① `restore_loss_side_only_to_base` 配置键在新 Δ* 模型下已无任何代码引用（`grep` 确认 `exposure.py`/`actions.py` 均不读它），属死键；且「已知缺口」里「利润搬运口径待澄清（该键 + 整次搬运被跳过）」在新模型下已不成立——新模型 `inverse_skew_actions` 中减盈利腿恒执行、加亏损腿才是可选，止盈不会被跳过。② 「已知缺口」里「风控剩余维度未补齐（组合级回撤/C7/快照新鲜度）」与上文「实盘化推进」的「内核风控补全」（C7、`snapshot_max_age_seconds` 600s、`max_total_drawdown_pct`→GLOBAL_STOP 均已落地）自相矛盾。
- **涉及文件**：`config/config.sample.json`；`PROJECT_PROGRESS.md`；如有其他 config 样例。
- **改动**：删除或注释弃用 `restore_loss_side_only_to_base` 死键；补一条回归测试锁定「亏损腿已达/超 base 时，止盈（减盈利腿）仍会执行」；订正「已知缺口」两条陈旧描述（搬运口径、风控维度）与实际代码一致。
- **验收**：新增回归测试通过；文档缺口与代码对齐、无自相矛盾；无 live 开关变更。
- **约束**：纯清理与对账，不改变任何交易行为。
- **完成结果**：从 `config/config.sample.json` 和产品方案的两段配置示例中删除无代码引用的 `restore_loss_side_only_to_base`；新增动作回归测试，锁定亏损腿已达或超过 base 时仍会生成 `REDUCE_PROFIT_SIDE`，不再出现旧模型“整次搬运被跳过”的语义。同步订正本文件、产品技术方案、架构文档与策略逻辑文档：组合级 `GLOBAL_STOP`、C7 自融资账本、计划快照新鲜度拦截、趋势进入速度门和亏损腿重建均已落地；保留 STOP 后人工复核恢复、UI 风控投影、Funding 和参数标定等真实剩余项。仅删除死键、增加测试并对账文档，没有改变交易实现或 live 开关。
- **验收结论（Claude，2026-07-13）：通过。** 死键 repo-wide 零残留（`.py`/`.json` grep 确认，`199 passed` 印证无 KeyError）；`test_profit_transfer_reduces_profit_leg_when_loss_leg_is_above_base` 是有效载荷（short≥base 时 `action_set.actions[0]` 为 `REDUCE_PROFIT_SIDE`）。四份文档对账准确、无自相矛盾、无过度声称：STRATEGY_LOGIC 参数表删除死键行、`max_total_drawdown_pct` 从「未接线」改为已落地，且诚实保留 `min_position_distance/target_price_distance（未接线）`、STOP 后恢复、Funding、参数标定等真实剩余项。零交易行为变更、未动 live 开关。合并在 `main`（`837f051`）。

## STOP 恢复流程 + 风控 UI 投影修复计划（2026-07-13，交付 Codex 执行）

面向「可运维」这条线，补齐 STOP 后的人工复核恢复与风控前端投影。**本计划交由 Codex 执行，每个任务完成后由 Claude 对其提交做 review。T2 依赖 T1（消费其 endpoint 与 snapshot 字段），须 T1 先合并。**

### 背景（现状确认）

- per-symbol `state="STOPPED"` 是**持久化死锁**：`MAX_SYMBOL_DRAWDOWN` 触发 `execute_stop_unwind` 拆对冲全平并置 `STOPPED`；此后 `engine._on_price` / `execute_paper_tick` 首分支 `if state.get("state")=="STOPPED"` 短路，只 emit 风险事件、永不再交易。拆平后已实现亏损被锁定，`symbol_stopped`（`total_pnl < -limit`）也保持 true，**双重冻结、无任何恢复入口**。
- `StrategyControlService` 只有策略级 `set_running/emergency_stop/resume`（整体状态 + 账户 `paused_by_admin`），**不清 per-symbol STOPPED latch**。
- 组合级 `GLOBAL_STOP` 由 `policy.portfolio_stopped` 每 tick 重算、**回撤恢复即自动清除**，不是 latch——本计划不需为它做恢复，只需在 UI 显示其激活态。
- snapshot 只暴露扁平 `risk_events`（前 60）与 `risk_status`（normal/watch），**没有结构化的 STOPPED symbol 列表 / GLOBAL_STOP 激活标志**；`RiskPage.vue` 只有策略级「恢复运行」（`resumeSystem`），无 per-symbol 复核恢复。

### 全局约束

1. 每个任务独立提交，conventional commits；保持测试绿（基线 `199 passed / 1 skipped`）。
2. 恢复是**状态变更的人工动作**：必须管理员权限 + 写 `admin_audit_logs`，且必须显式指定被恢复的 `account_id::symbol`，不做批量隐式恢复。
3. 不改动 live 通道默认开关；`plan_only` / 只读语义不变。
4. 前端改动本机无 node，`npm run check/build` 需 Windows 侧复验（沿用既有前端验证约定）。
5. 完成后在本文件对应条目登记结果。

### 任务 T1：per-symbol STOPPED 人工复核恢复流程（已完成，2026-07-13）

- **问题**：见上「背景」——STOPPED 是永久死锁，无管理员复核恢复路径。
- **涉及文件**：`backend/src/orbit/application/strategy_control.py`（或新 `SymbolRecoveryService`）；`backend/src/orbit/application/symbol_states.py` / `domain/strategy/lifecycle.py`（复用 `reanchor` 语义）；对应 FastAPI router（系统控制组）；`backend/src/orbit/application/snapshot_queries.py`（暴露 STOPPED 列表）；`backend/tests/`。
- **改动**：新增管理员用例 `resume_stopped_symbol(account_id, symbol, *, actor, reason)`：① 校验该 `account_id::symbol` 当前确为 `STOPPED`，否则拒绝；② 以当前价重锚（复用 `StrategyLifecycle.reanchor` 语义）→ `BALANCED`，并**重置回撤基准**（如把 `budget_usdt` 基线对齐到当前 equity，使 `symbol_stopped` 不会因锁定的历史已实现亏损立即再触发），使该 symbol 下个 tick 可正常参与决策；③ 写 `admin_audit_logs`（before/after 状态、operator、reason）。snapshot 结构化暴露 `stopped_symbols`（`account_id::symbol`、回撤、已实现亏损、`stopped_at`）。
- **验收**：应用层测试——① 恢复一个 STOPPED symbol 后其 `state` 回到 `BALANCED` 且下一 tick 不再被首分支短路（可正常生成动作）；② 恢复非 STOPPED symbol 被拒绝；③ 写入了管理员审计；④ 权限校验（非管理员拒绝）；⑤ snapshot 含 `stopped_symbols` 结构化字段。
- **约束**：仅在显式管理员动作下恢复、必审计；不绕过 `plan_only`；不改交易实现的正常路径。
- **完成结果**：新增独立 `SymbolRecoveryService` 与 `POST /api/admin/stopped-symbols/resume`。用例要求管理员、明确 `account_id::symbol` 和必填 reason；仅接受当前 `STOPPED` 状态。恢复时复用 `StrategyLifecycle.reanchor()` 回到 `BALANCED`，保留累计已实现盈亏和账户账务历史，以恢复时总 PnL 写入 `risk_drawdown_baseline_pnl_usdt`、恢复时权益写入 `risk_drawdown_budget_usdt`，后续 symbol 回撤只计算恢复后的新增损益；gross、C7、plan_only 和 live 开关不变。恢复动作写 `RESUME_STOPPED_SYMBOL` 管理员审计并进入持久化白名单。
- **结构化投影**：STOP 拆平时记录 `stopped_at`；snapshot 新增 `stopped_symbols`，逐项包含 `account_id::symbol`、回撤金额/比例、已实现亏损、权益和停止时间，并按账户权限过滤。管理员权限能力新增 `can_resume_stopped_symbol`。
- **验收结果**：管理员恢复后 state 为 `BALANCED`、风险基准归零且下一 tick 正常生成 `POSITION_REBUILD`；非 STOPPED、非管理员、空 reason 均拒绝且不写审计；API 成功路径返回恢复后的 snapshot。后端全量 `204 tests OK`，`npm run check` / `npm run build` 通过。
- **验收结论（Claude，2026-07-13）：通过。** crux 端到端接线正确：`RiskContext.drawdown_pnl_usdt = total_pnl − baseline`、`effective_drawdown_budget`，`evaluate_risk`/引擎/`plans.symbol_risk_context` 一致消费；fresh/存量 symbol baseline=0、budget 回退，**行为与原先完全一致（无回归）**，旧状态 `.get(... ) or default` 平滑迁移。crux 被有效载荷证明——`test_admin_can_resume_stopped_symbol_and_reset_drawdown_baseline` 断言恢复后 `symbol_stopped==False` 且下一 `on_tick` 真的产出 `POSITION_REBUILD`、无 `MAX_SYMBOL_DRAWDOWN`、state≠STOPPED，非死锁复现。五条验收全覆盖（恢复→可交易/非STOPPED拒绝/审计/权限/snapshot 结构化）。HTTP 端 `Depends(require_admin)` + 服务层 `is_admin` 双重门控、成功才写审计、走事务。后端 `203 passed / 1 skipped`（+4）。合并在 `main`（`39b8a25`）。**小观察（非阻断）**：`RiskState.total_pnl_usdt` 现返回 baseline 调整后的值，仅对已恢复 symbol 与原始总 PnL 不同（对未恢复 symbol baseline=0 无差异），用于回撤语义更贴切，不影响正确性。

### 任务 T2：风控 UI 完整投影（已完成，2026-07-13）

- **问题**：风控页无 per-symbol STOPPED 视图与复核恢复入口，GLOBAL_STOP 激活态不可见，`info` 级 blocked 决策与 material 告警混在一张表。
- **涉及文件**：`backend/src/orbit/application/snapshot_queries.py` / `portfolio_views.py`（补结构化风控投影：`global_stop` 激活标志、`stopped_symbols`、blocked 决策摘要）；`frontend/src/pages/RiskPage.vue`；`frontend/src/stores/appStore.js`；`frontend/src/api/client.js`。
- **改动**：① snapshot 暴露结构化 `risk_state`（`global_stop` 激活布尔、`stopped_symbols` 列表、`blocked_decisions` 摘要）；② `RiskPage` 增加 STOPPED symbols 面板，每行带「复核恢复」按钮（确认弹窗 + 必填 reason，调用 T1 endpoint）；GLOBAL_STOP 激活时顶部横幅告警；把 `info` 级 blocked 决策独立成一区，避免污染 material 告警表。
- **验收**：① 后端测试——snapshot payload 含新的结构化 `risk_state` 字段（`global_stop`/`stopped_symbols`/`blocked_decisions`）；② 前端渲染 STOPPED 面板与恢复动作、GLOBAL_STOP 横幅、blocked 独立区（import/export 交叉验证 + 类名核对）；③ `npm run check/build` 需 Windows 侧复验并在本文件登记。
- **约束**：恢复动作只经 T1 审计化 endpoint；只读/`plan_only` 语义不变；不新造后端未提供的数据。
- **完成结果**：snapshot 新增结构化 `risk_state`，统一投影组合级 `global_stop`、按账户可见性过滤的 `stopped_symbols` 和 `info` 级 `blocked_decisions`。组合回撤判断抽成执行计划与风险快照共用函数，避免 UI 状态与内核计划分叉；保留原 `risk_events` 契约供既有页面兼容。风控页新增 GLOBAL_STOP 顶部横幅、STOPPED 币种复核面板、实质风险告警区和独立决策阻断区；每个 STOPPED 行仅在权限能力允许时提供「复核恢复」，确认对话框强制填写原因并只调用 T1 审计化 endpoint。HTTP 200 的业务拒绝不会覆盖当前应用状态。
- **验收结果**：新增 snapshot 风险结构、组合回撤、blocked 分类与账户权限过滤测试；后端全量 `207 tests OK`。`npm run check`、`npm run build`、前端 import/export 交叉检查、关键类名核对及 `git diff --check` 均通过。未改变 `plan_only` / `read_only` 或 live 默认开关。
- **验收结论（Claude，2026-07-13）：后端通过；前端静态通过、构建待 Windows 复验。** 后端结构化投影正确：`risk_state`={`global_stop`（从真实账户快照重算组合回撤，与执行计划共用函数）、`stopped_symbols`、`info` 级 `blocked_decisions`}，业务用户按账户可见性过滤；后端 `206 passed / 1 skipped`（+3）。前端静态核对：模板四要素齐全（GLOBAL_STOP 横幅 / STOPPED 面板+管理员限定「复核恢复」/ 实质告警 / blocked 独立区）；恢复 modal 强制 reason（前端 + 后端双校验）；`percent/displayTime/openRecovery/closeRecovery/confirmRecovery` 均已定义，`resumeStoppedSymbol`/`riskState`↔appStore↔`resumeStoppedSymbolRequest`↔client 的 import/export 交叉验证干净；`can_resume_stopped_symbol=is_admin` 已进 auth 载荷，且真正安全边界是 endpoint 的 `Depends(require_admin)`（前端 flag 仅控显隐）。合并在 `main`（`03ecbfc`）。**验证边界（诚实）**：本机无 node，无法执行 `npm run check/build`，也无法验证实际渲染；Codex 声称的「npm 构建通过」在同一 Linux 无-node 环境下无法坐实，**按项目约定仍需 Windows 侧复验后在本文件登记**，在此之前前端构建视为待确认。

## 策略可行性判定（第一优先级，2026-07-13，交付 Codex 执行）

**定位**：在为策略投入运营基础设施（运行模式状态机、Pydantic、testnet 连续运行）之前，先把「这套策略到底能不能过盈利门」判定清楚。**本计划交由 Codex 执行，Claude 逐条验收。**

### 前置事实（已确认，避免重复劳动）

- 准入判据已在 `backend/src/orbit/domain/calibration/estimators.py`：`pi_required`（π>1−(a−c)/θ）、`wilson_interval`、单市场 C8（`admitted = total≥30 且 Wilson 下界 > pi_required`）、matrix 组合门（盈利市场过半 + 组合正期望）。**缺的是成文预注册标准与明确 verdict，不是判据本身。**
- Funding + OHLC 路径已在 `domain/calibration/replay.py` 全量回放标定内（M6，含真实 funding 的 20 折 `-5.93`）。**「funding 进标定」已完成**；剩余的 funding 进实时引擎属运营范畴、不 gate 本判定。
- 已缓存数据仅 `var/calibration/{BTCUSDT_15m,BTCUSDT_1h,ETHUSDT_1h}.json`。**扩多币种/多周期需先 `fetch_klines/fetch_funding`（打 fapi），本机 451——数据获取是 V2 的前置约束，须在 Binance 可达网络完成。**
- 全套 replay 标定在当前几何下反复 FAIL，模块消融定位**趋势减仓几何为主要负贡献**，且参数族扫描未找到可部署配置。

### 全局约束

1. 独立提交、测试保持绿（基线 `206 passed / 1 skipped`）。
2. **严守 walk-forward 纪律**：候选只在训练窗选择，验证窗完全隔离判定；禁止为让某次验证/回放通过而调参。
3. 任何改变交易触发的几何改动一律 config 门控、默认 off，零默认行为变更。
4. 不动 live 默认开关；结论（含负结果）如实写回本文件。

### 任务 V1：成文预注册 testnet 准入协议 + 现状 verdict（已完成，2026-07-13）

- **问题**：准入门散在 `estimators.py`/`replay_matrix.py` 代码里，没有一份成文、预注册的「过什么线才允许进 testnet」标准；历次 FAIL 也没有对齐到一个明确 bar。
- **涉及文件**：新增 `docs/design/ADMISSION.md`；`PROJECT_PROGRESS.md`；只读引用 `estimators.py`/`replay_matrix.py`。
- **改动**：成文钉死准入协议——① 市场×周期×折数矩阵与训练/验证窗定义；② 准入指标与阈值（单市场 C8 Wilson 下界 > `pi_required`、组合正期望、盈利市场过半、最差折回撤上限、必须含 funding+OHLC 路径）；③ walk-forward 纪律与「训练窗选参、验证窗判定」流程；④ 用**现有缓存数据**跑一次，产出对照该 bar 的**明确 go/no-go verdict**（预期 no-go，如实记录，不粉饰）。
- **验收**：ADMISSION.md 成文、阈值明确可复算；附现状 verdict 与逐项指标对照；无调参。
- **约束**：不改代码行为，纯标准 + 判定。
- **完成结果**：新增 `docs/design/ADMISSION.md`，冻结 BTC/ETH × 15m/1h、每市场 5 折的 20 折矩阵，明确训练/验证窗、训练窗选参纪律和输入 SHA-256。联合准入门要求：单市场外样本 C8（至少 30 笔、95% Wilson 下界严格高于 `pi_required`、单次期望为正）；组合正期望且至少 3/4 盈利市场；完整领域引擎在 fixed OHLC、fixed OLHC、myopic 三条路径上均须正收益、至少 3/4 盈利市场、11/20 盈利折、Funding 完整且最差折回撤不超过 5%。阈值在本轮输出前固定，没有根据结果调整。
- **现状 verdict（NO-GO）**：统计部署口径仅 BTCUSDT 1h 产生 9 笔外样本交易，`pi_ci_low=0.120582 < pi_required=0.410000`、单次期望 `-0.306667%`；其余 3 个市场因训练期不准入而空仓，组合只有 9 笔、代理净收益 `-2.76%`、盈利市场 `0/4`。完整引擎 fixed OHLC / fixed OLHC / myopic 分别为 `-7.234039/-6.616807/-5.929452 USDT`，盈利市场 `0/4、1/4、1/4`，盈利折 `5/20、6/20、6/20`；Funding 均完整、最差折回撤均 `3.865260%`，但收益和覆盖门失败。当前不得进入 testnet/paper/live，下一步仅执行默认 off 的 V2 结构候选实验。

### 任务 V2：趋势减仓几何重设计候选 + walk-forward 判定（优先级：高，真正的可行性实验）

- **问题**：负期望根因指向趋势减仓几何，且**参数族扫描已证明「调参数」不够**——需要一次**结构性**改动尝试。
- **前置**：若要纳入 BTC/ETH 之外市场或 ETH-15m，须先在 Binance 可达网络用 `fetch_klines --ohlc` / `fetch_funding` 补 `var/calibration/` 数据；本机 451 无法获取，缺数据时先用现有 BTC/ETH 缓存跑。
- **涉及文件**：`backend/src/orbit/domain/strategy/actions.py`（趋势减仓 sizing）/ `lifecycle.py` / `rules/event_rules.py`（趋势减仓触发）；`config/config.sample.json`（新几何旋钮，默认 off/中性）；`backend/tools/replay_matrix.py`；`backend/tests/`。
- **改动**：在训练窗内**先诊断**哪个几何杠杆最能改善期望（如：把「阶梯逐步减仓」换成「确认后单次决断减仓」、θ_t 放宽使减仓更晚更少、减仓与 excursion+速度双确认绑定、非对称只在强趋势侧减仓），**预注册一个**候选，config 门控、默认 off 实现；在验证窗对照 V1 的 bar 出 go/no-go。
- **验收**：① 单元测试锁定新几何在开启/关闭下的分支行为，默认 off 零行为变更（现有测试绿）；② 训练窗诊断 + 预注册候选 + 验证窗判定数据写回本文件，明确 PASS/FAIL；③ 若 PASS，给出可进入运营链路的结论；若 FAIL，量化说明差距还有多大、下一个几何方向。
- **约束**：默认 off、零默认行为变更；候选只在训练窗选、验证窗判定；不据验证集反推。
- **候选预注册（验证前）**：20 个外层训练窗 close-only 诊断中，当前结构为 `+10.544612 USDT / 10/20` 盈利折，完全关闭趋势减仓为 `-12.739084 USDT / 11/20`；当前 469 次趋势减仓直接实现 `-109.228762 USDT`。训练窗不支持完全关闭，但支持保留首次风险解除并删除“跨零翻向 + 后续阶梯切割”。唯一候选冻结为 `neutralize_counter_trend_skew`：确认趋势后仅在净敞口反向时一次性归零，不建立顺势敞口；配置默认 off。完整预注册见 `docs/design/V2_CANDIDATE.md`，此时尚未读取该候选的验证窗结果。

### 任务 V3：逆势补仓 excursion 深度门（进行中，2026-07-13）

- **训练窗诊断**：当前完整结构为 `+10.538653 USDT / 9/20` 盈利折；只减盈利腿为 `+9.237862 / 12/20`；完全关闭利润搬运为 `+16.229884 / 10/20`。逆势补仓改善少数样本总收益但降低折覆盖，训练窗不支持全开或全关。
- **唯一预注册候选**：`first_rung_loss_side_add_only`。只允许第一档利润搬运补亏损腿，第二档及以后只减盈利腿；配置默认关闭，完整规则与冻结验证门见 `docs/design/V3_CANDIDATE.md`。此时尚未读取该候选的验证窗结果。
- **完成结果**：fixed OHLC / fixed OLHC / myopic 分别为 `-7.483875 / -7.251277 / -6.481023 USDT`，盈利市场 `0/4、1/4、1/4`，盈利折 `5/20、6/20、6/20`；Funding 完整且回撤门通过，但收益、覆盖与 C8 均失败。相比 V1 三条路径还分别恶化 `0.249836 / 0.634470 / 0.551571 USDT`，结论为 **FAIL / NO-GO**，开关保持默认关闭。
- **数据纪律**：现有 20 个验证折已用于 V1/V2/V3，不再视为下一候选的全新外样本。后续可继续训练窗归因，但新的 go/no-go 必须先补充时间上更新、从未参与候选选择的 OHLC+Funding 锁箱区间。

### 任务 V4：有界逆势周期 + 新市场锁箱（进行中，2026-07-13）

- **新锁箱**：已从 Binance USD-M Futures 公共接口抓取 BNBUSDT/SOLUSDT x 15m/1h OHLC 和各 1080 个 Funding 点；四市场各 5 折，共 20 个新验证折。数量、UTC 范围和 SHA-256 已在策略运行前冻结于 `docs/design/V4_CANDIDATE.md`。
- **唯一预注册候选**：`bounded_counter_trend_cycle`，组合 V3 的“仅第一档补亏损腿”和 V2 的“趋势确认后只归零、不跨零翻向”，其余参数及退出/reanchor 规则不变，默认 full 行为不变。此时尚未运行 BNB/SOL 锁箱回放。
- **完成结果**：C8 部署口径仅 6 笔、单次期望 `-0.473%`、净收益 `-2.840%`，明确失败。fixed OHLC / fixed OLHC / myopic 分别为 `+1.456814 / +3.198224 / -0.724717 USDT`，盈利市场 `1/4、2/4、2/4`，盈利折 `9/20、9/20、5/20`；Funding 完整且回撤低于 1%，但收益、覆盖与 C8 未联合过门，结论为 **FAIL / NO-GO**。
- **阶段决策**：停止继续微调当前 V 系列几何。V1-V4 在 BTC/ETH 和全新 BNB/SOL 上均显示利润搬运正贡献会被趋势风险解除与旧仓恢复侵蚀；下一阶段转为策略模型重评，现有 BNB/SOL 锁箱不再作为下一模型的全新外样本。

### 模型重评 M0：固定期限回归收益源审计（已完成，2026-07-13）

- 新增 `horizon_reversion_report` 与 `backend/tools/analyze_reversion_horizon.py`，按固定期限对逆势 excursion 做 reversion/extension/timeout 分类和真实盯市，逐笔扣除 `0.14%` 往返成本。
- BTC/ETH/BNB/SOL x 15m/1h x 1h/4h/8h/24h 共 32 个组合，**成本后正期望为 0/32**；最佳为 SOLUSDT 1h/24h，仍只有 `-0.046136%/次`。22/32 组合毛期望为正，但最高 `+0.093864%`，仍不足覆盖成本。
- **决策**：当前无条件锚点回归收益假设不成立，策略进入研究暂停；停止 V5 式仓位几何开发，不进入 testnet/paper/live。平台型账户、快照、计划、风控和回放能力继续保留。恢复策略开发前必须先有成本后正期望且置信下界过零的独立 alpha，并使用全新锁箱。完整结论见 `docs/design/MODEL_REASSESSMENT.md`。

### 验收结论（Claude，2026-07-13）：V1–V4 + M0 整批通过；策略研究暂停结论成立

- **纪律（重点核验）**：ADMISSION.md 在候选验证前冻结阈值/矩阵/路径，并明文「FAIL 原样记录、禁止调窗/路径/成本/市场追求 PASS」。提交序列每个候选均「先 `docs: preregister`、后 `feat: evaluate`」；抽查 V2 evaluate 提交（`4446f71`）**未删改已冻结候选 spec，只追加结果**（`git show | grep '^-'` 为空）→ 候选在见到验证结果后未被改。V4 识别到 20 折已被 V1–V3 消耗、专门拉全新 BNB/SOL 作锁箱外样本——数据卫生到位。各候选 config 默认 off（`neutralize_counter_trend_skew_only`/`first_rung_loss_side_add_only` 等 = false），零默认行为变更。
- **根因测量 sound**：核验 `horizon_reversion_report` 逻辑正确——逆势押注方向（`gross=-direction*(price/entry-1)`）、reversion/extension/timeout 判定、成本扣减、退出重锚不重叠均无误。结论 32 组合成本后 0/32 为正，与解析事实一致：对冲双腿 `dPnL=Δ·dPrice−costs−funding` 本身不产生收益，唯一 alpha 是锚点回归，而回归成本后为负。**这是真 NO-GO，不是测量假阴性。**
- **决策门解析**：本计划内置的 go/no-go 决策门现解析为 **NO-GO** → 按约定**不投入运营链路**（运行模式状态机 / Pydantic / testnet 均暂缓）。这正是可行性判定前移的价值——在建运营机器前拦住了负期望策略。
- 后端 `215 passed / 1 skipped`。合并在 `main`（`ee9bd88..9d473c6`）。**验证边界（诚实）**：`var/` 标定数据 gitignored、本机不全且 fapi 451，我未在本机重算数值结果；但 verdict 为 NO-GO（无过门造假动机）、输入 SHA-256 已记档、且结论有独立解析支撑，故结论稳健。

### 决策门

**V2 完成记录（2026-07-13）**：预注册候选 `neutralize_counter_trend_skew` 已实现并完成隔离验证。fixed OHLC / fixed OLHC / myopic 分别为 `+0.500907 / -1.924124 / -0.655463 USDT`，盈利市场 `2/4、1/4、1/4`，盈利折 `9/20、6/20、9/20`；Funding 完整且最差折回撤均低于 1%，但收益、市场覆盖、折覆盖及沿用的 C8 统计门未同时通过。结论为 **FAIL / NO-GO**，开关保持默认关闭，不进入 testnet/paper/live。完整实验记录见 `docs/design/V2_CANDIDATE.md`。

V1+V2 完成后是一个**显式 go/no-go 决策点**：过 bar → 才进入运营链路（运行模式状态机 → 账户健壮性 → Pydantic → testnet 连续运行 → 小资金 live，即 Codex 建议的 #1/#5/#2/#6）；不过 bar → 继续几何迭代或重新评估策略，**不提前投入运营基础设施**。

## Alpha 候选 F 系列：Funding Carry 审计（2026-07-13，交付 Codex 执行）

承接 MODEL_REASSESSMENT：无条件锚点回归 alpha 已证伪，恢复策略开发前必须先有一个**成本后正期望、置信下界过零、可预注册**的独立 alpha（MODEL_REASSESSMENT §5）。第一个候选是 **Funding Carry（永续资金费套利）**——理由：funding 是真实、持续、可测量的现金流，不依赖「猜价格回归」；且已有 funding 数据与回放框架，审计成本低。**本计划交由 Codex 执行，Claude 逐条验收。**

### 关键前提（必须写清，决定可审计性）

- 真正的 delta-neutral carry 需要一条 **spot（或第二）腿**对冲方向敞口；当前系统是**纯 USDT 永续**。因此本系列**先用现有 perp+funding 数据做便宜的「必要条件筛查」（F1）**，通过后再补 spot 数据做完整两腿审计（F2）。**不在必要条件成立前建 spot 执行。**
- M0 已知：约 22/32 图形组合「毛期望为正、被成本吃掉」，即成本(0.14%/往返)是主要杀手。Funding carry 的核心问题同样是「funding 是否大到、稳到能覆盖建/平/再平衡成本」。

### 全局约束

1. 独立提交、测试保持绿（基线 `215 passed / 1 skipped`）。
2. 纯离线研究估计器（像 `horizon_reversion_report` 一样纯计算），不碰交易/live 开关。
3. 严守 M0 §5：成本诚实、≥30 非重叠事件、成本后单次期望为正、Wilson 下界过零、参数在开新锁箱前冻结、不依赖恢复旧亏损腿。
4. 结论（含负结果）如实写回本文件；FAIL 原样记录，禁止调阈值/窗/成本追求 PASS。

### 任务 F1：Funding 经济性必要条件筛查（优先级：高，便宜先行，只用现有 perp+funding 数据）

- **预注册（运行前）**：筛查协议已冻结于 `docs/design/FUNDING_CARRY.md`。窗口为 1/3/7/14/30 天，双腿建平成本 `0.38%`、每日再平衡成本 `0.02%`；使用非重叠连续窗口和固定种子 10,000 次 bootstrap。只有同一窗口至少 3/4 市场各自 `>=30` 事件、成本后均值及 bootstrap 下界均大于零，且组合下界大于零，才允许 F2。此时尚未运行 F1 数值结果。
- **完成结果**：BTC/ETH/BNB/SOL x 1/3/7/14/30 天共 20 个组合全部成本后负期望，通过市场均为 `0/4`。组合平均净 carry 分别为 `-0.3849/-0.3947/-0.4143/-0.4493/-0.5269%`，bootstrap 下界全部更低；最好的 SOL 30 天毛 Funding `+0.7090%` 仍低于冻结总成本 `0.98%`，且仅 12 个事件。
- **决策**：**F1 FAIL / Funding Carry NO-GO，F2 不启动**。不获取 spot 锁箱、不建设 spot 执行，也不调整成本/窗口追求 PASS。完整结果见 `docs/design/FUNDING_CARRY.md`。
- **验收结论（Claude，2026-07-13）：通过。** 纪律：预注册协议在跑数前冻结，evaluate 提交（`3410d99`）只追加结果、未回改窗口/成本/判据（`git show | grep '^-'` 为空）；成本口径诚实且明标乐观上界（`gross=Σ|rate|` 假设每次都收到 funding + spot 完美对冲，未计 basis/借币/翻向）。估计器核验 sound：`bootstrap_mean_interval`（固定种子 20260713、10000 重采样、2.5/97.5 分位）、Wilson、percentile 线性插值均正确；`27 passed`。**结论稳健**——乐观上界下 20/20 组合仍成本后为负、通过市场 0/4，真实 carry 只会更差；且长窗口(14/30d)事件数 25/12 本就不过 30 门。合理拒绝了「换 maker 费率/调窗重跑」。合并在 `main`（`a6ef735..3410d99`）。**验证边界（诚实）**：funding 数据 gitignored、本机 fapi 451，未重算数值；但 verdict 为 NO-GO（无造假动机）、乐观上界仍失败、估计器逻辑已验证，故结论可信。

- **目标**：在投入 spot 数据/执行前，先判定 funding 本身是否「大到且稳到」有可能覆盖 carry 成本——若连必要条件都不过，立即 NO-GO 停在此处，成本极低。
- **涉及文件**：`backend/src/orbit/domain/calibration/estimators.py`（新增 `funding_carry_screen` 纯估计器）；`backend/tools/`（新增 CLI）；`docs/design/`（新增 `FUNDING_CARRY.md` 预注册协议）；`backend/tests/test_calibration.py`。
- **改动（先预注册、后跑）**：① 在 `FUNDING_CARRY.md` 预注册筛查定义——持有窗口集合（如 1/3/7/14/30 天，换算成结算次数）、成本口径（建+平两腿往返 + 每次再平衡，保守值成文）、事件采样为非重叠、判据（累计收集 funding − 摊销成本后单次期望 > 0 且 Wilson/自助下界过零）；② 实现纯计算 `funding_carry_screen`：给定历史 funding 序列与价格，逐持有窗口计算「按当时实际 funding 方向持有 delta-neutral 一单位、每结算收 `|rate|×notional`、扣成本」的成本后期望与置信下界（此阶段假设方向腿被 spot 完美对冲、价格 P&L≈0，仅作**必要条件上界**——真实 basis/spot 成本在 F2 才计，须在文档标注「此为上界、真实会更差」）；③ 用现有 BTC/ETH（及 Codex 可获取的 BNB/SOL）funding 数据跑，产出 go/no-go。
- **验收**：① 单元测试锁定估计器（含成本扣减、非重叠、Wilson 下界）；② `FUNDING_CARRY.md` 预注册在跑数前冻结；③ 逐市场成本后期望/下界对照写回本文件，明确 PASS/FAIL；④ 明确标注这是**乐观上界**（未计 basis/spot 成本）。
- **约束**：纯离线；不建 spot 执行；不据结果回调阈值。

### 任务 F2（条件触发：仅当 F1 必要条件通过）：完整 perp+spot carry 审计

- **前提**：F1 PASS 才启动；F1 FAIL 则不做 F2，直接把 Funding Carry 记为 NO-GO 并考虑其他 alpha 或停止。
- **改动**：在 Binance 可达网络补 spot 价格数据（`fetch_*` 打 fapi，本机 451 无法获取——数据前置）；估计器计入两腿建/平/再平衡成本、basis（perp−spot）收敛/漂移、spot 腿费用；在**全新锁箱**上按 M0 §5 完整判据出 go/no-go。
- **验收**：真实两腿 MTM 成本后期望、≥30 非重叠事件、Wilson 下界过零、全新锁箱、参数冻结；结论写回。
- **约束**：同 F1；新锁箱数据在开箱前不得用于选参。

**说明（诚实）**：Funding carry 天花板低、且加密 funding 常在平静期很小/围绕零波动——F1 很可能直接 NO-GO。但它便宜、可证伪快，且过了就是一个有结构支撑的真起点；不过也照样记为负结果、转下一个 alpha 或停止。

## Alpha 候选 G 系列：极端 Funding 反应（2026-07-13，交付 Codex 执行）

承接 F1 NO-GO。第二个 alpha 候选是**极端 Funding 后的短期价格反应**——与已否掉的「无条件锚点回归 / carry」不同信号类别：这是**有条件的方向性**信号（funding 极端 = 拥挤持仓，往往先于价格向反方向修正），行为金融有依据。**它是方向性单腿，纯 perp 即可审计，不需要 spot 数据/执行——同样便宜。本计划交由 Codex 执行，Claude 逐条验收。**

### 全局约束

1. 独立提交、测试保持绿（基线 `215 passed / 1 skipped`）。
2. 纯离线研究估计器，不碰交易/live 开关；成本口径诚实。
3. 严守 M0 §5 与既有纪律：成本后期望为正、Wilson/bootstrap 下界过零、≥30 非重叠事件、**参数在训练窗选择并冻结后才碰锁箱**、无未来数据泄漏（只用入场时点已知的 funding，不用事后值）。
4. 结论（含负结果）如实写回；FAIL 原样记录，禁止调阈值/窗/成本/持有期追求 PASS。

### 任务 G1：极端 Funding 反应信号审计（优先级：高，便宜、纯 perp）

- **训练协议与结论（2026-07-13）**：协议已预先冻结于 `docs/design/G1_EXTREME_FUNDING.md`，随后完整运行 `36` 组训练网格。候选 `0/36`，所有组合均为 `0/4` 单市场合格。按冻结排序最优的诊断组合为 lookback `360`、分位 `95%`、持有 `1h`：合并 `135` 个事件，平均净收益 `-0.0665%`，bootstrap 95% 下界 `-0.2032%`。全网格最高均值组合虽为 `+0.2272%`，下界仍为 `-0.3429%` 且 `0/4` 市场合格。**G1 训练阶段 FAIL；按协议未创建或打开新锁箱，未据结果回调参数。**

- **假设**：funding 处于极端（极正=拥挤多头付费）时，逆着拥挤方向持有短期方向头寸（极正→做空、极负→做多），成本后是否有正期望。
- **涉及文件**：`backend/src/orbit/domain/calibration/estimators.py`（新增纯计算估计器，形如 `horizon_reversion_report`）；`backend/tools/`（新增 CLI）；`docs/design/G1_EXTREME_FUNDING.md`（预注册协议）；`backend/tests/test_calibration.py`；如需新锁箱数据则 `fetch_klines/fetch_funding`（本机 fapi 451，须 Binance 可达网络补）。
- **改动（先预注册、后跑）**：
  1. **训练窗诊断 + 预注册**：在**训练窗**选择信号自由参数并冻结——极端判据（如滚动窗口的分位阈值或绝对阈值）、逆势方向、持有期 H、入场/出场口径；成本为**单腿 perp 往返** `2×(0.05% taker + 0.02% slippage)=0.14%`（成文，不含 maker 优化）；事件非重叠、每次退出后按当时价重设。写入 `G1_EXTREME_FUNDING.md`，冻结后再碰验证/锁箱。
  2. **估计器**：给定 funding + 价格序列，逐事件计算逆势方向头寸持有 H 的成本后净收益（`gross = -crowd_dir×(exit/entry−1)×100`，`net = gross − 0.14%`），输出非重叠事件数、成本后均值、Wilson 与固定种子 bootstrap 下界、胜率、最差事件、回撤。
  3. **隔离判定**：在**从未参与选参**的锁箱（时间上更新的独立区间，或全新市场）上一次性打分。20 折 / BNB / SOL / 既有 funding 均已被前序候选消耗，不得再作全新外样本。
- **验收**：① 单元测试锁定估计器（成本扣减、方向、非重叠、无未来泄漏、Wilson/bootstrap 下界）；② `G1_EXTREME_FUNDING.md` 预注册在碰锁箱前冻结；③ 训练窗选参 + 锁箱判定数据写回本文件，明确 PASS/FAIL（单市场 ≥30 事件、成本后均值>0、下界>0；组合正期望且盈利市场过半）；④ 若 PASS，给出可否进入更严格验证/运营链路的结论；若 FAIL，量化差距。
- **约束**：纯离线、方向性单腿、无 spot；参数只在训练窗选、锁箱一次性判定、不据锁箱回调。

**后续**：G1 PASS → 进入更严格的多市场/多周期锁箱复核再议运营；G1 FAIL → 至多再做一个便宜候选（G2，如 funding 动量/跨币种相对强弱），仍 NO-GO 则「零售成本下此处无唾手可得 alpha」的判断已很有分量，转平台价值（路 B）或收尾（路 C）。

**说明（诚实）**：极端-funding 反转是已知且被广泛套利的信号，edge 大概率很薄、未必扛过 0.14% 成本；但它便宜、可证伪快、信号类别与前两次不同。照例负结果只要方法对即通过。

- **G1/G2 验收结论（Claude，2026-07-13）：均通过；双双训练阶段 FAIL。** Codex 交了 G1（极端 funding 逆势反转）与 G2（跨币种 funding 相对强弱动量），各自 preregister→evaluate。纪律：预注册在选参前冻结，evaluate 只追加结果（G1 仅翻转「状态」行、未改冻结参数；G2 纯追加）。估计器核验 sound：滚动阈值**排除当前结算**、入场在 funding 时点后第一根收盘、事件非重叠、`admitted=≥30 且均值>0 且 bootstrap 下界>0`、成本 `0.14%` 单腿——**无未来泄漏、无 sign 陷阱**（反转与动量两个方向都测了）。G1 训练窗无任何成本后正期望候选 → 按协议不开锁箱；G2 0/9 组合、连成本前毛收益都负。后端 `230 passed / 1 skipped`（+15）。合并在 `main`（`990ef09..c8f5208`）。
- **阶段结论（路 A 已走完）**：至此**四个独立、低成本 alpha 候选全部 NO-GO**——无条件锚点回归（M0，0/32）、Funding carry（F1，乐观上界 0/20）、极端 funding 反转（G1，训练无候选）、funding 相对强弱动量（G2，0/9）。共同根因是零售成本墙（0.14–0.38%/往返）吃光弱信号。按预注册的收敛机制，**停止继续枚举便宜 alpha**，转平台价值（路 B）或项目收尾（路 C）决策。策略保持 `plan_only/read_only`，不进 testnet/paper/live。

### 任务 G2：Funding 跨币种相对强弱动量（最后一个低成本候选）

- **训练协议与结论（2026-07-13）**：协议已预先冻结于 `docs/design/G2_FUNDING_RELATIVE_STRENGTH.md`，随后完整运行 `9` 组训练网格。候选 `0/9`，全部组合净均值为负。最优诊断组合为 lookback `3天`、holding `1天`：`135` 个事件，价格贡献 `-0.0023%`、Funding 贡献 `-0.0082%`、毛收益 `-0.0105%`、成本后净收益 `-0.1505%`，bootstrap 95% 下界 `-0.3050%`；四市场覆盖门通过但统计门失败。**G2 训练阶段 FAIL；未创建或打开新锁箱，未测试反向或回调参数。**
- **决策**：F1 Funding Carry、G1 极端 Funding 反转、G2 Funding 相对强弱动量均已按预注册规则 NO-GO。停止继续枚举低成本 alpha；下一步应在平台价值路线（数据同步、执行计划、风控审计、paper/live 基础设施）与项目收尾之间作明确选择，而不是继续调参寻找策略正收益。

## 研究平台（方向 1）前端化计划（2026-07-13）

**产品决定**：转向平台价值，**先做方向 1**——把现在只有命令行的「诚实标定/回测体检机」做成可界面操作；找到合适策略后再做方向 2（多账户监控+风控台，主要是把现有 DDG 专属页面通用化）。

### 首要设计律（贯穿所有阶段，最高优先级）

**UI 必须保住这台机器的诚实，不得成为「自由调参重跑到通过」的骗人回测。** 硬性护栏：
1. 预注册（信号定义/参数/成本/矩阵/阈值）一旦冻结即**不可改**，只能新建新候选；
2. 锁箱（held-out 数据）**只能开一次**，开箱是记录在案的一次性动作；
3. 运行结果**只追加**，不可覆盖或删除既有 verdict；
4. verdict 永远对照**预注册时固定的** bar，不能事后移动阈值/窗/成本/市场集合。

这条是平台价值的命根子，任何阶段实现都不得给出绕过它的后门。

### 范围决定（2026-07-13 已拍板）

- **自己用**（内部工具，非对外产品）→ 保持精简：单管理员操作即可，不做多用户/权限/精致视觉，够看清、够操作即止；不过度工程。
- **点一下就跑**（UI 服务器端触发运行）→ 需要后台 job runner，但因自己用可做得简单（进程内后台任务、单人、无队列）。
- **关键现实**：绝大多数标定只读本地缓存 `var/calibration/*.json`、**不碰网络**——「在缓存数据上跑评估」任何机器可跑（本机 451 也行）；**只有「拉新数据」需 Binance 可达网络**。二者在 UI/后端明确分开，拉数据失败时清晰报错、不影响跑评估。

### 交付给 Codex 的任务（P0/P1 先做，P2 随后；每个 Claude 逐条验收）

**全局约束**：焊死上面「首要设计律」四条护栏；不改 live 开关；复用现有 `estimators.py`/`replay.py`/screen 工具，不重写策略/标定逻辑；前端本机无 node，`npm run check/build` 需 Windows 复验；测试保持绿。

**任务 UI-P0：后端只读研究 API + 结构化读模型（优先级：高）**
- **涉及文件**：新增 `backend/src/orbit/application/research/`（读模型服务）+ `api/routers/research.py`；`bootstrap.py` 装配；`backend/tests/`。
- **改动**：① 数据目录读模型——扫 `var/calibration/`，列已缓存数据集（市场/周期/行数/区间/SHA-256）；② 候选注册表——定义结构化候选记录（id、信号定义、参数、成本、矩阵、阈值、`frozen_hash`、`frozen_at`、status、verdict、`lockbox_opened_at`），存于**只追加**存储（`var/research/registry.json` 或 MySQL 表），并把既有 M0/F1/G1/G2 回填为初始记录；③ 结果读模型——结构化读取 `var/calibration/*.json` 报告。只读 API：`GET /api/research/datasets`、`/candidates`、`/candidates/{id}`、`/results/{id}`。
- **验收**：只读端点返回结构化数据；候选记录含冻结哈希与 verdict；写入路径强制「只追加、冻结后不可改」（单测覆盖：改已冻结候选被拒）；不触碰 CLI 计算逻辑。
- **完成结果（2026-07-14）**：新增 `application/research/{catalog,candidates}.py`、`persistence/research_registry.py`（哈希链只追加候选注册表）、`api/routers/research.py`（4 个 GET）；种子回填既有候选（含 `frozen_hash`/verdict）；数据目录读模型带 SHA-256；结果读模型不接受任意路径。
- **验收结论（Claude，2026-07-14）：通过。** 纯只读——router 仅 `GET /datasets /candidates /candidates/{id} /results/{id}`，无任何写端点；catalog 服务只有读方法。注册表护栏严格：**哈希链防篡改**（加载校验 sequence/chain/fingerprint）+ `append()` 遇已存在 ID 直接拒。`test_frozen_candidate_cannot_be_changed_or_replaced` 断言「改已冻结候选→raise frozen / 替换→raise cannot be replaced」——**关键护栏真验证**；种子候选含 64 位 frozen_hash + verdict；结果读模型无路径穿越。`264 passed`（+5）。合并在 `main`（`6c357fa`）。路线图第 2 项完成。

**任务 UI-P1：研究平台前端（只读先行）**
- **涉及文件**：新增 `frontend/src/pages/ResearchPage.vue`（或小页面组）；`stores/appStore.js`、`api/client.js`；导航加入口。
- **改动**：三块只读视图——① 数据目录；② **候选履历「墓地」**（列出测过的假设 + PASS/FAIL 徽章，负结果本身是 IP）；③ 候选明细（逐市场/逐折对照**预注册固定 bar**、verdict、冻结时间与锁箱开箱溯源）。
- **验收**：三视图渲染 UI-P0 数据；import/export 交叉验证 + 类名核对；`npm run check/build` Windows 侧复验后登记。
- **完成结果（2026-07-14）**：新增 `ResearchPage.vue`（数据目录带过滤 + 候选墓地 PASS/FAIL 徽章 + 候选明细逐市场/逐折对照 verdict）；`api/client.js` 加 4 个研究 GET；`appStore.js` 加 research state + `loadResearchCatalog/selectResearchCandidate/selectResearchResult` 链式加载；App.vue 导航加「研究平台」入口。后端未动（`264 passed`）。
- **验收结论（Claude，2026-07-14）：后端未动、前端静态验证通过；构建/渲染待 Windows 复验。** import/export 交叉验证干净——4 个 client 函数打对 P0 端点、appStore 全部导入并导出 3 个 action、ResearchPage 导入 `store`/3 action 均 resolve；模板引用的 `isPass/normalizeEvidence/evidenceRow/firstNumber` 等**均在脚本定义**；`onMounted(loadResearchCatalog)` 挂载即加载；App.vue 导航 import+入口+路由+渲染完整接入。纯只读消费 P0（无写入口）。合并在 `main`（`40bb010`）。**验证边界**：本机无 node，`npm run check/build` 与实际渲染需 Windows 侧复验后补记。路线图第 3 项（前端静态）完成。
- **完成结果（2026-07-14）**：新增只读研究平台入口，完整接入 UI-P0 的数据目录、候选登记簿、候选明细与结果读模型。页面展示 M0/F1/G1/G2 的冻结参数、成本、市场矩阵、固定判定门槛、verdict、冻结哈希/时间与锁箱溯源，并按候选类型归一化呈现逐市场/逐折证据；无创建、改参、开箱、重跑或删除入口。
- **验收结果**：真实环境渲染 `46` 个缓存数据集、`4` 个冻结候选和 `5` 份可用报告；候选切换、数据集类型/文本筛选通过浏览器交互验收。桌面端无页面横向溢出；移动端文档宽度与视口一致，导航和宽表保留各自容器内横向滚动。`npm run check`、`npm run build`、import/export 与关键类名核对均通过；live 默认开关未改动。

**任务 UI-P2：后端 job runner + 前端触发/进度/结果（优先级：中，依赖 P0）**
- **涉及文件**：`application/research/`（job runner + 候选创建/运行用例）；`api/routers/research.py`（写端点）；`frontend/src/pages/ResearchPage.vue`（创作+触发交互）。
- **改动**：① `POST /candidates` 创建预注册并**冻结**（写入即算哈希、不可再改）；② `POST /runs` 对某冻结候选触发评估 job（进程内后台，调现有 estimators/replay，**默认只跑缓存数据**）；`GET /runs/{id}` 轮询进度/结果，结果**只追加**；③ 锁箱开箱为一次性、记录在案；④ 「拉新数据」为独立动作，需 Binance 网络、失败清晰报错；⑤ 前端：预注册表单→冻结→触发→看进度→出 verdict，护栏 UI 化（冻结不可编辑、锁箱一次、结果只追加）。
- **验收**：创建即冻结（改冻结候选被拒的单测）；run 只引用冻结候选、结果只追加、锁箱只开一次；跑缓存数据不需网络；前端全流程可操作（Windows 复验）。
- **约束**：job runner 保持简单（单人、无队列）；不引入绕过四条护栏的后门。
- **完成结果（2026-07-14）**：新增 M0/F1/G1/G2 白名单协议模板、候选创建即冻结、候选/数据双 SHA-256 复核、哈希链只追加 run ledger 与单任务后台 runner。新增 `GET /templates`、`POST /candidates`、`GET/POST /runs`、`GET /runs/{id}` 和独立 `POST /datasets/fetch`；缓存评估只调用固定工具与目录数据，结果使用独占创建落盘。锁箱开箱写入首个 queued 事件且只能一次；进程重启会追加失败事件释放中断任务。数据拉取单独访问 Binance，每次生成带 run ID 的新缓存文件，不覆盖旧数据。
- **验收结果**：候选不可替换、数据指纹漂移拒跑、锁箱二次开启拒绝、结果/状态只追加、重启恢复、真实 M0 工具离线运行和 API 全流程均有自动测试。前端已完成预注册冻结、协议推荐矩阵、任务进度轮询、缓存评估、一次性开箱和独立数据拉取入口；G1/G2 强制 15m K 线配对。桌面/375px 移动端真实浏览器验收无横向溢出和控制台错误。后端 `273 tests OK`，`npm run check/build` 通过；未改 live 默认开关。

## 交易体系研究纲领（2026-07-13，目标：长期相对稳定 + 回撤可控）

**目标锚定**（区别于前面找单一 alpha）：要的是一套**交易体系**——长期相对稳定、回撤在可接受范围、温和收益。据此，研究方式变了：

1. **稳定与回撤是「设计」出来的，不是「找」出来的**——来自分散 + 按波动率定仓 + 风控 overlay，而非某一个高 edge 信号。
2. **判断「组合」的稳定性/夏普/回撤，不是判断单信号的 alpha**；每个 sleeve 只需「薄但为正 + 稳健 + 互不相关」，bar 比找 hero alpha 低得多。
3. **复用已建地基**：多币种资金管理机器、`RiskGuard`/STOP、审计、锁箱标定纪律——「体系」的地基已在，缺的是「信号 sleeve」和「仓位/组合层」。
4. **诊断已知**：双向网格是**做空波动（赚震荡）**，成本后为负（M0 已证）；多币种只降方差、不改负期望，救不了它。第一块 sleeve 改测其**反面**——趋势跟踪（做多波动）。
5. **终点线**：成功 = 一个体系撑到**纸面前向测试**；停止 = 定预算（再认真测 N 个带因果的 sleeve 全不过，则转平台价值或收尾）。

### 任务 TB1：趋势跟踪篮子 sleeve — 诚实成本后判定（交付 Codex，优先级：高）

- **预注册（运行前，2026-07-14）**：协议已冻结于 `docs/design/TREND_BASKET.md`。正式宇宙固定为 BTC/ETH/BNB/SOL/XRP/DOGE/ADA/LINK/AVAX/DOT/LTC/BCH 共 12 个 USD-M perp，要求 `4h`、共同连续至少 3 年、Funding 覆盖率 `>=99%`、至少 10 个合格市场；末 365 天为一次性锁箱。训练只搜索动量 `28/84/168` 天 × 波动率 `28/84` 天，周频再平衡、组合目标波动 `10%`、gross cap `1.0`、换手成本按完整往返 `0.14%` 并计真实 Funding。组合 bar 固定为年化净收益正、Sharpe `>=0.5`、最大回撤 `<=20%`、盈利年度折严格过半、数据/Funding 完整。现有四币 1h 运行无论数值如何只标记 `DATA_LIMITED_NON_CONCLUSIVE`。
- **正式训练（锁箱前，2026-07-14）**：12/12 市场通过数据质量门，共同 `1824.67` 天、`10949` 根 4h K 线；六组中 `mom28_vol28` 与 `mom28_vol84` 训练 PASS。按冻结排序唯一候选为 `mom28_vol28`：年化净收益 `+23.135%`、Sharpe `0.948`、最大回撤 `18.937%`、盈利年度折 `2/3`。训练报告 SHA-256 为 `e557cd0c389e34781259851df8570aaf5823d445da48171cf1f8489b6a4f0797`，状态 `TRAINING_PASS_LOCKBOX_PENDING`，锁箱尚未打开。
- **实现纠错**：首次运行复用了标准 8 小时 Funding 槽，漏掉 SOL 的 `75` 个非标准结算事件；初始文件与开箱标记保留但结果作废。改为按原始 Funding 时间逐条计账后，训练唯一候选仍为 `mom28_vol28`，参数未改变；纠错训练年化 `+23.019%`、Sharpe `0.944`、回撤 `18.937%`。受限纠错路径要求原标记、同候选、同输入指纹且只能使用一次，二次尝试已验证被拒绝。
- **最终锁箱（2026-07-14）**：同一候选末 365 天净收益 `+10.146%`、年化 `+10.141%`、Sharpe `0.523`、盈利年度折 `1/1` 均过线，但最大回撤 `20.951%` 超过冻结 `20%` 上限 `0.951` 个百分点，最终 **`LOCKBOX_FAIL`**。不放宽 bar、不切换候选、不进入 paper/testnet/live；若继续研究风险 overlay，必须作为新预注册候选并使用新锁箱。
- **验收结论（Claude，2026-07-14）：通过；且这是项目首个「正结果性质」的 FAIL。** 关键验证：① **没用弱数据硬测**——真 fetch 了 12 币种 × 4h × ~5 年正式宇宙，且数据质量门在代码层强制 `interval≥4h、≥10 市场、≥1095 天`（弱 1h/4 主流币进不了正式判定），正中我要求的「防假性 NO-GO」；② 估计器核验 sound——旧权重承担本期收益、目标权重滞后一期执行（pending）、换手计成本、funding 按持仓符号逐条记账，**无前视、无收益虚增**；③ 纪律：预注册→冻结训练候选→锁箱一次性；④ funding 纠错处理得当——真 bug（漏 SOL 75 个非标准结算）、**未改候选选择**、纠错后仍 FAIL、二次纠错被拒。`238 passed`（+12）。**小观察（非阻断）**：锁箱开箱后发现 bug 的理想处理是换全新锁箱，Codek 采「同候选受限纠错复算」略放松；但因选参未变、verdict 仍 FAIL，实际风险为零，可接受。
- **战略意义（与前 5 次 NO-GO 本质不同）**：这是全项目**第一个成本后、真实 funding、留出 365 天锁箱上仍为正收益（年化 +10%、Sharpe 0.52）的候选**，唯一未过的是最大回撤（超 0.95pp）。前 5 次是「负期望」问题（edge 不存在）；这次是「edge 存在、但回撤未达标」——而回撤恰是**风控/定仓可工程的维度**（正是本平台强项）。诚实边界：仍是预注册 bar 下的 FAIL，且「回撤能否在全新锁箱压到 20% 内」尚未证明，须作为新候选（TB2）预注册 + 新锁箱验证，禁止在本锁箱上调。
- **假设（凭什么存在）**：时序动量/趋势溢价是多市场、数十年被验证的持续现象（正偏、截断亏损让盈利奔跑，天生回撤受控）；与已证伪的均值回归正相反。审计它在**加密 perp、扣真实成本后**是否为分散篮子提供「薄但为正」的贡献。
- **数据前置（关键）**：公正测试趋势溢价需要**日线（或 4h+）+ 分散的多币种宇宙（~10–20 个流动性好的 perp）+ funding**；本机 fapi 451，须在 Binance 可达网络用 `fetch_klines/fetch_funding` 补齐并记指纹。**⚠️ 现有 BTC/ETH/BNB/SOL × 15m/1h 是「弱测试」**——4 个主流币高相关、1h 过噪且换手成本高，**很可能假性 NO-GO（错杀）**；可作冒烟，但**不得据此对趋势 sleeve 下结论**，公正判定必须用正确数据。
- **涉及文件**：`backend/src/orbit/domain/calibration/`（新增纯计算 trend-basket 回测估计器）；`backend/tools/`（新 CLI）；`docs/design/TREND_BASKET.md`（预注册协议）；`backend/tests/`。
- **改动（先预注册、后跑）**：
  1. **预注册冻结**：宇宙、信号（时序动量 lookback，如价格 vs N 周期前 / 均线）、**按波动率定仓**（vol lookback + 目标风险，使各币等风险贡献）、再平衡频率、成本（换手 × 单腿往返 `0.14%` + 持仓 funding）、**组合级准入 bar**（成本后正收益、最大回撤上限、夏普/盈利折过半——适配「稳定+回撤」目标，不同于 alpha 筛查的 C8）；无未来泄漏（信号只用入场时点已知数据）。
  2. **估计器**：纯计算 trend-basket 回测——TS 动量信号 → vol-target sizing → 篮子聚合 → 扣成本+funding → 输出净收益、年化、夏普、最大回撤、盈利折、逐币贡献。
  3. **训练窗选参冻结 → 锁箱一次性判定 → 诚实 verdict**。
- **验收**：① 单测锁定估计器（信号、vol sizing、成本扣减、无未来泄漏、回撤/夏普计算）；② `TREND_BASKET.md` 预注册在碰锁箱前冻结；③ 训练/锁箱结果写回本文件，明确 PASS/FAIL（组合级 bar）；④ **若数据不足以公正测试（仍只有 4 主流币/1h），如实标注「数据受限、非结论性」，不下 NO-GO**。
- **约束**：纯离线、组合级判据、参数只在训练窗选、锁箱一次性判定、不据锁箱回调；不改 live 开关。

**说明（诚实）**：趋势跟踪不神——有很长走平/回撤期、收益温和、加密上是否持续须实测，不给免费通行证。但它对口「稳定+回撤可控」目标、低频低成本、且能直接插进已建的多币种资金管理机器。

### 任务 TB2：风险管理版趋势篮子 — 把回撤压进上限（交付 Codex，优先级：高）

- **背景**：TB1 找到成本后+真 funding+留出锁箱仍正收益的趋势 sleeve（年化 +10%、Sharpe 0.52），唯一未过是最大回撤 `20.95%` vs `20%` 上限。TB2 目标：加风控层，在**保住正收益 + Sharpe≥0.5** 的同时把回撤压进 `20%`，且必须**在从未参与选参的样本外**证明。
- **纪律难点与解法（关键）**：TB1 已把「末 365 天」当锁箱用掉、其回撤已被看到，**不得复用它测 TB2**（否则 overlay 等于照答案定做）。TB2 改用 **walk-forward：多个不重叠的滚动样本外窗口，每步只用该窗口之前的数据选 overlay 参数、在下一未见窗口打分**；信号参数**沿用 TB1 冻结的 `mom28/vol28`，不再重搜信号**，TB2 只加风控层。若能在 Binance 可达网络补更早历史（拿到真正全新时间段），可另加一次性全新锁箱强化证据。
- **涉及文件**：`backend/src/orbit/domain/calibration/trend_basket.py`（加风控 overlay + walk-forward 评估）；`backend/tools/`（CLI）；`docs/design/TB2_RISK_MANAGED.md`（预注册）；`backend/tests/`。
- **改动（先预注册、后跑）**：
  1. **预注册冻结 overlay 类型 + 小网格**（只在风控层，不碰信号）：如 ① 目标组合波动率 ∈ `{6%, 8%}`（比 TB1 的 10% 低——按波动率定仓天然降回撤，Sharpe 近似不变，这是最直接的「用仓位大小控回撤」）；② 组合级回撤节流（权益回撤超阈值就降 gross，阈值预注册小网格）；③ 二者组合。网格要小、成文冻结。
  2. **walk-forward 评估**：多个不重叠 OOS 窗口，每步 overlay 参数只由过去数据选、下一窗口一次性打分；输出各 OOS 窗口的净收益/年化/Sharpe/最大回撤分布 + 聚合 + 最差窗口。
  3. **准入 bar（沿用 TB1 组合级）**：聚合与**最差 OOS 窗口**都须满足「正收益、Sharpe≥0.5、最大回撤≤20%、盈利折过半」。
- **验收**：① 单测锁定 overlay + walk-forward（无未来泄漏、每步选参只用过去、回撤节流逻辑）；② `TB2_RISK_MANAGED.md` 预注册在跑数前冻结、信号参数沿用 TB1；③ walk-forward 各窗口结果写回，明确 PASS/FAIL；④ 诚实标注：单纯「降目标波动」压回撤是合法的仓位控制（Sharpe 不变即可接受），但要区分「只是缩小规模」还是「真的改善了收益/回撤形状」。
- **约束**：只加风控层、不重搜信号、不复用 TB1 已烧锁箱、每个 OOS 窗口选参只用过去、不据任何 OOS 窗口回调；不改 live 开关。
- **完成结果（2026-07-14）**：预注册先独立提交，再使用 TB1 原 12 市场 4h OHLC、逐条 Funding 和固定 `mom28/vol28` 信号完成两步年度 walk-forward；末 365 天 TB1 锁箱完整排除。WF1 训练选中 `vol06_dd10`，随后 OOS 年化 `+23.390%`、Sharpe `1.371`、最大回撤 `9.355%`、盈利折 `1/1`，判定 PASS；但节流触发 `0` 次，实际只是 6% 目标波动的规模缩小，未证明形状改善。WF2 的 8 个候选均满足正收益、Sharpe 和回撤门，却全部只有 `1/2` 盈利年度折，训练池为空，按纪律不打开 WF2 OOS。最终 **`TB2_FAIL`**，不放宽年度稳定性门、不进入 paper/testnet/live。正式报告实际文件 SHA-256：`9ef092c5f428182aaed19896c72933d9fdbf13fd43c523a77e04c043ea35e439`；CLI 最初记录的换行转换前哈希已作审计纠错，研究结果未改变。
- **验收结论（Claude，2026-07-14）：通过（纪律无可挑剔）；FAIL 原因转移，且暴露一个「指标 vs 目标」错配。** 我这轮的四个重点全过：① **未复用 TB1 已烧锁箱**（末 365 天完整排除）；② walk-forward 两窗、每步选参只用过去（训练截止早于 OOS）；③ 信号沿用 `mom28/vol28` 未重搜、只加 8 个风控候选；④ 最差窗口必须达标，WF2 训练失败时**拒绝偷看 OOS 补选**。估计器 walk-forward/节流/无泄漏有单测；`242 passed`（+4）。**两点关键观察**：(a) **回撤问题已被解决**——降目标波动到 6% 后 WF1 OOS 回撤仅 `9.4%`、且年化 `+23%`/Sharpe `1.37`（诚实：节流触发 0 次，纯规模控制，Codek 如实标注未证明形状改善）；(b) 本次 FAIL **不再是回撤，而是「盈利年度折严格过半」**——2 折窗口下该门等于要求「每年都盈利」，而这**对趋势跟踪先天 lumpy（大赚几年、平/亏几年）的收益侧写过严**，也与用户目标「长期相对稳定 + 回撤可接受」（明确容忍部分下行年）**不完全一致**——这是**预注册指标选得不贴目标**，不是策略本身没救。**注意（守纪律）**：这不构成「放宽该门以通过」（禁止）；正确出路是为下一候选**按目标本义预注册一个更贴切的稳定性指标**（如滚动多年回撤/时长、全 OOS Sharpe，而非逐年为正），且**必须在全新数据上冻结验证**，防止照本轮结果挑指标。

**说明（诚实）**：把回撤压进 20% 在技术上不难（降仓位即可），难的是**在全新样本外同时保住正收益和 Sharpe、且最差窗口也达标**——这才是「稳定体系」的真门槛。TB2 PASS = 趋势 sleeve 具备进入下一步（更多 sleeve 组合 / 纸面前向）的资格；FAIL 则记录差距、继续风控迭代或换 sleeve。

### 任务 TB3：目标本义准入门 + 冻结系统样本外确认（最后一道回测门，交付 Codex，优先级：高）

- **背景**：TB1 证明趋势 sleeve 成本后+真 funding+样本外仍正收益；TB2 证明回撤可由仓位控制，但暴露「盈利年度折严格过半」对趋势 lumpy 侧写过严、与目标错配。经与用户校准，准入门改按**用户真实风险偏好**定义（回撤容忍 30%、被套时长放宽到 18 个月、40% 为好年份天花板而非下限、收益温和）。
- **冻结准入门（从容忍度/原则推导，跑数前冻结；非照 TB1/TB2 结果反推）**：
  1. 成本后净收益 `> 0`；
  2. 最大回撤 `<= 30%`（用户容忍；当**规模约束**，靠定仓位满足）；
  3. Calmar（年化净收益 ÷ 最大回撤）`>= 0.5`（原则：每单位回撤至少换 0.5 单位年收益）；
  4. Sortino（只罚下行波动）`>= 0.7`（比 Sharpe 公平于趋势正偏）；
  5. 最差滚动 12 个月收益 `>= -30%`（对齐回撤容忍）；
  6. 正收益滚动 12 个月窗口占比 `>= 55%`（相对稳定，**不要求年年为正**）；
  7. 最大回撤持续时长 `<= 18 个月`（用户放宽后）；
  8. 聚合与**最差 OOS 窗口**都须满足。
- **冻结系统**：信号沿用 TB1 `mom28/vol28`**不重搜**；仓位预注册小网格（目标波动 `{10%,15%,20%}`，训练窗内选「训练最大回撤留足缓冲（如 ≤25%）下的最高波动」，只用过去选、冻结）。
- **涉及文件**：`backend/src/orbit/domain/calibration/trend_basket.py`（加 Calmar/Sortino/滚动 12m/回撤时长指标 + 冻结门评估）；`backend/tools/`；`docs/design/TB3_ADMISSION.md`（预注册）；`backend/tests/`。
- **评估**：全可用历史尽可能多的不重叠 walk-forward OOS 窗口，每步选参只用过去、下一未见窗口打分；逐窗口 + 聚合对照冻结门。
- **数据诚实（关键）**：加密回测历史（~2021–2026）已被 TB1/TB2 检视，TB3 verdict 属「**回测确认**」级别；**真正终点线是纸面前向测试（见 TB4）**，用从未见过的未来时间做最终裁决。
- **验收**：① 门从容忍度/原则推导且**冻结在跑数前**（不得照已见结果挑指标）；② 系统冻结、信号不重搜、仓位只训练窗选；③ 新指标（Calmar/Sortino/滚动/回撤时长）有单测、walk-forward 无泄漏；④ 逐窗口+聚合结果写回，明确 PASS/FAIL；⑤ 若 PASS，结论为「**具备进入纸面前向的资格**」，不直接授权 testnet/live。
- **约束**：只加指标+门，不重搜信号/成本/市场/方向；不据任何 OOS 窗口回调门或参数；不改 live 开关。
- **完成结果（2026-07-14）**：先独立预注册，再以两个互不重叠的 608 天 OOS 完成 `BACKTEST_CONFIRMATION`。两步训练均因 `vol15/vol20` 超过 `25%` 回撤缓冲而冻结 `vol10`；WF1 OOS 总净收益 `+43.933%`、Calmar `1.290`、Sortino `1.410`、回撤 `18.937%`，WF2（最差 OOS）总净收益 `+23.044%`、Calmar `0.633`、Sortino `0.905`、回撤 `20.951%`、最差滚动 12m `-10.152%`、正滚动占比 `59.02%`、最长回撤 `6.8` 月；聚合净收益 `+77.101%`、Calmar `0.893`、Sortino `1.163`。逐窗口和聚合七项门全部通过，最终 **`TB3_PASS`**。这只授权进入 TB4 纸面前向验证，不授权 testnet/live。正式报告 SHA-256：`af31e84e1409845b17b5c3b0a8290d427b59feb68912a8abf47ff8723ea1d187`。
- **验收结论（Claude，2026-07-14）：通过——全项目首个 PASS，且经严格核验干净。** PASS 需比 FAIL 严格得多，逐项核实：① **门跑数前冻结、非反推**——预注册提交（`8af9c1a`）先冻结全部 7 项阈值，与用户容忍度商定值完全一致（回撤≤30%/Calmar≥0.5/Sortino≥0.7/最差滚动12m≥-30%/正占比≥55%/被套≤18月/净>0），confirm 提交只改「状态」行、未动门；② **系统冻结**：信号沿用 `mom28/vol28` 未重搜，仓位只在训练窗按 `≤25%` 缓冲选 `vol10`，`vol15` 超 0.224pp 也照拒（无放宽）；③ **新指标实现无虚高**：Sortino 用全样本下行偏差（标准且偏保守，非只除负期数那种抬高算法）、Calmar=年化÷回撤、回撤时长（含窗口末未回本）、滚动 12m 均正确，均有单测；④ **数值舒服过关非勉强**：最差窗口 WF2 与聚合逐项仍显著高于门（Calmar 0.63/0.89 vs 0.5、Sortino 0.9/1.16 vs 0.7、被套 6.8 月 vs 18）。`246 passed`（+4）。合并在 `main`（`8af9c1a..a16c598`）。
- **诚实边界（务必记住）**：①**这是「回测确认」不是全新样本**——WF2（2024-11→2026-07）与 TB1 锁箱期重叠（回撤 20.95% 同一数字即证），Codek 已如实标注并要求 TB4；②**OOS 期（2023–2026）恰是加密强趋势区间**，趋势跟踪在趋势市天然表现好，震荡/无趋势的未来可能明显逊色——这正是**必须 TB4 前向验证**的原因，`TB3_PASS` 只是「具备资格」，绝非「可上真钱」。

### 任务 TB4（TB3 PASS 后触发）：纸面前向测试 = 真正的终点线

- **定位**：回测历史已用尽，唯一真正「全新数据」是**未来时间**。TB4 把 TB3 冻结的完整系统（信号+仓位+门）接入平台 **paper 模式**（M3 执行通道已具备），在真实前向时间里累积从未见过的样本外证据，对照 TB3 冻结门判定。
- **说明**：TB4 需实现 trend-basket 为可运行 paper 策略（比 offline 估计器大），且需真实日历时间累积证据——是「验证」阶段，不是「研究」阶段。TB3 未 PASS 前不启动。

### 任务 TB-R：参数稳健性诊断 + 多周期一篮子候选（TB4 前向前置，交付 Codex，优先级：高）

- **背景（两个真实缺口）**：TB3 冻结系统依赖单一 `mom28/vol28 + 7 天再平衡`。用户指出两点，均成立：① **卡边界**——动量 lookback 网格是 `{28,84,168}`，`28` 是最短项，「训练选中 28」实为「28 只赢了 84/168，更短的 14/10/7 从未测过」；选中值落在搜索区间边缘，通常意味着真最优在边界外。② **可能是幸运数字**——照训练表现挑单一参数，正是「刚好挑到过拟合那对」的标准姿势。TB-R 在 TB4 前向之前，先回答「28/7 是代表值还是幸运/太慢」。
- **重要平衡（写清，避免过度纠偏）**：加密「快」但更「吵」，短 lookback 反应快却更易被噪声打脸+换手成本更高；趋势文献普遍偏中长周期正因能滤噪。故「快市场就该用快参数」不成立，这是**两面问题，只能实测**。
- **涉及文件**：`backend/src/orbit/domain/calibration/trend_basket.py`（加多周期集成信号 + 敏感性扫描）；`backend/tools/`；`docs/design/TB_ROBUST.md`（预注册）；`backend/tests/`。
- **改动（先预注册、后跑）**：
  - **Part A 敏感性诊断（只报告、不选参）**：在同一 walk-forward OOS 上，扫 lookback `{7,14,28,56,84,168}` × 再平衡 `{3,7,14}` 天，输出各组合 OOS 的 Calmar/Sortino/最大回撤/年化/滚动12m 曲面。目的：看邻域是**平滑（稳健）**还是**尖刺/边界效应（脆弱）**、更短到底更好还是更差。**此扫描仅用于诊断，不得据它挑一个部署配置。**
  - **Part B 多周期一篮子候选（预注册、固定、不选单一赢家）**：冻结一个**固定** lookback 集合（如 `14/28/56/84/168`，跨快到慢、成文不调），每币的集成信号为各 lookback 符号权重的等权平均（组合方法预注册冻结），再按 `vol28`、目标波动 `10%`、gross cap `1.0`、`7` 天再平衡、`0.14%` 成本+真实 Funding 定仓。**该候选没有可选的 lookback——用全部、取平均**，从结构上消除「边界」与「幸运数字」两个问题。
  - 用**同一套 walk-forward OOS + 同一套 TB3 冻结准入门**评判该一篮子候选。
- **验收/判定**：
  - ① 若**一篮子候选通过 TB3 门**且**Part A 曲面平滑（28/7 邻域不是孤立尖点）** → 稳健性确认，**一篮子版本取代单一 28/7 成为 TB4 前向对象**（更稳健）；
  - ② 若**一篮子 FAIL 或曲面尖刺/边界效应明显** → 说明单一 28/7 的 PASS 脆弱/靠运气，**不得拿去 TB4 前向**，需重新设计或判定趋势 sleeve 尚不达标；
  - ③ 单测锁定集成信号、敏感性扫描无未来泄漏、组合方法与预注册一致；结果写回本文件。
- **约束**：Part A 只诊断不选参；Part B 集合固定、判断整体而非再挑单一赢家；扩网格属扩大搜索，必须预注册冻结 + 判断集成 + 同一留出数据，**不得据 OOS 结果回调集合或组合方法**；仍是回测，最终真伪由 TB4 前向裁决；不改 live 开关。
- **完成结果（2026-07-14）**：先预注册并单独澄清零动量分量，再运行 18 格敏感性和固定多周期集成。Part A 显示 7 天动量三格均负，`14/28/56` 形成连续有效区域；中央 `28/7` 四轴邻居有 `3/4` supportive，短端由 `14/7` 支持，中央相对邻居中位数的年化/Calmar/Sortino倍率仅 `1.075/1.391/1.026`，判定 **`SMOOTH`**。Part B 固定 `14/28/56/84/168` 等权集成在 WF1/WF2 均过 TB3 门，聚合净收益 `+61.890%`、年化 `+15.558%`、Calmar `1.032`、Sortino `1.213`、最大回撤 `15.082%`、正滚动 12m 占比 `91.31%`、最长回撤 `13.923` 月。最终 **`TB_R_PASS`**；该集成取代单一 `28/7` 成为 TB4 唯一前向对象，不从 Part A 挑最佳格点。报告 SHA-256：`7dd708b59c7c498b9fa5e8c9db0a3fceae4e6dec17541e91c66d6b40b65e66c4`。
- **验收结论（Claude，2026-07-14）：通过（PASS，严格核验干净）；且直接解答了用户两个担心。** ① `clarify` 提交只精修「集成信号取值是否含 0」的边缘描述，**未改冻结集合/组合方法**；② Part A **只诊断未选参**——曲面判 SMOOTH 但**没去挑最优的 `14/14`(+30.6%)部署**，明写禁止；③ Part B 集合 `14/28/56/84/168` **预注册固定、等权、无选择**，且**未据曲面剔除弱周期(84/168)**——含拖累项仍过门，稳健性更强；④ 估计器复用 TB1 已核验执行(无前视/真成本/真 funding),集成仅 5 个 lookback 符号取平均;`250 passed`(+4)。合并在 `main`(`6cf186b..09f11a8`)。
  - **两个担心的实测答案**：**「幸运数字?」→ 不是**——`28` 坐在 `14/28/56` 连续有效区中间、邻居同样过门，且不挑单一的集成也过门。**「28 卡边界、快市场该更快?」→ 实测否定**——向短端补测的 `7` 天动量三种再平衡**全亏**（噪声+churn），`14` 才转正,「快市场用快参数」被证伪。
  - **且集成比单一 `28/7` 更好**：最大回撤 `20.95%→15.08%`、两 OOS 收益更均衡(`+16%/+15%` vs `+24%/+13%`),以少量收益换跨周期分散——**更贴「稳定+回撤可控」目标**。
  - **诚实边界不变**：仍是 `BACKTEST_CONFIRMATION`，OOS 期(2023-2026)仍是加密强趋势区间、幸存者偏差与执行真实性未建模；**TB4 前向仍是唯一真裁决**，TB-R PASS 只是把「更值得信、更稳健的版本」送去前向。

**说明**：TB-R 一次性回答用户两个担心——「28/7 是不是幸运数字」（Part A 曲面 + Part B 不挑单一）与「28 卡边界、对快市场是否太慢」（Part A 向短端补齐 + 实测快慢）。它是把「值得信的版本」交给 TB4 前向之前的最后一道稳健性关。

### 任务 TB4：多周期集成趋势篮子纸面前向测试 = 真正的终点线（交付 Codex）

- **定位**：TB1–TB-R 已用尽加密回测历史，均为 `BACKTEST_CONFIRMATION`。唯一未被污染的「全新数据」是**未来时间**。TB4 把 TB-R 冻结的多周期集成接入平台 **paper 模式**，在真实前向时间里累积从未见过的样本外证据，对照 TB3 冻结门判定。**这是「验证」不是「研究」**——交付物是「一个正在跑的、冻结的、被监控的前向测试」，**verdict 需数月真实日历时间才能得出**。
- **冻结系统（来自 TB-R，一字不改）**：12 市场 4h；动量集成 lookback `{14,28,56,84,168}` 等权、`ensemble_signal=5 个符号均值`；`vol28`、目标波动 `10%`、gross cap `1.0`；`7` 天再平衡、下一根执行；成本 `0.14%` 往返 + 真实 Funding。
- **运行环境**：paper 前向需持续 4h K 线（12 市场），须部署在 **Binance 可达网络**（本机 fapi 451 跑不了）；复用平台已有账户/风控/审计/paper 通道基础设施。

**任务 TB4-A：实现可运行的冻结集成趋势篮子 + 与 offline 逐笔对齐（优先级：高）**
- **问题**：现有 `EventEngine` 是双向网格引擎，趋势篮子是**另一类策略**（12 币方向性组合、周频再平衡、动量集成信号）。需新建趋势篮子策略 runner，并接入 paper 执行。
- **涉及文件**：新增趋势篮子策略 runner（`domain/strategy/` 或新模块）；paper 执行接线（复用/推广 `PaperExecutionService`）；市场数据接线（12 市场 4h）；`backend/tests/`。
- **改动**：实现 runner——从 12 市场 4h K 线历史算集成信号 → vol-target 目标权重 → 周频再平衡 → paper 虚拟成交；参数**硬编码冻结**、无任何可调/可选项。
- **验收（最关键）**：**逐笔对齐测试**——把该 runner 在 TB-R 的历史数据上回放，**必须逐再平衡复现 offline 估计器的目标权重与净收益**（在极小容差内一致）。不一致则前向测的不是被验证过的系统，TB4 无意义。此外：账户/风控/审计复用无回归；live 开关不受影响（paper only）。
- **约束**：只实现冻结系统、零自由参数；不改 live 默认开关；对齐测试是硬门槛。
- **完成结果（2026-07-14）**：新增 `trend_basket_runner.py`，参数全部硬冻结为模块常量（动量 `14/28/56/84/168` 天、`vol28`、`7` 天再平衡、目标波动 `10%`、成本 `0.14%`），spec 为 `frozen=True` dataclass、构造仅私有 `_spec` 默认冻结值，**无公开可调旋钮**；含缺市场/非连续 K 线拒绝。新增 `verify_tb4_alignment.py`。
- **验收结论（Claude，2026-07-14）：通过（TB4-A 硬门槛过关）。** 逐笔对齐测试 `test_replay_matches_offline_estimator_at_every_period_and_rebalance` 逐周期比对净收益、逐再平衡比对换手/成本/**每币目标权重**，均 `places=12`；正式对齐工具跑 `9,940` 周期 / `237` 再平衡，**最大净收益误差 `0.0`、最大权重误差 `0.0`**（字面为零，非容差内）→ `TB4_ALIGNMENT_PASS`。即**前向将运行的系统与通过 TB-R 的 offline 系统逐笔一字不差**——前向可信的地基成立。runner 参数确认硬冻结无旋钮。`252 passed`（+2）。合并在 `main`（`ed69d44`）。
- **下一步（TB4-B，属部署+日历时间，非一次提交可完成）**：`TB4_FORWARD.md` 已预注册前向协议框架（中途检查点只报告不判定、最终用 TB3 同一冻结门）；实际启动需部署在 Binance 可达网络（本机 fapi 451）并**跑够 ≥12 个月形成完整滚动 12m**。启动后铁律：**期间什么都别动**。

**任务 TB4-B：预注册前向协议 + 启动并监控 paper 前向（优先级：高，依赖 TB4-A）**
- **改动**：① 预注册 `docs/design/TB4_FORWARD.md`——前向**起始时间戳**、**最短运行期**（需长到形成完整滚动 12 个月，即 ≥12 个月 + 缓冲；可设中途只读检查点但**不据此提前下结论**）、判定用 TB3 同一套冻结门、以及**铁律：前向期间不得改参数/不得提前止损结论/不得因早期波动微调**；② 启动 paper 前向，持续记录权益曲线与 TB3 指标；③ 前端/快照暴露前向进度与当前指标（只读监控）。
- **验收**：协议预注册冻结在启动前；前向记录只追加、防篡改；到预注册期限才出 PASS/FAIL；期间参数只读不可变。
- **约束**：**前向测试的最大敌人是「手贱」**——早期看着好就想上真钱、看着差就想调参，协议必须从机制上禁止；paper 通过也只授权「考虑小资金 live 的讨论」，不自动开 live。

**TB4-B 启动器建设规格（交付 Codex；操作手册见 `docs/design/TB4_OPERATIONS.md` 第 5 节）**
- **架构要点**：`FrozenTrendBasketRunner` 本身已是自带成本/Funding 的 paper 模拟器，**不需要复用网格的 `PaperExecutionService` 撮合**；TB4-B 只需「用实时收盘 K 线 + Funding 驱动 runner → 只追加落盘 → 只读监控」。**paper only，永不触碰 live 下单通道。**
- **涉及文件**：新增前向服务（如 `application/trend_forward.py`）；市场数据接线（12 市场 4h K 线，复用 `BinanceKlineFeed`/`MarketFeedService` 拉取；本机 fapi 451，须部署在 Binance 可达网络）；Funding 持续拉取；只追加持久化 repository（MySQL/JSON）；snapshot 只读投影；`backend/tests/`。
- **改动**：
  1. **定时驱动**：每根 4h K 线收盘后拉 12 市场最新收盘 + 到期 Funding，喂 `FrozenTrendBasketRunner.on_close(...)`；复用 TB4-A 冻结 `TB4_SPEC`，无任何自由参数。
  2. **起点锁定 + 暖机分离**：记录预注册**前向起始时间戳**与输入指纹，不可篡改；signal 需 ≥168 天历史暖机，**暖机用起点前的历史数据，但只有起点之后的权益/成交/指标计入前向证据**（暖机不计分）。
  3. **只追加持久化 + 重启确定性**：权益曲线、每次再平衡、当前 TB3 指标、以及喂入的收盘序列全部**只追加**落盘；进程重启能确定性恢复（复现同一状态，保持 TB4-A 的逐笔一致性），可对前向数据再跑对齐校验。
  4. **只读监控**：snapshot/控制台暴露前向进度（已跑多久）、权益曲线、当前指标 vs 冻结门、数据完整性、成交健康——**中途只报告、不判定**。
  5. **护栏**：不提供任何改参数/提前止损/提前判定/移动起点的入口；到预注册期限才允许出 PASS/FAIL。
- **验收**：① **重启确定性测试**——中断+恢复后状态与不间断运行逐笔一致；② 暖机数据不计入前向证据（起点后才计分）的测试；③ 持久化只追加、不可覆盖删除；④ 无参数旋钮暴露、live 通道零触碰；⑤ 监控只读、期限前无 PASS/FAIL；⑥ 复用冻结 `TB4_SPEC`（对齐性质保持）。
- **约束**：paper only、参数冻结、无提前判定/改参入口、护栏从机制上禁止「手贱」。
- **完成结果（2026-07-14）**：新增 `application/trend_forward.py`（前向服务）+ `trend_forward_market.py`（12 市场 4h 行情适配）+ `persistence/trend_forward_ledger.py`（哈希链只追加账本）+ `tools/run_tb4_forward.py`（`--initialize`/持续轮询/`--once`）；runner 加 `export_state()` 支持确定性恢复；snapshot 只读暴露 `trend_forward`；config 加前向参数。账本默认 `var/forward/tb4/`。
- **验收结论（Claude，2026-07-14）：通过（护栏全部真载荷验证）。** 两道硬门槛扎实：`test_restart_replays_to_exact_same_state` 断言重启后 `export_state()` 与 `snapshot()` **全等**（保住 TB4-A 逐笔对齐）；`test_warmup_is_not_scored_and_first_forward_close_is_scored` 断言 init 后 `scored_periods=0`、喂首根前向收盘才 `=1`（暖机不计分）。更强的护栏：账本**哈希链防篡改**（`test_hash_chain_detects_modified_record` 改一条记录→重建 `fingerprint mismatch`）、起点清单不可重初始化、重复收盘幂等、`parameters_mutable=False`、`live_trading=False`、期限前无 verdict。复用冻结 `TB4_SPEC`。`259 passed`（+7）。合并在 `main`（`cf982c7`）。
- **诚实更正（采纳 Codex）**：本人先前在 `HANDOFF.md` 写「前向天然修掉幸存者+执行两个偏差」属**过度声称**，Codex 已更正为：paper 前向仍按收盘价+固定 `0.14%` 记账，**不验证真实成交滑点、也不消除「最初选当前存活币种」的历史幸存者偏差**；它消除的是「未来行情窥视」，并会暴露测试期内的停牌/下线。此更正正确，予以采纳。
- **路线图第 1 项（功能收尾）完成**：前向可启动（`run_tb4_forward.py --initialize`，须 Binance 可达主机），真实前向计时待用户部署；启动后铁律「什么都别动」。

**说明（诚实，务必记住）**：① 前向测试消除未来行情窥视，并会暴露固定市场在测试期内的停牌/下线问题；但当前 paper 仍按收盘价和固定 `0.14%` 成本记账，**不等于真实成交滑点验证，也不会自动消除最初选取当前存活币种的历史幸存者偏差**；行情 regime 仍只能靠时间覆盖。② TB4 交付的是「跑起来的测试」，**真结论要等至少 12 个月**，期间最重要的动作是**什么都别动**。③ paper 前向是检验历史结果能否延续的关键证据，但不是实盘收益保证。

## 项目完善路线图（2026-07-14，交付 Codex 逐项执行）

**背景**：用户可能后续换模型，决定现在把项目做完善到「换人/换模型也能接着做」。总览与研究结论见 `docs/HANDOFF.md`（先读）。以下为剩余全部 Codex 任务，按建议顺序排列；每项详细规格见本文件对应小节。

| 顺序 | 任务 | 规格位置 | 优先级 |
|---|---|---|---|
| 1 | **TB4-B 前向启动器**（持续 4h K 线驱动 runner + 只追加落盘 + 只读监控 + 无改参入口） | 本文「TB4-B 启动器建设规格」 | 高（功能收尾） |
| 2 | **UI-P0 只读研究 API（已完成）**（数据目录 + 候选注册表[只追加/冻结不可改] + 结果读模型） | 本文「研究平台（方向1）前端化计划」 | 高 |
| 3 | **UI-P1 研究前端（只读，已完成）**（数据目录 / 候选墓地 / 候选明细对照固定 bar） | 同上 | 中 |
| 4 | **UI-P2 job runner + 触发（已完成）**（网页填预注册→冻结→点一下跑缓存数据→看进度→出 verdict；四护栏 UI 化） | 同上 | 中（依赖 P0） |
| 5 | **运维打磨** | 见下「任务 OPS-1」 | 低 |

**贯穿纪律（所有任务）**：保持测试绿；不改 live 默认开关；研究相关一律焊死「预注册冻结不可改 / 锁箱开一次 / 结果只追加 / verdict 对固定 bar」四护栏；前端本机无 node，`npm run check/build` 需 Windows 复验。

**UI-P0 完成记录（2026-07-14）**：已新增研究数据目录、M0/F1/G1/G2 冻结候选登记簿和 JSON 结果读模型，并提供管理员只读 API：`GET /api/research/datasets`、`/candidates`、`/candidates/{id}`、`/results/{id}`。候选登记簿使用 JSONL 哈希链只追加保存，重复 ID、覆盖和指纹篡改均会被拒绝；未改动 CLI 计算逻辑和 live 默认开关。

**UI-P1 完成记录（2026-07-14）**：研究平台前端已接入 UI-P0，只读展示数据目录、候选墓地、冻结定义、固定 bar、锁箱溯源和结构化结果证据；桌面/移动端及筛选、候选切换均完成真实浏览器验收。

**UI-P2 完成记录（2026-07-14）**：研究平台已形成「选择白名单协议与缓存数据 → 冻结候选和数据指纹 → 后台运行固定评估器 → 轮询进度 → 只追加 verdict/结果」闭环；锁箱开箱仅一次，联网拉新数据为独立任务且不覆盖旧缓存。研究平台 P0/P1/P2 路线完成。

### 任务 OPS-1：跨平台运维打磨（优先级：低）

- **问题**：平台按 Windows 开发——`backend/scripts/` 只有 `.cmd`/`.ps1`，README 为 PowerShell + `C:\Users\...` 路径；`LocalCredentialVault` 用 Windows DPAPI，Linux 调用 `protect()` 抛错；前端在无 node 的 Linux 上无法本地构建。
- **涉及文件**：`backend/scripts/`（补 bash）；`infrastructure/credentials/`（Linux vault adapter）；`README.md` / `docs/`。
- **改动**：① 补一套 Linux/bash 启动/校验脚本（对应现有 `.cmd`/`.ps1`）；② 新增 Linux 凭证 vault adapter（或统一走 `env:` 引用），使非 Windows 也能保存凭证；③ README/文档补 Linux 运行说明与前端 Windows 侧构建复验流程。
- **验收**：Linux 下可按文档启动后端、跑校验；凭证在 Linux 可保存/读取；文档无自相矛盾。
- **约束**：不改交易逻辑与 live 开关；纯运维/跨平台补齐。

## 最近验证

- `npm run check` 通过。
- `npm run build` 通过。
- Python 单元测试及 API 契约测试：`273 tests OK`。
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

- **趋势生命周期仍需继续完善（最高优先级）**：`StrategyLifecycle` 已接管事件后状态变更、恢复重锚、计数器清零、趋势进入的持续确认与可选速度门、趋势退出候选计数和亏损腿重建；速度门训练对照不支持翻默认，趋势退出参数的回测标定仍未完整落地。
- **核心风控、per-symbol 恢复与前端投影已补齐**：`RiskGuard` 已覆盖 symbol `STOPPED` 拆对冲全平、gross `ONLY_REDUCE`、组合级回撤 `GLOBAL_STOP` 和 C7 自融资账本；`plan_only` 已按 `snapshot_max_age_seconds` 拦截陈旧快照，管理员可审计化恢复单个 STOPPED symbol，风控页已完整投影 GLOBAL_STOP、STOPPED 与 blocked 决策（T1/T2 已完成）。剩余项是 paper/live 组合态编排。
- **趋势确认速度门默认关闭**：进入 TREND 已支持最近 `k` 个 close tick 的位移速度门；首个训练候选降低了趋势触发但损害净收益，因此默认保持中性，后续需按周期独立标定（S1 已完成）。
- **利润搬运口径已澄清**：新 Δ* 模型不再使用 `restore_loss_side_only_to_base`；减盈利腿独立生成，加亏损腿按剩余目标差额与自融资预算可选追加，亏损腿已达或超过 base 不会阻止止盈（S3 已完成）。
- **成本项仍需标定**：Funding 在失衡对冲中是方向性成本（当前恒为 0）；利润搬运已支持可选的加仓腿往返成本覆盖，但首轮训练窗没有触发差异，默认保持关闭（S2 已完成）。
- **Regime Gate 审查发现（2026-07-13，修复计划见上方「Regime Gate 审查修复计划」）**：
  - 被 regime / 规则拦截的决策已写入 `info` 级 blocked 风险事件，且不产生成交；持续阻断已按状态转换去重，不再冲刷 material 风险历史（R1/R1.1 已完成）。
  - RANGE 自相关阈值语义已厘清：训练窗不支持收紧到 `0.20`，保留 `0.95` 作为极端病态保险，并由分类测试锁定（R2 已完成）。
  - regime 冷启动静默期：`min_samples` 根收盘前禁止利润搬运/重建（`interval=1h` 约 20 小时），属预期行为，paper/live 上线首日需据此设期望。
  - paper 收盘推进已统一委托 `EventEngine.advance_close()`，与 dry_run/replay 共用 close-only 指标和生命周期推进（R3 已完成）。

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

当前 `plan_only` 计划生成和 dry_run 模拟引擎已切到 `Δ*` 内核，并共用策略动作集、事件触发规则、生命周期与 `RiskGuard`；趋势进入持续确认和可选速度门、趋势退出候选计数、亏损腿分批重建、C7 自融资账本、组合级回撤和快照新鲜度拦截均已落地。剩余重点转为参数标定、STOP 后人工复核恢复、paper/live 组合态编排与 UI 投影。

1. 为 FastAPI routers 增加 Pydantic 请求模型、统一业务错误映射和更完整的账户级权限契约测试。
2. 按 interval 独立标定趋势退出、速度门和恢复参数，不跨周期复用 tick 参数。
3. 完成 T2 风控 UI 投影，并继续补 paper/live 组合态编排。
4. 接入 Funding 实际结算数据，并在交易成本或最低利润参数变化时重新标定利润搬运成本门。

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
