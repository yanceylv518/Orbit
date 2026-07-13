<template>
  <section class="page active">
    <div v-if="riskState.global_stop" class="global-stop-banner" role="alert">
      <div>
        <strong>GLOBAL_STOP 已激活</strong>
        <span>组合级回撤已触发全局拦截，当前不会生成新的开仓动作。</span>
      </div>
    </div>

    <div class="metric-grid risk-metrics">
      <MetricCard label="运行用户" :value="users.length" note="业务用户" />
      <MetricCard label="运行账户" :value="accounts.length" note="Binance futures" />
      <MetricCard label="STOPPED 币种" :value="stoppedSymbols.length" note="等待管理员复核" :value-class="stoppedSymbols.length ? 'negative' : ''" />
      <MetricCard label="计划拦截" :value="blockedCount" note="来自计划风控检查" :value-class="blockedCount ? 'negative' : ''" />
      <MetricCard label="决策阻断" :value="blockedDecisions.length" note="info / 不产生成交" />
      <MetricCard label="实质告警" :value="materialRiskEvents.length" :note="materialRiskEvents.length ? '需要关注' : '当前正常'" :value-class="materialRiskEvents.length ? 'negative' : ''" />
    </div>

    <div class="metric-grid risk-buckets">
      <MetricCard
        label="账户同步风险"
        :value="syncBucket.length"
        note="未同步 / 同步失败 / 配置未启用"
        :value-class="syncBucket.length ? 'negative' : ''"
      />
      <MetricCard
        label="Hedge Mode 风险"
        :value="hedgeBucket.length"
        note="账户未开启双向持仓"
        :value-class="hedgeBucket.length ? 'negative' : ''"
      />
      <MetricCard
        label="计划动作风险"
        :value="actionBucket.length"
        note="动作被 RiskGuard 拦截"
        :value-class="actionBucket.length ? 'negative' : ''"
      />
    </div>

    <div class="risk-workspace">
      <article class="panel stopped-symbol-panel">
        <div class="panel-head">
          <div>
            <h3>STOPPED 币种</h3>
            <p class="muted">恢复会重置该账户币种的回撤基准，并写入管理员审计。</p>
          </div>
          <StatusBadge :text="stoppedSymbols.length ? `${stoppedSymbols.length} 项待复核` : '无待复核项'" :color="stoppedSymbols.length ? 'red' : 'green'" />
        </div>
        <div class="table-wrap">
          <table>
            <thead><tr><th>账户</th><th>币种</th><th>回撤</th><th>已实现亏损</th><th>当前权益</th><th>停止时间</th><th>操作</th></tr></thead>
            <tbody>
              <tr v-for="item in stoppedSymbols" :key="item.id">
                <td><strong>{{ accountName(item.account_id) }}</strong><div class="muted mono">{{ item.account_id }}</div></td>
                <td><StatusBadge :text="item.symbol" color="red" /></td>
                <td class="negative mono">{{ money(item.drawdown_usdt) }} / {{ percent(item.drawdown_pct) }}</td>
                <td class="negative mono">{{ money(item.realized_loss_usdt) }}</td>
                <td class="mono">{{ money(item.equity_usdt) }}</td>
                <td>{{ displayTime(item.stopped_at) }}</td>
                <td>
                  <button
                    v-if="canResumeStoppedSymbol"
                    class="button small"
                    :disabled="Boolean(store.recoveringStoppedSymbolId)"
                    @click="openRecovery(item)"
                  >
                    {{ store.recoveringStoppedSymbolId === item.id ? "恢复中" : "复核恢复" }}
                  </button>
                  <span v-else class="muted">仅管理员</span>
                </td>
              </tr>
              <tr v-if="!stoppedSymbols.length"><td colspan="7" class="muted">当前没有处于 STOPPED 状态的账户币种。</td></tr>
            </tbody>
          </table>
        </div>
      </article>

      <article class="panel risk-alert-panel">
        <div class="panel-head"><h3>实质风险告警</h3></div>
        <div class="table-wrap">
          <table>
            <thead><tr><th>时间</th><th>用户</th><th>账户</th><th>币种</th><th>风险类型</th><th>风险等级</th><th>动作</th></tr></thead>
            <tbody>
              <tr v-for="risk in materialRiskEvents.slice(0, 12)" :key="risk.id">
                <td>{{ displayTime(risk.timestamp) }}</td>
                <td>{{ risk.user_id || "-" }}</td>
                <td>{{ risk.exchange_account_id || "-" }}</td>
                <td>{{ risk.symbol || "-" }}</td>
                <td><StatusBadge :text="risk.risk_type" :color="risk.risk_level === 'high' ? 'red' : 'orange'" /></td>
                <td><StatusBadge :text="risk.risk_level || '-'" :color="risk.risk_level === 'high' ? 'red' : 'orange'" /></td>
                <td>{{ risk.action_taken }}</td>
              </tr>
              <tr v-if="!materialRiskEvents.length"><td colspan="7" class="muted">暂无实质风险告警。</td></tr>
            </tbody>
          </table>
        </div>
      </article>

      <article class="panel blocked-decision-panel">
        <div class="panel-head">
          <div>
            <h3>决策阻断记录</h3>
            <p class="muted">规则或市场状态阻止了动作，以下记录均未产生成交。</p>
          </div>
        </div>
        <div class="table-wrap">
          <table>
            <thead><tr><th>时间</th><th>账户</th><th>币种</th><th>阻断原因</th><th>来源</th></tr></thead>
            <tbody>
              <tr v-for="item in blockedDecisions.slice(0, 12)" :key="item.id">
                <td>{{ displayTime(item.timestamp) }}</td>
                <td>{{ accountName(item.exchange_account_id) }}</td>
                <td>{{ item.symbol || "-" }}</td>
                <td><strong>{{ item.risk_type || "BLOCKED" }}</strong><div class="muted">{{ item.message || "未提供说明" }}</div></td>
                <td>{{ item.trigger?.block_source || item.context?.block_source || "-" }}</td>
              </tr>
              <tr v-if="!blockedDecisions.length"><td colspan="5" class="muted">暂无决策阻断记录。</td></tr>
            </tbody>
          </table>
        </div>
      </article>

      <article class="panel plan-risk-panel">
        <div class="panel-head"><h3>计划风控检查</h3></div>
        <div class="table-wrap">
          <table>
            <thead><tr><th>账户</th><th>币种</th><th>计划状态</th><th>检查结果</th><th>人工确认</th></tr></thead>
            <tbody>
              <tr v-for="plan in executionPlans.slice(0, 14)" :key="plan.id">
                <td><strong>{{ accountName(plan.account_id) }}</strong><div class="muted">{{ plan.account_id }}</div></td>
                <td>{{ plan.symbol }}</td>
                <td><StatusBadge :text="statusLabel(plan.status)" :color="planStatusColor(plan.status)" /></td>
                <td>
                  <div v-for="check in plan.risk_checks || []" :key="check.name">
                    <StatusBadge :text="check.ok ? '通过' : '拦截'" :color="check.ok ? 'green' : 'orange'" />
                    {{ check.message || check.name }}
                  </div>
                  <span v-if="!(plan.risk_checks || []).length" class="muted">无检查项</span>
                </td>
                <td><StatusBadge v-if="plan.manual_review?.status === 'confirmed'" text="已确认" color="green" /><span v-else class="muted">未确认</span></td>
              </tr>
              <tr v-if="!executionPlans.length"><td colspan="5" class="muted">暂无执行计划风控记录。</td></tr>
            </tbody>
          </table>
        </div>
      </article>

      <article class="panel risk-side-panel">
        <div class="panel-head"><h3>审计日志</h3></div>
        <div class="audit-list">
          <div v-for="item in auditLogs.slice(0, 12)" :key="item.id" class="audit-item">
            <strong>{{ item.action_type }}</strong>
            <div class="muted">{{ displayTime(item.timestamp) }} / {{ item.admin_user_id }}</div>
            <p>{{ item.reason }}</p>
          </div>
          <p v-if="!auditLogs.length" class="muted">暂无管理员操作。</p>
        </div>
      </article>

      <article class="panel risk-action-panel">
        <div class="panel-head"><h3>快捷操作</h3></div>
        <div class="quick-actions">
          <button class="button danger" @click="emergencyStop">全局急停</button>
          <button class="button ghost" @click="resumeSystem">恢复运行</button>
          <button class="button ghost" @click="setActivePage('plans')">查看执行计划</button>
          <button class="button ghost" @click="setActivePage('accounts')">检查账户 API</button>
        </div>
      </article>
    </div>

    <div v-if="recoveryTarget" class="modal-backdrop" @click.self="closeRecovery" @keydown.esc="closeRecovery">
      <section class="modal-dialog" role="dialog" aria-modal="true" aria-labelledby="recovery-title">
        <div class="modal-head">
          <div>
            <h3 id="recovery-title">复核恢复 STOPPED 币种</h3>
            <p class="muted">{{ accountName(recoveryTarget.account_id) }} / {{ recoveryTarget.symbol }}</p>
          </div>
          <button class="modal-close" type="button" title="关闭" aria-label="关闭" @click="closeRecovery">×</button>
        </div>
        <div class="recovery-summary">
          <span>当前回撤 <strong class="negative">{{ money(recoveryTarget.drawdown_usdt) }}</strong></span>
          <span>已实现亏损 <strong class="negative">{{ money(recoveryTarget.realized_loss_usdt) }}</strong></span>
        </div>
        <label class="modal-field">
          <span>复核原因</span>
          <textarea v-model="recoveryReason" rows="4" maxlength="500" placeholder="填写恢复依据、已核对的账户状态与风险判断" autofocus></textarea>
        </label>
        <p v-if="recoveryError" class="form-error">{{ recoveryError }}</p>
        <p class="modal-warning">确认后该币种将按当前价格重锚并重置回撤基准，此动作会写入管理员审计。</p>
        <div class="modal-actions">
          <button class="button ghost" type="button" :disabled="recoveryBusy" @click="closeRecovery">取消</button>
          <button class="button danger" type="button" :disabled="recoveryBusy" @click="confirmRecovery">
            {{ recoveryBusy ? "正在恢复" : "确认恢复" }}
          </button>
        </div>
      </section>
    </div>
  </section>
