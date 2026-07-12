<template>
  <section class="page active">
    <div class="page-toolbar">
      <div>
        <h2>策略事件参数</h2>
        <p>利润搬运、仓位恢复、亏损腿减仓。</p>
      </div>
      <div class="action-row">
        <select class="select-control" aria-label="系统策略选择">
          <option>系统策略：Dynamic Dual Grid V1</option>
        </select>
        <button class="button" @click="submit">保存配置</button>
      </div>
    </div>
    <div class="event-config-grid">
      <article v-for="card in cards" :key="card.title" class="event-card" :class="card.color">
        <div class="event-card-header">
          <h3>{{ card.title }}</h3>
          <StatusBadge :text="card.priority" :color="card.color" />
        </div>
        <label v-for="field in card.fields" :key="field.path" class="field">
          <span>{{ field.label }}</span>
          <input v-model.number="form[field.path]" type="number" min="0" step="0.01" />
        </label>
        <p class="muted">{{ card.desc }}</p>
      </article>
    </div>
  </section>
</template>

<script setup>
import { computed, reactive, watchEffect } from "vue";
import StatusBadge from "../components/StatusBadge.vue";
import { saveEventConfig, store } from "../stores/appStore.js";

const form = reactive({});
const cfg = computed(() => store.state?.event_config || {});

const cards = computed(() => [
  {
    title: "利润搬运",
    color: "green",
    priority: "优先级 2",
    desc: "盈利腿减仓实现净利润，再按配置恢复或增加亏损腿。",
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
    desc: "价格回调或反弹后，逐步把多空仓位拉回目标结构。",
    fields: [
      field("回调触发", "position_recovery.trigger.pullback_pct_from_trend_extreme"),
      field("盈利侧恢复比例", "position_recovery.sizing.restore_profit_side_ratio", 100),
      field("亏损侧归一比例", "position_recovery.sizing.normalize_loss_side_ratio", 100),
      field("目标仓位偏差", "position_recovery.target.target_balance_position_distance_pct", 100),
    ],
  },
  {
    title: "亏损腿减仓",
    color: "orange",
    priority: "优先级 1",
    desc: "单边趋势确认后，停止逆势恢复并逐步削减亏损腿。",
    fields: [
      field("单边确认幅度", "loss_side_reduction.trigger.trend_confirm_move_pct_from_base"),
      field("每步减仓触发", "loss_side_reduction.trigger.reduce_step_pct"),
      field("每步减仓比例", "loss_side_reduction.sizing.reduce_loss_side_ratio", 100),
      field("最低保留仓位", "loss_side_reduction.sizing.min_loss_side_position_ratio_of_base", 100),
    ],
  },
]);

function field(label, path, multiplier = 1) {
  return { label, path, multiplier };
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
      setByPath(next, item.path, Number(form[item.path] || 0) / item.multiplier);
    }
  }
  await saveEventConfig(next);
}
</script>
