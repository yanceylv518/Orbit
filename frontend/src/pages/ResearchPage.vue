<template>
  <section class="page active research-page">
    <div class="page-toolbar">
      <div>
        <h2>研究档案</h2>
        <p>所有结论均对照冻结时的参数、成本与判定门槛。</p>
      </div>
      <button class="button ghost" :disabled="store.researchBusy" @click="loadResearchCatalog">
        {{ store.researchBusy ? "读取中..." : "刷新档案" }}
      </button>
    </div>

    <div v-if="store.researchError" class="service-alert">{{ store.researchError }}</div>

    <div class="summary-grid research-summary">
      <div class="summary-item">
        <span>缓存数据集</span>
        <strong>{{ store.researchDatasets.length }}</strong>
        <small>{{ totalRows.toLocaleString("zh-CN") }} 行记录</small>
      </div>
      <div class="summary-item">
        <span>冻结候选</span>
        <strong>{{ store.researchCandidates.length }}</strong>
        <small>登记后不可修改</small>
      </div>
      <div class="summary-item">
        <span>保留结论</span>
        <strong class="negative">{{ failedCandidates }}</strong>
        <small>NO-GO / FAIL</small>
      </div>
      <div class="summary-item">
        <span>可用报告</span>
        <strong>{{ availableResults }}</strong>
        <small>本地结构化结果</small>
      </div>
    </div>

    <article class="panel research-dataset-panel">
      <div class="panel-head research-panel-head">
        <div>
          <h3>数据目录</h3>
          <p class="muted">{{ filteredDatasets.length }} / {{ store.researchDatasets.length }} 个缓存文件</p>
        </div>
        <div class="research-filters">
          <input v-model.trim="datasetQuery" type="search" placeholder="筛选市场或文件" aria-label="筛选数据集" />
          <div class="research-segments" aria-label="数据类型">
            <button
              v-for="option in datasetKinds"
              :key="option.value"
              class="tab"
              :class="{ active: datasetKind === option.value }"
              @click="datasetKind = option.value"
            >
              {{ option.label }}
            </button>
          </div>
        </div>
      </div>
      <div class="table-wrap research-data-table">
        <table>
          <thead><tr><th>数据集</th><th>市场</th><th>类型</th><th>周期</th><th>记录数</th><th>数据区间</th><th>SHA-256</th></tr></thead>
          <tbody>
            <tr v-for="dataset in filteredDatasets" :key="dataset.id">
              <td><strong>{{ dataset.id }}</strong><div class="muted">{{ dataset.relative_path }}</div></td>
              <td>{{ dataset.market || "-" }}</td>
              <td><StatusBadge :text="kindLabel(dataset.kind)" :color="kindColor(dataset.kind)" /></td>
              <td class="mono">{{ dataset.interval || "-" }}</td>
              <td class="mono">{{ Number(dataset.rows || 0).toLocaleString("zh-CN") }}</td>
              <td class="mono research-date-range">
                <span>{{ dateValue(dataset.start_time_ms) }}</span>
                <span>{{ dateValue(dataset.end_time_ms) }}</span>
              </td>
              <td><span class="mono research-hash" :title="dataset.sha256">{{ shortHash(dataset.sha256) }}</span></td>
            </tr>
            <tr v-if="!filteredDatasets.length"><td colspan="7" class="muted">没有符合当前筛选条件的数据集。</td></tr>
          </tbody>
        </table>
      </div>
    </article>

    <div class="research-workspace">
      <article class="panel research-history-panel">
        <div class="panel-head">
          <div>
            <h3>候选履历</h3>
            <p class="muted">已检验假设永久留档</p>
          </div>
          <span class="pill">{{ store.researchCandidates.length }} 项</span>
        </div>
        <div class="candidate-history">
          <button
            v-for="candidate in store.researchCandidates"
            :key="candidate.id"
            class="candidate-row"
            :class="{ active: candidate.id === store.researchCandidate?.id }"
            @click="selectResearchCandidate(candidate.id)"
          >
            <span class="candidate-id mono">{{ candidate.id }}</span>
            <span class="candidate-copy">
              <strong>{{ candidate.name }}</strong>
              <small>冻结于 {{ dateTime(candidate.frozen_at) }}</small>
            </span>
            <StatusBadge :text="verdictLabel(candidate.verdict)" :color="verdictColor(candidate.verdict)" />
          </button>
          <p v-if="!store.researchCandidates.length && !store.researchBusy" class="muted">暂无冻结候选。</p>
        </div>
      </article>

      <article class="panel research-detail-panel">
        <template v-if="candidate">
          <div class="research-candidate-head">
            <div>
              <div class="research-title-line">
                <span class="candidate-id large mono">{{ candidate.id }}</span>
                <h3>{{ candidate.name }}</h3>
                <StatusBadge :text="verdictLabel(candidate.verdict)" :color="verdictColor(candidate.verdict)" />
              </div>
              <p>{{ candidate.signal_definition }}</p>
            </div>
            <div class="research-freeze-state">
              <span>冻结指纹</span>
              <strong class="mono" :title="candidate.frozen_hash">{{ shortHash(candidate.frozen_hash) }}</strong>
            </div>
          </div>

          <div class="research-audit-strip">
            <div><span>冻结时间</span><strong>{{ dateTime(candidate.frozen_at) }}</strong></div>
            <div><span>登记状态</span><strong>{{ candidate.status }}</strong></div>
            <div><span>锁箱开箱</span><strong>{{ candidate.lockbox_opened_at ? dateTime(candidate.lockbox_opened_at) : "未开箱" }}</strong></div>
            <div><span>最终判定</span><strong :class="verdictClass(candidate.verdict)">{{ candidate.verdict }}</strong></div>
          </div>

          <div class="research-definition-grid">
            <section>
              <h4>预注册参数</h4>
              <dl class="research-kv">
                <template v-for="entry in entries(candidate.parameters)" :key="entry[0]">
                  <dt>{{ fieldLabel(entry[0]) }}</dt><dd>{{ definitionValue(entry[1]) }}</dd>
                </template>
              </dl>
            </section>
            <section>
              <h4>成本假设</h4>
              <dl class="research-kv">
                <template v-for="entry in entries(candidate.costs)" :key="entry[0]">
                  <dt>{{ fieldLabel(entry[0]) }}</dt><dd>{{ definitionValue(entry[1]) }}</dd>
                </template>
              </dl>
            </section>
            <section>
              <h4>测试矩阵</h4>
              <dl class="research-kv">
                <template v-for="entry in entries(candidate.matrix)" :key="entry[0]">
                  <dt>{{ fieldLabel(entry[0]) }}</dt><dd>{{ definitionValue(entry[1]) }}</dd>
                </template>
              </dl>
            </section>
            <section class="research-bars">
              <h4>固定判定门槛</h4>
              <div v-for="entry in entries(candidate.thresholds)" :key="entry[0]" class="fixed-bar-row">
                <span>{{ fieldLabel(entry[0]) }}</span>
                <strong>{{ definitionValue(entry[1]) }}</strong>
              </div>
            </section>
          </div>

          <div class="research-result-head">
            <div>
              <h4>结果证据</h4>
              <p class="muted">逐市场或逐配置对照冻结门槛</p>
            </div>
            <div class="research-segments">
              <button
                v-for="item in candidate.results || []"
                :key="item.id"
                class="tab"
                :class="{ active: item.id === store.researchResult?.id }"
                :disabled="!item.available || store.researchResultBusy"
                @click="selectResearchResult(item.id)"
              >
                {{ resultLabel(item.id) }}
              </button>
            </div>
          </div>

          <div v-if="store.researchResultBusy" class="research-loading muted">正在读取冻结结果...</div>
          <template v-else-if="result">
            <div class="research-result-meta">
              <span>{{ result.protocol || candidate.id }}</span>
              <span class="mono" :title="result.sha256">SHA {{ shortHash(result.sha256) }}</span>
              <span>{{ result.relative_path }}</span>
            </div>
            <div class="table-wrap research-evidence-table">
              <table>
                <thead><tr><th>市场 / 配置</th><th>测试窗口</th><th>样本</th><th>成本后结果</th><th>置信下界</th><th>门槛判定</th></tr></thead>
                <tbody>
                  <tr v-for="row in evidenceRows" :key="row.key">
                    <td><strong>{{ row.scope }}</strong></td>
                    <td class="mono">{{ row.test }}</td>
                    <td class="mono">{{ integerValue(row.samples) }}</td>
                    <td class="mono" :class="numberClass(row.net)">{{ percentValue(row.net) }}</td>
                    <td class="mono" :class="numberClass(row.lower)">{{ percentValue(row.lower) }}</td>
                    <td><StatusBadge :text="row.admitted ? 'PASS' : 'FAIL'" :color="row.admitted ? 'green' : 'red'" /></td>
                  </tr>
                  <tr v-if="!evidenceRows.length"><td colspan="6" class="muted">该历史报告没有可归一化的逐项证据，最终 verdict 仍以冻结登记为准。</td></tr>
                </tbody>
              </table>
            </div>
          </template>
          <div v-else class="research-loading muted">该候选没有可用的本地结果文件。</div>
        </template>
        <div v-else class="research-loading muted">请选择候选查看冻结定义与结果。</div>
      </article>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from "vue";
