<template>
  <section class="page active research-page" :class="{ 'data-center-page': isDataMode }">
    <div class="page-toolbar">
      <div>
        <h2>{{ isDataMode ? "市场数据中心" : "量价关系研究" }}</h2>
        <p>
          {{ isDataMode
            ? "统一管理历史研究数据、数据质量和构建任务；这里的故障不会改变实盘运行数据。"
            : "先验证成交量与价格之间是否存在可重复关系，再讨论具体入场信号。" }}
        </p>
      </div>
      <div class="toolbar">
        <button class="button ghost" :disabled="store.researchBusy" @click="loadResearchCatalog">
          {{ store.researchBusy ? "读取中..." : isDataMode ? "刷新数据" : "刷新研究档案" }}
        </button>
        <button v-if="isResearchMode" class="button primary" @click="showCreate = !showCreate">
          {{ showCreate ? "收起新候选" : "登记新候选" }}
        </button>
      </div>
    </div>

    <div v-if="pageError" class="service-alert">{{ pageError }}</div>

    <article v-if="isResearchMode" class="panel research-topic-panel">
      <div class="panel-head research-panel-head">
        <div>
          <span class="eyebrow">当前研究主题</span>
          <h3>量价关系</h3>
          <p class="muted">目标是判断成交量变化与后续价格行为是否存在跨市场、跨周期可重复的统计关系。当前阶段不组合入场信号，也不授权Paper或Live。</p>
        </div>
        <StatusBadge text="研究中" color="blue" />
      </div>
      <div class="research-audit-strip">
        <div><span>统一历史数据</span><strong>{{ officialDataset?.dataset_state === "COMPLETE" ? "已完整" : "待确认" }}</strong></div>
        <div><span>基础周期</span><strong>15分钟</strong></div>
        <div><span>派生周期</span><strong>1小时 / 4小时</strong></div>
        <div><span>下一步</span><strong>冻结R-0假设与变量</strong></div>
      </div>
    </article>

    <article v-if="isResearchMode && showCreate" class="panel research-create-panel">
      <div class="panel-head research-panel-head">
        <div>
          <h3>先写死规则，再登记新候选 <HelpTip term="预注册" /></h3>
          <p class="muted">提交后参数、成本、数据指纹与及格线永久不可修改。</p>
        </div>
        <StatusBadge text="预注册" color="blue" />
      </div>
      <div class="research-create-grid">
        <section class="research-create-fields">
          <label>
            <span>使用哪套固定检验规则</span>
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
            <p>{{ candidateCopy(selectedTemplate).summary }}</p>
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
            <div><h4>本候选固定使用哪些数据</h4><p class="muted">已选 {{ draft.datasetIds.length }} 个本地缓存文件</p></div>
            <button class="button ghost compact" type="button" @click="applySuggestedDatasets">推荐选择</button>
          </div>
          <div class="research-picker-list">
            <label v-for="dataset in compatibleDatasets" :key="dataset.id" class="research-picker-row">
              <input v-model="draft.datasetIds" type="checkbox" :value="dataset.id" />
              <span><strong>{{ dataset.id }}</strong><small>{{ dataset.market || "-" }} · {{ kindLabel(dataset.kind) }} · {{ dataset.interval || "-" }}</small></span>
              <code :title="`数据内容指纹：${dataset.sha256}`">{{ shortHash(dataset.sha256) }}</code>
            </label>
          </div>
        </section>
      </div>
      <div class="research-freeze-footer">
        <label class="research-confirm-check">
          <input v-model="draft.confirmed" type="checkbox" />
          <span>我确认：登记后只能新建另一个候选，不能修改或覆盖这个候选。</span>
        </label>
        <button class="button primary" :disabled="!canFreeze || store.researchWorkflowBusy" @click="freezeCandidate">
          {{ store.researchWorkflowBusy ? "冻结中..." : "冻结候选" }}
        </button>
      </div>
    </article>

    <div v-if="isDataMode" class="summary-grid research-summary">
      <div class="summary-item">
        <span>正式历史数据版本</span>
        <strong>{{ officialDataset?.dataset_state === "COMPLETE" ? "完整" : officialDataset ? "不完整" : "未登记" }}</strong>
        <small class="mono">{{ shortHash(officialDataset?.sha256) }}</small>
      </div>
      <div class="summary-item">
        <span>全市场归档条目</span>
        <strong>{{ Number(officialDataset?.rows || 0).toLocaleString("zh-CN") }}</strong>
        <small>manifest条目，不是K线根数</small>
      </div>
      <div class="summary-item">
        <span>旧缓存数据文件</span>
        <strong>{{ legacyDatasets.length }}</strong>
        <small>{{ ohlcDatasetCount }} 个K线 · {{ fundingDatasetCount }} 个Funding</small>
      </div>
      <div class="summary-item">
        <span>数据任务历史</span>
        <strong>{{ dataRuns.length }}</strong>
        <small>成功、失败和停止记录均保留</small>
      </div>
    </div>

    <div v-else class="summary-grid research-summary">
      <div class="summary-item">
        <span>历史研究候选</span>
        <strong>{{ store.researchCandidates.length }}</strong>
        <small>M0 / F1 / G1 / G2 等既有档案</small>
      </div>
      <div class="summary-item">
        <span>未通过的候选</span>
        <strong class="negative">{{ failedCandidates }}</strong>
        <small>没有通过预先写定的门槛</small>
      </div>
      <div class="summary-item">
        <span>可以查看的结果报告</span>
        <strong>{{ availableResults }}</strong>
        <small>本地结构化结果</small>
      </div>
      <div class="summary-item">
        <span>实验任务历史</span>
        <strong>{{ experimentRuns.length }}</strong>
        <small>不包含数据下载和构建任务</small>
      </div>
    </div>

    <article v-if="visibleRuns.length" class="panel research-runs-panel">
      <div class="panel-head">
        <div>
          <h3>{{ isDataMode ? "数据任务记录" : "实验运行记录" }}</h3>
          <p class="muted">{{ isDataMode ? "只显示数据拉取、全市场构建及其历史错误" : "只显示候选实验；程序完成不等于研究通过" }}</p>
        </div>
        <span class="pill">{{ visibleRuns.length }} 次</span>
      </div>
      <div class="research-run-list">
        <button v-for="run in visibleRuns.slice(0, 8)" :key="run.id" class="research-run-row" :class="{ static: Boolean(run.job_type) }" @click="openRunTarget(run)">
          <span class="candidate-id mono">{{ run.job_type ? "DATA" : run.candidate_id }}</span>
          <span class="research-run-copy"><strong>{{ runLabel(run) }}</strong><small>{{ dateTime(run.updated_at) }} · {{ run.id }}</small></span>
          <span class="research-progress"><i :style="{ width: `${run.progress || 0}%` }"></i></span>
          <StatusBadge :text="runStatusLabel(run)" :raw="run.status" :color="runStatusColor(run)" />
        </button>
      </div>
    </article>

    <article v-if="isDataMode" class="panel research-shortline-panel">
      <div class="panel-head research-panel-head">
        <div>
          <h3>全市场短线研究数据</h3>
          <p class="muted">一次完成历史合约索引、官方校验下载，以及15分钟到1小时/4小时的本地聚合。</p>
        </div>
        <StatusBadge
          :text="shortlineRun ? runStatusLabel(shortlineRun) : '尚未启动'"
          :raw="shortlineRun?.status || 'idle'"
          :color="shortlineRun ? runStatusColor(shortlineRun) : 'blue'"
        />
      </div>
      <div class="research-shortline-grid">
        <section class="research-shortline-copy">
          <strong>{{ shortlineRun ? shortlinePhaseLabel(shortlineRun.phase) : "等待建立 DATA-1R" }}</strong>
          <p>{{ shortlineRun?.message || "预计占用约 8–12 GB；已完成文件会保留，失败或取消后再次启动会校验并继续。" }}</p>
          <div v-if="shortlineRun" class="research-progress large">
            <i :style="{ width: `${shortlineRun.progress || 0}%` }"></i>
          </div>
          <small v-if="shortlineRun?.total_items" class="muted">
            已完成 {{ Number(shortlineRun.completed_items || 0).toLocaleString("zh-CN") }} /
            {{ Number(shortlineRun.total_items).toLocaleString("zh-CN") }}
            <template v-if="shortlineRun.current_item"> · {{ shortlineRun.current_item }}</template>
          </small>
          <small v-if="shortlineRun?.total_bytes" class="muted">
            已校验 {{ formatBytes(shortlineRun.completed_bytes) }} / {{ formatBytes(shortlineRun.total_bytes) }}
            <template v-if="shortlineRun.error_count"> · {{ shortlineRun.error_count }} 个错误</template>
          </small>
          <ul v-if="shortlineRun?.recent_logs?.length" class="research-shortline-logs">
            <li v-for="line in shortlineRun.recent_logs" :key="line">{{ line }}</li>
          </ul>
          <small v-if="shortlineRun?.lock_holder" class="muted">
            任务锁 {{ shortlineRun.lock_holder.owner }} · PID {{ shortlineRun.lock_holder.pid }} · {{ dateTime(shortlineRun.lock_holder.started_at) }}
          </small>
          <small v-if="shortlineRun?.dataset_fingerprint" class="muted mono" :title="shortlineRun.dataset_fingerprint">
            数据指纹 {{ shortHash(shortlineRun.dataset_fingerprint) }} · {{ shortlineRun.contract_count || "-" }} 个合约 · {{ shortlineRun.partition_count || "-" }} 个分区
          </small>
        </section>
        <section class="research-shortline-actions">
          <template v-if="!shortlineActive">
            <label><span>并行下载数</span><select v-model.number="shortlineDraft.workers"><option v-for="value in [1, 2, 4, 6, 8]" :key="value" :value="value">{{ value }}</option></select></label>
            <label class="research-confirm-check">
              <input v-model="shortlineDraft.confirmed" type="checkbox" />
              <span>我确认开始全市场公开数据下载，并允许占用约 8–12 GB 磁盘。</span>
            </label>
            <button class="button primary" :disabled="!shortlineDraft.confirmed || store.researchWorkflowBusy || hasActiveRun" @click="startShortline">
              {{ shortlineRun?.status === "cancelled" || shortlineRun?.status === "failed" ? "校验并继续" : "开始建立数据集" }}
            </button>
          </template>
          <template v-else>
            <p class="muted">停止不会删除已经通过 checksum 的文件；再次启动时会继续校验。</p>
            <button class="button danger" :disabled="store.researchWorkflowBusy || shortlineRun.status === 'cancelling'" @click="stopShortline">
              {{ shortlineRun.status === "cancelling" ? "正在停止..." : "停止数据任务" }}
            </button>
          </template>
        </section>
      </div>
    </article>

    <article v-if="isDataMode" class="panel research-dataset-panel">
      <div class="panel-head research-panel-head">
        <div>
          <h3>研究可以使用哪些本地数据？</h3>
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
        <label><span>数据类型</span><select v-model="fetchDraft.kind"><option value="ohlc">K 线价格</option><option value="funding">资金费率（Funding）</option></select></label>
        <label v-if="fetchDraft.kind === 'ohlc'"><span>周期</span><select v-model="fetchDraft.interval"><option v-for="interval in fetchIntervals" :key="interval" :value="interval">{{ interval }}</option></select></label>
        <label><span>天数</span><input v-model.number="fetchDraft.days" type="number" min="1" max="2000" /></label>
        <button class="button primary" :disabled="store.researchWorkflowBusy || hasActiveRun" @click="fetchDataset">开始拉取</button>
      </div>
      <div class="table-wrap research-data-table">
        <table>
          <thead><tr><th>数据集</th><th>市场</th><th>类型</th><th>周期</th><th>记录数</th><th>数据区间</th><th>内容指纹 <HelpTip term="哈希指纹" /></th></tr></thead>
          <tbody>
            <tr v-for="dataset in filteredDatasets" :key="dataset.id">
              <td><strong>{{ dataset.id }}</strong><div class="muted">{{ dataset.relative_path }}</div></td>
              <td>{{ dataset.market || "-" }}</td>
              <td><StatusBadge :text="kindLabel(dataset.kind)" :raw="dataset.kind" :color="kindColor(dataset.kind)" /></td>
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

    <div v-if="isResearchMode" class="research-workspace">
      <article class="panel research-history-panel">
        <div class="panel-head">
          <div>
            <h3>历史研究档案</h3>
            <p class="muted">M0、F1、G1、G2及后续实验的通过和失败记录都永久保留</p>
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
              <strong :title="candidateCopy(candidate).originalName">{{ candidateCopy(candidate).name }}</strong>
              <small>冻结于 {{ dateTime(candidate.frozen_at) }}</small>
            </span>
            <StatusBadge :text="verdictLabel(candidate.latest_verdict)" :raw="candidate.latest_verdict || 'PENDING'" :color="verdictColor(candidate.latest_verdict)" />
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
                <h3 :title="candidateCopy(candidate).originalName">{{ candidateCopy(candidate).name }}</h3>
                <StatusBadge :text="verdictLabel(candidate.latest_verdict)" :raw="candidate.latest_verdict || 'PENDING'" :color="verdictColor(candidate.latest_verdict)" />
              </div>
              <p :title="candidateCopy(candidate).originalSummary">{{ candidateCopy(candidate).summary }}</p>
            </div>
            <div class="research-freeze-state">
              <span>冻结内容指纹 <HelpTip term="哈希指纹" /></span>
              <strong class="mono" :title="candidate.frozen_hash">{{ shortHash(candidate.frozen_hash) }}</strong>
            </div>
          </div>

          <div class="research-audit-strip">
            <div><span>冻结时间</span><strong>{{ dateTime(candidate.frozen_at) }}</strong></div>
            <div><span>登记状态</span><strong :title="`系统原始值：${candidate.status}`">{{ enumLabel(candidate.status) }}</strong></div>
            <div><span>一次性考卷 <HelpTip term="锁箱" /></span><strong>{{ candidate.effective_lockbox_opened_at ? dateTime(candidate.effective_lockbox_opened_at) : "尚未打开" }}</strong></div>
            <div><span>当前结论</span><strong :class="verdictClass(candidate.latest_verdict)" :title="`系统原始值：${candidate.latest_verdict || 'PENDING'}`">{{ verdictLabel(candidate.latest_verdict) }}</strong></div>
          </div>

          <div v-if="candidate.status === 'frozen'" class="research-run-control">
            <div>
              <h4>按登记时的规则开始检验</h4>
              <p>只读取登记时选定的缓存文件和内容指纹，不接受临时改参数。</p>
            </div>
            <label class="research-confirm-check">
              <input v-model="openLockbox" type="checkbox" :disabled="Boolean(candidate.effective_lockbox_opened_at)" />
              <span>{{ candidate.effective_lockbox_opened_at ? "考卷已经打开，不能再次开启" : "本次将永久记录为打开一次性考卷" }}</span>
            </label>
            <button class="button primary" :disabled="store.researchWorkflowBusy || hasActiveRun" @click="runCandidate">
              {{ hasActiveRun ? "已有任务运行中" : openLockbox ? "开箱并运行" : "运行缓存评估" }}
            </button>
          </div>

          <div class="research-definition-grid">
            <section>
              <h4>跑数前写死的参数 <HelpTip term="预注册" /></h4>
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
              <h4>跑数前写死的及格线</h4>
              <div v-for="entry in entries(candidate.thresholds)" :key="entry[0]" class="fixed-bar-row">
                <span>{{ fieldLabel(entry[0]) }}</span>
                <strong>{{ definitionValue(entry[1]) }}</strong>
              </div>
            </section>
          </div>

          <div class="research-result-head">
            <div>
              <h4>结果为什么通过或失败？</h4>
              <p class="muted">逐个市场或配置对照跑数前写死的及格线</p>
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
              <span class="mono" :title="result.sha256">报告指纹 <HelpTip term="哈希指纹" /> {{ shortHash(result.sha256) }}</span>
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
                    <td><StatusBadge :text="enumLabel(row.admitted ? 'PASS' : 'FAIL')" :raw="row.admitted ? 'PASS' : 'FAIL'" :color="row.admitted ? 'green' : 'red'" /></td>
                  </tr>
                  <tr v-if="!evidenceRows.length"><td colspan="6" class="muted">该历史报告没有可以统一展示的逐项证据，最终结论仍以冻结登记为准。</td></tr>
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
import HelpTip from "../components/HelpTip.vue";
import StatusBadge from "../components/StatusBadge.vue";
import { candidateCopy, enumLabel } from "../domain/labels.js";
import {
  cancelResearchRun,
  createResearchCandidate,
  isAuthenticated,
  loadResearchCatalog,
  refreshResearchRun,
  selectResearchCandidate,
  selectResearchResult,
  startResearchDatasetFetch,
  startResearchRun,
  startShortlineDatasetBuild,
  store,
} from "../stores/appStore.js";

