<template>
  <section class="page active">
    <div class="metric-grid">
      <MetricCard label="总权益" :value="fmt(strategy.total_equity)" note="USDT" />
      <MetricCard label="今日盈亏" :value="fmt(strategy.today_pnl)" :note="`${fmt(strategy.today_pnl_pct, 3)}%`" :value-class="cls(strategy.today_pnl)" />
      <MetricCard label="运行模式" :value="modeLabel(strategy.mode)" :note="statusLabel(strategy.status)" />
      <MetricCard label="风控状态" :value="strategy.risk_status === 'normal' ? '正常' : '关注'" :note="storageLabel" />
    </div>

    <div class="dashboard-stack">
      <article class="panel full-panel">
        <div class="panel-head">
          <h3>系统策略</h3>
          <span class="pill">Tick {{ state.tick_index }}</span>
        </div>
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>策略名称</th>
                <th>运行模式</th>
                <th>状态</th>
                <th>币种数量</th>
                <th>今日盈亏</th>
                <th>总权益</th>
                <th>数据源</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td><strong>{{ strategy.name }} {{ strategy.version }}</strong><div class="muted">{{ strategy.id || "system" }}</div></td>
                <td>{{ modeLabel(strategy.mode) }}</td>
                <td><StatusBadge :text="statusLabel(strategy.status)" :color="statusColor(strategy.status)" /></td>
                <td>{{ strategy.symbol_count }}</td>
                <td :class="cls(strategy.today_pnl)">{{ fmt(strategy.today_pnl) }} USDT</td>
                <td>{{ fmt(strategy.total_equity) }} USDT</td>
                <td>{{ storageLabel }}</td>
                <td><button class="button ghost small" @click="setActivePage('events')">查看</button></td>
              </tr>
            </tbody>
          </table>
        </div>
      </article>

      <article class="panel full-panel">
        <div class="panel-head">
          <h3>币种状态</h3>
          <button class="button ghost small" @click="setActivePage('symbol')">查看仓位</button>
        </div>
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>币种</th>
                <th>状态</th>
                <th>当前价格</th>
                <th>多头仓位</th>
                <th>空头仓位</th>
                <th>浮动盈亏</th>
                <th>最近事件</th>
                <th>更新时间</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="symbol in symbols" :key="symbol.symbol">
                <td><button class="tab" :class="{ active: store.selectedSymbol === symbol.symbol }" @click="selectSymbol(symbol.symbol, true)">{{ symbol.symbol }}</button></td>
                <td><StatusBadge :text="stateLabel(symbol.state)" :color="stateColor(symbol.state)" /></td>
                <td>{{ fmt(symbol.price, symbol.symbol === "SOLUSDT" ? 3 : 2) }}</td>
                <td>{{ fmt(symbol.long_qty, 6) }}</td>
                <td>{{ fmt(symbol.short_qty, 6) }}</td>
                <td :class="cls(symbol.unrealized_pnl)">{{ fmt(symbol.unrealized_pnl) }} USDT</td>
                <td>{{ lastEvents[symbol.symbol] ? eventLabel(lastEvents[symbol.symbol].event_type) : "无" }}</td>
                <td>{{ symbol.updated_at || state.server_time }}</td>
              </tr>
              <tr v-if="!symbols.length"><td colspan="8" class="muted">暂无真实仓位。请在交易账户页同步 Binance 后查看。</td></tr>
            </tbody>
          </table>
        </div>
      </article>
    </div>
  </section>
</template>

<script setup>
import { computed } from "vue";
import MetricCard from "../components/MetricCard.vue";
import StatusBadge from "../components/StatusBadge.vue";
import { cls, fmt } from "../core/format.js";
import { eventLabel, modeLabel, stateColor, stateLabel, statusColor, statusLabel } from "../domain/labels.js";
import { selectSymbol, setActivePage, store, symbols } from "../stores/appStore.js";

const state = computed(() => store.state || {});
const strategy = computed(() => state.value.strategy || {});
const storageLabel = computed(() => state.value.storage?.driver === "mysql" ? "MySQL / Binance" : "JSON fallback");
const lastEvents = computed(() => {
  const result = {};
  for (const event of state.value.strategy_events || []) {
    if (!result[event.symbol]) result[event.symbol] = event;
  }
  return result;
});
</script>
