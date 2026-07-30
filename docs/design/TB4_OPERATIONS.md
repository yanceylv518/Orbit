# TB4 前向测试操作手册（Runbook）

版本：2026-07-30（V2：并入 LIVE-SMALL 自动执行部署；判定纪律不变）
适用对象：平台管理员（自用）

---

## 0. 先读：当前状态与两条铁律

**状态**
- ✅ **冻结策略已实现并逐笔对齐通过**（TB4-A）：`FrozenTrendBasketRunner`，与通过 TB-R 的 offline 系统逐笔零误差一致。
- ✅ **持续运行的后端前向启动器已实现**（TB4-B）：尚未在 Binance 可达主机执行初始化，因此真实前向计时仍未开始。
- ✅ **LIVE-SMALL 小资金实盘自动执行已实现**（LIVE-1/2/3）：与 paper 前向**并行**运行，受 `LIVE_SMALL.md` V2 协议管辖（初始 500 USDT 冻结、加仓/停止规则预注册、回撤 30% 机制停机）。

**两条铁律（贯穿始终）**
1. **必须跑在 Binance 可达网络**：本仓库开发机访问 `fapi.binance.com` 返回 451（区域封锁）。前向必须部署在你自己能连 Binance 的机器上。
2. **启动后什么都别动**：不调参数、不提前下结论、不因早期波动改变任何冻结项。前向测试最大的敌人是手贱。
   - **与小资金实盘的关系（澄清,避免误读）**：按 `LIVE_SMALL.md` V2,500 USDT 小资金实盘与 paper 前向并行,这**不是**"提前上真钱"的违规——它有自己的预注册协议;其规模只能按协议 1.2（满 3 个月按条件加仓）/1.3（停止规则）变更,**不得**因 paper 前向早期表现好而加钱。TB4 paper 的 12 个月判定纪律不受实盘并行影响,两本账各自独立。

---

## 1. 环境准备（一次性）

1. **机器**：能正常访问 `https://fapi.binance.com`（浏览器或 `curl` 能通）。
2. **Python**：3.10+。
3. **拉代码**：
   ```
   git clone <你的 Orbit 仓库>
   cd Orbit
   ```
4. **依赖**：本项目运行时刻意精简（标准库为主）。可选 MySQL 持久化需 `pip install PyMySQL`；不装则用本地 JSON 兜底。
5. **（可选）MySQL**：长期前向建议用 MySQL 持久化，避免进程重启丢状态。见 `README.md` 的 MySQL 接入步骤。
6. **凭证主密钥（实盘自动执行必需）**：Linux 上保存实盘账户 API Key/Secret 需要 `pip install cryptography` 并持久注入环境变量 `ORBIT_CREDENTIAL_MASTER_KEY`（生成方式见 `README.md` / `generate_vault_key.py`；或改用 `env:` 引用直接从环境读取凭证）。不配置则实盘账户凭证无法保存,自动执行无法启用;仅跑 paper 前向可跳过本步。

---

## 2. 现在就能做：验证「你机器上的系统 = 通过验证的那个」

这一步至关重要——**在信任任何前向结果之前，先确认你机器上跑的实现和通过 TB-R 的一字不差。**

1. **拉历史数据**（12 市场 4h OHLC + Funding）：
   ```
   python backend/tools/fetch_klines.py --ohlc   # 具体参数见 --help
   python backend/tools/fetch_funding.py         # 具体参数见 --help
   ```
   宇宙固定为：`BTC ETH BNB SOL XRP DOGE ADA LINK AVAX DOT LTC BCH`（USDT 永续），周期 `4h`。数据落在 `var/calibration/`（已 gitignore）。

2. **跑逐笔对齐校验**：
   ```
   python backend/tools/verify_tb4_alignment.py   # 参数见 --help，传入上面各市场数据集
   ```
   **期望结果**：`TB4_ALIGNMENT_PASS`，最大净收益误差 `0.0`、最大权重误差 `0.0`。
   - 若不是 0.0：**停**。说明你的数据或环境和验证时不一致，别启动前向。

3. **含义**：拿到 `ALIGNMENT_PASS` = 你机器上的冻结 runner 与 TB-R 验证过的 offline 系统逐笔相同。这是前向可信的地基。

---

## 3. 冻结系统规格（**任何一项都不可改**）

| 项 | 值 |
|---|---|
| 宇宙 | 12 个 USDT 永续（见上） |
| K 线周期 | 4h |
| 动量信号 | 多周期集成：lookback `14 / 28 / 56 / 84 / 168` 天，各占 20%，`ensemble_signal = 5 个符号的均值` |
| 仓位 | 按 `vol28`（28 天波动）定仓，目标组合年化波动 `10%`，gross cap `1.0` |
| 再平衡 | 每 `7` 天，下一根 K 线执行 |
| 成本 | 往返 `0.14%` + 真实 Funding |
| 模式 | **paper（纸面）**，不下真单 |

代码位置：`backend/src/orbit/domain/strategy/trend_basket_runner.py`（参数为模块常量、`frozen` dataclass，**无公开旋钮**）。

---

## 4. 前向判定标准（预注册、冻结，见 `TB4_FORWARD.md`）

- **最短运行期**：≥ 12 个月（需形成完整的滚动 12 个月分布）+ 缓冲。
- **中途检查点**：只报告运行健康/数据完整性/当前指标，**不作 PASS/FAIL**。
- **最终判定**：用 TB3 同一套冻结门——净收益 >0、最大回撤 ≤30%、Calmar ≥0.5、Sortino ≥0.7、最差滚动 12m ≥−30%、正滚动 12m 占比 ≥55%、最长回撤 ≤18 个月。
- **前向期间参数只读、不可变。**

