# V4 有界逆势周期候选预注册

预注册时间：2026-07-13  
状态：候选与新市场锁箱已冻结，尚未运行任何锁箱策略回放

## 1. 候选来源

候选只依据已成为历史诊断证据的 BTCUSDT/ETHUSDT V1-V3 结果设计，不使用 BNBUSDT/SOLUSDT 锁箱结果：

- V2 的“趋势确认后只中和逆势净敞口”将三条旧验证路径改善 `4.69-7.73 USDT`，并把最差折回撤降到不足 `0.60%`，但市场和折覆盖未过门；
- V3 单独限制深档补亏损腿没有改善旧验证覆盖，说明只裁剪补仓而保留原趋势翻向止损不足以改变期望；
- 两者的联合交互尚未被验证：限制逆势风险的建立深度，同时禁止趋势确认后的跨零翻向，构成一个完整的有界风险周期。

## 2. 唯一预注册候选

候选名：`bounded_counter_trend_cycle`。

候选只组合两个已经默认关闭的结构门：

1. `events.profit_transfer.sizing.first_rung_loss_side_add_only = true`：仅第一档允许补亏损腿，第二档以后只减盈利腿；
2. `events.loss_side_reduction.sizing.neutralize_counter_trend_skew_only = true`：趋势确认后只把逆势净敞口归零，不跨零建立顺势敞口；
3. 现有趋势退出持续确认、`POSITION_RECOVERY`、`POSITION_REBUILD` 和 reanchor 规则保持不变；
4. 不修改 `a_pt`、`theta_t`、档数、仓位比例、成本、Funding、Regime Gate 或 RiskGuard；
5. 默认 `full` 配置保持两个开关均为 `false`，零默认行为变更。

实现只需增加显式回放 variant，禁止根据锁箱结果再修改组合或参数。

## 3. 新市场锁箱

数据来自 Binance USD-M Futures 公共接口，抓取完成后立即记录数量、UTC 范围和 SHA-256。BNB/SOL 从未参与 V1-V3 候选选择或验证。

| 文件 | 数量 | UTC 范围 | SHA-256 |
|---|---:|---|---|
| `BNBUSDT_15m_lockbox_ohlc.json` | 17279 | 2026-01-14 13:59:59 - 2026-07-13 13:29:59 | `a523f4d80517b4eaefaa3c7be93bd984b640a78d7a8f6082721607d1c7476357` |
| `BNBUSDT_1h_lockbox_ohlc.json` | 8639 | 2025-07-18 14:59:59 - 2026-07-13 12:59:59 | `a30a0dfea9cdf273fc74ff9195c2c5927ed42bd22537eccacecf6a8af855e19d` |
| `SOLUSDT_15m_lockbox_ohlc.json` | 17279 | 2026-01-14 13:59:59 - 2026-07-13 13:29:59 | `5d474711fb66de6a13ca427e99b1291776250a412643701ae1480e71dd0949ab` |
| `SOLUSDT_1h_lockbox_ohlc.json` | 8639 | 2025-07-18 14:59:59 - 2026-07-13 12:59:59 | `e04edbcf163cf6d9908ab1ea4ef00ffdf376d39b5cf645000fbf292c6c9e7e60` |
| `BNBUSDT_lockbox_funding.json` | 1080 | 2025-07-18 16:00:00 - 2026-07-13 08:00:00 | `03f6b1119733cb4ba96ee15657bac9732ea72b8228a4a15c094e250b86e7a2fb` |
| `SOLUSDT_lockbox_funding.json` | 1080 | 2025-07-18 16:00:00 - 2026-07-13 08:00:00 | `2eb15512c2be5ab7ae93b10404ca9ebf15038d0ced610048213c0ceb544d5b80` |

窗口保持原矩阵同构：15m 使用 `train=5760 / validation=1920`，1h 使用 `train=2880 / validation=960`，每个市场 5 个外层验证折，共 20 折。训练段只作为 walk-forward 暖启动边界，不再用于改变候选。

## 4. 冻结准入门

候选实现和测试完成后，同时运行 `fixed_ohlc`、`fixed_olhc`、`myopic` 三条 OHLC+Funding 路径，以及 C8 统计代理。

GO 条件沿用 `ADMISSION.md`：每条完整引擎路径均须净收益为正、至少 3/4 盈利市场、至少 11/20 盈利折、Funding 完整、最差折回撤不超过 5%；C8 须至少 30 笔、95% Wilson 下界严格高于 `pi_required`、单次期望为正。任一失败即为 NO-GO。

锁箱一旦运行，只允许记录 PASS/FAIL 和差距，不得调整候选、阈值、市场或窗口。
