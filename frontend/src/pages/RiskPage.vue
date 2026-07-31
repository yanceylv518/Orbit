<template>
  <section class="page active">
    <div v-if="isStopped" class="global-stop-banner" role="alert">
      <div>
        <strong>{{ executionStatusText }}</strong>
        <span>{{ liveExecution.stop_reason || "自动执行已停止，不会发送新的 TB4 订单。" }}</span>
      </div>
    </div>

    <div class="metric-grid">
      <MetricCard
        label="实盘当前回撤"
        :value="metricPercent(equity.live_drawdown_pct)"
        :note="`距 ${percent(threshold)} 停机线 ${distanceText(equity.live_drawdown_pct)}`"
        :value-class="drawdownClass(equity.live_drawdown_pct)"
      />
      <MetricCard
        label="paper 当前回撤"
        :value="metricPercent(equity.paper_drawdown_pct)"
        :note="`距 ${percent(threshold)} 停机线 ${distanceText(equity.paper_drawdown_pct)}`"
        :value-class="drawdownClass(equity.paper_drawdown_pct)"
      />
      <MetricCard
        label="自动执行"
        :value="executionStatusText"
        :note="liveExecution.stop_reason || (liveExecution.enabled ? '执行闸门已启用' : '默认关闭，不会下单')"
        :value-class="isStopped ? 'negative' : ''"
      />
      <MetricCard
        label="执行账本"
        :value="liveExecution.ledger?.status || '未就绪'"
        :note="liveExecution.ledger?.error || '哈希链只追加校验'"
        :value-class="liveExecution.ledger?.status === 'INVALID' ? 'negative' : ''"
      />
    </div>

    <div class="risk-system-grid">
      <article class="panel">
        <div class="panel-head">
          <div>
            <h3>LIVE-SMALL 回撤水位</h3>
            <p class="muted">与自动执行停机检查同源；达到或超过 30% 时机制性拒绝新订单。</p>
          </div>
          <StatusBadge :text="equity.status || 'NO_OBSERVATIONS'" :color="equity.status === 'READY' ? 'green' : 'orange'" />
        </div>
        <div class="drawdown-stack">
          <div v-for="item in drawdownItems" :key="item.label" class="drawdown-row">
            <div class="drawdown-label">
              <strong>{{ item.label }}</strong>
              <span>{{ metricPercent(item.value) }} / {{ percent(threshold) }}</span>
            </div>
            <div class="drawdown-track" :aria-label="`${item.label}回撤水位`">
              <span :class="{ danger: Number(item.value) >= threshold }" :style="{ width: drawdownWidth(item.value) }"></span>
              <i aria-hidden="true"></i>
            </div>
          </div>
        </div>
        <p v-if="equity.status !== 'READY'" class="empty-note">
          权益账本尚无有效基准；自动执行会以 EQUITY_BASELINE_MISSING 关闭失败，不会静默放行。
        </p>
      </article>

      <article class="panel">
        <div class="panel-head">
          <div>
            <h3>停止条件</h3>
            <p class="muted">任一条件触发即停止；无法程序判定的条件明确保留人工复核。</p>
          </div>
        </div>
        <div class="condition-list">
          <div v-for="condition in stopConditions" :key="condition.label" class="condition-item">
            <StatusBadge :text="condition.state" :color="condition.color" />
            <div><strong>{{ condition.label }}</strong><p class="muted">{{ condition.note }}</p></div>
          </div>
        </div>
      </article>
    </div>

    <article class="panel guards-panel">
      <div class="panel-head">
        <div>
          <h3>自动执行护栏</h3>
          <p class="muted">显示当前执行投影，不提供绕过、重试或原地恢复入口。</p>
        </div>
        <button
          class="button danger small"
          :disabled="!canEmergencyStop || !liveExecution.enabled || isStopped"
          @click="stopLiveExecution"
        >
          急停自动执行
        </button>
      </div>
      <div class="guard-cards">
        <div v-for="guard in guards" :key="guard.label" class="guard-card">
          <StatusBadge :text="guard.state" :color="guard.color" />
          <strong>{{ guard.label }}</strong>
          <p class="muted">{{ guard.note }}</p>
        </div>
      </div>
      <p v-if="!canEmergencyStop" class="muted">当前用户无管理员急停权限。</p>
    </article>

    <article class="panel audit-panel">
      <div class="panel-head">
        <div>
          <h3>管理员审计日志</h3>
          <p class="muted">急停、恢复、确认及其他管理员动作的只读记录。</p>
        </div>
        <span class="pill">{{ auditLogs.length }} 条</span>
      </div>
      <div class="audit-list">
        <div v-for="item in auditLogs.slice(0, 20)" :key="item.id" class="audit-item">
          <strong>{{ item.action_type }}</strong>
          <div class="muted">{{ timeText(item.timestamp) }} / {{ item.admin_user_id || "-" }}</div>
          <p>{{ item.reason || "未提供原因" }}</p>
        </div>
        <p v-if="!auditLogs.length" class="muted">暂无管理员操作记录。</p>
      </div>
    </article>

    <details v-if="hasLegacyPlanOnly" class="legacy-risk-details">
      <summary>旧网格 plan_only 风控（仍有启用配置）</summary>
      <p class="muted legacy-explanation">
        以下内容仅服务仍在运行的旧网格计划；它不参与 TB4 LIVE-SMALL 的回撤与停机判断。
      </p>
      <LegacyRiskPanel />
    </details>
  </section>
