export const PAGE_META = {
  home: ["首页", "系统正常吗？", "只显示需要行动的事情和今天最重要的结果。"],
  strategy: ["策略", "这些规则在找什么？", "查看全部策略的图形、筛选条件、买卖规则与运行状态。"],
  dashboard: ["概览", "现在有什么要处理？", "从账户同步到计划确认，按顺序检查每个环节。"],
  accounts: ["账户", "钱和交易权限接在哪里？", "管理用户、交易账户、API 凭证和连接状态。"],
  data: ["", "数据", "查看当前币种和历史数据更新状态。"],
  research: ["研究", "哪些方向值得继续验证？", "保留现有研究页面与流程，本批不改其内容。"],
  forward: ["量化", "系统现在正常吗？", "先看运行结论，再进入实例或复盘核对细节。"],
  signals: ["信号", "今天有值得出手的信号吗？", "查看真实信号、登记做或不做，并对比模拟结果与实际成交。"],
  plans: ["计划", "这次准备怎么调仓？", "先看动作和风险检查，再决定是否确认。"],
  symbol: ["市场", "每个币现在是什么状态？", "查看仓位方向、价格变化和历史动作。"],
  review: ["复盘", "过去执行得怎么样？", "比较实盘和模拟结果，找出费用、成交和计划偏差。"],
  risk: ["风控", "什么情况必须停？", "看账户离 30% 停止线还有多远，以及保护规则是否正常。"],
  reports: ["报告", "过去发生了什么？", "查看每日结果、图表和操作记录。"],
};

// 已移除页面和旧路由锚点统一回到仍在维护的页面。
export const LEGACY_PAGE_ALIASES = {
  live: "forward",
  events: "logs",
};

