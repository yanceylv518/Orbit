# Orbit 项目进度（原 Dynamic Dual Grid V1）

最后更新：2026-08-10

## 新短线策略平台升级（目标架构，尚未实现）

2026-08-10 已确认下一阶段产品方向并形成正式目标架构：

- Binance USDT 永续，持仓数分钟至数小时，首批研究突破/动量与超跌反弹。
- 每日按历史时点可见的流动性生成动态币池。
- 一个交易账户同时只运行一个策略实例；多个账户可并行运行。
- 每个账户最多三个非零币种仓位；满仓信号记录为容量拒绝，不排队、不强制换仓。
- 支持多空；3–5 倍仅为待准入目标，不是当前授权配置。
- 目标运行架构采用共享市场数据、实例租约、账户隔离风险、订单意图/outbox、幂等执行和重启对账。

完整方案见 `docs/design/MULTI_ACCOUNT_SHORT_STRATEGY_ARCHITECTURE.md`。当前仅完成架构设计，尚未实现动态历史币池、分钟级组合 replay、通用策略注册、多 worker 租约、订单 outbox 或多账户并发运行，不授权据此开启真实资金交易。

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
- 支持 Binance API Key / Secret 跨平台加密保存：Windows 使用 DPAPI，Linux 使用环境主密钥驱动的 AES-256-GCM。
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
  - Binance API Key / Secret 保存、平台凭证加密、指纹计算、凭证列持久化写入与快照失效信号已抽到 `orbit.application.credentials.CredentialService`
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
- **完成结果（2026-07-14）**：新增 `research/runs.py`（`ResearchWorkflowService` + `AllowlistedRunner`）、`research/protocols.py`、`persistence/research_runs.py`（哈希链 run 账本）；`research.py` 加 `POST /candidates`（创建即冻结）、`POST /runs`（触发评估）、`POST /datasets/fetch`（独立拉数据）；前端 ResearchPage 加创作+触发+进度交互。
- **验收结论（Claude，2026-07-14）：通过（四护栏在写路径全焊死，且多防作弊）。** 后端护栏经真载荷测试：**冻结不可改**（`test_frozen_candidate_cannot_be_changed_or_replaced`）；**锁箱只开一次**（`test_run_is_append_only_and_lockbox_can_open_only_once`：二次开→`already been opened`）；**结果只追加**（哈希链账本）+ 结果绑定候选 `frozen_hash`；**verdict 对固定 bar**（阈值在冻结候选内、改阈值即新候选）；**额外**：`test_run_fails_if_cached_dataset_changes_after_freeze`（冻结后换数据→run 失败 `fingerprint changed`，堵死数据掉包）、只跑 allow-list 工具/缓存数据/不碰网络（无任意命令执行）、单活跃 run。前端写入口 import/export resolve（`createResearchCandidate/startResearchRun` 接对 guarded 端点）。`272 passed`（+8）。合并在 `main`（`2bc06e2`）。**验证边界**：前端 `npm run check/build` 与渲染待 Windows 复验。路线图第 4 项完成（研究平台 UI 全套后端护栏就绪）。
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
| 5 | **运维打磨（已完成）** | 见下「任务 OPS-1」 | 低 |

**贯穿纪律（所有任务）**：保持测试绿；不改 live 默认开关；研究相关一律焊死「预注册冻结不可改 / 锁箱开一次 / 结果只追加 / verdict 对固定 bar」四护栏；前端本机无 node，`npm run check/build` 需 Windows 复验。

**UI-P0 完成记录（2026-07-14）**：已新增研究数据目录、M0/F1/G1/G2 冻结候选登记簿和 JSON 结果读模型，并提供管理员只读 API：`GET /api/research/datasets`、`/candidates`、`/candidates/{id}`、`/results/{id}`。候选登记簿使用 JSONL 哈希链只追加保存，重复 ID、覆盖和指纹篡改均会被拒绝；未改动 CLI 计算逻辑和 live 默认开关。

**UI-P1 完成记录（2026-07-14）**：研究平台前端已接入 UI-P0，只读展示数据目录、候选墓地、冻结定义、固定 bar、锁箱溯源和结构化结果证据；桌面/移动端及筛选、候选切换均完成真实浏览器验收。

**UI-P2 完成记录（2026-07-14）**：研究平台已形成「选择白名单协议与缓存数据 → 冻结候选和数据指纹 → 后台运行固定评估器 → 轮询进度 → 只追加 verdict/结果」闭环；锁箱开箱仅一次，联网拉新数据为独立任务且不覆盖旧缓存。研究平台 P0/P1/P2 路线完成。

### 任务 OPS-1：跨平台运维打磨（优先级：低）

- **问题**：平台按 Windows 开发——`backend/scripts/` 只有 `.cmd`/`.ps1`，README 为 PowerShell + `C:\Users\...` 路径；`LocalCredentialVault` 用 Windows DPAPI，Linux 调用 `protect()` 抛错；前端在无 node 的 Linux 上无法本地构建。
- **涉及文件**：`backend/scripts/`（补 bash）；`infrastructure/credentials/`（Linux vault adapter）；`README.md` / `docs/`。
- **改动**：① 补一套 Linux/bash 启动/校验脚本（对应现有 `.cmd`/`.ps1`）；② 新增 Linux 凭证 vault adapter（或统一走 `env:` 引用），使非 Windows 也能保存凭证；③ README/文档补 Linux 运行说明与前端 Windows 侧构建复验流程。
- **验收**：Linux 下可按文档启动后端、跑校验；凭证在 Linux 可保存/读取；文档无自相矛盾。
- **完成结果（2026-07-14）**：新增 bash 脚本（`run_server/run_server_mysql/setup_mysql/check_mysql/verify/healthcheck.sh`，`set -eu`）；新增 `AesGcmCredentialVault`（AES-GCM 认证加密、随机 nonce、master key 走 `ORBIT_CREDENTIAL_MASTER_KEY` env）+ `factory.create_credential_vault`（Linux→AES-GCM、Windows→DPAPI 自动选择）+ `generate_vault_key.py`；README/ARCHITECTURE/技术方案补 Linux 说明；`requirements.txt` 加 `cryptography`。
- **验收结论（Claude，2026-07-14）：通过。** vault 为标准安全构造（非自制加密）：`test_round_trip...` 随机 nonce/不泄明文/可解回；`test_tampered_ciphertext_and_wrong_key_are_rejected` 篡改密文与错密钥均 `Failed to decrypt`（GCM 认证）；缺 master key 时加密被挡但 `env:` 引用仍跨平台可用；DPAPI 旧引用有清晰迁移报错；`test_auto_selects_aesgcm_on_linux_and_dpapi_on_windows` 验证 factory 选择 + Linux 往返可用。bash 脚本齐全。`279 passed`（+7）。合并在 `main`（`128fb83`）。**小观察（非阻断）**：新增编译依赖 `cryptography`——但仅加密-at-rest 需要，`env:` 引用路径无需它，符合「运行时精简」精神。**路线图第 5 项完成——全部 5 项完成。**
- **约束**：不改交易逻辑与 live 开关；纯运维/跨平台补齐。

**OPS-1 完成记录（2026-07-14）**：新增 POSIX `sh` 启动、MySQL 初始化/检查、HTTP 健康检查和一体化验证脚本；凭证工厂按平台自动选择 Windows DPAPI 或跨平台 AES-256-GCM，Linux 主密钥仅从 `ORBIT_CREDENTIAL_MASTER_KEY` 注入，数据库继续只保存密文引用/环境引用和指纹。新增随机 nonce、篡改、错密钥、缺失密钥、平台选择与迁移错误测试；README、交接文档和技术方案已统一跨平台口径。未改交易逻辑和 live 默认开关。

## 小资金实盘阶段（2026-07-30，决策记录 + 交付 Codex）

**决策（用户拍板，2026-07-30）**：研究目的是实盘，不接受纯 paper 等待。据此调整路线：**小资金实盘与 TB4 paper 前向并行**——paper 前向照常部署作为记账基准，同时用预先冻结的小额资金按系统目标权重**手动**周频执行实盘。理由：任何长度的前向验证都无法产生确定性，理性路径是"小仓位立即实盘 + 规模随证据调整"；纪律全部预先写死在 `docs/design/LIVE_SMALL.md`（初始规模冻结 / 每 3 个月按条件加仓 / 回撤 30% 或系统性偏离即停 / 参数不可变）。**live 自动下单通道继续焊死不动**，实盘执行为人工照清单下单。

**后续研究方向**：本策略进入实盘观察后，研究线转向**第二个低相关 sleeve** 的探索（与趋势 sleeve 互补）；候选方向另行预注册，继续走研究平台四护栏流程（预注册冻结 / 锁箱开一次 / 结果只追加 / verdict 对固定 bar）。

### 任务 LIVE-1：前向目标权重的实盘执行清单投影（优先级：高，交付 Codex）

- **问题**：手动实盘需要"照着下单"的清单，但 `TrendForwardService.snapshot()` 里只有 `runner.snapshot()` 的 `weights`（每币带符号权益占比）。人工换算方向/名义金额/调仓差额既繁琐又易错。
- **涉及文件**：`backend/src/orbit/application/trend_forward.py`（或新增只读投影模块）；前向监控前端页；`backend/tests/`。
- **改动**：
  1. 新增**只读**执行清单投影 `execution_checklist`：输入实盘资金规模（配置项或查询参数，如 `live_capital_usdt`；当前冻结值 500）,对每币输出：方向（LONG/SHORT/FLAT）、目标名义 USDT（`weight × capital`）、按最新收盘价折算的目标数量、与上一次清单的名义变化额。资金规模仅用于换算展示，**不进入 runner 状态、不影响账本与对齐性质**。
  1b. **最低下单额标记**：维护 12 市场的最低名义/数量步进配置（静态配置文件即可，来源 Binance 合约规则，标注获取日期），目标名义低于最低额的行标记 `BELOW_MIN_NOTIONAL → 保持 FLAT`，并在清单汇总里输出"可执行名义占目标名义的比例"，供对账时归因结构性跟踪误差（见 `LIVE_SMALL.md` 1.1）。
  2. 前向监控页展示该清单（再平衡时间、逐币行、合计 gross 校验），并提供简单的成交记录/对账模板导出（CSV 即可），承载 `LIVE_SMALL.md` 第 2 节的每周流程。
  3. **不接任何自动下单**：不新增任何触达交易所下单接口的代码路径，live 通道维持焊死。
- **验收**：① 清单为纯投影，重复计算幂等、不改 runner/账本状态（保持 TB4-A/TB4-B 对齐与哈希链性质）；② 权重×资金×价格换算有单测（含 FLAT/反向翻转/资金规模变化、低于最低下单额标记与可执行比例场景）；③ 全库 grep 无新增下单调用；④ 前端只读展示；⑤ 测试全绿。
- **约束**：不改 `TB4_SPEC` 与前向协议语义；不改 live 默认开关；`LIVE_SMALL.md` 为本任务的产品口径来源。
- **完成结果（Codex，2026-07-30）**：新增独立纯投影 `TrendExecutionChecklistProjector`，只读取最近一次**已执行再平衡的冻结目标权重**（不误用每根 K 线后会漂移的 paper 当前权重），按 `live_capital_usdt=500` 输出 LONG/SHORT/FLAT、目标名义、相对上次目标变化、最新收盘折算数量及按步进向下取整后的可执行数量；低于 `MIN_NOTIONAL`/`minQty` 的目标明确标为 `BELOW_MIN_NOTIONAL → 保持 FLAT`，汇总目标/可执行 gross 与覆盖比例。Binance 12 市场规则以版本化只读 JSON 随包交付，来源为官方 `/fapi/v1/exchangeInfo`、获取日 2026-07-30，并在超过刷新周期时向 UI 暴露 stale 警告；配置可替换规则文件但必须完整覆盖冻结 12 市场且数值合法。`TrendForwardService.snapshot()` 只读附加 `execution_checklist`，未启动/首笔再平衡前分别给出明确空态；不写 runner、不写账本。
- **前端交付**：新增“前向实盘”页面，展示前向状态、500 USDT 换算规模、目标 gross、可执行覆盖率和逐币手动执行清单；提供只在 READY 时可用的 UTF-8 CSV 成交记录模板（预留真实方向/数量/均价/手续费/订单号/时间/备注字段）。页面明确“不自动下单”，规则过期时阻止用户把清单当作可靠执行依据。
- **验收证据（Codex，2026-07-30）**：新增投影单测覆盖幂等无状态变更、LONG/SHORT/FLAT、反向翻转的名义变化、资金规模变化、步进取整、最低额与可执行比例；前向服务测试验证 snapshot 重复读取不改变 runner export state 与 ledger event count。完整后端 `284 tests OK`；`npm run check` 与生产 `npm run build` 通过；真实本地 `/api/state` 浏览器冒烟确认未启动空态、500 USDT、禁用 CSV、执行边界正常渲染且控制台无错误；`git diff --check` 通过；本任务 diff 未新增 `place_order`、`/fapi/v1/order` 或开启 live 的代码。
- **验收结论（Claude，2026-07-30）：通过（`2a0f62e`）。** 独立复核关键项：① 纯投影成立——projector 只读 runner 的 `rebalances/closes/times`，`test_projects_direction_quantity_flip_and_minimums_without_mutation` 断言投影前后 runner 状态不变，前向服务测试另证 snapshot 重复读取不动 `export_state()` 与账本计数；② 规格场景单测齐全（方向翻转、FLAT、资金规模跨越最低额、`BELOW_MIN_NOTIONAL`、可执行占比）；③ 红线干净——本机全库 grep 确认 `place_order`/`order_execution.py` 均属旧提交 `16ce8d1`（默认全关），本次零触碰；④ 前端无写请求，CSV 为客户端导出且仅 READY 可用；⑤ 本机全量 `291 passed / 1 skipped`（+12）。**设计取向（认可）**：清单锚定「最近一次已执行再平衡的冻结目标权重」而非逐根收盘漂移的当前权重，与周频手工执行的稳定指令需求一致，优于规格原文的字面表述。**部署提醒**：`tb4_exchange_rules.json` 为静态登记值（BTC 最低名义 50 等），部署时须对照实时 `exchangeInfo` 复核并更新 `fetched_at`；stale 警告机制已内建。

### 任务 LIVE-2：实盘执行核对——真实持仓 vs 目标清单 + 权益对账（优先级：高，依赖 LIVE-1，交付 Codex）

- **问题**：`LIVE_SMALL.md` 第 2 节要求每周执行后核对、每月与 paper 基准对账，目前只能人工比 CSV。需要系统自动回答两个问题：**"我这周是否正确执行了策略？"**（持仓核对）和 **"实盘轨迹与 paper 基准差多少、差在哪？"**（权益对账）。
- **涉及文件**：复用 Binance 只读同步（真实持仓/余额，平台已有）；LIVE-1 的 `execution_checklist`；新增只读对账投影（如 `application/live_reconciliation.py`）；前向监控前端页；`backend/tests/`。
- **改动**：
  1. **持仓核对（每次账户同步后可算）**：把同步到的真实合约持仓与最新执行清单逐币比对，输出每币状态：`MATCH`（方向一致且数量偏差在容差内，容差 = 数量步进 + 可配置百分比）、`DEVIATION`（方向不符或超容差，给出差额）、`EXPECTED_FLAT`（清单标记低于最低下单额、实际空仓，属正常）、`UNEXPECTED_POSITION`（清单外币种持仓）。汇总输出本次执行正确率与偏差清单。
  2. **权益对账**：按同步时点记录实盘账户权益序列（只追加），与 paper 基准净值曲线同图展示，输出累计偏差和逐周偏差；偏差归因第一版保持简单——用清单"可执行名义占比"标注结构性部分，其余留人工判断，不做过度建模。
  3. **只读、不纠偏**：发现偏差只展示和提示,不自动下单纠正（live 通道维持焊死）；`DEVIATION`/`UNEXPECTED_POSITION` 在前向监控页醒目标出，供用户当场手动处理或记录原因。
- **验收**：① 核对与对账均为纯只读投影，不改 runner/账本/同步状态；② 四种状态判定（含容差边界、方向翻转、EXPECTED_FLAT、清单外持仓）有单测；③ 实盘权益序列只追加持久化有测试；④ 全库 grep 无新增下单调用；⑤ 前端展示核对结果与双曲线对比；⑥ 测试全绿。
- **约束**：不改 `TB4_SPEC` 与前向协议语义；不改 live 默认开关；偏差处理永远归人工。
- **完成结果（Codex，2026-07-30）**：新增独立 `LiveReconciliationService`，只对配置项 `trend_forward.live_account_id` 显式指定的主网、非 dry-run 账户生效，不猜测账户。每次只读同步成功并提交后，以 LIVE-1 最近一次冻结再平衡清单核对实际持仓；按“数量步进 + 目标数量百分比”容差输出 `MATCH`、`DEVIATION`、`EXPECTED_FLAT`、`UNEXPECTED_POSITION`，并汇总执行正确率和偏差清单。核对仅展示，不生成纠偏计划、不调用订单接口、不改变 runner、TB4 账本或账户同步状态。
- **权益对账交付**：新增独立 JSONL SHA-256 哈希链账本，账户同步成功后幂等追加实盘权益、同期 paper 权益、paper 行情/再平衡时点及可执行名义比例；拒绝倒序记录、重复同步不重复写入，写入前验完整链并 `fsync`。同步状态先提交、观测后追加；观测异常会随同步响应和监控投影显式报告，不回滚已成功的账户同步。监控投影将首个有效点归一为 1.0，同图展示实盘/paper 曲线，输出累计偏差、按 ISO 周最后观测点计算的逐周偏差和结构性可执行比例；账本篡改显示 `DATA_INTEGRITY_ERROR`。前端无自动纠偏入口。
- **验收证据（Codex，2026-07-30）**：单测覆盖四种持仓状态、方向翻转、容差等号边界、未配置/测试网阻断、权益幂等追加、归一化与逐周偏差、非法 paper 权益/时间戳隔离、哈希篡改检测；账户同步测试证明持久化提交先于观测追加，权限测试证明业务用户不能读取其他账户对账。完整后端 `292 tests OK`；`npm run check` 与生产 `npm run build` 通过；`git diff --check` 通过；本任务 diff 未新增 Binance 下单调用或开启 live 默认开关。
- **验收结论（Claude，2026-07-30）：通过（`2a0f62e`）。** 独立复核关键项：① 只读成立——`read_only=True`、`auto_correction=False`，核对纯计算无状态变更，快照按账户可见性过滤（不可见回 `NOT_VISIBLE`）；② 四状态判定齐全、容差边界含等号（`test_tolerance_boundary_is_inclusive`），容差=步进+可配百分比，Hedge Mode `LONG/SHORT/BOTH` 折算正确（LONG 取正、SHORT 取负、同币聚合）；③ 权益账本哈希链只追加、拒绝重复与时间倒退、`fsync` 落盘，篡改检测有测试（`test_hash_chain_detects_tampered_equity_observation`）；④ 记录钩子在事务提交之外执行且异常不打断账户同步（`test_invalid_paper_equity_and_timestamp_do_not_raise_from_sync_hook`），testnet/dry_run/未配置账户被明确阻断；⑤ 前端双曲线（`MultiLineChart` 归一化实盘/paper）与偏差醒目展示确认存在；⑥ 本机全量测试绿。**部署提醒**：`live_account_id` 默认空，部署时须填入实盘账户 ID 核对才激活。附带验收 `4798672`（Windows 启动脚本 Python 解析可移植化：`PYTHON_BIN`→`.venv`→PATH，纯运维，无异议）。Codex 声称的 `npm run check/build` 通过系其 Windows 侧运行结果，本机无 node 无法独立复跑，予以采信并留此记录。

### 任务 LIVE-3：自动执行冻结清单 + 逐单比对验证（优先级：高，依赖 LIVE-1/LIVE-2，交付 Codex）

**决策背景（2026-07-30）**：用户明确要求实盘由自动下单执行，且实盘下单必须与策略计划比对、验证正确执行。协议已升级 `LIVE_SMALL.md` V2（执行方式改自动，四条铁律不变）。本任务首次打开 live 下单路径,护栏必须**机制化到位后才允许启用**。

- **问题**：LIVE-1 产出冻结执行清单、LIVE-2 做持仓核对，但执行环节仍靠人工。需要：再平衡后自动把持仓调整到清单目标，且每笔订单可逐一映射回清单、成交结果逐币比对留痕。
- **涉及文件**：新增 `application/live_execution.py`（自动执行服务）；复用 `16ce8d1` 已有下单端口（`order_execution.py` / `infrastructure/exchange/binance.py` 的 `place_order`）；新增只追加执行账本（哈希链，同 `live_equity_ledger` 构造）；`tools/run_tb4_forward.py` 轮询接线；snapshot 投影 + `ForwardPage.vue` 执行报告区；`config`；`backend/tests/`。
- **改动**：
  1. **触发与流程**：前向轮询检测到**新的已执行再平衡**（`rebalance_time_ms` 变化）后，对配置的实盘账户执行一轮：只读同步账户 → 以 LIVE-1 冻结清单的 `signed_target_quantity` 与实际持仓求差 → 差额按步进取整、低于最低量/最低名义则跳过（防尘埃单）→ 市价单逐币下单 → 再次同步 → 触发 LIVE-2 核对。每个 `rebalance_time_ms` 至多执行一轮（幂等,重启不得重复执行,以执行账本为准）。
  2. **唯一指令源**：订单参数只能由冻结清单行派生；执行账本逐笔记录 `checklist 行 → 订单意图 → 交易所回执 → 成交结果` 的完整映射。出现任何无法映射到清单行的订单记录即标记 `PROTOCOL_VIOLATION` 并急停。
  3. **逐单比对（用户核心要求）**：执行完成后生成执行报告：逐币输出 `目标数量 / 下单数量 / 实际成交数量 / 成交均价 vs 收盘价滑点 / 手续费 / 状态`（`EXECUTED_MATCH` / `PARTIAL_FILL` / `ORDER_FAILED` / `SKIPPED_DUST` / `SKIPPED_BELOW_MIN`），汇总执行成功率；随后 LIVE-2 持仓核对作为第二道独立验证。报告与账本只追加,snapshot 只读投影,前端展示。
  4. **护栏（全部机制化,缺一不得启用）**：
     - 总开关 `trend_forward.auto_execution_enabled` 默认 **false**;启用还须同时满足:`live_account_id` 已配置、账户为主网非 dry_run、账户为单向持仓模式（拒绝 Hedge Mode）、清单 `READY` 且规则未过期（`rules_stale=false`）、账户同步新鲜（可配置最大时龄）。任一不满足则本轮拒绝执行并记录原因。
     - 单笔名义上限（config,默认 150 USDT）与单轮总名义上限（清单目标 gross 的 1.1 倍封顶）;超限拒绝并告警,不截断静默执行。
     - **失败不追单**：单币下单失败记录后跳过,不重试超过 1 次、不改价追单;残余偏差交 LIVE-2 显式暴露,人工决定。
     - **急停不对称**：管理员急停 API（`POST`,必填 reason,写审计）立即置停,拒绝一切新订单;重新启用只能改配置文件并重启进程。
     - **协议停机制化**：执行前检查 LIVE-2 权益账本,实盘或 paper 自基准回撤 ≥ 30% 时拒绝执行并标记 `PROTOCOL_STOP`（`LIVE_SMALL.md` 1.3 的机制化）。
     - 执行器**永不**修改杠杆/保证金模式/持仓模式;部署时人工设定（1x、单向）,执行器只校验不设置。
  5. **不碰既有性质**：runner、TB4 账本、对齐性质、`TB4_SPEC` 零改动;paper 前向照常独立记账。
- **验收**：① 默认关闭——全部现有测试在默认配置下无任何下单调用;启用条件缺一拒绝（逐条测试）;② 幂等——同一 `rebalance_time_ms` 重复触发/进程重启不重复下单（以账本为准）;③ 逐单映射——每笔订单可追溯到清单行,注入无映射订单记录触发 `PROTOCOL_VIOLATION` 急停;④ 比对报告——五种状态判定、滑点计算、部分成交与失败路径有单测（mock 网关,含下单异常）;⑤ 上限与回撤拒绝——超单笔/总额上限拒绝、权益回撤 ≥30% 拒绝并 `PROTOCOL_STOP` 有测试;⑥ 急停——API 急停后新订单被拒且写审计,重启前不可恢复;⑦ 执行账本哈希链只追加防篡改;⑧ 测试全绿,`git diff --check` 通过。
- **约束**：唯一指令源为冻结清单;不改 `TB4_SPEC`/前向协议/TB4 账本;失败不追单;急停易于触发、启用刻意;`LIVE_SMALL.md` V2 为产品口径来源。**mock 网关完成全部测试,真实下单只在部署后由用户启用总开关**。
- **完成结果（Codex，2026-07-30）**：新增 `LiveExecutionService` 与 JSONL 哈希链执行账本；Orbit 后端成为 TB4 paper 轮询和 LIVE-SMALL 自动执行的唯一 writer。每轮先同步、按冻结清单计算目标差、按规则取整与过滤、落盘 `ROUND_STARTED` 后以确定性 `clientOrderId` 发送市价单，再同步并生成逐单成交/滑点/手续费与 LIVE-2 持仓核对报告。同一 epoch/再平衡只消费一次；未完成轮次、账本篡改、清单映射不一致、Hedge Mode、陈旧规则/账户快照、单笔/单轮超限及 paper/live 回撤 ≥30% 均 fail closed。管理员急停与下单门使用同一并发闸，急停返回后不会再发送新订单；重新启用必须改 epoch 并重启。默认 `auto_execution_enabled=false`，本轮没有真实下单。
- **验收证据（Codex，2026-07-30）**：LIVE-3 定向回归 `40 tests OK`，完整后端 `304 tests OK`；`npm run check`、生产 `npm run build`、浏览器前向实盘页冒烟和控制台检查通过；执行测试全部使用 mock gateway，覆盖五种逐单状态、滑点/手续费、成交查询失败保留订单回执、启用闸门、幂等、金额上限、双权益回撤、急停、未映射记录、未完成轮次和账本篡改。新增公开 `exchangeInfo` 规则刷新工具及 MARKET_LOT_SIZE 解析测试，避免静态规则过期后无可持续恢复路径。部署手册已改为先 `--initialize --once`，随后由后端单 writer 常驻；禁止同时运行独立持续轮询器。
- **验收结论（Claude，2026-07-30）：通过（`87f772b`）。** 逐条独立复核八项验收：① 默认关闭实证——`test_default_disabled_performs_no_sync_or_order`，且全库 `place_order` 调用点仅旧 `order_execution.py:131` 与新 `live_execution.py:442`（后者在下单闸内、逐单前复查急停）；② 幂等实证——重复触发返回 `ALREADY_CONSUMED` 且 mock 网关订单数保持 1，重启后未完成轮次触发 `PROTOCOL_STOP`（`test_incomplete_claim_stops_later_round_after_restart`）；③ 逐单映射——`ROUND_STARTED` 固化清单 SHA-256 与逐行哈希，`ORDER_RESULT` 带 `checklist_row_sha256`，注入无映射记录触发 `PROTOCOL_VIOLATION` 闩锁（`test_emergency_stop_and_injected_unmapped_order_latch_execution`）；④ 五状态/滑点（BUY/SELL 符号正确）/手续费/成交查询失败保留回执均有测试；⑤ 单笔与单轮上限、双权益回撤 ≥30% 拒绝有测试；⑥ 急停与下单同闸、写审计、恢复须改 epoch+重启（不对称成立）；⑦ 执行账本哈希链防篡改有测试；⑧ 本机全量 `303 passed / 1 skipped`（+12，含 4 子测试）。**关键安全点专项核实**：Hedge Mode 拦截字段链路 `dualSidePosition→position_mode.dual_side_position` 正确，且 position_mode 与账户/持仓同一 try 拉取、失败即非 `synced`，护栏无静默放行路径。**两个超规格的好设计（认可）**：`trend_forward.enabled=true` 时独立轮询工具被限制为仅 `--initialize --once`（单 writer，防双执行器）；新增 `fetch_tb4_exchange_rules.py` 公开接口规则刷新工具（解决 LIVE-1 验收提醒的静态规则可持续性）。**已知运营行为（刻意 fail-closed，接受并须知晓）**：`ROUND_REJECTED` 永久消耗该再平衡——瞬时故障（如同步失败）会跳过整周执行不重试，残余偏差由 LIVE-2 暴露、状态页显示 REJECTED；协议第 2 节的每周人工查看即为此兜底。Codex 报告 `304 tests OK` 与本机口径一致（303+1 skipped）；`npm run check/build` 系 Windows 侧结果，采信留痕。
- **文档验收（Claude，2026-07-30）：`TB4_OPERATIONS.md` 修订通过，另修正 3 处（已由本人直接修正并留痕）。** 核对通过项：§5 配置键与 `config.sample.json` 一致；`--initialize --once` 与单 writer 守卫一致；急停 epoch 锁定语义与代码一致；暖机 1,009 根（168 天 × 6 + 1）正确；§4 判定门与 TB3 冻结门逐项一致；`fetch_tb4_exchange_rules.py` 默认输出路径与配置示例吻合；账户安全清单（主网/单向/1x/仅合约权限/禁提现/IP 白名单）与代码护栏对应。修正项：① §0/§6/§7 仍保留旧路线「不上真钱、PASS 才讨论小资金 live」表述,与已冻结的 `LIVE_SMALL.md` V2（小资金实盘并行）矛盾——已补澄清:并行实盘受 LIVE-SMALL 协议管辖,规模变更只走协议 1.2/1.3,paper 早期表现不是加仓依据,两本账独立；② §1 环境准备缺实盘部署必需的 `ORBIT_CREDENTIAL_MASTER_KEY` / `cryptography` 步骤（不配则实盘凭证无法保存）——已补第 6 步并交叉引用 README；③ 版本行未随实质修订更新——已改为 2026-07-30 V2。

