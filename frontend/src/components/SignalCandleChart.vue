<template>
  <div class="signal-chart-wrap">
    <div v-if="!candles.length" class="chart-empty">旧信号未保存图形快照；新产生的信号会显示真实 K 线和成交量。</div>
    <svg v-else class="signal-candle-chart" :viewBox="`0 0 ${width} ${height}`" role="img" :aria-label="`${symbol} 信号 K 线与成交量`">
      <g class="grid">
        <line v-for="y in [18, 72, 126, 180]" :key="y" x1="42" :x2="width - 8" :y1="y" :y2="y" />
      </g>
      <g v-for="(bar, index) in plotted" :key="bar.open_time_ms">
        <line :x1="bar.x" :x2="bar.x" :y1="bar.highY" :y2="bar.lowY" :class="bar.up ? 'up' : 'down'" />
        <rect :x="bar.x - bodyWidth / 2" :y="Math.min(bar.openY, bar.closeY)" :width="bodyWidth" :height="Math.max(1, Math.abs(bar.openY - bar.closeY))" :class="bar.up ? 'up-fill' : 'down-fill'">
          <title>{{ tooltip(bar) }}</title>
        </rect>
        <rect :x="bar.x - bodyWidth / 2" :y="volumeY(bar.volume)" :width="bodyWidth" :height="236 - volumeY(bar.volume)" :class="bar.up ? 'volume-up' : 'volume-down'">
          <title>{{ tooltip(bar) }}</title>
        </rect>
        <g v-if="index === signalIndex" class="signal-marker">
          <path :d="`M ${bar.x - 5} ${Math.max(8, bar.highY - 13)} L ${bar.x + 5} ${Math.max(8, bar.highY - 13)} L ${bar.x} ${Math.max(13, bar.highY - 5)} Z`" />
          <line :x1="bar.x" :x2="bar.x" :y1="Math.max(13, bar.highY - 5)" :y2="Math.max(16, bar.highY - 1)" />
        </g>
      </g>
      <line v-if="entryY !== null" x1="42" :x2="width - 8" :y1="entryY" :y2="entryY" class="entry-line" />
      <line v-if="stopY !== null" x1="42" :x2="width - 8" :y1="stopY" :y2="stopY" class="stop-line" />
      <text x="4" :y="entryY - 3" v-if="entryY !== null" class="entry-label">进场</text>
      <text x="4" :y="stopY - 3" v-if="stopY !== null" class="stop-label">止损</text>
      <text x="4" y="224" class="volume-label">成交量</text>
    </svg>
    <div class="chart-legend"><span class="entry-key">进场</span><span class="stop-key">止损</span><span>▲ 信号时刻</span><span>悬停 K 线查看涨跌幅、振幅与成交量</span></div>
  </div>
</template>

<script setup>
import { computed } from "vue";

const props = defineProps({
  symbol: { type: String, default: "" },
  before: { type: Array, default: () => [] },
  after: { type: Array, default: () => [] },
  entry: { type: Number, default: null },
  stop: { type: Number, default: null },
});
const width = 760; const height = 244;
const candles = computed(() => {
  const map = new Map();
  [...props.before, ...props.after].forEach((row) => map.set(Number(row.open_time_ms), row));
  return [...map.values()].sort((a, b) => Number(a.open_time_ms) - Number(b.open_time_ms)).slice(-80);
});
const priceMin = computed(() => Math.min(...candles.value.flatMap((r) => [Number(r.low), props.stop || Number(r.low)])));
const priceMax = computed(() => Math.max(...candles.value.flatMap((r) => [Number(r.high), props.entry || Number(r.high)])));
const maxVolume = computed(() => Math.max(1, ...candles.value.map((r) => Number(r.quote_volume || 0))));
const priceY = (value) => 190 - ((Number(value) - priceMin.value) / Math.max(priceMax.value - priceMin.value, 1e-12)) * 170;
const bodyWidth = computed(() => Math.max(2, Math.min(9, (width - 54) / Math.max(candles.value.length, 1) * 0.62)));
const plotted = computed(() => candles.value.map((row, index) => ({
  ...row,
  x: 46 + index * ((width - 58) / Math.max(candles.value.length - 1, 1)),
  openY: priceY(row.open), closeY: priceY(row.close), highY: priceY(row.high), lowY: priceY(row.low),
  up: Number(row.close) >= Number(row.open), volume: Number(row.quote_volume || 0),
})));
const signalIndex = computed(() => Math.max(0, props.before.length - 1 - Math.max(0, props.before.length + props.after.length - candles.value.length)));
const entryY = computed(() => props.entry ? priceY(props.entry) : null);
const stopY = computed(() => props.stop ? priceY(props.stop) : null);
const volumeY = (volume) => 236 - (volume / maxVolume.value) * 30;
function tooltip(bar) {
  const change = (Number(bar.close) / Number(bar.open) - 1) * 100;
  const amplitude = (Number(bar.high) / Number(bar.low) - 1) * 100;
  return `${new Date(Number(bar.open_time_ms)).toLocaleString()}\n开 ${bar.open} 高 ${bar.high} 低 ${bar.low} 收 ${bar.close}\n涨跌 ${change.toFixed(2)}% · 振幅 ${amplitude.toFixed(2)}%\n成交额 ${bar.volume.toLocaleString()}`;
}
</script>

<style scoped>
.signal-chart-wrap{min-width:0}.signal-candle-chart{display:block;width:100%;height:244px;background:#0b1526;border:1px solid #203454;border-radius:8px}.grid line{stroke:#1d304d;stroke-width:1}.up,.down{stroke-width:1.2}.up{stroke:#64d3aa}.down{stroke:#ef6a79}.up-fill{fill:#64d3aa}.down-fill{fill:#ef6a79}.volume-up{fill:#1f6d60}.volume-down{fill:#713842}.entry-line{stroke:#4aa3ff;stroke-dasharray:5 4}.stop-line{stroke:#ef6a79;stroke-dasharray:5 4}.entry-label{fill:#69b5ff}.stop-label{fill:#ff8290}.volume-label{fill:#6f829f}.signal-marker path{fill:#f5b94c}.signal-marker line{stroke:#f5b94c}.signal-candle-chart text{font-size:10px}.chart-legend{display:flex;gap:14px;flex-wrap:wrap;color:#7f91ac;font-size:12px;margin-top:6px}.entry-key{color:#69b5ff}.stop-key{color:#ff8290}
.chart-empty{height:120px;display:grid;place-items:center;text-align:center;color:#71839e;background:#0b1526;border:1px solid #203454;border-radius:8px;padding:14px}
</style>
