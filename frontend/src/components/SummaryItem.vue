<template>
  <div class="summary-item">
    <span>{{ label }}</span>
    <strong>
      <slot>{{ value }}</slot>
    </strong>
    <small v-if="note">{{ note }}</small>
  </div>
</template>

<script setup>
defineProps({
  label: { type: String, required: true },
  value: { type: [String, Number], default: "--" },
  note: { type: String, default: "" },
});
</script>