### 任务 UI-R1：四核心导航重构 + 策略中心首屏（优先级：高，交付 Codex；含 SC-2 精简版）

**决策背景（2026-07-30，用户提出方向、Claude 定稿）**：现导航仍围绕已 NO-GO 的双网格工作流组织（工作台漏斗/执行计划/币种视图），与项目真实形态（趋势策略 + 研究平台 + 小资金实盘）脱节。用户提出四核心方向（策略中心/账户中心/研究平台/实盘中心）,Claude 确认采用并定稿如下职责边界;策略中心首屏与本任务合并交付,避免核心导航挂空页。

**四核心职责定义（产品口径,PAGE_META 文案据此撰写）**：

| 核心 | 回答的问题 | 负责 | 永不负责 |
|---|---|---|---|
| **实盘中心**（默认页） | 「系统现在一切正常吗？这周执行对了吗？」 | paper 前向进度与健康、冻结执行清单、自动执行状态与逐单报告、持仓核对、实盘/paper 权益对照、急停 | 修改任何参数;解释策略原理与历史证据 |
| **策略中心** | 「正在运行的策略是什么、为什么可信？」 | 冻结定义、普通语言原理、结构化证据、当前信号解释、已知风险、生命周期状态 | 调参、下单、启停;承载任何写操作 |
| **研究平台** | 「下一个候选如何被诚实地检验？」 | 数据目录、候选注册（含墓地）、预注册冻结、锁箱、job 运行、verdict | 触碰生产策略与实盘;放宽四护栏 |
| **账户中心** | 「用户、账户、凭证、同步状态如何？」 | 业务用户与交易账户关系、API 凭证（不回显明文）、Binance 只读同步 | 策略内容;交易动作 |

**两个附带决策**：① **不保留独立工作台**——「一切正常吗」由实盘中心页首的系统健康条回答（paper 前向状态/自动执行状态含急停红显/最近核对结果/账户同步时龄,四格一行）,避免和实盘中心重复;② **治理页面（风控中心/报表/审计）暂入归档组**——其内容绝大部分是双网格内核投影,TB4 实盘的风控（急停/PROTOCOL_STOP/回撤停机）已在实盘中心呈现;待实盘跑稳后再评估是否为 TB4 建独立审计视图。

- **目标导航**：
  ```
  核心（一级,无分组标题或单组）
  ├── 策略中心  #strategy   （新页,SC-2 精简版,见下）
  ├── 研究平台  #research   （现有,不动）
  ├── 实盘中心  id=forward  （现前向实盘改名,新增别名 #live→forward）
  └── 账户中心  #accounts   （现「用户与账户」改名）
  旧网格（存档,折叠分组,默认收起）
  ├── 工作台 / 执行计划 / 币种视图 / 风控中心 / 报表
  ```
- **改动**：
  1. `App.vue` navGroups 按上表重构；默认登陆页由 `dashboard` 改为**实盘中心**（`forward`）；`labels.js` 改名与 `PAGE_META` 文案按四核心职责定义撰写,新增 `live→forward` 别名,删除 `strategy→dashboard` 别名（`#strategy` 让位给新页）;既有 `#dashboard/#plans/#symbol/#risk/#reports/#events/#logs` 全部保持可达（归档组或重定向）。
  1b. **实盘中心页首系统健康条**：四格一行——paper 前向（状态/进度）、自动执行（ENABLED/DISABLED/EMERGENCY_STOPPED/PROTOCOL_STOP,异常红显）、最近持仓核对（MATCH/DEVIATION 计数）、实盘账户同步时龄;全部复用现有快照字段,不新增后端接口。
  2. **策略中心首屏（SC-2 精简版,遵循 `STRATEGY_CENTER.md`,不越界）**：① 身份与状态区——策略名/ID/版本/冻结定义哈希/运行模式,**并行态强制表述**（采纳设计评审意见①:显示 `LIVE_PILOT(500 USDT)` 时必须同时显示 paper 前向进度,不得表述为已从 paper 毕业）;② 普通语言原理摘要;③ 冻结参数表——由后端从 `TB4_SPEC` 序列化导出（SC-1 的定义部分:`StrategyDefinition` + `GET /api/strategies`、`GET /api/strategies/{id}` 定义摘要,证据接口后置）,前端零参数副本;④ 已知风险区（`STRATEGY_CENTER.md` §4.6 文案）;⑤ 「查看实盘中心/研究平台/风控」跳转。**证据区如实显示「结构化证据尚未接入（待 SC-1 bundle + SC-4）」,禁止手抄任何回测指标充数。**
  3. 归档组页面功能零改动。
- **验收**：① 导航呈现四核心 + 折叠归档,默认页为实盘中心;② 全部旧锚点可达（逐条测试重定向/归档可达）;③ 策略中心冻结参数与 `TB4_SPEC` 逐项相等且来自后端接口（对照测试）,全前端 grep 无 TB4 参数常量副本;④ 无任何手抄回测指标;⑤ 匿名 401、业务用户不见部署细节（权限测试）;⑥ 后端测试全绿,`npm run check/build` + 桌面/窄屏冒烟（Windows 侧）;⑦ `git diff --check` 通过。
- **约束**：不改交易行为、`TB4_SPEC`、各账本与 LIVE-3 协议;SC-3（信号表）/SC-4（证据图表）/SC-5（对照）不在本批,后续独立交付;`STRATEGY_CENTER.md` 为策略中心的设计上限,本批只做其子集,不新增设计外内容。
- **验收结论（Claude，2026-07-31）：通过（`a5a5046`），附两处菜单修正（已由本人直接修正）。** 核查项全过：① 冻结参数逐字段对照测试 `test_serialized_spec_matches_frozen_runner_field_for_field`，前端 grep 无 TB4 参数常量副本，参数由 `strategy_catalog.py` 从 `TB4_SPEC` 序列化;② 并行态强制表述落实——`LIVE_PILOT` 时显示「小资金实盘与纸面前向并行…不代表纸面前向已经毕业」并附前向进度,有专测 `test_live_pilot_keeps_parallel_paper_forward_progress`;③ 证据区如实显示「结构化回测证据尚未接入」,无手抄指标;④ 实盘中心页首系统健康条已交付;⑤ 匿名 `/api/strategies` 返回 401,未知策略不臆造（`test_unknown_strategy_is_not_synthesized`）;⑥ 别名 `live→forward` 新增、`strategy→dashboard` 删除,归档组折叠可达;⑦ 本机全量 `307 passed / 1 skipped`（+4）。**本人修正两处（用户反馈菜单仍不合理,判断为客观问题）**：删除唯一分组的「核心」组标题（单组无需标题,纯噪音）;菜单顺序改为实盘中心/策略中心/研究平台/账户中心（默认页排第一,消除高亮错位）。前端改动照例待 Windows `npm run check/build` 复验。
- **完成结果（Codex，2026-07-30）**：四核心导航与默认实盘中心已落地，旧双网格五页进入默认折叠的存档组，`#events/#logs/#live` 兼容锚点分别落到工作台/报表/实盘中心；实盘中心页首新增四格健康条，全部复用现有快照。新增只读 `StrategyCatalogService`、`StrategyDefinition` 与 `/api/strategies` 两级接口，冻结参数直接从 `TB4_SPEC` 序列化，生命周期用 `phases + primary` 表达 paper/live 并行；接口只返回脱敏运行摘要。策略中心首屏已展示身份、哈希、并行状态、普通语言机制、冻结参数、文档规定的已知风险和跨中心跳转；结构化证据明确标为尚未接入，没有手抄回测指标。未修改 runner、`TB4_SPEC`、交易行为或任何账本。
- **验收证据（Codex，2026-07-30）**：新增字段级 spec 对照、paper/live 并行语义、未知策略、匿名 401、业务用户脱敏 API 测试；完整后端 `308 tests OK`，`npm run check`、生产 `npm run build`、`git diff --check` 通过。浏览器确认默认 `#forward`、策略中心真实接口渲染、存档默认收起、八个旧/别名锚点可达且控制台无错误；桌面视觉冒烟通过。当前浏览器控制面不提供 viewport 调整，窄屏实际视觉冒烟仍需在可调整窗口环境补证，响应式规则与生产构建已完成。

### 架构评审：多账户短线策略平台（Claude，2026-08-10）

**对象**：`docs/design/MULTI_ACCOUNT_SHORT_STRATEGY_ARCHITECTURE.md`（`f012ee7`,状态 PROPOSED）。**结论：设计评审通过——工程质量高、诚实边界清晰;但附带一个结构性前置条件与三项修正,在其满足前不应启动阶段 1 之后的平台建设投入。**

**认可的部分**：① ADR-01~06 全部站得住（单账户单策略、共享行情/隔离执行、持久化租约+fencing token、至少一次+幂等副作用、组合级事件回测唯一准入口径、满仓不抢占并留反事实证据）;② 状态机与故障表完整,`UNKNOWN` 订单纪律、fail-closed 默认、`MANAGE_ONLY`、币池迟滞设计专业;③ 与现有体系的边界处理正确（TB4 作 legacy 只读导入、bounded context 分离、不改冻结 hash）;④ §16 诚实自列七项未完成证据,明确「不授权真实资金运行」。

**结构性前置条件（最重要）**：本架构为一个**尚无任何证据的策略族**（分钟级突破/动量、超跌反弹）规划了数月级平台投入,顺序颠倒了本项目自己的纪律——**证据先于基建**。F/G 系列的教训正是这类事件型候选在诚实成本下大概率死亡。要求插入**阶段 R-0：策略族先行筛查**——用预注册事件研究（现有机器:C8 统计门+事件采样）在样本数据上先回答「突破/超跌反弹扣除点差+冲击+费用后是否存在正期望迹象」,廉价、几轮计算的量级;R-0 亡则阶段 1–5 全部投入免掉,R-0 活才解锁平台建设。这与本文 ADR-05 精神一致,只是把它提到基建之前。

**三项修正**：① **DATA-1 复活为硬前置**——本文 §2.2 明确禁止「依赖仍存活币种回推历史币池」,这在字面上就需要含退市合约的全量历史（DATA-1,当前状态暂缓）;阶段 2/3 的历史币池重建与 replay 没有它无法诚实进行。评审时曾建议扩展到 1m 并单独评估百 GB 级存储，后续用户已将 DATA-1R 最细粒度定稿为 15m、1h/4h 本地聚合，1m/5m 不在当前范围，以后如需更细粒度须重新立项。② **历史点差/深度数据源可行性验证**——币池政策与成交性模拟依赖历史 bid/ask 与深度,公开归档仅部分提供（bookTicker/bookDepth 覆盖范围与起始时间需实测）;此项不落实,§9 的「使用当时 bid/ask」是无源之水,须在冻结 UniversePolicy 前完成数据源核查并写入证据。③ **排期不得挤占现有主线**——TB4 paper 前向与 LIVE-SMALL 的部署运行仍是第一优先级;本架构各阶段执行前须逐阶段经用户显式排期确认,不默认连续推进。

**另行登记**：`8d5cf2c`~`842fe89`（实盘启用向导、杠杆校验、V3 逐仓 3x）为实盘资金相关改动,已于同日完成批量验收,见下节。

### 批量验收：实盘启用向导 + LIVE-SMALL V3 + 认证收紧（Claude，2026-08-10）

**对象**：`b192532`（HelpTip 悬停修复）、`4c7933c`（MySQL 目录权威化）、`8d5cf2c`/`ec0b8a9`（实盘启用向导与布防流程）、`4e3fbe3`（杠杆校验接口修正）、`842fe89`（LIVE-SMALL V3 逐仓 3x）。**结论：全部通过。** 本机全量 `339 passed / 1 skipped`。

**关键护栏逐项核实**：
1. **V3 倍数冻结且旧授权失效**：`LIVE_EXPOSURE_MULTIPLIER=3.0` 为模块常量,清单协议升为 `LIVE_SMALL_EXECUTION_CHECKLIST_V3`;持久化授权风险字段不匹配即失效降级（`test_legacy_live_authorization_is_invalidated_fail_closed`、`test_legacy_config_cannot_authorize_v3_execution`）。
2. **逐轮配置回读门**：每轮下单前 `_exchange_configuration_gate` 经 `/fapi/v1/symbolConfig` 回读 12 市场,任一市场杠杆≠3、非逐仓或自动追加保证金开启即整轮拒绝;`4e3fbe3` 修正了用 `positionRisk` 验空仓市场的错误（该接口只返回有持仓/挂单的交易对）,有专测。
3. **启用摩擦等价性成立**（对照远期路线红线）：后端强制确认短语（`PREPARE LIVE ACCOUNT`/`ENABLE LIVE SMALL V3`）+ 严格新 epoch + 激活时无条件重新预检（12 项,含空仓/无挂单/权益≥500/单向持仓/12 市场逐仓 3x/order-test 权限）+ 管理员审计;急停后 epoch 永久锁定,恢复须走完整流程。「停止易、启用刻意」保持。
4. **下单调用面未扩大**：仍仅 `order_execution.py`（默认关）、`live_execution.py`（闸内）、`binance.py` 网关三处。
5. **认证收紧正确**：MySQL 目录权威、业务用户不能登录控制台、生产模式拒绝 bootstrap 默认密码,有契约测试。

**重要语义观察（需用户知晓并决策,不阻断验收）**：V3 将实盘目标放大 3 倍,但 30% 停机线**未同步调整**。TB-R 样本外最大回撤为 1 倍口径的 `15.08%`——同样的行情路径在 3 倍下对应约 `45%` 实盘回撤,将在 paper 回撤约 `10%` 时就触发 30% 停机。即：**按本策略的历史正常回撤形态,V3 实盘大概率会在一次普通回撤期内触发停机**,把可恢复的回撤变成已实现的停止（且协议已诚实注明:停机只停新单、不自动平仓,30% 不是硬性最大损失）。这不是实现缺陷,是 ×3 与 30% 线的交互改变了协议语义。两个可选方向：(a) 保持现状——接受「较易停机→人工复盘重启」的保守行为;(b) 预注册 V4 将停机线改按 paper（1 倍）口径或分级处理。**需用户明确选择,在此之前按现状运行。**
**用户决策（2026-08-10）：选 (a) 保持现状。** 30% 停机线维持双口径（实盘 3 倍与 paper 1 倍各自对 30%）不变;接受「普通回撤期较大概率触发停机→停新单不平仓→人工书面复盘后决定是否新 epoch 重启」的保守行为。首次触发停机时按 `LIVE_SMALL.md` V3 §4 流程处理,不视为异常事故。停机线的任何调整须走 V4 预注册,不得在运行中修改。

**遗留（非阻断）**：V3 协议 §3 自注的「3 倍理论权益曲线独立落账」尚未实现,复盘归因暂以逐币三层对比替代;后续作为复盘增强项。

### 远期目标形态（2026-07-31，用户定调,暂不立项）

**目标**：项目直接部署在服务器,网页上配置账号、选择策略、即可运行实盘。现状对照：网页配账号/看策略/看实盘/急停已具备;缺口按顺序——① 部署一键化（安装脚本+检查清单,锦上添花）;② **网页启用自动执行（LIVE-4,待首轮实盘跑稳后立项）**——设计红线:启用摩擦必须与「改配置+重启」等价（管理员+输入确认语句与资金额度+自动生成新 epoch+写审计+协议要点强制确认）,「停止易、启用难」的不对称不得因网页化而消失;③ 多策略选择——数据模型已预留,待第二个策略通过研究门后自然触发（策略挂载=把已准入策略绑定到账户,不是自由挑选商品）。

### 任务 UI-R4：全站文案人话化（优先级：高，交付 Codex）

**决策背景（2026-07-31，用户反馈）**：页面大部分是专业术语,用户看不懂。原则：**人话为主、术语为辅**——每个概念先用普通话说清,专业词保留在次要位置（括号/小字/悬停）,保证与文档、账本、API 口径可对照;**纯显示层改动,后端与枚举值零改动;风险语言不得为通俗而软化**（急停/停止/亏损等字样必须保留原有分量）。

- **改动**：
  1. **盘点**：清点全前端用户可见字符串（页头/区块标题/表头/状态值/按钮/提示/空态文案）,逐条改写或确认保留。
  2. **状态枚举集中人话化**：全部枚举经 `labels.js` 统一映射后再上页面,禁止裸英文枚举直出;映射示例（对齐口径,其余类推）：
     - `EXECUTED_MATCH` → 「按计划成交」;`PARTIAL_FILL` → 「部分成交」;`ORDER_FAILED` → 「下单失败」
     - `BELOW_MIN_NOTIONAL` → 「金额低于交易所最低限制,按规则不下单」;`EXPECTED_FLAT` → 「按规则空仓（正常）」
     - `UNEXPECTED_POSITION` → 「出现计划外持仓（需处理）」;`DEVIATION` → 「与计划不符（需处理）」
     - `PROTOCOL_STOP` → 「触发保护规则,已自动停止」;`EMERGENCY_STOPPED` → 「已手动急停」
     - 悬停或小字保留原始枚举值,便于与账本/文档对照。
  3. **指标术语加解释**：新增 `HelpTip` 组件（悬停/点按出一句人话）,覆盖至少：回撤（账户从最高点回落了多少;到 30% 自动停止）、名义金额（仓位价值,USDT）、滑点（实际成交价与参考价的差距）、再平衡（每周按信号调一次仓）、Funding（永续合约多空双方互付的资金费）、paper/纸面前向（模拟盘,不用真钱,用来验证策略）、锁箱（预留的"考卷"数据,只许用一次）、预注册（跑数前先把规则和及格线写死,防止事后挑好看的）、哈希/指纹（内容的防篡改校验码）、Calmar/Sortino（收益与回撤/下行风险的比值,越高越好）。
  4. **页头文案重写**：`PAGE_META` 副标题与描述改为「这页帮你回答什么问题」的人话（如实盘页:「系统现在正常吗?这周按计划执行了吗?」）。
  5. **术语对照表**：新增帮助入口（modal 或策略页小节）,三列:术语｜人话｜一句解释,覆盖第 2/3 点全部词条。
- **验收**：① 全部状态枚举经统一映射,页面无裸枚举（grep 模板断言）;② 页头/区块标题/空态文案完成人话化;③ `HelpTip` 覆盖上列指标清单;④ 后端零改动、枚举与数据值零改动（纯显示层）;⑤ 风险语言未软化（急停/停止/亏损用词保留）;⑥ Windows `npm run check/build` + 桌面/窄屏冒烟;⑦ **最终验收为 Claude 逐页 copy review**,以「非专业读者能否答出每页在说什么、要不要做什么」为准。
- **约束**：不改任何后端代码与 API;不改枚举常量本身;人话不得曲解语义（paper 不得表述为可信实盘,PASS 不得表述为收益保证）。
- **完成结果（Codex，2026-07-31）**：五个主菜单及其嵌入的研究、日报、事件日志和旧网格风险区已完成展示层文案改写；`PAGE_META` 统一改成用户问题，状态、事件、模式、研究结论、执行结果、账户连接和审计动作统一从 `labels.js` 取中文主标签，原始值只留在悬停或次级证据。新增可悬停/点按的 `HelpTip`，以及全局「术语帮助」三列表，覆盖回撤、名义金额、滑点、再平衡、资金费率、纸面前向、锁箱、预注册、哈希指纹、Calmar 和 Sortino；急停、自动停止、亏损和计划外持仓仍保持明确风险语气。未修改后端、API、枚举常量或任何交易行为。
- **验收证据（Codex，2026-07-31）**：Windows `npm.cmd run check`、生产 `npm.cmd run build`、`git diff --check` 和后端零差异检查通过；模板裸执行状态漏扫无结果。浏览器逐页确认五个主菜单问题式页头、真实空状态、研究候选中文主说明、全局三列术语表及全部必需术语，页面控制台无错误；桌面视觉检查通过。当前浏览器控制面不支持改变视口，640px 响应式规则已静态复核，但 390×844 实际视觉复验仍是最终验收前的缺失证据；Claude 逐页 copy review 也仍待执行。
- **验收结论（Claude，2026-07-31）：通过（`4b892e4`，copy review 完成）。** 逐项核查：① 页头全部改为用户问题式且贴切（「我们交易什么？」「系统现在正常吗？」「什么情况必须停？」）;② 状态映射语义准确且**风险分量未软化**——四种自动停止各有明确成因表述（「触发保护规则/发现计划外操作/数据完整性异常/上次执行未完成，已自动停止」）,「已手动急停」「出现计划外持仓（需处理）」保持分量;③ 术语表三列齐全,词条内容诚实无曲解——「纸面前向=不用真钱的模拟盘」未表述为可信实盘,「回撤」词条自带 30% 停止线说明,「预注册=防止事后只挑好看的结果」直白且正确;④ 模板 grep 无裸枚举直出;⑤ `HelpTip` 覆盖 7 个页面;⑥ **后端零文件改动**（stat 证实）,本机全量 `311 passed / 1 skipped` 无回归。**遗留（非阻断,记入待办）**：390×844 实际视觉复验待 Codex 侧有条件时补做;届时如有溢出仅属样式微调,不影响本次文案验收。

### 设计评审：系统模块重划分 MODULAR-1（Claude，2026-08-11）

**对象**：`docs/design/SYSTEM_MODULE_REDESIGN.md`（`00da87a`,PROPOSED）。**结论：评审通过;待用户确认 §17 五项产品决策后升级 ACCEPTED。**

**认可**：① §2 诊断全部属实且与本人观察一致——研究 Tab 已超载（候选+数据下载+任务历史混杂）、三类研究数据缓存无统一版本契约、`app_state.py`/`runs.py` 承担跨模块聚合、任务状态与研究 verdict 混用一个标签;② 八模块边界（数据→研究→策略→运行→执行→复盘,风险/账户横切）符合交易系统正典分解,且是用户五项生命周期导航的自然延伸;「一个事实一个所有者」「任务状态≠研究结论≠数据完整性」（§7.3）「副作用显式隔离」与项目纪律同构;③ **§12 TB4 保护边界是全文最硬的部分**——冻结项枚举完整,六条强制回归证据（对齐 PASS/逐根零误差/清单一致/账本不重建/故障隔离/不触发重启）,任一失败停止切换;④ §6.4 数据集等价报告设计诚实——DATA-1R 不得静默替换 TB4 数据源,等价须逐字段+同 runner 输出双重证明,且证明后也不自动切换;⑤ 迁移全程 expand-and-verify、禁止未校验双写、回退只切读取不删事实。

**评审意见（纳入执行约束）**：① **研究线不得停摆等待重构**——R-0 筛查按既有研究平台机制立即可跑（预注册已具备全部前置）,其结果在 MOD-3 作为 legacy experiment 只读导入,与 M0/F1/G1/G2 同等待遇;禁止把 R-0 排到 MOD-3 之后;② 每个 MOD 阶段独立立项、独立验收,§12 六条回归证据每阶段必跑;③ 生产服务器仅更新经验收版本,MOD 迁移期间生产行为零变化是各阶段硬验收项;④ 八模块的 DTO/事件/端口仪式感须与单人系统规模相称——按 §16「不引入新基础设施、不一次性搬家」执行,端口先行、机械移动殿后。

**§17 五项决策的建议**（待用户确认）：① 一级导航采用「数据/研究/策略/实盘/复盘/风控/账户」七项,概览暂缓——同意;② 「执行」首期作实盘二级页——同意,多账户并行后再升一级;③ M0/F1/G1/G2 归入历史研究档案——同意;④ 首个研究主题命名「量价关系」——同意,R-0 的突破/动量族与超跌反弹族即其首批假设;⑤ MOD-1（信息架构先行,零后端改动）为第一个实施任务——同意,附加约束:与 R-0 并行,不互相阻塞。

**用户确认（2026-08-11）：五项决策全部按建议通过,设计升级 `ACCEPTED`。** Codex 执行顺序：MOD-0（冻结基线）→ MOD-1（信息架构）,与 R-0（按既有研究平台机制预注册+筛查）并行;每个 MOD 独立验收,§12 六条 TB4 回归证据每阶段必跑。

**MOD-0 验收结论（Claude，2026-08-11）：通过（`36ae15f`）。** ① 版本化基线文件 `config/architecture/modular1_runtime_baseline.v1.json` 钉住 TB4 `spec_sha256`/`definition_hash`、账本路径与受保护设计文档哈希,锚定 source commit;② `verify_modular_baseline.py` 在当前工作区实跑 `MODULAR_BASELINE_PASS`;③ 基线校验测试只读不改 manifest（专测）;④ DATA-1R/TB4 故障隔离测试补入;⑤ `MODULAR1_BASELINE.md` 留存导航/API/依赖清单与术语表;⑥ 零生产行为改动,全量测试绿。

**MOD-1 验收结论（Claude，2026-08-11）：通过（`9999385`）。** ① 导航七项与决议逐字一致（数据/研究/策略/实盘/复盘/风控/账户）;② 纯前端改动——后端零文件触碰（stat 证实）;③ 研究页以「量价关系」为主线,M0/F1/G1/G2 归入既有档案分区;④ DATA-1R 面板迁数据页,策略页只留正式策略;⑤ 旧锚点 `strategy/research→research` 等别名齐全;⑥ 本机全量 `386 passed / 1 skipped`,`git diff --check` 通过;Windows check/build 采信留痕。§12 回归证据:基线 PASS + 后端零 diff + 测试绿,本阶段适用项全过。

**MOD-0 完成记录（Codex，2026-08-11）：本地基线通过，生产运行快照待部署主机执行。** 新增机器可读 `ORBIT_MODULAR1_RUNTIME_BASELINE_V1`，冻结 TB4 spec SHA `f74db0b9…c56ed`、definition hash `3207b10f…e6753`，并逐文件锁定 Paper/Live协议、runner、前向、执行、订单和风险关键路径；新增只读 `verify_modular_baseline.py`，可在开发机核对静态基线，也可在已初始化主机用 `--require-runtime` 验证真实 Paper manifest 与事件哈希链且不写运行状态。`MODULAR1_BASELINE.md` 已盘点重构前导航、API、代码归属和统一术语。故障隔离测试向 DATA-1R 目录注入失败并证明兄弟 `var/forward/tb4` manifest/events 字节不变。验收：机器基线 PASS；新增定向 8 项通过；后端全量 `387 passed`；TB4 对齐 `9,940` 周期/`237` 次再平衡、收益与目标权重误差均 `0.0`、`TB4_ALIGNMENT_PASS`；前端 check/build 与 `git diff --check` 通过。开发机未初始化 TB4，不冒充生产manifest/账本快照已验；该项必须在生产发布前后按基线文档执行。

**MOD-1 完成记录（Codex，2026-08-11）：七模块信息架构已落地，交易后端零改动。** 一级导航调整为「数据 / 研究 / 策略 / 实盘 / 复盘 / 风控 / 账户」；新增独立数据工作区承接 DATA-1R、数据任务历史、本地数据目录和手工拉取，研究工作区聚焦「量价关系」主题、预注册候选、实验任务和只追加结果，策略工作区只展示冻结的 TB4 正式定义与证据。旧 `#strategy/research` 地址兼容跳转到 `#research`。正式数据版本固定优先识别 `shortline-data-v1`，归档 manifest 条目与旧缓存文件/K线/Funding 数量分开表达；数据任务状态使用「任务完成/任务失败」，不再与研究 PASS/FAIL 混淆。前端状态也将数据错误与研究错误分开，可恢复 DATA-1R 携带的历史错误不会串到研究页面。验收：前端 check/build 通过；浏览器桌面与 `390×844` 窄屏实测通过，三页内容边界成立且控制台无 warning/error；后端全量 `387 passed`；机器基线 `MODULAR_BASELINE_PASS`，受保护 TB4 文件哈希全部不变；TB4 对齐 `9,940` 周期/`237` 次再平衡、收益与目标权重误差均 `0.0`、`TB4_ALIGNMENT_PASS`。本阶段未修改任何后端/API/策略定义/实盘路径；开发机仍无 `var/forward/tb4` 运行快照，生产发布前后必须执行 `--require-runtime` 门禁。

### 任务 PAGE-1：七页合理化设计（2026-08-11 用户定方向,交付 Codex;先设计稿后实施）

