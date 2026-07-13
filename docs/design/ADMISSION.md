# Dynamic Dual Grid Testnet 准入协议

版本：V1（2026-07-13）  
状态：预注册标准已冻结，当前判定为 **NO-GO**

## 1. 目的与适用范围

本文定义 Dynamic Dual Grid 从离线研究进入 Binance Futures Testnet 连续运行前必须通过的统计与领域回放标准。标准先于 V2 几何候选验证固定，后续不得因为某次验证结果而移动阈值、删除亏损市场或改变路径口径。

Testnet 在这里仍会消耗工程和运营注意力，因此不是“无条件试运行”。只有统计代理门和完整领域引擎门同时通过，才允许进入 testnet；testnet 通过也不等于允许小资金 live。

## 2. 数据矩阵与隔离折

当前预注册矩阵固定为 BTCUSDT、ETHUSDT 两个市场和 15m、1h 两个周期：

| 市场 | 缓存行数 | 数据区间（UTC） | 训练窗 | 验证窗 | 验证折 |
|---|---:|---|---:|---:|---:|
| BTCUSDT 15m | 17,279 | 2026-01-14 00:59 至 2026-07-13 00:29 | 5,760 | 1,920 | 5 |
| ETHUSDT 15m | 17,279 | 2026-01-14 00:59 至 2026-07-13 00:29 | 5,760 | 1,920 | 5 |
| BTCUSDT 1h | 8,639 | 2025-07-18 01:59 至 2026-07-12 23:59 | 2,880 | 960 | 5 |
| ETHUSDT 1h | 8,639 | 2025-07-18 01:59 至 2026-07-12 23:59 | 2,880 | 960 | 5 |

合计为 4 个市场周期和 20 个隔离验证折。每折独立初始化和期末清算，不跨折携带仓位、锚点或账务状态。

后续扩充市场只能增加矩阵覆盖，不得根据验证结果删除表现不佳的既有市场。新增数据必须在 Binance 可达网络获取，并在运行前记录时间范围和输入指纹。

## 3. Walk-forward 纪律

1. 几何参数和 Regime Gate 参数只能读取训练窗；验证窗只用于一次性打分。
2. 统计代理使用既有 `A_GRID`、`THETA_GRID` 和 18 组 Gate 网格，不因 V1 结果增加定向候选。
3. 训练期 Gate 未通过 C8 的折在 `gate_deploy` 口径保持空仓，不能拿“最不差”参数替代。
4. V2 每次只预注册一个结构性候选。候选若读取过某段验证结果，该段数据不得再用于选择候选，只能作为已有诊断证据。
5. FAIL 必须原样记录。禁止以调整折窗、路径、成本或市场集合的方式追求 PASS。

## 4. 联合准入门

以下两层全部通过才是 GO。任一硬条件失败即为 NO-GO。

### 4.1 统计代理门（C8）

成本率固定为 `c = 0.14%`。每个市场周期在隔离验证折聚合后必须同时满足：

1. 外样本 excursion 数量不少于 30；
2. 95% Wilson 下界严格大于加权盈亏平衡线：`pi_ci_low > pi_required`；
3. 外样本单次期望 `expected_value_pct > 0`。

组合还必须满足：

1. 聚合外样本期望为正；
2. 至少 3/4 市场周期为正收益；
3. 上述单市场 C8 条件没有失败项。

C8 是简化 excursion 代理的必要条件，不是完整策略盈利的充分条件。

### 4.2 完整领域引擎门

完整回放直接复用生产 `EventEngine`，每折预算为 100 USDT，按 `config/config.sample.json` 计手续费与滑点，并必须使用真实历史 Funding。固定执行三种 OHLC 路径：

- `fixed_ohlc`：每根按 O-H-L-C；
- `fixed_olhc`：每根按 O-L-H-C；
- `myopic`：逐 K 在两条极值顺序中延续收盘权益较低的状态，仅作为局部压力测试。

三种路径必须分别同时满足：

1. 20 折合计净收益 `total_net_pnl_usdt > 0`；
2. 至少 3/4 市场周期合计净收益为正；
3. 至少 11/20 验证折净收益为正；
4. `funding_complete = true`；
5. 最差单折峰值回撤不超过初始预算的 5%。

5% 回撤线取生产单币种 10% STOP 上限的一半，为 testnet 准入保留安全余量。三种路径必须全部通过，不能选择事后表现最好的一条作为 verdict。

## 5. V1 复算口径

统计代理命令使用 `backend/tools/calibrate_matrix.py`，参数为 `--cost 0.14 --tune-gate`，数据集依次为：

