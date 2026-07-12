<template>
  <section class="page active">
    <!-- 策略实例：平台策略，系统维护 -->
    <article class="panel">
      <div class="panel-head">
        <h3>平台策略实例</h3>
        <span class="pill">策略由平台维护，管理员挂载运行</span>
      </div>
      <div class="summary-grid compact">
        <SummaryItem label="策略" :value="`${strategy.name || '-'} ${strategy.version || ''}`" :note="strategy.id || 'system'" />
        <SummaryItem label="运行模式" :note="modeLabel(strategy.mode)"><StatusBadge :text="statusLabel(strategy.status)" :color="statusColor(strategy.status)" /></SummaryItem>
        <SummaryItem label="覆盖币种" :value="strategy.symbol_count ?? 0" :note="(strategy.symbols || []).join(' / ') || '-'" />
        <SummaryItem label="策略内核" :value="kernelLabel" note="净敞口 Δ* 模型 · 生命周期 · RiskGuard" />
      </div>
    </article>

    <!-- 账户挂载与运行配置 -->
    <article class="panel">
      <div class="panel-head">
        <h3>账户挂载与运行配置</h3>
        <span class="muted">运行配置编辑接口为 /api/account-run-config（界面编辑后续补充）</span>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr><th>账户</th><th>启用</th><th>模式</th><th>币种</th><th>预算 (USDT)</th><th>单笔上限</th><th>允许加仓</th><th>更新时间</th></tr>
          </thead>
          <tbody>
            <tr v-for="config in runConfigs" :key="config.account_id">
              <td>
                <strong>{{ accountLabel(config.account_id) }}</strong>
                <div class="muted">{{ config.account_id }}</div>
              </td>
              <td><StatusBadge :text="config.enabled ? '已启用' : '已停用'" :color="config.enabled ? 'green' : 'orange'" /></td>
              <td>{{ statusLabel(config.mode) }}</td>
              <td>{{ (config.symbols || []).join(" / ") }}</td>
              <td>{{ budgetText(config) }}</td>
              <td>{{ fmt(config.max_single_order_usdt) }}</td>
              <td>{{ boolText(config.allow_add_position) }}</td>
              <td class="muted">{{ config.updated_at || "-" }}</td>
            </tr>
            <tr v-if="!runConfigs.length"><td colspan="8" class="muted">暂无账户运行配置。请先在用户与账户页添加交易账户。</td></tr>
          </tbody>
        </table>
      </div>
    </article>

    <!-- 事件参数 -->
    <div class="page-toolbar">
      <div>
        <h2>策略事件参数</h2>
        <p>利润搬运、仓位恢复、亏损腿减仓。标注「未生效」的参数已被 Δ* 内核取代，保存不影响行为。</p>
      </div>
      <button class="button" @click="submit">保存配置</button>
    </div>
    <div class="event-config-grid">
      <article v-for="card in cards" :key="card.title" class="event-card" :class="card.color">
        <div class="event-card-header">
          <h3>{{ card.title }}</h3>
          <StatusBadge :text="card.priority" :color="card.color" />
        </div>
        <label v-for="field in card.fields" :key="field.path" class="field">
          <span>
            {{ field.label }}
            <StatusBadge v-if="field.unwired" text="未生效" color="orange" />
          </span>
          <input v-model.number="form[field.path]" type="number" min="0" step="0.01" :disabled="field.unwired" />
        </label>
        <p class="muted">{{ card.desc }}</p>
      </article>
    </div>
  </section>
</template>

<script setup>
import { computed, reactive, watchEffect } from "vue";
import StatusBadge from "../components/StatusBadge.vue";
import SummaryItem from "../components/SummaryItem.vue";
import { fmt } from "../core/format.js";
import { boolText, modeLabel, statusColor, statusLabel } from "../domain/labels.js";
import { exchangeAccounts, executionPlans, saveEventConfig, store } from "../stores/appStore.js";