import StatusBadge from "../components/StatusBadge.vue";
import {
  loadResearchCatalog,
  selectResearchCandidate,
  selectResearchResult,
  store,
} from "../stores/appStore.js";

const datasetQuery = ref("");
const datasetKind = ref("all");
const datasetKinds = [
  { value: "all", label: "全部" },
  { value: "ohlc", label: "K 线" },
  { value: "funding", label: "Funding" },
  { value: "series", label: "序列" },
];

const candidate = computed(() => store.researchCandidate);
const result = computed(() => store.researchResult);
const totalRows = computed(() => store.researchDatasets.reduce((sum, item) => sum + Number(item.rows || 0), 0));
const failedCandidates = computed(() => store.researchCandidates.filter((item) => !isPass(item.verdict)).length);
const availableResults = computed(() => store.researchCandidates.reduce(
  (sum, item) => sum + (item.results || []).filter((entry) => entry.available).length,
  0,
));
const filteredDatasets = computed(() => {
  const query = datasetQuery.value.toLowerCase();
  return store.researchDatasets.filter((item) => {
    const kindMatches = datasetKind.value === "all" || item.kind === datasetKind.value;
    const queryMatches = !query || `${item.id} ${item.market || ""} ${item.interval || ""}`.toLowerCase().includes(query);
    return kindMatches && queryMatches;
  });
});
const evidenceRows = computed(() => normalizeEvidence(result.value?.report || {}));

