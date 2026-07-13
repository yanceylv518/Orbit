<template>
  <section class="page active">
    <div class="page-toolbar">
      <div>
        <h2>第一阶段执行计划</h2>
        <p>基于真实 Binance 持仓生成计划动作；当前阶段只演练，不下单。点击行首箭头查看触发快照。</p>
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
            <tr><th></th><th>时间</th><th>账户</th><th>币种</th><th>事件</th><th>相位</th><th>Δ → Δ*</th><th>状态</th><th>计划动作</th><th>确认 / 导出</th></tr>
          </thead>
          <tbody>
            <template v-for="plan in plans" :key="plan.id">
              <tr>
                <td>
                  <button class="button ghost small expand-toggle" @click="toggleExpand(plan.id)">{{ expandedId === plan.id ? "▾" : "▸" }}</button>
                </td>
                <td>{{ plan.created_at || "-" }}</td>
                <td><strong>{{ accountName(plan.account_id) }}</strong><div class="muted">{{ plan.account_id }}</div></td>
                <td>{{ plan.symbol }}</td>
                <td>{{ eventLabel(plan.event_type) }}</td>
                <td><StatusBadge :text="stateLabel(plan.trigger?.lifecycle_state || '-')" :color="stateColor(plan.trigger?.lifecycle_state || '')" /></td>
                <td class="mono">{{ deltaText(plan) }}</td>
                <td>
                  <StatusBadge :text="statusLabel(plan.status)" :color="planStatusColor(plan.status)" />
                  <div v-if="plan.status === 'blocked'" class="muted">{{ blockSummary(plan) }}</div>
                  <div v-if="plan.expires_at_ms" class="muted">
                    <StatusBadge v-if="isExpired(plan)" text="已过期" color="orange" />
                    <template v-else>有效 {{ ttlText(plan) }}</template>
                  </div>
                </td>
                <td>
                  <div v-for="action in plan.actions || []" :key="`${plan.id}-${action.action}`">
                    <StatusBadge v-if="action.status === 'blocked'" text="拦截" color="orange" />
                    {{ action.action }} {{ fmt(action.quantity, 6) }} / {{ fmt(action.notional_usdt) }} USDT
                  </div>
                  <span v-if="!(plan.actions || []).length">-</span>
                </td>
                <td>
                  <div class="plan-review">
                    <StatusBadge v-if="plan.manual_review?.status === 'confirmed'" text="已确认" color="green" />
                    <button v-else-if="plan.status === 'planned'" class="button small" @click="confirmExecutionPlan(plan.id)">确认</button>
                    <span v-else class="muted">不可确认</span>
                    <small v-if="plan.last_export" class="muted">已导出 {{ plan.last_export.exported_at }}</small>
                  </div>
                </td>
              </tr>
              <!-- 详情展开行：触发快照 + 生命周期上下文 + 风控逐条 -->
              <tr v-if="expandedId === plan.id" class="plan-detail-row">
                <td colspan="10">
                  <div class="plan-detail">
                    <div class="plan-detail-section">
                      <h4>触发快照</h4>
                      <dl class="facts">
                        <template v-for="item in triggerFacts(plan)" :key="item.label">
                          <dt>{{ item.label }}</dt><dd>{{ item.value }}</dd>
                        </template>
                      </dl>
                    </div>
                    <div class="plan-detail-section">
                      <h4>风控检查</h4>
                      <div v-for="check in plan.risk_checks || []" :key="check.name" class="risk-check-line">
                        <StatusBadge :text="check.ok ? '通过' : '拦截'" :color="check.ok ? 'green' : 'orange'" />
                        {{ check.message || check.name }}
                      </div>
                      <p v-if="!(plan.risk_checks || []).length" class="muted">无检查项</p>
                      <h4>动作明细</h4>
                      <div v-for="action in plan.actions || []" :key="`${plan.id}-detail-${action.action}`" class="risk-check-line">
                        <StatusBadge :text="action.status === 'blocked' ? '拦截' : '待演练'" :color="action.status === 'blocked' ? 'orange' : 'green'" />
                        {{ action.action }} · {{ fmt(action.quantity, 6) }} · {{ fmt(action.notional_usdt) }} USDT
                        <span v-if="action.reduce_only" class="muted">（reduce-only）</span>
                        <span v-if="action.block_reason" class="muted">{{ action.block_reason }}</span>
                        <span v-if="action.reason" class="muted">{{ action.reason }}</span>
                      </div>
                      <p v-if="!(plan.actions || []).length" class="muted">无动作</p>
                    </div>
                    <div class="plan-detail-section raw-trigger">
                      <h4>原始触发数据</h4>
                      <pre>{{ JSON.stringify(plan.trigger || {}, null, 2) }}</pre>
                    </div>
                  </div>
                </td>
              </tr>
            </template>
            <tr v-if="!plans.length"><td colspan="10" class="muted">暂无执行计划。请先同步账户，然后生成执行计划。</td></tr>
          </tbody>
        </table>
      </div>
    </article>
  </section>
