# DATA-1R 全市场短线研究数据集

状态：`IMPLEMENTED_SAMPLE_VERIFIED`（工具与真实样本验证完成；全量数据尚未下载）
最后更新：2026-08-10

## 1. 产品目标与边界

DATA-1R 为突破/动量、超跌反弹等短线候选提供避免幸存者偏差的研究数据。数据集覆盖 Binance USD-M 历史永续合约，包括已退市合约；它只服务研究与回测，不产生信号、不授权 Paper/Live，也不替换 TB4 已冻结数据或指纹。

当前冻结粒度：

- 原始 K 线只保存官方 15m 月度 ZIP；
- 1h/4h 必须从连续 15m 子根按 UTC 边界本地聚合；
- 任何缺根或重复子根产生无 OHLCV 值的 `INCOMPLETE` 聚合根，禁止进入交易回放；
- Funding 作为独立原始事件保存，不属于“更细 K 线”，纳入完整性报告；
- 5m/1m 不在本项目范围。

非目标包括实时行情、短线策略逻辑、自动下单、三仓仲裁和全量数据随代码发布。全量原始数据位于 `var/calibration/shortline-data-v1/`，由 `.gitignore` 隔离。

## 2. 正式数据路径

数据源为 Binance 官方公共归档：

- 月度 USD-M K 线：`data/futures/um/monthly/klines/{symbol}/15m/`
- 月度 Funding：`data/futures/um/monthly/fundingRate/{symbol}/`
- 每个 ZIP 必须通过同目录官方 `.CHECKSUM` 后才原子替换目标文件。

目录布局：

```text
shortline-data-v1/
├─ metadata/archive_index.json
├─ metadata/archive_index_state.json
├─ metadata/contracts.json
├─ raw/klines/15m/{symbol}/{symbol}-15m-{yyyy-mm}.zip
├─ raw/funding/{symbol}/{symbol}-fundingRate-{yyyy-mm}.zip
├─ derived/1h/{symbol}/*.jsonl.gz
├─ derived/4h/{symbol}/*.jsonl.gz
├─ derived/daily_liquidity/{symbol}/*.jsonl.gz
├─ verification/native/{interval}/{symbol}/*.zip
├─ verification_report.json
├─ quality_report.json
└─ manifest.json
```

派生 gzip 固定 `mtime=0`，JSON 字段排序，因此相同输入产生相同字节和 SHA-256。manifest 按路径排序并计算数据集指纹；重复构建不会因为运行时间改变指纹。

## 3. 数据模型与无未来规则

`ContractMetadata` 保存首根、末根、上市、退市、当前状态、状态推断来源和 `history_complete`。使用 exchangeInfo 快照时状态来源为 `EXCHANGE_INFO_SNAPSHOT`；没有快照时只能使用明确标注的归档陈旧度启发式。

完整构建必须同时满足：

1. archive index 的范围为 `ALL_USDT_PERPETUAL`；
2. 每个索引中的 15m 分区均已下载；
3. 本地不存在未登记的原始分区。

否则默认拒绝构建。`--allow-partial` 只用于样本验证，生成 `dataset_state=PARTIAL`、`history_complete=false`；`universe_at` 必须排除这些合约，不能把样本误当完整历史。

`universe_at(T)` 仅使用：

- `listed_at + min_history_days <= T`；
- `T < delisted_at`（如果已退市）；
- `day_close_time < T` 的完整日流动性记录。

退市时间只在 T 已越过该边界时排除合约，不用于提前剔除“即将退市”标的。流动性按冻结回看天数计算中位 quote volume，再执行阈值与 Top-N 排序。

## 4. 运行命令

以下命令均不读取 API Key/Secret：

管理员也可从前端“策略 → 研究候选 → 全市场短线研究数据”启动同一固定流程。页面要求先勾选并再次确认 8–12 GB 下载，并只允许选择 1–8 个并行下载；服务端依次执行 `index → sync --confirm-full-download → build → verify-batch`。最后一阶段确定性抽取最多 3 个 symbol 的最新月份，对 1h/4h 分别复用 `verify-native` 逐字段核对。页面记录阶段、文件/字节进度、当前对象、错误数、最近日志和锁持有者。运行中可停止；已经通过 checksum 的正式文件不会删除，重新启动会重新读取索引/checksum 并继续校验。

```powershell
# 1. 枚举全部历史 symbol、15m 与 Funding 对象；状态可在 state 文件审计
.\.venv\Scripts\python.exe backend/tools/shortline_dataset.py index

# 2. 小范围下载验证
.\.venv\Scripts\python.exe backend/tools/shortline_dataset.py sync `
  --symbol LUNAUSDT --start-month 2022-05 --end-month 2022-05 --workers 1

# 3. 全量下载必须显式确认；已有且 checksum 未变的文件保持不变
.\.venv\Scripts\python.exe backend/tools/shortline_dataset.py sync --confirm-full-download --workers 4

