<template>
  <span class="help-tip">
    <span
      class="help-tip-trigger"
      :aria-label="`${term || '指标'}解释`"
      :title="explanation"
    >?</span>
    <span class="help-tip-content" role="tooltip">
      <strong v-if="term">{{ term }}</strong>
      {{ explanation }}
    </span>
  </span>
</template>

<script setup>
import { computed } from "vue";
import { TERM_HELP } from "../domain/labels.js";

const props = defineProps({
  term: { type: String, default: "" },
  text: { type: String, default: "" },
});
const explanation = computed(() => props.text || TERM_HELP[props.term] || "暂无解释。");
</script>
