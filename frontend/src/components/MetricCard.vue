<template>
  <article class="metric-card">
    <span>{{ label }} <HelpTip v-if="help" :term="help" /></span>
    <strong :class="valueClass">{{ value }}</strong>
    <small>{{ note }}</small>
  </article>
</template>

<script setup>
import HelpTip from "./HelpTip.vue";

defineProps({
  label: { type: String, required: true },
  value: { type: [String, Number], default: "--" },
  note: { type: String, default: "" },
  valueClass: { type: String, default: "" },
  help: { type: String, default: "" },
});
</script>
