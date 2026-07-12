<template>
  <svg
    v-if="points"
    :viewBox="`0 0 ${width} ${height}`"
    width="100%"
    height="100%"
    preserveAspectRatio="none"
  >
    <rect x="0" y="0" :width="width" :height="height" fill="transparent" />
    <line :x1="pad" :x2="width - pad" :y1="height - pad" :y2="height - pad" stroke="#22304a" />
    <line :x1="pad" :x2="pad" :y1="pad" :y2="height - pad" stroke="#22304a" />
    <polyline :points="points" fill="none" stroke="#3987e5" stroke-width="2" />
    <text :x="pad" y="18" fill="#93a1bb" font-size="12">{{ label }}: {{ fmt(lastValue, 2) }}</text>
  </svg>
</template>

<script setup>
import { computed } from "vue";
import { fmt } from "../core/format.js";

const props = defineProps({
  data: { type: Array, default: () => [] },
  dataKey: { type: String, required: true },
  label: { type: String, default: "" },
  width: { type: Number, default: 640 },
  height: { type: Number, default: 248 },
  pad: { type: Number, default: 28 },
});

const values = computed(() => props.data.map((item) => Number(item[props.dataKey] || 0)));
const lastValue = computed(() => values.value.at(-1) || 0);
const points = computed(() => {
  if (!props.data.length) return "";
  const min = Math.min(...values.value);
  const max = Math.max(...values.value);
  const span = max - min || 1;
  return props.data.map((item, index) => {
    const x = props.pad + (index / Math.max(props.data.length - 1, 1)) * (props.width - props.pad * 2);
    const y = props.height - props.pad - ((Number(item[props.dataKey]) - min) / span) * (props.height - props.pad * 2);
    return `${x},${y}`;
  }).join(" ");
});
</script>