const props = defineProps({
  mode: { type: String, default: "research" },
});
const datasetQuery = ref("");
const datasetKind = ref("all");
const showCreate = ref(false);
const showFetch = ref(false);
const openLockbox = ref(false);
const draft = reactive({ protocol: "M0", id: "", name: "", datasetIds: [], confirmed: false });
const fetchDraft = reactive({ symbol: "BTCUSDT", kind: "ohlc", interval: "15m", days: 180 });
const shortlineDraft = reactive({ workers: 4, confirmed: false });
const fetchIntervals = ["1m", "3m", "5m", "15m", "30m", "1h", "4h", "1d"];
let runPollTimer = null;
const datasetKinds = [
  { value: "all", label: "全部" },
  { value: "ohlc", label: "K 线" },
  { value: "funding", label: "资金费率" },
  { value: "series", label: "序列" },
];

const isDataMode = computed(() => props.mode === "data");
const isResearchMode = computed(() => !isDataMode.value);
const pageError = computed(() => (isDataMode.value ? store.dataError : store.researchError));
const candidate = computed(() => store.researchCandidate);
const result = computed(() => store.researchResult);
const dataRuns = computed(() => store.researchRuns.filter((item) => (
  item.job_type === "dataset_fetch" || item.job_type === "shortline_dataset"
)));
const experimentRuns = computed(() => store.researchRuns.filter((item) => !item.job_type));
const visibleRuns = computed(() => (isDataMode.value ? dataRuns.value : experimentRuns.value));
const officialDataset = computed(() => (
  store.researchDatasets.find((item) => item.id === "shortline-data-v1")
  || store.researchDatasets.find((item) => item.kind === "dataset_manifest")
  || null
));
const legacyDatasets = computed(() => store.researchDatasets.filter((item) => item.kind !== "dataset_manifest"));
const ohlcDatasetCount = computed(() => legacyDatasets.value.filter((item) => ["ohlc", "series"].includes(item.kind)).length);
const fundingDatasetCount = computed(() => legacyDatasets.value.filter((item) => item.kind === "funding").length);
const selectedTemplate = computed(() => store.researchTemplates.find((item) => item.id === draft.protocol) || null);
const activeRunStatuses = ["queued", "running", "cancelling"];
const hasActiveRun = computed(() => store.researchRuns.some((item) => activeRunStatuses.includes(item.status)));
const shortlineRun = computed(() => store.researchRuns.find((item) => item.job_type === "shortline_dataset") || null);
const shortlineActive = computed(() => Boolean(shortlineRun.value && activeRunStatuses.includes(shortlineRun.value.status)));
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