**流程**：Codex 产出 `docs/design/PAGE_DESIGN.md`（逐页详细设计）→ Claude 评审冻结 → 分批实施（每批独立验收）。**设计稿未经评审不得直接改页面。**

**通用设计纪律**（全部页面适用）：① 每页首屏 10 秒内回答其模块核心问题（问题定义沿用 MODULAR-1 §3 职责表）;② 每个数字有单位与来源,任务状态/数据状态/研究 verdict/策略准入四类状态永不混用同一标签;③ 只读页面零副作用控件,写动作集中、带确认、写审计;④ 文案沿用 UI-R4 人话口径;⑤ 空状态自解释（无数据/未部署/未启用时页面须说明"为什么空、下一步做什么"）;⑥ 展示层优先——发现需要新后端读模型的,单独登记不夹带。

**逐页设计纲要**（Codex 依此展开,不得偏离模块边界）：
| 页 | 首屏 | 主要区块 | 明确禁止 |
|---|---|---|---|
| 数据 | 当前数据版本卡（指纹/截止/状态/质量摘要） | 版本历史、合约覆盖（活跃/退市计数）、质量与停牌窗口、任务控制（含单飞锁状态）、实时行情健康 | 策略结论、账户信息 |
| 研究 | 主题「量价关系」+ 进行中实验 | 假设列表（预注册/运行/verdict 分列）、预注册向导、实验历史（与数据任务分开）、结论与墓地、既有档案（M0/F1/G1/G2） | 数据下载控制、策略准入动作 |
| 策略 | 正式策略目录 + 身份状态 | 按 `STRATEGY_CENTER.md`:冻结定义/证据/已知风险 + 准入状态时间线 | 调参、启停、下单 |
| 实盘 | 系统健康条 | 实例分列（TB4 paper / LIVE-SMALL live 两本账）、当前信号与目标、冻结清单、启用向导、最新执行报告;执行详情（计划/订单/成交/对账）为二级页 | 修改参数;解释研究历史 |
| 复盘 | 累计偏差与最新一轮结论 | 权益对照、逐轮执行报告、成本/滑点归因、协议检查点（3 个月加仓评估）、TB4 原始/3 倍/实际三层对比 | 修改任何状态 |
| 风控 | 回撤水位 vs 30% 停机线 | 停止条件清单、护栏状态（PROTOCOL_STOP/VIOLATION/未完成轮次）、急停、审计日志、恢复流程说明 | 修改策略定义 |
| 账户 | 账户列表与连接健康 | 用户/账户/凭证（不回显明文）、同步、账户↔策略实例绑定视图 | 策略内容、交易动作 |

**约束**：与 MOD-2、R-0 并行互不阻塞;TB4 运行路径零触碰;实施批次建议:批 A（数据+研究,当前最粗糙）→ 批 B（实盘+复盘+风控）→ 批 C（策略+账户,现状较好仅微调）。
- **设计稿评审（Claude，2026-08-11）：通过并冻结（`c07c890`,`PAGE_DESIGN.md` 升 ACCEPTED）。** 亮点：① 六维状态语言表（任务/数据/研究/准入/运行/执行）比规格的四类更完整,逐维给出允许值、人话主标签和禁止混用规则;② 17 项读模型缺口诚实登记并映射到 MOD-2~5 归属,明确「缺口未接入前显式占位,禁止前端拼接多事实源制造完整假象」;③ 单位口径表把「归档分区≠K 线根数≠Funding 条数」焊死;④ TB4 保护清单含 `verify_modular_baseline.py` 必过。§14 六项决策全部按稿确认。**授权批 A 实施**;批 B/C 依序,每批验收必跑基线校验。

**PAGE-1 设计稿完成（Codex，2026-08-11）：已提交 Claude 评审，尚未授权页面实施。** 新增 `docs/design/PAGE_DESIGN.md`，逐页冻结候选设计覆盖：首屏核心问题、区块顺序、字段/单位/来源、六类状态语义、权限与写操作、空/错/无权状态、390×844 响应式行为、跨页深链和明确禁止项。数据页以正式数据版本为首要事实，研究页以「量价关系」和实验为主线，策略页严格区分 `AdmissionDecision` 与运行/协议停机，实盘页分列 TB4 Paper 与 LIVE-SMALL Live，复盘页目标为原始/3x理论/实际三层，风控页首屏锚定 30% 停机线，账户页以连接健康与实例绑定优先。另登记 17 项 `READ-MODEL GAP`，全部分配到 MOD-2/MOD-3/MOD-4/MOD-5/ARCH-1，明确不得由页面拼算或假数据补齐；实施仍按批 A→B→C 且每批独立验收。本提交只改设计与进度文档，未修改前端、后端、API、TB4 或运行账本。

**人话化修正验收（Claude，2026-08-11,`246b1b7` + 本人一处修正）：通过。** 按新验收标准执行:黑名单全模板扫描,可见文字仅剩一处违规（研究页小字「研究 verdict」,本人已直接改为「研究结论」）,其余命中均为代码字段或悬停次级层,合规;数据页主文案已达人话标准（「数据更新到什么时候」「数据有没有缺失」）,技术细节降级到「技术详情（供开发与排障使用）」折叠区。**但用户判定数据/研究页仍不达预期,诊断为「诚实空壳」问题**——页面结构与文案合格,但核心问题因读模型缺口显示「暂时无法」、研究主流程因 R-0 未交付而全空,且空状态泄漏内部任务编号（R-01/R-02）。处置:立项 DATA-2（摘要读模型提前+清除内部编号）,催办 R-0。

**批 A 验收结论（Claude，2026-08-11）：通过（`a7e2160`）。** 核查：① 纯前端实证——提交仅触碰 `ResearchPage.vue`/`app.css`/进度文件,后端零文件;② 本机 `MODULAR_BASELINE_PASS`、全量 `386 passed / 1 skipped`、`git diff --check` 通过,Codex 侧另附 TB4 对齐 9,940 周期/237 再平衡零误差复跑;③ 设计红线落实抽查——「载入完成前不显示 0 值」明示、四处读模型缺口「尚未接入」显式占位（含「不允许在此切换数据源」的边界声明）、单位分列（归档分区独立计数）;④ 数据任务不再出现在研究页,旧候选下沉档案。**观察（非阻断）**：数据页/研究页目前经 `isDataMode` 共用一个组件文件,展示层可接受;按前端模块化目标,MOD-6 拆 store 时应顺势拆为独立模块文件,记入后续。

**PAGE-1 批 A 完成记录（Codex，2026-08-11）：数据页与研究页已按冻结设计实施，待读 Claude 验收。** 数据页首屏改为正式 `shortline-data-v1` 版本卡，内容指纹、15m→1h/4h 规则、D-01 截止与 D-02 质量缺口分列；归档分区、兼容缓存、K线/序列与 Funding 均带独立单位，不再混加。DATA-1R 活动/终态、单飞锁与历史任务分区展示，终态不再显示残留进度或把旧 lock holder 误称当前锁；版本历史、合约覆盖、质量/停牌、实时公共行情四项缺口明确占位，不做浏览器拼算。研究页以量价关系主题、当前假设与当前实验为首屏，预注册/任务/verdict 分列；R-01/R-02 未接入时诚实空置且不拿旧协议冒充 R-0，M0/F1/G1/G2 下沉历史档案，兼容创建工具明确不是量价预注册入口。两页首次载入不再用 0 伪装“尚未读取”，数据任务完全不出现在研究页。验收：前端 check/build 通过；桌面与 390×844 浏览器实测通过，历史兼容工具可达、页面控制台无 warning/error；后端全量 `387 passed`；`MODULAR_BASELINE_PASS`；TB4 对齐 `9,940` 周期/`237` 次再平衡，收益与目标权重误差均 `0.0`。仅修改前端展示与本进度记录，后端/API/TB4/运行账本零触碰；D/R 读模型缺口仍归后续 MOD-2/MOD-3，不夹带实现。

**PAGE-1 批 A 易用性修正（Codex，2026-08-11）：数据页改为研究者语言。** 根据实际页面反馈，首屏移除归档分区、缓存文件数、内容指纹以及 DATA-1R/D-xx/MOD-x 等研发编号，改为“历史合约、价格数据、资金费率、最近更新、覆盖日期、缺失情况”等用户可直接判断的含义；存储条目、分片和校验码仅保留在默认收起的“技术详情（供开发与排障使用）”。全市场任务统一称“更新历史数据”，原始 WinError/锁错误转换为可执行的人话提示，历史任务不再显示内部 run ID；旧缓存区改称“旧研究数据（用于复现以前的报告）”并默认折叠。浏览器桌面与 `390×844` 实测通过，修正并复核最近更新时间，不存在 `Invalid Date`；前端 check/build、后端全量 `387 passed`、`MODULAR_BASELINE_PASS`、TB4 对齐 `9,940` 周期/`237` 次再平衡且两项最大误差 `0.0`、`git diff --check` 均通过。仅修改展示层与本进度记录，后端/API/TB4/运行账本零触碰。

**数据页重复进入性能修正（Codex，2026-08-11）：缓存立即展示并按数据边界加载。** 数据页不再复用会额外读取候选、模板、候选明细和研究结果的整套研究目录加载器，只并行读取数据目录与数据更新记录；首次加载后保留内存投影，再次进入立即显示上次结果并在后台刷新，手动“刷新数据”仍强制给出读取状态，登出时清空缓存避免跨会话复用。后端数据目录按顶层 JSON 和正式 manifest 的相对路径、文件大小、纳秒修改时间建立线程安全元数据缓存；源文件未变化时不再重复解析约 61 MB JSON/manifest 和计算校验码，任何文件新增或修改都会自动失效并重扫。实测同一进程目录冷读约 `382.9 ms`、热读约 `2.6 ms`（约 `146.6x`）；真实浏览器验证首次加载后离开再返回可立即看到“全市场历史数据”，不再出现阻塞加载页。新增缓存复用、返回值隔离和文件变化失效测试；前端 check/build、后端全量 `388 passed`、`MODULAR_BASELINE_PASS`、TB4 `9,940` 周期/`237` 次再平衡零误差、`git diff --check` 全部通过。未修改 TB4/Live 路径与运行账本。

## 短线平台推进（2026-08-10 起，用户拍板）

**背景**：LIVE-SMALL V1（TB4×3 自动实盘）已在生产运行。用户决定启动下一阶段：研究新的短线策略、升级多账户多策略架构。按架构评审（2026-08-10）的前置条件,推进分两轨,**任何工作不得触碰生产运行路径**：

- **轨道 A（研究,证据线）**：DATA-1R 数据集 → R-0 策略族筛查。R-0 是阶段 2+ 昂贵平台建设（WebSocket 行情事件仓/动态币池/分钟级 replay）的解锁条件——任一族 PASS 才建,两族 FAIL 则短线平台冻结、架构文档留作蓝图。
- **轨道 B（平台,与策略无关的部分）**：ARCH-1 控制面与数据模型（架构文档阶段 1）。多账户多策略的控制面对任何策略家族都需要（TB4 本身将来也要多账户运行）,不依赖 R-0 结论,可与轨道 A 并行。
- **生产纪律**：生产服务器只拉取经验收的版本;所有新表/新代码必须对现有 LIVE-SMALL 运行零行为改变（现有测试全绿 + 生产路径零 diff 验证）。

### 任务 DATA-UI-1：数据集同步的界面化后台任务（轨道 A 配套,优先级：中,交付 Codex）

**背景（2026-08-10,用户提出）**：DATA-1R 的 index/sync/build/verify 目前是 CLI 手工执行。数据同步应成为界面上的后台任务：点击开启、实时看进度、不影响其他操作。长期高频场景是**每月归档新增分区后的增量同步**。复用研究平台 UI-P2 的 job 模式。

- **改动**：
  1. **后端 job 服务**：把 index→sync→build→verify-native 包装为可管理的分阶段后台任务;进度结构化（当前阶段/已下载分区数与总数/字节数/当前 symbol/错误计数）,job 状态持久化（服务重启后页面仍能看到历史与断点）,失败可从断点重跑。
  2. **单飞锁**：同一数据集根目录同一时刻至多一个 sync job（防并发写坏分区文件——CLI 与 UI 任务共享同一把锁）;锁持有者与启动时间可见。
  3. **前端**：研究 Tab 数据目录区新增数据集卡片——状态、进度条、阶段标签、最近日志尾部、启动按钮（全量下载弹确认对话框,等价 `--confirm-full-download`）、优雅取消（可续传,不留半成品）。轮询复用现有 job 轮询机制,不阻塞其他页面。
  4. **护栏**：管理员限定;启动前检查磁盘剩余空间（低于阈值拒绝并提示）;build 完成后 manifest 指纹在界面展示并自动登记研究数据目录;**不触碰生产交易路径,生产服务器可通过配置禁用该功能**。
- **验收**：① 单飞锁有测试（并发第二个 job 被拒,CLI 运行时 UI 启动同样被拒）;② 进度持久化——重启后状态与断点正确恢复;③ 取消后重启动从断点续传、数据完整性不受影响（checksum 仍全过）;④ 全量确认对话框、磁盘检查、管理员/匿名权限有测试;⑤ 指纹展示与目录登记与 CLI 产物一致;⑥ 现有测试全绿,生产路径零改动;⑦ Windows `npm check/build`。
- **约束**：复用 DATA-1R 既有实现（job 只做编排,不复制下载/聚合逻辑）;不改变数据集格式与指纹语义;当前正在跑的 CLI 下载不受影响。
- **验收结论（Claude，2026-08-10）：通过（`6cbbd04`）,附一项遗留。** 核查：① 单一活动任务守卫覆盖全部研究任务（`_active_run_id`,含 UI/CLI 互斥语义）,job 可确认/渐进/可取消有专测;② 中断的 run 在服务重启后正确判 FAILED（`test_interrupted_run_is_failed_on_service_restart`）;③ 全量下载须显式 `confirm_full_download`,全部接口 `require_admin`;④ **三项数据正确性修复尤为关键**：build 改为按 symbol 流式处理（正好解决本机构建两次被内存问题打断的现场缺陷）、索引外本地分区阻断 COMPLETE、分区内部缺口/重复阻断 COMPLETE,后两项各有专测;⑤ 本机全量 `368 passed / 1 skipped`（+3）,`git diff --check` 通过。**遗留（非阻断）**：规格要求的「启动前磁盘余量检查」未实现,记入待办,下轮补。验收同时已将本地构建切换到新版流式代码重跑。
- **验收补齐（Codex，2026-08-10）：通过（代码与小样本/故障注入级；全量下载仍待用户从页面启动）。** ① 页面与 CLI 已共用数据集根目录跨进程锁，真实启动 CLI 子进程验证 UI 持锁时被拒；锁元数据公开 owner/run/PID/开始时间，父进程退出而工作进程仍存活时不会误开第二任务。② 后台固定执行 `index → checksum sync → build → verify-batch`，原生抽样复用既有 `verify-native`，进度持久化文件/字节、symbol、错误数与日志尾部；服务重启把活动任务投影为 `interrupted/resumable` 并保留原进度。③ 故障注入在第 7 字节中断真实 downloader，确认 `.part` 保留、重启发出 `Range: bytes=7-`、最终官方 SHA-256 一致且原子替换后无 `.part`。④ 页面任务启动前磁盘阈值、运行配置禁用开关、双重全量确认、管理员 401/403、指纹目录登记均有测试或页面实测。⑤ DATA-1R 构建仍按 symbol 流式处理，索引外分区及内部缺口/重复阻断 COMPLETE；锁文件与令牌明确排除于 manifest。⑥ 后端全量 376 项、Windows 前端 check/build、`git diff --check` 通过；`live_execution.py`、`trend_forward.py` 等生产交易执行/前向路径相对 DATA-UI-1 基线零差异，`bootstrap.py` 仅新增研究任务配置注入。浏览器新会话控制台零错误。未启动 8–12 GB 全量下载。

### 任务 DATA-1R-FIX1：交易所停牌窗口登记机制 + 磁盘余量检查（优先级：高,阻塞全量构建,交付 Codex）

**背景（Claude 现场排查,2026-08-10）**：全量构建被完整性门拦下——40,137 分区中 12 个 15m 分区内部有连续缺口（全部为 missing、零 duplicate）。逐一扫描定性:缺口为 30–288 根（7.5–72 小时）的整段连续窗口,文件均通过官方 `.CHECKSUM`,分布特征与交易所**真实停牌**一致（BNX 2022 三次对应其代币迁移停牌;AERGO/CTK/CVC/SLP/PUMP/CVX 集中在 2025 年下架潮前后;LIT/MAVIA/AIA 类同）。**结论:缺口是官方归档源头就有的事实,不是下载损坏。**「任一分区有内部缺口即拒绝 COMPLETE」的门对现实过严——按此语义全市场历史数据集永远无法 COMPLETE。

- **12 个坏分区清单（缺口根数）**：AERGO 2025-04(44)、AIA 2026-01(45)、BNX 2022-04(96)/2022-06(96)/2022-08(288)、CTK 2025-04(41)、CVC 2025-05(34)、CVX 2025-07(46)、LIT 2025-12(70)、MAVIA 2025-03(68)、PUMP 2025-07(30)、SLP 2025-07(47)。精确窗口毫秒级明细见扫描产物(交付时由工具重新生成,不抄本清单)。
- **改动**：
  1. **停牌窗口登记表（halt registry）**：新增版本化、随仓库提交的登记文件——逐条记录 `symbol + 缺口起止(open_time_ms) + 根数 + 定性说明与依据`（能找到币安公告的注公告,找不到的注「官方 checksum 归档源头缺失,特征与停牌一致」）。build 检测到的分区内缺口若与登记条目**精确匹配**（symbol+窗口逐毫秒相等）则不阻断 COMPLETE;存在登记外缺口仍然 FAIL。登记条目不得宽于实际缺口（防止拿宽窗口作免检通行证,须有测试）。
  2. **缺口进入质量事实链**：登记内缺口写入 manifest 与质量报告（数据集级 `verified_halt_windows`）;对应时段的 1h/4h 聚合根维持既有 `INCOMPLETE` 语义不变;流动性/覆盖率指标如实计入缺失。
  3. **初始登记表**：把上述 12 个窗口按工具重扫的精确毫秒边界录入,逐条附定性依据。
  4. **补 DATA-UI-1 遗留**：sync/build 启动前磁盘余量检查（低于可配置阈值拒绝并提示,UI 与 CLI 共用）。
- **验收**：① 登记外缺口 FAIL、登记内精确匹配则 COMPLETE 且 manifest 含 `verified_halt_windows`（各有测试）;② 登记条目宽于实际缺口被拒绝（测试）;③ 12 窗口录入后全量 build 产出 COMPLETE 数据集与最终指纹;④ `verify-native` 抽样通过;⑤ 磁盘检查 UI/CLI 双路径测试;⑥ 全量测试绿,`git diff --check` 通过。
- **约束**：不放松聚合 INCOMPLETE 语义;登记表修改属数据治理动作,须随普通提交评审,不提供运行时旁路。
- **进度澄清（Claude，2026-08-10）**：`6f3c8ad` 已交付本任务第 4 项（磁盘检查）及任务安全加固,**第 1–3 项（停牌窗口登记表）尚未实现**——本机 grep 证实构建代码无 halt registry 引用,12 个停牌缺口仍会阻断全量 COMPLETE 构建。**FIX1 核心仍待交付,是当前数据线的唯一阻塞项。**
- **验收结论（Claude，2026-08-10,对 `6f3c8ad` 任务安全加固部分）：通过。** ① 跨进程数据集锁为真实进程级验证——UI 持锁时**真实启动 CLI 子进程**被拒（`test_real_cli_is_rejected_while_ui_holds_dataset_lock`）,锁元数据公开持有者/PID/起始时间,父进程退出而工作进程存活不误开;② 磁盘阈值+运行时禁用开关在 job 创建前拦截（DATA-UI-1 遗留项就此闭合）;③ 断点续传做了真实故障注入——第 7 字节切断下载,`.part` 保留、重启发 `Range: bytes=7-`、终态官方 SHA-256 一致、原子替换后无残留;④ 中断任务重启后投影为 `interrupted/resumable` 且保留进度;⑤ 生产路径相对基线零差异;⑥ 本机全量 `375 passed / 1 skipped`,`git diff --check` 通过,Windows 侧 check/build 采信留痕。
- **第 1–3 项完成记录（Codex，2026-08-10）**：已提交版本化 `ORBIT_DATA1R_HALT_REGISTRY_V1` 登记表，按官方 `.CHECKSUM` 重新下载/校验 12 个原始 ZIP 后重扫并录入精确 `symbol + month + start/end open_time_ms + count + archive SHA-256 + 依据`，合计 12 个窗口、905 根 15m。构建器只在窗口三元组与原始 ZIP SHA-256 同时精确匹配时解除 COMPLETE 阻断；登记外缺口继续失败，宽于实际缺口的登记即使 `--allow-partial` 也拒绝。质量报告、分区质量、`metadata/verified_halt_registry.json` 与 manifest 均携带 `verified_halt_windows` 和登记表哈希，原始 `missing_count/coverage_ratio` 不抹除。聚合器补齐首末观测之间的全空 1h/4h 桶，确保整段停牌也显式产出不可交易的 `INCOMPLETE`，不再静默缺行。真实 12 分区复验：12/12 窗口命中、905/905 缺失归档、登记外缺失 0，24 个窗口×周期检查点全部 `INCOMPLETE`；重复构建的质量哈希与数据集指纹一致。针对性 20 项、后端全量 380 项及 `git diff --check` 通过。当前工作区没有已下载的 40,137 个全量分区，因此本记录只宣告第 1–3 项代码与真实 12 分区证据完成，不冒充验收项③的全量 COMPLETE 构建；第 4 项磁盘检查不在本轮范围。

**DATA-1R-FIX1 验收结论 + 数据集正式交付（Claude，2026-08-10）：通过,数据线贯通。** ① 停牌登记表（`config/research/data1r_halt_registry.v1.json`,`214cbc2`）12 条与现场扫描逐毫秒吻合,且每条锚定归档文件 SHA（比规格更严）;精确匹配放行/宽窗口拒绝/登记外 FAIL/初始表校验四类测试齐全,`379 passed`。② **全量构建 COMPLETE**：829/829 合约,**数据集指纹 `dcb60c95ecd796e9ade32fcc8bf600a958ba7e88c47a2fdbd7d55569b56ca546`**,质量报告 SHA `f5885005…6638710f`。③ `verify-native` 六组多样化抽样（BTC 2021-06/ETH 2024-11/LUNA 2022-04/BNX 停牌月 2022-08/SOL 2023-03/DOGE 2025-12,共 2,670 根 1h/4h）全部零差异通过。**R-0 预注册自此可冻结,须引用上述数据集指纹。**

### R-0 训练结果判读（Claude，2026-08-13，报告 `docs/evidence/r0/r0_training_v2_20260812.json`）

**总判定 `TRAINING_FAIL`，两族均未过门，锁箱未开（`lockbox_authorized_families: []`）。按协议 §11 → `R0_FAIL`：全自动短线平台建设冻结。** 契约 SHA `a9a7abd4…`、数据指纹 `dcb60c95…` 与冻结值一致。

**逐族判读**：
- **突破/动量族：干净地死了,无抢救价值。** 8 个组合全部为负（−0.353% ~ −0.403%/笔）,事件数 13 万–30 万,**bootstrap 置信上界也全为负**——即最乐观情形仍亏损。样本充分,结论确定。
- **超跌反弹族：有真实信号,死在稳定性。** 最佳组合（4h 内跌 ≥10%、持有 4h）成本后 **+0.626%/笔、7,051 事件**,三个流动性层全正（高 0.58 / 中 0.79 / 低 0.50,非单层支撑）。**仅两道门未过**:`bootstrap_lower_bound`（下界 −0.218,统计上不能排除运气）与 `leave_one_year_out`（**2022 年 −0.97%** 单年翻负）。存在清晰梯度:**跌幅门槛越极端越值钱**（跌 10% 为正,放宽到 5% 转负）。
- **两项预注册诊断的答案**：① **「3 日量递增更好」被证伪且方向相反**——量不递增 **+0.844%** vs 量递增 **+0.049%**（合理解释:暴跌中放量递增=恐慌仍在加速;量走平=抛压衰竭,才易反弹）;② **上市年龄无差别**（≤30 天 +0.646% vs >30 天 +0.624%）,新币既非毒也非蜜。

**关键资产（须保护）**：**锁箱期 2025-01-01 → 2026-07-31 从未打开**,对这两族而言仍是处女数据。下一版假设可用「训练期设计 + 该锁箱验证」的正确结构;任何人不得以任何理由提前触碰。

**失败模式的战略含义**：超跌族的失败不是「没有信号」,而是「**行情依赖**」——牛/震荡年为正、单边熊年为负。行情依赖对**全自动**是致命的（机器不会避开 2022 那种环境）,但恰是**大环境过滤器**与**人工低频择时**能改善的维度,与用户的半自动路线方向一致。

**后续三选（用户决策）**：A 接受 R0_FAIL,短线方向关闭;B **新预注册**「极端超跌 + 大环境过滤」假设,以仍封存的锁箱验证（禁止在旧协议上改参重跑）;C 先实现 R0-DIAG（最大浮盈/浮亏路径测量）回答半自动路线价值,再定 B。**Claude 建议 C→B**：先用路径数据看清「人接手能否改善盈亏比」,再据此设计新假设。

### 任务 DATA-2：数据页摘要读模型（提前自 MOD-2,优先级：高,交付 Codex）

**背景（2026-08-11,用户反馈数据/研究页"不是想要的"）**：批 A 后数据页核心问题两项显示「暂时无法确认/汇总」——摘要读模型被排在 MOD-2,但底层事实（质量报告、manifest、合约元数据）已全部存在,缺的只是轻量只读接口。提前交付,让数据页立即能回答自己的核心问题。

- **改动**：① 新增只读接口（归 `/api/research/datasets` 扩展或独立 `/api/data/summary`,管理员限定）:数据截止时间（全合约共同覆盖末端,即 D-01）、质量摘要（缺失/重复/停牌窗口计数与明细分页,即 D-02）、合约覆盖聚合（活跃/退市计数,D-04 摘要部分）——全部从既有质量报告与 manifest 读取,服务端聚合,禁止新算事实;② 数据页接入,替换「暂时无法」占位;③ **全前端清除内部任务编号**——空状态与提示文案不得出现 R-01/R-02/MOD-x/D-xx 等内部编号,改用用户语言（如「预注册功能尚未开放」）。
- **验收**：① 数据页首屏四问全部有真实答案;② 接口纯只读、数值与质量报告文件逐项一致（对照测试）;③ 前端 grep 无内部任务编号残留;④ 人话黑名单扫描清零;⑤ 全量测试绿+基线 PASS。
- **约束**：MOD-2 后续仍按原设计建正式数据目录服务,本接口届时并入,不算重复建设;TB4 零触碰。
- **验收结论（Claude，2026-08-11）：通过（`dd41714` + `1df5147`）。** ① 数据页首屏四问全部有真实答案（合约覆盖含活跃/退市分列、共同截止时点、缺失/停牌/重复摘要）;② 后端四测扎实——摘要**只投影冻结质量报告不重算**（对照测试）、停牌明细分页且与缺口精确对应、缓存隔离并在报告变更时失效、**质量报告指纹失配即拒绝**（fail-closed 延续到读模型层）;③ 前端内部任务编号零残留（grep 实证）;④ 人话黑名单模板扫描仅剩策略页一处「规则指纹」——带 HelpTip 的小字次级形态,合规;⑤ 本机全量 `393 passed / 1 skipped`（+7）、`MODULAR_BASELINE_PASS`、`git diff --check` 通过。数据页「诚实空壳」问题就此闭合;研究页的内容供给仍待 R-0（已催办）。

**完成记录（Codex，2026-08-11）：DATA-2 已实现，待 Claude 复核。** 新增管理员只读 `/api/data/summary` 与 `/api/data/quality`，直接投影正式 manifest、质量报告和合约元数据，并按文件签名缓存；质量明细支持交易暂停、缺失与重复三类服务端分页，不扫描 K 线、不重算冻结事实。正式数据实测返回：截止 `1785542399999`、829 个历史合约（800 在交易、29 已退市）、20,528 个分片、未解释缺失 0、重复 0、已核实交易暂停 12 段/905 根 15m、资金费率覆盖 829/829，均与冻结报告逐项一致。数据页四问已替换占位，新增可分页质量检查区；研发任务编号已从前端可见文字清除，合约覆盖、时间截止和质量结论均改为用户语言。同步完成数据页加载优化：目录元数据使用签名缓存，二次进入先显示已有结果并后台刷新；实测目录服务冷读约 382.9 ms、热读约 2.6 ms。新增服务/API/缓存回归测试；前端 check/build 通过，后端全量 `394 tests OK`，`MODULAR_BASELINE_PASS`，TB4 对齐 `9,940` 周期/`237` 次再平衡且收益与目标权重最大误差均为 `0.0`。未修改 `TB4_SPEC`、TB4 runner、LIVE 执行与账本。

