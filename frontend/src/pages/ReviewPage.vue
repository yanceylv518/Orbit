<template>
  <section class="page active">
    <div class="page-toolbar">
      <div>
        <h2>{{ activeTab === "execution" ? "实盘执行复盘" : "历史日报" }}</h2>
        <p>
          {{ activeTab === "execution"
            ? "用同期 paper 基准拆分策略表现、执行偏差与真实交易成本。"
            : "查看旧网格与平台运行期间生成的日报和事件日志。" }}
        </p>
      </div>
      <div class="action-row" role="tablist" aria-label="复盘工作区">
        <button class="tab" :class="{ active: activeTab === 'execution' }" @click="activeTab = 'execution'">
          执行复盘
        </button>
        <button class="tab" :class="{ active: activeTab === 'daily' }" @click="activeTab = 'daily'">
          历史日报
        </button>
      </div>
    </div>

    <ReportsPage v-if="activeTab === 'daily'" />

    <template v-else>
      <div class="metric-grid">
        <MetricCard
          label="累计 paper 偏差"
          :value="metricPercent(equity.cumulative_deviation_pct)"
          note="实盘归一化权益减 paper 归一化权益"
          :value-class="deviationClass(equity.cumulative_deviation_pct)"
        />
        <MetricCard
          label="最近逐周偏差"
          :value="metricPercent(equity.latest_weekly_deviation_pct)"
          note="最近 ISO 周的实盘收益减 paper 收益"
          :value-class="deviationClass(equity.latest_weekly_deviation_pct)"
        />
        <MetricCard
          label="结构性跟踪比例"
          :value="equity.structural_tracking_ratio == null ? '-' : percent(Number(equity.structural_tracking_ratio) * 100)"
          note="最低名义额与取整后可表达的目标比例"
        />
        <MetricCard
          label="权益观测"
          :value="equity.points?.length || 0"
          note="来自只追加 LIVE-2 权益账本"
        />
      </div>

      <article class="panel equity-review-panel">
        <div class="panel-head">
          <div>
            <h3>实盘与 paper 归一化权益</h3>
            <p class="muted">首个有效同步点统一为 1.0；曲线差异只展示，不自动推断原因。</p>
          </div>
          <StatusBadge :text="equity.status || 'NO_OBSERVATIONS'" :color="equity.status === 'READY' ? 'green' : 'orange'" />
        </div>
        <div v-if="!equity.points?.length" class="empty-state">
          配置专用实盘账户并在 TB4 清单 READY 后同步，才会开始记录权益对照。
        </div>
        <div v-else class="equity-chart">
          <MultiLineChart
            :data="equity.points"
            :keys="['live_normalized', 'paper_normalized']"
            :colors="['#37d391', '#3987e5']"
            :width="720"
            :height="220"
          />
          <div class="chart-legend">
            <span><i class="live-line"></i>实盘</span>
            <span><i class="paper-line"></i>paper</span>
            <span>最后同步 {{ timeText(equity.points.at(-1)?.synced_at_ms) }}</span>
          </div>
        </div>
      </article>

      <div class="review-grid">
        <article class="panel">
          <div class="panel-head">
            <div>
              <h3>滑点与费用累计</h3>
              <p class="muted">仅汇总执行账本中的已完成轮次；不同手续费资产不做汇率换算。</p>
            </div>
          </div>
          <div class="metric-grid compact-metrics">
            <MetricCard label="完成轮次" :value="reports.length" note="ROUND_COMPLETED" />
            <MetricCard label="尝试订单" :value="costSummary.attempted" note="排除尘埃与低于最低额" />
            <MetricCard
              label="名义加权滑点"
              :value="costSummary.weightedSlippageBps == null ? '-' : `${fmt(costSummary.weightedSlippageBps, 3)} bps`"
              note="按实际成交名义绝对值加权"
            />
            <MetricCard
              label="失败 / 证据异常"
              :value="costSummary.errorCount"
              note="失败、部分成交或取证异常"
              :value-class="costSummary.errorCount ? 'negative' : ''"
            />
          </div>
          <div class="fee-list">
            <div v-for="item in costSummary.fees" :key="item.asset">
              <span>{{ item.asset }}</span><strong class="mono">{{ fmt(item.amount, 8) }}</strong>
            </div>
            <p v-if="!costSummary.fees.length" class="muted">尚无可按资产汇总的手续费记录。</p>
            <p v-if="costSummary.mixedFeeRows" class="muted">
              {{ costSummary.mixedFeeRows }} 行返回多个手续费资产，保留在逐单明细中，未混加为单一总额。
            </p>
          </div>
        </article>

        <article class="panel checkpoint-panel">
          <div class="panel-head">
            <div>
              <h3>LIVE-SMALL 三个月检查点</h3>
              <p class="muted">只允许在日历检查点评估；短期盈利不会提前授权加仓。</p>
            </div>
            <StatusBadge :text="checkpoint.badge" :color="checkpoint.due ? 'orange' : 'blue'" />
          </div>
          <dl class="checkpoint-dates">
            <div><dt>实盘观测起点</dt><dd>{{ timeText(checkpoint.startMs) }}</dd></div>
            <div><dt>下次检查</dt><dd>{{ timeText(checkpoint.nextMs) }}</dd></div>
          </dl>
          <div class="condition-list">
            <div v-for="condition in checkpoint.conditions" :key="condition.label" class="condition-item">
              <StatusBadge :text="condition.state" :color="condition.color" />
              <div><strong>{{ condition.label }}</strong><p class="muted">{{ condition.note }}</p></div>
            </div>
          </div>
          <p class="protocol-note">
            所有条件同时满足时，每次最多增至当前规模的 1.5 倍；无法解释的系统性偏离必须人工书面归因，
            页面不会自动判定通过。
          </p>
        </article>
      </div>

      <article class="panel report-history-panel">
        <div class="panel-head">
          <div>
            <h3>逐轮执行报告</h3>
            <p class="muted">按执行账本倒序读取，不改变账本、执行状态或策略参数。</p>
          </div>
          <button v-if="isAdmin" class="button ghost small" :disabled="store.liveExecutionReportsBusy" @click="loadReports">
            {{ store.liveExecutionReportsBusy ? "刷新中" : "刷新报告" }}
          </button>
        </div>
        <div v-if="!isAdmin" class="empty-state">执行报告含全账户成交证据，仅管理员可查看。</div>
        <div v-else-if="store.liveExecutionReportsError" class="service-alert">{{ store.liveExecutionReportsError }}</div>
        <div v-else-if="!reports.length" class="empty-state">尚无已完成的自动执行轮次。</div>
        <div v-else class="report-history-layout">
          <div class="table-wrap report-list">
            <table>
              <thead><tr><th>再平衡时间</th><th>结果</th><th>成功</th><th>失败</th></tr></thead>
              <tbody>
                <tr
                  v-for="report in reports"
                  :key="reportKey(report)"
                  :class="{ selected: reportKey(report) === reportKey(selectedReport) }"
                  @click="selectedReportKey = reportKey(report)"
                >
                  <td>{{ timeText(report.rebalance_time_ms) }}</td>
                  <td><StatusBadge :text="report.status" :color="report.status === 'COMPLETED' ? 'green' : 'red'" /></td>
                  <td>{{ report.matched_count || 0 }}/{{ report.attempted_count || 0 }}</td>
                  <td :class="Number(report.failed_count || 0) ? 'negative' : ''">{{ report.failed_count || 0 }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <div class="table-wrap report-detail">
            <table>
              <thead>
                <tr><th>市场</th><th>状态</th><th>成交量</th><th>成交均价</th><th>滑点</th><th>手续费</th></tr>
              </thead>
              <tbody>
                <tr v-for="row in selectedReport?.rows || []" :key="row.symbol">
                  <td><strong>{{ row.symbol }}</strong></td>
                  <td><StatusBadge :text="rowStatusText(row.status)" :color="rowStatusColor(row.status)" /></td>
                  <td class="mono">{{ fmt(row.executed_quantity, 8) }}</td>
                  <td class="mono">{{ fmt(row.average_price, 6) }}</td>
                  <td class="mono">{{ row.slippage_bps == null ? "-" : `${fmt(row.slippage_bps, 3)} bps` }}</td>
                  <td class="mono">{{ fmt(row.fee, 8) }} {{ row.fee_assets?.join("/") || "-" }}</td>
                </tr>
                <tr v-if="!selectedReport?.rows?.length"><td colspan="6" class="muted">该轮没有逐单记录。</td></tr>
              </tbody>
            </table>
          </div>
        </div>
      </article>
    </template>
  </section>
</template>

<script setup>
import { computed, onMounted, ref, watch } from "vue";
import MetricCard from "../components/MetricCard.vue";
import MultiLineChart from "../components/MultiLineChart.vue";
import StatusBadge from "../components/StatusBadge.vue";
import { fmt, percent } from "../core/format.js";
import ReportsPage from "./ReportsPage.vue";
import {
  isAdmin,
  isAuthenticated,
  loadLiveExecutionReports,
  store,
} from "../stores/appStore.js";

const activeTab = ref("execution");
const selectedReportKey = ref("");
const equity = computed(() => store.state?.live_reconciliation?.equity || {
  status: "NO_OBSERVATIONS",
  points: [],
  weekly_points: [],
});
const liveExecution = computed(() => store.state?.live_execution || {});
const reports = computed(() => store.liveExecutionReports || []);
const selectedReport = computed(() => (
  reports.value.find((report) => reportKey(report) === selectedReportKey.value) || reports.value[0] || null
));

function reportKey(report) {
  return report ? `${report.execution_epoch || ""}:${report.rebalance_time_ms || 0}` : "";
}

watch(reports, (items) => {
  if (!items.some((report) => reportKey(report) === selectedReportKey.value)) {
    selectedReportKey.value = reportKey(items[0]);
  }
}, { immediate: true });

async function loadReports() {
  if (isAdmin.value) await loadLiveExecutionReports(100);
}

onMounted(loadReports);
watch(isAuthenticated, (authenticated) => {
  if (authenticated) loadReports();
});

const costSummary = computed(() => {
  let attempted = 0;
  let errorCount = 0;
  let weightedSlip = 0;
  let notional = 0;
  let mixedFeeRows = 0;
  const fees = new Map();
  for (const report of reports.value) {
    attempted += Number(report.attempted_count || 0);
    errorCount += Number(report.failed_count || 0) + Number(report.evidence_error_count || 0);
    for (const row of report.rows || []) {
      const quantity = Math.abs(Number(row.executed_quantity || 0));
      const price = Number(row.average_price || 0);
      const slip = Number(row.slippage_bps);
      const rowNotional = quantity * price;
      if (rowNotional > 0 && Number.isFinite(slip)) {
        weightedSlip += rowNotional * slip;
        notional += rowNotional;
      }
      const assets = row.fee_assets || [];
      if (assets.length === 1) {
        fees.set(assets[0], (fees.get(assets[0]) || 0) + Number(row.fee || 0));
      } else if (assets.length > 1) {
        mixedFeeRows += 1;
      }
    }
  }
  return {
    attempted,
    errorCount,
    weightedSlippageBps: notional ? weightedSlip / notional : null,
    fees: [...fees.entries()].map(([asset, amount]) => ({ asset, amount })),
    mixedFeeRows,
  };
});

function addCalendarMonths(timestamp, months) {
  const source = new Date(timestamp);
  const target = new Date(Date.UTC(
    source.getUTCFullYear(),
    source.getUTCMonth() + months,
    1,
    source.getUTCHours(),
    source.getUTCMinutes(),
    source.getUTCSeconds(),
    source.getUTCMilliseconds(),
  ));
  const lastDay = new Date(Date.UTC(target.getUTCFullYear(), target.getUTCMonth() + 1, 0)).getUTCDate();
  target.setUTCDate(Math.min(source.getUTCDate(), lastDay));
  return target.getTime();
}

const checkpoint = computed(() => {
  const startMs = Number(equity.value.points?.[0]?.synced_at_ms || 0);
  if (!startMs) {
    return {
      startMs: null,
      nextMs: null,
      due: false,
      badge: "等待首个观测点",
      conditions: [
        { label: "满 3 个日历月", state: "未开始", color: "orange", note: "权益账本尚无实盘起点。" },
        { label: "未触发 30% 停止线", state: "待数据", color: "orange", note: "需要实盘与 paper 回撤水位。" },
        { label: "偏差已完全归因", state: "人工复核", color: "blue", note: "必须以滑点、成交时点和结构性不可执行逐项解释。" },
      ],
    };
  }
  const now = Date.now();
  let nextMs = addCalendarMonths(startMs, 3);
  while (nextMs <= now) nextMs = addCalendarMonths(nextMs, 3);
  const previousMs = addCalendarMonths(nextMs, -3);
  const due = now >= previousMs && previousMs > startMs;
  const threshold = Number(equity.value.stop_threshold_pct ?? 30);
  const liveDd = equity.value.live_drawdown_pct;
  const paperDd = equity.value.paper_drawdown_pct;
  const drawdownSafe = liveDd != null && paperDd != null
    && Number(liveDd) < threshold && Number(paperDd) < threshold;
  const executionStopped = ["PROTOCOL_STOP", "PROTOCOL_VIOLATION", "EMERGENCY_STOPPED", "DATA_INTEGRITY_ERROR"]
    .includes(liveExecution.value.status);
  return {
    startMs,
    nextMs,
    due,
    badge: `${Math.max(0, Math.ceil((nextMs - now) / 86400000))} 天后检查`,
    conditions: [
      {
        label: "到达日历检查点",
        state: due ? "可评估" : "未到期",
        color: due ? "green" : "blue",
        note: `下一次检查时间 ${timeText(nextMs)}。`,
      },
      {
        label: "当前未处于停止状态",
        state: drawdownSafe && !executionStopped ? "未停止" : "不满足",
        color: drawdownSafe && !executionStopped ? "green" : "red",
        note: `实盘回撤 ${metricPercent(liveDd)}，paper 回撤 ${metricPercent(paperDd)}，停机线 ${percent(threshold)}。`,
      },
      {
        label: "偏差可完全归因",
        state: "人工复核",
        color: "blue",
        note: "系统没有足够证据自动判断“无法解释的系统性偏离”。",
      },
    ],
  };
});

function metricPercent(value) {
  return value == null ? "-" : percent(Number(value));
}

function deviationClass(value) {
  return value != null && Math.abs(Number(value)) > 1 ? "negative" : "";
}

function timeText(value) {
  if (value === null || value === undefined || value === "") return "-";
  const date = new Date(Number(value) || value);
  return Number.isNaN(date.getTime()) ? "-" : date.toLocaleString("zh-CN", { hour12: false });
}

function rowStatusText(value) {
  return ({
    EXECUTED_MATCH: "完全成交",
    PARTIAL_FILL: "部分成交",
    ORDER_FAILED: "下单失败",
    SKIPPED_DUST: "尘埃跳过",
    SKIPPED_BELOW_MIN: "低于最低额",
  })[value] || value;
}

function rowStatusColor(value) {
  return ["EXECUTED_MATCH", "SKIPPED_DUST", "SKIPPED_BELOW_MIN"].includes(value) ? "green" : "red";
}
</script>

<style scoped>
.equity-review-panel, .review-grid, .report-history-panel { margin-top: 14px; }
.equity-chart { min-height: 260px; padding-top: 10px; }
.chart-legend { display: flex; flex-wrap: wrap; gap: 18px; align-items: center; color: var(--muted); }
.chart-legend span { display: inline-flex; align-items: center; gap: 6px; }
.chart-legend i { width: 18px; height: 2px; display: inline-block; }
.live-line { background: #37d391; }
.paper-line { background: #3987e5; }
.review-grid { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 14px; }
.compact-metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.fee-list { margin-top: 14px; display: grid; gap: 8px; }
.fee-list > div { display: flex; justify-content: space-between; border-top: 1px solid var(--line); padding-top: 8px; }
.checkpoint-dates { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; margin: 0 0 16px; }
.checkpoint-dates div { padding: 12px; background: var(--panel-inset); border-radius: 8px; }
.checkpoint-dates dt { color: var(--muted); font-size: 12px; }
.checkpoint-dates dd { margin: 5px 0 0; font-weight: 700; }
.condition-list { display: grid; gap: 12px; }
.condition-item { display: grid; grid-template-columns: auto 1fr; gap: 10px; align-items: start; }
.condition-item p { margin: 3px 0 0; }
.protocol-note { margin: 16px 0 0; padding-top: 12px; border-top: 1px solid var(--line); color: var(--muted); }
.report-history-layout { display: grid; grid-template-columns: minmax(320px, .8fr) minmax(560px, 1.4fr); gap: 14px; }
.report-list tr { cursor: pointer; }
.report-list tr.selected td { background: color-mix(in srgb, var(--accent) 12%, transparent); }
.empty-state { padding: 30px 12px; text-align: center; color: var(--muted); }
@media (max-width: 1050px) {
  .review-grid, .report-history-layout { grid-template-columns: 1fr; }
}
@media (max-width: 680px) {
  .compact-metrics, .checkpoint-dates { grid-template-columns: 1fr; }
}
</style>
