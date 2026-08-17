<template>
  <section class="page active quant-page">
    <ReviewPage v-if="routeKind === 'review'" />

    <template v-else-if="routeKind === 'instance'">
      <div class="page-toolbar quant-toolbar">
        <div>
          <button class="text-link back-link" @click="setActivePage('forward')">← 返回量化运行</button>
          <h2>{{ instance.name }}</h2>
          <p>{{ instance.description }}</p>
        </div>
        <div class="action-row">
          <StatusBadge :text="instance.status" :color="instance.color" />
          <button
            v-if="instance.live && isAdmin"
            class="button danger small"
            :disabled="!liveExecution.enabled"
            @click="stopLiveExecution"
          >紧急停止</button>
        </div>
      </div>

      <div class="instance-answer-grid">
        <article class="answer-card">
          <span>1 · 现在持有什么？</span>
          <strong>{{ holdingAnswer }}</strong>
          <p>{{ holdingNote }}</p>
          <div v-if="positionRows.length" class="holding-list">
            <div v-for="row in positionRows.slice(0, 8)" :key="row.symbol">
              <b>{{ row.symbol }}</b>
              <span>{{ directionText(row.direction) }}</span>
              <small>{{ row.target_weight == null ? '目标权重待记录' : percent(Number(row.target_weight) * 100) }}</small>
            </div>
          </div>
        </article>

        <article class="answer-card">
          <span>2 · 本周是否按计划执行？</span>
          <strong :class="executionAnswerClass">{{ executionAnswer }}</strong>
          <p>{{ executionNote }}</p>
        </article>

        <article class="answer-card">
          <span>3 · 赚亏来自哪里？</span>
          <strong>{{ returnAnswer }}</strong>
          <p>{{ returnNote }}</p>
        </article>

        <article class="answer-card">
          <span>4 · 离停止线还有多远？</span>
          <strong :class="riskAnswerClass">{{ riskAnswer }}</strong>
          <p>{{ riskNote }}</p>
        </article>

        <article class="answer-card answer-card-wide">
          <span>5 · 系统本身正常吗？</span>
          <strong :class="systemAnswerClass">{{ systemAnswer }}</strong>
          <p>{{ systemNote }}</p>
          <details class="audit-details">
            <summary>查看审计与技术状态</summary>
            <dl>
              <div><dt>模拟基准</dt><dd>{{ enumLabel(forward.status || 'NOT_STARTED') }}</dd></div>
              <div><dt>自动执行</dt><dd>{{ enumLabel(liveExecution.status || 'DISABLED') }}</dd></div>
              <div><dt>持仓核对</dt><dd>{{ reconciliationText }}</dd></div>
              <div><dt>最近账户同步</dt><dd>{{ timeText(reconciliation.account_synced_at) }}</dd></div>
            </dl>
          </details>
        </article>
      </div>
    </template>

    <template v-else>
      <div class="quant-summary-line">
        <div>
          <span class="eyebrow">运行结论</span>
          <h2>{{ summarySentence }}</h2>
        </div>
        <div class="action-row">
          <button class="button ghost" @click="setActivePage('forward/review')">查看复盘</button>
          <button class="button" @click="drawerOpen = true">启用新量化</button>
        </div>
      </div>

      <div class="metric-grid quant-health-grid">
        <MetricCard label="模拟运行" :value="enumLabel(forward.status || 'NOT_STARTED')" :note="paperNote" />
        <MetricCard label="自动执行" :value="executionStatus" :note="executionHealthNote" :value-class="executionHealthClass" />
        <MetricCard label="持仓核对" :value="positionHealth" :note="positionHealthNote" :value-class="positionDeviation ? 'negative' : ''" />
        <MetricCard label="账户同步" :value="syncAgeText" :note="reconciliationText" :value-class="reconciliation.status === 'READY' ? '' : 'negative'" />
      </div>

      <article class="panel quant-main-card">
        <div class="panel-head">
          <div>
            <h3>量化实例</h3>
            <p class="muted">每个实例独立回答持仓、执行、收益、风险和系统健康五个问题。</p>
          </div>
          <span class="pill">{{ instances.length }} 个实例</span>
        </div>
        <div class="table-wrap">
          <table class="instance-table">
            <thead><tr><th>实例</th><th>运行方式</th><th>当前结论</th><th>最近更新</th><th></th></tr></thead>
            <tbody>
              <tr v-for="item in instances" :key="item.route">
                <td><strong>{{ item.name }}</strong><small>{{ item.description }}</small></td>
                <td>{{ item.mode }}</td>
                <td><StatusBadge :text="item.status" :color="item.color" /></td>
                <td>{{ item.updatedAt }}</td>
                <td><button class="text-link" @click="setActivePage(item.route)">查看详情 →</button></td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-if="exceptionText" class="quant-exception-row">
          <span>需要处理</span>
          <strong>{{ exceptionText }}</strong>
          <button class="text-link" @click="setActivePage('forward/live-small')">打开实例</button>
        </div>
        <div class="legacy-entry">
          <span>需要使用原有初始化、账户预检或布防工具？</span>
          <button class="text-link" @click="setActivePage('forward/legacy')">进入传统流程</button>
        </div>
      </article>
    </template>

    <div v-if="drawerOpen" class="drawer-backdrop" @click.self="drawerOpen = false">
      <aside class="activation-drawer" role="dialog" aria-modal="true" aria-label="启用新量化">
        <div class="panel-head">
          <div><span class="eyebrow">启用向导</span><h3>启用新量化</h3></div>
          <button class="icon-button" aria-label="关闭" @click="drawerOpen = false">×</button>
        </div>
        <p class="muted">新的统一启用编排仍在建设中。这里先展示入口，不会修改账户或触发下单。</p>
        <ol class="activation-steps">
          <li><b>选择策略</b><span>从已经通过研究与审批的策略中选择。</span></li>
          <li><b>选择运行方式</b><span>模拟观察或小资金实盘。</span></li>
          <li><b>完成安全检查</b><span>核对账户、权限、资金与停止规则。</span></li>
        </ol>
        <button class="button" disabled>即将开放</button>
        <button class="button ghost" @click="setActivePage('forward/legacy'); drawerOpen = false">使用传统流程</button>
      </aside>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from "vue";
