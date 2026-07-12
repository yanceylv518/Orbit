<template>
  <div class="trigger-progress" :title="`偏离 ${absMove.toFixed(2)}% · 偏斜线 ${aPt}% · 趋势线 ${thetaT}%`">
    <div class="trigger-track">
      <div class="trigger-fill" :class="fillClass" :style="{ width: fillWidth }"></div>
      <span class="trigger-mark" :style="{ left: markLeft(aPt) }"></span>
      <span class="trigger-mark trend" :style="{ left: markLeft(thetaT) }"></span>
    </div>
    <div class="trigger-legend">
      <span>0</span>
      <span>偏斜 {{ aPt }}%</span>
      <span>趋势 {{ thetaT }}%</span>
    </div>
  </div>
</template>

<script setup>
import { computed } from "vue";

const props = defineProps({
  movePct: { type: Number, default: 0 },
  aPt: { type: Number, default: 1.5 },
  thetaT: { type: Number, default: 4 },
});

const absMove = computed(() => Math.abs(Number(props.movePct) || 0));
// 刻度上限 = 趋势线再放 15%，保证趋势线不顶格
const scale = computed(() => Math.max(props.thetaT * 1.15, absMove.value, 0.0001));
const fillWidth = computed(() => `${Math.min(100, (absMove.value / scale.value) * 100)}%`);
const fillClass = computed(() => {
  if (absMove.value >= props.thetaT) return "trend";
  if (absMove.value >= props.aPt) return "skew";
  return "calm";
});

function markLeft(value) {
  return `${Math.min(100, (value / scale.value) * 100)}%`;
}
</script>
