<template>
  <span class="badge" :class="color">{{ text }}</span>
</template>

<script setup>
defineProps({
  text: { type: [String, Number], default: "-" },
  color: { type: String, default: "blue" },
});
</script>
