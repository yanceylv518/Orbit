<template>
  <section class="page active research-page">
    <div class="page-toolbar">
      <div>
        <h2>研究档案</h2>
        <p>所有结论均对照冻结时的参数、成本与判定门槛。</p>
      </div>
      <div class="toolbar">
        <button class="button ghost" :disabled="store.researchBusy" @click="loadResearchCatalog">
          {{ store.researchBusy ? "读取中..." : "刷新档案" }}
        </button>
        <button class="button primary" @click="showCreate = !showCreate">
          {{ showCreate ? "收起预注册" : "新建预注册" }}
        </button>
      </div>
    </div>

    <div v-if="store.researchError" class="service-alert">{{ store.researchError }}</div>

    <article v-if="showCreate" class="panel research-create-panel">
      <div class="panel-head research-panel-head">
        <div>
          <h3>冻结新候选</h3>
          <p class="muted">提交后参数、成本、数据指纹与判定门槛永久不可修改。</p>
        </div>
        <StatusBadge text="预注册" color="blue" />
      </div>
      <div class="research-create-grid">
        <section class="research-create-fields">
          <label>
            <span>研究协议</span>
            <select v-model="draft.protocol" @change="applySuggestedDatasets">
              <option v-for="template in store.researchTemplates" :key="template.id" :value="template.id">
                {{ template.id }} · {{ template.name }}
              </option>
            </select>
          </label>
          <label>
            <span>候选 ID</span>
            <input v-model.trim="draft.id" maxlength="32" placeholder="例如 M0-20260714-A" />
          </label>
          <label>
            <span>候选名称</span>
            <input v-model.trim="draft.name" maxlength="120" :placeholder="selectedTemplate?.name || '候选名称'" />
          </label>
          <div v-if="selectedTemplate" class="research-template-preview">
            <p>{{ selectedTemplate.signal_definition }}</p>
            <dl class="research-kv">
              <template v-for="entry in entries(selectedTemplate.parameters)" :key="`p-${entry[0]}`">
                <dt>{{ fieldLabel(entry[0]) }}</dt><dd>{{ definitionValue(entry[1]) }}</dd>
              </template>
              <template v-for="entry in entries(selectedTemplate.costs)" :key="`c-${entry[0]}`">
                <dt>{{ fieldLabel(entry[0]) }}</dt><dd>{{ definitionValue(entry[1]) }}</dd>
              </template>
            </dl>
          </div>
        </section>
        <section class="research-dataset-picker">
          <div class="research-picker-head">
            <div><h4>冻结数据矩阵</h4><p class="muted">已选 {{ draft.datasetIds.length }} 个缓存文件</p></div>
            <button class="button ghost compact" type="button" @click="applySuggestedDatasets">推荐选择</button>
          </div>
          <div class="research-picker-list">
            <label v-for="dataset in compatibleDatasets" :key="dataset.id" class="research-picker-row">
              <input v-model="draft.datasetIds" type="checkbox" :value="dataset.id" />
              <span><strong>{{ dataset.id }}</strong><small>{{ dataset.market || "-" }} · {{ kindLabel(dataset.kind) }} · {{ dataset.interval || "-" }}</small></span>
              <code>{{ shortHash(dataset.sha256) }}</code>
            </label>
          </div>
        </section>
      </div>
      <div class="research-freeze-footer">
        <label class="research-confirm-check">
          <input v-model="draft.confirmed" type="checkbox" />
          <span>确认冻结后只能创建新候选，不能修改或覆盖本候选。</span>
        </label>
        <button class="button primary" :disabled="!canFreeze || store.researchWorkflowBusy" @click="freezeCandidate">
          {{ store.researchWorkflowBusy ? "冻结中..." : "冻结候选" }}
        </button>
      </div>
    </article>

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

    <article v-if="store.researchRuns.length" class="panel research-runs-panel">
      <div class="panel-head">
        <div><h3>评估任务</h3><p class="muted">单任务串行 · 状态与结果只追加</p></div>
        <span class="pill">{{ store.researchRuns.length }} 次</span>
      </div>
      <div class="research-run-list">
        <button v-for="run in store.researchRuns.slice(0, 8)" :key="run.id" class="research-run-row" :class="{ static: run.job_type === 'dataset_fetch' }" @click="openRunTarget(run)">
          <span class="candidate-id mono">{{ run.job_type === "dataset_fetch" ? "DATA" : run.candidate_id }}</span>
          <span class="research-run-copy"><strong>{{ runLabel(run) }}</strong><small>{{ dateTime(run.updated_at) }} · {{ run.id }}</small></span>
          <span class="research-progress"><i :style="{ width: `${run.progress || 0}%` }"></i></span>
          <StatusBadge :text="runStatusLabel(run)" :color="runStatusColor(run)" />
        </button>
      </div>
    </article>

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
          <button class="button ghost compact" @click="showFetch = !showFetch">{{ showFetch ? "收起拉取" : "拉取新数据" }}</button>
        </div>
      </div>
      <div v-if="showFetch" class="research-fetch-strip">
        <label><span>市场</span><input v-model.trim="fetchDraft.symbol" maxlength="20" placeholder="BTCUSDT" /></label>
        <label><span>数据类型</span><select v-model="fetchDraft.kind"><option value="ohlc">K 线</option><option value="funding">Funding</option></select></label>
        <label v-if="fetchDraft.kind === 'ohlc'"><span>周期</span><select v-model="fetchDraft.interval"><option v-for="interval in fetchIntervals" :key="interval" :value="interval">{{ interval }}</option></select></label>
        <label><span>天数</span><input v-model.number="fetchDraft.days" type="number" min="1" max="2000" /></label>
        <button class="button primary" :disabled="store.researchWorkflowBusy || hasActiveRun" @click="fetchDataset">开始拉取</button>
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
            <StatusBadge :text="verdictLabel(candidate.latest_verdict)" :color="verdictColor(candidate.latest_verdict)" />
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
                <StatusBadge :text="verdictLabel(candidate.latest_verdict)" :color="verdictColor(candidate.latest_verdict)" />
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
            <div><span>锁箱开箱</span><strong>{{ candidate.effective_lockbox_opened_at ? dateTime(candidate.effective_lockbox_opened_at) : "未开箱" }}</strong></div>
            <div><span>当前判定</span><strong :class="verdictClass(candidate.latest_verdict)">{{ candidate.latest_verdict }}</strong></div>
          </div>

          <div v-if="candidate.status === 'frozen'" class="research-run-control">
            <div>
              <h4>运行冻结评估</h4>
              <p>只读取冻结时登记的缓存文件与 SHA-256，不接受临时改参。</p>
            </div>
            <label class="research-confirm-check">
              <input v-model="openLockbox" type="checkbox" :disabled="Boolean(candidate.effective_lockbox_opened_at)" />
              <span>{{ candidate.effective_lockbox_opened_at ? "锁箱已开，不可再次开启" : "本次为一次性锁箱开箱" }}</span>
            </label>
            <button class="button primary" :disabled="store.researchWorkflowBusy || hasActiveRun" @click="runCandidate">
              {{ hasActiveRun ? "已有任务运行中" : openLockbox ? "开箱并运行" : "运行缓存评估" }}
            </button>
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
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import StatusBadge from "../components/StatusBadge.vue";
import {
  createResearchCandidate,
  loadResearchCatalog,
  refreshResearchRun,
  selectResearchCandidate,
  selectResearchResult,
  startResearchDatasetFetch,
  startResearchRun,
  store,
} from "../stores/appStore.js";

