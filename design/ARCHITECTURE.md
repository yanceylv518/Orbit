# Orbit 技术架构与代码组织设计

> 目标态蓝图。原则：架构从一开始就按可模块化、可扩展、清晰分层去建，不因第一阶段功能简单而妥协。
> 本文只定方向与结构，不含逐行迁移步骤。角色定位遵循《PROJECT_PROGRESS.md》产品原则：
> **管理员是平台使用者/操作者；业务用户只是交易账户归属方；策略由平台提供并维护。**

最后更新：2026-07-08

---

## 1. 设计目标与三条扩展轴

系统要能在不改动核心的前提下沿三条轴扩展，这决定了所有抽象边界：

| 扩展轴 | 现在 | 将来 | 承载抽象 |
|---|---|---|---|
| 交易所 | Binance Futures | OKX / Bybit / 现货 | `ExchangeGateway` 端口 + adapter registry |
| 策略与事件 | Dynamic Dual Grid（利润搬运 / 仓位恢复 / 亏损腿减仓） | 更多策略、更多事件类型 | `Strategy` + 可插拔 `EventRule` 流水线 |
| 执行模式 | `plan_only`（只读演练） | `paper`（模拟撮合）→ `live`（实盘下单） | `ExecutionMode` + 可组合 `RiskGuard` 链 |

附带的非功能目标：持久化可事务化、密钥管理跨平台、权限策略单点、后台任务与请求解耦、领域逻辑可脱离框架单测。

---

## 2. 技术选型

| 层面 | 选型 | 理由 |
|---|---|---|
| 后端框架 | **FastAPI** | 类型化 DTO、依赖注入承载 RBAC/事务、自动 OpenAPI、async 适配交易所 I/O |
| ORM / 迁移 | **SQLAlchemy 2.0 + Alembic** | 取代代码里的 ad-hoc `ALTER TABLE`；版本化 schema |
| 校验 / DTO | **pydantic v2** | 请求/响应/配置统一模型 |
| 后台调度 | **APScheduler**（或自管 asyncio task） | tick / 同步 / 报表与 HTTP 生命周期解耦 |
| 数值 | **Decimal 贯穿领域层** | 金额精度；仅在出口 DTO 转 float |
| 存储 | **MySQL 主库** + 可选 **Redis**（会话/缓存/分布式锁） | 会话与运行时快照未来可脱离进程内存 |
| 密钥 | **CredentialVault 端口**（env / DPAPI / 云 KMS） | 消除 Windows-only 锁定 |
| 前端 | **Vue 3 + Vite + TypeScript + Pinia**（目标态） | 组件化、类型对齐 OpenAPI；短期可保留原生 JS，但须按 §7 组件结构组织 |
| 测试 | pytest（unit/integration/api）+ 前端组件测试 | 领域层纯单测，服务层接内存/临时库 |

> 说明：后端从 `http.server` 迁移是刻意的架构决定，不是为技术而技术——RBAC、事务边界、密钥端口、async I/O 这些都需要一个有依赖注入的框架来干净承载。

---

## 3. 分层架构（六边形 / 依赖单向内聚）

```
                 ┌──────────────────────────────────────────────┐
  inbound  ─────▶│  API 层 (FastAPI routers + pydantic schemas)  │  仅做协议转换与鉴权
  (HTTP)         │  deps: 当前用户、PermissionPolicy、UnitOfWork │
                 └───────────────────────┬──────────────────────┘
                                         ▼
                 ┌──────────────────────────────────────────────┐
                 │  应用层 (Application / Use Cases)             │  编排 + 事务边界 + 审计
                 │  AccountService / ExecutionPlanService /      │
                 │  StrategyRuntimeService / SyncService /       │
                 │  ReportingService / AuthService              │
                 └───────┬───────────────────────────┬──────────┘
                         ▼                            ▼
        ┌────────────────────────────┐   ┌────────────────────────────┐
        │  领域层 (Domain, 纯逻辑)   │   │  端口 (Ports, 抽象接口)     │
        │  StrategyEngine / EventRule│   │  ExchangeGateway            │
        │  Planning / RiskPolicy     │   │  StateRepository / UoW      │
        │  实体: User/Account/       │   │  CredentialVault            │
        │  StrategyInstance / VO     │   │  Clock / Scheduler / EventBus│
        └────────────────────────────┘   └───────────────┬────────────┘
                                                          ▼
                 ┌──────────────────────────────────────────────┐
  outbound ─────▶│  基础设施 (Infrastructure / Adapters)         │
  (DB/交易所)    │  SQLAlchemy repos · BinanceGateway ·          │
                 │  DPAPI/Env/KMS Vault · Scheduler runner       │
                 └──────────────────────────────────────────────┘
```

