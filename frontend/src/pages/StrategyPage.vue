<template>
  <section class="strategy-workspace-page">
    <div class="page-toolbar strategy-tabs-toolbar">
      <div>
        <h2>{{ activeTab === "official" ? "正式运行的策略" : "正在检验的候选" }}</h2>
        <p>
          {{ activeTab === "official"
            ? "看清系统现在交易什么、为什么这样做，以及有哪些已知风险。"
            : "跑数据前先写死规则和及格线，再用一次性考卷检验候选。" }}
          <HelpTip v-if="activeTab === 'research'" term="预注册" />
          <HelpTip v-if="activeTab === 'research'" term="锁箱" />
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
import HelpTip from "../components/HelpTip.vue";
import ResearchPage from "./ResearchPage.vue";
import StrategyCenterPage from "./StrategyCenterPage.vue";
import { setStrategyTab, store } from "../stores/appStore.js";

const activeTab = computed(() => store.activeStrategyTab);
</script>
