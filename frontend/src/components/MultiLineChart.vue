<template>
  <svg
    v-if="linePoints.length"
    :viewBox="`0 0 ${width} ${height}`"
    width="100%"
    height="100%"
    preserveAspectRatio="none"
  >
    <line :x1="pad" :x2="width - pad" :y1="height - pad" :y2="height - pad" stroke="#22304a" />
    <polyline
      v-for="line in linePoints"
      :key="line.key"
      :points="line.points"
      fill="none"
      :stroke="line.color"
      stroke-width="2"
    />
  </svg>
</template>

<script setup>
import { computed } from "vue";

const props = defineProps({
  data: { type: Array, default: () => [] },
  keys: { type: Array, default: () => [] },
  colors: { type: Array, default: () => [] },
  width: { type: Number, default: 300 },
  height: { type: Number, default: 150 },
  pad: { type: Number, default: 22 },
});

const linePoints = computed(() => {
  if (!props.data.length || !props.keys.length) return [];
  const values = props.data.flatMap((item) => props.keys.map((key) => Number(item[key] || 0)));
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  return props.keys.map((key, index) => ({
    key,
    color: props.colors[index] || "#3987e5",
    points: props.data.map((item, itemIndex) => {
      const x = props.pad + (itemIndex / Math.max(props.data.length - 1, 1)) * (props.width - props.pad * 2);
      const y = props.height - props.pad - ((Number(item[key]) - min) / span) * (props.height - props.pad * 2);
      return `${x},${y}`;
    }).join(" "),
  }));
});
</script>
