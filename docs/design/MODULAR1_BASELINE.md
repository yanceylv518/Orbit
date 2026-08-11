# MODULAR-1 实施基线

状态：`ACTIVE_BASELINE`  
基线来源：`c5ed5cf9d2e283d9af6fa0279ec080d68652fdad`  
最后更新：2026-08-11

## 1. 用途

本文是 `SYSTEM_MODULE_REDESIGN.md` 的 MOD-0 交付物。它只记录重构开始前可复核的导航、API、代码归属和 TB4 保护基线，不改变任何产品或运行行为。

机器可读基线位于 `config/architecture/modular1_runtime_baseline.v1.json`，只读验证入口为：

```powershell
.\.venv\Scripts\python.exe backend/tools/verify_modular_baseline.py
```

生产/前向主机必须额外验证真实 Paper manifest 与哈希链：

```powershell
.\.venv\Scripts\python.exe backend/tools/verify_modular_baseline.py `
  --runtime-dir var/forward/tb4 --require-runtime
```

工具不写 manifest、events 或任何运行状态。未初始化 TB4 的开发机默认只验证静态冻结规格和受保护文件；生产验收不得省略 `--require-runtime`。

## 2. 重构前导航

当前一级导航及页面组件：

| 路由 | 页面 | 当前混合职责 |
|---|---|---|
| `forward` | `ForwardPage.vue` | TB4 Paper、Live准备、目标仓位与执行状态 |
| `strategy` | `StrategyPage.vue` | 正式策略与研究候选两个Tab |
| `review` | `ReviewPage.vue` | Paper/Live权益、订单和持仓复盘 |
| `risk` | `RiskPage.vue` | 风险状态、预检、急停 |
| `accounts` | `AccountsPage.vue` | 用户、账户、凭证与同步 |

`StrategyPage.vue` 内部现状：

```text
正式策略 -> StrategyCenterPage
研究候选 -> ResearchPage
              ├─ 候选预注册与结果
              ├─ DATA-1R任务
              ├─ 单市场数据拉取
              └─ 混合任务历史
```

MOD-1 目标导航固定为：`数据 / 研究 / 策略 / 实盘 / 复盘 / 风控 / 账户`。执行首期保留为实盘二级职责。

## 3. 重构前API

| Router | 前缀/主要入口 | 当前目标模块 |
|---|---|---|
| `auth.py` | `/api/auth/*` | Accounts/Shell |
| `accounts.py` | `/api/admin/users`、`/accounts`、`/account-run-config` | Accounts/Runtime |
| `binance.py` | `/api/binance/*` | Accounts/Execution adapters |
| `research.py` | `/api/research/datasets|candidates|runs|results` | Data + Research + Jobs |
| `strategies.py` | `/api/strategies/*` | Strategy |
| `strategy_control.py` | `/api/strategy-control/*` | Strategy + Runtime + Risk |
| `execution_plans.py` | `/api/execution-plans/*` | Execution |
| `system.py` | `/api/health`、`/api/admin/live-pilot/*`、运行控制 | Shell + Runtime + Risk + Review |

MOD-1 只重新组合前端，不改上述API。API拆分从MOD-2开始，并保留兼容适配器。

## 4. 当前代码归属

| 当前代码 | 当前事实/副作用 | 目标归属 |
|---|---|---|
| `application/research/catalog.py` | JSON缓存、DATA-1R manifest、候选、结果的混合目录 | Data + Research |
| `application/research/runs.py` | 数据任务、数据拉取、实验任务 | Data/Jobs + Research |
| `application/shortline_dataset.py` | DATA-1R构建编排 | Data |
| `domain/calibration/shortline_dataset.py` | 历史数据模型与聚合质量 | Data domain |
| `application/strategy_catalog.py` | TB4冻结策略只读投影 | Strategy |
| `domain/strategy/trend_basket_runner.py` | TB4冻结spec与runner | Strategy spec + Runtime kernel |
| `application/trend_forward.py` | TB4 Paper前向 | Runtime |
| `application/live_execution.py`、`order_execution.py` | Live清单与订单副作用 | Execution |
| `application/live_risk.py`、`domain/risk` | TB4/账户风险判定 | Risk |
| `application/portfolio_views.py` | 跨模块只读展示投影 | Review/Shell queries |
| `application/app_state.py` | 兼容状态与跨模块入口 | Legacy facade/composition |
| `frontend/src/stores/appStore.js` | 全局认证、导航与全部业务状态 | Shell + 模块store |

## 5. TB4冻结基线

机器基线固定：

- spec SHA-256：`f74db0b9f9c8018ffb21ecdc5a0f1fbb6d615704f291f9b72f478ed62bfc56ed`
- definition hash：`3207b10f98382254a308dc07f133718f0c33615dce55c358dc5e03ef5bae6753`
- Paper协议、LIVE-SMALL协议、runner、前向、执行、订单和风险关键文件 SHA-256：见机器基线JSON。

环境运行事实不能写成仓库全局常量。每个已初始化环境必须在部署前后分别记录：

- Paper `manifest_sha256`；
- Paper事件数量与哈希链head；
- Live执行账本文件hash、记录数和尾记录hash；
- 当前market cursor；
- 当前TB4原始目标与3倍目标清单hash。

前后快照必须一致或只出现由正常新行情/成交产生的可解释只追加变化，不能截断、重建或重排。

## 6. 统一术语

| 术语 | 唯一含义 |
|---|---|
| 数据版本 | 一组不可变分区、截止时间、质量报告及其fingerprint |
| 数据快照 | 某实验从一个数据版本中冻结的市场、区间和分区hash |
| 研究假设 | 可被数据支持或否定的陈述，不是交易策略 |
| 实验定义 | 跑数前冻结的数据快照、方法、成本和门槛 |
| 任务状态 | 程序是否排队、运行、成功、失败或取消 |
| 研究结论 | `SUPPORTED/NOT_SUPPORTED/INCONCLUSIVE/INVALID` |
| 策略定义 | 含信号、退出、仓位、成本和证据的冻结交易规则 |
| 运行实例 | 某个策略定义在Paper或Live环境中的独立运行状态 |
| 目标仓位 | runner发布的期望组合，不等于已成交持仓 |
| 执行结果 | 订单和成交事实，不等于策略研究结论 |

## 7. MOD阶段通用验收命令

每个MOD阶段至少执行：

```powershell
.\.venv\Scripts\python.exe backend/tools/verify_modular_baseline.py
.\.venv\Scripts\python.exe backend/tools/verify_tb4_alignment.py `
  --tb1-training-report var/calibration/tb1_trend_basket_training_corrected.json `
  --tb1-training-report-sha256 f863f39ec4445802bc727c0c052a81763ad2c2afd29c667e58fcd48e11f1abe8 `
  --json-output var/calibration/tb4_runner_alignment_modular1.json
.\.venv\Scripts\python.exe -m unittest discover -s backend/tests
cd frontend
npm.cmd run check
npm.cmd run build
```

`verify_tb4_alignment.py` 需要本地12市场TB1历史数据。生产发布还必须运行带 `--require-runtime` 的基线检查并比较部署前后运行快照。

## 8. MOD-0完成门

- 当前导航、API和代码归属已记录；
- TB4 spec、definition、协议和关键执行文件已有机器校验；
- 开发机可只读核验已存在的TB4 manifest与事件哈希链；
- DATA-1R任务故障不能修改兄弟目录中的TB4 manifest或events；
- 统一术语已固定；
- 全量后端测试、前端check/build、TB4对齐和diff检查通过；
- 生产环境manifest/账本快照留待部署主机执行，不能用开发机“未初始化”冒充通过。