**R-0 预注册评审（Claude，2026-08-11）：内容通过,数据锚定阻断,整体打回待修（`e636d1d` 不冻结）。**
- **认可的部分（修复后原样保留）**：两族机械定义干净且无未来泄漏（通道/相对成交额均不含当前根,次根开盘入场,ATR 止损跳空取劣价）;超跌族仅做多以保留 LUNA 类事件的真实伤害;8+8 冻结小网格与全确定性选参顺序（无事后挑选自由度）;分层保守成本诚实注明「无盘口数据,不伪装测出真实滑点」;**按 UTC 日成组的 block bootstrap + 删层/删年稳健性门**比 C8 更严,正面落实「不得靠单层单年撑起」;训练/锁箱切分与一次性开箱纪律完整;§12 审计边界把实现测试义务写死。协议通俗解释到位,符合人话标准。
- **阻断缺陷**：三指纹并存——`dcb60c95`（build_state 构建记录）/`174d551c`（正式数据机 manifest 现值,本人实测）/`5c2404f9`（R-0 契约所钉）。根因:`verify-native` 把校验记录写入 manifest 并改变数据集指纹,**「验证数据」这一动作改变了「数据身份」**,不同机器跑不同校验后同一份数据出现多个身份;契约锚定的状态在正式数据机上不存在,fail-closed 将阻止运行。
- **修复任务 R0-FIX（交付 Codex,阻塞 R-0 冻结）**：① **数据身份与校验证词分离**——数据集内容指纹只由数据分区哈希+质量报告+停牌登记决定,一经 COMPLETE 即稳定不变;`verify-native` 结果改存独立的只追加证词记录（attestation,引用内容指纹,不反向改写身份）;② manifest 迁移一次,恢复稳定内容指纹并与 `build_state` 一致,迁移前后数据分区零改动（哈希对照测试）;③ R-0 机器契约与文档重钉稳定内容指纹,契约 SHA 更新;④ 测试:重复校验/多机校验不改变内容指纹、证词只追加、契约指纹与正式数据机实测一致。
- **纪律说明**：本次打回发生在任何估计器实现与数据接触之前（提交自身声明「不实现估计器、不扫描 K 线」）,预注册完整性未受损;修复后重新提交冻结。

**R0-FIX 验收结论（Claude，2026-08-11）：通过（`2563460`）,R-0 预注册正式冻结。** ① 身份与证词分离实测闭环——本人执行 `migrate-manifest`:指纹自漂移值恢复为稳定内容指纹 `dcb60c95…ca546`（与 build_state 一致）,101,721 个分区 `partitions_unchanged=true`,六条既有校验作为独立证词导入;随后**连续两次重复 verify-native,指纹保持不变**（活体验证）;② 迁移保分区哈希有专测;③ 契约重钉稳定指纹,契约 SHA `1e657485…` 与文档声明一致;④ 「契约与正式数据机一致」测试在迁移后通过,全量 `400 passed / 1 skipped`。**正式数据集指纹自始至终为 `dcb60c95…ca546`,预注册锚定就绪。R-0 协议（`R0_SHORTLINE_SCREEN.md` + 机器契约 v1）自此冻结,授权按 §12 实现估计器与测试;训练跑数前须再次核验契约与数据指纹。**

**估计器验收结论（Claude，2026-08-12）：通过（`965acbe`）,训练期评估已启动。** 19 项测试与协议 §12 义务逐条对应且超出三条:训练选择防篡改（`test_tampered_training_selection_is_rejected`）、锁箱标记仅可创建一次、网格必须恰好展开 8+8;「训练失败不得读锁箱」验证到**连数据加载器都不被调用**的强度;指纹失配在任何数据读取前 fail-closed。本机全量 `419 passed / 1 skipped`、`MODULAR_BASELINE_PASS`、`git diff --check` 通过。**训练期评估已由 Claude 在正式数据机启动**（`screen_r0_shortline.py train`,脱离会话运行）;结果出来后 Claude 审训练报告,再决定是否开锁箱。

**R-0 V2 修订（2026-08-12,用户拍板,交付 Codex）**：用户判定流动性门槛 500 万 USDT 过低,**提高到日成交额中位数 ≥ 3,000 万 USDT**。**纪律说明**：v1 训练虽已启动,但在任何人接触任何结果之前由 Claude 中止、半成品报告与日志未读即销毁——属证据接触前的修订,以新版本形式合规执行;v1 契约作废。
- **V2 要求**：① 流动性下限改 3,000 万,其余机械定义/成本/切分/统计方法不动;② **取消固定 top-120 名额（2026-08-12 用户质询后 Claude 定稿）**——120 是 v1 低门槛时代的实用补丁,3,000 万门槛本身即经济筛子,排名截断徒增任意性与边界抖动;V2 币池 = 全部满足门槛的合约,分层改为「合格集按成交额排名动态三等分」,层最小规模不足时的处理规则写死进契约;②b **流动性回看窗口 7 天改 3 天**（2026-08-12 用户拍板）——判定用信号前最近 **3 个完整 UTC 日**的日成交额**中位数**（即 3 天中至少 2 天达标,单日假量仍难通过）,换取热点币更快入池,契合短线定位;上市满 30 天资格线保留;已知代价（防刷量能力下降、入池早期成本失真风险上升）由用户知情接受,记录在案;②c **「3 日成交量递增」定为预注册诊断维度而非币池硬过滤**（2026-08-12 用户提出、Claude 定位）——递增属预测意图（信号域）而非可交易性（币池域）,硬过滤将砍掉 ~5/6 的可入池天数且会误伤"量大但走平"的头部币;V2 契约须预注册该诊断:全部事件按「信号前 3 完整日成交额是否严格递增」二分切片输出对比统计,跑数前声明、不参与选参与判定;若诊断显示递增组显著更优,升格为下一版协议的正式条件;②d **取消上市满 30 天资格线**（2026-08-12 用户拍板,Claude 认同——30 与 120 同属无锚数字,其担忧已由 3,000 万门槛承担大半）——新币入池由指标物理下限自然约束（币池需 3 个完整日+量能基线需 96 根,实际最早约上市第 4 天）;同时预注册**上市年龄诊断切片**（事件按信号时上市 ≤30 天 / >30 天二分对比,跑数前声明,不参与选参与判定）,新上市阶段是毒是蜜由数据裁决;③ **样本门诚实重推**——训练/锁箱的最少事件数、合约数、年份覆盖须按新币池的容量重新推导并冻结（跑数前定,不看结果调）;若新门槛下样本天然不足,如实预注册更低的样本门并接受统计效力下降的说明,不得为凑样本回调流动性门槛;④ 文档+机器契约升 v2、SHA 更新,重新提交 Claude 评审冻结后才可重启训练。

**R-0 V2 重实现记录（Codex，2026-08-12）：已完成，待 Claude 复审冻结；未重启训练。** V1 训练进程已终止，确认无训练报告、无锁箱 marker。新增机器契约 `r0_shortline_screen.v2.json`（SHA-256 `a9a7abd45a69fd96e492549de2617a8ce472dce7cf56a80653060ed2f78a9799`）：3 个连续完整 UTC 日、日成交额中位数 ≥3,000 万、全部合格合约、取消 30 天上市门槛；合格集按稳定成交额排名动态三等分，余数依次给高/中层，少于 3 个合约则整个时点不产生事件。估计器逐事件增加「3 日量严格递增/非递增」与「上市 ≤30 天/>30 天」两项诊断汇总，并 fail-closed 要求 V2 诊断解析器存在；诊断不进入币池、候选排序或 PASS/FAIL 门。纯流动性容量审计（零 15m 信号/收益读取）显示：训练期 1,824/1,827 个日快照可分层、387 个曾合格合约、日合格数中位 80；锁箱期 577/577 个日快照可分层、661 个曾合格合约、日合格数中位 100，因此原训练/锁箱样本门原样保留，不为通过而放宽。正式数据上下文只读核验通过（内容指纹 `dcb60c95…ca546`）。后续语义审计再收紧两处 fail-closed：每个已产生事件必须同时带有两项合法诊断值，动态分层必须精确匹配 V2 方法/余数/不足处理且强制无 Top-N、3 日窗口；聚焦 28 tests、后端全量 `423 tests OK`、`MODULAR_BASELINE_PASS`、`git diff --check` 通过。V2 未经 Claude 再冻结前禁止运行训练，锁箱继续未打开；TB4/LIVE/运行账本零修改。

**V2 契约评审（Claude，2026-08-12）：通过并冻结（`5a38d8e`）,训练已重启。** 核验：① 币池五项修订全部落实（3 日中位数 ≥3,000 万/无名额/无上市线/动态三等分/平票按 symbol 字母序）;② **容量审计洁净**——`audit_r0_v2_universe.py` 明确 `signal_or_return_data_read: False`,只数每日合格合约容量（训练期日中位 80、锁箱期 100,容量充足）,未触碰任何信号或收益;据此**样本门维持 V1 数值不放宽**并明示「自然达不到事件门必须如实失败」;③ 两个诊断切片（3 日量递增/上市年龄）预注册且 `selection_or_gate_effect: NONE`;④ 契约 SHA `a9a7abd4…` 与文档一致,数据指纹锚定稳定的 `dcb60c95…`;⑤ 全量 `421 passed / 1 skipped`。**V2 训练评估已由 Claude 在正式数据机启动（冻结即解除「禁止训练」）,首份可阅读的结果将是 V2 训练报告。**

**信息架构再修正（2026-08-13,用户定调,推翻此前七页与五入口两版）**：页面不按后端模块切,按**「两条业务线 + 三样共用」**切——
```
共用   数据 ｜ 策略与研究（策略库=已冻结策略/形态,研究=假设与实验）
业务线 量化：运行 / 复盘（跑得对不对、收益多少）
       信号：信号台 / 复盘（信号图形、我做了的、我没做的）
       账户与设置
```
**关键修正**：①**复盘不是一个页面**——两条线的复盘要回答的问题根本不同（量化=执行忠实度+收益构成;信号=逐信号回到图上看做/没做的结果）,此前把二者塞进同一页是别扭的根源;②**图是信号线的主体**——信号台与信号复盘必须以价格图为中心（进场/止损/持有区间/实际离场逐一标注）,此前全套设计无一张图,是「不像交易软件」的根因;③模块边界≠页面边界,MODULAR-1 后端划分不变。样稿见 `docs/design/PAGE2_MOCKUP.html`（含量化复盘、信号台带图、信号复盘做了/没做/计划外三段）。`LAYOUT_DESIGN.md` 须按此重修后再实施。

### 任务 PAGE-3：按冻结样稿实施页面（2026-08-13 用户下令实施,交付 Codex）

**视觉与结构准绳**：`docs/design/PAGE2_MOCKUP.html`（可运行样稿,ACCEPTED）。样稿的骨架、信息密度、图形语言、文案口径即验收标准;`LAYOUT_DESIGN.md` 的**结构部分已被样稿取代**（七页→两条业务线）,其余布局纪律（三段式、信息预算、视觉层级、窄屏规则）继续有效。`PAGE_DESIGN.md` 的内容与状态语言不变。

**本次实施范围（重要裁决）**：**只做量化线与共用页,信号线页面一律不建**——信号台/信号复盘/信号图库的数据源（R-0 结果、信号服务、模拟单账本、人工成交配对）尚不存在,现在实现即制造空壳;样稿保留为设计图纸,待 R-0 出结果且信号服务立项后另立任务实施。

**目标导航（本次落地 4 项）**：
```
数据 ｜ 策略与研究 ｜ 量化（运行 · 实例详情 · 复盘）｜ 账户
（信号 —— 暂不出现在导航,数据就绪后加入）
```
- **页面映射**：现 `#forward` → **量化·运行**（一级页仅四要素:一句话总结/四格健康条/实例列表/异常提示行;启用向导改为页内抽屉,退出导航）;`#forward/{instance}` → **量化·实例详情**（正常态一屏五问,审计信息默认折叠,异常驱动展开）;现 `#review` → **量化·复盘**（只答两问:执行忠实度逐周表 + 收益构成表,不放图表堆砌）;现 `#risk` **取消一级入口**——回撤水位与停止条件并入实例详情第④问,急停保留在实例行与实例详情,审计日志进各页「审计明细」Tab;`#data` 与 `#strategy`（策略与研究）按样稿重排,策略详情含**五步运转说明**（人话,非量化用户可复述）。
- **图形语言（本次落地部分）**：量化·实例详情与复盘可用样稿中的「持仓区间+调仓点」图（价格线 + 持多/持空底色 + 调仓时刻点）;所有图表遵循样稿配色与直标规范,不用红绿作唯一编码。
- **验收**：① 与样稿逐页比对结构一致（首屏一句答案+四格+主卡;一级页无第三个全宽面板）;② 启用向导为抽屉、非页面,Esc/点空白可关;③ 量化·复盘只有执行忠实度与收益构成两块主内容;④ 旧锚点 `#risk/#review/#forward/#plans/#symbol/#dashboard/#research` 全部重定向可达;⑤ 人话黑名单清零、内部编号零残留、六维状态语言合规;⑥ 后端零改动（本批纯展示层,读模型缺口显式占位）;⑦ 全量测试绿 + `verify_modular_baseline.py` PASS + 桌面/390×844 实测;⑧ TB4 运行路径零触碰。
- **分批**：批一 骨架+导航+量化·运行/实例详情;批二 量化·复盘;批三 数据页+策略与研究页。每批独立提交独立验收。
- **验收结论（Claude，2026-08-13）：三批全部通过（`ad8f29f` / `9e71349` / `4d8af55`）。** 逐条核实：① 导航落地四项「数据｜策略与研究｜量化｜账户」,风控/复盘一级入口按裁决取消;② 实例详情实现一屏五问（持有什么/是否按计划执行/赚亏来自哪里/离停止线多远/系统是否正常）,审计与技术状态收进折叠区;③ 量化·复盘只剩两块——逐周「忠实执行/需要解释」表 + 收益损耗构成,原 545 行砍到 178 行,大幅减法;④ 启用向导为抽屉（`role="dialog"`,点空白关闭）,**并按我上轮的过渡条款保留了「使用传统流程」兜底入口**,新编排未交付前不留启用真空;⑤ 十条旧锚点全部重定向（含 `risk→forward/live-small`、`review→forward/review`）;⑥ 策略详情五步说明为人话（观察市场→判断方向→控制分量→形成组合定期调整→先模拟再受控实盘）,参数由后端注入无前端副本;⑦ **后端零改动实证**（`git diff --stat -- backend/` 为空）;⑧ 人话黑名单与内部编号双扫描清零;⑨ 全量 `427 passed / 1 skipped`、`MODULAR_BASELINE_PASS`、`git diff --check` 通过。**遗留（非阻断,规格已列为占位）**：停止线剩余额度在接口未提供精确值时诚实标注不推算;信号线三页按裁决未建。

**PAGE-3 完成记录（Codex，2026-08-13）：三批实现完成，待 Claude 复核。** 批一 `ad8f29f`：导航收敛为“数据 / 策略与研究 / 量化 / 账户”，新增量化运行总览、五问式实例详情与启用抽屉；原启用工具保留为低显著度“传统流程”。批二 `9e71349`：量化复盘收敛为“每周执行忠实度”和“收益构成”两块主内容，移除曲线堆叠、季度检查点和旧日报混排。批三：策略与研究合并为统一入口，正式 TB4 与量价关系研究分流，策略详情按五步人话流程解释；数据页继续使用 PAGE-1 已完成的唯一正式数据版本与历史证据封存结构。旧锚点 `risk/review/plans/symbol/dashboard/research` 浏览器逐项验证均正确重定向；启用抽屉 Esc 关闭通过；390×844 实测无横向溢出，量化一级页只有一句结论、四格健康条和一张主卡，复盘严格两张主卡，策略入口五步完整；浏览器控制台零错误。验收：前端生产构建通过；后端全量 `428 passed`；`MODULAR_BASELINE_PASS`；本批后端零改动、TB4 受保护路径零触碰。

### 任务 PAGE-2：布局与视觉层级重构（2026-08-12 用户反馈「页面乱,信息从上排到下」,交付 Codex;设计稿先行）

**问题定位**：PAGE-1 定了内容与语义,未定版式——当前每页仍是全宽面板垂直无限堆叠,视觉上是「长文档」而非「驾驶舱」。本任务只改布局与视觉层级,内容与语义沿用 PAGE-1 冻结设计。

**流程**：Codex 产出 `docs/design/LAYOUT_DESIGN.md`（逐页桌面+窄屏 ASCII 线框图）→ Claude 评审冻结 → 分批实施。**设计稿未冻结不得改页面。**

**布局纪律（全站统一骨架,逐页线框须遵守）**：
1. **首屏一屏出答案**：每页第一视口 = 紧凑答案区（KPI 条 + 唯一主卡片）,回答该页核心问题;其余内容全部折下或收纳,禁止首屏出现第三个以上全宽面板。
2. **用宽度,别只用高度**：桌面端主内容区两栏化——主列（约 2/3,承载主卡片与明细）+ 侧列（约 1/3,承载状态/次要指标/快捷入口）;KPI 用四格网格;全宽面板仅留给表格与图表。
3. **次级内容收纳**：历史列表、技术详情、归档类内容一律进页内 Tab / 折叠区 / 抽屉,不与主内容同层堆叠;每页首屏外的区块数不超过 3 个可见分组。
4. **密度分级**：主数字大、辅助说明小、来源与口径最小;同层卡片等高;分组之间留白节奏统一,禁止面板间距忽大忽小。
5. **骨架一致**：七页共用「答案区 → 操作区 → 明细区」三段式骨架,用户学一次通用全站;操作区（写动作）视觉上与观察区明确隔离。
6. 图表与指标卡实现须达 dataviz 规范级（配色/对比度/图例直标）,评审时逐项核。
- **补充（2026-08-12,用户质询「数据不该只有一套吗」）**：数据页呈现原则修订——**现役数据只有一套**（全市场数据集,新研究唯一可绑定对象）,页面主体只展示它;旧研究数据（TB 系列 4h/校准缓存）**不得以并列数据集形态出现**,收纳为折叠的「历史证据封存（只读）」区,文案明确其唯一职责是「让已冻结结论与在跑策略可复验」,不可用于新研究,也没有「切换/选用」入口。
- **约束**：纯展示层;不改 PAGE-1 冻结的内容、语义与状态语言;不改任何后端;TB4 基线每批必跑;窄屏（390×844）每页实测。分批建议:批一（实盘+数据,日常最高频）→ 批二（研究+复盘+风控）→ 批三（策略+账户）。

**优先级收束（2026-08-12,应用户「真的是乱七八糟」反馈）**：Codex 侧**只做 PAGE-2,做完为止**——R0-UI-1 押后（训练在后台照跑,不受影响）,其余新线程冻结。PAGE-2 追加硬验收:每页首屏=一句答案+一张主卡;滚动不超一屏到底,其余进 Tab/抽屉;七页同骨架。装修一次刷完,不再碎片化交付。

**追加硬要求（2026-08-12,用户:「至少在页面上要让人看懂这个策略到底是怎么运转的」）**：策略的运转过程必须在页面上可懂,分两层交付:
1. **策略页「它是怎么运转的」区（PAGE-2 内,纯展示）**：用步骤条/流程图讲清一个周期内发生什么——「每 4 小时收一次盘 → 对 12 个币分别问五个时间尺度『最近在涨还是在跌』→ 按投票结果和各币波动大小算出下周该拿多少 → 每 7 天按计算结果自动调一次仓 → 亏到警戒线自动停」;每一步配一句人话解释,禁止公式与代号直出;真钱账的「×3 杠杆投影」「30% 停止线」在同图标注。
2. **实盘页「为什么拿着这些仓位」（SC-3 信号解释,PAGE-2 完成后立即做,唯一允许插队 R0-UI-1 之前的任务）**：逐币一行回答「为什么多/空/空仓」——五个时间尺度各自的涨跌投票、波动率导致的仓位缩放、最终权重;数据须来自冻结 runner 的只读诊断投影（生产同源,禁止前端重算,`STRATEGY_CENTER.md` §4.3 既有设计）。
- 验收标准（两层通用）:**不了解量化的人读完页面,能向别人复述这个策略在干什么**——验收时以此为准,读不懂即打回。

**追加结构原则（2026-08-12,用户:「多策略项目,不能把一个策略的细节堆在页面上,多策略难道往下继续堆?」）**：所有策略相关页面一律**「列表 → 详情」两级结构**,禁止把任何单一策略的完整细节平铺在一级页面:
1. **策略页一级** = 策略目录:每个策略一张卡（名称/阶段/一句话状态）;点卡进入**策略详情页**（独立路由如 `#strategy/{id}`）,运转流程/证据/风险都住在详情页里。当前只有一个策略就一张卡,结构从第一天起按 N 个设计。
2. **实盘页一级** = 实例列表:每个运行实例一行（策略名/账户/状态/今日概要）+ 全局健康条聚合;逐单、清单、核对细节住**实例详情页**（`#forward/{instance}`）。
3. **复盘/风控** = 一级聚合视图（全局回撤水位、全局偏差）+ 按实例下钻;不同策略的明细永不同屏平铺。
4. 深链路由沿用 PAGE-1 §10 的不可变 ID 规范。`LAYOUT_DESIGN.md` 线框须按此两级结构绘制。
5. **实盘页专项（2026-08-12,用户:「都不知道整个页面在干啥」）**：一级页只许四样东西——一句话总结（正常/有 N 件事要处理）、四格健康条、实例列表（每实例一行人话状态）、异常时的红色提示行;**启用向导整体撤出一级页**（一次性开通流程,收进「启用新实盘」入口,仅使用时出现）;急停保留为实例行上的紧急动作;清单/逐单/核对/权益全部住实例详情页。
6b. **启用向导极简化（2026-08-12,用户:「本来很简单,选策略、账号、输金额不就行了」——完全正确,现向导把机器检查清单外包给了用户）**：向导界面只剩**三项选择 + 一次确认**——策略下拉（仅列已准入策略）、账户下拉、**金额自由输入**、输入确认语启动。**金额规则（2026-08-12 用户定稿:不固定金额,给最低线+比例仓位）**：策略仓位天然按资金比例计算,金额为用户输入;系统按交易所最低下单额+策略目标权重**动态计算建议最低金额**（口径:至少 90% 目标名义可执行）,低于最低线时如实提示「只能执行部分组合」而非禁止;**对正在运行的实例改金额**属风险敞口变更,走确认语+审计留痕的正式变更流程,不提供随手调整入口;原 LIVE-SMALL 协议的固定 500 相应升级为「初始金额 500,后续变更走版本化流程」。**架构原则明文化（2026-08-12 用户定调:策略不受金额限制,只受整体仓位比例影响）**：①策略层零金额概念——定义只含比例（目标波动/仓位上限/权重/回撤线),任何以 USDT 计的数字禁止进入策略定义;②金额属实例层（策略×账户×金额的绑定信息）;③交易所最低下单额属执行层物理约束,以「可执行覆盖率」如实报告,不得表述为策略属性。三层分离在页面文案与数据模型中一体执行。原手动步骤（初始化基准/刷新规则/设置杠杆保证金/12 项预检）**全部转为点击后自动编排执行**:全过即启动;任一项失败以人话报告原因与所需动作,不让用户手动闯关。**护栏零削减**:检查一项不少、确认语保留、急停不对称保留、金额受协议约束;后端补一个编排入口（顺序执行既有各步 API,自身无新副作用）,审计逐步留痕不变。
7. **信息预算 + 异常驱动展示（2026-08-12,用户:「一个实盘两个页面都放不下」——根因是信息过量而非布局）**：实例详情页正常状态下**只渲染五问,一屏放完**——①持有什么/为什么（逐币一行）②本周执行对了吗③赚亏多少④离停止线多远⑤系统健康;**审计类信息（账本状态/批次号/协议字段/逐单原始回执/核对内部值/各类校验码）正常状态下一律不渲染**,收进底部「审计明细」折叠入口,供出事查案;**异常驱动**:哪一问出了问题,相关细节才自动展开到那一问下方。全站通用此原则:正常=极简,异常=细节自己浮出来。

**PAGE-2 设计稿完成记录（Codex，2026-08-12）：已提交 Claude 评审，页面尚未实施。** 新增 `docs/design/LAYOUT_DESIGN.md`，按最新追加约束重画七个一级页及策略/实例详情的桌面与 390×844 窄屏结构：全站统一“答案区→操作区→明细区”，首屏固定四格 KPI + 唯一主卡，历史/证据/审计进入 Tab、抽屉或折叠；策略与实盘强制列表→不可变 ID 详情，实盘一级页只保留一句总结、四格健康、实例列表和异常提示；策略详情以五步人话流程解释 4h 收盘、五尺度投票、波动缩放、七日调仓和 30% 停止；实例详情正常状态只回答五问，异常才展开相关证据。现役数据仍只有一套，旧缓存只进“历史证据封存”。范围冲突按时间顺序处理：PAGE-2 布局保持展示层，SC-3 信号解释与极简启用自动编排列为紧随其后的独立提交，接口未到位前禁止前端重算或用旧手工流程冒充。已同步 Claude 最新 R0 图形化与 R0-DIAG：结果区固定八类图，成本瀑布/事件收益分布登记报告缺口，MFE/MAE 路径散点与路径分布等待 v2.1；作废训练不占主卡，所有新增测量均不得改变原门与选参。设计稿含组件收敛、六阶段可回滚提交计划、逐页信息预算和 Claude 六项决策点；未经冻结不改页面。

### 任务 R0-UI-1：R-0 训练/锁箱的界面化运行与实时进度（**已押后,待 PAGE-2 完成**;2026-08-12 用户提出,交付 Codex）

**追加:结果图形化（2026-08-12 用户要求——只看结果没法指导下一步,图形化是研究闭环的必要输入）**。训练/锁箱报告须配六类图,全部达 dataviz 规范（配色对比度/图例直标/单位齐全）:
1. **组合总览图**:16 个参数组合的成本后均值点图 + bootstrap 置信区间须线,按过门/未过门着色——一眼看出谁接近门槛、差多远;
2. **成本瀑布图**:每组合毛收益 → 扣 Funding → 扣手续费滑点的逐层递减——直接回答「信号有没有信息、是不是死于成本」（半自动筛选路线的判据图）;
3. **分层对比**:高/中/低流动性层各自的净收益——看利润来自哪类市场;
4. **分年稳定性**:逐日历年均值——看是普适关系还是某一年的行情特产;
5. **诊断切片对比**:量递增 vs 非递增、新上市 vs 成熟,两组并排——你的两个直觉的图形答案;
6. **事件收益分布**:单事件净收益直方图——看肥尾（是稳定小赚还是靠极端大单撑着）。
**用途边界（一句话)**：图用于读懂死因/活因、设计**下一版**预注册假设或转向半自动——不提供任何「照图改本版参数重跑」的入口,本版结论只认冻结的门。

### 任务 R0-DIAG：逐事件行情路径测量（2026-08-12 用户要求,交付 Codex,**先于训练重跑**）

**背景**：用户明确战略取向——「后面可能不做全自动,低频做高盈亏比的短线（系统筛信号+人工决策）」。固定持有期收益对人工交易几乎无指导意义;需要每笔样本的**行情路径**:进场后最多曾浮盈多少、最多曾浮亏多少。**纪律定位**：纯增加测量字段的诊断补遗（契约 v2.1）,零改动及格线/选参/判定;在任何结果被阅读之前声明并实施,当前运行中的训练作废不读、补遗后重跑。
- **每事件新增记录**：① 持有窗口内最大浮盈/最大浮亏（百分比 + ATR 倍数双口径）;② 延长观察窗（至 2×H）内的同两值——看固定出场是否砍掉了后续空间;③ 到达最大浮盈/浮亏的时间（第几根）;④ 是否「先打止损后创浮盈高点」（止损过早诊断）。
- **配套图（并入 R0-UI-1 图形化,第 7、8 类）**：⑦ 盈亏比散点——每事件「最大浮盈 vs 最大浮亏」,人工交易价值一图定夺（右下密集=有高盈亏比空间;贴对角线=没肉）;⑧ 浮盈/浮亏分布直方图 + 到达时间分布。
- **验收**：字段计算有单测（含跳空/止损事件的路径截断口径）;判定管道零改动（门与选参结果与不加字段时逐字节一致,专测）;声明先于实施提交。