const ENUM_LABELS = {
  REAL_POSITION: "已有真实持仓",
  BALANCE: "多空仓位平衡",
  BALANCED: "多空仓位平衡",
  SKEWED_LONG: "多头仓位偏多",
  SKEWED_SHORT: "空头仓位偏多",
  TREND_UP: "价格处于上涨趋势",
  TREND_DOWN: "价格处于下跌趋势",
  REANCHORING: "正在按新价格重设基准",
  TREND_UP_REDUCING_SHORT: "上涨中减少空头仓位",
  TREND_DOWN_REDUCING_LONG: "下跌中减少多头仓位",
  RECOVERING_FROM_UP: "上涨结束后恢复仓位",
  RECOVERING_FROM_DOWN: "下跌结束后恢复仓位",
  STOPPED: "已停止",
  PAUSED: "已暂停",
  PROFIT_TRANSFER_UP: "上涨时落袋部分利润",
  PROFIT_TRANSFER_DOWN: "下跌时落袋部分利润",
  POSITION_RECOVERY_UP: "上涨结束后恢复仓位",
  POSITION_RECOVERY_DOWN: "下跌结束后恢复仓位",
  LOSS_SIDE_REDUCTION_UP: "上涨时减少亏损的空头仓位",
  LOSS_SIDE_REDUCTION_DOWN: "下跌时减少亏损的多头仓位",
  SYNC_REQUIRED: "需要先同步账户",
  HEDGE_MODE_REQUIRED: "账户未开启双向持仓模式",
  ACCOUNT_CONFIG_DISABLED: "账户运行配置未启用",
  NO_REAL_POSITION: "账户没有可处理的真实持仓",
  NO_TRIGGER: "价格尚未触发调仓条件",
  read_only: "只读观察",
  active: "正常",
  running: "运行中",
  paused: "已暂停",
  paused_by_admin: "已被管理员暂停",
  emergency_stopped: "已手动急停",
  unassigned: "尚未分配",
  disabled: "已禁用",
  synced: "账户已同步",
  unsynced: "账户尚未同步",
  missing_credentials: "尚未配置 API 凭证",
  error: "同步失败",
  plan_only: "只生成计划，不自动下单",
  planned: "计划已生成",
  blocked: "被风险规则拦截",
  no_action: "本次无需操作",
  confirmed: "已经人工确认",
  dry_run: "只读观察",
  testnet: "交易所测试网",
  live: "真实资金账户",
  NOT_STARTED: "尚未开始",
  RUNNING: "正在运行",
  MATURE: "已达到最短观察期",
  NOT_AVAILABLE: "当前没有可执行计划",
  AWAITING_FIRST_REBALANCE: "等待第一次每周调仓",
  READY: "数据已就绪",
  NO_OBSERVATIONS: "尚无权益记录",
  ACCOUNT_NOT_CONFIGURED: "尚未指定实盘账户",
  AWAITING_ACCOUNT_SYNC: "等待账户首次同步",
  ACCOUNT_NOT_SYNCED: "账户同步尚未成功",
  ACCOUNT_NOT_LIVE: "指定账户不是真实资金账户",
  PAPER_NOT_READY: "模拟基准尚未产生首笔调仓",
  NOT_VISIBLE: "当前用户无权查看",
  DISABLED: "自动下单默认关闭",
  ENABLED: "自动下单已启用",
  EMERGENCY_STOPPED: "已手动急停",
  PROTOCOL_STOP: "触发保护规则，已自动停止",
  PROTOCOL_VIOLATION: "发现计划外操作，已自动停止",
  DATA_INTEGRITY_ERROR: "数据完整性异常，已自动停止",
  INCOMPLETE_ROUND: "上次执行未完成，已自动停止",
  COMPLETED: "本轮执行完成",
  COMPLETED_WITH_ERRORS: "本轮完成，但有异常需要处理",
  EXECUTABLE: "金额符合规则，可以执行",
  BELOW_MIN_NOTIONAL: "金额低于交易所最低限制，按规则不下单",
  FLAT: "按规则保持空仓",
  MARKET_NOT_TRADING: "市场当前不可交易",
  EXECUTED_MATCH: "按计划成交",
  PARTIAL_FILL: "只成交了一部分",
  ORDER_FAILED: "下单失败",
  SKIPPED_DUST: "差额太小，按规则不下单",
  SKIPPED_BELOW_MIN: "金额低于最低限制，按规则不下单",
  MATCH: "持仓与计划一致",
  DEVIATION: "与计划不符（需处理）",
  EXPECTED_FLAT: "按规则空仓（正常）",
  UNEXPECTED_POSITION: "出现计划外持仓（需处理）",
  queued: "等待运行",
  succeeded: "评估完成",
  failed: "评估失败",
  frozen: "规则已经冻结",
  PENDING: "尚未得出结论",
  PASS: "通过预先写定的门槛",
  FAIL: "没有通过预先写定的门槛",
  NO_GO: "没有通过预先写定的门槛",
  GO: "通过预先写定的门槛",
  LOCKBOX_PASS: "锁箱检验通过",
  BACKTEST_CONFIRMED: "历史数据检验已通过",
  PAPER_FORWARD: "正在做模拟盘前向观察",
  LIVE_PILOT: "正在进行小资金实盘",
  DRAFT: "尚未配置",
  FORWARD_READY: "前向已初始化",
  CONFIGURED: "账户已配置",
  PREFLIGHT_READY: "预检已通过",
  ARMED: "已布防，等待首份清单",
  ACTIVE: "真实资金执行中",
  STOPPED: "自动执行已停止",
  VALID: "账本校验正常",
  EMPTY: "账本尚无记录",
  INVALID: "账本校验失败",
  high: "高风险",
  medium: "中风险",
  low: "低风险",
  info: "提示",
  admin: "管理员",
  operator: "操作员",
  viewer: "只读用户",
  user: "普通用户",
  evaluated: "已经完成评估",
  normal: "正常",
  attention: "需要关注",
  warning: "需要关注",
  futures: "永续合约",
  USDT_FUTURES: "USDT 永续合约",
  ohlc: "K 线价格",
  funding: "资金费率",
  series: "时间序列",
  dataset_manifest: "数据版本清单",
  BUY: "买入",
  SELL: "卖出",
  LONG: "做多",
  SHORT: "做空",
  BOTH: "单向持仓",
  SYNC_BINANCE_ACCOUNT: "同步交易所账户",
  RESUME_STOPPED_SYMBOL: "恢复已停止的币种",
  EMERGENCY_STOP: "执行全局急停",
  LIVE_EXECUTION_EMERGENCY_STOP: "急停自动下单",
  EMERGENCY_STOP_LIVE_EXECUTION: "急停自动下单",
  GENERATE_EXECUTION_PLANS: "生成调仓计划",
  CONFIRM_EXECUTION_PLAN: "人工确认调仓计划",
  EXPORT_EXECUTION_PLANS: "导出调仓计划",
  GENERATE_DAILY_REPORT: "生成每日复盘报告",
  SET_BINANCE_CREDENTIALS: "设置交易所 API 凭证",
  START_STRATEGY: "启动旧网格策略",
  PAUSE_STRATEGY: "暂停旧网格策略",
  GLOBAL_EMERGENCY_STOP: "执行全局急停",
  RESUME_AFTER_EMERGENCY_STOP: "急停后恢复旧网格策略",
  UPDATE_ACCOUNT_RUN_CONFIG: "修改账户运行配置",
  UPDATE_EVENT_CONFIG: "修改旧网格事件参数",
  UPSERT_BUSINESS_USER: "保存业务用户",
  UPSERT_EXCHANGE_ACCOUNT: "保存交易账户",
  EXECUTE_LIVE_PLAN: "执行真实资金调仓计划",
  REGIME_TRENDING_BLOCKED: "趋势行情中禁止逆势操作",
  TREND_EXIT_NOT_CONFIRMED: "趋势结束尚未确认",
  MAX_GROSS_EXPOSURE: "仓位总价值超过上限",
  MAX_SYMBOL_DRAWDOWN: "单个币种亏损达到停止线",
};

