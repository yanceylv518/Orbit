<template>
  <section class="page active strategy-detail-page">
    <div class="page-toolbar quant-toolbar">
      <div>
        <button class="text-link back-link" @click="setActivePage('strategy')">← 返回策略与研究</button>
        <span class="eyebrow">正式策略</span>
        <h2>{{ strategy?.name || "TB4 趋势篮子" }}</h2>
        <p>{{ strategy?.summary || "正在读取正式策略说明…" }}</p>
      </div>
      <StatusBadge v-if="strategy" :text="phaseText(strategy.lifecycle.primary)" :color="phaseColor(strategy.lifecycle.primary)" />
    </div>

    <div v-if="store.strategyCatalogError" class="service-alert">{{ store.strategyCatalogError }} <button class="button ghost small" @click="loadStrategyCatalog">重试</button></div>
    <div v-else-if="!strategy" class="panel empty-state">{{ store.strategyCatalogBusy ? "正在读取正式策略…" : "当前没有可展示的正式策略。" }}</div>

    <template v-else>
      <div class="review-answer-strip strategy-status-strip">
        <div><span>交易什么</span><strong>{{ strategy.spec.symbols.length }} 个永续合约</strong></div>
        <div><span>依据什么</span><strong>趋势强弱与波动风险</strong></div>
        <div><span>多久调整</span><strong>每 {{ strategy.display.rebalance_days }} 天</strong></div>
        <div><span>现在在哪一步</span><strong>{{ phaseText(strategy.lifecycle.primary) }}</strong></div>
      </div>

      <article class="panel strategy-process-panel">
        <div class="panel-head"><div><h3>这套策略是怎样工作的？</h3><p class="muted">按真实决策顺序解释，不用内部编号和文件校验码。</p></div></div>
        <ol class="strategy-five-answers">
          <li>
            <span>第一步</span><div><h4>观察市场</h4><p>使用 Binance 永续合约的历史价格与资金费率；15 分钟数据统一生成 1 小时和 4 小时序列。</p></div>
          </li>
          <li>
            <span>第二步</span><div><h4>判断方向</h4><p>比较不同时间长度的价格趋势，决定每个市场偏多、偏空或不持仓。</p></div>
          </li>
          <li>
            <span>第三步</span><div><h4>控制每个市场的分量</h4><p>波动大的市场分配更小仓位，避免某个市场独自决定组合结果。</p></div>
          </li>
          <li>
            <span>第四步</span><div><h4>形成组合并定期调整</h4><p>组合目标波动程度为 {{ strategy.display.target_portfolio_vol_pct }}%，仓位总价值不超过资金的 {{ strategy.display.gross_cap_pct }}%，每 {{ strategy.display.rebalance_days }} 天统一调整。</p></div>
          </li>
          <li>
            <span>第五步</span><div><h4>先模拟观察，再受控实盘</h4><p>冻结规则先在未来行情中持续计分；进入小资金实盘后仍与模拟基准并行，并接受持仓核对和强制停止保护。</p></div>
          </li>
        </ol>
      </article>

      <div class="strategy-center-grid">
        <article class="panel">
          <div class="panel-head"><div><h3>已经固定的关键规则</h3><p class="muted">运行中不能随意修改，修改必须重新研究和评审。</p></div></div>
          <dl class="facts strategy-facts">
            <dt>决策使用的 K 线</dt><dd>{{ strategy.display.interval_hours }} 小时</dd>
            <dt>观察趋势的时间</dt><dd>{{ strategy.display.momentum_lookback_days.join(" / ") }} 天</dd>
            <dt>估计波动的时间</dt><dd>{{ strategy.display.volatility_lookback_days }} 天</dd>
            <dt>每次买卖的成本假设</dt><dd>{{ strategy.spec.roundtrip_cost_pct }}%</dd>
            <dt>永续合约资金费</dt><dd>使用实际历史资金费率</dd>
          </dl>
        </article>
        <article class="panel">
          <div class="panel-head"><h3>需要始终记住的风险</h3></div>
          <ul class="risk-list"><li v-for="risk in strategy.known_risks" :key="risk">{{ humanText(risk) }}</li></ul>
          <p class="muted">历史验证只能说明规则过去如何表现，不能保证未来盈利。</p>
        </article>
      </div>

      <article class="panel strategy-links">
        <div><h3>接下来做什么？</h3><p class="muted">查看研究证据，或进入量化实例观察真实运行。</p></div>
        <div class="action-row">
          <button class="button ghost" @click="setActivePage('strategy/research')">查看研究</button>
          <button class="button" @click="setActivePage('forward')">查看量化运行</button>
        </div>
      </article>
    </template>
  </section>
</template>

<script setup>
import { computed, onMounted, watch } from "vue";
import StatusBadge from "../components/StatusBadge.vue";
import { enumLabel } from "../domain/labels.js";
import { isAuthenticated, loadStrategyCatalog, setActivePage, store } from "../stores/appStore.js";
const strategy = computed(() => store.selectedStrategy);
function phaseText(value) { return enumLabel(value); }
function phaseColor(value) { return value === "LIVE_PILOT" ? "orange" : (value === "PAPER_FORWARD" ? "blue" : "green"); }
function humanText(value) { return String(value || "").replace(/\bpaper\b/gi, "模拟盘").replace(/\blive\b/gi, "实盘").replace(/\bFunding\b/g, "资金费率"); }
onMounted(() => { if (isAuthenticated.value) loadStrategyCatalog(); });
watch(isAuthenticated, (value) => { if (value) loadStrategyCatalog(); });
</script>
