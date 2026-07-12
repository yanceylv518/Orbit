<template>
  <section class="page active">
    <!-- 主流程漏斗：逐格可点击直达 -->
    <div class="metric-grid funnel-grid">
      <button class="metric-link" @click="setActivePage('accounts')">
        <MetricCard
          label="账户同步"
          :value="`${syncFunnel.syncedCount}/${syncFunnel.total}`"
          :note="syncFunnel.failed.length ? `${syncFunnel.failed.length} 个失败` : (syncFunnel.unsynced.length ? `${syncFunnel.unsynced.length} 个未同步` : '全部就绪')"
          :value-class="syncFunnel.failed.length ? 'negative' : ''"
        />
      </button>
      <button class="metric-link" @click="setActivePage('accounts')">
        <MetricCard
          label="Hedge Mode"
          :value="`${syncFunnel.hedgeOkCount}/${syncFunnel.syncedCount}`"
          :note="syncFunnel.hedgeFail.length ? `${syncFunnel.hedgeFail.length} 个未通过` : '已同步账户全部通过'"
          :value-class="syncFunnel.hedgeFail.length ? 'negative' : ''"
        />
      </button>
      <button class="metric-link" @click="setActivePage('plans')">
        <MetricCard label="计划待确认" :value="planFunnel.pendingConfirm.length" note="待人工审查" />
      </button>
      <button class="metric-link" @click="setActivePage('risk')">
        <MetricCard
          label="风控拦截"
          :value="planFunnel.blocked.length"
          note="点击进入风控中心"
          :value-class="planFunnel.blocked.length ? 'negative' : ''"
        />
      </button>
      <button class="metric-link" @click="setActivePage('plans')">
        <MetricCard label="无动作" :value="planFunnel.noActionCount" note="未满足触发条件" />
      </button>
    </div>

    <div class="todo-grid">
      <!-- 待办：同步失败账户 -->
      <article class="panel">
        <div class="panel-head">
          <h3>待处理：账户同步</h3>
          <button class="button ghost small" :disabled="store.syncAllBusy" @click="syncAllAccounts">
            {{ store.syncAllBusy ? "同步中..." : "同步全部账户" }}
          </button>
        </div>
        <div class="table-wrap">
          <table>
            <thead><tr><th>账户</th><th>状态</th><th>原因</th><th>操作</th></tr></thead>
            <tbody>
              <tr v-for="row in problemAccounts" :key="row.account.id">
                <td>
                  <strong>{{ row.account.account_label }}</strong>
                  <div class="muted">{{ row.account.id }}</div>
                </td>
                <td><StatusBadge :text="statusLabel(row.snapshot?.status || 'unsynced')" :color="row.snapshot?.status === 'error' ? 'red' : 'orange'" /></td>
                <td class="wrap-cell">{{ row.snapshot?.error || (row.snapshot ? hedgeNote(row) : "尚未同步") }}</td>
                <td><button class="button small" @click="syncBinanceAccount(row.account.id)">同步</button></td>
              </tr>
              <tr v-if="!problemAccounts.length">
                <td colspan="4" class="muted">
                  {{ syncFunnel.total ? "全部账户同步正常。" : "尚无交易账户。" }}
                  <a v-if="!syncFunnel.total" href="#accounts" @click.prevent="setActivePage('accounts')">去添加账户</a>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </article>

      <!-- 待办：待确认计划 -->
      <article class="panel">
        <div class="panel-head">
          <h3>待处理：执行计划</h3>
          <button class="button ghost small" @click="generateExecutionPlans('')">生成执行计划</button>
        </div>
        <div class="table-wrap">
          <table>
            <thead><tr><th>币种</th><th>事件</th><th>相位</th><th>Δ → Δ*</th><th>操作</th></tr></thead>
            <tbody>
              <tr v-for="plan in planFunnel.pendingConfirm.slice(0, 5)" :key="plan.id">
                <td><strong>{{ plan.symbol }}</strong></td>
                <td>{{ eventLabel(plan.event_type) }}</td>
                <td><StatusBadge :text="stateLabel(plan.trigger?.lifecycle_state || '-')" :color="stateColor(plan.trigger?.lifecycle_state || '')" /></td>
                <td class="mono">{{ deltaText(plan) }}</td>
                <td><button class="button small" @click="setActivePage('plans')">审查</button></td>
              </tr>
              <tr v-if="!planFunnel.pendingConfirm.length">
                <td colspan="5" class="muted">没有待确认计划。同步账户后可生成执行计划。</td>
              </tr>
            </tbody>
          </table>
        </div>
      </article>
    </div>

    <!-- 系统状态行 -->
    <article class="panel status-line-panel">
      <div class="status-line">
        <span><span class="muted">运行模式</span> <StatusBadge :text="modeLabel(strategy.mode)" color="blue" /></span>
        <span><span class="muted">策略</span> {{ strategy.name }} {{ strategy.version }} · <StatusBadge :text="statusLabel(strategy.status)" :color="statusColor(strategy.status)" /></span>
        <span><span class="muted">存储</span> {{ storageLabel }}</span>
        <span><span class="muted">内核</span> {{ kernelLabel }}</span>
        <span><span class="muted">最近同步</span> {{ lastSyncedLabel }}</span>
        <span v-if="feed">
          <span class="muted">行情源</span>
          <template v-if="feed.last_error"><span class="negative">{{ feed.interval }} 异常</span></template>
          <template v-else>{{ feed.interval }} · tick {{ feed.tick_count }}</template>
        </span>
        <span><span class="muted">总权益</span> {{ fmt(strategy.total_equity) }} USDT</span>
        <span><span class="muted">今日盈亏</span> <span :class="cls(strategy.today_pnl)">{{ fmt(strategy.today_pnl) }} USDT</span></span>
      </div>
    </article>
  </section>