export function enumLabel(value) {
  if (value === null || value === undefined || value === "") return "-";
  return ENUM_LABELS[value] || `未识别状态（${value}）`;
}

export function enumCodeTitle(value) {
  return value ? `系统原始值：${value}` : "";
}

export function stateLabel(value) {
  return enumLabel(value);
}

export function eventLabel(value) {
  return enumLabel(value);
}

export function statusLabel(value) {
  return enumLabel(value);
}

export function statusColor(value) {
  if (["active", "running"].includes(value)) return "green";
  if (["emergency_stopped", "disabled"].includes(value)) return "red";
  if (["paused", "paused_by_admin"].includes(value)) return "orange";
  return "blue";
}

export function modeLabel(value) {
  return enumLabel(value);
}

export function accountModeLabel(account) {
  if (account.dry_run) return "只读";
  if (account.testnet) return "测试网";
  return "实盘";
}

export function accountModeColor(account) {
  if (account.dry_run) return "blue";
  if (account.testnet) return "orange";
  return "red";
}

export function planStatusColor(value) {
  return value === "planned" ? "green" : (value === "blocked" ? "orange" : "blue");
}

export function boolText(value) {
  return value ? "是" : "否";
}

export function stateColor(value) {
  if (!value) return "blue";
  if (value === "STOPPED") return "red";
  if (value === "PAUSED") return "orange";
  if (value === "REAL_POSITION") return "green";
  if (["BALANCE", "BALANCED"].includes(value)) return "blue";
  if (value.includes("SKEWED")) return "orange";
  if (value === "REANCHORING") return "green";
  if (value.includes("REDUCING")) return "orange";
  if (value.includes("RECOVERING")) return "green";
  if (value.includes("DOWN")) return "red";
  return "green";
}

