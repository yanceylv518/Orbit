<template>
  <button class="signal-window-card" type="button" @click="$emit('open')">
    <header><span><strong>{{ event.symbol }}</strong><small>{{ year }} · {{ event.tier }}</small></span><b :class="event.net_return_pct >= 0 ? 'positive' : 'negative'">{{ pct(event.net_return_pct) }}</b></header>
    <svg :viewBox="`0 0 ${width} ${height}`" role="img" :aria-label="`${event.symbol} 训练期信号窗口`">
      <rect width="100%" height="100%" fill="#0b1423" />
      <rect v-if="postExitX !== null" :x="postExitX" y="8" :width="width - postExitX - 8" :height="priceBottom - 8" fill="#8393aa" fill-opacity=".08" />
      <line v-for="tick in 3" :key="tick" x1="8" :x2="width - 8" :y1="8 + tick * (priceBottom - 8) / 4" :y2="8 + tick * (priceBottom - 8) / 4" stroke="#26374e" />
      <line :x1="8" :x2="width - 8" :y1="priceY(event.entry_price)" :y2="priceY(event.entry_price)" stroke="#4ea1ff" stroke-dasharray="4 3" />
      <line :x1="8" :x2="width - 8" :y1="priceY(event.stop_price)" :y2="priceY(event.stop_price)" stroke="#ef6c75" stroke-dasharray="4 3" />
      <g v-for="(candle, index) in candles" :key="candle[0]">
        <line :x1="x(index)" :x2="x(index)" :y1="priceY(candle[2])" :y2="priceY(candle[3])" :stroke="candle[4] >= candle[1] ? '#76d5a6' : '#ef6c75'" />
        <rect :x="x(index) - bodyWidth / 2" :y="priceY(Math.max(candle[1], candle[4]))" :width="bodyWidth" :height="Math.max(1, Math.abs(priceY(candle[1]) - priceY(candle[4])))" :fill="candle[4] >= candle[1] ? '#76d5a6' : '#ef6c75'" />
        <rect :x="x(index) - bodyWidth / 2" :y="volumeY(candle[5])" :width="bodyWidth" :height="height - 8 - volumeY(candle[5])" fill="#3e8ef7" fill-opacity=".32" />
      </g>
      <polyline :points="movingAveragePoints" fill="none" stroke="#f0b35a" stroke-width="1.2" />
      <polyline :points="benchmarkPoints" fill="none" stroke="#9f7aea" stroke-width="1.1" stroke-dasharray="3 2" />
      <g v-for="mark in marks" :key="mark.label"><circle :cx="x(mark.index)" :cy="priceY(mark.price)" r="3.5" :fill="mark.color" /><text :x="x(mark.index) + 5" :y="priceY(mark.price) - 5" :fill="mark.color" font-size="8">{{ mark.label }}</text></g>
      <text v-if="postExitX !== null" :x="postExitX + 4" y="17" fill="#8393aa" font-size="8">出场后走势</text>
    </svg>
    <footer><span>最大浮盈 {{ pct(event.annotations.mfe_pct) }} · 第 {{ event.annotations.mfe_bar }} 根</span><span>最大浮亏 {{ pct(event.annotations.mae_pct) }}</span><em v-if="event.stop_then_recovered_2h">止损后又回来</em></footer>
  </button>
</template>

<script setup>
import { computed } from "vue";
const props = defineProps({ event: { type: Object, required: true }, expanded: { type: Boolean, default: false } });
defineEmits(["open"]);
const width = computed(() => props.expanded ? 920 : 420);
const height = computed(() => props.expanded ? 430 : 220);
const candles = computed(() => props.event.window.candles || []);
const priceBottom = computed(() => height.value * .73);
const bodyWidth = computed(() => Math.max(1, (width.value - 16) / Math.max(candles.value.length, 1) * .58));
const prices = computed(() => candles.value.flatMap((row) => [row[2], row[3]]));
const minimum = computed(() => Math.min(...prices.value, props.event.stop_price));
const maximum = computed(() => Math.max(...prices.value, props.event.entry_price));
const maxVolume = computed(() => Math.max(...candles.value.map((row) => row[5]), 1));
const year = computed(() => props.event.entry_year_utc);
const x = (index) => 8 + index * (width.value - 16) / Math.max(candles.value.length - 1, 1);
const priceY = (value) => 8 + (maximum.value - value) / Math.max(maximum.value - minimum.value, 1e-9) * (priceBottom.value - 16);
const volumeY = (value) => height.value - 8 - value / maxVolume.value * (height.value - priceBottom.value - 12);
const postExitX = computed(() => props.event.annotations.exit_index === null ? null : x(props.event.annotations.exit_index));
const movingAveragePoints = computed(() => candles.value.map((_, index) => {
  const rows = candles.value.slice(Math.max(0, index - 7), index + 1);
  return `${x(index)},${priceY(rows.reduce((sum, row) => sum + row[4], 0) / rows.length)}`;
}).join(" "));
const benchmarkPoints = computed(() => {
  const values = props.event.window.benchmark_return_pct || [];
  const valid = values.filter((value) => value !== null);
  const lo = Math.min(...valid, 0); const hi = Math.max(...valid, 0);
  return values.map((value, index) => value === null ? null : `${x(index)},${8 + (hi - value) / Math.max(hi - lo, 1e-9) * (priceBottom.value - 16)}`).filter(Boolean).join(" ");
});
const marks = computed(() => {
  const a = props.event.annotations;
  const rows = candles.value;
  return [
    { label: "进场", index: a.entry_index, price: props.event.entry_price, color: "#4ea1ff" },
    ...(a.exit_index === null ? [] : [{ label: "出场", index: a.exit_index, price: props.event.exit_price, color: "#f0b35a" }]),
    { label: `MFE ${a.mfe_bar}`, index: a.mfe_index, price: props.event.direction === "LONG" ? rows[a.mfe_index][2] : rows[a.mfe_index][3], color: "#76d5a6" },
    { label: "MAE", index: a.mae_index, price: props.event.direction === "LONG" ? rows[a.mae_index][3] : rows[a.mae_index][2], color: "#b6c2d5" },
  ];
});
function pct(value) { return `${Number(value).toFixed(2)}%`; }
</script>