**依赖方向铁律**：`api → application → domain`；`application` 只依赖 `ports`，`infrastructure` 实现 `ports` 并在启动时注入。**领域层不 import 任何框架、DB、网络**——这是能单测、能替换实现的根本。当前 `AppState`（1500 行同时干状态/逻辑/持久化/权限/序列化）正是被这套分层拆解的对象。

| 层 | 职责 | 绝不能做 |
|---|---|---|
| API | 解析请求、鉴权依赖、调用 service、序列化响应 | 写业务逻辑 |
| Application | 用例编排、开启/提交事务(UoW)、写审计、调端口 | 直接拼 SQL / 直接连交易所 |
| Domain | 策略、规划、风控判定、实体不变量 | 任何 I/O |
| Ports | 定义抽象接口 | 具体实现 |
| Infrastructure | ORM 仓储、交易所 SDK、密钥、调度 | 泄漏实现细节到上层签名 |

---

## 4. 核心抽象（端口）

### 4.1 ExchangeGateway —— 交易所可插拔
```python
class ExchangeGateway(Protocol):
    def test_connectivity(self) -> ConnectivityResult: ...
    def fetch_account_snapshot(self) -> AccountSnapshot: ...
    def fetch_positions(self) -> list[Position]: ...
    def fetch_position_mode(self) -> PositionMode: ...
    def place_order(self, order: OrderRequest) -> OrderResult: ...   # live 阶段启用
```
`BinanceFuturesGateway` 实现之；`ExchangeRegistry` 按 `exchange` 字段选 adapter。**加一个交易所 = 加一个 adapter，核心零改动。** 现有 `binance.py` 的 normalize 逻辑收敛进该 adapter，对外只暴露领域 VO（`Position`/`AccountSnapshot`）。

### 4.2 Strategy + EventRule —— 事件可插拔流水线
把引擎从"三个 if 分支写死"改成**优先级排序的规则流水线**：
```python
class EventRule(Protocol):
    name: str
    priority: int
    def evaluate(self, ctx: SymbolContext) -> StrategyAction | None: ...

class StrategyEngine:
    def __init__(self, rules: list[EventRule], risk: RiskPolicy): ...
    def on_tick(self, state, price) -> TickResult:  # 依 priority 跑第一个命中的规则
```
`LossSideReductionRule` / `ProfitTransferRule` / `PositionRecoveryRule` 各自成类并注册。**加事件类型 = 加一个 Rule 类**；同一套 Rule 同时服务模拟撮合（`paper`）与真实持仓规划（`plan_only`），消除现在 `engine.py` 与 `planning.py` 逻辑双写、以及一批"配了没接线"的参数漂移。

### 4.3 RiskGuard 链 + ExecutionMode —— 风控从"只报"到"能拦"
```python
class RiskGuard(Protocol):
    def check(self, action: StrategyAction, ctx) -> GuardVerdict: ...  # allow / block / reduce_only
```
守卫按链执行：`ModeGuard(plan_only/paper/live)` → `ReduceOnlyGuard` → `MaxGrossExposureGuard` → `MaxDrawdownGuard` → `SymbolPauseGuard`。**风控结果进入前置 guard 真正阻断动作**（对应 PROJECT_PROGRESS §21.3 的缺口），而不是只生成风控事件。`plan_only → paper → live` 只是链首 `ModeGuard` 的配置切换。