const datasetQuery = ref("");
const datasetKind = ref("all");
const showCreate = ref(false);
const showFetch = ref(false);
const openLockbox = ref(false);
const draft = reactive({ protocol: "M0", id: "", name: "", datasetIds: [], confirmed: false });
const fetchDraft = reactive({ symbol: "BTCUSDT", kind: "ohlc", interval: "15m", days: 180 });
const fetchIntervals = ["1m", "3m", "5m", "15m", "30m", "1h", "4h", "1d"];
let runPollTimer = null;
const datasetKinds = [
  { value: "all", label: "全部" },
  { value: "ohlc", label: "K 线" },
  { value: "funding", label: "Funding" },
  { value: "series", label: "序列" },
];

const candidate = computed(() => store.researchCandidate);
const result = computed(() => store.researchResult);
const selectedTemplate = computed(() => store.researchTemplates.find((item) => item.id === draft.protocol) || null);
const hasActiveRun = computed(() => store.researchRuns.some((item) => ["queued", "running"].includes(item.status)));
const compatibleDatasets = computed(() => {
  const mode = selectedTemplate.value?.dataset_rule?.mode;
  if (mode === "funding") return store.researchDatasets.filter((item) => item.kind === "funding");
  if (mode === "candles") return store.researchDatasets.filter((item) => ["ohlc", "series"].includes(item.kind));
  const interval = selectedTemplate.value?.dataset_rule?.candle_interval;
  return store.researchDatasets.filter((item) => item.kind === "funding"
    || (["ohlc", "series"].includes(item.kind) && (!interval || item.interval === interval)));
});
const canFreeze = computed(() => Boolean(
  draft.confirmed && draft.id && draft.protocol && draft.datasetIds.length,
));
const totalRows = computed(() => store.researchDatasets.reduce((sum, item) => sum + Number(item.rows || 0), 0));
const failedCandidates = computed(() => store.researchCandidates.filter((item) => {
  const verdict = item.latest_verdict || item.verdict;
  return verdict && String(verdict).toUpperCase() !== "PENDING" && !isPass(verdict);
}).length);
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

