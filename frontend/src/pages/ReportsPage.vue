<template>
  <section class="page active">
    <div class="page-toolbar">
      <div>
        <h2>每日复盘报告</h2>
        <p>先选择报告资源，再查看 Markdown 或图表。</p>
      </div>
      <button class="button" @click="generateReport">生成今日报告</button>
    </div>
    <div class="resource-workspace">
      <article class="panel resource-list-panel">
        <div class="panel-head">
          <h3>资源列表</h3>
          <span class="pill">{{ resources.length }} 项</span>
        </div>

        <div v-if="reports.length" class="report-summary-list">
          <div v-for="report in reports" :key="report.id || report.markdown_path" class="report-summary">
            <strong>{{ report.date }} 日报</strong>
            <span :class="cls(report.daily_pnl)">{{ fmt(report.daily_pnl) }} USDT</span>
            <small>费用 {{ fmt(report.fee_total) }} · 事件 {{ eventCount(report) }}</small>
          </div>
        </div>

        <div class="resource-list">
          <button
            v-for="resource in resources"
            :key="resource.key"
            class="resource-button"
            :class="{ active: selectedKey === resource.key }"
            @click="selectResource(resource.key)"
          >
            <span>{{ resource.title }}</span>
            <small>{{ resource.date }} · {{ resource.typeLabel }}</small>
          </button>
          <p v-if="!resources.length" class="muted">暂无报告资源。生成日报后可在这里选择 Markdown 或图表。</p>
        </div>
      </article>

      <article class="panel resource-preview-panel">
        <div class="panel-head">
          <div>
            <h3>{{ selectedResource ? selectedResource.title : "资源预览" }}</h3>
            <p v-if="selectedResource" class="muted">{{ selectedResource.date }} · {{ selectedResource.typeLabel }}</p>
          </div>
          <a v-if="selectedResource" class="button ghost small" :href="selectedResource.href" target="_blank">新窗口打开</a>
        </div>

        <div v-if="selectedResource?.type === 'image'" class="resource-preview image-preview">
          <img :src="selectedResource.href" :alt="selectedResource.title" />
        </div>

        <div v-else-if="selectedResource?.type === 'markdown'" class="resource-preview markdown-preview">
          <p v-if="markdownLoading" class="muted">正在读取 Markdown...</p>
          <p v-else-if="markdownError" class="login-error">{{ markdownError }}</p>
          <pre v-else>{{ markdownText }}</pre>
        </div>

        <div v-else class="resource-preview empty-preview">
          <p class="muted">请选择左侧资源。</p>
        </div>
      </article>
    </div>
  </section>
</template>

<script setup>
import { computed, ref, watch } from "vue";
import { cls, fmt } from "../core/format.js";
import { generateReport, store } from "../stores/appStore.js";

const reports = computed(() => store.state?.daily_reports || []);
const selectedKey = ref("");
const markdownText = ref("");
const markdownError = ref("");
const markdownLoading = ref(false);

const resources = computed(() => {
  const items = [];
  for (const report of reports.value) {
    const reportKey = report.id || report.markdown_path || report.date;
    if (report.markdown_path) {
      items.push({
        key: `${reportKey}:markdown`,
        type: "markdown",
        typeLabel: "Markdown",
        title: `${report.date} 日报正文`,
        date: report.date,
        path: report.markdown_path,
        href: `/${report.markdown_path}`,
      });
    }
    for (const chart of report.charts || []) {
      items.push({
        key: `${reportKey}:chart:${chart.path}`,
        type: "image",
        typeLabel: "图表",
        title: chart.title || chart.path,
        date: report.date,
        path: chart.path,
        href: `/${chart.path}`,
      });
    }
  }
  return items;
});

const selectedResource = computed(() => resources.value.find((item) => item.key === selectedKey.value) || null);

function selectResource(key) {
  selectedKey.value = key;
}

function eventCount(report) {
  return Number(report.profit_transfer_count || 0)
    + Number(report.loss_side_reduce_count || 0)
    + Number(report.position_recovery_count || 0);
}

watch(resources, (items) => {
  if (!items.find((item) => item.key === selectedKey.value)) {
    selectedKey.value = items[0]?.key || "";
  }
}, { immediate: true });

watch(selectedKey, async () => {
  const resource = selectedResource.value;
  markdownText.value = "";
  markdownError.value = "";
  markdownLoading.value = false;
  if (!resource || resource.type !== "markdown") return;

  markdownLoading.value = true;
  try {
    const response = await fetch(resource.href, { headers: { Accept: "text/markdown,text/plain,*/*" } });
    if (!response.ok) throw new Error(`读取失败（HTTP ${response.status}）`);
    markdownText.value = await response.text();
  } catch (error) {
    markdownError.value = error instanceof Error ? error.message : "读取 Markdown 失败。";
  } finally {
    markdownLoading.value = false;
  }
}, { immediate: true });
</script>
