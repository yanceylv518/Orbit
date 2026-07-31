<template>
  <section class="page active strategy-center-page">
    <div v-if="store.strategyCatalogError" class="service-alert">
      {{ store.strategyCatalogError }}
      <button class="button ghost small" @click="loadStrategyCatalog">重试</button>
    </div>

    <div v-if="!strategy" class="panel empty-state">
      {{ store.strategyCatalogBusy ? "正在读取冻结策略定义…" : "当前没有可展示的冻结策略。" }}
    </div>

    <template v-else>
      <article class="panel strategy-identity">
        <div class="panel-head">
          <div>
            <span class="eyebrow">FROZEN STRATEGY</span>
            <h3>{{ strategy.name }}</h3>
            <p>{{ strategy.summary }}</p>
          </div>
          <div class="lifecycle-badges" aria-label="策略运行阶段">
            <StatusBadge
              v-for="phase in strategy.lifecycle.phases"
              :key="phase"
              :text="phaseText(phase)"
              :color="phaseColor(phase)"
            />
          </div>
        </div>

        <div class="summary-grid compact">
          <SummaryItem label="策略 ID" :value="strategy.id" />
          <SummaryItem label="冻结版本" :value="`v${strategy.version}`" />
          <SummaryItem label="定义哈希" :value="shortHash(strategy.definition_hash)" :note="strategy.definition_hash" />
          <SummaryItem label="主要运行模式" :value="phaseText(strategy.lifecycle.primary)" />
        </div>

        <div v-if="strategy.lifecycle.primary === 'LIVE_PILOT'" class="parallel-phase-note">
          <strong>小资金实盘与纸面前向并行</strong>
          <span>
            实盘额度 {{ strategy.lifecycle.live_pilot.capital_usdt }} USDT；
            纸面前向 {{ paperProgressText }}。启动实盘不代表纸面前向已经毕业。
          </span>
        </div>
      </article>

      <div class="strategy-center-grid">
        <article class="panel">
          <div class="panel-head">
            <div>
              <h3>策略如何工作</h3>
              <p class="muted">这里描述规则本身，不用单笔涨跌事后评价买卖点。</p>
            </div>
          </div>
          <ol class="mechanics-list">
            <li v-for="item in strategy.mechanics" :key="item.title">
              <strong>{{ item.title }}</strong>
              <span>{{ item.body }}</span>
            </li>
          </ol>
        </article>

        <article class="panel">
          <div class="panel-head">
            <div>
              <h3>冻结参数</h3>
              <p class="muted">由后端冻结 runner 直接提供，页面没有另一套参数副本。</p>
            </div>
            <span class="mono muted">spec {{ shortHash(strategy.spec_sha256) }}</span>
          </div>
          <dl class="facts strategy-facts">
            <dt>K 线周期</dt><dd>{{ strategy.display.interval_hours }} 小时</dd>
            <dt>动量周期</dt><dd>{{ strategy.display.momentum_lookback_days.join(" / ") }} 天</dd>
            <dt>波动率周期</dt><dd>{{ strategy.display.volatility_lookback_days }} 天</dd>
            <dt>再平衡周期</dt><dd>{{ strategy.display.rebalance_days }} 天</dd>
            <dt>目标组合波动</dt><dd>{{ strategy.display.target_portfolio_vol_pct }}%</dd>
            <dt>总敞口上限</dt><dd>{{ strategy.display.gross_cap_pct }}%</dd>
            <dt>回测往返成本</dt><dd>{{ strategy.spec.roundtrip_cost_pct }}%</dd>
          </dl>
          <div class="symbol-chip-list" aria-label="交易市场">
            <span v-for="symbol in strategy.spec.symbols" :key="symbol">{{ symbol }}</span>
          </div>
        </article>
      </div>

      <div class="strategy-center-grid">
        <article class="panel">
          <div class="panel-head"><h3>已知风险</h3></div>
          <ul class="risk-list">
            <li v-for="risk in strategy.known_risks" :key="risk">{{ risk }}</li>
          </ul>
        </article>

        <article class="panel evidence-placeholder">
          <div>
            <span class="eyebrow">EVIDENCE</span>
            <h3>结构化回测证据尚未接入</h3>
            <p>{{ strategy.evidence.message }}</p>
          </div>
          <button class="button ghost" @click="setActivePage('research')">查看研究候选档案</button>
        </article>
      </div>

      <article class="panel strategy-links">
        <div>
          <h3>下一步看哪里</h3>
          <p class="muted">正式策略解释“规则是什么”；研究候选、实盘、复盘与账户分别承接后续生命周期。</p>
        </div>
        <div class="action-row">
          <button class="button" @click="setActivePage('forward')">进入实盘</button>
          <button class="button ghost" @click="setActivePage('research')">查看研究候选</button>
          <button class="button ghost" @click="setActivePage('accounts')">进入账户</button>
          <button class="button ghost" @click="setActivePage('risk')">查看风控</button>
        </div>
      </article>
    </template>
  </section>
</template>

<script setup>
import { computed, onMounted, watch } from "vue";
import StatusBadge from "../components/StatusBadge.vue";
import SummaryItem from "../components/SummaryItem.vue";
import {
  loadStrategyCatalog,
  isAuthenticated,
  setActivePage,
  store,
} from "../stores/appStore.js";

const strategy = computed(() => store.selectedStrategy);
const paperProgressText = computed(() => {
  const paper = strategy.value?.lifecycle?.paper_forward || {};
  if (paper.status === "NOT_STARTED") return "尚未启动";
  if (paper.elapsed_days == null) return paper.status || "状态未知";
  return `已运行 ${paper.elapsed_days} / ${paper.minimum_forward_days ?? "-"} 天`;
});

function phaseText(value) {
  return ({
    BACKTEST_CONFIRMED: "历史回测确认",
    PAPER_FORWARD: "纸面前向",
    LIVE_PILOT: "小资金实盘",
  })[value] || value;
}

function phaseColor(value) {
  return value === "LIVE_PILOT" ? "orange" : (value === "PAPER_FORWARD" ? "blue" : "green");
}

function shortHash(value) {
  return value ? `${value.slice(0, 10)}…` : "-";
}

onMounted(() => {
  if (isAuthenticated.value) loadStrategyCatalog();
});
watch(isAuthenticated, (authenticated) => {
  if (authenticated) loadStrategyCatalog();
});
</script>
