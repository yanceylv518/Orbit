<template>
  <section class="page active">
    <div class="metric-grid">
      <MetricCard label="前向状态" :value="forwardStatus" :note="forwardNote" />
      <MetricCard
        label="实盘换算资金"
        :value="`${fmt(checklist.capital_usdt)} USDT`"
        note="仅用于只读清单，不进入策略状态"
      />
      <MetricCard
        label="目标总名义"
        :value="`${fmt(summary.target_gross_notional_usdt)} USDT`"
        :note="`gross 权重 ${percent(Number(summary.target_gross_weight || 0) * 100)}`"
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
          <h3>LIVE-SMALL V1 · 每周手动执行清单</h3>
          <p class="muted checklist-meta">
            再平衡 {{ timeText(checklist.rebalance_time_ms) }} · 行情 {{ timeText(checklist.close_time_ms) }}
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
              <th>目标名义</th>
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
                <StatusBadge :text="checklistStatusText(row.status)" :color="checklistStatusColor(row.status)" />
                <div class="muted row-action">{{ row.action }}</div>
              </td>
            </tr>
          </tbody>
          <tfoot>
            <tr>
              <td colspan="3"><strong>合计 gross</strong></td>
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
      <h3>执行边界</h3>
      <p class="muted">
        本页只把冻结策略最近一次已执行再平衡目标换算为手工清单，不会调用交易所下单接口。
        数量按 Binance 规则向下取整；低于最低下单额的目标保持空仓，其跟踪误差需在月度对账中单独归因。
      </p>
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
        label="累计 paper 偏差"
        :value="equityResult.cumulative_deviation_pct == null ? '-' : percent(equityResult.cumulative_deviation_pct)"
        :note="`结构性可执行比例 ${percent(Number(equityResult.structural_tracking_ratio || 0) * 100)}`"
        :value-class="cls(equityResult.cumulative_deviation_pct)"
      />
    </div>

    <article class="panel">
      <div class="panel-head">
        <div>
          <h3>真实持仓 vs 冻结目标</h3>
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
              <td><StatusBadge :text="reconciliationRowText(row.status)" :color="reconciliationRowColor(row.status)" /></td>
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

    <article class="panel equity-panel">
      <div class="panel-head">
        <div>
          <h3>实盘与 paper 归一化权益</h3>
          <p class="muted checklist-meta">首个有效同步点统一为 1.0；差异只做展示与人工归因。</p>
        </div>
        <span class="muted">{{ equityResult.points?.length || 0 }} 个只追加观测点</span>
      </div>
      <div v-if="!equityResult.points?.length" class="empty-state">
        配置真实账户并在 TB4 清单 READY 后同步，才会开始记录权益对照。
      </div>
      <div v-else class="equity-chart">
        <MultiLineChart
          :data="equityResult.points"
          :keys="['live_normalized', 'paper_normalized']"
          :colors="['#37d391', '#3987e5']"
          :width="720"
          :height="220"
        />
        <div class="chart-legend">
          <span><i class="live-line"></i>实盘</span>
          <span><i class="paper-line"></i>paper</span>
          <span>最近逐周偏差 {{ percent(equityResult.latest_weekly_deviation_pct) }}</span>
        </div>
      </div>
    </article>
  </section>
</template>

<script setup>
import { computed } from "vue";
import MetricCard from "../components/MetricCard.vue";
import MultiLineChart from "../components/MultiLineChart.vue";
import StatusBadge from "../components/StatusBadge.vue";
import { cls, fmt, percent } from "../core/format.js";
import { store } from "../stores/appStore.js";

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
const reconciliationStatusText = computed(() => ({
  ACCOUNT_NOT_CONFIGURED: "请在 trend_forward.live_account_id 显式指定专用实盘账户",
  AWAITING_ACCOUNT_SYNC: "专用账户尚未同步",
  ACCOUNT_NOT_SYNCED: "专用账户同步失败或凭证未就绪",
  ACCOUNT_NOT_LIVE: "账户必须为主网且非 dry-run",
  PAPER_NOT_READY: "等待 TB4 第一笔正式再平衡",
  READY: "只读核对已就绪",
  NOT_VISIBLE: "当前用户无权查看该实盘账户",
})[reconciliation.value.status] || reconciliation.value.status || "尚未就绪");
const forwardStatus = computed(() => {
  const map = { NOT_STARTED: "未启动", RUNNING: "运行中", MATURE: "已到期" };
  return map[forward.value.status] || forward.value.status || "未知";
});
const forwardNote = computed(() => (
  forward.value.status === "NOT_STARTED"
    ? "需先在 Binance 可达主机初始化"
    : `已计分 ${forward.value.scored_periods || 0} 根 4h K线`
));
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
  return ({ LONG: "做多", SHORT: "做空", FLAT: "空仓" })[value] || value;
}

function directionColor(value) {
  return value === "LONG" ? "green" : (value === "SHORT" ? "red" : "blue");
}

function checklistStatusText(value) {
  return ({
    EXECUTABLE: "可执行",
    BELOW_MIN_NOTIONAL: "低于最低额",
    FLAT: "保持空仓",
    MARKET_NOT_TRADING: "市场不可交易",
  })[value] || value;
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
  return ({
    MATCH: "符合目标",
    DEVIATION: "存在偏差",
    EXPECTED_FLAT: "预期空仓",
    UNEXPECTED_POSITION: "清单外持仓",
  })[value] || value;
}

function reconciliationRowColor(value) {
  return ["MATCH", "EXPECTED_FLAT"].includes(value) ? "green" : "red";
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
.equity-panel { margin-top: 14px; }
.equity-chart { height: 260px; padding-top: 10px; }
.chart-legend { display: flex; gap: 18px; align-items: center; color: var(--muted); }
.chart-legend span { display: inline-flex; align-items: center; gap: 6px; }
.chart-legend i { width: 18px; height: 2px; display: inline-block; }
.live-line { background: #37d391; }
.paper-line { background: #3987e5; }
tfoot td { border-top: 1px solid var(--line-strong); }
</style>
