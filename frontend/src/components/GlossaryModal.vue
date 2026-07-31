<template>
  <div v-if="open" class="modal-backdrop glossary-backdrop" @click.self="$emit('close')" @keydown.esc="$emit('close')">
    <section class="modal-dialog glossary-dialog" role="dialog" aria-modal="true" aria-labelledby="glossary-title">
      <div class="modal-head">
        <div>
          <h3 id="glossary-title">术语帮助</h3>
          <p class="muted">先看人话解释；原术语保留，方便与报告、账本和文档对照。</p>
        </div>
        <button class="modal-close" type="button" aria-label="关闭术语帮助" @click="$emit('close')">×</button>
      </div>
      <div class="table-wrap glossary-table">
        <table>
          <thead><tr><th>术语</th><th>人话</th><th>一句解释</th></tr></thead>
          <tbody>
            <tr v-for="item in GLOSSARY_TERMS" :key="item.term">
              <td><strong>{{ item.term }}</strong> <HelpTip :text="item.explanation" /></td>
              <td>{{ item.plain }}</td>
              <td>{{ item.explanation }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </div>
</template>

<script setup>
import HelpTip from "./HelpTip.vue";
import { GLOSSARY_TERMS } from "../domain/labels.js";

defineProps({ open: { type: Boolean, default: false } });
defineEmits(["close"]);
</script>
