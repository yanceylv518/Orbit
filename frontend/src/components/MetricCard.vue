<template>
  <article class="metric-card">
    <span>{{ label }}</span>
    <strong :class="valueClass">{{ value }}</strong>
    <small>{{ note }}</small>
  </article>
</template>

<script setup>
defineProps({
  label: { type: String, required: true },
  value: { type: [String, Number], default: "--" },
  note: { type: String, default: "" },
  valueClass: { type: String, default: "" },
});
</script>
