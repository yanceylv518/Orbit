# G2 Funding 跨币种相对强弱动量预注册

预注册时间：2026-07-13  
状态：训练搜索已完成，G2 FAIL；未创建或打开新锁箱

## 1. 假设

Funding 是永续合约方向需求的可观察价格。若这种需求具有短期持续性，则过去 Funding 相对更高的市场可能继续强于 Funding 相对更低的市场。G2 只审计一个事先冻结的方向：

```text
score_i(t) = mean(funding_i over trailing L settlements, including t)
long_market = argmax(score_i(t))
short_market = argmin(score_i(t))
```

每条腿等名义，组合收益以两腿总 gross notional 为分母。G2 不同时测试“做空最高、做多最低”的反转方向，避免在结果中二选一；该反转含义也已与 G1 的逆拥挤假设高度重合。

## 2. 时间对齐与无未来泄漏

- 将 Funding 时间戳归一到最近的 8 小时结算槽，只接受距离标准槽不超过 60 秒的数据，并取四市场共有结算槽；
- 信号在结算槽 `t` 的 Funding 已发生后计算，trailing score 可以包含 `t`，不得包含 `t` 之后的 Funding；
- 每条腿的入场价取 `t` 之后第一个 15m 已收盘 K 线的 close；
- 持有 `H` 个 Funding 周期，即从入场 K 线起固定 `32H` 根 15m K 线后退出；
- 持有期 Funding 现金流只计 `t` 之后、退出前已经发生的结算；当前 `t` 的 Funding 已在入场前发生，不计入持仓现金流；
- 持仓期间忽略新信号，退出后才允许下一事件，保证组合事件不重叠；
- score 最高与最低相等时不交易；数据缺腿或尾部不足完整持有期时丢弃事件。

## 3. 收益与成本

设两腿各占组合 gross notional 的 `50%`：

```text
long_price_pct = (long_exit / long_entry - 1) * 100
short_price_pct = -(short_exit / short_entry - 1) * 100
long_funding_pct = -sum(long_future_funding) * 100
short_funding_pct = +sum(short_future_funding) * 100
gross_pair_pct = 0.5 * (
    long_price_pct + short_price_pct
    + long_funding_pct + short_funding_pct
)
net_pair_pct = gross_pair_pct - 0.14%
```

每条腿建平成本均为 `2 x (0.05% taker + 0.02% slippage) = 0.14%`；按两腿 gross notional 加权后，组合成本仍为 `0.5 x 0.14% + 0.5 x 0.14% = 0.14%`。不使用 maker 优化，不假设 Funding 免费。

## 4. 冻结训练网格

训练数据使用已被前序研究打开的 BTCUSDT、ETHUSDT、BNBUSDT、SOLUSDT 15m perp OHLC 与 Funding；它们不再具备新锁箱资格。

- score lookback：`3 / 9 / 21` 次 Funding，即 `1 / 3 / 7` 天；
- holding：`3 / 9 / 21` 次 Funding，即 `1 / 3 / 7` 天；
- 共 `3 x 3 = 9` 个参数组合；
- Bootstrap 固定 `10,000` 次、种子 `20260713`，输出事件均值 95% 区间；胜率同时输出 Wilson 95% 区间。

## 5. 训练候选选择门

参数组合进入候选池必须同时满足：

1. 非重叠组合事件数 `>= 30`；
2. 成本与 Funding 现金流后的平均净收益 `> 0`；
3. Bootstrap 均值 95% 下界 `> 0`；
4. 四个市场各自至少参与 `10` 条事件腿，避免结论只来自固定币对。

若候选池非空，按以下冻结顺序选择唯一候选：bootstrap 下界最高，其次平均净收益最高、事件数最多、lookback 更长、holding 更短。若候选池为空，**G2 在训练阶段直接 FAIL，不创建或打开新锁箱**。

## 6. 条件触发的锁箱

只有训练门 PASS 才允许获取至少四个从未参与选择的新市场，先冻结 Funding 与 OHLC 文件哈希，再按唯一参数一次性判定。锁箱仍要求 `>=30` 非重叠事件、净均值和 bootstrap 下界为正、每个市场至少参与 `10` 条事件腿。

锁箱结果不得用于修改方向、lookback、holding、成本、市场、时间归一或价格对齐规则。

## 7. 实现边界

- 新增纯计算跨市场 Funding 相对强弱估计器与离线 CLI；
- 单元测试锁定排序方向、时间归一、当前/未来 Funding 边界、两腿价格与 Funding 现金流、成本、非重叠、覆盖门和统计门；
- 不修改策略配置、EventEngine、API、数据库、前端或执行通道。

## 8. 训练结果（2026-07-13）

按上述冻结协议运行 `9` 个参数组合，使用 BTCUSDT、ETHUSDT、BNBUSDT、SOLUSDT 四个已打开市场。完整机器可读结果保存在本地忽略文件 `var/calibration/g2_funding_relative_strength_training.json`。

- 候选组合：`0 / 9`；全部组合平均净收益为负；
- 按预注册排序最接近门槛的诊断组合：score lookback `9` 次 Funding（3 天）、holding `3` 次 Funding（1 天）；
- 该组合有 `135` 个非重叠事件，四市场事件腿覆盖为 BTC `71`、ETH `34`、BNB `63`、SOL `102`，覆盖门通过；
- 平均价格贡献 `-0.0023%`，平均 Funding 现金流贡献 `-0.0082%`，平均毛收益 `-0.0105%`，扣 `0.14%` 成本后平均净收益 `-0.1505%`；
- 净收益 bootstrap 95% 区间为 `[-0.3050%, +0.0018%]`，统计门失败；
- 1 天/3 天持有组合分别有 `135/54` 个事件但均为负；7 天持有组合只有 `24` 个事件，同时不满足 `>=30` 样本门和覆盖门。

**结论：G2 在训练阶段 FAIL。** Funding 相对强弱动量在当前定义下连成本前毛收益都未转正，加入真实 Funding 现金流和零售执行成本后更差。按预注册规则，不获取新市场、不打开锁箱，也不测试相反方向或回调 lookback/holding。至此 F1、G1、G2 三个低成本独立候选均为 NO-GO，应结束继续枚举便宜 alpha，转入平台价值路线或项目收尾决策。