### 4.4 StateRepository + UnitOfWork —— 事务与读写分离
```python
class UnitOfWork(Protocol):
    accounts: AccountRepository
    strategies: StrategyRepository
    runtime: RuntimeSnapshotRepository   # 覆盖写，一行
    events: EventRepository              # append-only，仅新事件批插
    audit: AuditRepository
    def __enter__/__exit__  # 一个用例 = 一个事务
```
一次落库整体提交，解决现在 `autocommit=True` + 多语句的无原子性问题。**运行时快照（覆盖写）与审计明细（追加写）在仓储层就分离**，不再每 tick 全量 `INSERT IGNORE` 重写历史。时序类数据（`market_snapshots`）归入独立仓储，带保留/降采样策略，或后续外接 TSDB。

### 4.5 CredentialVault —— 跨平台密钥
```python
class CredentialVault(Protocol):
    def protect(self, plaintext: str) -> str: ...
    def reveal(self, ref: str) -> str: ...
```
实现：`EnvVault`（`env:` 引用）、`DpapiVault`（Windows）、未来 `KmsVault`。按平台/配置选择，去掉 Linux 存不了凭证的硬伤。库中只存引用与指纹，绝不存明文。

### 4.6 Scheduler / Clock / EventBus
- `Scheduler`：后台 tick、账户同步、日报生成作为独立注册任务，与 HTTP 生命周期解耦（现在塞在 `AppState.background_loop`）。
- `Clock`：可注入，测试可冻结时间。
- `EventBus`（轻量）：领域事件（策略事件产生、风控触发、急停）解耦审计/通知/报表订阅方，为将来"利润分成、充值提醒"等业务用户侧功能留扩展点。

---

## 5. 后端目录结构

```
orbit/
├─ pyproject.toml
├─ alembic/                      # 迁移脚本（取代代码内 ALTER TABLE）
├─ config/                       # 分层配置：defaults.yaml / <env>.yaml / .env
├─ src/orbit/
│  ├─ main.py                    # 组合根：装配 DI 容器、注册路由与调度
│  ├─ api/                       # 入站适配层（薄）
│  │  ├─ app.py                  # FastAPI factory
│  │  ├─ deps.py                 # current_user / PermissionPolicy / UoW 依赖
│  │  ├─ routers/                # auth, admin_users, accounts, strategies,
│  │  │                          # execution_plans, risk, reports, market, system
│  │  └─ schemas/                # pydantic 请求/响应 DTO
│  ├─ application/               # 用例 / 服务（事务与审计边界）
│  │  ├─ accounts.py  strategies.py  execution_plans.py
│  │  ├─ sync.py  reporting.py  auth.py
│  │  ├─ permissions.py          # PermissionPolicy（权限判定唯一来源）
│  │  └─ unit_of_work.py
│  ├─ domain/                    # 纯逻辑，无 I/O，可独立单测
│  │  ├─ strategy/
│  │  │  ├─ engine.py            # 规则流水线执行器
│  │  │  ├─ rules/               # loss_side_reduction / profit_transfer / position_recovery
│  │  │  ├─ state.py  risk.py
│  │  ├─ planning/               # 基于真实持仓的执行计划（复用 rules）
│  │  ├─ accounts/               # User / ExchangeAccount / StrategyInstance 实体
│  │  ├─ value_objects.py        # Money, Symbol, Qty, Price…
│  │  └─ errors.py
│  ├─ ports/                     # 抽象接口
│  │  ├─ exchange.py  repository.py  credentials.py  clock.py  events.py
│  ├─ infrastructure/            # 出站适配实现
│  │  ├─ db/{models.py, session.py, repositories/}
│  │  ├─ exchange/{base.py, registry.py, binance/}
│  │  ├─ credentials/{env.py, dpapi.py, vault.py}
│  │  ├─ scheduler/runner.py
│  │  └─ audit/
│  └─ telemetry/                 # 结构化日志、指标
└─ tests/
   ├─ unit/          # domain（无需 DB/网络）
   ├─ integration/   # services + 临时库 + fake gateway
   └─ api/           # 路由 + 鉴权
```

**命名边界即职责边界**：看目录就知道逻辑在哪层、能不能有 I/O、改动波及面多大。