export const TERM_HELP = {
  回撤: "账户权益从历史最高点回落了多少；实盘或模拟基准达到 30% 时，系统必须自动停止新订单。",
  名义金额: "仓位按当前价格折算出的价值，单位通常是 USDT，不等于实际投入的保证金。",
  滑点: "实际成交价与下单参考价之间的差距；数值越大，成交成本越高。",
  再平衡: "每 7 天根据最新信号重新计算目标仓位，并只交易与当前仓位的差额。",
  Funding: "永续合约多空双方定期互付的资金费，可能是成本，也可能是收入。",
  纸面前向: "不用真钱的模拟盘；参数冻结后，只用未来新行情持续检验策略。",
  锁箱: "预留的一段“考卷”数据，只允许按预先写定的规则打开和使用一次。",
  预注册: "跑数据前先写死参数、成本、数据和及格线，防止事后只挑好看的结果。",
  哈希指纹: "根据内容计算的防篡改校验码；内容变一个字符，校验码通常就会变化。",
  Calmar: "年化收益与最大回撤的比值，表示每承受一单位回撤换来多少收益，越高越好。",
  Sortino: "收益与下行波动的比值，只重点惩罚亏损方向的波动，越高越好。",
};

export const GLOSSARY_TERMS = [
  { term: "回撤", plain: "从最高点亏回了多少", explanation: TERM_HELP.回撤 },
  { term: "名义金额", plain: "仓位按现价值多少钱", explanation: TERM_HELP.名义金额 },
  { term: "滑点", plain: "实际成交价偏了多少", explanation: TERM_HELP.滑点 },
  { term: "再平衡", plain: "每周重新按信号调仓", explanation: TERM_HELP.再平衡 },
  { term: "Funding", plain: "永续合约资金费", explanation: TERM_HELP.Funding },
  { term: "paper / 纸面前向", plain: "不用真钱的未来行情模拟", explanation: TERM_HELP.纸面前向 },
  { term: "锁箱", plain: "只许打开一次的考卷数据", explanation: TERM_HELP.锁箱 },
  { term: "预注册", plain: "跑数前先写死规则", explanation: TERM_HELP.预注册 },
  { term: "哈希 / 指纹", plain: "内容防篡改校验码", explanation: TERM_HELP.哈希指纹 },
  { term: "Calmar", plain: "收益相对最大回撤", explanation: TERM_HELP.Calmar },
  { term: "Sortino", plain: "收益相对亏损方向波动", explanation: TERM_HELP.Sortino },
  { term: "按计划成交", plain: "方向、数量和最终持仓都符合计划", explanation: "系统原始状态为 EXECUTED_MATCH。" },
  { term: "部分成交", plain: "交易所只成交了一部分", explanation: "必须人工关注剩余持仓差额；系统原始状态为 PARTIAL_FILL。" },
  { term: "计划外持仓", plain: "账户里出现目标清单没有的仓位", explanation: "需要立即查明来源并处理；系统原始状态为 UNEXPECTED_POSITION。" },
  { term: "自动停止", plain: "系统拒绝继续发送新订单", explanation: "保护规则、计划外操作、数据异常或未完成轮次都可能触发，不能删除账本绕过。" },
  { term: "手动急停", plain: "管理员立即停止新订单", explanation: "急停后不能在页面直接恢复，必须更换执行批次标识并重启。" },
];

// 冻结候选的本地化只影响展示；ID、原名和冻结内容仍由后端返回并保留为对照证据。
const CANDIDATE_COPY = {
  M0: {
    name: "无条件锚点回归",
    summary: "假设价格偏离固定锚点后会回归，并在计入延迟和交易成本后检验是否仍有收益。",
  },
  F1: {
    name: "资金费率套利必要条件筛选",
    summary: "先检查资金费率收入能否覆盖进出场与调仓成本；连必要条件都不满足时，不继续开发。",
  },
  G1: {
    name: "极端资金费率反转",
    summary: "检验资金费率达到极端水平后，价格是否出现足以覆盖成本的反向变化。",
  },
  G2: {
    name: "资金费率相对强弱动量",
    summary: "比较不同市场的资金费率强弱，检验按相对排名交易后能否获得覆盖成本的收益。",
  },
};

export function candidateCopy(candidate) {
  const localized = CANDIDATE_COPY[candidate?.id];
  return {
    name: localized?.name || candidate?.name || candidate?.id || "未命名候选",
    summary: localized?.summary || candidate?.signal_definition || "该候选尚未提供说明。",
    originalName: candidate?.name || "",
    originalSummary: candidate?.signal_definition || "",
  };
}
