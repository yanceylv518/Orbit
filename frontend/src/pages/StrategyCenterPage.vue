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
            <span class="eyebrow">已冻结的正式策略</span>
            <h3>{{ strategy.name }}</h3>
            <p>{{ strategy.summary }}</p>
          </div>
          <div class="lifecycle-badges" aria-label="策略运行阶段">
            <StatusBadge
              v-for="phase in strategy.lifecycle.phases"
              :key="phase"
              :text="phaseText(phase)"
              :raw="phase"
              :color="phaseColor(phase)"
            />
          </div>
        </div>

        <div class="summary-grid compact">
          <SummaryItem label="策略 ID" :value="strategy.id" />
          <SummaryItem label="冻结版本" :value="`v${strategy.version}`" />
          <SummaryItem label="策略内容指纹" help="哈希指纹" :value="shortHash(strategy.definition_hash)" :note="strategy.definition_hash" />
          <SummaryItem label="主要运行模式" :value="phaseText(strategy.lifecycle.primary)" />
        </div>

        <div v-if="strategy.lifecycle.primary === 'LIVE_PILOT'" class="parallel-phase-note">
          <strong>小资金实盘与模拟盘前向同时运行 <HelpTip term="纸面前向" /></strong>
          <span>
            实盘额度 {{ strategy.lifecycle.live_pilot.capital_usdt }} USDT；
            模拟盘前向 {{ paperProgressText }}。启动实盘不代表策略已经得到未来行情证明。
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
              <span>{{ humanText(item.body) }}</span>
            </li>
          </ol>
        </article>

        <article class="panel">
          <div class="panel-head">
            <div>
              <h3>已经写死、运行中不能改的规则</h3>
              <p class="muted">这些值直接来自后端正式策略；页面没有另一份可能不同步的副本。</p>
            </div>
            <span class="mono muted" :title="strategy.spec_sha256">规则指纹 <HelpTip term="哈希指纹" /> {{ shortHash(strategy.spec_sha256) }}</span>
          </div>
          <dl class="facts strategy-facts">
            <dt>K 线周期</dt><dd>{{ strategy.display.interval_hours }} 小时</dd>
            <dt>动量周期</dt><dd>{{ strategy.display.momentum_lookback_days.join(" / ") }} 天</dd>
            <dt>波动率周期</dt><dd>{{ strategy.display.volatility_lookback_days }} 天</dd>
            <dt>每隔多久重新调仓 <HelpTip term="再平衡" /></dt><dd>{{ strategy.display.rebalance_days }} 天</dd>
            <dt>目标波动程度</dt><dd>{{ strategy.display.target_portfolio_vol_pct }}%</dd>
            <dt>仓位总价值上限 <HelpTip term="名义金额" /></dt><dd>{{ strategy.display.gross_cap_pct }}%</dd>
            <dt>回测假设的买卖成本</dt><dd>{{ strategy.spec.roundtrip_cost_pct }}%</dd>
            <dt>永续合约资金费 <HelpTip term="Funding" /></dt><dd>使用实际历史资金费</dd>
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
            <li v-for="risk in strategy.known_risks" :key="risk">{{ humanText(risk) }}</li>
          </ul>
        </article>

        <article class="panel evidence-placeholder">
          <div>
            <span class="eyebrow">回测证据</span>
            <h3>回测成绩图表还没有接进页面</h3>
            <p>{{ humanText(strategy.evidence.message) }}</p>
            <p class="muted">
              常用评价指标：Calmar <HelpTip term="Calmar" /> · Sortino <HelpTip term="Sortino" />
            </p>
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
import HelpTip from "../components/HelpTip.vue";
import StatusBadge from "../components/StatusBadge.vue";
import SummaryItem from "../components/SummaryItem.vue";
import {
  loadStrategyCatalog,
  isAuthenticated,
  setActivePage,
  store,
} from "../stores/appStore.js";
import { enumLabel } from "../domain/labels.js";

const strategy = computed(() => store.selectedStrategy);
const paperProgressText = computed(() => {
  const paper = strategy.value?.lifecycle?.paper_forward || {};
  if (paper.status === "NOT_STARTED") return "尚未启动";
  if (paper.elapsed_days == null) return enumLabel(paper.status);
  return `已运行 ${paper.elapsed_days} / ${paper.minimum_forward_days ?? "-"} 天`;
});

function phaseText(value) {
  return enumLabel(value);
}

function phaseColor(value) {
  return value === "LIVE_PILOT" ? "orange" : (value === "PAPER_FORWARD" ? "blue" : "green");
}

function shortHash(value) {
  return value ? `${value.slice(0, 10)}…` : "-";
}

function humanText(value) {
  return String(value || "")
    .replace(/\bpaper\b/gi, "模拟盘")
    .replace(/\blive\b/gi, "实盘")
    .replace(/\bFunding\b/g, "资金费率")
    .replace(/结构化证据尚未接入（待 SC-1 bundle \+ SC-4）/g, "结构化回测图表尚未接入");
}

onMounted(() => {
  if (isAuthenticated.value) loadStrategyCatalog();
});
watch(isAuthenticated, (authenticated) => {
  if (authenticated) loadStrategyCatalog();
});
</script>