</template>

<script setup>
import { computed } from "vue";
import MetricCard from "../components/MetricCard.vue";
import StatusBadge from "../components/StatusBadge.vue";
import { percent } from "../core/format.js";
import { post, store } from "../stores/appStore.js";
import LegacyRiskPanel from "./LegacyRiskPanel.vue";

const liveExecution = computed(() => store.state?.live_execution || {
  enabled: false,
  status: "DISABLED",
  latest_report: null,
  ledger: {},
});
const reconciliation = computed(() => store.state?.live_reconciliation || {});
const equity = computed(() => reconciliation.value.equity || {
  status: "NO_OBSERVATIONS",
  live_drawdown_pct: null,
  paper_drawdown_pct: null,
  stop_threshold_pct: 30,
});
const threshold = computed(() => Number(equity.value.stop_threshold_pct ?? 30));
const auditLogs = computed(() => store.state?.admin_audit_logs || []);
const canEmergencyStop = computed(() => Boolean(store.state?.auth?.permissions?.can_emergency_stop));
const hasLegacyPlanOnly = computed(() => (store.state?.account_run_configs || []).some(
  (config) => config.enabled && config.mode === "plan_only",
));
const stoppedStatuses = new Set([
  "EMERGENCY_STOPPED",
  "PROTOCOL_STOP",
  "PROTOCOL_VIOLATION",
  "DATA_INTEGRITY_ERROR",
  "INCOMPLETE_ROUND",
]);
const isStopped = computed(() => stoppedStatuses.has(liveExecution.value.status));
const executionStatusText = computed(() => ({
  DISABLED: "默认关闭",
  ENABLED: "已启用",
  EMERGENCY_STOPPED: "管理员急停",
  PROTOCOL_STOP: "回撤协议停机",
  PROTOCOL_VIOLATION: "协议违规停机",
  DATA_INTEGRITY_ERROR: "数据完整性停机",
  INCOMPLETE_ROUND: "未完成轮次停机",
  NOT_VISIBLE: "无权查看",
})[liveExecution.value.status] || liveExecution.value.status || "未知");
const drawdownItems = computed(() => [
  { label: "实盘权益", value: equity.value.live_drawdown_pct },
  { label: "paper 基准", value: equity.value.paper_drawdown_pct },
]);
const dataIntegrityFailure = computed(() => (
  liveExecution.value.status === "DATA_INTEGRITY_ERROR"
  || liveExecution.value.ledger?.status === "INVALID"
  || reconciliation.value.status === "DATA_INTEGRITY_ERROR"
  || reconciliation.value.ledger?.status === "INVALID"
));
const stopConditions = computed(() => [
  drawdownCondition("实盘权益回撤达到停机线", equity.value.live_drawdown_pct),
  drawdownCondition("paper 基准回撤达到停机线", equity.value.paper_drawdown_pct),
  {
    label: "实盘与 paper 无法解释的系统性偏离",
    state: "人工复核",
    color: "blue",
    note: "需要结合多周偏差、滑点、成交时点和结构性不可执行做书面归因。",
  },
  {
    label: "数据完整性事故",
    state: dataIntegrityFailure.value ? "已触发" : "未发现",
    color: dataIntegrityFailure.value ? "red" : "green",
    note: dataIntegrityFailure.value
      ? (liveExecution.value.stop_reason || "执行或权益账本完整性异常。")
      : "执行账本与权益账本当前未投影完整性错误。",
  },
]);
const guards = computed(() => [
  {
    label: "30% 协议停机",
    state: liveExecution.value.status === "PROTOCOL_STOP" ? "已触发" : "未触发",
    color: liveExecution.value.status === "PROTOCOL_STOP" ? "red" : "green",
    note: "实盘或 paper 回撤达到阈值时拒绝该轮执行。",
  },
  {
    label: "清单映射与协议违规",
    state: liveExecution.value.status === "PROTOCOL_VIOLATION" ? "已触发" : "未触发",
    color: liveExecution.value.status === "PROTOCOL_VIOLATION" ? "red" : "green",
    note: "清单外订单或账本映射不一致会闩锁停机。",
  },
  {
    label: "未完成轮次",
    state: liveExecution.value.status === "INCOMPLETE_ROUND" ? "已触发" : "未触发",
    color: liveExecution.value.status === "INCOMPLETE_ROUND" ? "red" : "green",
    note: "重启发现 ROUND_STARTED 未完成时不重复下单。",
  },
  {
    label: "管理员急停",
    state: liveExecution.value.status === "EMERGENCY_STOPPED" ? "已触发" : "未触发",
    color: liveExecution.value.status === "EMERGENCY_STOPPED" ? "red" : "green",
    note: "恢复必须修改 execution epoch 并重启，页面没有直接恢复入口。",
  },
]);

