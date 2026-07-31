<template>
  <span class="help-tip">
    <button
      type="button"
      class="help-tip-trigger"
      :aria-label="`${term || '指标'}解释`"
      :aria-expanded="open"
      :title="explanation"
      @click.stop="open = !open"
      @blur="open = false"
    >?</button>
    <span class="help-tip-content" :class="{ open }" role="tooltip">
      <strong v-if="term">{{ term }}</strong>
      {{ explanation }}
    </span>
  </span>
</template>

<script setup>
import { computed, ref } from "vue";
import { TERM_HELP } from "../domain/labels.js";

const props = defineProps({
  term: { type: String, default: "" },
  text: { type: String, default: "" },
});
const open = ref(false);
const explanation = computed(() => props.text || TERM_HELP[props.term] || "暂无解释。");
</script>