</template>

<script setup>
import { computed } from "vue";
import MetricCard from "../components/MetricCard.vue";
import StatusBadge from "../components/StatusBadge.vue";
import { cls, fmt } from "../core/format.js";
import { eventLabel, modeLabel, stateColor, stateLabel, statusColor, statusLabel } from "../domain/labels.js";
import {
  executionPlans,
  generateExecutionPlans,
  marketFeed,
  planFunnel,
  setActivePage,
  store,
  syncAllAccounts,
  syncBinanceAccount,
  syncFunnel,
} from "../stores/appStore.js";

const feed = marketFeed;

const state = computed(() => store.state || {});
const strategy = computed(() => state.value.strategy || {});
const storageLabel = computed(() => (state.value.storage?.driver === "mysql" ? "MySQL / Binance" : "JSON fallback"));
const kernelLabel = computed(() => {
  const plan = executionPlans.value.find((item) => item.trigger?.exposure_model);
  return plan?.trigger?.exposure_model || "net_exposure_v1";
});
const lastSyncedLabel = computed(() => {
  const at = syncFunnel.value.lastSyncedAt;
  if (!at) return "从未同步";
  return typeof at === "number" ? new Date(at).toLocaleString() : String(at);
});

// 需要处理的账户 = 同步失败 + 未同步 + Hedge 未通过
const problemAccounts = computed(() => [
  ...syncFunnel.value.failed,
  ...syncFunnel.value.unsynced,
  ...syncFunnel.value.hedgeFail,
]);

function hedgeNote(row) {
  return row.snapshot?.position_mode?.hedge_mode_ok === false ? "Hedge Mode 未通过，请在 Binance 开启双向持仓" : "-";
}

function deltaText(plan) {
  const trigger = plan.trigger || {};
  if (trigger.current_net_qty === undefined) return "-";
  return `${fmt(trigger.current_net_qty, 4)} → ${fmt(trigger.target_net_qty, 4)}`;
}
</script>
