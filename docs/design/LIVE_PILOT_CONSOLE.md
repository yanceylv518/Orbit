# LIVE-SMALL 管理控制台设计

版本：2026-07-31（V2：授权布防与订单触发解耦）

## 1. 目标与边界

本能力把 TB4 前向初始化、交易规则刷新、实盘账户准备、生产预检与自动执行激活收敛到管理员
控制台。它替代生产环境中的手工脚本和运行时配置编辑，但不提供任意命令执行、策略参数修改、
账本覆盖或绕过预检的入口。

部署软件、安装依赖、配置数据库和注入凭证主密钥仍属于服务器运维，不属于策略运行控制。

## 2. 状态机

```text
DRAFT
  ├─ 选择账户 ─> CONFIGURED
  └─ 初始化前向 ─> FORWARD_READY

CONFIGURED / FORWARD_READY
  ├─ 初始化前向、刷新规则、准备账户
  └─ 全部预检通过 ─> PREFLIGHT_READY

PREFLIGHT_READY
  ├─ 清单未生成 + 新 epoch + 确认短语 + 再预检 ─> ARMED
  └─ 清单已就绪 + 新 epoch + 确认短语 + 再预检 ─> ACTIVE

ARMED
  └─ 首份冻结清单就绪 ─> ACTIVE（逐轮闸门决定是否实际下单）

ACTIVE
  └─ 管理员急停或机制停机 ─> STOPPED

STOPPED
  └─ 重新预检 + 新 epoch ─> ARMED / ACTIVE
```

状态只是工作流投影，不能替代每次激活时的实时预检。激活接口无条件重新执行账户安全预检。
`ARMED` 表示管理员已经授权未来的合规清单自动执行，不表示已经产生订单；清单就绪后仍必须
通过每一轮运行时闸门才能下单。

## 3. 持久化与运行时

- `live_pilot_control` 保存在生产运行时存储；MySQL 模式写入 `app_runtime_state`。
- TB4 paper manifest/events 使用 `var/forward/tb4/` 的不可变、只追加账本。
- LIVE-SMALL 订单和执行报告使用 `var/forward/live-small/` 的只追加账本。
- 交易规则快照写入 `var/forward/live-small/tb4_exchange_rules.json`，采用临时文件后原子替换。
- 初始化已有 manifest 时只读取并返回哈希；空目录可接管，非空目录拒绝覆盖。
- 急停同时关闭内存执行器并持久化 `STOPPED`，服务重启不会恢复旧批次。

## 4. 管理 API

所有接口均要求已登录管理员，同源会话鉴权，并写管理员审计日志：

| 接口 | 作用 | 关键护栏 |
|---|---|---|
| `POST /api/admin/live-pilot/configure` | 选择专用账户 | ACTIVE 时拒绝换账户 |
| `POST /api/admin/live-pilot/initialize-forward` | 初始化冻结前向 | 不覆盖既有账本 |
| `POST /api/admin/live-pilot/refresh-rules` | 刷新主网规则 | 原子写文件 |
| `POST /api/admin/live-pilot/prepare-account` | 检查空仓/无挂单，设置单向持仓与 12 市场 1x，再保存主网实盘属性 | 要求 `PREPARE LIVE ACCOUNT` |
| `POST /api/admin/live-pilot/preflight` | 执行生产预检 | 账户安全检查任一失败则 fail closed；信号清单可等待 |
| `POST /api/admin/live-pilot/activate` | 授权并布防自动执行 | 新 epoch、`ENABLE LIVE SMALL`、重新预检 |
| `POST /api/admin/live-execution/emergency-stop` | 停止新增订单 | 当前 epoch 永久锁定 |

请求体使用严格模型，未知字段被拒绝。页面不接收、保存或回显 API Secret；凭证继续由账户中心
通过平台凭证库管理。

## 5. 生产预检

激活所需的账户安全检查：

1. 已选择且处于 active 的 Binance 合约账户；
2. 主网、`dry_run=false`；
3. 最近一次账户同步成功；
4. Binance 实际为单向持仓；
5. 合约钱包权益不少于冻结的 500 USDT；
6. TB4 前向已初始化；
7. 交易规则存在且未过期；
8. 账户没有未完成挂单；
9. 12 个策略市场没有既有持仓；
10. 12 个策略市场杠杆均为 1x；
11. 使用清单数量，或基于实时价格和交易规则计算的最小合规数量，通过 Binance
    `/order/test` 权限检查。该接口只校验参数与权限，不创建订单。

冻结清单 `READY` 是订单触发条件，不是管理员授权条件。尚未生成首份清单时，该项显示为
“等待”，预检仍可通过并进入 `ARMED`；清单生成后系统才进入执行轮次。

杠杆配置必须通过 Binance `/fapi/v1/symbolConfig` 回读。不得使用
`/fapi/v3/positionRisk` 验证空仓市场，因为官方定义该接口只返回存在持仓或挂单的交易对。

预检只证明当前时点满足执行条件。每一轮真实执行仍继续经过快照新鲜度、清单映射、数量精度、
单笔名义金额、幂等执行账本和回撤停机等运行时护栏。

## 6. 故障语义

- 网络、Binance、凭证、规则或持久化失败均不允许布防。
- 账户准备在无挂单、无持仓时才允许修改 Binance 持仓模式；12 市场设为 1x 的任一步失败均
  返回失败并要求重试，不会静默跳过。
- 并发激活请求不能覆盖已激活批次。
- 执行器参数先完整校验再原子应用，避免半更新。
- 激活持久化失败时立即撤销内存启用。
- 非空前向目录、损坏账本、未完成轮次或未知订单状态必须人工调查，不允许删除状态后重试。

## 7. 验收证据

- 后端单元与 API 契约测试覆盖控制状态、epoch 校验、确认短语、空目录初始化和管理员权限。
- 前端静态检查与生产构建必须通过。
- 首次生产启用前仍需在真实服务器页面保存以下证据：完整预检结果、manifest 哈希、规则刷新
  时间、执行 epoch、管理员审计记录，以及第一轮理论清单与实际订单/成交对账。