import MetricCard from "../components/MetricCard.vue";
import StatusBadge from "../components/StatusBadge.vue";
import ReviewPage from "./ReviewPage.vue";
import { percent } from "../core/format.js";
import { enumLabel } from "../domain/labels.js";
import { isAdmin, post, setActivePage, store } from "../stores/appStore.js";

const drawerOpen = ref(false);
const forward = computed(() => store.state?.trend_forward || {});
const checklist = computed(() => forward.value.execution_checklist || { rows: [], status: "NOT_AVAILABLE" });
const reconciliation = computed(() => store.state?.live_reconciliation || {});
const positionResult = computed(() => reconciliation.value.positions || {});
const liveExecution = computed(() => store.state?.live_execution || {});
const liveControl = computed(() => store.state?.live_pilot_control || {});
const equity = computed(() => reconciliation.value.equity || {});
const positionRows = computed(() => checklist.value.rows || []);
const positionDeviation = computed(() => Number(positionResult.value.deviation_count || 0));
const routeKind = computed(() => {
  if (store.activeRoute === "forward/review") return "review";
  if (store.activeRoute !== "forward") return "instance";
  return "overview";
});
const paperNote = computed(() => forward.value.status === "NOT_STARTED"
  ? "尚未建立模拟基准"
  : `已运行 ${forward.value.elapsed_days ?? "-"} 天`);
const executionStatus = computed(() => enumLabel(liveControl.value.status === "ARMED" ? "ARMED" : (liveExecution.value.status || "DISABLED")));
const executionHealthClass = computed(() => ["EMERGENCY_STOPPED", "PROTOCOL_STOP", "PROTOCOL_VIOLATION", "DATA_INTEGRITY_ERROR", "INCOMPLETE_ROUND"].includes(liveExecution.value.status) ? "negative" : "");
const executionHealthNote = computed(() => liveExecution.value.stop_reason || (liveExecution.value.enabled ? "执行闸门已开启" : "当前不会自动下单"));
const positionHealth = computed(() => reconciliation.value.status !== "READY" ? "尚未就绪" : (positionDeviation.value ? `${positionDeviation.value} 项偏差` : "全部符合"));
const positionHealthNote = computed(() => reconciliation.value.status === "READY"
  ? `${positionResult.value.correct_count || 0}/${positionResult.value.total_count || 0} 项符合计划`
  : reconciliationText.value);