**R0-DIAG 执行令（用户 2026-08-13 选定路线 C,交付 Codex,当前唯一优先任务）**
- **背景**：训练已判 `TRAINING_FAIL`（记录见上节判读）。R0-DIAG 的目的不是翻案,而是回答**「人接手管理能否改善盈亏比」**,据此决定是否设计下一版假设（路线 B）。
- **纪律硬约束**：① 只增加测量字段,**九道门、选参顺序、币池、成本、统计方法一律不动**;② 重跑必须复现**完全相同的 `TRAINING_FAIL` 与逐组合数值**（与 `docs/evidence/r0/r0_training_v2_20260812.json` 逐字段一致性专测,不一致即判实现缺陷）;③ 锁箱仍不得触碰。
- **分析焦点（按已知结果收窄）**：突破族已确定性死亡,路径分析**重点在超跌族**,尤其 `跌≥10%` 的三个组合（其中最佳:观察 16 根/持有 16 根,+0.626%,7,051 事件）。
- **必须回答的五个问题**（报告须直接输出对应统计,不要求解读）：
  1. **最大浮盈(MFE)分布** vs 实际净收益——中位数 MFE 若显著高于实际收益,说明固定时间出场砍掉了肉,人工管理有空间;
  2. **最大浮亏(MAE)分布**——多少笔在最终盈利前曾深度浮亏（考验人能否拿得住）;
  3. **MFE 到达时间分布**——肉一般在第几根出现,决定持有期与盯盘节奏;
  4. **「先打止损、后创新高」占比**——2×ATR 止损是否过紧;
  5. **按年份切片的 MFE/MAE**——2022 年是「浮盈本来就小」还是「浮盈够但被止损打掉」,这决定大环境过滤该过滤什么。
- **交付形态**：结构化报告 JSON + 关键分布的图（复用 R0-UI-1 第 7、8 类图规格:盈亏比散点、浮盈浮亏与到达时间分布）;报告归档 `docs/evidence/r0/`。

**R0-DIAG 验收与判读（Claude，2026-08-13）：通过（`0172d99`）,报告 `docs/evidence/r0/r0_path_diagnostic_v2_1_20260813.json`。**
- **纪律核验全过**：`baseline_verdict=TRAINING_FAIL`、`selection_or_gate_effect=NONE`、`lockbox_opened=false`;声明的训练报告 SHA 与本机实测**逐位一致**（`8d5c9681…`）,复现门有专测（`test_reproduction_gate_requires_every_training_field_to_match`）;全量 `433 passed`、`MODULAR_BASELINE_PASS`。
- **五问答案（主组合:4h 内跌≥10%、持有 4h,7,051 事件,实拿 +0.626%）**：
  1. **浮盈 vs 实拿——差距巨大**:持有期内中位浮盈 **4.42%**（2 倍窗 5.94%）,实际中位只拿到 **0.75%**,**仅兑现约 17%**。固定时间出场是主要漏损处。
  2. **要吃肉必须先扛浮亏**:盈利单（3,874 笔,55%）中位曾浮亏 **1.86%**,71% 曾浮亏 >1%,47% 曾浮亏 >2%。
  3. **肉的到达节奏**:中位第 **8 根（约 2 小时）**到达最大浮盈,四分位 3–14 根（45 分钟–3.5 小时）——适合低频人工,不需秒盯。
  4. **止损明显过紧**:1,956 笔止损（27.7%）中 **43.4% 在止损后创出高于进场价的价位**（原持有期内即 22.2%）。
  5. **2022 年的真实死因**:不是「熊市没有反弹」——中位浮盈仍有 3.62%;而是**浮亏最大（3.87%）、止损后新高占比最高（54%）**,即被 2×ATR 反复扫损后行情又回来。
- **判读结论：半自动/人工路线获得数据支持,但须防过度乐观。** ①「肉是真的」——机会平均给出 4.4% 浮盈,而机械固定出场只拿 0.75%;②「漏损点明确且可工程化」——出场规则（固定时间→追踪/分批/目标位）与**止损宽度（2×ATR 过紧）**;③ **诚实边界**:MFE 是事后最高点,任何人都不可能每次卖在顶,合理预期是「显著优于 0.75%,远低于 4.4%」,**禁止把 MFE 当可实现收益**;④ **心理适配提醒**:该形态要求「计划内扛住约 2% 浮亏」,与用户自述弱点（砍不掉亏损）方向相反——正确姿势是**机械宽止损 + 绝不计划外扛单**,而非靠意志判断。
- **路线 B 的设计线索（须新预注册,禁止在旧协议改参重跑）**：更宽止损（3×ATR 或结构止损）、出场规则改造、2022 型环境过滤;验证用**仍封存的 2025-01→2026-07 锁箱**。

### 任务 RC-0：漏斗曲线诊断——系统能否有效缩小范围（2026-08-14 用户定义系统职责后立项,交付 Codex）

**系统职责定义（用户 2026-08-14）**：「此系统的作用就是尽可能缩小范围。」——系统不预测输赢、不承诺筛出的信号赚钱;**它的唯一职责是把全市场机会缩小到用户视野能覆盖的量级,判断力归用户**。据此,评估标准由「筛出的能不能赚」改为「**缩得够不够小 + 大机会漏得多不多**」。

- **两种失败方式（都须量化）**：① **缩不够**——过滤后仍每月数百个,用户无法处理;② **漏太多**——量降下来了但大机会同时被筛掉,剩余全是平庸样本。
- **核心指标 · 富集度**：`筛后集合中大机会占比 ÷ 筛前占比`。富集 >1 表示过滤器带真实信息;≈1 表示仅是随机抽稀（仍能降量,但用户面对的是随机样本,须如实说明）。「大机会」定义冻结为 **10 天窗口内 MFE ≥10R**（沿用现有测量,不新造口径）。
- **待测过滤器（首次测量用户自己的判断标准,此前八特征从未包含它们）**：
  1. **效率比** `ER = |净位移| ÷ Σ|逐根位移|`,窗口 N（取 96/288 两档）;
  2. **趋势强度** `= N 期收益率 ÷ 同期 ATR`;
  3. **插针度** `= (上影+下影) ÷ 实体` 的近 N 根均值;
  4. 三者的组合（同时过阈值）。
- **输出 · 漏斗曲线**：每个过滤器按分位阈值从松到紧扫描（如保留前 50%/20%/10%/5%/2%/1%）,每档记录:**① 每月剩余信号数;② 保留的 ≥10R 大机会占全部大机会的比例（召回率）;③ 剩余集合中大机会的占比（精确度）;④ 富集倍数**。两族、三窗口全给;并标出「每月 10~30 个」这一可用工作量区间对应的召回率与富集度。
- **纪律**：纯诊断,不设门、不判 PASS/FAIL、不碰锁箱;所有阈值扫描属训练集探索,**任何据此形成的规则仍须独立数据验证**,报告须带该标记。
- **判读用途**：若在「每月 10~30 个」的量级上仍能保住相当比例的大机会且富集 >1 → 信号服务立项有据,RC-1 指标即为首版过滤器;若富集 ≈1 → 系统仍可用于降量,但须向用户如实说明「这是随机抽稀,不含选股信息」。
- **验收与判读（Claude，2026-08-14，`1d3b641`）：通过,结论对 RC-1 原设想部分否定、部分支持。** 纪律齐全（锁箱未开未读、纯诊断、`474 passed`、明确「训练集探索值不是交易门槛」）;去重后 43.5 万独立事件。
  1. **三个指标只有一个带信息**：**方向对齐趋势强度**（`信号方向 ×(收盘−N根前收盘)÷ATR14`）在两族、三结果窗口上一致富集 >1——超跌族 288 根在月均 23.4 个信号处富集 **1.84×**（精确度 13.29%→24.40%）,突破族 96 根富集 **1.73×**;**效率比反向有害**（富集 0.35~0.59,越"直"的路径后续大机会反而越少）;**插针度接近随机抽稀**（0.94~1.12）。**RC-1「强、顺、少插针三者同时过线」的原设想不被数据支持,三者捆绑后被效率比拖累（超跌族组合仅 0.76×）。**
  2. **降到可用工作量的代价极大**：突破族原始信号量过大,压到月均 13 个需保留 0.2%,**漏掉 99.6% 的大机会**（精确度虽升到 50~61%）;超跌族保留 5% 时召回 9.18%,即**仍漏掉约 91%**。「缩得够小」与「大机会不漏」在当前指标下无法兼得。
  3. **月度拥挤是产品级隐患**：月均 13~23 个的档位,月度 p90 达 35~64 个,单月最高 109~137 个。固定历史分位只能控长期均值,**不能保证每月只推 10~30 个**;产品化须另行预注册「按时间桶限额/排序」的展示机制（报告未偷加,做法正确）。
  4. **对系统职责的回答**：「缩小范围」可拆为**纯降量**（任何指标靠极端分位都能做到,但富集≈1 时只是随机抽稀）与**有信息的降量**（当前仅方向对齐趋势强度做到）。**系统确实能有信息地缩小范围,但幅度有限（1.8 倍左右）,且以漏掉九成机会为代价。**
  - **Claude 结论**：RC-1 应**放弃三指标捆绑**,以**方向对齐趋势强度为唯一主要候选**,效率比与插针度降级为待重新定义或放弃的对照。**不要在本训练集上继续找更漂亮的边界**（多重检验已到极限）;正确路径是前向 paper 采集真实数据后验证富集度、召回率与月度拥挤。锁箱继续封存。

**RC-0 完成记录（Codex，2026-08-14）：漏斗曲线已生成，锁箱未开。** 新增冻结契约 `config/research/rc0_funnel.v1.json`、纯计算模块和可恢复离线扫描器；同族内按“family + symbol + signal time + direction”去重，12 组参数的 1,637,351 个参数样本合并为 434,558 个独立事件（突破 406,245、超跌 28,313），避免月频率被多参数重复命中放大。正式机器报告 `docs/evidence/rc0/rc0_funnel_v1_20260814.json`（SHA-256 `0095357397cdd12929e5cf0366f03d50010f9bc721dd93ae1e80391bf8cd932f`），可读报告 `docs/evidence/rc0/RC0_FUNNEL_V1_REPORT.md`。

- **核心结果：只有方向对齐趋势强度稳定富集。** 以 10 天 `MFE≥10R` 为主标签，在月均 10~30 个附近：突破族 96/288 根趋势强度均保留 0.2%、月均 13.4 个，富集 `1.73×/1.44×`，但召回仅 `0.35%/0.29%`；超跌族 96/288 根趋势强度均保留 5%、月均 23.4 个，富集 `1.32×/1.84×`，召回 `6.61%/9.18%`。同方向在 1/3/10 天标签中一致。
- **ER 与插针度不支持原 RC-1 三指标组合。** 可用工作量附近，高 ER 的富集在突破仅 `0.51~0.59×`、超跌仅 `0.35~0.41×`，呈反向抽稀；低插针度约 `0.94~1.12×`，接近随机；三者同时要求被 ER 拖累，超跌 288 根组合月均 25.9 个时富集 `0.76×`，突破组合没有扫描点正好落入工作量区间。故“强”获支持，“顺/少插针”按当前定义未获支持，不得直接捆绑成 RC-1 规则。
- **工作量仍有峰值问题。** 落在月均区间的趋势强度曲线，月度 p90 仍约 35~64 个、单月最高 109~137 个；固定历史分位只控制长期平均，不能保证每月都在 10~30 个。若产品化，按时间桶限额/排序必须另立协议，当前未实现。
- **纪律**：特征只含信号时刻及以前已收盘 K 线；MFE 标签仅作事后诊断；`training_end_ms=1735689599999`、`lockbox_opened=false`、`lockbox_data_read=false`、`selection_or_gate_effect=NONE`。所有探索边界必须独立前向验证，不产生交易门或实盘授权。契约 SHA-256 `43cc541b4d871ac10b9d6d9900cd319f26b0719efd6456c3f04542f4cee1342b`。
- **验收**：RC-0 专项 `6 passed`，后端全量 `475 passed`（仅 2 条既有 Pydantic 弃用警告），`MODULAR_BASELINE_PASS`；报告来源/契约哈希、去重事件数、两族×两特征窗×三结果窗×四过滤器×九档曲线、逐月计数合计与锁箱字段均通过自动校验。

### 任务 RC-0B：降量曲线测量——币池门槛 × 形态严格度（2026-08-14 用户决策后立项,交付 Codex）

**用户决策链（记录在案）**：① **不再增加预测型过滤器**,剩余判断交给人;② 但突破族原始量每天约 225 个,人无法处理,须降量;③ 降量手段选**提高币池成交额门槛**（用户明确:从 3,000 万提高到 **2 亿**,理由是「绝对门槛保留热门小币,排名截断只保留大币」——与此前删除固定 top-120 同一原则）。

- **测量内容（纯计数,不含任何预测性判断,不设门、不碰锁箱）**：对**突破族与超跌族**分别计算,在下列组合下的**实际信号量**:
  1. **币池日成交额中位数门槛**：`3,000 万 / 1 亿 / 2 亿 / 5 亿`（沿用现有 3 日中位口径）;
  2. **形态严格度**（仅突破族,超跌族保持冻结定义不变）:通道 `32 / 96 / 288 根`,放量倍数 `1.5 / 2.5 / 4.0`;
  3. 每个组合输出:**日均信号数、月均、月度 p90、单日最大、单月最大**、同时合格市场数的日均与分布、以及**保留的 10 天 ≥10R 大机会占全量的比例**（仅作参考,说明降量代价,不作为选择依据）。
- **交付形态**：一张可直接读的表 + 机器报告归档 `docs/evidence/rc0/`;**由用户按真实数字选定最终组合**,不由 Codex 或 Claude 代选。
- **纪律**：这是**非预测型降量**——门槛与形态严格度改变的是「机会的稀有度」,不声称「更可能盈利」;报告不得据此推荐"最优"组合,只陈述数量与代价。所有数值仍属训练集统计,产品化时需重新以前向数据核对。
- **后续**：用户选定后,该组合即为信号服务首版的**推送范围定义**,写入信号服务规格;此后系统只负责扫描、推送、守纪律、记录,不再做筛选。

**RC-0B 完成记录（Codex，2026-08-14）：40 组非预测型降量曲线已归档，等待用户选择。** 以 RC-0 同族去重事件为唯一母池，完整复现突破 `406,245` 条（`222.72/日`）与超跌 `28,313` 条（`15.52/日`）；逐项计算 `3,000万/1亿/2亿/5亿` 三日成交额中位门槛，突破再交叉 `32/96/288` 根通道与 `1.5/2.5/4.0` 倍放量，共 36 组，超跌冻结形态共 4 组。用户指定的 `2亿` 门槛单独作用时，突破降至 `59.79/日`、超跌降至 `5.03/日`；若突破同时使用 `96根+2.5倍`，降至 `21.40/日`，但训练期 `10天 MFE≥10R` 大机会仅保留 `8.4%`。峰值仍显著高于均值：该组合月度 p90 `1052.7`、单日最大 `140`，说明流动性与形态严格度能降长期总量，不能消除共振日拥挤。`2亿` 门槛下同时合格市场日均 `20.2`、中位 `20`、p90 `35`、最大 `78`。以上只陈述工作量与代价，不含预测型过滤、不推荐组合、不产生交易门；最终组合仍由用户选择。机器报告 `docs/evidence/rc0/rc0b_volume_curve_v1_20260814.json`（SHA-256 `2ade73c6…8a19`），中文表 `docs/evidence/rc0/RC0B_VOLUME_CURVE_V1_REPORT.md`，冻结契约 `config/research/rc0b_volume_curve.v1.json`（SHA-256 `7de8b62f…ab44`）；锁箱未打开、未读取。验收：RC-0/RC-0B 联合专项 `14 passed`，后端全量 `483 passed`（仅 2 条既有 Pydantic 弃用警告），机器报告从特征库重复生成后 SHA-256 完全一致，`MODULAR_BASELINE_PASS`。

### 任务 SIG-1：信号服务最小可用版（2026-08-14 立项,交付 Codex,轨道二正式开工）

**目标**：按已冻结的推送范围实时扫描,每个信号自动记模拟单,并通过 **Pushover** 把最好的少数几个推到用户手机。先做到「能收到信号、有完整记录」,页面与人工配对留给 SIG-2。

- **前置依赖（必须知晓）**：需部署在 Binance 可达主机并有实时 15m 行情——**与 TB4 前向同一台服务器,目前尚未部署**;本任务可先实现与测试,真实运行待部署。
- **① 信号生成**：按冻结范围扫描——币池日成交额中位数 ≥2 亿（3 日中位）、突破族 8 小时通道 + 放量 ≥4.0、超跌族沿用冻结定义;每根 15m 收盘后计算,信号只用已收盘数据。
- **② 信号模拟账（核心资产）**：**每个信号无论是否推送、是否被用户采纳,一律自动记一笔模拟单**——机械进出（次根开盘进、2×ATR 止损、冻结时间退出）,只追加哈希链落盘,复用 TB4 账本构造。**被每日限额截断的信号同样入账**,供事后评估限额代价。
- **③ Pushover 推送（用户 2026-08-14 指定）**：
  - **规则**：设趋势强度高门槛,**够格即时推送,每天最多 3 条**;额度用完当天不再推,页面仍可见全部（限额 30）。**不采用「等一天结束排序取前三」**——信号有时效,等不起。门槛取值写入配置并记录在案,首版建议取历史日内前 10% 分位,上线后按实际推送频率校准。
  - **内容**：币种、方向、触发原因（哪类形态/放量倍数/趋势强度排名）、参考进场价、建议止损价、1R/2R/3R 参考位、信号时刻。
  - **凭证安全**：Pushover 的 API Token 与 User Key **必须走既有凭证库**（Linux AES-GCM / Windows DPAPI 或 `env:` 引用）,**禁止明文入配置或日志**;推送内容不含任何账户、持仓、金额信息。
  - **旁路原则**：推送失败**不得影响信号生成与模拟账落盘**;失败与重试如实记录,连续失败在页面/日志告警。
- **④ 记录**：信号、模拟单、推送发送与结果全部只追加、可复算;每日限额与门槛的实际生效情况逐日留痕。
- **验收**：① 信号定义与冻结范围逐项一致（对照测试:同一段历史回放,产出信号与 RC-0B 口径一致）;② 模拟账只追加、防篡改、重启可恢复;③ **被限额截断的信号确实入账**（专测）;④ 每日推送上限与门槛有测试（含跨日重置、额度用尽后不推）;⑤ Pushover 凭证不出现在配置/日志/接口响应（grep 专测）;⑥ 推送失败不影响主流程（故障注入测试）;⑦ 全量测试绿 + 基线 PASS + TB4 零触碰。
- **不在本批**：信号台页面、人工成交配对、四条硬约束、三账对比复盘（均属 SIG-2）。

### 信号服务推送范围（**用户 2026-08-14 定稿,冻结**）

RC-0B 验收通过（`62b5e69`,`482 passed`,锁箱未碰,报告明确不代选）。**用户按真实数字选定方案 A + 每日限额 30**,自此成为信号服务首版的推送范围定义：

| 项 | 冻结值 |
|---|---|
| 币池门槛 | 日成交额中位数 **≥ 2 亿 USDT**（3 日中位口径,动态,同时合格市场日均 20.2 个） |
| 突破族形态 | 通道 **32 根（8 小时）**、放量 **≥ 4.0 倍** → 日均 16.1 个 |
| 超跌族形态 | 冻结定义不变（跌 ≥10%/观察 16 根） → 日均 5.0 个 |
| 合计工作量 | **日均约 21 个** |
| **每日限额** | **30 个/天**;超出部分按**方向对齐趋势强度**降序取前 30（该指标是 RC-0 中唯一被证实富集 >1 的） |

- **关键依据（记录,防止日后误改）**：RC-0B 显示**收紧形态不带选股信息**——各档「大机会保留% ÷ 日均」效率几乎持平且随收紧略降（0.425 → 0.373）,故组合选择纯属工作量取舍,方案 A 在同等工作量下保住的大机会最多（6.4%）。突破族基数约为超跌族 42 倍,故即便只保留 6.4%,绝对数量仍远多于超跌族。
- **限额的定位（须写进产品文案）**：**限额是工作量保护,不是预测型过滤**;仅在信号超过 30 个的日子生效（超跌族单日峰值 293、突破族 88,共振日必然触发）。排序用趋势强度是「不得不排时的最小信息选择」,不声称被截断的信号更差;**被截断的信号仍须完整进入信号模拟账与记录**,供事后评估限额代价。
- **后续**：此范围定义写入信号服务规格;系统职责自此仅为扫描、推送、守纪律、记录,不再新增任何筛选。

### 候选概念 RC-1：强势平滑上涨顺势入场（2026-08-14 用户提出,**待 RB-2 结果后正式预注册**）

**用户原话**：「也可以不做回调买,就是选上涨趋势中的点买入,关键是判断此上涨趋势强势、上涨比较顺、没有大幅来回插针;这种机会可能很少,一个月一次甚至没有,那就做到尽可能低频。」

- **与既有候选的本质差异**：既非事件触发（突破/超跌）,而是**状态过滤**——先判定「这段趋势的品质」,合格即顺势入场,不挑时机、不等回调。低频是设计目标而非副作用。
- **「顺」的机械定义（入场时点可算,仅用已收盘数据）**：
  1. **效率比（主指标）** `ER = |净位移| ÷ Σ|逐根位移|`,窗口 N;ER→1 为一路平滑,ER→0 为来回震荡。直接对应「没有大幅来回插针」。
  2. **趋势强度** `= N 期收益率 ÷ 同期 ATR`（风险调整后的涨幅,涨得多且波动小才算强）。
  3. **插针度** `= (上影+下影)长度 ÷ 实体长度` 的近 N 根均值/分位。
  4. 可选辅助:收盘位于 K 线上半部的比例、价格未破关键均线的连续根数。
- **入场/出场骨架（待预注册时冻结）**：三指标同时过阈值 → **次根开盘买入,不等回调**;出场用追踪止损（目标是吃长趋势,不设固定时间）;频率由阈值本身控制,另设名额上限与冷却。
- **必须正视的对立假设（写进预注册的诚实条款）**：买入强势平滑趋势 = 可能买在**趋势耗尽**处。「延续」与「耗尽」是同一形态在不同阶段的表现,先验无法分辨,**只能由数据裁决**;预注册须同时报告「入场后继续上行」与「入场即见顶」两类结果的占比。
- **与 TB4 的重叠度评估（立项前必答）**：TB4 已是多尺度动量 + 7 天再平衡且在实盘运行。RC-1 须论证其**独立价值**——即「按趋势品质择时的单标的入场」是否优于「按周机械再平衡的组合持有」,否则属重复建设。
- **排期**：**等 RB-2 的顺滑度与长周期趋势分组结果**——那两项会先告诉我们「顺滑度在数据里是否可辨识、长周期方向是否主导收益」,直接决定 RC-1 的指标设计与阈值方向。RB-2 判读后再起草正式预注册。

### 任务 RB-2：机会画像诊断——「这批信号值不值得做成信号服务」（2026-08-14 用户 reframe 触发,交付 Codex,当前唯一优先任务）

**RB-2 完成记录（Codex，2026-08-14）：机会画像已归档，锁箱未开。** 新增纯描述配置 `config/research/rb2_opportunity_profile.v1.json`（SHA-256 `d3c578fb…47b02`）及训练期离线诊断工具；逐组复现 R-0 冻结的跌≥10% 超跌信号（观察窗 16/32 × 原持有 8/16），并在同一可比事件集上并列画像 R-0 原出场与 RB-1 `ST-B__EX-B`，共 8 组。四组可比事件数 8,765/7,050/21,653/15,986，仅因 RB-1 32 根路径越过训练截止共同排除 2/1/3/1 笔，未向后读取锁箱。稳定描述：Top 10% 贡献正利润池约 47.0%–54.8%，移除 Top 10% 后 8/8 组整体均为负；RB-1 路径中 MFE/R p90 约 3.02–3.36、摸到 2R 比例 20.4%–22.8%，但 MFE 是事后上限。频率为日历日均 3.96–11.96 个，极端单日 225–564 个，前十大币只占约 10.2%–10.6%，说明平日可低频观察但共振日有信号洪峰。Top 10% 相对 Bottom 10% 较一致地表现为相对成交量更高、BTC 同窗更弱、UTC 时段略早；跌幅深度仅在 16 根窗口差异较明显，流动性层/上市年龄/量趋势无跨组合一致方向。上述只作陈述，若升级为筛选条件必须另立协议并独立验证。报告 `docs/evidence/rb2/rb2_opportunity_profile_20260814.json`（SHA-256 `3afd4dae…bbdd`）与可读摘要已归档；报告无门、无 PASS/FAIL、`lockbox_opened=false`、`lockbox_data_read=false`。

**RB-2 新增规格补齐（Codex，2026-08-14）：筛选力曲线 + 突破族门 B 对照完成。** 保留 v1 不覆盖，完整 v2 报告 `docs/evidence/rb2/rb2_opportunity_profile_v2_20260814.json`（SHA-256 `6d5b83ec…a4944`）含超跌族 8 个“参数×出场”画像及突破族 8 个冻结参数画像。筛选力需求 `k*` 定义为事后剔除最差事件后剩余均值首次超过 +0.3% 的最小比例：超跌 7/8 组为 5%、1/8 为 10%；突破 8/8 均为 20%，说明超跌是明显更容易筛选的猎场，突破族门 B 难度下限仍高。反向“只保留最好 k%”曲线同步输出。突破族从冻结 R0 训练检查点完整复现事件数与均值；因检查点无路径 K 线，MFE/R 及缺失的连续特征明确标空，不伪造。配置 SHA 更新为 `58743911…66d8`；锁箱仍零读取、无门、无 PASS/FAIL。

**用户 reframe（决定性,记录在案）**：「重点不是一组参数的成功或失败,而是这组参数有没有做信号的必要;做信号也不是每单必做,而是看有没有高收益的。」——此前 R-0/RB-1 的全部门槛（均值、bootstrap 下界）回答的是「机械做完每一单是否赚钱」（全自动问题）,与用户的半自动路线不匹配。**均值≈0 且右尾肥,恰恰是半自动打猎的理想形态,却会被现有门直接判死。** RB-2 改用「机会画像」口径评估。

- **定位**：纯描述性统计,**不设门、不判 PASS/FAIL、不拟合规则、不碰锁箱**;产出用于回答一个产品决策——**是否值得为这个形态建信号服务**。
- **评估对象**：跌≥10% 的超跌信号集（沿用 R-0 冻结信号定义,观察窗 16/32 两版都算）;出场口径同时给两套:R-0 固定出场 与 RB-1 胜出出场,以便看「机会本身」而非「某套出场」。**同时对突破族出同样画像作并排对照**（2026-08-14 用户分流原则要求:被门 A 判死的族,下葬前须照门 B 看一眼;并排比较本身有信息量）。
- **必须输出的四组画像**：
  1. **R 倍数分布**：以初始风险 R 为单位的**最大浮盈（MFE）与最终收益**分布——p50/p75/p90/p95/p99,以及摸到 ≥1R/2R/3R/5R/10R 的事件占比;直方图数据随报告输出。
  2. **尾部贡献度**：按最终收益排序,**top 1%/5%/10%/20% 分别贡献总利润的百分比**;并给出「剔除 top 10% 后整体是正是负」——这是「价值是否集中在少数单」的直接答案。
  3. **频率画像**：每月/每周信号数、每日均值、单日最多、按币种分布（有没有集中在少数币）;供判断人工可处理性。
  5. **筛选力需求曲线（2026-08-14 用户洞察「失败很多但整体接近打平的参数组很有必要」的量化）**：把事件按最终收益排序,依次剔除最差的 `5%/10%/15%/20%/30%/40%/50%/60%`,输出每一步剩余事件的均值与事件数;报告**最小剔除比例 k\***（使剩余均值 > +0.3%）。用途:横向比较各参数组的**筛选难度**——k\* 小 = 只要避开少数明显的坑就转正 = 好猎场;k\* 大 = 需要近乎不可能的筛选精度。**诚实标注**:剔除最差是事后视角,衡量的是任务难度下限,不是可实现收益。同时输出反向口径「只保留最好的 k%」的均值曲线。
  4. **可辨识性检验（决定性）**：将事件按最终收益分为 **top 10% / 中间 / bottom 10%**,比较三组在**信号时刻即可观察**的特征分布：跌幅深度、相对成交量、量趋势、大盘同期状态、流动性层、UTC 时段、上市年龄、ATR 相对水平。**逐特征输出三组的分布对比与差异量度**（分位数表 + 组间均值差）。结论只作陈述,不下判断。
