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
        <button class="button ghost" :disabled="store.researchBusy" @click="refreshCatalog">
          {{ store.researchBusy ? "读取中..." : isDataMode ? "刷新数据" : "刷新研究档案" }}
        </button>
      </div>
    </div>

    <div v-if="pageError" class="service-alert">{{ pageError }}</div>

    <div v-if="!catalogReady && !pageError" class="panel structured-empty-state catalog-loading-state">
      <strong>{{ isDataMode ? "正在读取数据版本与任务…" : "正在读取研究假设与历史档案…" }}</strong>
      <p>载入完成前不显示 0 值，避免把“尚未读取”误解为“没有数据”。</p>
    </div>

    <template v-else-if="catalogReady">

    <article v-if="isDataMode" class="panel data-version-panel">
      <div class="panel-head research-panel-head">
        <div>
          <span class="eyebrow">当前研究数据</span>
          <h3>{{ officialDataset ? "全市场历史数据" : "历史数据尚未准备好" }}</h3>
          <p class="muted">包含 Binance 永续合约的历史价格与资金费率。正在进行的更新不会影响已经准备好的数据。</p>
        </div>
        <StatusBadge
          :text="datasetStateLabel(officialDataset)"
          :raw="officialDataset?.dataset_state || 'UNREGISTERED'"
          :color="officialDataset?.dataset_state === 'COMPLETE' ? 'green' : 'orange'"
        />
      </div>
      <div class="data-version-grid">
        <div>
          <span>覆盖的历史合约</span>
          <strong>{{ shortlineRun?.contract_count ? `${Number(shortlineRun.contract_count).toLocaleString("zh-CN")} 个` : "明细待完善" }}</strong>
          <small>包含仍在交易和已经退市的永续合约</small>
        </div>
        <div>
          <span>可研究的时间尺度</span>
          <strong>15分钟 / 1小时 / 4小时</strong>
          <small>1小时和4小时由15分钟数据统一生成</small>
        </div>
        <div>
          <span>数据更新到什么时候</span>
          <strong>暂时无法统一确认</strong>
          <small>后续将显示全部合约共同覆盖到的日期</small>
        </div>
        <div>
          <span>数据有没有缺失</span>
          <strong>暂时无法汇总</strong>
          <small>后续将分别显示缺失、重复和停牌时段</small>
        </div>
      </div>
      <div v-if="!officialDataset" class="data-empty-callout">
        尚未生成可供研究使用的完整数据。请先在下方检查并更新历史数据；实盘行情与本页隔离，不会因此停止。
      </div>
      <details v-if="officialDataset" class="technical-details">
        <summary>技术详情（供开发与排障使用）</summary>
        <div class="technical-details-grid">
          <div><span>内部版本编号</span><strong class="mono">{{ officialDataset.id }}</strong></div>
          <div><span>数据校验码</span><strong class="mono" :title="officialDataset.sha256">{{ shortHash(officialDataset.sha256) }}</strong></div>
          <div><span>存储清单条目</span><strong>{{ Number(officialDataset.rows || 0).toLocaleString("zh-CN") }}</strong></div>
          <div><span>最近构建分片</span><strong>{{ Number(shortlineRun?.partition_count || 0).toLocaleString("zh-CN") }}</strong></div>
        </div>
        <p>以上数字仅用于开发人员验证文件是否完整，不代表合约数量、K线条数或可交易市场数量，普通研究无需关注。</p>
      </details>
    </article>

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
        <div><span>下一步</span><strong>接入 R-0 预注册定义</strong></div>
      </div>
    </article>

    <template v-if="isResearchMode">
      <div class="summary-grid research-summary">
        <div class="summary-item">
          <span>量价关系预注册假设</span>
          <strong>{{ topicCandidates.length }}</strong>
          <small>单位：个 · 来源：研究登记</small>
        </div>
        <div class="summary-item">
          <span>正在运行的实验</span>
          <strong>{{ activeTopicRuns.length }}</strong>
          <small>单位：项 · 仅实验任务</small>
        </div>
        <div class="summary-item">
          <span>得到支持</span>
          <strong class="positive">{{ supportedTopicCandidates }}</strong>
          <small>研究结论，不是任务运行状态</small>
        </div>
        <div class="summary-item">
          <span>未支持 / 证据不足</span>
          <strong>{{ unresolvedTopicCandidates }}</strong>
          <small>单位：个 · 结果永久保留</small>
        </div>
      </div>

      <article class="panel research-hypothesis-panel">
        <div class="panel-head">
          <div>
            <h3>量价关系假设</h3>
            <p class="muted">预注册、程序运行和研究结论分列；程序完成不代表关系成立。</p>
          </div>
          <StatusBadge text="R-01 / R-02 待读模型" color="orange" />
        </div>
        <div v-if="topicCandidates.length" class="table-wrap">
          <table>
            <thead><tr><th>假设</th><th>预注册</th><th>最近任务</th><th>研究结论</th><th>证据</th></tr></thead>
            <tbody>
              <tr v-for="item in topicCandidates" :key="item.id">
                <td><strong>{{ item.id }}</strong><div class="muted">{{ item.name || "未命名假设" }}</div></td>
                <td><StatusBadge :text="item.status === 'frozen' ? '已冻结' : enumLabel(item.status)" color="blue" /><div class="muted">{{ dateTime(item.frozen_at) }}</div></td>
                <td><StatusBadge :text="latestRunFor(item.id) ? runStatusLabel(latestRunFor(item.id)) : '尚未运行'" :color="latestRunFor(item.id) ? runStatusColor(latestRunFor(item.id)) : 'blue'" /></td>
                <td><StatusBadge :text="researchVerdictLabel(item.latest_verdict)" :color="researchVerdictColor(item.latest_verdict)" /></td>
                <td class="mono">{{ shortHash(item.frozen_hash) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else class="structured-empty-state">
          <strong>尚无量价关系的正式预注册假设</strong>
          <p>R-0 的结构化变量和数据版本绑定将在 MOD-3 接入。在此之前不使用旧协议冒充量价关系，也不会提供一个无法满足冻结契约的创建按钮。</p>
          <span>下一步：完成 R-01 研究投影与 R-02 预注册命令。</span>
        </div>
      </article>

      <article class="panel research-runs-panel">
        <div class="panel-head">
          <div><h3>量价关系实验运行</h3><p class="muted">这里只显示当前主题实验，永远不包含数据下载任务。</p></div>
          <span class="pill">{{ topicExperimentRuns.length }} 次</span>
        </div>
        <div v-if="topicExperimentRuns.length" class="research-run-list">
          <button v-for="run in topicExperimentRuns.slice(0, 8)" :key="run.id" class="research-run-row" @click="openRunTarget(run)">
            <span class="candidate-id mono">{{ run.candidate_id }}</span>
            <span class="research-run-copy"><strong>{{ runLabel(run) }}</strong><small>{{ dateTime(run.updated_at) }} · {{ run.id }}</small></span>
            <span class="research-progress"><i :style="{ width: `${run.progress || 0}%` }"></i></span>
            <StatusBadge :text="runStatusLabel(run)" :raw="run.status" :color="runStatusColor(run)" />
          </button>
        </div>
        <div v-else class="structured-empty-state compact">
          <strong>当前没有量价关系实验在运行</strong>
          <p>先完成预注册，随后实验任务及其错误会显示在这里；数据构建任务请到“数据”页查看。</p>
        </div>
      </article>
    </template>

    <article id="legacy-create" v-if="isResearchMode && showCreate" class="panel research-create-panel legacy-create-panel">
      <div class="panel-head research-panel-head">
        <div>
          <h3>登记历史协议候选 <HelpTip term="预注册" /></h3>
          <p class="muted">仅用于 M0 / F1 / G1 / G2 兼容协议；它不是 R-0 量价关系预注册入口。提交后不可修改。</p>
        </div>
        <StatusBadge text="历史兼容工具" color="orange" />
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
        <span>历史合约</span>
        <strong>{{ shortlineRun?.contract_count ? Number(shortlineRun.contract_count).toLocaleString("zh-CN") : "—" }}</strong>
        <small>单位：个 · 包含已退市合约</small>
      </div>
      <div class="summary-item">
        <span>价格数据</span>
        <strong>{{ officialDataset?.dataset_state === "COMPLETE" ? "已包含" : "未准备好" }}</strong>
        <small>15分钟、1小时和4小时 K 线</small>
      </div>
      <div class="summary-item">
        <span>资金费率</span>
        <strong>{{ officialDataset?.dataset_state === "COMPLETE" ? "已包含" : "未准备好" }}</strong>
        <small>用于还原永续合约的持仓成本</small>
      </div>
      <div class="summary-item">
        <span>最近一次更新</span>
        <strong>{{ shortlineRun?.updated_at ? dateTime(shortlineRun.updated_at) : "暂无记录" }}</strong>
        <small>{{ shortlineRun ? runStatusLabel(shortlineRun) : "尚未运行数据更新" }}</small>
      </div>
    </div>

    <article v-if="isResearchMode && legacyExperimentRuns.length" class="panel research-runs-panel legacy-run-panel">
      <div class="panel-head">
        <div>
          <h3>历史协议实验任务</h3>
          <p class="muted">M0 / F1 / G1 / G2 的运行记录，与当前量价关系主题分开。</p>
        </div>
        <span class="pill">{{ legacyExperimentRuns.length }} 次</span>
      </div>
      <div class="research-run-list">
        <button v-for="run in legacyExperimentRuns.slice(0, 8)" :key="run.id" class="research-run-row" @click="openRunTarget(run)">
          <span class="candidate-id mono">{{ run.candidate_id }}</span>
          <span class="research-run-copy"><strong>{{ runLabel(run) }}</strong><small>{{ dateTime(run.updated_at) }} · {{ run.id }}</small></span>
          <span class="research-progress"><i :style="{ width: `${run.progress || 0}%` }"></i></span>
          <StatusBadge :text="runStatusLabel(run)" :raw="run.status" :color="runStatusColor(run)" />
        </button>
      </div>
    </article>

    <article v-if="isDataMode" class="panel research-shortline-panel">
      <div class="panel-head research-panel-head">
        <div>
          <h3>更新全市场历史数据</h3>
          <p class="muted">系统会自动查找历史合约、下载并核对公开数据，再生成15分钟、1小时和4小时数据。</p>
        </div>
        <StatusBadge
          :text="shortlineRun ? runStatusLabel(shortlineRun) : '尚未启动'"
          :raw="shortlineRun?.status || 'idle'"
          :color="shortlineRun ? runStatusColor(shortlineRun) : 'blue'"
        />
      </div>
      <div class="research-shortline-grid">
        <section class="research-shortline-copy">
          <strong>{{ shortlineRun ? shortlinePhaseLabel(shortlineRun.phase) : "尚未更新历史数据" }}</strong>
          <p>{{ shortlineRun?.message ? userFacingDataMessage(shortlineRun.message) : "预计占用约 8–12 GB；已经下载好的文件会保留，中断后可以继续。" }}</p>
          <div v-if="shortlineActive" class="research-progress large">
            <i :style="{ width: `${shortlineRun.progress || 0}%` }"></i>
          </div>
          <small v-if="shortlineActive && shortlineRun?.total_items" class="muted">
            已完成 {{ Number(shortlineRun.completed_items || 0).toLocaleString("zh-CN") }} /
            {{ Number(shortlineRun.total_items).toLocaleString("zh-CN") }}
            <template v-if="shortlineRun.current_item"> · {{ shortlineRun.current_item }}</template>
          </small>
          <small v-if="shortlineActive && shortlineRun?.total_bytes" class="muted">
            已校验 {{ formatBytes(shortlineRun.completed_bytes) }} / {{ formatBytes(shortlineRun.total_bytes) }}
            <template v-if="shortlineRun.error_count"> · {{ shortlineRun.error_count }} 个错误</template>
          </small>
          <details v-if="shortlineActive && (shortlineRun?.recent_logs?.length || shortlineRun?.lock_holder)" class="technical-details compact">
            <summary>查看排障信息</summary>
            <ul v-if="shortlineRun?.recent_logs?.length" class="research-shortline-logs">
              <li v-for="line in shortlineRun.recent_logs" :key="line">{{ line }}</li>
            </ul>
            <small v-if="shortlineRun?.lock_holder" class="muted">
              任务进程 {{ shortlineRun.lock_holder.owner }} · PID {{ shortlineRun.lock_holder.pid }} · {{ dateTime(shortlineRun.lock_holder.started_at) }}
            </small>
          </details>
          <small v-if="shortlineRun && !shortlineActive" class="muted">最近任务于 {{ dateTime(shortlineRun.updated_at) }} 结束；正式数据完整性以上方版本卡为准。</small>
        </section>
        <section class="research-shortline-actions">
          <template v-if="!shortlineActive">
            <label><span>同时下载几个文件（速度设置）</span><select v-model.number="shortlineDraft.workers"><option v-for="value in [1, 2, 4, 6, 8]" :key="value" :value="value">{{ value }}</option></select></label>
            <label class="research-confirm-check">
              <input v-model="shortlineDraft.confirmed" type="checkbox" />
              <span>我确认开始全市场公开数据下载，并允许占用约 8–12 GB 磁盘。</span>
            </label>
            <button class="button primary" :disabled="!shortlineDraft.confirmed || store.researchWorkflowBusy || hasActiveRun" @click="startShortline">
              {{ shortlineRun?.status === "cancelled" || shortlineRun?.status === "failed" ? "检查并继续更新" : "检查并更新数据" }}
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

    <article v-if="isDataMode" class="panel research-runs-panel">
      <div class="panel-head">
        <div>
          <h3>最近的数据更新记录</h3>
          <p class="muted">这里记录每次更新是否完成。上方显示“已准备好，可以开始研究”才代表数据可以使用。</p>
        </div>
        <span class="pill">{{ dataRuns.length }} 次</span>
      </div>
      <div v-if="dataRuns.length" class="research-run-list">
        <div v-for="run in dataRuns.slice(0, 8)" :key="run.id" class="research-run-row static">
          <span class="candidate-id">数据</span>
          <span class="research-run-copy"><strong>{{ runLabel(run) }}</strong><small>{{ dateTime(run.updated_at) }}</small></span>
          <span class="research-progress"><i :style="{ width: `${run.progress || 0}%` }"></i></span>
          <StatusBadge :text="runStatusLabel(run)" :raw="run.status" :color="runStatusColor(run)" />
        </div>
      </div>
      <div v-else class="structured-empty-state compact">
        <strong>还没有更新记录</strong>
        <p>使用上方“检查并更新数据”后，进度和结果会显示在这里。</p>
      </div>
    </article>

    <div v-if="isDataMode" class="data-gap-grid">
      <article class="panel data-gap-card">
        <span class="eyebrow">功能建设中</span><h3>查看以前的数据版本</h3>
        <p>以后可以查看每次数据更新产生的版本。目前只显示现在可供研究使用的数据。</p>
        <StatusBadge text="尚未开放" color="orange" />
      </article>
      <article class="panel data-gap-card">
        <span class="eyebrow">功能建设中</span><h3>每个合约覆盖多久</h3>
        <p>以后可以分别查看仍在交易和已经退市的合约，以及每个合约的起止日期。</p>
        <StatusBadge text="尚未开放" color="orange" />
      </article>
      <article class="panel data-gap-card">
        <span class="eyebrow">功能建设中</span><h3>数据缺失与停牌检查</h3>
        <p>以后会分别展示缺失、重复、停牌和不同周期之间不一致的情况。</p>
        <StatusBadge text="尚未开放" color="orange" />
      </article>
      <article class="panel data-gap-card">
        <span class="eyebrow">功能建设中</span><h3>实时行情是否正常</h3>
        <p>以后会单独显示公共实时行情的连接和更新时间，不与历史数据混在一起。</p>
        <StatusBadge text="尚未开放" color="orange" />
      </article>
    </div>

    <details v-if="isDataMode" class="panel research-dataset-panel legacy-data-details">
      <summary class="legacy-data-summary">
        <div>
          <h3>旧研究数据（用于复现以前的报告）</h3>
          <p class="muted">通常不需要操作。这里保留 {{ legacyDatasets.length }} 个旧文件，展开后可查看或补充单个市场。</p>
        </div>
        <span class="pill">高级工具</span>
      </summary>
      <div class="legacy-data-content">
        <div class="panel-head research-panel-head">
          <div>
            <h4>旧数据文件</h4>
            <p class="muted">这些文件只用于复现历史报告，不是当前全市场研究数据。</p>
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
          <button class="button ghost compact" @click="showFetch = !showFetch">{{ showFetch ? "收起工具" : "补充单个市场数据" }}</button>
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
          <thead><tr><th>文件</th><th>市场</th><th>数据内容</th><th>周期</th><th>数据条数</th><th>覆盖日期</th><th>文件校验码</th></tr></thead>
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
            <tr v-if="!filteredDatasets.length"><td colspan="7" class="muted">没有符合当前筛选条件的旧数据文件。</td></tr>
          </tbody>
        </table>
      </div>
      </div>
    </details>

    <div v-if="isResearchMode" class="summary-grid research-summary legacy-summary">
      <div class="summary-item"><span>历史候选</span><strong>{{ legacyCandidates.length }}</strong><small>单位：个 · M0/F1/G1/G2</small></div>
      <div class="summary-item"><span>未通过门槛</span><strong class="negative">{{ failedLegacyCandidates }}</strong><small>研究结论，不是任务失败</small></div>
      <div class="summary-item"><span>可查看报告</span><strong>{{ legacyAvailableResults }}</strong><small>单位：份 · 本地冻结结果</small></div>
      <div class="summary-item"><span>历史实验任务</span><strong>{{ legacyExperimentRuns.length }}</strong><small>单位：次 · 不含数据任务</small></div>
    </div>

    <div v-if="isResearchMode" class="research-workspace">
      <article class="panel research-history-panel">
        <div class="panel-head">
          <div>
            <h3>历史研究档案</h3>
            <p class="muted">M0、F1、G1、G2 的通过和失败记录永久保留，不占据当前主题主流程。</p>
          </div>
          <div class="archive-head-actions">
            <span class="pill">{{ legacyCandidates.length }} 项</span>
            <button class="button ghost compact" @click="toggleLegacyCreate">{{ showCreate ? "收起兼容工具" : "登记历史候选" }}</button>
          </div>
        </div>
        <div class="candidate-history">
          <button
            v-for="candidate in legacyCandidates"
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
          <p v-if="!legacyCandidates.length && !store.researchBusy" class="muted">尚无 M0 / F1 / G1 / G2 历史档案。</p>
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
    </template>
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
const catalogReady = ref(false);
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
const pageError = computed(() => {
  const error = isDataMode.value ? store.dataError : store.researchError;
  return isDataMode.value ? userFacingDataMessage(error) : error;
});
const candidate = computed(() => store.researchCandidate);
const result = computed(() => store.researchResult);
const dataRuns = computed(() => store.researchRuns.filter((item) => (
  item.job_type === "dataset_fetch" || item.job_type === "shortline_dataset"
)));
const experimentRuns = computed(() => store.researchRuns.filter((item) => !item.job_type));
const officialDataset = computed(() => (
  store.researchDatasets.find((item) => item.id === "shortline-data-v1")
  || store.researchDatasets.find((item) => item.kind === "dataset_manifest")
  || null
));
const legacyDatasets = computed(() => store.researchDatasets.filter((item) => item.kind !== "dataset_manifest"));
const activeRunStatuses = ["queued", "running", "cancelling"];
const legacyProtocolIds = new Set(["M0", "F1", "G1", "G2"]);
const legacyCandidates = computed(() => store.researchCandidates.filter(isLegacyCandidate));
const topicCandidates = computed(() => store.researchCandidates.filter((item) => !isLegacyCandidate(item)));
const topicCandidateIds = computed(() => new Set(topicCandidates.value.map((item) => item.id)));
const topicExperimentRuns = computed(() => experimentRuns.value.filter((item) => topicCandidateIds.value.has(item.candidate_id)));
const legacyExperimentRuns = computed(() => experimentRuns.value.filter((item) => !topicCandidateIds.value.has(item.candidate_id)));
const activeTopicRuns = computed(() => topicExperimentRuns.value.filter((item) => activeRunStatuses.includes(item.status)));
const supportedTopicCandidates = computed(() => topicCandidates.value.filter((item) => isSupportedVerdict(item.latest_verdict)).length);
const unresolvedTopicCandidates = computed(() => topicCandidates.value.filter((item) => {
  const verdict = String(item.latest_verdict || "PENDING").toUpperCase();
  return verdict !== "PENDING" && !isSupportedVerdict(verdict);
}).length);
const selectedTemplate = computed(() => store.researchTemplates.find((item) => item.id === draft.protocol) || null);
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
const failedLegacyCandidates = computed(() => legacyCandidates.value.filter((item) => {
  const verdict = item.latest_verdict || item.verdict;
  return verdict && String(verdict).toUpperCase() !== "PENDING" && !isPass(verdict);
}).length);
const legacyAvailableResults = computed(() => legacyCandidates.value.reduce(
  (sum, item) => sum + (item.results || []).filter((entry) => entry.available).length,
  0,
));
const filteredDatasets = computed(() => {
  const query = datasetQuery.value.toLowerCase();
  return legacyDatasets.value.filter((item) => {
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

async function refreshCatalog() {
  const loaded = await loadResearchCatalog();
  catalogReady.value = loaded;
  if (loaded && !draft.datasetIds.length) applySuggestedDatasets();
  if (loaded && hasActiveRun.value) startRunPolling();
}

function isLegacyCandidate(item) {
  const protocol = String(item?.protocol || item?.id || "").toUpperCase().split(/[-_]/)[0];
  return legacyProtocolIds.has(protocol);
}

function latestRunFor(candidateId) {
  return topicExperimentRuns.value.find((item) => item.candidate_id === candidateId) || null;
}

function isSupportedVerdict(value) {
  return ["SUPPORTED", "GO", "PASS", "LOCKBOX_PASS"].includes(String(value || "").toUpperCase());
}

function researchVerdictLabel(value) {
  const normalized = String(value || "PENDING").toUpperCase();
  return {
    PENDING: "等待结论",
    SUPPORTED: "得到支持",
    NOT_SUPPORTED: "未得到支持",
    INCONCLUSIVE: "证据不足",
    INVALID: "实验无效",
    GO: "得到支持",
    PASS: "得到支持",
    LOCKBOX_PASS: "得到支持",
    NO_GO: "未得到支持",
    FAIL: "未得到支持",
  }[normalized] || enumLabel(normalized);
}

function researchVerdictColor(value) {
  const normalized = String(value || "PENDING").toUpperCase();
  if (isSupportedVerdict(normalized)) return "green";
  if (["NOT_SUPPORTED", "NO_GO", "FAIL", "INVALID"].includes(normalized)) return "red";
  return normalized === "INCONCLUSIVE" ? "orange" : "blue";
}

function datasetStateLabel(dataset) {
  if (!dataset) return "尚未准备好";
  return dataset.dataset_state === "COMPLETE" ? "已准备好，可以开始研究" : "需要继续检查";
}

function toggleLegacyCreate() {
  showCreate.value = !showCreate.value;
  if (showCreate.value) window.setTimeout(() => document.getElementById("legacy-create")?.scrollIntoView({ behavior: "smooth", block: "start" }), 0);
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
  if (!window.confirm("确认检查并更新全市场历史数据？预计占用约 8–12 GB 磁盘。")) return;
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
    const runs = isDataMode.value ? dataRuns.value : experimentRuns.value;
    const active = runs.find((item) => activeRunStatuses.includes(item.status));
    if (!active) {
      window.clearInterval(runPollTimer);
      runPollTimer = null;
      return;
    }
    await refreshResearchRun(active.id);
  }, 1200);
}

function runLabel(run) {
  if (run.status === "failed") return run.job_type
    ? (userFacingDataMessage(run.error) || "数据更新失败")
    : (run.error || "评估失败");
  if (run.job_type === "shortline_dataset") {
    if (run.status === "succeeded") return "全市场历史数据已更新";
    if (run.status === "cancelled") return "历史数据更新已停止";
    return `${shortlinePhaseLabel(run.phase)} · ${userFacingDataMessage(run.message) || "正在处理"}`;
  }
  if (run.job_type === "dataset_fetch") {
    const request = run.request || {};
    return run.status === "succeeded"
      ? `已新增 ${run.dataset_id}`
      : `拉取 ${request.symbol || "-"} ${request.kind === "funding" ? "资金费率" : request.interval || "K 线"}`;
  }
  if (run.status === "succeeded") return "实验程序已完成";
  return run.status === "running" ? "正在运行缓存评估" : "等待执行";
}

function userFacingDataMessage(value) {
  const message = String(value || "").trim();
  if (!message) return "";
  if (/全市场研究数据集已完成|research dataset.*complete/i.test(message)) {
    return "全部历史数据已经下载、校验并整理完成。";
  }
  if (/WinError\s*5|拒绝访问/i.test(message)) {
    return "无法写入数据目录，可能有文件正被其他程序占用。请稍后重试；如果持续出现，请联系开发人员。";
  }
  if (/does not hold the dataset lock|dataset lock/i.test(message)) {
    return "数据更新未取得写入权限。请重新启动后台服务后再试。";
  }
  return message
    .replace(/DATA-1R/gi, "全市场历史数据更新")
    .replace(/dataset/gi, "数据")
    .replace(/manifest/gi, "数据清单")
    .replace(/checksum/gi, "文件校验");
}

function runStatusLabel(run) {
  return {
    queued: enumLabel("queued"),
    running: `正在运行 ${run.progress || 0}%`,
    cancelling: "正在停止",
    cancelled: "已停止",
    succeeded: "任务完成",
    failed: "任务失败",
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
    complete: "历史数据已更新完成",
    interrupted: "上次更新中断，可以继续",
  }[value] || "正在处理历史数据";
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
  await refreshCatalog();
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