---

## 6. 数据与持久化设计

原则：**按数据性质分三类，各用各的写入策略**，而不是每次 mutation 全量重写。

| 数据类别 | 例子 | 写入策略 | 存储 |
|---|---|---|---|
| 运行时快照 | tick_index、symbol_states、当前持仓视图 | **覆盖写一行**（事务 upsert） | MySQL（后续可 Redis） |
| 审计/事件明细 | strategy_events、trade_events、admin_audit_logs、execution_plans | **append-only**，仅在产生新记录时批插 | MySQL 规范化表 |
| 时序指标 | market_snapshots、metric_history | 降采样 + 保留期，或外接 TSDB | 独立表/库 |

配套规则：
- **迁移用 Alembic**，删除代码里的 `ensure_identity_schema/ensure_credential_schema` 在线 `ALTER`。
- **schema 与写入必须一致**：现存 `account_run_configs / execution_plans / risk_events` 三张建了却从不写的表，要么由对应仓储写入，要么删除。
- **不再 blob 与规范化表双写**：运行时快照走结构化仓储；如需整体快照留档，单列 JSON 归档表按需生成，不与事务主路径耦合。

---

## 7. 前端结构与页面/菜单设计

### 7.1 前端目录（Vue 3 + Vite + TS 目标态）
```
web/src/
├─ api/            # 按 OpenAPI 生成/封装的类型化客户端
├─ stores/         # Pinia：auth、runtime、accounts、plans、risk
├─ router/         # 路由 = 菜单，带 role 守卫
├─ layouts/        # AdminConsoleLayout（侧边导航+顶部指标）
├─ pages/          # 每个菜单一个页面容器
├─ components/     # KpiTile / DataTable / EventTimeline / MiniChart / Editor…
└─ styles/
```
> 短期若保留原生 JS：至少把现在 1200 行的 `app.js` 按上面的 `pages/ components/ stores` 拆成多文件模块，render 函数与数据获取分离。

### 7.2 信息架构（菜单）

对齐最初设计图与角色定位。**管理员控制台是主体**；业务用户端为后续独立、数据隔离的第二前台。

**管理员控制台（默认操作者，主导航）**

| 菜单 | 页面职责 | 主要消费 API | 备注 |
|---|---|---|---|
| 总览 Dashboard | 顶部 KPI（总权益/当日盈亏/风控状态）+ 系统策略表 + 币种状态表 + 事件时间线 | `GET /state`、`GET /market/*` | 系统级鸟瞰 |
| 用户与账户 | 业务用户列表；交易账户（所属用户、API 状态、Hedge Mode、同步入口）；API Key/Secret 维护 | `/admin/users`、`/accounts`、`/binance/sync`、`/binance/credentials` | 账户页只承载"用户↔账户↔凭证"，不放策略配置 |
| 策略中心 | 平台策略实例总览；三大事件参数卡片配置；账户挂载与运行配置 | `/strategies`、`/config/events`、`/account-run-config` | **策略是平台维护的**，独立于账户页 |
| 执行计划 | 按账户生成 plan_only 计划；风控检查明细；人工确认；导出（写审计） | `/execution-plans/{generate,confirm,export}` | 第一阶段核心交付 |
| 币种详情 | 顶部币种指标条 + 多空仓位概览 + 图表 + 该币种事件时间线 | `/market/{symbol}` | 从总览/策略钻取进入 |
| 风控中心 | 风控 KPI + 系统风险告警 + 计划风控分类 + 审计日志 + 全局急停/恢复 | `/risk/*`、`/admin/{emergency-stop,resume}` | 急停/恢复仅管理员 |
| 报表 | 日报列表、Markdown 正文、SVG 曲线 | `/reports/*` | |
| 系统设置 | 存储/连接/运行参数展示与部分可配、密钥后端状态 | `/system/*` | 敏感值不回显 |

**业务用户端（后续阶段，`login_required=true` 且非管理员）**