```text
BTCUSDT-15m,var/calibration/BTCUSDT_15m.json,5760,1920
ETHUSDT-15m,var/calibration/ETHUSDT_15m.json,5760,1920
BTCUSDT-1h,var/calibration/BTCUSDT_1h.json,2880,960
ETHUSDT-1h,var/calibration/ETHUSDT_1h.json,2880,960
```

完整引擎命令使用 `backend/tools/replay_matrix.py`，对同一矩阵分别运行 `--intrabar-mode fixed_ohlc`、`fixed_olhc` 和 `myopic`；每个 dataset 同时传入对应 OHLC 与 Funding 文件。V1 本地报告写在 `var/calibration/v1_admission_*.json`，该目录被 Git 忽略，正式 verdict 以本文为准。

## 6. V1 现状判定

### 6.1 C8 对照

以下是 `gate_deploy` 外样本口径。零交易表示该市场所有折均未在训练期获得部署准入，不属于“零风险通过”。

| 市场 | 外样本笔数 | pi_hat | Wilson 下界 | pi_required | 单次期望 | C8 |
|---|---:|---:|---:|---:|---:|---|
| BTCUSDT 15m | 0 | 0 | 0 | 0 | 0 | FAIL（证据不足） |
| ETHUSDT 15m | 0 | 0 | 0 | 0 | 0 | FAIL（证据不足） |
| BTCUSDT 1h | 9 | 0.333333 | 0.120582 | 0.410000 | -0.306667% | FAIL |
| ETHUSDT 1h | 0 | 0 | 0 | 0 | 0 | FAIL（证据不足） |

组合部署口径只有 9 笔，净代理收益 `-2.76%`，盈利市场 `0/4`。统计代理门失败。

### 6.2 完整引擎对照

| 路径 | 合计净收益 | 盈利市场 | 盈利折 | 最差折回撤 | Funding | 判定 |
|---|---:|---:|---:|---:|---|---|
| fixed_ohlc | -7.234039 USDT | 0/4 | 5/20 | 3.865260% | 完整 | FAIL |
| fixed_olhc | -6.616807 USDT | 1/4 | 6/20 | 3.865260% | 完整 | FAIL |
| myopic | -5.929452 USDT | 1/4 | 6/20 | 3.865260% | 完整 | FAIL |

回撤上限和 Funding 完整性通过，但三条路径均未通过正收益、盈利市场覆盖和盈利折覆盖。距离最低覆盖线仍差 2–3 个盈利市场、5–6 个盈利折；距离收益线为 `5.93–7.23 USDT`。

### 6.3 Verdict

**NO-GO：当前策略不得进入 testnet、paper 候选或 live。**

下一步只允许执行 V2：在训练窗诊断后预注册一个趋势减仓结构候选，默认关闭实现，再用完全隔离的验证窗按本文同一 bar 判定。V2 若仍失败，应记录差距并继续几何研究或重新评估策略，不提前建设运营链路。

## 7. V1 输入指纹

以下为本次复算输入 SHA-256：

| 文件 | SHA-256 |
|---|---|
| `config/config.sample.json` | `b03ccf3791181c20718130c8dcbd9e588bc483c3990a35f9bacfb8bba69f3459` |
| `BTCUSDT_15m.json` | `0a41b174d15e3b51f76bca36a3474492218514bbc16b831a955561a65ee400e3` |
| `ETHUSDT_15m.json` | `bee6ef03e35c62059ae8208616dbafb53eb2d8b4105cb6feb78d718ecd386915` |
| `BTCUSDT_1h.json` | `c60eee74c4b5a4889d5f1789d4d48363814f7e0fbb428b1b540b523bc8371684` |
| `ETHUSDT_1h.json` | `ce7af6047125ef7b6d213834882446430c0d925dcbeca3202d0c40229c45eca7` |
| `BTCUSDT_15m_ohlc.json` | `75639ab644b0dc5478c1c674857687756d3397a6e1666d80a97593027da69206` |
| `ETHUSDT_15m_ohlc.json` | `af861ed0a43e6b59ef3eefc595a6d316257949cfdea3cb78d8366bdc0ddb7e0f` |
| `BTCUSDT_1h_ohlc.json` | `598a76b0f74236cbc51a004d0927c54649b191f9d75230b4a1d066319aca4771` |
| `ETHUSDT_1h_ohlc.json` | `a0e7c88c1a2b6778f4909997b9a1e36fbe0c0b232ff21bee98860f7966f50034` |
| `BTCUSDT_funding.json` | `a39db5cc3eab3e92ef7840f198cf98a165a2a20d0c6fa529c0bb2b47810e7e6b` |
| `ETHUSDT_funding.json` | `6a89125e2a962cb66763ae9351e4ddc7140b5ef9697fef3a4cf49db456fa677e` |

