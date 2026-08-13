<template>
  <section class="quant-review">
    <div class="page-toolbar quant-toolbar">
      <div>
        <button class="text-link back-link" @click="setActivePage('forward')">← 返回量化运行</button>
        <h2>量化复盘</h2>
        <p>只回答两个问题：执行有没有忠实遵循计划，收益和损耗由什么构成。</p>
      </div>
      <button v-if="isAdmin" class="button ghost" :disabled="store.liveExecutionReportsBusy" @click="loadReports">
        {{ store.liveExecutionReportsBusy ? "刷新中" : "刷新复盘" }}
      </button>
    </div>

    <div class="review-answer-strip">
      <div><span>执行结论</span><strong :class="executionConclusionClass">{{ executionConclusion }}</strong></div>
      <div><span>收益结论</span><strong>{{ returnConclusion }}</strong></div>
      <div><span>已复盘调仓</span><strong>{{ reports.length }} 次</strong></div>
      <div><span>最近观测</span><strong>{{ latestObservation }}</strong></div>
    </div>

    <article class="panel review-main-panel">
      <div class="panel-head">
        <div>
          <span class="eyebrow">问题一</span>
          <h3>每周执行是否忠实遵循计划？</h3>
          <p class="muted">按执行账本汇总每次调仓；只把已经完整结束的轮次算入复盘。</p>
        </div>
        <StatusBadge :text="executionConclusion" :color="executionErrors ? 'red' : (reports.length ? 'green' : 'orange')" />
      </div>
      <div v-if="!isAdmin" class="empty-state">执行报告含账户成交证据，仅管理员可查看。</div>
      <div v-else-if="store.liveExecutionReportsError" class="service-alert">{{ store.liveExecutionReportsError }}</div>
      <div v-else-if="!reports.length" class="empty-state">尚无完整调仓记录，暂时不能评价执行忠实度。</div>
      <div v-else class="table-wrap">
        <table>
          <thead><tr><th>调仓周</th><th>执行结果</th><th>按计划完成</th><th>失败或异常</th><th>成交价偏差</th><th>结论</th></tr></thead>
          <tbody>
            <tr v-for="row in fidelityRows" :key="row.key">
              <td>{{ row.week }}</td>
              <td><StatusBadge :text="enumLabel(row.status)" :raw="row.status" :color="row.errors ? 'red' : 'green'" /></td>
              <td>{{ row.matched }}/{{ row.attempted }}</td>
              <td :class="row.errors ? 'negative' : ''">{{ row.errors }}</td>
              <td>{{ row.slippage }}</td>
              <td><strong :class="row.errors ? 'negative' : 'positive'">{{ row.errors ? "需要解释" : "忠实执行" }}</strong></td>
            </tr>
          </tbody>
        </table>
      </div>
      <details v-if="selectedReport" class="audit-details review-audit">
        <summary>查看最近一次调仓的逐市场审计记录</summary>
        <div class="table-wrap">
          <table>
            <thead><tr><th>市场</th><th>执行结果</th><th>计划数量</th><th>实际成交</th><th>成交均价</th><th>手续费</th></tr></thead>
            <tbody>
              <tr v-for="row in selectedReport.rows || []" :key="row.symbol">
                <td><strong>{{ row.symbol }}</strong></td>
                <td>{{ enumLabel(row.status) }}</td>
                <td>{{ quantityText(row.target_quantity) }}</td>
                <td>{{ quantityText(row.executed_quantity) }}</td>
                <td>{{ moneyText(row.average_price) }}</td>
                <td>{{ feeText(row) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </details>
    </article>

    <article class="panel review-main-panel">
      <div class="panel-head">
        <div>
          <span class="eyebrow">问题二</span>
          <h3>收益和损耗由什么构成？</h3>
          <p class="muted">只展示账本能够直接支持的项目；策略收益、费用和成交价影响不会混成一个猜测值。</p>
        </div>
        <StatusBadge :text="equity.status === 'READY' ? '已有观测' : '等待数据'" :color="equity.status === 'READY' ? 'blue' : 'orange'" />
      </div>
      <div class="table-wrap">
        <table class="return-composition-table">
          <thead><tr><th>组成</th><th>当前记录</th><th>这代表什么</th><th>数据说明</th></tr></thead>
          <tbody>
            <tr>
              <td><strong>策略与实盘累计差距</strong></td>
              <td :class="deviationClass(equity.cumulative_deviation_pct)">{{ metricPercent(equity.cumulative_deviation_pct) }}</td>
              <td>实盘归一化收益减去未放大的模拟收益</td>
              <td>两者风险倍数不同，不能全部归因为执行损耗</td>
            </tr>
            <tr>
              <td><strong>最近一周差距</strong></td>
              <td :class="deviationClass(equity.latest_weekly_deviation_pct)">{{ metricPercent(equity.latest_weekly_deviation_pct) }}</td>
              <td>最近自然周实盘与模拟收益之差</td>
              <td>{{ latestWeekLabel }}</td>
            </tr>
            <tr>
              <td><strong>手续费</strong></td>
              <td>{{ feeSummary }}</td>
              <td>交易所逐笔返回的真实手续费</td>
              <td>不同资产分别保留，不做汇率换算</td>
            </tr>
            <tr>
              <td><strong>成交价影响</strong></td>
              <td>{{ slippageSummary }}</td>
              <td>实际成交价相对下单参考价的偏差</td>
              <td>按真实成交金额加权，仅使用有成交证据的订单</td>
            </tr>
            <tr>
              <td><strong>未解释部分</strong></td>
              <td>暂无独立读数</td>
              <td>资金费、价格时点和其他差异的剩余影响</td>
              <td>当前读模型不能可靠拆分，因此不在前端估算</td>
            </tr>
          </tbody>
        </table>
      </div>
    </article>
  </section>
</template>

<script setup>
import { computed, onMounted } from "vue";
import StatusBadge from "../components/StatusBadge.vue";
import { fmt } from "../core/format.js";
import { enumLabel } from "../domain/labels.js";
import { isAdmin, loadLiveExecutionReports, setActivePage, store } from "../stores/appStore.js";

const reports = computed(() => store.liveExecutionReports || []);
const equity = computed(() => store.state?.live_reconciliation?.equity || { status: "NO_OBSERVATIONS", weekly_points: [] });
const selectedReport = computed(() => reports.value[0] || null);
const executionErrors = computed(() => reports.value.reduce((sum, report) => sum + Number(report.failed_count || 0), 0));
const executionConclusion = computed(() => !reports.value.length ? "等待完整调仓" : (executionErrors.value ? `${executionErrors.value} 项需要解释` : "执行符合计划"));
const executionConclusionClass = computed(() => executionErrors.value ? "negative" : "");
const returnConclusion = computed(() => equity.value.latest_weekly_deviation_pct == null ? "暂无足够观测" : `最近一周差距 ${metricPercent(equity.value.latest_weekly_deviation_pct)}`);
const latestObservation = computed(() => {
  const row = equity.value.weekly_points?.at(-1);
  return row ? `${row.iso_year} 年第 ${row.iso_week} 周` : "暂无记录";
});
const latestWeekLabel = computed(() => {
  const row = equity.value.weekly_points?.at(-1);
  return row ? `${row.iso_year} 年第 ${row.iso_week} 周的最后一次同步` : "尚无周度权益观测";
});
const fidelityRows = computed(() => reports.value.map((report, index) => {
  const rows = report.rows || [];
  let weighted = 0;
  let notional = 0;
  for (const row of rows) {
    const amount = Math.abs(Number(row.executed_quantity || 0) * Number(row.average_price || 0));
    const slippage = Number(row.slippage_bps);
    if (amount && Number.isFinite(slippage)) { weighted += amount * slippage; notional += amount; }
  }
  return {
    key: `${report.rebalance_time_ms || index}`,
    week: weekText(report.rebalance_time_ms), status: report.status,
    matched: Number(report.matched_count || 0), attempted: Number(report.attempted_count || 0),
    errors: Number(report.failed_count || 0), slippage: notional ? `${fmt(weighted / notional, 3)} bps` : "暂无成交记录",
  };
}));
const feeItems = computed(() => {
  const totals = new Map();
  for (const report of reports.value) for (const row of report.rows || []) {
    const assets = row.fee_assets || [];
    if (assets.length === 1) totals.set(assets[0], (totals.get(assets[0]) || 0) + Number(row.fee || 0));
  }
  return [...totals.entries()];
});
const feeSummary = computed(() => feeItems.value.length ? feeItems.value.map(([asset, amount]) => `${fmt(amount, 8)} ${asset}`).join("；") : "暂无手续费记录");
const slippageSummary = computed(() => {
  const rows = fidelityRows.value.filter((row) => !row.slippage.startsWith("暂无"));
  if (!rows.length) return "暂无成交记录";
  let weighted = 0; let notional = 0;
  for (const report of reports.value) for (const row of report.rows || []) {
    const amount = Math.abs(Number(row.executed_quantity || 0) * Number(row.average_price || 0));
    const slip = Number(row.slippage_bps);
    if (amount && Number.isFinite(slip)) { weighted += amount * slip; notional += amount; }
  }
  return notional ? `${fmt(weighted / notional, 3)} bps` : "暂无成交记录";
});

function loadReports() { return loadLiveExecutionReports(); }
function metricPercent(value) { return value == null ? "暂无记录" : `${Number(value) >= 0 ? "+" : ""}${fmt(value, 3)}%`; }
function deviationClass(value) { return value == null ? "" : (Number(value) >= 0 ? "positive" : "negative"); }
function weekText(value) {
  const date = new Date(Number(value));
  if (Number.isNaN(date.getTime())) return "时间未记录";
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}
function quantityText(value) { return value == null ? "-" : fmt(value, 8); }
function moneyText(value) { return Number(value) ? fmt(value, 4) : "-"; }
function feeText(row) { return Number(row.fee) ? `${fmt(row.fee, 8)} ${(row.fee_assets || []).join("/")}` : "-"; }
onMounted(() => { if (isAdmin.value) loadReports(); });
</script>
