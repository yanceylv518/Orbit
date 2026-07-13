# Funding Carry F1 必要条件筛查预注册

预注册时间：2026-07-13  
状态：协议已冻结，尚未运行 F1 数值筛查

## 1. 目标与边界

F1 只回答一个必要条件：历史 Funding 现金流是否大到且稳定到足以覆盖 delta-neutral carry 的最低执行成本。F1 不实现 spot/perp 交易，不改运行配置，不构成 testnet、paper 或 live 准入。

真实 carry 需要 perp 与 spot（负 Funding 时还需要可借入的 short spot）两条腿。F1 暂时假设价格方向敞口被完美对冲、每次都能持有收取 Funding 的方向，只测 Funding 上界。Basis 漂移、spot 借币利息、保证金利息、方向切换冲击和容量限制均未计入，因此真实收益只能更差。

## 2. 数据与非重叠采样

使用已经获取的 Binance USD-M Futures 历史 Funding：BTCUSDT、ETHUSDT、BNBUSDT、SOLUSDT，各 1080 个结算点，约 360 天。

- 结算间隔按 8 小时预期；相邻点超过 12 小时视为数据断裂，不允许窗口跨越断裂；
- 每个连续段从最早点开始切分为不重叠窗口，尾部不足一个完整窗口的数据丢弃；
- 持有窗口固定为 `1/3/7/14/30 天`，对应 `3/9/21/42/90` 次 Funding 结算；
- 不根据结果移动窗口起点、重叠采样或删除负窗口。

## 3. 乐观 Funding 收益

对每个窗口，假设每个结算时刻都持有可收取 Funding 的正确 perp 方向，并由 spot 完美对冲：

```text
gross_funding_pct = 100 * sum(abs(funding_rate_i))
net_carry_pct = gross_funding_pct
                - entry_exit_cost_pct
                - rebalance_cost_pct_per_day * holding_days
```

冻结成本：

- perp 往返：`2 * (0.05% taker + 0.02% slippage) = 0.14%`；
- spot 往返：`2 * (0.10% taker + 0.02% slippage) = 0.24%`；
- 两腿建仓和平仓合计：`entry_exit_cost_pct = 0.38%`；
- 再平衡：假设每日调整两腿各约 10% 名义，冻结为 `rebalance_cost_pct_per_day = 0.02%`；
- 总成本分别为 1/3/7/14/30 天：`0.40% / 0.44% / 0.52% / 0.66% / 0.98%`。

该成本仍未包含负 Funding 时的 spot 借币费，也没有为每次 Funding 符号翻转额外收取全量换向成本，故仍是乐观上界。

## 4. 统计量与冻结判据

逐市场、逐窗口输出：非重叠事件数、盈利事件数、胜率及 Wilson 95% 区间、平均/中位毛 Funding、平均净 carry、总净 carry、最差窗口、最大回撤，以及均值 bootstrap 95% 区间。

Bootstrap 固定为：`10,000` 次有放回抽样、随机种子 `20260713`，使用均值分布的 2.5%/97.5% 分位数。

单市场 PASS 必须同时满足：

1. 非重叠窗口数 `>= 30`；
2. 平均 `net_carry_pct > 0`；
3. Bootstrap 均值 95% 下界 `> 0`。

F1 总体 PASS 必须存在一个相同持有窗口同时满足：

1. 至少 `3/4` 市场单市场 PASS；
2. 四市场全部非重叠窗口合并后的平均净 carry `> 0`；
3. 合并 bootstrap 95% 下界 `> 0`。

任一条件不满足即 F1 FAIL，并停止 F2。筛查运行后只追加结果，不修改本协议中的窗口、成本、样本或判据。

## 5. 实现约束

- 纯计算函数：`funding_carry_screen`，输入 FundingPoint 序列、窗口与冻结成本；
- CLI 只读本地 Funding JSON，报告写入 Git 忽略目录；
- 单元测试覆盖成本扣减、非重叠窗口、数据断裂、Wilson 与 bootstrap 下界、样本量门；
- 不创建 spot repository、订单动作、API 路由或前端入口。