# 4. 正式构建；缺少任一索引分区即失败
.\.venv\Scripts\python.exe backend/tools/shortline_dataset.py build `
  --active-symbols-file var/calibration/exchangeInfo.json

# 5. 样本构建只能显式标记 partial
.\.venv\Scripts\python.exe backend/tools/shortline_dataset.py build --allow-partial

# 6. 与官方原生聚合逐字段核对，结果写入 verification_report 和 manifest
.\.venv\Scripts\python.exe backend/tools/shortline_dataset.py verify-native `
  --symbol LUNAUSDT --month 2022-05 --interval 1h

# 7. 查询 T 时点的流动性币池
.\.venv\Scripts\python.exe backend/tools/shortline_dataset.py universe `
  --timestamp 2022-05-01T00:00:00Z --min-history-days 30 `
  --lookback-days 7 --min-median-quote-volume 10000000 --limit 30
```

无筛选条件的全量 sync 必须带 `--confirm-full-download`，避免误触 8–12 GB 下载。worker 限制为 1–16。中断下载保留 `.part` 并使用 HTTP Range 恢复；服务端忽略 Range 时安全重下。checksum 不匹配不会覆盖正式分区。

页面入口的 worker 上限收紧为 8；命令行仍保留 1–16，供人工诊断和受控运维使用。页面任务与命令行使用相同的数据目录、校验规则与构建器，不存在第二套下载实现。

所有会写 DATA-1R 的 CLI 命令和页面任务共用数据集根目录的跨进程锁。锁元数据位于 `metadata/dataset_job_lock.json`，公开 owner、run id、父/工作进程 PID 与开始时间但不通过 API 暴露令牌。页面任务先持有整条流水线的锁，再向受控 CLI 子阶段传一次性令牌；普通 CLI 无法绕过，因此不会与页面并发写分区。父服务意外退出但 CLI 子阶段仍存活时，工作进程 PID 会继续阻止第二个任务。

页面任务启动前检查磁盘空间，默认要求至少 15 GB 可用；配置项位于 `runtime.research.shortline_min_free_gb`。生产环境可将 `runtime.research.shortline_jobs_enabled=false` 完全关闭页面任务；`shortline_verify_sample_symbols` 控制正式构建后的原生抽样 symbol 数。

## 5. 质量、故障与恢复

`quality_report.json` 包含：

- 索引范围、应有/已下载/缺失/意外分区；
- 每个合约覆盖率、15m 缺口总数、最多 1000 个缺口区间和重复数；
- 每月分区完整性；
- Funding 重复和超过“声明周期 + 60 秒交易所时间漂移容差”的真实缺口；
- 缺 Funding 的 symbol；
- 报告自身确定性 SHA-256。

长时间数据缺口不会展开成无限时间戳：报告保存准确总数、有界样本和区间。枚举状态显式持久化为 `RUNNING/COMPLETE/FAILED/CANCELLED`；失败可重跑，索引与下载按 key/checksum 幂等合并。

页面 job 历史写入只追加研究运行账本。服务重启后，未结束任务会明确投影为 `failed/interrupted/resumable=true`，保留原阶段和进度；重新启动时依靠已落盘索引、正式 ZIP 与 `.part` 断点续校，不伪装为从未中断。下载中断测试覆盖 HTTP Range 从现有 `.part` 精确续传，并在原子替换前重新通过官方 SHA-256。

研究目录将 `manifest.json` 作为 `dataset_manifest` 登记，并公开数据集指纹、状态和质量报告哈希。只有 `COMPLETE` 数据集可以进入正式全市场研究冻结。

## 6. 当前真实证据与未完成项

2026-08-10 已用官方归档完成最小真实验证：

- 枚举到 LUNAUSDT 15m 共 17 个分区，范围 2021-01 至 2022-05；Funding 同为 17 个分区；
- 下载并通过官方 checksum 验证 LUNAUSDT 2022-05 的 15m 与 Funding 样本；
- 15m 本地聚合的 295 根完整 1h、73 根完整 4h 与官方原生月度归档逐字段零差异；官方 4h 另有 1 根退市前仅含 12/16 子根的部分根，本地明确标记 `INCOMPLETE` 并拒绝用于研究；
- 15m 样本 1180 根、无缺口和重复；Funding 37 条，在 60 秒时间漂移容差下无缺口；
- 该样本因缺少其余 16 个月且索引范围仅一个 symbol，正确标记为 `PARTIAL`，不可用于 `universe_at`。

同日已完成页面任务链路验收：未勾选容量确认时不能启动；勾选后可提交后台任务；任务状态持久化并可轮询阶段/进度；停止后进入 `CANCELLED`，已完成文件保留。正式构建另补充两项阻断：本地存在索引外 15m 分区时拒绝 COMPLETE，任一已下载分区内部存在缺口或重复时拒绝 COMPLETE。构建器按 symbol 流式处理，不再把全市场 K 线对象同时保存在内存中。

尚未完成全市场 8–12 GB 下载、全 symbol 原生聚合抽样、完整 exchangeInfo 状态快照、生产规模耗时/磁盘/恢复演练。Binance 归档未来可能修订历史文件；每次增量运行必须重新读取官方 checksum，manifest 指纹变化后旧预注册不得静默沿用。