function normalizeEvidence(report) {
  if (Array.isArray(report.reports)) {
    return report.reports.map((row, index) => evidenceRow(row.market || `记录 ${index + 1}`, row, index));
  }
  if (Array.isArray(report.markets)) {
    return report.markets.flatMap((market) => Object.entries(market.reports || {}).map(([window, row], index) => (
      evidenceRow(market.name || "-", row, `${market.name}:${window}:${index}`, `${window} settlements`)
    )));
  }
  if (Array.isArray(report.best_diagnostic_config?.markets)) {
    const config = report.best_diagnostic_config;
    return config.markets.map((row, index) => evidenceRow(
      row.name || `市场 ${index + 1}`,
      row,
      `${config.id}:${row.name || index}`,
      config.id,
    ));
  }
  if (Array.isArray(report.configurations)) {
    return report.configurations.map((row, index) => evidenceRow(row.id || `配置 ${index + 1}`, row, index));
  }
  return [];
}

function evidenceRow(scope, row, key, test = "") {
  const net = firstNumber(row, [
    "mean_net_return_pct",
    "mean_net_carry_pct",
    "net_return_pct",
    "expected_value_pct",
    "mean_gross_return_pct",
  ]);
  const lower = firstNumber(row, ["bootstrap_mean_ci_low", "expected_value_ci_low"]);
  const explicit = row.admitted ?? row.stage_admitted ?? row.coverage_admitted;
  return {
    key: String(key),
    scope,
    test: test || testLabel(row),
    samples: firstNumber(row, ["events", "trades", "common_slots", "signals", "candidate_count"]),
    net,
    lower,
    admitted: explicit === undefined ? Number(net) > 0 : Boolean(explicit),
  };
}