const reconciliationText = computed(() => ({
  ACCOUNT_NOT_CONFIGURED: "尚未选择实盘账户",
  AWAITING_ACCOUNT_SYNC: "等待账户首次同步",
  ACCOUNT_NOT_SYNCED: "账户同步尚未成功",
  ACCOUNT_NOT_LIVE: "当前不是主网实盘账户",
  PAPER_NOT_READY: "等待模拟基准首次调仓",
  READY: "数据已就绪",
  NOT_VISIBLE: "当前用户无权查看",
})[reconciliation.value.status] || enumLabel(reconciliation.value.status));
const syncAgeText = computed(() => {
  const timestamp = new Date(reconciliation.value.account_synced_at || "").getTime();
  if (!timestamp || Number.isNaN(timestamp)) return "无同步记录";
  const minutes = Math.max(0, Math.floor((Date.now() - timestamp) / 60000));
  return minutes < 1 ? "刚刚" : (minutes < 60 ? `${minutes} 分钟前` : `${Math.floor(minutes / 60)} 小时前`);
});
const exceptionText = computed(() => {
  if (executionHealthClass.value) return liveExecution.value.stop_reason || "自动执行已停止，请核对原因";
  if (positionDeviation.value) return `发现 ${positionDeviation.value} 项持仓与计划不一致`;
  return "";
});
const summarySentence = computed(() => exceptionText.value || (forward.value.status === "NOT_STARTED"
  ? "量化实例尚未开始运行，可以先查看正式策略。"
  : "量化系统运行平稳，当前没有必须立即处理的问题。"));
const instances = computed(() => [
  {
    route: "forward/tb4-paper", name: "趋势策略 · 模拟观察", description: "用冻结规则持续验证策略，不使用真实资金", mode: "模拟运行",
    status: enumLabel(forward.value.status || "NOT_STARTED"), color: forward.value.status === "MATURE" ? "green" : "blue", updatedAt: timeText(forward.value.last_scored_at || forward.value.started_at),
  },
  {
    route: "forward/live-small", name: "趋势策略 · 小资金实盘", description: "受停止规则保护的真实资金执行实例", mode: "小资金实盘",
    status: executionStatus.value, color: executionHealthClass.value ? "red" : (liveExecution.value.enabled ? "green" : "orange"), updatedAt: timeText(reconciliation.value.account_synced_at), live: true,
  },
]);
const instance = computed(() => instances.value.find((item) => item.route === store.activeRoute) || instances.value[0]);
const holdingAnswer = computed(() => positionRows.value.length ? `当前有 ${positionRows.value.length} 个市场目标` : "尚无本周持仓目标");
const holdingNote = computed(() => positionRows.value.length ? "方向和权重来自已经冻结的本周清单；触发原因需由策略解释记录提供。" : "产生第一份正式调仓清单后，这里会显示方向与权重。");
const executionAnswer = computed(() => instance.value.live ? positionHealth.value : enumLabel(checklist.value.status || "NOT_AVAILABLE"));
const executionAnswerClass = computed(() => positionDeviation.value ? "negative" : "");
const executionNote = computed(() => instance.value.live ? positionHealthNote.value : "模拟实例按冻结规则计分，不会向交易所下单。");
const returnAnswer = computed(() => equity.value.latest_weekly_deviation_pct == null ? "暂无足够观测" : `本周偏差 ${percent(Number(equity.value.latest_weekly_deviation_pct), 2)}`);
const returnNote = computed(() => "收益拆分只展示账本已经记录的策略收益、手续费与成交价偏差；缺失项不会估算。请在复盘页查看。");
const riskAnswer = computed(() => liveExecution.value.status === "EMERGENCY_STOPPED" ? "已紧急停止" : "未触发强制停止");
const riskAnswerClass = computed(() => liveExecution.value.status === "EMERGENCY_STOPPED" ? "negative" : "");
const riskNote = computed(() => liveExecution.value.stop_reason || "停止线按实例配置执行；当前接口未提供精确剩余额度时不做推算。");
const systemAnswer = computed(() => exceptionText.value || "系统状态正常");
const systemAnswerClass = computed(() => exceptionText.value ? "negative" : "");
const systemNote = computed(() => `模拟基准、执行闸门、持仓核对和账户同步共同决定这个结论。最近同步：${syncAgeText.value}。`);

function timeText(value) {
  if (value === null || value === undefined || value === "") return "暂无记录";
  const date = new Date(/^\d+$/.test(String(value)) ? Number(value) : value);
  return Number.isNaN(date.getTime()) ? "暂无记录" : date.toLocaleString("zh-CN", { hour12: false });
}
function directionText(value) { return enumLabel(value); }
async function stopLiveExecution() {
  const reason = prompt("请输入紧急停止原因：");
  if (!reason?.trim() || !confirm("确认立即停止所有新的自动订单？")) return;
  await post("/api/admin/live-execution/emergency-stop", { reason: reason.trim() });
}
function closeOnEscape(event) { if (event.key === "Escape") drawerOpen.value = false; }
onMounted(() => window.addEventListener("keydown", closeOnEscape));
onUnmounted(() => window.removeEventListener("keydown", closeOnEscape));
</script>
