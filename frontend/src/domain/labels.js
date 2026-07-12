export const PAGE_META = {
  dashboard: ["总览", "用户总览", "核心资产、系统策略和币种状态。"],
  accounts: ["交易账户", "用户与账户", "业务用户、交易账户和真实账户同步。"],
  events: ["策略事件配置", "策略事件配置", "利润搬运、仓位恢复、亏损腿减仓。"],
  plans: ["执行计划", "第一阶段执行计划", "真实仓位触发判断、计划动作和风控拦截。"],
  symbol: ["币种详情", "币种详情 / 事件时间线", "单币种多空仓位、权益曲线和事件时间线。"],
  risk: ["风控中心", "管理员风控中心", "运行概览、风险告警、审计日志和快捷操作。"],
  reports: ["报表中心", "每日复盘报告", "Markdown 日报和 SVG 曲线图。"],
  logs: ["事件日志", "策略事件日志", "父事件、子成交和执行原因。"],
};

export function stateLabel(value) {
  const map = {
    REAL_POSITION: "真实持仓",
    BALANCE: "平衡",
    BALANCED: "平衡",
    SKEWED_LONG: "净多偏斜",
    SKEWED_SHORT: "净空偏斜",
    TREND_UP: "趋势上涨",
    TREND_DOWN: "趋势下跌",
    REANCHORING: "重锚中",
    TREND_UP_REDUCING_SHORT: "上涨减空",
    TREND_DOWN_REDUCING_LONG: "下跌减多",
    RECOVERING_FROM_UP: "上涨后恢复",
    RECOVERING_FROM_DOWN: "下跌后恢复",
  };
  return map[value] || value;
}

export function eventLabel(value) {
  const map = {
    PROFIT_TRANSFER_UP: "利润搬运（向上）",
    PROFIT_TRANSFER_DOWN: "利润搬运（向下）",
    POSITION_RECOVERY_UP: "仓位恢复（上涨后）",
    POSITION_RECOVERY_DOWN: "仓位恢复（下跌后）",
    LOSS_SIDE_REDUCTION_UP: "亏损腿减仓（空头）",
    LOSS_SIDE_REDUCTION_DOWN: "亏损腿减仓（多头）",
    SYNC_REQUIRED: "等待账户同步",
    HEDGE_MODE_REQUIRED: "Hedge Mode 未通过",
    ACCOUNT_CONFIG_DISABLED: "运行配置未启用",
    NO_REAL_POSITION: "无真实持仓",
    NO_TRIGGER: "未触发",
  };
  return map[value] || value;
}

export function statusLabel(value) {
  const map = {
    read_only: "只读",
    active: "正常",
    running: "运行中",
    paused: "已暂停",
    paused_by_admin: "管理员暂停",
    emergency_stopped: "急停中",
    unassigned: "未分配",
    disabled: "已禁用",
    synced: "已同步",
    unsynced: "未同步",
    missing_credentials: "未配置凭证",
    error: "同步失败",
    plan_only: "计划演练",
    planned: "已生成",
    blocked: "已拦截",
    no_action: "无动作",
    confirmed: "已确认",
  };
  return map[value] || value || "-";
}

export function statusColor(value) {
  if (["active", "running"].includes(value)) return "green";
  if (["emergency_stopped", "disabled"].includes(value)) return "red";
  if (["paused", "paused_by_admin"].includes(value)) return "orange";
  return "blue";
}

export function modeLabel(value) {
  const map = {
    dry_run: "只读",
    read_only: "只读",
    testnet: "测试网",
    live: "实盘",
  };
  return map[value] || value || "-";
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
  if (value === "REAL_POSITION") return "green";
  if (["BALANCE", "BALANCED"].includes(value)) return "blue";
  if (value.includes("SKEWED")) return "orange";
  if (value === "REANCHORING") return "green";
  if (value.includes("REDUCING")) return "orange";
  if (value.includes("RECOVERING")) return "green";
  if (value.includes("DOWN")) return "red";
  return "green";
}
