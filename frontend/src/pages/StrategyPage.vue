<template>
  <StrategyCenterPage v-if="store.activeRoute !== 'strategy'" />
  <section v-else class="page active strategy-hub-page">
    <article class="panel data-overview-card strategy-overview-card">
      <div class="data-overview-head"><div><h2>策略中心</h2><p class="muted">自动调仓与提醒信号统一管理，点开策略查看图形和完整规则。</p></div><button class="button ghost small" :disabled="store.strategyCatalogBusy || store.signalDeskBusy" @click="refresh">{{ store.strategyCatalogBusy || store.signalDeskBusy ? "刷新中…" : "刷新策略" }}</button></div>
      <div class="data-overview-metrics strategy-overview-metrics"><div><span>全部策略</span><strong>{{ strategyCards.length }}</strong><small>套已配置规则</small></div><div><span>当前启用</span><strong>{{ enabledCount }}</strong><small>运行或提醒中</small></div><div><span>今日信号</span><strong>{{ todaySignals }}</strong><small>个已记录机会</small></div><div><span>策略类型</span><strong>自动 / 信号</strong><small>统一目录</small></div></div>
    </article>

    <div v-if="store.strategyCatalogError" class="service-alert">{{ store.strategyCatalogError }} <button class="button ghost small" @click="refresh">重试</button></div>
    <div class="strategy-card-list">
      <article v-for="item in strategyCards" :key="item.slug" class="panel strategy-directory-card">
        <div class="strategy-card-title">
          <div><span class="eyebrow">{{ item.kind }}</span><h3>{{ item.name }}</h3></div>
          <StatusBadge :text="item.status" :color="item.color" />
        </div>
        <p>{{ item.summary }}</p>
        <dl class="strategy-card-rules">
          <dt>核心指标</dt><dd>{{ item.indicators }}</dd>
          <dt>当前参数</dt><dd>{{ item.parameters }}</dd>
        </dl>
        <div class="strategy-card-stats">
          <span><small>今天</small><b>{{ item.today }}</b></span>
          <span><small>当前持有</small><b>{{ item.holdings }}</b></span>
          <span><small>动作方式</small><b>{{ item.action }}</b></span>
        </div>
        <button class="button" @click="setActivePage(`strategy/${item.slug}`)">查看图形与完整规则</button>
      </article>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, watch } from "vue";
import StatusBadge from "../components/StatusBadge.vue";
import StrategyCenterPage from "./StrategyCenterPage.vue";
import { isAuthenticated, loadSignalDesk, loadStrategyCatalog, setActivePage, store } from "../stores/appStore.js";

const signalItems = computed(() => store.signalDesk?.items || store.signalDesk?.signals || []);
const trendWeights = computed(() => store.state?.trend_forward?.runner?.weights || {});
const todaySignals = computed(() => signalItems.value.length);
const signalCount = (pattern) => signalItems.value.filter((row) => pattern.test(String(row.family || row.type || row.strategy || row.name || ""))).length;
const activeTrend = computed(() => Object.values(trendWeights.value).filter((value) => Math.abs(Number(value)) > 1e-9).length);
const serviceEnabled = computed(() => Boolean(store.signalDesk?.service?.enabled ?? store.signalDesk?.service_enabled));
const signalParameters = computed(() => store.signalDesk?.operations?.parameters || {});
const signalParameterSummary = computed(() => {
  const params = signalParameters.value;
  const parts = [];
  if (params.signal_interval) parts.push(`${params.signal_interval} K 线`);
  if (params.candidate_limit) parts.push(`每日最多 ${params.candidate_limit} 个候选`);
  if (params.liquidity_threshold_usdt) parts.push(`成交额门槛 ${(Number(params.liquidity_threshold_usdt) / 1000000).toFixed(0)}M USDT`);
  return parts.length ? parts.join(" · ") : "登录后读取当前配置";
});

const strategyCards = computed(() => [
  { slug: "trend", name: "多周期趋势", kind: "自动策略", summary: "让多个时间尺度共同判断涨跌，并让波动较小的市场承担更多仓位。", indicators: "趋势投票 · 近期波动 · 组合风险", parameters: "观察 14 / 28 / 56 / 84 / 168 天 · 每 7 天调仓 · 目标波动 10%", status: store.state?.trend_forward?.status === "NOT_STARTED" ? "尚未启动" : "运行中", color: store.state?.trend_forward?.status === "NOT_STARTED" ? "orange" : "green", today: "每周调仓", holdings: `${activeTrend.value} 个市场`, action: "自动调仓" },
  { slug: "breakout", name: "放量突破", kind: "信号策略", summary: "寻找成交突然活跃、价格冲出近期区间的机会。", indicators: "通道高点 · 成交量比 · 趋势强度 · 真实波幅", parameters: signalParameterSummary.value, status: serviceEnabled.value ? "提醒已启用" : "提醒未启用", color: serviceEnabled.value ? "green" : "orange", today: `${signalCount(/break|突破/i)} 个`, holdings: "手动决定", action: "发出提醒" },
  { slug: "oversold", name: "快速超跌", kind: "信号策略", summary: "寻找短时间急跌后可能出现修复的机会，同时避开仍在加速下跌的市场。", indicators: "短期跌幅 · 真实波幅 · 成交量比 · 长周期方向", parameters: signalParameterSummary.value, status: serviceEnabled.value ? "提醒已启用" : "提醒未启用", color: serviceEnabled.value ? "green" : "orange", today: `${signalCount(/oversold|超跌/i)} 个`, holdings: "手动决定", action: "发出提醒" },
  { slug: "strength", name: "持续强势", kind: "信号策略", summary: "寻找价格保持强势、成交持续配合且大方向没有转弱的市场。", indicators: "趋势强度 · 长周期均线 · 成交量比 · 相对强弱", parameters: signalParameterSummary.value, status: serviceEnabled.value ? "提醒已启用" : "提醒未启用", color: serviceEnabled.value ? "green" : "orange", today: `${signalCount(/strong|强势/i)} 个`, holdings: "手动决定", action: "发出提醒" },
]);
const enabledCount = computed(() => strategyCards.value.filter((item) => /运行中|已启用/.test(item.status)).length);
function refresh() { loadStrategyCatalog(); loadSignalDesk(); }
onMounted(() => { if (isAuthenticated.value) refresh(); });
watch(isAuthenticated, (value) => { if (value) refresh(); });
</script>
