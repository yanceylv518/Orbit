# R-0 估计器实现说明

状态：`TRAINING_EVALUATED_FAIL`
冻结依据：`R0_SHORTLINE_SCREEN.md` / `r0_shortline_screen.v2.json`

## 边界

本实现是纯离线研究估计器，不接入 Shadow、Paper、Testnet、Live、订单执行或运行账本。它只实现已经冻结的两个策略族、16 组参数、成本、Funding、统计门和一次性锁箱纪律；没有新增参数或指标。V1 已在结果落盘前停止且不得再运行，CLI 默认只接受 V2 契约。

估计器分为三层：

1. `domain/calibration/r0_shortline.py`：信号、ATR、下一根开盘成交、止损/时间退出、Funding、成本、非重叠事件、UTC 日 block bootstrap、分组汇总和候选排序。
2. `application/r0_shortline_screen.py`：在读取市场数据前核验机器契约 SHA、manifest 内容指纹、质量报告指纹、数据截止和 COMPLETE/缺失/重复条件；编排训练与锁箱 verdict。
3. `tools/screen_r0_shortline.py`：顺序读取每个合约的正式 15m/Funding 归档。训练命令最多打开 2024-12 的归档，不打开 2025 年后的 K 线或流动性文件；锁箱必须显式确认并以独占文件记录第一次开箱。V2 使用最近 3 个完整 UTC 日的 3,000 万 USDT 中位成交额门槛、全部合格合约和动态三等分，不使用固定 Top-N 或 30 天上市硬门槛。
4. `tools/audit_r0_v2_universe.py`：只读取每日流动性与合约元数据，复算训练/锁箱容量，不读取 15m 信号、Funding 或收益。

## 使用方式

训练输出和锁箱输出均使用独占创建，已有文件不会被覆盖：

```powershell
# 只运行训练段；不会打开 2025-2026 锁箱
.\.venv\Scripts\python.exe backend/tools/screen_r0_shortline.py train `
  --out var/research/r0_training_<run-id>.json

# 仅当训练报告至少有一个策略族通过时，才允许显式开箱一次
.\.venv\Scripts\python.exe backend/tools/screen_r0_shortline.py lockbox `
  --training-report var/research/r0_training_<run-id>.json `
  --out var/research/r0_lockbox_<run-id>.json `
  --confirm-open-lockbox
```

## 正式训练结果（2026-08-12）

正式训练已经在冻结的 V2 契约和正式全市场数据上完成。完整机器报告保存于
`docs/evidence/r0/r0_training_v2_20260812.json`，SHA-256 为
`733b864d30d2cde517b4773dd593c8c6136e32b24e232a5ec1cb31ab724f2738`。

- 总结论：`TRAINING_FAIL`。
- 突破/动量族：8 组参数均未通过训练门，族结论为 `TRAINING_FAIL`。
- 超跌反弹族：8 组参数均未同时通过全部预注册训练门，族结论为 `TRAINING_FAIL`。
- 获准进入锁箱的策略族：0 个。
- 锁箱状态：保持关闭；没有读取或评估 2025–2026 锁箱段。
- 交易授权：无。本任务本来就只决定是否值得继续建设短线研究平台，不授权交易。

报告已用应用层 `validate_training_report` 重新校验：契约 SHA、数据集指纹和按冻结顺序重新计算的候选选择均一致。依据预注册裁决，两族均未通过意味着短线平台阶段 2+ 暂不解锁；如需研究新假设，应另立新协议，不能修改本次门槛后重跑。

## 输出

每组参数都输出整体以及逐流动性层、逐 UTC 年、逐合约、逐 3 日成交额趋势、逐上市年龄的事件数、平均净收益和 95% UTC 入场日 block-bootstrap 区间，同时逐条列出固定门是否通过。后两项仅为预注册诊断，不参与选择和 PASS/FAIL。训练只按冻结顺序选择每个策略族的唯一候选；无候选即 `TRAINING_FAIL`。锁箱只运行训练选出的候选，最终结果明确标注 `trading_authorized=false`。