async function startShortline() {
  if (!window.confirm("确认开始全市场 DATA-1R 下载与构建？预计占用约 8–12 GB 磁盘。")) return;
  const run = await startShortlineDatasetBuild({
    confirm_full_download: shortlineDraft.confirmed,
    workers: shortlineDraft.workers,
  });
  if (!run) return;
  shortlineDraft.confirmed = false;
  startRunPolling();
}

async function stopShortline() {
  const run = shortlineRun.value;
  if (!run || !window.confirm("确认停止当前数据任务？已完成文件会保留。")) return;
  const updated = await cancelResearchRun(run.id);
  if (updated) startRunPolling();
}

function openRunTarget(run) {
  if (!run.job_type) selectResearchCandidate(run.candidate_id);
}

function startRunPolling() {
  if (runPollTimer) return;
  runPollTimer = window.setInterval(async () => {
    const active = visibleRuns.value.find((item) => activeRunStatuses.includes(item.status));
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
  if (run.job_type === "shortline_dataset") {
    if (run.status === "succeeded") return "DATA-1R 全市场数据集完成";
    if (run.status === "cancelled") return "DATA-1R 数据任务已停止";
    return `${shortlinePhaseLabel(run.phase)} · ${run.message || "正在处理"}`;
  }
  if (run.job_type === "dataset_fetch") {
    const request = run.request || {};
    return run.status === "succeeded"
      ? `已新增 ${run.dataset_id}`
      : `拉取 ${request.symbol || "-"} ${request.kind === "funding" ? "资金费率" : request.interval || "K 线"}`;
  }
  if (run.status === "succeeded") return `冻结结论：${verdictLabel(run.verdict)}`;
  return run.status === "running" ? "正在运行缓存评估" : "等待执行";
}

function runStatusLabel(run) {
  if (run.job_type && run.status === "succeeded") return "任务完成";
  if (run.job_type && run.status === "failed") return "任务失败";
  return {
    queued: enumLabel("queued"),
    running: `正在运行 ${run.progress || 0}%`,
    cancelling: "正在停止",
    cancelled: "已停止",
    succeeded: run.verdict ? verdictLabel(run.verdict) : enumLabel("succeeded"),
    failed: enumLabel("failed"),
  }[run.status] || enumLabel(run.status);
}

function runStatusColor(run) {
  if (run.status === "failed" || run.verdict === "FAIL") return "red";
  if (run.status === "succeeded") return "green";
  if (run.status === "cancelled" || run.status === "cancelling") return "orange";
  return "blue";
}

function shortlinePhaseLabel(value) {
  return {
    queued: "等待启动",
    starting: "启动任务",
    index: "第一步：枚举历史合约",
    download: "第二步：下载并校验原始数据",
    build: "第三步：聚合并生成质量报告",
    verify: "第四步：核对官方原生聚合",
    complete: "数据集构建完成",
    interrupted: "服务重启后等待续校",
  }[value] || "数据任务";
}

function formatBytes(value) {
  const bytes = Number(value || 0);
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
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
  if (row.holding_ticks !== undefined) parts.push(`持有 ${row.holding_ticks} 个周期`);
  if (row.holding_settlements !== undefined) parts.push(`持有 ${row.holding_settlements} 个结算期`);
  if (row.window_settlements !== undefined) parts.push(`${row.window_settlements} 个结算期`);
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
    holding_ticks: "持有周期数",
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
  return enumLabel(value);
}

function kindColor(value) {
  return { ohlc: "blue", funding: "orange", series: "green" }[value] || "blue";
}

function isPass(value) {
  return ["GO", "PASS", "LOCKBOX_PASS"].includes(String(value || "").toUpperCase());
}

function verdictLabel(value) {
  if (!value || String(value).toUpperCase() === "PENDING") return enumLabel("PENDING");
  return enumLabel(isPass(value) ? "PASS" : "FAIL");
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
async function initializeResearch() {
  await loadResearchCatalog();
  if (!draft.datasetIds.length) applySuggestedDatasets();
  if (hasActiveRun.value) startRunPolling();
}

onMounted(async () => {
  if (isAuthenticated.value) await initializeResearch();
});
watch(isAuthenticated, async (authenticated) => {
  if (authenticated) await initializeResearch();
});
onBeforeUnmount(() => {
  if (runPollTimer) window.clearInterval(runPollTimer);
});
</script>
