<template>
  <span class="badge" :class="color" :title="raw ? `系统原始值：${raw}` : title">{{ text }}</span>
</template>

<script setup>
defineProps({
  text: { type: [String, Number], default: "-" },
  color: { type: String, default: "blue" },
  raw: { type: [String, Number], default: "" },
  title: { type: String, default: "" },
});
</script>
