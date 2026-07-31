<template>
  <div class="summary-item">
    <span>{{ label }} <HelpTip v-if="help" :term="help" /></span>
    <strong>
      <slot>{{ value }}</slot>
    </strong>
    <small v-if="note">{{ note }}</small>
  </div>
</template>

<script setup>
import HelpTip from "./HelpTip.vue";

defineProps({
  label: { type: String, required: true },
  value: { type: [String, Number], default: "--" },
  note: { type: String, default: "" },
  help: { type: String, default: "" },
});
</script>
