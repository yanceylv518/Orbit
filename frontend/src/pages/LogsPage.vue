<template>
  <section class="page active">
    <article class="panel">
      <div class="panel-head"><h3>策略事件日志</h3></div>
      <div class="event-log">
        <div v-for="event in events.slice(0, 24)" :key="event.id" class="event-item">
          <strong>{{ eventLabel(event.event_type) }} · {{ event.symbol }}</strong>
          <div class="muted">{{ event.timestamp }} / {{ stateLabel(event.state_before) }} -> {{ stateLabel(event.state_after) }}</div>
          <p>{{ event.reason }}</p>
          <div class="table-wrap">
            <table>
              <thead><tr><th>动作</th><th>方向</th><th>数量</th><th>成交价</th><th>手续费</th><th>已实现盈亏</th></tr></thead>
              <tbody>
                <tr v-for="trade in event.trades || []" :key="trade.id">
                  <td>{{ trade.action }}</td>
                  <td>{{ trade.position_side }}</td>
                  <td>{{ fmt(trade.qty, 6) }}</td>
                  <td>{{ fmt(trade.fill_price, 4) }}</td>
                  <td>{{ fmt(trade.fee, 4) }}</td>
                  <td :class="cls(trade.realized_pnl)">{{ fmt(trade.realized_pnl, 4) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
        <p v-if="!events.length" class="muted">暂无策略事件。</p>
      </div>
    </article>
  </section>
</template>

<script setup>
import { computed } from "vue";
import { cls, fmt } from "../core/format.js";
import { eventLabel, stateLabel } from "../domain/labels.js";
import { store } from "../stores/appStore.js";

const events = computed(() => store.state?.strategy_events || []);
</script>