function drawdownCondition(label, value) {
  if (value == null) {
    return { label, state: "待数据", color: "orange", note: "权益账本尚无有效基准。" };
  }
  const triggered = Number(value) >= threshold.value;
  return {
    label,
    state: triggered ? "已触发" : "未触发",
    color: triggered ? "red" : "green",
    note: `当前 ${metricPercent(value)}，冻结阈值 ${percent(threshold.value)}。`,
  };
}

function metricPercent(value) {
  return value == null ? "-" : percent(Number(value));
}

function distanceText(value) {
  if (value == null) return "待建立基准";
  return `${percent(Math.max(0, threshold.value - Number(value)))}`;
}

function drawdownWidth(value) {
  if (value == null || threshold.value <= 0) return "0%";
  return `${Math.min(100, Math.max(0, Number(value) / threshold.value * 100))}%`;
}

function drawdownClass(value) {
  if (value == null) return "";
  return Number(value) >= threshold.value * 0.8 ? "negative" : "";
}

function timeText(value) {
  if (!value) return "-";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString("zh-CN", { hour12: false });
}

async function stopLiveExecution() {
  const reason = prompt("请输入自动执行急停原因。急停后只能修改配置 epoch 并重启才能恢复：");
  if (!reason?.trim()) return;
  if (!confirm("确认立即停止所有新的 TB4 自动订单？")) return;
  await post("/api/admin/live-execution/emergency-stop", { reason: reason.trim() });
}
</script>

<style scoped>
.risk-system-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; margin-top: 14px; }
.drawdown-stack { display: grid; gap: 22px; padding: 8px 0; }
.drawdown-label { display: flex; justify-content: space-between; gap: 10px; margin-bottom: 8px; }
.drawdown-track { height: 12px; border-radius: 999px; background: var(--panel-inset); overflow: hidden; position: relative; }
.drawdown-track span { display: block; height: 100%; background: #e7a641; border-radius: inherit; transition: width .2s ease; }
.drawdown-track span.danger { background: #e75f5f; }
.drawdown-track i { position: absolute; right: 0; top: 0; width: 3px; height: 100%; background: #e75f5f; }
.empty-note { margin: 16px 0 0; color: var(--muted); }
.condition-list { display: grid; gap: 14px; }
.condition-item { display: grid; grid-template-columns: auto 1fr; gap: 10px; align-items: start; }
.condition-item p { margin: 3px 0 0; }
.guards-panel, .audit-panel, .legacy-risk-details { margin-top: 14px; }
.guard-cards { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
.guard-card { display: grid; align-content: start; gap: 8px; padding: 14px; background: var(--panel-inset); border-radius: 9px; }
.guard-card p { margin: 0; }
.legacy-risk-details { border: 1px solid var(--line); border-radius: 10px; padding: 14px; }
.legacy-risk-details summary { cursor: pointer; font-weight: 700; }
.legacy-explanation { margin: 10px 0 0; }
.legacy-risk-details :deep(.page) { padding: 14px 0 0; }
@media (max-width: 1050px) {
  .risk-system-grid { grid-template-columns: 1fr; }
  .guard-cards { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 680px) {
  .guard-cards { grid-template-columns: 1fr; }
}
</style>