- **诚实边界（写进报告）**：MFE 是事后可达上限,不等于人能拿到;可辨识性差异若存在,仍须经独立数据验证才可作为筛选规则（届时用锁箱或前向数据）。
- **验收**：① 锁箱零读取（fail-closed 专测）;② 不含任何门/PASS/FAIL 字段;③ 四组画像齐全且逐参数组合输出;④ 与既有冻结报告的事件集一致性（同信号定义,专测）;⑤ 全量测试绿 + 基线 PASS;⑥ 报告归档 `docs/evidence/rb2/`。
- **后续路径**：若「尾部集中 + 存在可辨识差异」→ 信号服务立项有据,进入半自动试跑设计;若「尾部不集中」或「三组特征分布无差异」→ 人工筛选无立足点,该形态如实关闭,锁箱保持封存。
- **验收与判读（Claude，2026-08-14）：交付部分通过,两项规格缺失须补;已交付部分的结论对半自动路线不利（`c072b1d`）。**
  - **纪律核验通过**：`lockbox_opened=false`、`lockbox_data_read=false`、无门/无 PASS-FAIL 字段、含 `honesty_boundary`;`458 passed`。
  - **缺失（须补齐重交）**：① **第 5 组画像「筛选力需求曲线」未实现**（全库无 removal/k\* 字段）——这正是量化用户「多亏少赢仍打平即好猎场」洞察的核心指标;② **突破族对照画像未产出**（8 张画像全部是超跌族 4 组参数 × 2 出场口径）,与「被门 A 判死的族下葬前须照门 B」的原则不符。
  - **⑤ 追加：长周期趋势状态特征（2026-08-14 用户「顺不顺要结合长周期行情」触发,Claude 判定为原可辨识性检验的关键遗漏）**。**问题定位**:原八特征中的 `btc_same_window_return_pct` 衡量的是「此刻大盘同窗口涨跌」,**不是「该币自身的长周期趋势方向」**;而按年份结果（2021 牛市 `+1.62%` / 2022 熊市 `−0.97%` / 2023 震荡 `−0.02%` / 2024 `+0.46%`）强烈提示长周期方向才是主导变量——同一个「跌 10% 后止跌」,在长周期上涨中是**上升趋势回调买入**（经典稳健形态）,在长周期下跌中是**接飞刀**,性质相反。**新增信号时刻可观察特征（全部只用信号前已收盘数据,无未来泄漏）**:① 该币 4h 收盘价相对 4h 50 期均线的位置与偏离度;② 该币 20 日 / 60 日收益率符号与数值;③ **信号方向与长周期动量方向是否一致**（超跌族做多 vs 长周期涨跌）;④ 长周期趋势已持续时长;⑤ BTC 自身的长周期趋势状态（区分个币趋势与市场趋势）。**分组输出**:按「长周期上涨 / 震荡 / 下跌」三分组,各组的收益 R 分布、顺滑度分布、尾部贡献与事件频率。**判读用途**:若「长周期上涨组」在收益与顺滑度上均显著优于其余组,则「只在长周期趋势向上时做超跌回调」成为最有前景的下一版假设,且该条件在入场时点完全可观察、可执行。
  - **④ 追加：按「顺滑度」分组的可辨识性检验（2026-08-14 用户交易偏好触发:「尽量只做很顺的趋势行情,尽可能少做」）**。定义**顺滑度 = 最大浮盈 R ÷ 最大浮亏 R**（浮亏为 0 时按最小可分辨值处理,口径写进契约）。按顺滑度分 TOP 10% / MIDDLE / BOTTOM 10%,重复第 4 组的八特征分布对比。**动机**:「最终赚多少」与「走得顺不顺」是两个问题,前者已证不可辨识,后者未测;若顺滑度存在入场时可辨识的先兆,则「只做顺的」在进场时点可执行,否则只能靠机制淘汰（分批建仓 + 追踪止损）而非预测。**多重检验成本如实记录**:本项训练期切片再加一维,任何发现必须以独立数据验证方可作为规则。
  - **③ 追加：长周期机会画像（2026-08-14 用户质疑「大行情应该都来自突破」触发,Claude 认定为原测试的结构性缺陷）**。**问题定位**:突破族持有上限 32 根（8 小时）,而「大行情」从启动到走完通常需数日至数周——原设计等于只测量了突破后的头 8 小时即强制平仓,**大行情的利润在结构上不可能进入统计**。故「突破族亏损」的准确表述是「15 分钟突破 + 8 小时持有亏损」,不等于「突破无效」;项目内已有反证——TB4 正是靠 4h 动量 + **7 天再平衡**捕捉同一现象并通过全部关卡、当前实盘运行中。**补充测量（纯诊断,不设门、不改任何冻结定义、不碰锁箱）**:对突破族与超跌族的信号,把观察窗从持有期延长到 **96 / 288 / 960 根（约 1 天 / 3 天 / 10 天）**,逐窗口输出:最大浮盈/最大浮亏的 R 倍数分布与分位、摸到 ≥2R/3R/5R/10R 的比例、尾部贡献度、到达最大浮盈的时间分布。**判读用途**:若长窗口下突破族出现明显肥尾（短窗口没有）,则证实「大行情来自突破、但需长持有」,后续应作为**新的长持有假设**预注册（并须评估其与 TB4 的重叠度,避免重复建设）;若长窗口下仍无肥尾,则「突破无效」的结论才真正成立。
  - **已交付部分的判读（最佳组合:跌10%/观察16/持有16,R-0 固定出场,7,050 事件）**：
    1. **尾巴不肥,这是最关键的负面证据**。最终收益以 R 为单位:p50 `0.12R`、p90 `1.15R`、p95 `1.52R`、**p99 仅 2.61R**;≥2R 仅 157 单（2.2%）,≥3R 仅 45 单（0.6%）,≥5R 仅 2 单。即便用事后 MFE 口径,曾摸到 ≥2R 的也只有 384 单（5.4%）。**这不是「多亏少赢、赢的极大」的肥尾结构,而是「赢面普遍很薄」。**
    2. **尾部集中度中等偏低**：top 10% 贡献正收益的 47%、top 20% 贡献 69.6%;去掉 top 10% 后均值 −0.893%。集中度存在,但远未到「少数单扛起全部」的程度——这与 1 的薄尾一致。
    3. **可辨识性检验：未发现能区分赢家与输家的特征（决定性负面）**。八个信号时刻特征中,TOP 10% 与 BOTTOM 10% 的中位数几乎重合:波动率 `4.36 vs 4.32`、跌幅深度 `12.47 vs 12.68`、大盘同期 `−4.70 vs −4.24`、相对成交量 `1.71 vs 1.48`、时段 `10 时 vs 12 时`。**唯一显著的模式是 TOP 与 BOTTOM 双双高于 MIDDLE（波动率 4.36/4.32 vs 3.07）——即该特征只区分「赌局大小」,不区分「输赢方向」**:挑高波动信号只会同时放大盈亏,不改变胜负比例。
  - **补齐第一轮验收（Claude，2026-08-14，`9b0b964`，报告 v2）：通过两项、仍缺三项。** 已补:**筛选力需求曲线**（含 remove-worst / retain-best 双曲线、k\* 与「事后视角」诚实标注）、**突破族对照画像**（16 张,两族齐全）;纪律不变（锁箱双 false）,`459 passed`。**仍缺**:③ 长周期画像（1/3/10 天窗口）、④ 顺滑度分组可辨识性、⑤ 长周期趋势状态特征——报告中无 `horizon`/`smooth`/`efficiency`/`ma50`/`20d` 等任一字段。
  - **重大发现:用户「大行情来自突破」的判断被数据证实（突破族确有肥尾,超跌族没有）**：
    | | 突破族（29.8 万事件） | 超跌族（2.2 万事件） |
    |---|---|---|
    | 收益中位数 | **−0.76R**（多数小亏） | 0.00R |
    | p90 / p95 / p99 | 1.48 / 2.33 / **4.69R** | 0.84 / 1.13 / **1.81R** |
    | top 10% 贡献 | **68.8%** | 53.0% |
    | top 20% 贡献 | **91.0%** | 76.5% |
    | 去掉 top 10% 后均值 | −1.036% | −0.98% |
    | 转正所需剔除最差比例 k\* | 20% | 5% |
    **突破族是典型的趋势跟踪收益结构——大多数单子小亏、少数单子大赢、利润高度集中于头部（top 20% 占 91%）**;超跌族则是薄尾。这正是「大行情来自突破」的数据形态。原「突破族确定性死亡」的结论**仅在门 A（机械做完每单）口径下成立**;按门 B 口径,突破族反而是两者中更像好猎场的那个。
  - **但门 B 的另一半仍未通过:大赢家依旧不可辨识。** 突破族 TOP 10% 与 BOTTOM 10% 在信号时刻的特征仍高度重合,唯一有差异的 `atr_relative_pct` 呈现与超跌族相同的模式——**TOP 1.106 / BOT 1.639,反而是最亏的那批波动更高**,中间 0.778 最低;即该特征仍只区分「赌局大小」不区分「输赢方向」。八特征中多数在分类口径下未产出可比中位数,**证据不足以支持「人工可挑出大赢家」**。
  - **补齐第二轮验收（Claude，2026-08-14，`cc95e80`）：进行中,尚不可判读——只交付了计算内核,未产出报告。** 已落地:`rb2_long_cycle.py`（4h 聚合、长周期状态判定 `UP/DOWN/RANGE`＝收盘在 MA50 上方且 20 日与 60 日收益同向、长窗口 MFE/MAE 与顺滑度 `mfe_r/mae_r`、到达时间）与契约条目（窗口 `96/288/960`、MA50、20/60 日）。**缺口**:① 未产出任何新报告（`docs/evidence/rb2/` 无新文件）;② **无对应测试**（`459 passed` 与上一轮持平,无 `long_cycle` 测试文件）——长周期状态判定与未来极值计算属易错逻辑（尤其 `future_extrema` 的窗口边界与无未来泄漏),必须有单测方可采信;③ 三项待补内容中仅内核就位,顺滑度分组的可辨识性对比、长周期三分组的收益/顺滑度/尾部输出均未生成。**要求**:补测试 + 跑出报告后重交,再行判读。**设计层面初审**:长周期状态定义（MA50 + 20/60 日双确认）合理且只用已收盘数据,与 `uses_completed_bars_only: true` 声明一致,方向正确。
  - **判读（关键,决定下一步方向）**：突破族「有肉」已证实,「够得着」未证实。而**尚缺的三项恰好是最可能提供「够得着」证据的维度**——长周期趋势状态（用户指出的主导变量）、顺滑度分组、以及长窗口下被 8 小时截断的真实尾部。**必须补齐后才能对突破族下最终结论;在此之前不得关闭突破方向。**
  - **补齐第三轮验收（Claude，2026-08-14，`d0eb8f7`）：通过,RB-2 至此完成。** 三项缺口全部补齐:长周期 1/3/10 天画像、长周期趋势分组、顺滑度可辨识性;新增三项单测（仅用已收盘 4h、未来极值窗口边界与顺滑度下限、趋势判定使用前 360 根）,`463 passed`;锁箱双 false;报告含 `TRAINING_SLICE_REQUIRES_INDEPENDENT_VALIDATION` 标记与诚实边界章节。覆盖 387 市场、12 组参数、163.7 万「参数×信号」样本。
  - **最终判读（RB-2 全部结果汇总）**：
    1. **「大行情来自突破」完全证实,且随窗口拉长持续放大**:突破族 MFE 中位数 1 天 `2.04~2.16R` → 3 天 `3.54~3.80R` → **10 天 `6.54~7.13R`**;10 天内曾触及 10R 的比例达 **33.5%~36.8%**。超跌族同窗口只有 `3.02~3.79R`、触及 10R 仅 `9.6%~14.3%`。**原「8 小时封顶」确实把突破族的尾巴整段切掉了,用户的质疑成立。**
    2. **但机会与痛苦同步放大**:突破族 10 天 MAE 中位数 `6.32~7.01R`,与 MFE 几乎等量级。**路径不天然顺滑**——「有大行情」不等于「拿得住」;MFE 是反事实上限,不可当作可实现收益。
    3. **长周期趋势门不成立（关键否定结果）**:突破族在本币 UP/RANGE/DOWN 三组的平均最终 R **全部为负**（`−0.237~−0.178R`）,顺势组只是少亏（`−0.191~−0.153R`）,**不足以据此建门**。超跌族 DOWN 组四组全负,UP/RANGE 有个别参数转正但**未跨四组一致**。即「只在长周期向上时做」这一假设,在当前出场规则下未获数据支持。
    4. **顺滑度存在弱可辨识信号,但不稳定**:超跌族顺滑 Top 组普遍伴随更深跌幅（`+1.40~+3.01pp`）、同期 BTC 更弱（`−0.98~−2.90pp`）、ATR 更高;突破族仅「ATR 略低」方向一致且幅度极小。属多切片探索所得,**须独立数据验证方可使用**。
    5. **门 B 综合结论**：突破族「有肉」已充分证实（肥尾 + 长窗口延伸）,「够得着」仍未证实（赢家不可辨识 + 路径伴随等量级回撤）。**两族均不具备立即建信号服务的条件,但突破方向的研究价值确立,不得关闭。**
  - **⑥ 追加（2026-08-14 用户问「大利润的回撤相对买入价有多大」,Claude 判定为决策关键缺口）：浮亏与浮盈的联合分布。** 现报告只给 MAE 与 MFE 的**边际分布**（10 天窗口 MAE 中位 `6.3~7.0R`≈买入价 10%,p75 `12.5R`≈20%,p90 `20R`≈31%）,**未给「大赢家自身的回撤」**——而两者含义天差地别:若大赢家 MAE 同样巨大 → 需极小仓位且要求扛住深度浮亏;若大赢家 MAE 很小 → 「顺不顺一进场就看得出」,可直接转化为「早期浮亏超过 X 即放弃」的可执行规则,正面呼应用户「只做顺的」偏好。**必须补的测量（纯诊断,不设门,不碰锁箱）**:① 按 MFE 分桶（`<2R / 2–5R / 5–10R / ≥10R`）分别给出该桶内 **MAE 的分位数（R 与买入价百分比双口径）**;② 同上分桶给出 **MAE 发生在 MFE 之前还是之后** 的比例,以及**入场后前 N 根（N=4/8/16/32）内的浮亏分位**——这直接回答「早期难受能否预测最终失败」;③ 两族、三窗口（1/3/10 天）全给;④ ATR 换算口径写进报告,勿只给 R。
  - **⑥ 验收与判读（Claude，2026-08-14，`6b692db`，报告 v4）：通过,且这是 RB-2 全程信息量最大的一份。** 纪律齐全（锁箱双 false、纯诊断无门、`468 passed`、含 `honesty_boundary` 与「按最终 MFE 分桶使用了未来信息,只衡量可预测性上限」的自我限定）。
    1. **大赢家的回撤显著小于失败者,关系单调**（突破族 10 天窗口,相对进场价）:`≥10R` 桶 MAE 中位 **5.30%**、p75 10.65%、p90 18.45%;`5~10R` 11.00%;`2~5R` 17.84%;**`<2R` 高达 26.18%**。即**走得出大行情的,途中普遍没那么难受**——但「不难受」不等于「不痛」:仍有四分之一的大赢家要扛 10.65% 以上。
    2. **回撤发生的时序也不同**:`≥10R` 桶有 **81% 是「先难受、后走出」**（MAE 早于 MFE）,而 `<2R` 桶仅 7.6%——失败者的大回撤多发生在有限浮盈之后（即冲高后彻底反转）。
    3. **早期浮亏确实带排序信息,且跨参数一致**:进场后前 1 小时 MAE 中位数,`≥10R` **0.74%** vs `<2R` **1.28%**;前 8 小时 1.63% vs 3.99%。方向在突破族 8/8、超跌族 4/4 参数上一致。
    4. **但不能设硬阈值（关键限定）**:分布重叠严重——大赢家前 1 小时 p75 已达 1.34%,高于失败者的中位数 1.28%;p90 更到 2.18%。任何简单切线都会同时留下失败者并错杀赢家。报告未产生、也拒绝产生阈值 X,判断正确。
    5. **超跌族同方向但更弱**:早期两组距离更小、长尾更薄,不提供更清晰的人工判断线。
    **对用户路线的意义**:「只做顺的」在数据上获得**描述性支持**（顺的更可能走远,且早期即有迹象）,但「早期浮亏超过 X 就放弃」**仍无可用阈值**;正确姿势是把早期浮亏作为**前向 paper 记录的采集项**,在未污染数据上检验其样本外排序能力,而非现在就写成规则。
  - **下一步建议（Claude）**：不再在本训练集上做新切片（多重检验已达上限,报告自身亦标注需独立验证）。可行路径两条:**(甲) 用真实前向时间验证**——把「突破 + 长持有/追踪出场」做成 paper 信号在线记录,数月后以未污染数据检验,同时把 RC-1（强势平滑趋势顺势入场）的指标一并采集;**(乙) 直接以 RC-1 为新候选走完整预注册**,用仍封存的锁箱裁决——但须先回答其与 TB4 的重叠度。**Claude 倾向 (甲)**:锁箱只有一次,而 RC-1 的指标设计目前仍缺独立证据支撑。
  - **初步结论（待补齐两项后定稿）**：**门 B 目前也不通过。** 薄尾 + 大赢家不可辨识 = 人工筛选缺乏立足点;「多亏少赢仍打平」的理想猎场结构在本形态上并不成立。补齐筛选力曲线与突破族对照后出最终结论。

### 任务 RB-1：极端超跌反弹 · 出场改造（协议已冻结,交付 Codex,当前唯一优先任务）

**RB-1 Step 1/2 完成记录（Codex，2026-08-14）：完成，锁箱未开。** 新增机器契约 `config/research/rb1_oversold.v1.json`（SHA-256 `af6148d886fdaf6eccd16bc3a67013f2fd47edd99004784d91f08a4c6995a494`），严格继承正式数据指纹、R-0 V2 币池/成本/切分，只展开冻结的 4 个止损与出场组合。训练期四组均使用同一批 6,526 个信号；按“bootstrap 下界→均值→最差年份→事件数→代码”排序，唯一胜出者为 `ST-B__EX-B`：成本后均值 `+0.4379%`、bootstrap 95% 下界 `-0.3032%`、最差年份均值 `-1.3799%`。Step 2 只复核该胜出者：全部信号为 `6,526` 笔、均值 `+0.4379%`、下界 `-0.3032%`；连续第 3 次及以上为 `437` 笔、均值 `+0.7175%`、下界 `-2.7922%`。因下界恶化，按预注册双改善门丢弃序号过滤，最终保留全部信号。机器报告与可读摘要归档在 `docs/evidence/rb1/`。CLI 只提供 `step1/step2`，不存在开箱命令；两份报告均为 `lockbox_opened=false`、`lockbox_data_read=false`。Step 3 仍须独立冻结 commit + Claude 确认，当前不授权锁箱、自动交易或实盘。

**协议**：`docs/design/RB_OVERSOLD_PROTOCOL.md`,状态 `FROZEN`（2026-08-14 用户确认原案,未作修改）。协议即规格,实现不得偏离。

- **交付内容**：
  1. **机器契约** `config/research/rb1_oversold.v1.json`——冻结继承项（数据指纹 `dcb60c95…`、只做多、跌幅 10%、观察窗 16 根、币池、成本、训练/锁箱切分）、4 个候选组合（ST-A/ST-B × EX-A/EX-B）、选参排序、锁箱门六条、纪律标记（`lockbox_access: PROHIBITED`,`grid_size_max: 4`）;契约 SHA 写回协议文档。
  2. **估计器**——在既有 R-0 估计器上扩展出场引擎:`ST-A` 3×ATR14 / `ST-B` 止跌 K 线低点 −0.5×ATR14;`EX-A` 达 1R 移成本后 2×ATR14 追踪 / `EX-B` 达 1.5R 平半仓后追踪;两者均含 32 根兜底时间退出;止损**只许朝盈利方向移动**。
  3. **三步流程分离执行**：`step1`（4 组合训练期评估 + 按冻结排序选唯一胜出者）→ `step2`（在胜出者上对比「全部信号」vs「第 3 次及以后」,输出纳入/丢弃结论）→ `step3`（冻结最终定义为独立 commit,**开锁箱须单独命令且一次性**）。**step3 未经 Claude 确认冻结 commit 存在,不得执行。**
- **必须的测试**：① 追踪止损只上移不下移、移动时点正确;② `R` 定义与 1R/1.5R 触发点计算;③ EX-B 半仓后剩余仓位的收益合成;④ 结构止损取「止跌 K 线」低点的口径无歧义;⑤ 兜底时间退出与止损同根冲突时的优先级（止损优先）;⑥ 跳空按更差价成交;⑦ **锁箱期数据在 step1/step2 中零读取**（fail-closed 专测）;⑧ 网格恰为 4,多一个即拒绝;⑨ 事件与 R-0 同信号定义的一致性（同一批信号,仅出场不同）。
- **验收**：上述测试全过;step1/step2 报告归档 `docs/evidence/rb1/`;全量测试绿 + `MODULAR_BASELINE_PASS`;TB4/LIVE 零触碰;**锁箱未开**。
- **约束**：不得新增候选、不得修改门与排序、不得在训练期新增探索性切片（协议 §7.4）;实现完成后先交 step1/step2 结果,Claude 判读后再决定 step3。
- **验收与判读（Claude，2026-08-14）：实现通过,但结果不支持开锁箱（`f83ee0a`）。**
  - **实现核验全过**：契约 SHA `af6148d8…` 与协议文档一致;`grid_size=4`、`lockbox_opened=false`、**`lockbox_data_read=false`**（step1/step2 均未触碰锁箱,有 fail-closed 专测）;七项测试覆盖网格封顶、与 R-0 同信号引擎仅出场不同、结构止损与 R 定义、追踪只上移、半仓收益合成、跳空取劣价与止损优先于时间退出、锁箱加载器零调用;`453 passed`、`MODULAR_BASELINE_PASS`。
  - **step1 结果（4 组合,各 6,526 事件）**：`ST-A×EX-A` 均值 `+0.779%`/下界 `−0.314`;`ST-A×EX-B` `+0.758%`/`−0.380`;`ST-B×EX-B` `+0.438%`/`−0.303`;`ST-B×EX-A` `+0.356%`/`−0.374`。按协议 §5「下界优先」选出 **`ST-B×EX-B`**（下界 −0.303 最高）。
  - **关键判读:出场改造未产生可信改善,且胜出者劣于 R-0 基线。** 同一信号在 R-0 固定出场下为均值 `+0.626%`/下界 `−0.218`;改造后**四个组合的下界全部更差**（−0.303 ~ −0.380）,胜出者均值亦低于基线（0.438 < 0.626）。机制解释:放宽止损 + 追踪出场提高了单笔离散度,均值小幅上移的同时方差显著上升,统计可信度反而下降。**「更宽止损 + 更聪明出场」这一假设在训练期未获支持。**
  - **step2**：序号过滤**未纳入**——`SEQ_3+` 仅 437 事件,均值 `+0.717%` 但下界 `−2.792`（远差于全量 −0.303）,按协议「均值与下界均须改善」判定丢弃。最终定义回落为「全部信号」。**R-0 阶段「后段更好」的发现在新出场规则下未能复现,原判读中的样本警告成立。**
  - **建议（用户决策）**：**不开锁箱**。理由:锁箱是本项目现存唯一未污染数据、只能开一次,而待验候选在训练期上连「优于原基线」都未做到,拿它去消耗唯一裁决机会不划算。三个可选方向:(甲) 就此收手,超跌方向进墓地,资源回到 TB4 与产品线;(乙) 保留锁箱,先用真实前向时间（paper 信号记录）积累新证据,数月后再定;(丙) 若仍要开箱,须明知「大概率 FAIL 且开完再无干净数据」。**Claude 倾向 (甲) 或 (乙)。**

### 任务 R0-DIAG2：方向与「同向第几次」诊断切片（2026-08-13 用户观察触发,交付 Codex）

**触发**：用户看图后提出「末期的动量突破要过滤掉,特别是空单」。现有冻结报告无方向切片、无「末期」维度,无法回答;故新增两个**纯诊断**切片测量。

- **纪律**：只加测量,**九道门、选参、参数、币池、成本一律不动**;必须复现完全相同的 `TRAINING_FAIL` 与逐组合数值（对照 `docs/evidence/r0/r0_training_v2_20260812.json`,逐字段一致性专测）;锁箱不得触碰;诊断结果**不得**用于本版判定,仅作为下一版预注册的依据。
- **切片一 · 方向**：`LONG` / `SHORT` 分组输出事件数、成本后均值、bootstrap 区间。突破族含多空;超跌族按定义仅 LONG,作完整性对照（若出现 SHORT 事件即实现缺陷）。
- **粒度要求（2026-08-13 用户补充,强制）**：方向切片与序号切片**必须逐层输出到最细粒度**——① 族级汇总;② **每一个定义**;③ **每一组参数**（16 组各自带 `by_direction`,不得只给族级汇总,否则会掩盖「某些参数下空单特别差」的差异）;④ 交叉切片（方向×序号）同样逐参数组合输出。报告结构须让「同一参数下多单 vs 空单」可直接并列读出。
- **图墙同步**：`R0-UI-2` 图库增加**方向筛选**（全部/只看多单/只看空单）,并支持同一组参数下**多空并排对比**;抽样按方向分层,保证空单样本不被多单淹没（每方向各自抽满配额,确定性不变）。
- **切片二 · 同向第几次（「末期」的机械定义,冻结如下）**：
  - 对**同一 symbol、同一方向**,按信号时间排序计数;
  - **两次同向信号间隔 ≤ 96 根 15m K 线（24 小时）** 则序号 +1;间隔 > 96 根**重置为 1**;
  - 出现**反方向信号**时该 symbol 序号立即重置为 1;
  - 分组输出:`SEQ_1` / `SEQ_2` / `SEQ_3` / `SEQ_4_PLUS`,各组事件数、成本后均值、bootstrap 区间;
  - 计数**只使用信号时点之前已发生的信号**,无未来信息;窗口 96 只取此一个值,不做网格（避免多重检验）。
- **交叉切片**：方向 × 序号（如 SHORT×SEQ_4_PLUS）至少输出事件数与均值——用户的假设正是「末期空单最差」,该格子是直接答案。
- **验收**：① 复现门通过（训练判定与逐组合数值逐字段一致）;② 序号计数有单测（含跨 24 小时重置、反向重置、同一时刻多 symbol 独立计数、无未来泄漏）;③ 超跌族无 SHORT 事件断言;④ 交叉切片齐全;⑤ 报告归档 `docs/evidence/r0/`;⑥ 全量测试绿 + 基线 PASS。
- **判读预案（Claude 执行）**：若「SHORT×SEQ_4_PLUS」显著差于整体,则该过滤器进入路线 B 新预注册的候选条件;若无差异,则如实记录并放弃该方向,不再消耗后续精力。
- **验收结论（Claude，2026-08-14）：核心通过,但逐参数切片缺失,打回补齐（`593c822`）。**
  - **纪律核验全过**：独立复现回执 `training_report_exact_match: true`、`verdict=TRAINING_FAIL`、基线 SHA 与本机实测一致;`lockbox_opened=false`、`selection_or_gate_effect=NONE`;序号定义按冻结口径（96 根间隔、反向重置、`uses_future_signals: false`）;全量 `445 passed`、`MODULAR_BASELINE_PASS`。
  - **缺陷（须补）**：`parameter_reports` 仅含 `reproduction`（事件数/均值/匹配标记）,**未包含 `by_direction`、`by_same_direction_sequence` 与交叉切片**,与规格「逐参数组合各自带方向切片」不符。该粒度并非可选——族级把 8 组好坏参数合并（超跌族族级 −0.143% vs 最佳组合 +0.626%）,恰恰掩盖了差异。**要求补齐后重交。**
  - **结果判读（族级,已可下结论）**：
    1. **空单确实全面更差,用户直觉方向正确**:突破族 LONG −0.342% vs SHORT −0.414%,且**每一个序号格子里 SHORT 都劣于 LONG**。
    2. **但「越末期越差」不成立,位置偏了**:最差的是 **SHORT×SEQ_2（−0.501%）与 SHORT×SEQ_3（−0.510%）**,而 SEQ_4_PLUS 反而回升（SHORT −0.377%）;全场最好的格子是 **LONG×SEQ_4_PLUS（−0.280%）**。准确说法是「**第二、三次的空单最差**」。
    3. **该过滤器救不活突破族**:即便最好的格子仍为 −0.280%,过滤掉最差的 SHORT×SEQ_2/3（约 28 万事件、占 17%）后剩余仍深度为负。突破族维持确定性死亡结论。
    4b. **补齐验收（Claude，2026-08-14，`ea0fde3`，报告 v1.1）：通过。** 16 组参数各带 `by_direction` / `by_same_direction_sequence` / 交叉切片;纪律字段不变（`TRAINING_FAIL`、锁箱 false、gate NONE）,`446 passed`。**逐参数结论**：① **空单更差在 8/8 组参数上一致**——每组的「空单第2/3次」都劣于「多单第4次以后」,无一例外,该效应稳健;② **超跌族「后段更好」在 4/4 个跌≥10% 组合上一致**:第1–2 次 vs 第3次及以后分别为 `+0.577%→+1.030%`、`−0.183%→+1.765%`、`+0.470%→+0.750%`、`−0.094%→+0.159%`,**全部为正向改善（+0.25 ~ +1.95pp）**;③ 跌 5% 的四组无论前后段基本仍为负——**极端跌幅仍是不可替代的前置条件**。**样本警告**:后段样本较薄（764 / 3,018 / 1,585 / 7,560）,方向一致性强但绝对水平不可外推;须由锁箱裁决。
    4. **超跌族出现反直觉信号**:SEQ_1 −0.183% → SEQ_4_PLUS −0.049%,**接的刀越多反而越好**（族级合并口径）。若逐参数补齐后在「跌≥10%」组合上仍成立,则「连续超跌的后段」值得进入路线 B 候选条件——与「末期要过滤」的直觉相反,须以数据为准。

