<template>
  <section class="page active">
    <div class="metric-grid risk-metrics">
      <MetricCard label="运行用户" :value="users.length" note="业务用户" />
      <MetricCard label="运行账户" :value="accounts.length" note="Binance futures" />
      <MetricCard label="待演练计划" :value="plannedCount" note="plan_only" />
      <MetricCard label="计划拦截" :value="blockedCount" note="来自计划风控检查" :value-class="blockedCount ? 'negative' : ''" />
      <MetricCard label="已确认计划" :value="confirmedCount" note="人工核对记录" />
      <MetricCard label="风险告警" :value="riskEvents.length" :note="store.state?.strategy?.risk_status === 'normal' ? '当前正常' : '需要关注'" :value-class="riskEvents.length ? 'negative' : ''" />
    </div>

    <div class="risk-workspace">
      <article class="panel risk-alert-panel">
        <div class="panel-head"><h3>系统风险告警</h3></div>
        <div class="table-wrap">
          <table>
            <thead><tr><th>时间</th><th>用户</th><th>账户</th><th>币种</th><th>风险类型</th><th>风险等级</th><th>动作</th></tr></thead>
            <tbody>
              <tr v-for="risk in riskEvents.slice(0, 12)" :key="risk.id">
                <td>{{ risk.timestamp }}</td>
                <td>{{ risk.user_id || "-" }}</td>
                <td>{{ risk.exchange_account_id || "-" }}</td>
                <td>{{ risk.symbol || "-" }}</td>
                <td><StatusBadge :text="risk.risk_type" :color="risk.risk_level === 'high' ? 'red' : 'orange'" /></td>
                <td><StatusBadge :text="risk.risk_level || '-'" :color="risk.risk_level === 'high' ? 'red' : 'orange'" /></td>
                <td>{{ risk.action_taken }}</td>
              </tr>
              <tr v-if="!riskEvents.length"><td colspan="7" class="muted">暂无风险告警</td></tr>
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
              <tr v-if="!executionPlans.length"><td colspan="5" class="muted">暂无执行计划风控记录</td></tr>
            </tbody>
          </table>
        </div>
      </article>

      <article class="panel risk-side-panel">
        <div class="panel-head"><h3>审计日志</h3></div>
        <div class="audit-list">
          <div v-for="item in auditLogs.slice(0, 12)" :key="item.id" class="audit-item">
            <strong>{{ item.action_type }}</strong>
            <div class="muted">{{ item.timestamp }} / {{ item.admin_user_id }}</div>
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
  </section>
</template>

<script setup>
import { computed } from "vue";
import MetricCard from "../components/MetricCard.vue";
import StatusBadge from "../components/StatusBadge.vue";
import { planStatusColor, statusLabel } from "../domain/labels.js";
import { accounts, emergencyStop, executionPlans, resumeSystem, setActivePage, store, users } from "../stores/appStore.js";

const riskEvents = computed(() => store.state?.risk_events || []);
const auditLogs = computed(() => store.state?.admin_audit_logs || []);
const plannedCount = computed(() => executionPlans.value.filter((plan) => plan.status === "planned").length);
const blockedCount = computed(() => executionPlans.value.filter((plan) => plan.status === "blocked").length);
const confirmedCount = computed(() => executionPlans.value.filter((plan) => plan.manual_review?.status === "confirmed").length);
const accountById = computed(() => Object.fromEntries(accounts.value.map((account) => [account.account_id, account])));

function accountName(accountId) {
  return accountById.value[accountId]?.account_label || accountId;
}
</script>