</template>

<script setup>
import { computed, ref, watchEffect } from "vue";
import StatusBadge from "../components/StatusBadge.vue";
import SummaryItem from "../components/SummaryItem.vue";
import { fmt } from "../core/format.js";
import { eventLabel, planStatusColor, stateColor, stateLabel, statusLabel } from "../domain/labels.js";
import { accounts, confirmExecutionPlan, executionPlans, exportExecutionPlans, generateExecutionPlans, isAdmin, store } from "../stores/appStore.js";

const expandedId = ref("");

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

function toggleExpand(planId) {
  expandedId.value = expandedId.value === planId ? "" : planId;
}

function deltaText(plan) {
  const trigger = plan.trigger || {};
  if (trigger.current_net_qty === undefined) return "-";
  return `${fmt(trigger.current_net_qty, 4)} → ${fmt(trigger.target_net_qty, 4)}`;
}

function blockSummary(plan) {
  const failed = (plan.risk_checks || []).find((check) => !check.ok);
  return failed?.message || plan.reason || "";
}

// 计划有效期：过期计划后端会拒绝确认，前端提前提示
function isExpired(plan) {
  return plan.expires_at_ms && Date.now() > plan.expires_at_ms;
}

function ttlText(plan) {
  const remaining = Math.max(0, plan.expires_at_ms - Date.now());
  const minutes = Math.floor(remaining / 60000);
  const seconds = Math.floor((remaining % 60000) / 1000);
  return minutes > 0 ? `${minutes}m${seconds}s` : `${seconds}s`;
}

function triggerFacts(plan) {
  const trigger = plan.trigger || {};
  const rows = [
    ["内核", trigger.exposure_model],
    ["生命周期", trigger.lifecycle_state ? stateLabel(trigger.lifecycle_state) : undefined],
    ["市况 Gate", trigger.regime],
    ["市况原始判定", trigger.regime_raw],
    ["效率比 ER", trigger.regime_features?.efficiency_ratio !== undefined ? fmt(trigger.regime_features.efficiency_ratio, 4) : undefined],
    ["收益自相关", trigger.regime_features?.return_autocorrelation !== undefined ? fmt(trigger.regime_features.return_autocorrelation, 4) : undefined],
    ["波动率 %", trigger.regime_features?.volatility_pct !== undefined ? `${fmt(trigger.regime_features.volatility_pct, 4)}%` : undefined],
    ["触发规则", trigger.event_rule],
    ["锚点价", trigger.base_price !== undefined ? fmt(trigger.base_price, 4) : undefined],
    ["偏离 %", trigger.move_pct_from_base !== undefined ? `${fmt(trigger.move_pct_from_base, 3)}%` : undefined],
    ["base 数量", trigger.base_qty !== undefined ? fmt(trigger.base_qty, 6) : undefined],
    ["当前 Δ", trigger.current_net_qty !== undefined ? fmt(trigger.current_net_qty, 6) : undefined],
    ["目标 Δ*", trigger.target_net_qty !== undefined ? fmt(trigger.target_net_qty, 6) : undefined],
    ["差值", trigger.delta_to_target_qty !== undefined ? fmt(trigger.delta_to_target_qty, 6) : undefined],
    ["阶梯计数", trigger.target_step_count],
    ["标记价", trigger.mark_price !== undefined ? fmt(trigger.mark_price, 4) : undefined],
    ["多头数量", trigger.long_qty !== undefined ? fmt(trigger.long_qty, 6) : undefined],
    ["空头数量", trigger.short_qty !== undefined ? fmt(trigger.short_qty, 6) : undefined],
    ["币种预算", trigger.symbol_budget_usdt !== undefined ? `${fmt(trigger.symbol_budget_usdt)} USDT` : undefined],
    ["目标原因", trigger.target_reason],
  ];
  return rows
    .filter(([, value]) => value !== undefined && value !== null && value !== "")
    .map(([label, value]) => ({ label, value }));
}

function exportCurrent() {
  exportExecutionPlans(plans.value.map((plan) => plan.id), store.selectedPlanAccount || "all");
}
</script>
