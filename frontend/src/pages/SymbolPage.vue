<template>
  <section class="page active">
    <!-- 币种卡片头：相位 + 锚点 + 触发进度 + Δ 净敞口 -->
    <article v-if="overview" class="panel symbol-header-panel">
      <div class="panel-head">
        <h3>
          {{ overview.symbol }}
          <StatusBadge :text="stateLabel(phase)" :color="stateColor(phase)" />
        </h3>
        <span class="muted">{{ overview.accountLabels.join(" / ") || "-" }}</span>
      </div>
      <div class="symbol-header-grid">
        <div class="summary-grid compact">
          <SummaryItem label="当前价格" :value="fmt(overview.price, priceDigits)" note="Binance mark price" />
          <SummaryItem label="锚点价" :value="anchorPrice ? fmt(anchorPrice, priceDigits) : '待生成计划'" :note="movePct === null ? '' : `偏离 ${fmt(movePct, 2)}%`" />
          <SummaryItem label="Δ 净敞口" :note="`≈ ${fmt(overview.delta_notional)} USDT`">
            <span :class="cls(overview.delta_qty)">{{ fmt(overview.delta_qty, 6) }}</span>
          </SummaryItem>
          <SummaryItem label="Δ* 目标" :value="targetDelta === null ? '-' : fmt(targetDelta, 6)" :note="deltaGap === null ? '' : `差 ${fmt(deltaGap, 6)}`" />
        </div>
        <div class="symbol-trigger-block">
          <h4 class="muted">触发进度（相对锚点偏离）</h4>
          <TriggerProgress v-if="movePct !== null" :move-pct="movePct" :a-pt="aPt" :theta-t="thetaT" />
          <p v-else class="muted">尚无内核计划上下文。同步账户并生成执行计划后展示。</p>
          <p v-if="kernelContext" class="muted kernel-context-line">
            内核 {{ kernelContext.exposure_model }}
            <template v-if="kernelContext.event_rule"> · 规则 {{ kernelContext.event_rule }}</template>
            <template v-if="kernelContext.target_step_count !== undefined"> · 阶梯 {{ kernelContext.target_step_count }}</template>
            <template v-if="kernelContext.trend_exit_candidate_count !== undefined"> · 趋势退出确认 {{ kernelContext.trend_exit_candidate_count }}</template>
          </p>
        </div>
      </div>
    </article>
    <div v-else class="summary-grid compact">
      <SummaryItem label="当前币种" value="暂无" note="请先同步 Binance" />
    </div>

    <article class="panel">
      <div class="panel-head">
        <h3>币种列表</h3>
        <select v-model="accountFilter" class="select-control" aria-label="按账户筛选">
          <option value="">全部账户</option>
          <option v-for="account in exchangeAccounts" :key="account.id" :value="account.id">{{ account.account_label }}</option>
        </select>
      </div>
      <div class="table-wrap">
        <table>
          <thead><tr><th>币种</th><th>相位</th><th>价格</th><th>多头</th><th>空头</th><th>Δ 净敞口</th><th>浮盈亏</th><th>最近事件</th></tr></thead>
          <tbody>
            <tr v-for="item in overviews" :key="item.symbol">
              <td><button class="tab" :class="{ active: store.selectedSymbol === item.symbol }" @click="selectSymbol(item.symbol)">{{ item.symbol }}</button></td>
              <td><StatusBadge :text="stateLabel(phaseOf(item))" :color="stateColor(phaseOf(item))" /></td>
              <td>{{ fmt(item.price, item.symbol === "SOLUSDT" ? 3 : 2) }}</td>
              <td>{{ fmt(item.long_qty, 6) }}</td>
              <td>{{ fmt(item.short_qty, 6) }}</td>
              <td :class="cls(item.delta_qty)">{{ fmt(item.delta_qty, 6) }}</td>
              <td :class="cls(item.unrealized_pnl)">{{ fmt(item.unrealized_pnl) }} USDT</td>
              <td>{{ lastEvents[item.symbol] ? eventLabel(lastEvents[item.symbol].event_type) : "无" }}</td>
            </tr>
            <tr v-if="!overviews.length"><td colspan="8" class="muted">暂无真实仓位。请先同步 Binance 账户。</td></tr>
          </tbody>
        </table>
      </div>
    </article>

    <div v-if="symbol" class="detail-grid">
      <article class="panel position-panel">
        <h3>仓位概览</h3>
        <div class="position-cards">
          <div class="position-card long"><strong>多头仓位</strong><p>数量：{{ fmt(symbol.long_qty, 6) }}</p><p>入场价：{{ fmt(symbol.long_entry_price, 2) }}</p><p :class="cls(symbol.long_unrealized_pnl)">浮动盈亏：{{ fmt(symbol.long_unrealized_pnl) }} USDT</p></div>
          <div class="position-card short"><strong>空头仓位</strong><p>数量：{{ fmt(symbol.short_qty, 6) }}</p><p>入场价：{{ fmt(symbol.short_entry_price, 2) }}</p><p :class="cls(symbol.short_unrealized_pnl)">浮动盈亏：{{ fmt(symbol.short_unrealized_pnl) }} USDT</p></div>
        </div>
        <dl class="facts">
          <dt>总敞口</dt><dd>{{ fmt(symbol.gross_exposure) }} USDT</dd>
          <dt>净敞口</dt><dd :class="cls(symbol.net_exposure)">{{ fmt(symbol.net_exposure) }} USDT</dd>
          <dt>已实现盈亏</dt><dd :class="cls(symbol.realized_pnl)">{{ fmt(symbol.realized_pnl) }}</dd>
          <dt>搬运次数</dt><dd>{{ symbol.profit_transfer_count }}</dd>
        </dl>
      </article>
      <article class="panel chart-panel">
        <h3>价格走势</h3>
        <div class="chart"><LineChart :data="history" data-key="price" :label="symbol.symbol" /></div>
        <div class="mini-grid">
          <div>
            <h4>仓位名义价值</h4>
            <div class="mini-chart"><MultiLineChart :data="positionData" :keys="['long', 'short']" :colors="['#19a862', '#ad3b48']" /></div>
            <div class="chart-legend">
              <span><i style="background: #19a862"></i>多头</span>
              <span><i style="background: #ad3b48"></i>空头</span>
            </div>
          </div>
          <div><h4>权益曲线</h4><div class="mini-chart"><LineChart :data="equityData" data-key="equity" label="equity" :width="300" :height="150" :pad="22" /></div></div>
        </div>
      </article>
      <article class="panel timeline-panel">
        <h3>事件时间线</h3>
        <div class="timeline">
          <div v-for="event in timelineEvents" :key="event.id" class="timeline-item">
            <strong>{{ eventLabel(event.event_type) }}</strong>
            <div class="muted">{{ event.timestamp }}</div>
            <p>{{ event.reason }}</p>
          </div>
          <p v-if="!timelineEvents.length" class="muted">暂无事件，等待价格触发策略条件。</p>
        </div>
      </article>
    </div>
  </section>
