# TB1 趋势跟踪篮子预注册

预注册时间：2026-07-14  
状态：正式训练 PASS，唯一候选已冻结；锁箱尚未打开

## 1. 研究问题

TB1 审计时序动量能否作为交易体系的第一块 sleeve：它不追求单笔高 alpha，而要求一个分散、按波动率定仓、成本后为正且回撤受控的组合贡献。信号方向固定为趋势延续，不同时测试反向均值回归。

```text
signal_i(t) = sign(close_i(t) / close_i(t - momentum_lookback) - 1)
annual_vol_i(t) = stdev(log_return_i over trailing vol_lookback) * sqrt(periods_per_year)
raw_weight_i(t) = signal_i(t) * target_portfolio_vol / (sqrt(active_markets) * annual_vol_i(t))
```

所有 `raw_weight` 按同一比例缩放，使 `sum(abs(weight_i)) <= 1.0`。这使活跃币种具有近似相等的事前风险贡献，同时不使用超过 1 倍的 gross leverage。

## 2. 正式数据宇宙

正式判定的固定 Binance USD-M perpetual 宇宙为：

`BTCUSDT, ETHUSDT, BNBUSDT, SOLUSDT, XRPUSDT, DOGEUSDT, ADAUSDT, LINKUSDT, AVAXUSDT, DOTUSDT, LTCUSDT, BCHUSDT`

数据要求：

- `4h` OHLC，至少覆盖共同连续 `1095` 天；
- 同期真实 Funding，单市场覆盖率至少为预期 8 小时结算次数的 `99%`；
- 至少 `10/12` 市场同时满足数据要求，低于 10 个市场不得给出 PASS/FAIL；
- 获取后、运行前记录每个输入文件的 SHA-256、行数和 UTC 区间；
- 共同时间轴末 `365` 天为一次性锁箱，之前为训练段；锁箱不得用于选参。

固定 12 个符号不得根据收益删除。因上市时间或缺失数据不合格的市场只能按上述客观数据门排除并记录原因。

## 3. 冻结训练网格

- 动量 lookback：`28 / 84 / 168` 天；
- 波动率 lookback：`28 / 84` 天；
- 再平衡：每 `7` 天；
- 组合年化目标波动率：`10%`；
- gross leverage cap：`1.0`；
- 共 `3 x 2 = 6` 组，除此之外不搜索信号死区、移动平均、止损或方向。

训练候选按 Sharpe 最高排序，其次年化净收益更高、最大回撤更低、动量 lookback 更长、波动 lookback 更长，只冻结唯一候选。训练门未通过则不打开锁箱。

## 4. 无未来泄漏与执行顺序

- `t` 收盘后只使用截至 `t` 的 close 计算信号与波动率；
- 目标权重在下一根 K 线收盘 `t+1` 执行，新权重只承担此后的价格收益和 Funding；
- 当前持仓承担两个收盘之间实际发生的 Funding；Funding 现金流为 `-signed_weight * funding_rate`；
- 每次再平衡前的持仓收益先按已知旧权重结算，再执行新权重和成本；
- 训练只读取锁箱起点之前的数据；锁箱只有在唯一候选冻结后才允许一次性运行；
- 最后一个价格点强制清仓并计成本，不用未来价格补齐。

## 5. 成本与组合记账

单腿完整往返成本固定为 `0.14% = 2 x (0.05% taker + 0.02% slippage)`。定义组合单边换手：

```text
turnover(t) = 0.5 * sum(abs(new_weight_i - old_weight_i))
transaction_cost_pct(t) = turnover(t) * 0.14%
price_return_pct(t) = sum(old_weight_i * simple_price_return_i(t)) * 100
funding_return_pct(t) = -sum(old_weight_i * funding_rate_i within interval) * 100
net_return_pct(t) = price_return_pct + funding_return_pct - transaction_cost_pct
```

从现金建仓和最终清仓各计半个完整往返，因此一条腿完整持有周期合计仍为 `0.14%`。组合权益按每期净收益复利。

## 6. 冻结组合级准入门

训练和一次性锁箱分别计算：总净收益、年化净收益、年化波动率、Sharpe（无风险利率按 0）、最大峰谷回撤、盈利年度折、换手、成本、Funding、逐币价格与 Funding 贡献。

候选必须同时满足：

1. 年化净收益 `> 0`；
2. 年化 Sharpe `>= 0.50`；
3. 最大回撤 `<= 20%`；
4. 固定 365 天折中，盈利折数严格超过有效折数的一半；
5. Funding 完整且数据质量门通过。

只有训练 PASS 才冻结唯一候选并打开锁箱；锁箱也全部通过才是 TB1 PASS。任何一层失败均原样记录，不据结果修改参数、成本、宇宙或 bar。

## 7. 数据受限冒烟

现有 BTC/ETH/BNB/SOL `1h` 数据可用于验证实现、时间对齐、成本和报告，但只有四个高相关主流币且周期过短、频率过高。该运行固定标记：

`DATA_LIMITED_NON_CONCLUSIVE`

弱冒烟不得产生 TB1 PASS 或 NO-GO，也不得打开正式锁箱。正式数据无法获取时，任务状态应是“实现完成、正式研究被数据前置阻塞”。

## 8. 实现边界

- 新增纯计算 trend-basket 估计器和离线 CLI；
- 单测锁定信号、波动率权重、执行滞后、Funding 符号、换手成本、复利、Sharpe、回撤和数据质量门；
- 不修改 EventEngine、策略配置、API、数据库、前端或 live 开关。

## 9. 正式训练结果（锁箱打开前，2026-07-14）

已从 Binance USD-M 公共接口获取冻结 12 市场约 5 年的 4h OHLC 与 Funding。12/12 市场通过质量门，共同连续区间为 `1824.67` 天、`10,949` 根 4h K 线；训练报告记录了每个输入文件的 SHA-256、行数和区间。末 `365` 天仍未读取为绩效锁箱。

六组训练结果：

| 参数 | 年化净收益 | Sharpe | 最大回撤 | 盈利年度折 | 训练门 |
|---|---:|---:|---:|---:|---|
| mom28 / vol28 | +23.135% | 0.948 | 18.937% | 2/3 | PASS |
| mom28 / vol84 | +19.886% | 0.880 | 17.237% | 3/3 | PASS |
| mom84 / vol28 | +1.868% | 0.199 | 44.281% | 2/3 | FAIL |
| mom84 / vol84 | +5.275% | 0.333 | 39.336% | 2/3 | FAIL |
| mom168 / vol28 | -9.543% | -0.318 | 44.266% | 2/3 | FAIL |
| mom168 / vol84 | -6.527% | -0.197 | 36.608% | 2/3 | FAIL |

按预注册排序冻结唯一候选 `mom28_vol28`：动量 28 天、波动率 28 天、周频再平衡、目标波动 10%、gross cap 1.0、往返成本 0.14% 并计真实 Funding。

本地只追加训练报告：`var/calibration/tb1_trend_basket_training.json`。报告 SHA-256：`e557cd0c389e34781259851df8570aaf5823d445da48171cf1f8489b6a4f0797`。

当前 verdict 为 `TRAINING_PASS_LOCKBOX_PENDING`，`lockbox_opened=false`。下一步只允许使用该报告和原输入指纹执行一次性锁箱，不得再选择 `mom28_vol84` 或修改参数。
