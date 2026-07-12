<template>
  <section class="page active">
    <div v-if="symbol" class="summary-grid compact">
      <SummaryItem label="当前币种" :value="symbol.symbol"><StatusBadge :text="stateLabel(symbol.state)" :color="stateColor(symbol.state)" /></SummaryItem>
      <SummaryItem label="当前价格" :value="fmt(symbol.price, symbol.symbol === 'SOLUSDT' ? 3 : 2)" note="Binance mark price" />
      <SummaryItem label="基准价" :value="fmt(symbol.base_price, 2)" :note="`偏离 ${fmt(symbol.move_pct, 2)}%`" />
      <SummaryItem label="浮动盈亏" :note="`净敞口 ${fmt(symbol.net_exposure)} USDT`"><span :class="cls(symbol.unrealized_pnl)">{{ fmt(symbol.unrealized_pnl) }} USDT</span></SummaryItem>
    </div>
    <div v-else class="summary-grid compact">
      <SummaryItem label="当前币种" value="暂无" note="请先同步 Binance" />
    </div>

    <article class="panel">
      <div class="panel-head">
        <h3>币种列表</h3>
        <StatusBadge v-if="symbol" :text="stateLabel(symbol.state)" :color="stateColor(symbol.state)" />
      </div>
      <div class="table-wrap">
        <table>
          <thead><tr><th>币种</th><th>状态</th><th>价格</th><th>多头</th><th>空头</th><th>浮盈亏</th><th>最近事件</th></tr></thead>
          <tbody>
            <tr v-for="item in symbols" :key="item.symbol">
              <td><button class="tab" :class="{ active: store.selectedSymbol === item.symbol }" @click="selectSymbol(item.symbol)">{{ item.symbol }}</button></td>
              <td><StatusBadge :text="stateLabel(item.state)" :color="stateColor(item.state)" /></td>
              <td>{{ fmt(item.price, item.symbol === "SOLUSDT" ? 3 : 2) }}</td>
              <td>{{ fmt(item.long_qty, 6) }}</td>
              <td>{{ fmt(item.short_qty, 6) }}</td>
              <td :class="cls(item.unrealized_pnl)">{{ fmt(item.unrealized_pnl) }} USDT</td>
              <td>{{ lastEvents[item.symbol] ? eventLabel(lastEvents[item.symbol].event_type) : "无" }}</td>
            </tr>
            <tr v-if="!symbols.length"><td colspan="7" class="muted">暂无真实仓位。请先同步 Binance 账户。</td></tr>
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
          <div><h4>仓位名义价值</h4><div class="mini-chart"><MultiLineChart :data="positionData" :keys="['long', 'short']" :colors="['#078f52', '#d92d20']" /></div></div>
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
import { computed } from "vue";
import LineChart from "../components/LineChart.vue";
import MultiLineChart from "../components/MultiLineChart.vue";
import StatusBadge from "../components/StatusBadge.vue";
import SummaryItem from "../components/SummaryItem.vue";
import { cls, fmt } from "../core/format.js";
import { eventLabel, stateColor, stateLabel } from "../domain/labels.js";
import { currentSymbol, selectSymbol, store, symbols } from "../stores/appStore.js";

const symbol = computed(() => currentSymbol());
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
