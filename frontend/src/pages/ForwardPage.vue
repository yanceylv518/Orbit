<template>
  <section class="page active">
    <div class="system-health-strip" aria-label="实盘系统健康">
      <div class="system-health-title">
        <span>系统健康</span>
        <small>每 2.5 秒随服务状态刷新</small>
      </div>
      <div class="metric-grid system-health-grid">
        <MetricCard label="模拟盘前向" help="纸面前向" :value="forwardStatus" :note="paperHealthNote" />
        <MetricCard
          label="自动执行"
          :value="executionStatusText"
          :note="liveExecution.stop_reason || (liveExecution.enabled ? '执行闸门已开启' : '默认关闭，不会下单')"
          :value-class="executionHealthClass"
        />
        <MetricCard
          label="最近持仓核对"
          :value="reconciliationHealthValue"
          :note="reconciliationHealthNote"
          :value-class="Number(positionResult.deviation_count || 0) ? 'negative' : ''"
        />
        <MetricCard
          label="实盘账户同步"
          :value="syncAgeText"
          :note="reconciliation.account_synced_at ? timeText(reconciliation.account_synced_at) : reconciliationStatusText"
          :value-class="reconciliation.status === 'READY' ? '' : 'negative'"
        />
      </div>
    </div>

    <div class="metric-grid">
      <MetricCard label="前向状态" :value="forwardStatus" :note="forwardNote" />
      <MetricCard
        label="实盘换算资金"
        :value="`${fmt(checklist.capital_usdt)} USDT`"
        note="仅用于只读清单，不进入策略状态"
      />
      <MetricCard
        label="目标仓位总价值"
        help="名义金额"
        :value="`${fmt(summary.target_gross_notional_usdt)} USDT`"
        :note="`占资金比例 ${percent(Number(summary.target_gross_weight || 0) * 100)}`"
      />
      <MetricCard
        label="可执行覆盖"
        :value="percent(Number(summary.executable_notional_ratio || 0) * 100)"
        :note="`${summary.executable_symbols || 0} 个市场可执行`"
        :value-class="Number(summary.executable_notional_ratio || 0) < 0.8 ? 'negative' : ''"
      />
    </div>

    <div v-if="checklist.rules_stale" class="service-alert">
      Binance 交易规则快照已超过刷新周期。清单仅供核对，刷新并复核规则前不要据此手动下单。
    </div>

    <article class="panel">
      <div class="panel-head">
        <div>
          <h3>本周调仓清单</h3>
          <p class="muted checklist-meta">
            小资金实盘 · 每周调仓 <HelpTip term="再平衡" /> {{ timeText(checklist.rebalance_time_ms) }}
            · 使用行情 {{ timeText(checklist.close_time_ms) }}
            · 规则 {{ checklist.rules?.fetched_at || "-" }}
          </p>
        </div>
        <button class="button ghost small" :disabled="checklist.status !== 'READY'" @click="downloadCsv">
          导出成交记录模板 CSV
        </button>
      </div>

      <div v-if="checklist.status !== 'READY'" class="empty-state">
        {{ emptyText }}
      </div>
      <div v-else class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>市场</th>
              <th>方向</th>
              <th>权重</th>
              <th>目标仓位价值 <HelpTip term="名义金额" /></th>
              <th>较上次变化</th>
              <th>目标数量</th>
              <th>最低额 / 步进</th>
              <th>执行状态</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in checklist.rows" :key="row.symbol">
              <td><strong>{{ row.symbol }}</strong><div class="muted mono">{{ fmt(row.close_price, 4) }}</div></td>
              <td>
                <StatusBadge :text="directionText(row.direction)" :color="directionColor(row.direction)" />
              </td>
              <td class="mono">{{ percent(Number(row.weight || 0) * 100, 3) }}</td>
              <td class="mono">{{ fmt(row.target_notional_usdt, 4) }} USDT</td>
              <td class="mono" :class="cls(row.notional_change_usdt)">
                {{ signed(row.notional_change_usdt) }} USDT
              </td>
              <td class="mono">{{ quantityText(row) }}</td>
              <td class="mono">
                {{ fmt(row.min_notional_usdt) }} USDT
                <div class="muted">step {{ row.quantity_step }}</div>
              </td>
              <td>
                <StatusBadge :text="checklistStatusText(row.status)" :raw="row.status" :color="checklistStatusColor(row.status)" />
                <div class="muted row-action">{{ row.action }}</div>
              </td>
            </tr>
          </tbody>
          <tfoot>
            <tr>
              <td colspan="3"><strong>目标仓位总价值</strong></td>
              <td class="mono">{{ fmt(summary.target_gross_notional_usdt, 4) }} USDT</td>
              <td></td>
              <td class="mono">{{ fmt(summary.executable_gross_notional_usdt, 4) }} USDT 可执行</td>
              <td></td>
              <td>{{ summary.below_minimum_symbols || 0 }} 个低于最低额</td>
            </tr>
          </tfoot>
        </table>
      </div>
    </article>

    <article class="panel guard-panel">
      <div class="panel-head">
        <div>
          <h3>自动下单保护规则</h3>
          <p class="muted">
            小资金实盘第二版协议只允许执行上面的冻结清单。自动下单默认关闭；启用后仍受金额上限、
            单向持仓、规则时效、30% 回撤停止和防重复下单账本约束。
          </p>
        </div>
        <button
          class="button danger small"
          :disabled="!liveExecution.enabled || liveExecution.status === 'EMERGENCY_STOPPED'"
          @click="stopLiveExecution"
        >
          急停自动执行
        </button>
      </div>
    </article>

    <div class="metric-grid reconciliation-metrics">
      <MetricCard
        label="自动执行"
        :value="executionStatusText"
        :note="liveExecution.execution_epoch ? `执行批次 ${liveExecution.execution_epoch}` : '须修改配置并重启才能启用'"
        :value-class="liveExecution.status === 'ENABLED' ? '' : 'negative'"
      />
      <MetricCard
        label="最近执行轮次"
        :value="timeText(executionReport.rebalance_time_ms)"
        :note="executionReport.status ? `${enumLabel(executionReport.status)}（${executionReport.status}）` : '尚无执行报告'"
      />
      <MetricCard
        label="逐单成功率"
        :value="executionReport.success_ratio == null ? '-' : percent(Number(executionReport.success_ratio) * 100)"
        :note="`${executionReport.matched_count || 0}/${executionReport.attempted_count || 0} 笔完全成交`"
        :value-class="Number(executionReport.failed_count || 0) ? 'negative' : ''"
      />
      <MetricCard
        label="失败 / 证据异常"
        :value="Number(executionReport.failed_count || 0) + Number(executionReport.evidence_error_count || 0)"
        :note="liveExecution.stop_reason || '失败不自动追单'"
        :value-class="Number(executionReport.failed_count || 0) + Number(executionReport.evidence_error_count || 0) ? 'negative' : ''"
      />
    </div>

    <article class="panel">
      <div class="panel-head">
        <div>
          <h3>自动执行逐单比对</h3>
          <p class="muted checklist-meta">
            清单 → 订单意图 → Binance 回执 → 成交与手续费，全链路只追加留痕。
          </p>
        </div>
        <StatusBadge
          :text="enumLabel(executionReport.status || liveExecution.status || 'DISABLED')"
          :raw="executionReport.status || liveExecution.status || 'DISABLED'"
          :color="executionReport.status === 'COMPLETED_WITH_ERRORS' ? 'red' : (executionReport.status ? 'green' : 'orange')"
        />
      </div>
      <div v-if="!executionReport.rows?.length" class="empty-state">
        尚无自动执行报告。默认配置不会发送任何订单。
      </div>
      <div v-else class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>市场</th><th>状态</th><th>目标数量</th><th>下单数量</th>
              <th>成交数量</th><th>成交均价</th><th>成交价偏差 <HelpTip term="滑点" /></th><th>手续费</th><th>异常</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in executionReport.rows" :key="row.symbol">
              <td><strong>{{ row.symbol }}</strong></td>
              <td><StatusBadge :text="executionRowText(row.status)" :raw="row.status" :color="executionRowColor(row.status)" /></td>
              <td class="mono">{{ signedQuantity(row.target_quantity) }}</td>
              <td class="mono">{{ fmt(row.requested_quantity, 8) }}</td>
              <td class="mono">{{ fmt(row.executed_quantity, 8) }}</td>
              <td class="mono">{{ fmt(row.average_price, 6) }}</td>
              <td class="mono" :class="cls(-Math.abs(Number(row.slippage_bps || 0)))">
                {{ row.slippage_bps == null ? '-' : `${fmt(row.slippage_bps, 3)} bps` }}
              </td>
              <td class="mono">{{ fmt(row.fee, 6) }} {{ row.fee_assets?.join('/') || 'USDT' }}</td>
              <td :class="row.error ? 'negative' : 'muted'">{{ row.error || "-" }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </article>

    <div class="metric-grid reconciliation-metrics">
      <MetricCard
        label="实盘核对账户"
        :value="reconciliation.account_id || '未配置'"
        :note="reconciliationStatusText"
        :value-class="reconciliation.status === 'READY' ? '' : 'negative'"
      />
      <MetricCard
        label="执行正确率"
        :value="percent(Number(positionResult.accuracy_ratio || 0) * 100)"
        :note="`${positionResult.correct_count || 0}/${positionResult.total_count || 0} 项符合`"
        :value-class="Number(positionResult.deviation_count || 0) ? 'negative' : ''"
      />
      <MetricCard
        label="持仓偏差"
        :value="positionResult.deviation_count || 0"
        note="只提示，由用户手动处理"
        :value-class="Number(positionResult.deviation_count || 0) ? 'negative' : ''"
      />
      <MetricCard
        label="实盘与模拟累计差距"
        help="纸面前向"
        :value="equityResult.cumulative_deviation_pct == null ? '-' : percent(equityResult.cumulative_deviation_pct)"
        :note="`结构性可执行比例 ${percent(Number(equityResult.structural_tracking_ratio || 0) * 100)}`"
        :value-class="cls(equityResult.cumulative_deviation_pct)"
      />
    </div>

    <article class="panel">
      <div class="panel-head">
        <div>
          <h3>真实持仓是否符合计划？</h3>
          <p class="muted checklist-meta">
            同步 {{ timeText(reconciliation.account_synced_at) }} ·
            数量容差 = 步进 + 目标数量的 {{ fmt(reconciliation.quantity_tolerance_pct) }}%
          </p>
        </div>
        <StatusBadge
          :text="reconciliation.status === 'READY' ? (positionResult.status === 'MATCH' ? '全部符合' : '存在偏差') : '尚未就绪'"
          :color="reconciliation.status === 'READY' && positionResult.status === 'MATCH' ? 'green' : 'orange'"
        />
      </div>
      <div v-if="reconciliation.status !== 'READY'" class="empty-state">
        {{ reconciliationStatusText }}
      </div>
      <div v-else class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>市场</th><th>核对状态</th><th>目标数量</th><th>实际数量</th>
              <th>差额</th><th>容差</th><th>方向</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in positionResult.rows" :key="row.symbol">
              <td><strong>{{ row.symbol }}</strong></td>
              <td><StatusBadge :text="reconciliationRowText(row.status)" :raw="row.status" :color="reconciliationRowColor(row.status)" /></td>
              <td class="mono">{{ signedQuantity(row.target_quantity) }}</td>
              <td class="mono">{{ signedQuantity(row.actual_quantity) }}</td>
              <td class="mono" :class="cls(-Math.abs(Number(row.difference_quantity || 0)))">
                {{ signedQuantity(row.difference_quantity) }}
              </td>
              <td class="mono">{{ fmt(row.tolerance_quantity, 8) }}</td>
              <td>{{ row.direction_match ? "一致" : "不一致" }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </article>

    <article class="panel review-handoff-panel">
      <div class="panel-head">
        <div>
          <h3>执行结果进入复盘</h3>
          <p class="muted checklist-meta">
            实盘与模拟基准的权益曲线、每轮报告、成交价偏差和手续费分析已集中到复盘页。
          </p>
        </div>
        <button class="button ghost small" @click="setActivePage('review')">查看完整复盘</button>
      </div>
    </article>
  </section>
</template>

<script setup>
import { computed } from "vue";
import MetricCard from "../components/MetricCard.vue";
import HelpTip from "../components/HelpTip.vue";
import StatusBadge from "../components/StatusBadge.vue";
import { cls, fmt, percent } from "../core/format.js";
import { enumLabel } from "../domain/labels.js";
import { post, setActivePage, store } from "../stores/appStore.js";

const forward = computed(() => store.state?.trend_forward || {});
const checklist = computed(() => forward.value.execution_checklist || {
  status: "NOT_AVAILABLE",
  capital_usdt: 0,
  rows: [],
  summary: {},
});
const summary = computed(() => checklist.value.summary || {});
const reconciliation = computed(() => store.state?.live_reconciliation || {
  status: "ACCOUNT_NOT_CONFIGURED",
  account_id: null,
  positions: null,
  equity: { points: [] },
});
const positionResult = computed(() => reconciliation.value.positions || {});
const equityResult = computed(() => reconciliation.value.equity || { points: [] });
const liveExecution = computed(() => store.state?.live_execution || {
  enabled: false,
  status: "DISABLED",
  latest_report: null,
});
const executionReport = computed(() => liveExecution.value.latest_report || {});
const executionStatusText = computed(() => enumLabel(liveExecution.value.status));
const reconciliationStatusText = computed(() => ({
  ACCOUNT_NOT_CONFIGURED: "尚未选择用于小资金实盘的专用账户",
  AWAITING_ACCOUNT_SYNC: "等待专用实盘账户首次同步",
  ACCOUNT_NOT_SYNCED: "专用账户同步失败，或 API 凭证尚未就绪",
  ACCOUNT_NOT_LIVE: "该账户不是真实资金主网账户，不能用于小资金实盘",
  PAPER_NOT_READY: "模拟基准还没有产生第一次每周调仓",
  READY: "持仓核对数据已就绪",
  NOT_VISIBLE: "当前用户无权查看这个实盘账户",
})[reconciliation.value.status] || enumLabel(reconciliation.value.status));
const forwardStatus = computed(() => {
  return enumLabel(forward.value.status);
});
const forwardNote = computed(() => (
  forward.value.status === "NOT_STARTED"
    ? "需先在 Binance 可达主机初始化"
    : `已计分 ${forward.value.scored_periods || 0} 根 4h K线`
));
const paperHealthNote = computed(() => {
  if (forward.value.status === "NOT_STARTED") return "尚未初始化，纸面基准未开始";
  const elapsed = forward.value.elapsed_days;
  const minimum = forward.value.minimum_forward_days;
  return elapsed == null ? forwardNote.value : `已运行 ${elapsed} / ${minimum ?? "-"} 天`;
});
const executionHealthClass = computed(() => (
  ["EMERGENCY_STOPPED", "PROTOCOL_VIOLATION", "PROTOCOL_STOP", "DATA_INTEGRITY_ERROR", "INCOMPLETE_ROUND"]
    .includes(liveExecution.value.status)
    ? "negative"
    : ""
));
const reconciliationHealthValue = computed(() => {
  if (reconciliation.value.status !== "READY") return "未就绪";
  return Number(positionResult.value.deviation_count || 0)
    ? `偏差 ${positionResult.value.deviation_count}`
    : "全部符合";
});
const reconciliationHealthNote = computed(() => (
  reconciliation.value.status === "READY"
    ? `${positionResult.value.correct_count || 0}/${positionResult.value.total_count || 0} 项符合冻结目标`
    : reconciliationStatusText.value
));
const syncAgeText = computed(() => {
  if (!reconciliation.value.account_synced_at) return "无同步记录";
  const syncedAt = new Date(reconciliation.value.account_synced_at).getTime();
  if (Number.isNaN(syncedAt)) return "时间无效";
  const seconds = Math.max(0, Math.floor((Date.now() - syncedAt) / 1000));
  if (seconds < 60) return `${seconds} 秒前`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 分钟前`;
  return `${Math.floor(seconds / 3600)} 小时前`;
});
const emptyText = computed(() => {
  const map = {
    NOT_AVAILABLE: "TB4 前向尚未启动，当前没有可执行目标。",
    AWAITING_FIRST_REBALANCE: "TB4 已暖机，等待第一笔正式前向再平衡后生成清单。",
  };
  return map[checklist.value.status] || "当前没有可执行清单。";
});

function timeText(value) {
  if (value === null || value === undefined || value === "") return "-";
  const text = String(value);
  const input = /^\d+$/.test(text) ? Number(text) : value;
  const date = new Date(input);
  return Number.isNaN(date.getTime())
    ? "-"
    : date.toLocaleString("zh-CN", { hour12: false });
}

function directionText(value) {
  return enumLabel(value);
}

function directionColor(value) {
  return value === "LONG" ? "green" : (value === "SHORT" ? "red" : "blue");
}

function checklistStatusText(value) {
  return enumLabel(value);
}

function checklistStatusColor(value) {
  return value === "EXECUTABLE" ? "green" : (
    value === "FLAT" ? "blue" : "orange"
  );
}

function signed(value) {
  const number = Number(value || 0);
  return `${number >= 0 ? "+" : ""}${fmt(number, 4)}`;
}

function quantityText(row) {
  return row.status === "EXECUTABLE"
    ? `${row.direction === "SHORT" ? "-" : ""}${Number(row.target_quantity).toFixed(8).replace(/0+$/, "").replace(/\.$/, "")}`
    : "0";
}

function signedQuantity(value) {
  const number = Number(value || 0);
  return `${number > 0 ? "+" : ""}${number.toFixed(8).replace(/0+$/, "").replace(/\.$/, "")}`;
}

function reconciliationRowText(value) {
  return enumLabel(value);
}

function reconciliationRowColor(value) {
  return ["MATCH", "EXPECTED_FLAT"].includes(value) ? "green" : "red";
}

function executionRowText(value) {
  return enumLabel(value);
}

function executionRowColor(value) {
  return ["EXECUTED_MATCH", "SKIPPED_DUST", "SKIPPED_BELOW_MIN"].includes(value)
    ? "green"
    : "red";
}

async function stopLiveExecution() {
  const reason = prompt("请输入自动执行急停原因。急停后只能修改配置 epoch 并重启才能恢复：");
  if (!reason?.trim()) return;
  if (!confirm("确认立即停止所有新的 TB4 自动订单？")) return;
  await post("/api/admin/live-execution/emergency-stop", { reason: reason.trim() });
}

function csvCell(value) {
  const text = String(value ?? "");
  return `"${text.replaceAll('"', '""')}"`;
}

function downloadCsv() {
  if (checklist.value.status !== "READY") return;
  const headers = [
    "rebalance_time_utc", "symbol", "direction", "weight", "reference_close",
    "target_notional_usdt", "notional_change_usdt", "target_quantity",
    "checklist_status", "actual_side", "actual_quantity", "average_fill_price",
    "fee_usdt", "binance_order_id", "executed_at_utc", "note",
  ];
  const rebalanceTime = new Date(Number(checklist.value.rebalance_time_ms)).toISOString();
  const lines = [
    headers.map(csvCell).join(","),
    ...checklist.value.rows.map((row) => [
      rebalanceTime,
      row.symbol,
      row.direction,
      row.weight,
      row.close_price,
      row.target_notional_usdt,
      row.notional_change_usdt,
      row.signed_target_quantity,
      row.status,
      "", "", "", "", "", "", "",
    ].map(csvCell).join(",")),
  ];
  const blob = new Blob([`\uFEFF${lines.join("\r\n")}\r\n`], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `orbit-live-small-${rebalanceTime.slice(0, 10)}.csv`;
  link.click();
  URL.revokeObjectURL(url);
}
</script>

<style scoped>
.checklist-meta { margin-top: 4px; }
.row-action { margin-top: 3px; max-width: 190px; white-space: normal; }
.empty-state { padding: 30px 12px; text-align: center; color: var(--muted); }
.guard-panel { margin-top: 14px; }
.guard-panel p { margin-top: 7px; max-width: 980px; }
.reconciliation-metrics { margin-top: 14px; }
.review-handoff-panel { margin-top: 14px; }
tfoot td { border-top: 1px solid var(--line-strong); }
</style>