**R0-DIAG2 逐参数补齐（Codex，2026-08-14）：已完成打回项。** 原 v1 报告保持不可变，补齐版归档为 `docs/evidence/r0/r0_direction_sequence_diagnostic_v1_1_20260814.json`。报告新增定义级 `definition_reports`，且 16 个 `parameter_reports` 每组都带完整 `slices`：`by_direction`、`by_same_direction_sequence` 含事件数、成本后均值及日块 bootstrap 95% 区间，`direction_by_same_direction_sequence` 含所有 LONG/SHORT × SEQ_1/2/3/4_PLUS 格子的事件数与均值；同一参数下多空可直接并列。逐参数结果确认突破族 8 组全部 SHORT 均值劣于 LONG，SHORT×SEQ_2/3 的恶化广泛存在但不能救活整体。4 个“跌幅≥10%”超跌组合的 SEQ_4_PLUS 均值全部为正（+1.580% / +1.259% / +0.586% / +0.779%），但前三组 bootstrap 区间跨 0；仅“回看 32 根、持有 8 根”组合（`S1_DROP_STABILIZATION:f48a63c80597`）有 4,398 个事件、均值 +0.779%、95% 区间 +0.078% 至 +1.561%，可作为路线 B 新预注册候选线索，不改变本版 `TRAINING_FAIL`，不授权交易或开锁箱。

**R0-DIAG2 完成记录（Codex，2026-08-14）：已完成，原结论保持 `TRAINING_FAIL`。** 新增冻结契约 `config/research/r0_direction_sequence_diagnostic.v1.json`、纯诊断序号分类器和离线执行器；先用 829 个逐币检查点完整复现原训练报告，哈希收据 `docs/evidence/r0/r0_diag2_reproduction_receipt_v1_20260814.json` 记录基线报告、契约及检查点集合哈希，逐字段 exact match，锁箱未打开。正式报告归档为 `docs/evidence/r0/r0_direction_sequence_diagnostic_v1_20260814.json`，覆盖全部 16 个冻结参数组合；序号按同参数、同币种、同方向计算，间隔不超过 96 根递增，超时或反向立即重置，无未来信息。突破族共有 1,583,890 个参数—事件观察值，整体成本后均值 -0.3780%；LONG 790,239 个、均值 -0.3417%（日块 bootstrap 95% 区间 -0.3934% 至 -0.2899%），SHORT 793,651 个、均值 -0.4141%（-0.5110% 至 -0.3131%）。直接检验格 `SHORT×SEQ_4_PLUS` 为 71,525 个、均值 -0.3769%，几乎等于整体，且好于 SHORT 全体、`SHORT×SEQ_2`（-0.5009%）和 `SHORT×SEQ_3`（-0.5101%）；故“末期空单最差”不受支持，不建议将该过滤器带入路线 B。SHORT 整体较 LONG 弱仅记为诊断观察，不改变本版结论或授权交易。超跌族 SHORT 为 0 的 fail-closed 断言通过。

### 任务 R0-UI-2：逐参数组合的信号图墙（2026-08-13 用户要求,交付 Codex,依赖 R0-DIAG）

**目标**：每一组参数都能点开看它的信号长什么样——16 组参数从「16 行数字」变成「16 面可比较的图墙」,用于建立形态直觉、为下一版假设找线索。视觉准绳:`docs/design/PAGE2_MOCKUP.html` 的「研究·信号图库」。

- **后端（只读事件窗读模型）**：给定（策略族, 参数组合, 事件 ID）返回该事件的**K 线窗口**（信号前 N 根 + 持有期 + 之后 M 根,含成交量）与标注点（信号根、进场、止损位、实际出场、最大浮盈点、最大浮亏点）;数据一律取自冻结数据集,纯投影不重算;窗口大小写进契约常量,避免各处不一。
- **抽样纪律（必须确定性）**：单组合事件量可达 25 万,不得全量渲染。按固定种子分层抽样并写进报告:**最赚 N 笔 / 最亏 N 笔 / 随机 N 笔**（N 可配,默认 24）,同一参数组合每次抽到的样本必须一致（可复现）。抽样口径与样本清单随报告归档。
- **前端**：训练结果表每行（一组参数）可点开图墙——缩略图含价格线、均线、同期大盘、成交量（信号根高亮）、进场/止损虚线、出场点、**MFE/MAE 标记**;支持筛选「全部/只看赚的/只看亏的」、按年份/流动性层/诊断切片（量递增、上市年龄）过滤;点缩略图放大看完整窗口。**并排比较**:允许同时打开两组参数的图墙对照（如 跌5% vs 跌10%）。
- **纪律红线**：图墙用于**理解已冻结的结果**与**设计下一版假设**;不得提供任何「据此调本版参数重跑」入口;页面明示「看图产生假设,数据裁决假设」;锁箱期事件**不得进入任何图墙**（锁箱未开,其数据一眼都不能看）。
- **验收**：① 抽样确定性（同参数两次请求样本一致,专测）;② 锁箱期事件被硬过滤（专测:请求锁箱区间返回拒绝）;③ 事件窗口数据与冻结数据集逐根一致（对照测试）;④ 大样本组合不触发全量加载（性能断言）;⑤ 无改参入口（模板断言）;⑥ 人话与状态语言合规;⑦ 全量测试绿 + 基线 PASS。
- **按 R0-DIAG 结果补充的设计要求（2026-08-13,用户选定优先执行）**：
  1. **窗口必须画到出场之后**——右侧至少延伸到 **2 倍持有期**,否则「止损后又创新高」（占止损单 43.4%）这个最重要的现象在图上根本看不见;出场点之后的那段用浅色区分,标明「出场后走势」。
  2. **新增专用分组「止损后又回来」**——与「赚的/亏的」并列的第三个筛选项,直接调出那 43.4% 的样本墙;这是当前最值得用眼睛研究的一类形态。
  3. **每张图标注三个点**：进场、实际出场、**最大浮盈点（含到达用了几根）**;最大浮亏点用浅标记。让「浮盈 4.4% vs 实拿 0.75%」的差距在图上直接可见。
  4. **年份对照**——筛选器含年份,支持并排比较 **2021 与 2022** 同一参数的样本墙（判读指出 2022 的病是「被扫损后回来」,眼睛应能验证）。
  5. 图例与配色沿用 `PAGE2_MOCKUP.html`,不引入新语言。
- **验收结论（Claude，2026-08-13）：通过（`559be32`）。** 逐条核实：① **抽样确定性 + 三层不重叠 + 有界**有专测,16 组合各 72 个样本（最赚/最亏/确定性随机 各 24）,总 1,152,`population_event_count` 最大 29 万但不触发全量加载;② **锁箱硬过滤实证**——全库样本年份仅 2020–2024,`lockbox_opened=false`,契约要求 `lockbox_access=PROHIBITED`,越界事件 fail-closed 有专测;③ **窗口确实画到出场之后**——样例 95 根 K 线中出场后仍有 58 根,`post_exit_start_index` 明确分段,「止损后又回来」现象可见（样本中 141 笔带 `stop_then_recovered_2h=true` 标记）;④ 标注齐全:signal/entry/exit/MFE/MAE 索引与到达根数、`benchmark_return_pct`（同期大盘）、tier/年份/量趋势/上市年龄切片字段;⑤ 「只读取被请求的参数文件」有专测,防一次加载全部;⑥ 前端 `SignalWindowCard` 复用样稿图形语言,无改参入口;⑦ 全量 `437 passed`、`MODULAR_BASELINE_PASS`、`git diff --check` 通过。**归档产物**:`docs/evidence/r0/signal_gallery/`（清单 + 16 个参数样本文件,各带 SHA-256）。

**R0-UI-2 实现记录（Codex，2026-08-14）：完成，待 Claude 验收。** 训练结果 16 行均已增加“看样本”入口；新增冻结只读图库契约与约 6.6 MB 的证据包，每组按固定种子固化最赚 24 / 最亏 24 / 确定性随机 24，共 1,152 个训练期样本，锁箱事件为 0。页面每次只读取单组证据并最多返回 24 个窗口，不在请求时扫描全量事件；窗口含信号前 32 根及进场后 2H，绘制 K 线、成交量、移动均线、同期 BTC、进场/止损/实际出场/MFE/MAE 和浅色“出场后走势”。支持赚/亏/“止损后又回来”、年份、流动性、三日量趋势、上市年龄筛选，支持两组参数并排比较和单图放大；全程无参数编辑或旧协议重跑入口。后端全量 `438 passed`，前端检查与生产构建通过，真实页面验证 16 个入口、专用筛选从 72 个样本正确收窄到 7 个、并排两栏和 18 张过滤后图卡正常，浏览器控制台零错误。

**R0-UI-2 图表可读性修复（Codex，2026-08-14）：** 大图改为可缩放、可横向拖动的一屏行情工作台，弹窗本身不需要纵向滚动；多空方向和实际净收益固定显示在标题区，进场、出场、最大浮盈、最大浮亏压缩为图上方一行摘要。价格 K 线、成交额和同期 BTC 对照带合并到同一 SVG 并共用时间轴；价格轴仅由当前可见 K 线决定，远离行情的止损价不会再压扁蜡烛或制造大片空白。蜡烛区域不再绘制圆形编号、文字标签或贯穿竖线，仅为进出场保留与影线相隔 3px 的微型箭头；鼠标悬停单根 K 线可读取开高低收、涨跌幅、振幅和成交额。生产构建和静态保护测试覆盖“无圆点、无编号轨道、存在微型事件箭头及合并成交量/BTC 副图”。

**R0-UI-2 买卖点补充（Codex，2026-08-14）：** 纯微型箭头辨识度不足，进出场改为绿色“买”和红色“卖”小标签，并用 5px 三角尖端指向对应 K 线。多单按买入→卖出显示，空单按卖出→买回显示；标签根据买卖动作分别置于低点下方或高点上方，不覆盖蜡烛实体。

**R0-DIAG 完成记录（Codex，2026-08-13）：已完成全量诊断，原结论保持 `TRAINING_FAIL`。** 新增冻结补遗契约 `config/research/r0_path_diagnostic.v2.1.json`、只读路径测量器和离线执行器；正式运行先将原训练报告逐字段完整复现，再扫描训练期三个冻结焦点组合，锁箱标记保持 `false`，未读取 2025–2026 数据，未改变九道门、选参、币池、成本或统计。结构化报告归档为 `docs/evidence/r0/r0_path_diagnostic_v2_1_20260813.json`，共记录 8,767 / 7,051 / 15,987 个事件，并输出三组 MFE-MAE 散点图及“浮盈浮亏幅度 + 到达时间”分布图至 `docs/evidence/r0/charts/`。五问的关键事实：① 三组 H 内 MFE 中位数为 3.20% / 4.42% / 3.34%，均明显高于实际净收益均值 0.52% / 0.63% / 0.18%；② 最终盈利事件中，曾承受至少 2% MAE 的占比为 40.2% / 47.0% / 39.6%；③ H 内 MFE 中位到达第 4 / 8 / 9 根，2H 内为第 8 / 15 / 17 根；④ 止损后在 2H 内再创更高 MFE 的占止损事件 34.6% / 43.4% / 45.5%；⑤ 2022 年三组实际均值均为负（-0.68% / -0.97% / -0.78%），同期 MFE 2H 中位数仍有 3.77% / 4.88% / 4.00%，同时 MAE 2H 中位数升至 4.11% / 6.81% / 4.57%，说明问题不是“完全没有反弹空间”，而是逆向波动和路径风险同步扩大。以上仅支持下一版假设或半自动管理研究，不推翻本次训练失败，也不授权交易。路径截断/跳空止损/2H 边界和逐字段复现聚焦测试 `28 passed`。

**战略转向记录（2026-08-12）**：R-0 结果分析的主镜头相应调整——三情形判读中「半自动/人工路线」升为与「全自动路线」同权重的评估对象,核心判据:成本前信号信息量 + 盈亏比散点形态;全自动准入门照旧,不混用。

**项目终局双轨制定调（2026-08-12,用户拍板,详见 `docs/OVERVIEW.md`）**：轨道一=全自动策略（TB4 型,机器决策执行）;轨道二=形态半自动（系统筛信号+**每信号记模拟单**,人低频出手高盈亏比,四硬约束护栏,信号模拟账 vs 人工实盘账拆解「选择增益/管理增益」）。**架构影响**:多账户短线架构中为全自动预设的重基建（阶段 2+ 实时事件仓/全自动调度）在轨道二形态下非必需——R-0 结束后按数据与用户决策定轨,轨道二仅需「信号服务+模拟账账本+留痕日志+对比复盘」,工程量轻一个数量级;相关重建设在定轨前一律不启动。

**目标**：研究页可启动并实时观察 R-0 评估——逐参数组合的进度与结果表,复用 DATA-UI-1 后台任务框架与研究页「实验运行」区设计。

- **改动**：① 估计器加进度上报（当前组合/已完成组合数 16 分母/当前扫描 symbol/已发现事件数）,job 状态持久化、服务重启投影为可续跑;② 训练结果表:逐组合展示事件数、成本后均值、bootstrap 下界、九条门逐项通过状态,**任务状态与研究结论分列**（六维状态语言）;训练完成后显示按冻结顺序自动选出的唯一候选;③ 诊断切片（量递增/上市年龄）结果同屏展示;④ **锁箱按钮强护栏**:仅当训练报告存在且该族训练 PASS 时可用,需输入确认短语,机制上一次性（复用锁箱标记）,开箱后按钮永久变为只读结果;⑤ 与数据任务共用单飞家族锁,进度轮询复用现有机制。
- **两条纪律红线**：**(a) 全程零参数入口**——界面不提供任何修改网格/门槛/币池的控件,运行只有「启动（冻结契约）/取消」两个动作,取消后只能原样重跑,杜绝「跑一半看着不顺眼改了再来」;**(b) 契约指纹前置校验**——启动前展示契约 SHA 与数据指纹并校验,失配拒绝启动。
- **验收**：① 逐组合进度真实（mock 数据推进断言）;② 训练中断续跑与 CLI 结果一致性;③ 锁箱一次性+确认短语+训练未 PASS 不可用（各专测）;④ 零参数入口（模板断言无输入控件）;⑤ 状态语言合规、人话黑名单清零;⑥ 全量测试绿+基线 PASS。**当前正在跑的 CLI 训练不受影响,自然跑完;锁箱阶段起走界面。**

**R0-UI-1 实现记录（Codex，2026-08-12）：完成，待 Claude 验收。** 研究页已接入冻结的 V2 训练与一次性锁箱流程：启动前由后端核验契约 SHA、正式数据指纹和训练/锁箱门禁；任务与 DATA-1R 共用跨进程单飞锁，训练可安全取消，锁箱不可取消且仍由确认短语和永久 marker 保护。估计器按 symbol 原子写检查点并上报扫描合约、事件数和 16 组汇总进度，服务重启后可按同一身份续跑；逐组合结果展示事件数、成本后均值、bootstrap 下界、九项门、唯一候选与两类只读诊断。页面没有参数输入，仅保留冻结训练的启动/停止和训练通过后的一次性确认。当前 06:52 启动的旧 CLI 训练未被中断，并通过兼容状态明确显示“命令行训练后台运行、无逐项进度”，重复启动已在界面和后端双重禁止；后续从页面启动的任务提供完整实时进度。锁箱仍关闭。真实浏览器联调通过；后端全量 `428 tests OK`，前端 `npm run check` 与生产构建通过，`MODULAR_BASELINE_PASS`、`git diff --check` 通过；TB4/LIVE 冻结文件零修改。

### 任务 R-0：短线策略族先行筛查（轨道 A,优先级：高,交付 Codex;**V2 已冻结,训练运行中**）

- **目标**：在平台投入前回答——**突破/动量族**与**超跌反弹族**（15m 信号周期,用户拍板不用更细粒度）扣除保守成本后是否存在正期望迹象。这是筛查不是准入:PASS 只解锁「值得为它建平台并进入组合级回测研究」,不授权任何交易。
- **方法（先预注册后跑数,四护栏全套）**：
  1. 预注册 `docs/design/R0_SHORTLINE_SCREEN.md` 冻结：每族 1–2 个**机械定义**（突破族如「N 周期高点突破+成交额条件」;超跌族如「M 周期跌幅超阈值+企稳确认」）,参数小网格一次写死,禁止事后调;信号在收盘确认、次根可成交价成交;持有/退出规则冻结（含止损、时间退出）。
  2. 币池:用 DATA-1R 的 `universe_at` 时点币池,按流动性分层（含已退市合约——LUNA 类事件必须在样本内）。
  3. 事件采样非重叠;分层与聚合都出统计。
  4. **保守成本模型预注册**：taker 手续费 + 按流动性分层的点差假设 + 冲击缓冲,数值冻结并写明依据;短线族对成本最敏感,成本假设宁严勿松。
  5. 统计门（C8 风格,跑数前冻结）：每族每定义最少事件数、成本后均值为正且固定种子 bootstrap 95% 均值下界 > 0；若把胜率设为辅助门，才对预注册胜率阈值使用 Wilson 95% 下界。聚合过门且不得仅靠单一流动性层/单一年份撑起。
  6. verdict 只追加;FAIL 进候选墓地,不回头调参重跑。
- **判定**：任一族 PASS → 解锁架构阶段 2+;两族 FAIL → 短线平台建设冻结,如实记录。
- **约束**：纯研究,零生产接触;不改 `TB4_SPEC`/LIVE 路径;预注册冻结在任何数据接触之前提交。

**预注册完成记录（Codex，2026-08-11）：协议已冻结，尚未读取信号或收益。** 新增 `docs/design/R0_SHORTLINE_SCREEN.md` 与机器契约 `config/research/r0_shortline_screen.v1.json`（SHA-256 `806752e15bf7bf9ef4472c3e6b33ad7d05bd13804784a565cebc3ea8122a5c04`）。两个策略族各保留一个机械定义、各 8 组小网格：突破/动量使用前序 Donchian 通道与相对成交额，超跌反弹使用冻结跌幅与初步止跌；共同使用下一根开盘成交、`2×ATR14` 止损、真实 Funding 和按历史流动性排名冻结的 `0.16%/0.25%/0.40%` 往返成本。训练期冻结至 2024 年底，2025-01-01 至数据截止为一次性锁箱；统计采用固定种子的 UTC 入场日 block bootstrap，并用逐层/逐年留一后均值仍为正防止单一层或单一年份撑起结论。当前 manifest 因原生聚合校验报告及校验源进入清单，已由初次 COMPLETE 时登记的 `dcb60c95…ca546` 更新为 `5c2404f9…f900a`，质量报告 SHA `f5885005…6638710f` 未变；R-0 明确绑定当前完整 manifest，失配即停止。机器契约哈希门与 5 项静态协议测试已新增；后端全量 `399 tests OK`、`MODULAR_BASELINE_PASS`，TB4 对齐 `9,940` 周期/`237` 次再平衡且两项最大误差为 `0.0`。本提交不实现估计器、不扫描 K 线、不打开锁箱、不产生 verdict，也不修改 TB4/LIVE/运行账本。

**估计器实现记录（Codex，2026-08-12）：实现完成，尚未运行正式训练或锁箱。** 新增纯计算 R-0 估计器、fail-closed 应用编排和离线 CLI：严格展开冻结的 `8+8` 参数网格，实现前序 Donchian/相对成交额、超跌企稳、下一根开盘、简单 ATR14、跳空取劣止损、H 根后开盘退出、同合约非重叠、真实 Funding 边界/多空符号及高/中/低 `0.16%/0.25%/0.40%` 往返成本。统计按 UTC 入场日成组 bootstrap，逐参数输出整体/逐层/逐年/逐合约事件数、均值与区间，并执行冻结的删层/删年门和唯一候选排序。CLI 在任何市场读取前核验契约 SHA、manifest 内容指纹、质量报告与 COMPLETE/缺失/重复条件；训练只打开截至 2024-12 的归档，训练无候选时锁箱 loader 不会被调用；锁箱须显式确认、先以独占 marker 永久认领，再读取 2025-2026 数据，结果文件只允许独占创建。同步收紧 `universe_at` 为“最近连续 7 个完整 UTC 日”，不再跳过缺日偷用更早流动性，并缓存日内稳定排名且单独处理上市/退市的日内边界。新增 19 项合成测试覆盖 §12 义务；联合回归 45 项、后端全量 `420 tests OK`、`MODULAR_BASELINE_PASS`、正式契约/数据只读核验和 `git diff --check` 均通过。未运行 `train`/`lockbox`，未产生任何数值结果或 verdict，锁箱未打开，TB4/LIVE/账本零修改。实现说明见 `docs/design/R0_ESTIMATOR.md`。

**R-0 正式训练结果（2026-08-13 登记，训练于 2026-08-12 完成）：`TRAINING_FAIL`。** 冻结 V2 的 16 组参数已经全部完成训练：突破/动量族与超跌反弹族均未同时通过预注册的九项训练门，`lockbox_authorized_families=[]`，因此锁箱保持关闭且没有读取 2025–2026 一次性检验段。完整机器报告归档为 `docs/evidence/r0/r0_training_v2_20260812.json`，Git 归档字节 SHA-256 `8d5c9681…cfec6`（原始 Windows 产物仅换行不同，SHA-256 `733b864d…f2738`）；应用层重新核验确认其契约 SHA、正式数据指纹与冻结候选选择一致。按预注册裁决，短线平台阶段 2+ 暂不解锁，结果不授权任何交易；若提出新假设必须另立新协议，不得修改本次参数或门槛后重跑。

### 任务 ARCH-1：多策略控制面与数据模型（轨道 B,架构文档阶段 1,交付 Codex）

- **实现状态（2026-08-10）**：代码完成、生产迁移待执行。已新增六张附加表、领域不变量、MySQL 实时只读 repository、TB4 legacy 投影、管理员只读 API 与默认 check-only/显式 `--apply` 的幂等种子脚本。现有 LIVE-SMALL 执行器、控制协议与 TB4 runner 保持 zero-diff；三仓限制仅由 `SHORTLINE_V1` 风险政策强制，TB4 绑定 `LEGACY_COMPATIBILITY` 只读政策且不设三仓上限。
- **验证证据（2026-08-10）**：后端全量 353 项通过；前端 `npm run check` 与生产构建通过；`git diff --check` 通过。MySQL adapter、迁移幂等、冻结哈希、账户唯一激活绑定、管理员 401/403、敏感字段不暴露均有自动化测试。尚未执行真实 MySQL 迁移、并发事务压力测试或生产副本回滚演练，因此不得把 ARCH-1 标记为已部署。

- **范围**（严格限于 `MULTI_ACCOUNT_SHORT_STRATEGY_ARCHITECTURE.md` 阶段 1）：
  1. 新增表与 repository：`StrategyDefinition`、`StrategyEvidenceBundle`、`StrategyInstance`、`AccountStrategyBinding`、`PortfolioRiskPolicy`、`RunnerLease`（租约表先建模,worker 逻辑不在本批）。
  2. TB4 作为 legacy definition **只读导入**,冻结 hash 一字不改;现运行的 LIVE-SMALL 在新模型中登记为该 definition 的唯一 ACTIVE 绑定（投影登记,不改变其运行机制）。
  3. 数据库唯一约束:一个账户至多一条 `ACTIVE/STOPPING` 绑定;先 shadow 校验存量数据无冲突再上约束。
  4. 控制面只读 API:策略目录/实例/绑定列表（复用现有 `/api/strategies` 风格,管理员限定）。
  5. 迁移脚本幂等、可回滚（先扩展后校验,不删旧字段）。
- **TB4 兼容边界**：三仓硬上限属于新短线策略风险政策，不能反向套到冻结的 12 市场 TB4；TB4 只读导入时登记 legacy 兼容政策，不改变 LIVE-SMALL 行为。任何新建的非 legacy 实例必须绑定 `max_open_symbols=3` 的短线政策，禁止借 legacy 标记绕过。
- **验收**：① 唯一绑定约束有测试（含并发插入冲突）;② TB4 导入后 `definition_hash` 与现有 `spec_sha256` 一致性校验;③ **生产行为零变化**——现有全量测试不改一行仍全绿,LIVE-SMALL 执行路径 zero-diff;④ 迁移幂等有测试;⑤ 新 API 管理员限定、匿名 401;⑥ `git diff --check` 通过。
- **约束**：不实现 worker/租约认领逻辑、不建行情基建（属阶段 2+,待 R-0）;不改 LIVE-3 执行器与账本;bounded context 分离。
- **验收结论（Claude，2026-08-10）：通过（`c2174df`）。** 六项验收逐条核实：① 唯一激活绑定为**数据库级守卫**——`account_strategy_bindings.active_account_guard` 生成列（ACTIVE/STOPPING 时取账户 ID 否则 NULL）+ 唯一索引,并发冲突在 DB 层被拒,叠加领域层拒绝测试与 schema 测试;② TB4 只读投影保留双冻结哈希（`test_tb4_projection_preserves_both_frozen_hashes`）,seed writer 写入前校验冻结哈希;③ **生产零变化实证**——`live_execution.py`/`trend_forward.py` 对控制面零引用,既有测试未改一行,全量 `352 passed / 1 skipped`（+13）;④ 迁移为 expand-and-verify:`setup_mysql.py` 幂等建表,迁移脚本默认只校验、显式 `--apply` 才在事务中写投影,重复执行有测试;⑤ 全部控制面 API `require_admin`,匿名 401/业务用户 403 有契约测试;⑥ `git diff --check` 通过。**超规格的好设计（认可）**：三仓政策建模为强制绑定项且**明确不反向套用 TB4**（`test_nonlegacy_binding_cannot_bypass_shortline_policy` + legacy 只读兼容政策）;架构文档同步降级为 `PARTIALLY_IMPLEMENTED` 并如实列出未实现部分,15m 聚合决策同步入文。**部署提醒**：生产 MySQL 尚未执行迁移——下次生产更新窗口跑 `setup_mysql.py` + 迁移脚本 `--apply`;在此之前新表在生产不存在,零影响。

### 任务 DATA-1R：含退市合约的全市场历史数据集 + 时点币池（**已复活并扩展**,轨道 A 首任务,交付 Codex;原 DATA-1 规格 2026-07-31 立项、曾暂缓）

- **实现状态（Codex，2026-08-10）**：工具与真实样本路径已完成，全量数据下载待执行。新增官方 S3 分页/按 symbol 枚举、退市合约保留、15m/Funding checksum 下载与断点续传、1h/4h 完整聚合、每日流动性、合约元数据、无未来 `universe_at`、有界质量报告、确定性 manifest、研究目录登记和持久化原生聚合对照。完整构建要求 `ALL_USDT_PERPETUAL` 索引且所有 15m 分区齐全；`--allow-partial` 样本强制标记 `PARTIAL/history_complete=false` 并被时点币池拒绝。
- **真实样本证据（Codex，2026-08-10）**：Binance 官方归档真实枚举到 LUNAUSDT 15m 与 Funding 各 17 个分区（2021-01～2022-05）；下载 2022-05 单月 15m/Funding 并通过官方 `.CHECKSUM`。1180 根 15m 无缺口/重复，37 条 Funding 在 60 秒时间漂移容差下无缺口；本地聚合 295 根完整 1h、73 根完整 4h 与官方原生归档逐字段零差异。官方 4h 另含 1 根退市前只有 12/16 子根的部分根，本地按冻结规则标记 `INCOMPLETE` 并拒绝研究使用。样本因未下载其余 16 月且索引仅 LUNA，正确为 `PARTIAL`，不构成全量交付证据。
- **验收结论（Claude，2026-08-10）：通过（`148d8f8`,工具级验收;全量下载待执行）。** 四道硬门逐条核实：① **聚合对照**——`test_1h_and_4h_aggregation_are_exact` + 与官方原生逐字段精确比对（含成交笔数字段）,真实样本零差异;② **缺口不静默**——缺子根聚合根标记 `INCOMPLETE` 不可交易,有界缺口计数防时间戳膨胀;③ **时点币池无未来泄漏**——退市时间=末根收盘+1ms,仅用于 `timestamp >= delisted_at` 的排除,流动性只用时点前已收盘日数据（专测）;④ **LUNA 存在性**——退市前在池、退市后不在,真实归档枚举到其 17 个分区实证。加分项：官方 `.CHECKSUM` 校验、断点续传、zip 路径穿越防御、构建幂等+确定性索引、**`--allow-partial` 样本强制 `PARTIAL` 且被时点币池拒绝**（防止拿残缺数据当全量用）、S3 分页枚举保留退市合约。生产隔离实证:执行器/前向/bootstrap 对新模块零引用。全量 `365 passed / 1 skipped`（+13）,`git diff --check` 通过。**最难得的是真实样本证据选了 LUNA 退市月做端到端验证,连「退市周 4h 根只有 12/16 子根」这个真实边角都抓到并正确拒绝——这正是本数据集要防的那类问题的活案例。** 下一步:执行全量下载（本地,预计 8–15 GB）→ 质量报告与 manifest 指纹登记 → R-0 预注册冻结。
- **前端下载控制与复核（Codex，2026-08-10）**：在“策略 → 研究候选”新增“全市场短线研究数据”面板，由管理员显式确认 8–12 GB 后一键执行固定 `index → checksum sync → build` 流程；可选 1–8 并行下载，页面持续显示阶段、进度、当前对象与最终指纹，并支持安全停止和重启续校。所有研究任务共用单一活动任务守卫，接口继续受管理员鉴权保护。浏览器实测确认按钮门禁与控制台零错误；未代用户启动真实全量下载。验收时同时修正正式构建的三项风险：按 symbol 流式处理以避免全市场 K 线常驻内存；索引外本地 15m 分区阻断 COMPLETE；分区内部缺口/重复阻断 COMPLETE。