| 菜单 | 职责 | 阶段 |
|---|---|---|
| 我的账户 | 自己名下账户与 API 配置状态（数据隔离） | 早期 |
| 我的持仓 / 权益 | 真实持仓、权益、盈亏（只读） | 早期 |
| 充值手续费 | 手续费余额与充值 | 规划中 |
| 利润分成 / 对账单 | 分成规则与结算明细 | 规划中 |

> 可见性由 §4 的 `PermissionPolicy` 单点裁决：管理员见全量；业务用户仅见自己账户及其派生数据。前端路由守卫与后端 RBAC 用同一套权限定义，避免现在"server 与 app_state 各写一份角色判断"的漂移。

---

## 8. 权限与安全基线

- **RBAC 单一来源**：`PermissionPolicy` 定义 `can(user, action, resource)`；API 依赖注入调用它，前端菜单守卫复用同一份能力表。
- **认证**：会话入 Redis（可跨进程/重启存活）；口令 PBKDF2（保留现有强度）；实盘构建**禁用** bootstrap 默认口令自动初始化。
- **密钥**：仅存引用+指纹；`CredentialVault` 跨平台；快照/DTO 永不回显 Secret。
- **传输/CSRF**：Cookie `HttpOnly + SameSite=Strict`；写操作可加 CSRF token。
- **审计**：所有管理员写操作经应用层统一落审计（含 before/after），与业务写在同一事务。

---

## 9. 运行时与并发

- **调度独立**：tick / 同步 / 报表由 `Scheduler` 管理，非阻塞在请求线程。
- **落库在锁/事务边界外的 I/O 原则**：领域计算在内存完成，持久化经 UoW 事务提交；交易所网络 I/O 一律在事务外。统一现在"有的写路径持锁落库、有的没有"的不一致。
- **async 化**：交易所/DB I/O 用 async，避免线程被网络往返占满。

---

## 10. 可观测性与测试

- **日志**：结构化（JSON），按 request-id / account-id 关联。
- **指标**：策略事件计数、同步成功率、计划生成耗时、风控拦截数。
- **测试金字塔**：
  - `unit/`：domain 规则与风控——纯函数，覆盖策略核心（含现在缺测的 `planning`）。
  - `integration/`：service + 临时库 + `FakeExchangeGateway`，覆盖事务与权限过滤。
  - `api/`：路由鉴权与错误码。
  - 前端组件测试 + 一条 e2e 冒烟。

---

## 11. 扩展场景自检（验证架构是否真的可扩展）

| 需求 | 需要改的地方 | 不该动的地方 |
|---|---|---|
| 接入 OKX | 新增 `OkxGateway` 实现 `ExchangeGateway`，注册进 registry | 领域、应用、API、前端 |
| 新增一类策略事件 | 新增一个 `EventRule` 类并注册优先级 | 引擎执行器、其他规则 |
| 从 `plan_only` 走到 `live` | 配置 `ModeGuard` 放行 + 实现 `place_order` | 规则、规划、风控其余守卫 |
| 上线"利润分成" | 订阅 `EventBus` 的结算事件 + 新增业务用户端页面 | 管理员控制台、策略核心 |

能用"只加不改"回答，才说明边界切对了。

---

## 12. 现状评审与整改优先级

项目尚处早期，适合尽早落这套骨架而非后期重构。下表是对当前实现（`src/ddg/`）的评审结论，按严重度排序，并映射到本文目标解法。严重度定义：**P0 = 走实盘前必须修复**；**P1 = 影响安全/可维护，尽早修**；**P2 = 结构性优化，随重构推进**。