---

## 5. 启动并运行前向

在 Binance 可达主机、仓库根目录先做一次初始化：

```bash
python backend/tools/run_tb4_forward.py --initialize --once
```

该命令会拉取 12 市场共同连续的 1,009 根 4h 收盘进行暖机，锁定下一根收盘为前向起点并写入不可变清单。

生产运行时由 Orbit 后端充当 **唯一 TB4 轮询与自动执行 writer**。在 `config.local.json` 的
`runtime.trend_forward` 中设置：

```json
{
  "enabled": true,
  "live_account_id": "专用实盘账户 ID",
  "exchange_rules_path": "var/forward/live-small/tb4_exchange_rules.json",
  "auto_execution_enabled": false,
  "auto_execution_epoch": "",
  "execution_ledger_path": "var/forward/live-small/executions.jsonl",
  "max_snapshot_age_seconds": 120,
  "max_order_notional_usdt": 150,
  "round_gross_multiplier": 1.1
}
```

先以 `auto_execution_enabled=false` 启动后端，完成清单、账户同步、规则快照和页面状态核对。
先刷新主网市价单规则，并把输出路径写入配置的 `exchange_rules_path`：

```bash
python backend/tools/fetch_tb4_exchange_rules.py
```

确认账户为 Binance 主网、`dry_run=false`、单向持仓模式、人工设置 1x 杠杆且 API Key
只有合约交易权限（禁止提现、设置 IP 白名单）后，使用新的不可复用 epoch（例如
`live-small-2026-08-01-v1`）并把 `auto_execution_enabled` 改为 `true`，再重启后端。

启用后不要再并行运行持续版 `run_tb4_forward.py`；工具会在检测到
`trend_forward.enabled=true` 时拒绝成为第二个 writer。TB4 paper 账本默认位于
`var/forward/tb4/`，实盘执行账本默认位于 `var/forward/live-small/`。两者都必须持久化并备份。
平台快照分别以只读字段 `trend_forward`、`live_execution` 暴露进度和逐单报告。

自动执行规则以 `LIVE_SMALL.md` V2 为准：同一再平衡至多执行一次；失败不追单；急停后当前
epoch 永久锁定，只能修改 epoch 并重启后再启用。账本损坏、存在未完成轮次或发现无法映射到
冻结清单的订单记录时，系统 fail closed，不得通过删除账本恢复。

启动器实现以下约束：

1. **定时驱动**：每根 4h K 线收盘后，拉取 12 市场最新收盘价，喂给 `FrozenTrendBasketRunner.on_close(...)`。
2. **状态持久化**：把累积的 paper 权益曲线、每次再平衡、当前 TB3 指标写入本地 JSONL 哈希链只追加账本，进程重启可恢复、不丢状态。
3. **前向起点锁定**：记录预注册的**前向起始时间戳**与输入指纹，之后不可篡改。
4. **监控暴露**：在控制台/快照只读展示前向进度（已跑多久）、权益曲线、当前指标 vs 冻结门、数据完整性、成交健康。
5. **护栏**：期间不提供任何改参数/提前判定的入口。

> 只有 `--initialize` 在 Binance 可达主机成功完成后才开始真正的前向计时；代码存在和历史回放都不算前向样本。

---

## 6. 每月监控清单（看，但**不据此行动**）

启动后每月看一眼即可（前向是慢变量，不用天天盯）：

- [ ] **服务在跑吗**：进程健康、4h K 线按时进来、无长时间数据断裂。
- [ ] **数据完整**：12 市场都有连续 4h K 线、Funding 无大面积缺失。
- [ ] **权益曲线**：走势是否大体符合「趋势市赚、震荡市小回撤」的预期形态。
- [ ] **当前指标 vs 冻结门**：回撤、滚动 12m、被套时长——**只记录，不判定**（未到期限）。
- [ ] **有没有异常**：某个币权重异常、成交明显偏离预期。

**明确不要做的事**：
- ❌ 早期收益好看 → 给 LIVE-SMALL 加钱或提前扩大规模（加仓只走 `LIVE_SMALL.md` 1.2 的 3 个月条件检查；paper 表现不是加仓依据）；
- ❌ 早期回撤难看 → 调参数/暂停/换币（这就作弊了，前向作废）；
- ❌ 没到最短期限 → 下 PASS/FAIL 结论。

---

## 7. 到期之后

- 跑满预注册最短期限 → 用第 4 节的 TB3 冻结门判定 PASS/FAIL。
- **PASS**：授权**讨论 LIVE-SMALL 规模升级到"正式规模"**（小资金实盘按 `LIVE_SMALL.md` V2 已在并行运行）；升级仍是需要显式确认的独立决定，且须以新协议版本预注册。
- **FAIL**：如实记录，趋势 sleeve 在前向未达标；按 `LIVE_SMALL.md` 1.3 评估是否同时停止小资金实盘；回到研究（换 sleeve / 调整体系），不硬上。

---

## 8. 一句话总结

**先用第 2 节确认「你机器上的系统和验证过的一字不差」→ 建成 TB4-B 启动器 → 锁定起点开始跑 → 每月只看不动 → 满 12+ 个月按冻结门判定。整个过程唯一的纪律就是：诚实地等，什么都别动。**