function firstNumber(value, keys) {
  for (const key of keys) {
    if (value[key] !== undefined && value[key] !== null) return Number(value[key]);
  }
  return null;
}

function testLabel(row) {
  const parts = [];
  if (row.a_pct !== undefined) parts.push(`a=${row.a_pct}%`);
  if (row.lookback_settlements !== undefined) parts.push(`LB=${row.lookback_settlements}`);
  if (row.extreme_quantile !== undefined) parts.push(`q=${row.extreme_quantile}`);
  if (row.holding_ticks !== undefined) parts.push(`H=${row.holding_ticks} ticks`);
  if (row.holding_settlements !== undefined) parts.push(`H=${row.holding_settlements}`);
  if (row.window_settlements !== undefined) parts.push(`${row.window_settlements} settlements`);
  return parts.join(" · ") || "固定配置";
}

function entries(value) {
  return Object.entries(value || {});
}

function definitionValue(value) {
  if (Array.isArray(value)) return value.join(" / ");
  if (typeof value === "boolean") return value ? "是" : "否";
  if (value && typeof value === "object") return Object.entries(value).map(([key, item]) => `${key}: ${item}`).join(" · ");
  return value ?? "-";
}

function fieldLabel(value) {
  const labels = {
    a_pct: "锚点偏离",
    theta_pct: "趋势阈值",
    holding_ticks: "持有 ticks",
    holding_settlements: "持有结算期",
    lookback_settlements: "回看结算期",
    extreme_quantile: "极端分位",
    roundtrip_pct: "完整往返成本",
    entry_exit_pct: "进出成本",
    rebalance_pct_per_day: "每日再平衡成本",
    markets: "市场",
    intervals: "周期",
    horizons: "预测窗口数",
    configuration_count: "配置数量",
    required_markets: "最低通过市场数",
    required_positive_combinations: "最低正收益组合数",
    net_return_positive: "成本后收益为正",
    positive_expected_value: "期望收益为正",
    bootstrap_lower_bound_positive: "Bootstrap 下界为正",
    min_market_appearances: "最低市场出现次数",
  };
  return labels[value] || value.replaceAll("_", " ");
}

function kindLabel(value) {
  return { ohlc: "K 线", funding: "Funding", series: "序列" }[value] || value || "未知";
}

function kindColor(value) {
  return { ohlc: "blue", funding: "orange", series: "green" }[value] || "blue";
}

function isPass(value) {
  return ["GO", "PASS", "LOCKBOX_PASS"].includes(String(value || "").toUpperCase());
}

function verdictLabel(value) {
  return isPass(value) ? "PASS" : "FAIL";
}

function verdictColor(value) {
  return isPass(value) ? "green" : "red";
}

function verdictClass(value) {
  return isPass(value) ? "positive" : "negative";
}

function shortHash(value) {
  if (!value) return "-";
  return `${value.slice(0, 10)}…${value.slice(-6)}`;
}

function dateValue(value) {
  if (!value) return "-";
  return new Date(Number(value)).toLocaleDateString("zh-CN");
}

function dateTime(value) {
  if (!value) return "-";
  return new Date(value).toLocaleString("zh-CN", { hour12: false });
}

function resultLabel(value) {
  return value.replace(candidate.value?.id?.toLowerCase() || "", "").replaceAll("_", " ").trim() || value;
}

function percentValue(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  return `${Number(value).toLocaleString("zh-CN", { minimumFractionDigits: 3, maximumFractionDigits: 3 })}%`;
}

function integerValue(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  return Number(value).toLocaleString("zh-CN");
}

function numberClass(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "";
  return Number(value) >= 0 ? "positive" : "negative";
}

onMounted(loadResearchCatalog);
</script>