| # | 严重度 | 现状问题 | 位置 | 失败场景 | 目标解法 |
|---|---|---|---|---|---|
| 1 | P0 | MySQL `save()` 多语句 + `autocommit=True`，无事务 | `storage.py:74,353` | 落库中途失败留半写状态，快照与明细不一致 | UoW 单事务提交（§4.4） |
| 2 | P0 | 每次 mutation 全量重写全部 users/accounts/events；且规范化表与 JSON blob 双写，而 `load()` 只读 blob（规范化事件表实为只写） | `storage.py:353-471,560` | tick 越久写放大越重，明细表写入不被应用消费 | 快照覆盖写 / 明细 append / 时序降采样三分离（§6） |
| 3 | P0 | `market_snapshots` 每 tick 每 symbol 插一行，永不清理 | `storage.py:560` | 3s/tick × N symbol，单日数万行无界增长 | 时序独立仓储 + 保留/降采样（§6） |
| 4 | P0 | schema 建了 `account_run_configs / execution_plans / risk_events` 三表，`save()` 从不写 | `sql/schema.sql` vs `storage.py` | 表与写入不一致，数据只在 blob 里 | 由对应仓储写入或删除（§6） |
| 5 | P1 | 角色判断复制四处 | `server.py:288-301`、`app_state.py:330,461,701,787` | 加/改角色要改四处，权限逻辑易漂移 | `PermissionPolicy` 单点（§4、§8） |
| 6 | P1 | `persist()` 在持锁时同步落库，写路径不一致（`tick_once` 锁外，其余锁内） | `app_state.py`（`set_running` 等）vs `:676` | MySQL 往返持锁，阻塞后台 tick 与并发请求 | 锁内改内存、锁外/事务边界落库（§9） |
| 7 | P1 | bootstrap 默认口令硬编码 + 首登自动初始化 | `app_state.py:585`、`config.sample.json` | 实盘残留默认口令即被接管 | 实盘构建禁用该自动初始化分支（§8） |
| 8 | P1 | 凭证加密 DPAPI，仅 Windows | `binance.py:57` | Linux 存 API Key 抛 `CredentialError` | `CredentialVault` 跨平台端口（§4.5） |
| 9 | P2 | `AppState` 1500 行巨类：状态+逻辑+持久化+权限+序列化+双模式分叉 | `app_state.py` | 双模式 `if mock_data_enabled` 散落全类，难维护 | 拆 domain / application / infrastructure（§3、§5） |
| 10 | P2 | `engine.py`（模拟撮合）与 `planning.py`（真实规划）三大事件逻辑双写 | `engine.py`、`planning.py` | 改一处策略要同步两处，易不一致 | 统一 `EventRule` 流水线，两模式共用（§4.2） |
| 11 | P2 | 风控只生成事件、不阻断动作 | `engine.py:117` | `MAX_SYMBOL_DRAWDOWN`/`ONLY_REDUCE` 形同虚设 | `RiskGuard` 链前置阻断（§4.3；策略侧另见 PROGRESS §21.3） |
| 12 | P2 | 一批 config 旋钮建了没接线 | `skip_if_price_extended_pct_from_base`、`min_position_distance_pct_from_base`、`target_price_distance_pct_from_base`、`max_total_drawdown_pct` | 调参者以为生效，实则无效 | 随 `EventRule`/`RiskGuard` 实现或从配置删除（§4.2/§4.3） |
| 13 | P2 | HTTP handler 无统一异常兜底，非法 JSON 抛 500 traceback | `server.py:255` | 畸形请求泄漏堆栈 | API 层统一异常处理器（§3 API 层职责） |
| 14 | P2 | `planning.py` 无直接单测（仅经 app_state 间接覆盖）；前端仅 `node --check` | `tests/` | 第一阶段核心交付缺回归保护 | 测试金字塔补 domain 单测（§10） |

> 代码内 `ALTER TABLE`（`ensure_identity_schema`/`ensure_credential_schema`）→ 迁移统一走 Alembic（§6），随 #1–#4 一并处理。
> 策略逻辑本身的缺口（趋势生命周期不重置、亏损腿补不回等）不在本表，见 `PROJECT_PROGRESS.md` §21。

### 建议采用顺序

1. 立目录骨架与端口接口（`domain/ports/application` 空壳），固化边界。
2. 迁 `domain` 规则为 `EventRule` 流水线并补单测（消 #10、#12、#14）。
3. 接 FastAPI + `PermissionPolicy` + UoW + Alembic（消 #1、#5、#6、#13，落 §6 持久化三分离消 #2–#4）。
4. `CredentialVault` 跨平台与实盘口令加固（消 #7、#8）。
5. 再谈前端组件化（§7）。
```