const form = reactive({});
const cfg = computed(() => store.state?.event_config || {});
const strategy = computed(() => store.state?.strategy || {});
const runConfigs = computed(() => store.state?.account_run_configs || []);
const accountById = computed(() => Object.fromEntries(exchangeAccounts.value.map((account) => [account.id, account])));
const kernelLabel = computed(() => {
  const plan = executionPlans.value.find((item) => item.trigger?.exposure_model);
  return plan?.trigger?.exposure_model || "net_exposure_v1";
});

function accountLabel(accountId) {
  return accountById.value[accountId]?.account_label || accountId;
}

function budgetText(config) {
  const budgets = config.symbol_budget_usdt || {};
  const total = Object.values(budgets).reduce((sum, value) => sum + Number(value || 0), 0);
  return `${fmt(total)}（${Object.keys(budgets).length} 币种）`;
}

const cards = computed(() => [
  {
    title: "利润搬运",
    color: "green",
    priority: "优先级 2",
    desc: "盈利腿减仓实现净利润，再按配置恢复或增加亏损腿——本质是建立逆势偏斜（Δ 押注回归）。",
    fields: [
      field("触发利润（资金池%）", "profit_transfer.trigger.min_profit_pct_of_symbol_budget"),
      field("价格偏离触发", "profit_transfer.trigger.min_price_move_pct_from_base"),
      field("盈利腿减仓比例", "profit_transfer.sizing.reduce_profit_side_ratio", 100),
      field("亏损腿恢复比例", "profit_transfer.sizing.use_realized_profit_ratio_for_loss_side", 100),
      field("最多搬运次数", "profit_transfer.guard.max_times_per_trend"),
    ],
  },
  {
    title: "仓位恢复",
    color: "blue",
    priority: "优先级 3",
    desc: "价格回调或反弹后，把净敞口拉回目标结构（Δ→Δ*）。恢复比例已由 Δ* 内核按 base 目标计算。",
    fields: [
      field("回调触发", "position_recovery.trigger.pullback_pct_from_trend_extreme"),
      field("盈利侧恢复比例", "position_recovery.sizing.restore_profit_side_ratio", 100, true),
      field("亏损侧归一比例", "position_recovery.sizing.normalize_loss_side_ratio", 100, true),
      field("目标仓位偏差", "position_recovery.target.target_balance_position_distance_pct", 100),
    ],
  },
  {
    title: "亏损腿减仓",
    color: "orange",
    priority: "优先级 1",
    desc: "单边趋势确认后，先止损逆势偏斜，再逐步削减亏损腿。",
    fields: [
      field("单边确认幅度", "loss_side_reduction.trigger.trend_confirm_move_pct_from_base"),
      field("每步减仓触发", "loss_side_reduction.trigger.reduce_step_pct"),
      field("每步减仓比例", "loss_side_reduction.sizing.reduce_loss_side_ratio", 100),
      field("最低保留仓位", "loss_side_reduction.sizing.min_loss_side_position_ratio_of_base", 100),
    ],
  },
]);

function field(label, path, multiplier = 1, unwired = false) {
  return { label, path, multiplier, unwired };
}

function getByPath(source, path) {
  return path.split(".").reduce((node, part) => node?.[part], source);
}

function setByPath(target, path, value) {
  const parts = path.split(".");
  let node = target;
  for (let index = 0; index < parts.length - 1; index += 1) {
    node[parts[index]] ||= {};
    node = node[parts[index]];
  }
  node[parts.at(-1)] = value;
}

watchEffect(() => {
  for (const card of cards.value) {
    for (const item of card.fields) {
      const value = getByPath(cfg.value, item.path);
      form[item.path] = Number(value || 0) * item.multiplier;
    }
  }
});

async function submit() {
  const next = structuredClone(cfg.value);
  for (const card of cards.value) {
    for (const item of card.fields) {
      if (item.unwired) continue;
      setByPath(next, item.path, Number(form[item.path] || 0) / item.multiplier);
    }
  }
  await saveEventConfig(next);
}
</script>