**扩展（2026-08-10;粒度最终定稿:用户拍板）**：**只下载 15m 一档原始 K 线,1h 与 4h 由本地聚合生成**（OHLCV 标准聚合:首开/最高/最低/末收/量额求和,UTC 边界对齐）。不下 5m/1m。存储量估算 **8–12 GB**。聚合正确性两条硬要求：① **抽样对照测试**——聚合出的 1h/4h 与 Binance 原生归档同 symbol 同月抽样逐根比对,OHLC 与成交量必须精确一致,不一致即数据缺陷阻断;② **缺口不静默**——任一 15m 子根缺失时,聚合根必须标记 `INCOMPLETE` 并计入质量报告,禁止用不完整子集拼整根。聚合结果与原始 15m 同入 manifest 指纹体系。**现有 TB4 冻结 4h 数据集及其指纹不动**——DATA-1R 是研究线独立数据集,不替换生产/已冻结研究数据。其余规格（合约全集枚举、退市元数据、`universe_at` 无未来泄漏、质量报告、LUNA 存在性测试）不变。**连带约束**：R-0 及后续短线研究的信号周期下限为 15m;架构文档 §2.1「底层保存 1m」的目标相应收窄——若 R-0 通过后确需更细粒度,须另行评估立项,不默认下载。

**决策背景（2026-07-31，用户立项）**：后续研究转向形态/事件类与热门轮动类候选,这类研究须扫描「当时市场上的全部合约」。现有数据只覆盖今日存活的 12 主流币,任何全市场扫描回测都会把后来死掉的合约从样本中剔除,造成系统性虚高（幸存者偏差,典型案例 LUNA）。本任务交付**研究基础设施**：不产生信号、不碰 TB4/LIVE 任何路径;第一交付物是数据集+质量报告,不是策略。

- **涉及文件**：`backend/tools/`（新增全市场历史数据获取工具）;时点币池查询（`domain/calibration/` 或独立模块）;研究数据目录登记（复用 UI-P0 只追加目录）;`backend/tests/`;数据落 `var/calibration/`（gitignored）。
- **改动**：
  1. **合约全集枚举**：以 Binance 公开历史归档（`data.binance.vision`,含已退市合约的 K 线/Funding 文件）为主数据源,枚举 USDT-M 永续**历史上出现过的全部**合约;逐合约登记元数据:上市日（首根数据）、退市日（末根数据 + 状态判定）、当前状态。归档为公开 CDN;**可达性已探测（Claude,2026-07-31）:本机 `curl` 该归档返回 HTTP 200（fapi 的 451 不影响它）,全量下载可在本地开发机执行**,工具仍须支持在任意主机独立运行。
  2. **逐合约下载**：全生命周期 4h OHLC + Funding;支持断点续传与增量更新;逐文件 SHA-256 + 数据集级 manifest 指纹;重跑幂等——已有文件指纹不变,新增只追加。
  3. **时点币池查询**：`universe_at(timestamp, min_history_days, ...)` 纯函数——返回 T 时点可交易合约（上市满最短历史、尚未退市）;**只依赖 T 时点已知信息,禁止任何未来数据泄漏**（退市日仅用于判定 `T < 退市日`,不得用于提前剔除「即将退市」的合约）。
  4. **数据质量报告**：逐合约覆盖率、K 线缺口、Funding 完整性;报告 JSON 带哈希,与数据集一起登记进研究数据目录（只追加,预注册可引用指纹）。
- **验收**：① **已知案例存在性测试**——`LUNAUSDT` 等已退市合约必须在数据集与元数据中,且 `universe_at(退市前日期)` 包含它、`universe_at(退市后日期)` 不包含（以数据实际末根为准,测试用例写死具体日期断言）;② 时点函数无未来泄漏有专测;③ manifest 指纹、增量幂等有测试;④ 质量报告生成并登记进数据目录;⑤ 全库不触碰 `TB4_SPEC`、TB4/LIVE 账本与执行路径;⑥ 测试全绿,`git diff --check` 通过。
- **约束**：纯只读研究基础设施;不改动现有 12 币冻结数据集与其指纹;下载工具的网络依赖如实报告（可达性探测结果写进任务完成记录）;数据量大时允许先交付「枚举+元数据+时点函数+抽样下载验证」,全量下载作为可断点续传的长任务在可达主机执行。

### 任务 UI-R2：完整交易系统信息架构（优先级：高，交付 Codex；取代 UI-R1 的四核心+存档结构）

**决策背景（2026-07-31，用户定方向、Claude 定稿）**：用户判定 UI-R1 的「四核心 + 旧网格存档」仍不清晰——系统不应呈现为「新东西 + 旧东西」的拼盘,而应是**一套按交易生命周期组织的完整交易系统**：用户/账户、策略、实盘、复盘、风控集于一身,以策略、实盘、复盘为主线。

**目标导航（五项,无分组、无存档组,按生命周期排序）**：

| 菜单 | 回答的问题 | 内容 |
|---|---|---|
| **实盘**（默认页,id=forward） | 现在一切正常吗？这周执行对了吗？ | 系统健康条、paper 前向进度、冻结清单、自动执行状态与最新报告、持仓核对（现实盘中心,权益对照区移交复盘页,页尾留摘要+跳转） |
| **策略**（id=strategy） | 交易的是什么、为什么可信？下一个候选在哪？ | 两个 Tab：**正式策略**（现策略中心首屏）\| **研究候选**（现研究平台整页,功能零改动,`#research` 重定向到本页该 Tab） |
| **复盘**（新页,id=review） | 过去做得怎么样、和计划差多少？ | ① 实盘 vs paper 归一化权益对照与累计/逐周偏差（自实盘页迁移）;② 逐轮执行报告历史（每轮成功率/逐单状态/滑点/费用,需后端暴露 ROUND_COMPLETED 报告列表,见改动 3）;③ 滑点与成本累计统计;④ 协议检查点——距下次 3 个月加仓评估的时间与 `LIVE_SMALL.md` 1.2 条件清单;⑤ 历史日报 Tab（现报表页内容降权并入） |
| **风控**（重建,id=risk） | 什么情况下停、现在离停多远？ | ① LIVE-SMALL 协议状态:实盘/paper 当前回撤水位 vs 30% 停机线（进度条红区）、停止条件清单、急停状态与急停按钮（与实盘页双入口）;② 自动执行护栏状态（PROTOCOL_STOP/VIOLATION/未完成轮次）;③ 管理员审计日志（急停/恢复/确认等）;④ 旧网格风险数据仅在账户仍有 plan_only 活动时折叠显示 |
| **账户**（id=accounts） | 用户、账户、凭证、同步状态如何？ | 现账户中心,不动 |

- **改动**：
  1. 导航五项如上,删除「旧网格（存档）」组;`DashboardPage/PlansPage/SymbolPage` 退出导航与路由,旧锚点重定向：`dashboard→forward`、`plans→forward`、`symbol→strategy`、`reports→review`、`research→strategy(研究 Tab)`,`events/logs` 顺延;组件文件暂留仓库,实际删除待后续清理批次（UI-R3）确认后执行。
  2. 策略页 Tab 化：包装页承载「正式策略/研究候选」两 Tab,`ResearchPage` 组件整体复用零改动;Tab 状态入锚点（如 `#strategy/research`）以便直达。
  3. **后端小改（唯一新增接口）**：暴露执行报告历史——`GET /api/live-execution/reports?limit=N`（管理员,倒序 ROUND_COMPLETED 报告,复用执行账本 `read_all`,纯只读）;复盘页权益/偏差数据全部复用现有 `live_reconciliation` 快照,不新增其他接口。
  4. 复盘页与风控页按上表重组现有数据,禁止新增任何写路径（急停按钮仍走既有 admin 急停 API）。
- **验收**：① 菜单五项无分组,默认页实盘;② 全部旧锚点重定向逐条测试;③ 研究平台功能在策略页 Tab 下完整可用（筛选/候选切换/job 流程回归）;④ 复盘页权益对照与实盘页原区块数据一致（迁移无失真）,执行报告历史与账本逐轮一致;⑤ 风控页回撤水位与 LIVE-3 `_drawdown_stop` 同源同口径,急停功能回归;⑥ 新接口管理员 only、匿名 401、纯只读有测试;⑦ 后端测试全绿,Windows `npm run check/build` + 桌面/窄屏冒烟;⑧ `git diff --check` 通过。
- **约束**：不改交易行为、`TB4_SPEC`、各账本与 LIVE-3 协议;研究平台四护栏与页面功能零改动（只换挂载位置）;除改动 3 外不新增后端接口;`STRATEGY_CENTER.md` 仍为策略页正式策略 Tab 的设计上限。
- **完成结果（Codex，2026-07-31）**：导航已改为无分组的实盘/策略/复盘/风控/账户五项，默认实盘；旧组件保留但退出路由，八个旧锚点统一在路由入口和 `setActivePage` 内重定向。策略页以 `#strategy` / `#strategy/research` 承载正式策略和完整研究平台，补上登录后研究目录初始化，避免包装页预挂载造成 401 后不重载。复盘页承接原实盘权益对照，新增真实执行报告历史、名义加权滑点、按资产费用汇总和三个月协议检查点；无法解释偏差明确保留人工书面归因，不伪造自动结论。风控页按 LIVE-SMALL 重建，展示双权益回撤、30% 停机线、四项停止条件、执行护栏、急停和管理员审计；旧网格风控仅在启用的 `plan_only` 配置存在时折叠挂载。
- **同源与接口证据（Codex，2026-07-31）**：新增 `live_risk.py` 作为 LIVE-3 停机判断和 `live_reconciliation` 回撤投影的唯一共享计算；精确 30% 边界和缺失基准均有单测。唯一新增接口 `GET /api/live-execution/reports?limit=N` 只读倒序遍历执行账本中的 `ROUND_COMPLETED`，管理员限定，匿名 401、业务用户 403、limit 与不改账本均有测试。没有修改 `TB4_SPEC`、下单路径、账本格式或 LIVE-SMALL 协议。
- **验收证据（Codex，2026-07-31）**：后端全量 `312 tests OK`；`npm.cmd run check` 与生产 `npm.cmd run build` 通过；浏览器确认五项菜单、研究 Tab 加载 4 个真实候选、复盘/风控真实空状态、无归档 DOM，`dashboard/plans/symbol/reports/research/events/logs/live` 八个锚点逐条落到规定新路由，策略内部旧研究按钮也落到 `#strategy/research`。390×844 窄屏下复盘/风控无横向溢出，控制台无 error；`git diff --check` 通过。
- **验收结论（Claude，2026-07-31）：通过（`af59ba3`）。** 逐条独立复核：① 菜单五项无分组、默认实盘,`App.vue` 无归档组与旧页面引用;② 八个旧锚点别名表逐条核对正确（`dashboard/plans→forward`、`symbol→strategy`、`reports→review`、`research→strategy/research`、`events→forward`、`logs→review`、`live→forward`）;③ 研究平台整页复用零功能改动（仅补登录后初始化,修的是包装页预挂载 401 后不重载的真实问题）,Tab 状态入锚点;④ 复盘页承接权益对照并新增执行报告历史/名义加权滑点/费用汇总/协议检查点,「无法解释偏差留人工归因」的诚实边界保留;⑤ **回撤同源为代码级**——执行器 `_drawdown_stop` 与风控页投影同调 `live_risk.py` 单一实现,30% 边界与缺基准专测（`test_live_risk.py`）;⑥ 新接口管理员限定、匿名 401/业务用户 403/limit 钳制/不改账本均有测试;⑦ 本机全量 `311 passed / 1 skipped`（+4,与 Codex 312 口径一致）,`git diff --check` 通过;⑧ 旧页面组件按规格留仓库待 UI-R3 清理。`npm check/build` 系 Windows 侧结果,采信留痕。**至此信息架构定稿为五项生命周期导航,UI-R1 的四核心+存档结构作废。**

### 任务 SC-1～SC-5：正式策略中心（SC-1 定义子集 + SC-2 精简版已实现）

- **决策背景（2026-07-30）**：当前页面能展示 TB4 冻结清单和实盘执行，但没有统一入口解释“当前策略是什么、为什么产生该仓位、历史证据如何”。研究平台仅服务白名单实验候选，执行计划/币种视图仍属于旧双网格，用户容易混淆。
- **正式设计**：`docs/design/STRATEGY_CENTER.md`。新增只读策略中心，分别呈现冻结定义、当前同源信号、结构化回测证据、paper/live 对照与已知风险；研究平台继续负责候选实验，前向实盘继续负责订单与核对。
- **架构要求**：参数从 `TB4_SPEC` 唯一导出；回测指标来自带定义/数据/代码哈希的 `StrategyEvidenceBundle`；当前信号复用冻结 runner，不允许前端重算；定义或证据失配时 fail closed。不得用 Vue 常量、Markdown 抓取或简化公式填充页面。
- **实施顺序**：SC-1 后端策略目录与 evidence bundle；SC-2 首屏与导航；SC-3 当前信号诊断；SC-4 回测图表；SC-5 paper/live 对照。设计任务不改变当前交易行为，后续实现需独立验收。
- **设计评审（Claude，2026-07-30）：通过（`9254453`），实施暂缓待用户排期。** 设计质量高且与项目纪律同构：参数唯一冻结源（`TB4_SPEC` 序列化,前端零副本）、证据 bundle 内容寻址（定义/数据/代码三重哈希）、信号生产同源（禁止前端近似公式,SC-3 与冻结清单恒等测试）、失配 fail closed 不展示可疑数字——这是四护栏精神在展示层的正确延伸；§11 自列上线阻断项诚实。正确回应了旧策略中心被删的根因（静态空壳）,明确不恢复旧实现。**三条评审意见**：① 状态枚举缺并行态语义——系统实际同时处于 `PAPER_FORWARD`（TB4 前向照常计时）与 `LIVE_PILOT`（500 USDT 并行）,单值枚举须定义优先级规则,且 `LIVE_PILOT` 展示时强制附注 paper 前向进度,防止误读为「已从 paper 毕业」；② SC-1 前置条件——TB-R 原始结构化报告在 `var/calibration`（gitignored）,实施前须先确认原报告仍在并与 progress 登记的 SHA-256（`7dd708b5...`）核验一致,否则 bundle 转换无源可校；③ 排期建议——本设计纯认知/证据层,不改交易行为;当前主线是部署与首轮实盘,建议 SC-1 排在 LIVE-SMALL 跑通首个再平衡之后,SC-1~SC-3 先行、SC-4/SC-5 后置。**设计验收不等于开工授权,是否/何时实施由用户决定。**

## 最近验证

- `npm run check` 通过。
- `npm run build` 通过。
- Python 单元测试及 API 契约测试：`312 tests OK`。
- `git diff --check` 通过。
- 新增 POSIX shell 脚本已通过 Git Bash `bash -n` 语法检查。
- Linux AES-GCM vault 已验证随机 nonce、密文篡改/错密钥拒绝、缺失主密钥提示、环境变量引用与平台工厂选择。
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

- **生产身份目录收敛（2026-07-31）**：MySQL 模式已改为用户、账户、策略实例和账户运行配置的权威来源；目录不完整或无有效管理员时启动失败，不再静默回退 `config.local.json`。新增幂等目录迁移命令，保留已有密码哈希并支持业务用户 ID 映射；控制台仅允许管理员登录，业务用户只作为账户归属主体。生产默认密码回退与登录页默认密码提示已移除，新增公开 `/api/health` 并修复健康检查脚本。后端全量 320 项、前端 check/build 通过。
- **凭证加密已跨平台**：Windows 使用 DPAPI，Linux 使用环境主密钥驱动的 AES-256-GCM；`env:` 引用两端均可读取。跨平台迁移已有平台密文时必须重新录入凭证。
- **运维入口已跨平台**：Windows 保留 `.cmd`/`.ps1`，Linux 已补齐 POSIX `sh` 启动、MySQL 检查、健康检查和后端/前端验证入口。
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

页面收敛（2026-07-14）：按产品判断删除无明确独立职责的“策略中心”页面、导航、专用样式和图标；策略运行状态继续由工作台承载，研究证据、执行动作、币种生命周期和风险结果分别进入研究平台、执行计划、币种视图和风控中心。历史 `#strategy/#events` 统一重定向到工作台，后端策略内核与账户绑定数据未删除。

**验收结论（Claude，2026-07-30）：通过（`8e88702`）。** 产品判断成立：三个区块中两块为纯展示（策略卡、只读运行配置表——行内编辑从未建成），唯一写动作是双网格事件参数保存，而双网格已全线 NO-GO 且近半字段本就标注「未生效」禁用。静态核查干净：全前端无 `StrategyPage`/`saveEventConfig`/`#strategy` 残留引用；`LEGACY_PAGE_ALIASES` 新增 `strategy→dashboard`、`events→dashboard` 且 `App.vue` 消费点正常；`event-card`/`event-config-grid` 专用样式与模板同步移除无孤儿类名；后端 `POST /config/events`（`routers/system.py:34`）与账户运行配置 API 均保留未动。后端全量 `279 passed / 1 skipped`。按项目约定 `npm run check/build` 仍待 Windows 侧复验。

验证说明：本轮在 Linux 环境完成（无 node），已做 import/export 交叉验证与 script 块配平静态检查；`npm run check`/`npm run build` 需在 Windows 侧复验。

视觉重做（2026-07-12，应「风格不够大气、页面粗糙」反馈）：
- 整体切换为**深色交易终端设计系统**（`styles/app.css` 全量重写）：深蓝黑表面体系、tabular-nums 数字排版、克制的结构色 + 状态/盈亏专用色、卡片渐变与柔和阴影、sticky 毛玻璃顶栏。
- 品牌升级为 **ORBIT**：轨道环 logo（纯 CSS）、登录页深色渐变 + 轨道环装饰、`index.html` 标题与 `color-scheme: dark`。
- 侧栏重构：运营/策略/治理三分组 + 内联 SVG 线性图标（新组件 `NavIcon.vue`，零依赖）。
- 图表深色适配：轴线弱化；双线图色对 `#19A862/#AD3B48` 与价格线 `#3987E5` 按 dataviz 规范在面板色 `#111B2E` 上做了 CVD（Machado）与对比度校验（CVD ΔE 13.6 通过），并按 relief 规则为多空双线图补图例直标。
- 类名体系保持兼容，页面模板基本未动；已做全模板类名覆盖核对（无缺失）。

### 项目文件与运维

1. 校准产品技术方案中关于配置格式和目录结构的旧描述：当前以 JSON 配置和 `backend/`、`frontend/`、`docs/`、`config/` 顶层结构为准。
2. 跨平台凭证与 Linux/bash 运维入口已在 OPS-1 完成；部署时必须持久、安全地注入 `ORBIT_CREDENTIAL_MASTER_KEY`。
3. 每轮开发完成后更新本文件，避免进度记录滞后于代码结构。

### LIVE-UI 管理控制台（2026-07-31）

- 已将 TB4 前向初始化、主网交易规则刷新、专用账户选择与准备、完整生产预检和 LIVE-SMALL
  激活迁入“实盘”页面，不再要求管理员修改 `config.local.json` 或运行 Python 策略脚本。
- “准备账户”会先检查 Binance 空仓/无挂单，再通过签名接口切换单向持仓并把 12 个市场设置为
  1x；无需在终端或 Binance 页面逐项配置。
- 新增持久化 `live_pilot_control` 状态机；MySQL 模式随 `app_runtime_state` 保存，服务重启恢复。
- 激活要求不可复用 epoch、固定确认短语并实时重跑预检；运行中禁止换账户或覆盖批次。
- 预检覆盖主网、实盘模式、账户同步、单向持仓、500 USDT 权益、冻结清单、规则新鲜度、无挂单、
  无既有持仓、12 市场 1x 杠杆和 Binance 测试订单权限。
- 急停状态已持久化；当前 epoch 永久停止，恢复必须通过页面重新预检并创建新 epoch。
- 后端管理 API 使用严格请求模型并保留审计；前向和规则写入均保持原子、不可覆盖语义。
- 架构与故障边界见 `docs/design/LIVE_PILOT_CONSOLE.md`。
- 验证：后端全量 `330 tests OK`；前端 `npm run check`、`npm run build` 通过。

### LIVE-SMALL V3：3 倍目标风险 + 逐仓 3x（2026-07-31）

- **用户决策**：500 USDT 不变，实盘目标权重固定为原始 TB4 权重的 3 倍；Binance 12 个
  策略市场由全仓/1x 改为逐仓/3x。该变化实质放大盈亏，不是只修改杠杆显示。
- **协议隔离**：TB4 runner、paper 账本和原始目标波动 10% 不变；LIVE-SMALL 投影协议升级
  V3，并同时保留原始目标与 3 倍实盘目标。旧 V1/V2 授权和 epoch 升级后 fail closed。
- **账户准备**：仅在无挂单、无持仓时切换单向持仓、逐仓和 3x；设置后最多回读三次确认，
  自动追加保证金必须关闭。
- **逐轮闸门**：每轮认领订单前重新读取 `/fapi/v1/symbolConfig`；任一市场不是逐仓 3x、
  开启自动追加保证金或配置读取失败，整轮拒绝下单。
- **复盘 UI**：实盘页并列显示 TB4 原始目标与 3 倍实盘目标；复盘页逐币比较原始目标、
  3 倍目标和成交后实际持仓。未放大的 paper 权益差不再被描述为纯执行误差。
- **已知边界**：30% 回撤机制当前只停止后续订单，不会自动平仓；逐仓不构成组合最大损失
  保证。风险调整后的 3 倍理论权益基准尚未独立落账，暂不能用原始 paper 差额替代。
- **验证**：后端全量 `340 tests OK`；前端 `npm run check` 与生产 `npm run build` 通过。

### R0-FIX：稳定数据身份与独立校验证词（2026-08-11）

- **打回缺陷已修复**：manifest 内容身份明确排除 `verification/native/`、`verification_report.json` 与 `attestations/`；原生聚合校验不再重建或改变数据指纹。
- **独立 append-only 证词**：每次 `verify-native` 追加一条 `ORBIT_NATIVE_AGGREGATE_ATTESTATION_V1` 凭证，包含所证明的数据指纹、机器标识、顺序号、结果及自身 SHA；兼容报告只是证词投影，不进入数据身份。正式数据原有 6 组原生校验记录已一次性导入该账本，未丢失历史证据。
- **正式数据一次性迁移完成**：旧指纹 `5c2404f9…f900a` 恢复为首次 COMPLETE 构建登记的稳定指纹 `dcb60c95ecd796e9ade32fcc8bf600a958ba7e88c47a2fdbd7d55569b56ca546`；现场逐项核对 `101,721` 个数据分区，迁移前后哈希完全一致，质量报告 SHA 仍为 `f5885005…6638710f`。
- **R-0 重新锁定**：机器契约已绑定稳定正式指纹，新契约 SHA-256 为 `1e6574850cc13a7cde217ec292c953a36c52a7a24455f3101d13f634faacc8be`；文档与静态哈希门同步更新，并新增“正式数据存在时契约必须与实测 manifest 一致”的 fail-closed 测试。
- **验收证据**：重复校验/跨机器校验指纹不变、证词前缀只追加、迁移零分区变化均有自动化测试；聚焦 `27 tests OK`，后端全量 `401 tests OK`，`MODULAR_BASELINE_PASS`，`git diff --check` 通过。未读取任何 R-0 信号或收益，未打开锁箱，未修改 TB4、LIVE 或运行账本。
## RB-2 v3 长周期机会画像完成记录（Codex，2026-08-14）

- 已按确认后的 v3 契约补齐长周期趋势、顺滑度辨识，以及 96/288/960 根 15 分钟 K 线（约 1/3/10 天）机会画像；正式机器报告为 `docs/evidence/rb2/rb2_long_cycle_v3_20260814.json`，可读报告为 `docs/evidence/rb2/RB2_LONG_CYCLE_V3_REPORT.md`。
- 正式报告覆盖 387 个市场、12 组冻结参数、1,637,351 个“参数 × 信号”样本；仓库标准化后的报告 SHA-256 为 `bd24402f0708bc7d3f024998dedcd010aba1cdc9605e6f78e758e60a28e09f16`，契约 SHA-256 为 `b724ed9b4c671dd1c35ba93b13f85ef3da2c8757efa5632cd17fb040783d088c`。
- 报告逐参数输出：本币 UP/RANGE/DOWN 的最终 R、顺滑度、尾部与频率；MA50 偏离、20/60 日收益及趋势持续时长；方向对齐/不对齐分组；BTC 长趋势分组；按顺滑度 Top 10%/中间 80%/Bottom 10% 重做的八项可观察特征比较；三个长窗口的 MFE/MAE 分位数、2/3/5/10R 触达率、MFE 尾部贡献和到达 MFE 时间。
- 关键判读：突破族 10 天 MFE/R 中位数为 `6.54~7.13R`、触及 10R 比例 `33.5%~36.8%`，但同期 MAE/R 中位数也为 `6.32~7.01R`；本币三种长趋势状态及顺势组的原冻结退出平均最终 R 仍为负。突破方向存在长尾机会，但“事前稳定识别并顺滑持有”尚未成立。
- 超跌族在 DOWN 长趋势下四组平均最终 R 全部为负；顺滑度顶部样本与更深跌幅、更弱同期 BTC、较高 ATR 有较一致的训练期关联，但属于多重切片探索，只能进入新预注册候选，不能直接升级为过滤器。
- 纪律保持：`training_end_ms=1735689599999`，`lockbox_opened=false`、`lockbox_data_read=false`，`selection_or_gate_effect=NONE`；无 PASS/FAIL、无新门槛、无实盘或自动交易授权。扫描用 SQLite 仅为本地计算缓存，不提交版本库。
- 验证完成：RB-2 专项 `10 passed`；后端全量 `464 passed`（仅 2 条既有 Pydantic 弃用警告）；`MODULAR_BASELINE_PASS`；报告结构、契约哈希、样本合计、禁用判定字段及 `git diff --check` 均通过。

## RB-2 v4 浮亏—浮盈联合分布完成记录（Codex，2026-08-14）

- 已按 Claude 追加项 ⑥ 建立独立补充契约 `config/research/rb2_joint_path.v1.json`，没有修改或覆盖 v3 机器报告；正式机器报告为 `docs/evidence/rb2/rb2_joint_path_v4_20260814.json`，可读报告为 `docs/evidence/rb2/RB2_JOINT_PATH_V4_REPORT.md`。
- 覆盖与 v3 完全一致的 387 个市场、12 组冻结参数和 1,637,351 个“参数 × 信号”样本；按突破/超跌两族、96/288/960 根窗口和 `<2R / 2~5R / 5~10R / ≥10R` 四个 MFE 桶，输出全窗口 MAE 的 R/进场价百分比双口径、MAE 与 MFE 的到达先后，以及前 4/8/16/32 根 MAE 双口径。族级与逐参数级均完整保留。
- 关键发现：突破族 10 天 `≥10R` 样本的全窗口 MAE 相对进场价中位数为 `5.30%`，而 `<2R` 样本为 `26.18%`；两组前 1 小时 MAE 中位数分别为 `0.74%` 与 `1.28%`。`≥10R` 组早期 MAE 中位数低于 `<2R` 的方向，在突破 8/8、超跌 4/4 参数及全部三长窗口、四早期窗口中一致。
- 诚实边界：分布仍明显重叠——突破 10 天 `≥10R` 样本前 1 小时 MAE p75/p90 仍为 `1.34%/2.18%`，不能从训练期事后 MFE 分桶直接推导“浮亏超过 X 即退出”的在线规则。当前只确认早期浮亏具有排序关联，不生成 X，不改变任何门、退出或交易定义。
- 纪律保持：`training_end_ms=1735689599999`，`lockbox_opened=false`、`lockbox_data_read=false`、`selection_or_gate_effect=NONE`；中间 SQLite 仅作可恢复计算缓存，不提交版本库。机器报告 SHA-256 `c76ecd064770396c96d7c012fba66b67f32774889532fd800f6392ded40f2c0d`，契约 SHA-256 `53593be593404b45da43fcffba8a1651efcca0b5f6f40ab8b13b0c820d92c9a3`。
- 验证完成：RB-2 联合路径专项 `15 passed`；后端全量 `469 passed`（仅 2 条既有 Pydantic 弃用警告）；`MODULAR_BASELINE_PASS`；正式报告的来源哈希、契约哈希、族/参数/窗口/分桶完整性、样本合计和禁用判定字段均通过自动校验。