</template>

<script setup>
import { computed, ref } from "vue";
import MetricCard from "../components/MetricCard.vue";
import StatusBadge from "../components/StatusBadge.vue";
import { planStatusColor, statusLabel } from "../domain/labels.js";
import {
  accounts,
  emergencyStop,
  executionPlans,
  resumeStoppedSymbol,
  resumeSystem,
  riskState,
  setActivePage,
  store,
  users,
} from "../stores/appStore.js";

const riskEvents = computed(() => store.state?.risk_events || []);
const materialRiskEvents = computed(() => riskEvents.value.filter(
  (risk) => String(risk.risk_level || "").toLowerCase() !== "info",
));
const stoppedSymbols = computed(() => riskState.value.stopped_symbols || []);
const blockedDecisions = computed(() => riskState.value.blocked_decisions || []);
const auditLogs = computed(() => store.state?.admin_audit_logs || []);
const blockedCount = computed(() => executionPlans.value.filter((plan) => plan.status === "blocked").length);
const canResumeStoppedSymbol = computed(() => Boolean(store.state?.auth?.permissions?.can_resume_stopped_symbol));

const SYNC_EVENT_TYPES = ["SYNC_REQUIRED", "ACCOUNT_CONFIG_DISABLED"];
const blockedPlans = computed(() => executionPlans.value.filter((plan) => plan.status === "blocked"));
const syncBucket = computed(() => blockedPlans.value.filter((plan) => SYNC_EVENT_TYPES.includes(plan.event_type)));
const hedgeBucket = computed(() => blockedPlans.value.filter((plan) => plan.event_type === "HEDGE_MODE_REQUIRED"));
const actionBucket = computed(() => blockedPlans.value.filter(
  (plan) => !SYNC_EVENT_TYPES.includes(plan.event_type) && plan.event_type !== "HEDGE_MODE_REQUIRED",
));
const accountById = computed(() => Object.fromEntries(accounts.value.map((account) => [account.account_id, account])));
const recoveryTarget = ref(null);
const recoveryReason = ref("");
const recoveryError = ref("");
const recoveryBusy = ref(false);

function accountName(accountId) {
  return accountById.value[accountId]?.account_label || accountId || "-";
}

function money(value) {
  return `${Number(value || 0).toFixed(2)} USDT`;
}

function percent(value) {
  return `${Number(value || 0).toFixed(2)}%`;
}

function displayTime(value) {
  if (!value) return "-";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN", { hour12: false });
}

function openRecovery(item) {
  recoveryTarget.value = item;
  recoveryReason.value = "";
  recoveryError.value = "";
}

function closeRecovery() {
  if (recoveryBusy.value) return;
  recoveryTarget.value = null;
  recoveryReason.value = "";
  recoveryError.value = "";
}

async function confirmRecovery() {
  const reason = recoveryReason.value.trim();
  if (!reason) {
    recoveryError.value = "复核恢复必须填写原因。";
    return;
  }
  recoveryBusy.value = true;
  recoveryError.value = "";
  const target = recoveryTarget.value;
  const recovered = await resumeStoppedSymbol(target.account_id, target.symbol, reason);
  recoveryBusy.value = false;
  if (recovered) closeRecovery();
}
</script>
