<template>
  <ResearchPage v-if="store.activeRoute === 'strategy/research'" mode="research" />
  <StrategyCenterPage v-else-if="store.activeRoute === 'strategy/tb4'" />
  <section v-else class="page active strategy-hub-page">
    <div class="strategy-hub-answer">
      <div>
        <span class="eyebrow">策略与研究</span>
        <h2>先证明关系，再冻结规则，最后交给量化实例运行。</h2>
        <p>这里把“我们相信什么、证据到哪一步、哪些规则已经正式使用”放在同一条业务线上。</p>
      </div>
    </div>

    <div class="review-answer-strip strategy-status-strip">
      <div><span>正式策略</span><strong>{{ strategies.length ? `${strategies.length} 套` : "尚未读取" }}</strong></div>
      <div><span>当前研究主题</span><strong>量价关系</strong></div>
      <div><span>正式运行实例</span><strong>{{ runtimeCount }} 个</strong></div>
      <div><span>研究原则</span><strong>先验证，后组合</strong></div>
    </div>

    <div class="strategy-hub-grid">
      <article class="panel strategy-hub-card">
        <div>
          <span class="eyebrow">正式策略</span>
          <h3>TB4 趋势篮子</h3>
          <p>规则已经冻结，持续运行模拟观察，并可在严格保护下进行小资金实盘。</p>
        </div>
        <dl class="facts">
          <dt>交易市场</dt><dd>Binance USDT 永续合约</dd>
          <dt>基础数据</dt><dd>15 分钟 K 线，统一聚合为 1 小时和 4 小时</dd>
          <dt>调整频率</dt><dd>{{ selectedStrategy?.display?.rebalance_days ? `每 ${selectedStrategy.display.rebalance_days} 天` : "每周" }}</dd>
          <dt>当前阶段</dt><dd>{{ lifecycleText }}</dd>
        </dl>
        <button class="button" @click="setActivePage('strategy/tb4')">查看策略为什么这样做</button>
      </article>

      <article class="panel strategy-hub-card">
        <div>
          <span class="eyebrow">研究中的问题</span>
          <h3>量价关系真的存在吗？</h3>
          <p>暂不拼入场信号，先检验成交量与未来价格变化的关系是否稳定、可重复、跨市场成立。</p>
        </div>
        <ol class="mini-process">
          <li>先写清楚假设和判断门槛</li>
          <li>使用统一历史数据运行实验</li>
          <li>区分“程序跑完”和“关系成立”</li>
        </ol>
        <button class="button ghost" @click="setActivePage('strategy/research')">进入量价关系研究</button>
      </article>
    </div>

    <article class="panel strategy-lifecycle-card">
      <div class="panel-head"><div><h3>一个想法怎样变成可运行的量化策略？</h3><p class="muted">所有策略都遵循同一条路径，研究结果不会直接触发交易。</p></div></div>
      <ol class="five-step-flow">
        <li><span>1</span><b>提出问题</b><small>说明想验证的市场关系</small></li>
        <li><span>2</span><b>预先登记</b><small>实验前写死数据、方法和门槛</small></li>
        <li><span>3</span><b>验证证据</b><small>检验稳定性、成本和市场差异</small></li>
        <li><span>4</span><b>冻结策略</b><small>通过评审后形成不可随意改动的规则</small></li>
        <li><span>5</span><b>运行与复盘</b><small>模拟观察、小资金实盘、持续核对</small></li>
      </ol>
    </article>
  </section>
</template>

<script setup>
import { computed, onMounted, watch } from "vue";
import ResearchPage from "./ResearchPage.vue";
import StrategyCenterPage from "./StrategyCenterPage.vue";
import { enumLabel } from "../domain/labels.js";
import { isAuthenticated, loadStrategyCatalog, setActivePage, store } from "../stores/appStore.js";

const strategies = computed(() => store.strategies || []);
const selectedStrategy = computed(() => store.selectedStrategy);
const runtimeCount = computed(() => store.state?.trend_forward?.status && store.state.trend_forward.status !== "NOT_STARTED" ? 2 : 0);
const lifecycleText = computed(() => enumLabel(selectedStrategy.value?.lifecycle?.primary || "PAPER_FORWARD"));
onMounted(() => { if (isAuthenticated.value) loadStrategyCatalog(); });
watch(isAuthenticated, (value) => { if (value) loadStrategyCatalog(); });
</script>