</template>

<script setup>
import { computed, ref } from "vue";
import LineChart from "../components/LineChart.vue";
import MultiLineChart from "../components/MultiLineChart.vue";
import StatusBadge from "../components/StatusBadge.vue";
import SummaryItem from "../components/SummaryItem.vue";
import TriggerProgress from "../components/TriggerProgress.vue";
import { cls, fmt } from "../core/format.js";
import { eventLabel, stateColor, stateLabel } from "../domain/labels.js";
import { aggregateSymbols, currentSymbol, exchangeAccounts, selectSymbol, store, symbols } from "../stores/appStore.js";

const accountFilter = ref("");

const filteredRows = computed(() => (
  accountFilter.value
    ? symbols.value.filter((row) => row.account_id === accountFilter.value)
    : symbols.value
));
const overviews = computed(() => aggregateSymbols(filteredRows.value));
const overview = computed(() => (
  overviews.value.find((item) => item.symbol === store.selectedSymbol) || overviews.value[0] || null
));
const symbol = computed(() => currentSymbol());
const priceDigits = computed(() => (overview.value?.symbol === "SOLUSDT" ? 3 : 2));

// 内核上下文：来自该币种最近一份带 exposure_model 的执行计划 trigger
const kernelContext = computed(() => overview.value?.plan?.trigger || null);
const phase = computed(() => kernelContext.value?.lifecycle_state || overview.value?.plan?.trigger?.lifecycle_state || "REAL_POSITION");
const anchorPrice = computed(() => kernelContext.value?.base_price ?? null);
const movePct = computed(() => {
  if (kernelContext.value?.move_pct_from_base !== undefined) return Number(kernelContext.value.move_pct_from_base);
  if (anchorPrice.value && overview.value?.price) return ((overview.value.price / anchorPrice.value) - 1) * 100;
  return null;
});
const targetDelta = computed(() => (
  kernelContext.value?.target_net_qty !== undefined ? Number(kernelContext.value.target_net_qty) : null
));
const deltaGap = computed(() => (
  kernelContext.value?.delta_to_target_qty !== undefined ? Number(kernelContext.value.delta_to_target_qty) : null
));

// 触发阈值：现为固定百分比配置；σ 化落地后此处换算展示
const eventConfig = computed(() => store.state?.event_config || {});
const aPt = computed(() => Number(eventConfig.value?.profit_transfer?.trigger?.min_price_move_pct_from_base || 1.5));
const thetaT = computed(() => Number(eventConfig.value?.loss_side_reduction?.trigger?.trend_confirm_move_pct_from_base || 4));

function phaseOf(item) {
  return item.plan?.trigger?.lifecycle_state || "REAL_POSITION";
}

const history = computed(() => store.state?.price_history?.[symbol.value?.symbol] || []);
const latest = computed(() => history.value.at(-1)?.price || symbol.value?.price || 0);
const positionData = computed(() => history.value.map((point) => ({ tick: point.tick, long: symbol.value.long_qty * point.price, short: symbol.value.short_qty * point.price })));
const equityData = computed(() => history.value.map((point) => ({ tick: point.tick, equity: symbol.value.equity - (latest.value - point.price) * (symbol.value.long_qty - symbol.value.short_qty) })));
const timelineEvents = computed(() => (store.state?.strategy_events || []).filter((event) => event.symbol === symbol.value?.symbol).slice(0, 8));
const lastEvents = computed(() => {
  const result = {};
  for (const event of store.state?.strategy_events || []) {
    if (!result[event.symbol]) result[event.symbol] = event;
  }
  return result;
});
</script>
