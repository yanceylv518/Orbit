# TB4 冻结趋势组合纸面前向协议

状态：**TB4-A runner 对齐通过；TB4-B 后端启动器已实现，前向尚未启动**
最后更新：2026-07-14

## 1. 目的与证据边界

TB4 只验证 TB-R 已冻结系统在未来时间中的真实可执行表现，不再研究参数。历史回放仅用于证明线上 runner 与离线估计器是同一个数学系统，不能计入前向证据。

当前未填写前向开始时间，未累计任何前向样本。只有部署到 Binance 公共期货接口可达的持续运行环境、完成历史预热并原子写入不可变启动清单后，TB4-B 才能从清单时间开始计时。

## 2. 冻结系统

- 市场：`BTCUSDT, ETHUSDT, BNBUSDT, SOLUSDT, XRPUSDT, DOGEUSDT, ADAUSDT, LINKUSDT, AVAXUSDT, DOTUSDT, LTCUSDT, BCHUSDT`
- 周期：4h 已收盘 K 线，12 市场共同连续时间轴
- 信号：`14/28/56/84/168` 日动量符号等权平均
- 波动率：28 日对数收益样本标准差年化
- 组合目标波动率：10%
- gross cap：1.0
- 再平衡：每 7 日一次，信号后下一根 4h K 线执行
- 成本：0.14% 往返成本，按半换手计提
- Funding：逐条使用真实结算时间与真实费率，long 支付、short 收取
- 风险覆盖：不启用任何回撤调参或临时 overlay
- 通道：paper only；不得改变或自动开启 live

代码中的唯一冻结规格为 `TB4_SPEC`。运行层不得从账户配置、环境变量或前端请求覆盖上述参数。

## 3. TB4-A 对齐门

实现位于：

- `backend/src/orbit/domain/strategy/trend_basket_runner.py`
- `backend/tools/verify_tb4_alignment.py`
- `backend/tests/test_trend_basket_runner.py`

正式校验使用 TB1/TB-R 的 12 市场冻结输入，先核对每个输入 SHA-256，再将完整共同连续历史分别送入离线估计器和增量 runner。验收要求：

- 每根评估 K 线净收益绝对误差 `<= 1e-12`
- 每次再平衡信号/成交时间完全相同
- 每个市场目标权重绝对误差 `<= 1e-12`
- 换手和成本绝对误差 `<= 1e-12`

2026-07-14 正式运行结果：`9,940` 个评估周期、`237` 次再平衡；最大净收益误差 `0.0`，最大目标权重误差 `0.0`，verdict **`TB4_ALIGNMENT_PASS`**。本地证据文件为 `var/calibration/tb4_runner_alignment.json`，属于忽略提交的可再生校验产物。

## 4. TB4-B 启动前置条件

以下条件必须全部满足，才允许写入开始时间：

1. 运行主机能稳定访问 Binance USD-M K 线和 Funding 公共接口。
2. 12 市场完成至少 1,008 根共同连续 4h K 线预热，输入不存在缺口。
3. 实时增量数据按共同收盘时间同步，不用未收盘 K 线。
4. Funding 拉取、去重和时间区间归属通过生产接线测试。
5. paper 组合状态、权益曲线和成交记录使用只追加哈希链保存。
6. 启动清单包含本协议文件哈希、代码提交、UTC 开始时间和冻结规格哈希，写入后不可覆盖。
7. 控制台只读展示进度，不提供调参、提前 verdict 或切 live 操作。

## 5. 期限与判定纪律

- 最短运行期：形成完整滚动 12 个月窗口，原则上不少于 12 个月并预留数据缺口缓冲。
- 中途检查点只报告运行健康、数据完整性和当前冻结指标，不作 PASS/FAIL。
- 前向期间不得改参数、换市场、重置权益曲线、删除不利样本或因早期表现提前停止。
- 最终使用 TB3 同一套冻结门：净收益、最大回撤、Calmar、Sortino、最差滚动 12 个月、正滚动 12 个月比例和最长回撤时长。
- TB4 通过只授权讨论小资金 live，不自动开放 live。

## 6. TB4-B 后端交付

已实现：Binance 12 市场共同 4h 历史预热与增量 Funding 驱动、runner 确定性恢复、不可变启动清单、只追加 JSONL 哈希链账本、期限前禁止 verdict、平台 snapshot 只读投影，以及独立守护进程入口 `backend/tools/run_tb4_forward.py`。

首次部署到 Binance 可达网络后执行：

```bash
python backend/tools/run_tb4_forward.py --initialize
```

进程重启时去掉 `--initialize`，服务会验链并重放全部输入后继续。`--initialize` 只能成功一次；现阶段没有删除、覆盖、移动起点、调参或 live 操作入口。真实前向尚未启动，状态继续保持 `NOT_STARTED`。
