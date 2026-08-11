# R-0 估计器实现说明

状态：`IMPLEMENTED_NOT_EVALUATED`
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

本次交付只实现估计器和合成数据测试，没有执行上述正式训练或锁箱命令，因此尚无 R-0 数值结果或 PASS/FAIL。

## 输出

每组参数都输出整体以及逐流动性层、逐 UTC 年、逐合约、逐 3 日成交额趋势、逐上市年龄的事件数、平均净收益和 95% UTC 入场日 block-bootstrap 区间，同时逐条列出固定门是否通过。后两项仅为预注册诊断，不参与选择和 PASS/FAIL。训练只按冻结顺序选择每个策略族的唯一候选；无候选即 `TRAINING_FAIL`。锁箱只运行训练选出的候选，最终结果明确标注 `trading_authorized=false`。