function applySuggestedDatasets() {
  const template = selectedTemplate.value;
  if (!template) return;
  const mode = template.dataset_rule.mode;
  const datasets = compatibleDatasets.value;
  if (mode === "candles") {
    const preferred = datasets.filter((item) => item.interval === "1h");
    draft.datasetIds = uniqueMarketDatasets(preferred.length ? preferred : datasets).slice(0, 4).map((item) => item.id);
    return;
  }
  if (mode === "funding") {
    draft.datasetIds = uniqueMarketDatasets(datasets).map((item) => item.id);
    return;
  }
  const marketLimit = Number(template.dataset_rule.exact_markets || template.dataset_rule.minimum_markets || 4);
  const requiredInterval = template.dataset_rule.candle_interval;
  const markets = [...new Set(datasets.map((item) => item.market).filter(Boolean))]
    .filter((market) => datasets.some((item) => item.market === market && item.kind === "funding")
      && datasets.some((item) => item.market === market
        && ["ohlc", "series"].includes(item.kind)
        && (!requiredInterval || item.interval === requiredInterval)))
    .sort();
  draft.datasetIds = markets.slice(0, marketLimit).flatMap((market) => {
    const funding = bestDataset(datasets.filter((item) => item.market === market && item.kind === "funding"));
    const candles = bestDataset(datasets.filter((item) => item.market === market
      && item.kind === "ohlc"
      && (!requiredInterval || item.interval === requiredInterval)))
      || bestDataset(datasets.filter((item) => item.market === market
        && item.kind === "series"
        && (!requiredInterval || item.interval === requiredInterval)));
    return [funding?.id, candles?.id].filter(Boolean);
  });
}

function uniqueMarketDatasets(datasets) {
  const selected = new Map();
  for (const item of datasets) {
    const key = item.market || item.id;
    if (!selected.has(key) || Number(item.rows || 0) > Number(selected.get(key).rows || 0)) selected.set(key, item);
  }
  return [...selected.values()].sort((left, right) => Number(right.rows || 0) - Number(left.rows || 0));
}

function bestDataset(datasets) {
  return [...datasets].sort((left, right) => Number(right.rows || 0) - Number(left.rows || 0))[0] || null;
}

async function freezeCandidate() {
  const created = await createResearchCandidate({
    id: draft.id,
    name: draft.name,
    protocol: draft.protocol,
    dataset_ids: draft.datasetIds,
  });
  if (!created) return;
  showCreate.value = false;
  Object.assign(draft, { id: "", name: "", datasetIds: [], confirmed: false });
}

async function runCandidate() {
  const activeCandidate = candidate.value;
  if (!activeCandidate) return;
  if (openLockbox.value && !window.confirm("锁箱只能打开一次。确认本次运行永久记录为开箱操作？")) return;
  const run = await startResearchRun(activeCandidate.id, openLockbox.value);
  if (!run) return;
  openLockbox.value = false;
  startRunPolling();
}

async function fetchDataset() {
  const run = await startResearchDatasetFetch({
    symbol: fetchDraft.symbol,
    kind: fetchDraft.kind,
    interval: fetchDraft.interval,
    days: fetchDraft.days,
  });
  if (run) startRunPolling();
}

function openRunTarget(run) {
  if (run.job_type !== "dataset_fetch") selectResearchCandidate(run.candidate_id);
}

function startRunPolling() {
  if (runPollTimer) return;
  runPollTimer = window.setInterval(async () => {
    const active = store.researchRuns.find((item) => ["queued", "running"].includes(item.status));
    if (!active) {
      window.clearInterval(runPollTimer);
      runPollTimer = null;
      return;
    }
    await refreshResearchRun(active.id);
  }, 1200);
}

function runLabel(run) {
  if (run.status === "failed") return run.error || "评估失败";
  if (run.job_type === "dataset_fetch") {
    const request = run.request || {};
    return run.status === "succeeded"
      ? `已新增 ${run.dataset_id}`
      : `拉取 ${request.symbol || "-"} ${request.kind === "funding" ? "Funding" : request.interval || "K 线"}`;
  }
  if (run.status === "succeeded") return `冻结判定 ${run.verdict}`;
  return run.status === "running" ? "正在运行缓存评估" : "等待执行";
}

function runStatusLabel(run) {
  return { queued: "排队", running: `${run.progress || 0}%`, succeeded: run.verdict || "完成", failed: "失败" }[run.status] || run.status;
}

function runStatusColor(run) {
  if (run.status === "failed" || run.verdict === "FAIL") return "red";
  if (run.status === "succeeded") return "green";
  return "blue";
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
  if (!value || String(value).toUpperCase() === "PENDING") return "PENDING";
  return isPass(value) ? "PASS" : "FAIL";
}

function verdictColor(value) {
  if (!value || String(value).toUpperCase() === "PENDING") return "blue";
  return isPass(value) ? "green" : "red";
}

function verdictClass(value) {
  if (!value || String(value).toUpperCase() === "PENDING") return "muted";
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

watch(() => candidate.value?.id, () => { openLockbox.value = false; });
onMounted(async () => {
  await loadResearchCatalog();
  if (!draft.datasetIds.length) applySuggestedDatasets();
  if (hasActiveRun.value) startRunPolling();
});
onBeforeUnmount(() => {
  if (runPollTimer) window.clearInterval(runPollTimer);
});
</script>
