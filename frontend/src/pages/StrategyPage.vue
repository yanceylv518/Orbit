<template>
  <section class="strategy-workspace-page">
    <div class="page-toolbar strategy-tabs-toolbar">
      <div>
        <h2>{{ activeTab === "official" ? "正式策略" : "研究候选" }}</h2>
        <p>
          {{ activeTab === "official"
            ? "查看已准入策略的冻结定义、运行阶段和已知风险。"
            : "按预注册、冻结和锁箱纪律检验下一个候选。" }}
        </p>
      </div>
      <div class="action-row" role="tablist" aria-label="策略工作区">
        <button
          class="tab"
          :class="{ active: activeTab === 'official' }"
          role="tab"
          :aria-selected="activeTab === 'official'"
          @click="setStrategyTab('official')"
        >
          正式策略
        </button>
        <button
          class="tab"
          :class="{ active: activeTab === 'research' }"
          role="tab"
          :aria-selected="activeTab === 'research'"
          @click="setStrategyTab('research')"
        >
          研究候选
        </button>
      </div>
    </div>

    <StrategyCenterPage v-show="activeTab === 'official'" />
    <ResearchPage v-show="activeTab === 'research'" />
  </section>
</template>

<script setup>
import { computed } from "vue";
import ResearchPage from "./ResearchPage.vue";
import StrategyCenterPage from "./StrategyCenterPage.vue";
import { setStrategyTab, store } from "../stores/appStore.js";

const activeTab = computed(() => store.activeStrategyTab);
</script>
