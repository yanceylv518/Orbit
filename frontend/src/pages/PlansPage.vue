<template>
  <section class="page active">
    <div class="page-toolbar">
      <div>
        <h2>第一阶段执行计划</h2>
        <p>基于真实 Binance 持仓生成计划动作；当前阶段只演练，不下单。</p>
      </div>
      <div class="action-row plan-actions">
        <select v-model="store.selectedPlanAccount" class="select-control" aria-label="选择执行计划账户">
          <option v-if="isAdmin" value="">全部可见账户</option>
          <option v-for="account in accounts" :key="account.account_id" :value="account.account_id">{{ account.account_label }} / {{ account.account_id }}</option>
        </select>
        <button class="button" @click="generateExecutionPlans(store.selectedPlanAccount)">生成执行计划</button>
        <button class="button ghost" :disabled="!plans.length" @click="exportCurrent">导出计划</button>
      </div>
    </div>
    <article class="panel full-panel">
      <div class="summary-grid compact">
        <SummaryItem label="计划总数" :value="plans.length" note="当前可见账户" />
        <SummaryItem label="待演练" :value="countByStatus('planned')" note="只生成计划，不下单" />
        <SummaryItem label="已确认" :value="confirmedCount" note="人工核对记录" />
        <SummaryItem label="风控拦截" :value="countByStatus('blocked')" note="需要处理后再演练" />
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr><th>时间</th><th>账户</th><th>币种</th><th>事件</th><th>状态</th><th>计划动作</th><th>风控检查</th><th>确认 / 导出</th><th>原因</th></tr>
          </thead>
          <tbody>
            <tr v-for="plan in plans" :key="plan.id">
              <td>{{ plan.created_at || "-" }}</td>
              <td><strong>{{ accountName(plan.account_id) }}</strong><div class="muted">{{ plan.account_id }}</div></td>
              <td>{{ plan.symbol }}</td>
              <td>{{ eventLabel(plan.event_type) }}</td>
              <td><StatusBadge :text="statusLabel(plan.status)" :color="planStatusColor(plan.status)" /></td>
              <td>
                <div v-for="action in plan.actions || []" :key="`${plan.id}-${action.action}`">
                  {{ action.action }} {{ fmt(action.quantity, 6) }} / {{ fmt(action.notional_usdt) }} USDT
                  <span v-if="action.status === 'blocked'">（拦截：{{ action.block_reason || "风控" }}）</span>
                </div>
                <span v-if="!(plan.actions || []).length">-</span>
              </td>
              <td>
                <div v-for="check in plan.risk_checks || []" :key="check.name">
                  <StatusBadge :text="check.ok ? '通过' : '拦截'" :color="check.ok ? 'green' : 'orange'" />
                  {{ check.message || check.name }}
                </div>
              </td>
              <td>
                <div class="plan-review">
                  <StatusBadge v-if="plan.manual_review?.status === 'confirmed'" text="已确认" color="green" />
                  <button v-else-if="plan.status === 'planned'" class="button small" @click="confirmExecutionPlan(plan.id)">确认</button>
                  <span v-else class="muted">不可确认</span>
                  <small v-if="plan.last_export" class="muted">已导出 {{ plan.last_export.exported_at }}</small>
                </div>
              </td>
              <td>{{ plan.reason }}</td>
            </tr>
            <tr v-if="!plans.length"><td colspan="9" class="muted">暂无执行计划。请先同步账户，然后生成执行计划。</td></tr>
          </tbody>
        </table>
      </div>
    </article>
  </section>
</template>

<script setup>
import { computed, watchEffect } from "vue";
import StatusBadge from "../components/StatusBadge.vue";
import SummaryItem from "../components/SummaryItem.vue";
import { fmt } from "../core/format.js";
import { eventLabel, planStatusColor, statusLabel } from "../domain/labels.js";
import { accounts, confirmExecutionPlan, executionPlans, exportExecutionPlans, generateExecutionPlans, isAdmin, store } from "../stores/appStore.js";

watchEffect(() => {
  const validIds = accounts.value.map((account) => account.account_id);
  if (!isAdmin.value && !store.selectedPlanAccount && validIds.length) store.selectedPlanAccount = validIds[0];
  if (store.selectedPlanAccount && !validIds.includes(store.selectedPlanAccount)) store.selectedPlanAccount = "";
});

const plans = computed(() => {
  if (!store.selectedPlanAccount) return executionPlans.value;
  return executionPlans.value.filter((plan) => plan.account_id === store.selectedPlanAccount);
});
const confirmedCount = computed(() => plans.value.filter((plan) => plan.manual_review?.status === "confirmed").length);
const accountById = computed(() => Object.fromEntries(accounts.value.map((account) => [account.account_id, account])));

function countByStatus(status) {
  return plans.value.filter((plan) => plan.status === status).length;
}

function accountName(accountId) {
  return accountById.value[accountId]?.account_label || accountId;
}

function exportCurrent() {
  exportExecutionPlans(plans.value.map((plan) => plan.id), store.selectedPlanAccount || "all");
}
</script>
