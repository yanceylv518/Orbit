<template>
  <section class="page active data-v2">
    <article class="panel data-overview-card">
      <div class="data-overview-head"><div><h2>历史数据概览</h2><p class="muted">全量历史保留在服务器，日常只做增量更新。</p></div><button class="button small" :disabled="updateLocked" @click="start">{{ updateLocked ? "更新进行中" : "检查并更新" }}</button></div>
      <div class="data-overview-metrics"><div><span>覆盖范围</span><strong>{{ summary?.contracts?.total ?? "—" }}</strong><small>个历史合约</small></div><div><span>更新到何时</span><strong>{{ cutoff }}</strong><small>最近成功数据日期</small></div><div><span>数据完整性</span><strong :class="{ 'status-good': healthy }">{{ healthy ? "完整" : "需检查" }}</strong><small>{{ healthy ? "没有未解释缺口" : "存在未解释缺口" }}</small></div><div><span>时间尺度</span><strong>15分 / 1时 / 4时</strong><small>已生成研究周期</small></div></div>
    </article>
    <p v-if="store.dataError && !displayRun" class="service-alert compact data-update-error">{{ store.dataError }}</p>
    <article v-if="displayRun" class="panel data-task-compact">
      <div class="data-task-compact-main"><span class="task-live-dot"></span><div><strong>{{ phaseLabel(displayRun.phase) }}</strong><span>{{ displayRun.current_item || displayRun.current_symbol || displayRun.message || "正在准备数据更新" }}</span></div></div>
      <div class="data-task-compact-meta"><span>{{ itemProgress(displayRun) }}</span><span>{{ byteProgress(displayRun) }}</span><span :class="{ 'task-error': displayRun.error_count }">错误 {{ displayRun.error_count || 0 }}</span></div>
      <div class="data-task-compact-progress"><i :style="{ width: `${displayRun.progress || 0}%` }"></i></div><strong class="data-task-compact-percent">{{ displayRun.progress || 0 }}%</strong>
      <button class="button danger small" :disabled="startingUpdate || store.researchWorkflowBusy || displayRun.status === 'cancelling'" @click="stopTask">{{ startingUpdate ? "正在创建" : displayRun.status === "cancelling" ? "正在停止" : "停止" }}</button>
    </article>
    <section class="data-market-layout">
      <article class="panel data-market-list"><div class="panel-head"><div><h3>当前币种列表 <span class="market-live-status" :class="store.currentMarketStreamStatus">{{ streamStatusText }}</span></h3><p class="muted">当前合约行情，按 24 小时成交额降序。<strong v-if="store.currentMarkets.length" class="market-count">当前 {{ store.currentMarkets.length.toLocaleString("zh-CN") }} 个币种</strong><span v-if="store.currentMarkets.length && filteredCoins.length !== store.currentMarkets.length"> · 筛选后 {{ filteredCoins.length.toLocaleString("zh-CN") }} 个</span><span v-if="store.currentMarketsUpdatedAt"> · 目录刷新：{{ marketUpdatedAt }}</span></p></div><div class="market-list-actions"><select v-model="category"><option>全部分类</option><option>主流币</option><option>山寨币</option><option>股票类</option><option>大宗商品</option></select><select v-model="scope"><option>全部范围</option><option>扫描中</option><option>未扫描</option></select><button class="button ghost small" :disabled="store.currentMarketsBusy" @click="loadCurrentMarkets(true)">{{ store.currentMarketsBusy ? "刷新中…" : "刷新币种目录" }}</button></div></div><p v-if="store.currentMarketsError" class="service-alert compact">刷新失败：{{ store.currentMarketsError }}</p><p v-else-if="store.currentMarketsNotice" class="market-refresh-notice">{{ store.currentMarketsNotice }}</p><div class="table-wrap"><table><thead><tr><th :aria-sort="ariaSort('symbol')"><button class="sortable-head" @click="toggleSort('symbol')">币种 <span>{{ sortIndicator('symbol') }}</span></button></th><th :aria-sort="ariaSort('last_price')"><button class="sortable-head" @click="toggleSort('last_price')">最新价 <span>{{ sortIndicator('last_price') }}</span></button></th><th :aria-sort="ariaSort('change_24h_pct')"><button class="sortable-head" @click="toggleSort('change_24h_pct')">24小时涨跌 <span>{{ sortIndicator('change_24h_pct') }}</span></button></th><th :aria-sort="ariaSort('volume_24h_usdt')"><button class="sortable-head" @click="toggleSort('volume_24h_usdt')">24小时成交额 <span>{{ sortIndicator('volume_24h_usdt') }}</span></button></th><th :aria-sort="ariaSort('funding_rate')"><button class="sortable-head" @click="toggleSort('funding_rate')">资金费率 <span>{{ sortIndicator('funding_rate') }}</span></button></th><th>下次结算</th><th>扫描状态</th><th></th></tr></thead><tbody><tr v-if="!filteredCoins.length"><td colspan="8" class="muted">{{ store.currentMarketsBusy ? "正在读取当前市场…" : "当前筛选下没有币种，点击“刷新币种目录”重试。" }}</td></tr><tr v-for="coin in filteredCoins" :key="coin.symbol"><td><strong>{{ coin.symbol }}</strong></td><td class="market-price">{{ price(coin.last_price) }}</td><td><strong class="market-change" :class="changeClass(coin.change_24h_pct)">{{ changeText(coin.change_24h_pct) }}</strong></td><td>{{ money(coin.volume_24h_usdt) }}</td><td :class="changeClass(coin.funding_rate)">{{ fundingText(coin.funding_rate) }}</td><td>{{ fundingCountdown(coin.next_funding_at_ms) }}</td><td><strong>{{ coin.scan_state }}</strong><small v-if="coin.scan_reason" class="muted"> · {{ coin.scan_reason }}</small></td><td class="table-action"><button class="button ghost small" @click="openCoin(coin)">查看</button></td></tr></tbody></table></div></article>
    </section>

    <div v-if="selectedCoin" class="modal-backdrop" role="presentation" @mousedown.self="closeCoin">
      <section class="coin-detail-modal" role="dialog" aria-modal="true" :aria-labelledby="`coin-detail-${selectedCoin.symbol}`">
        <header class="coin-detail-head"><div><span class="eyebrow">币种详情</span><h2 :id="`coin-detail-${selectedCoin.symbol}`">{{ selectedCoin.symbol }}</h2><p class="muted">当前市场状态与数据可用性</p></div><button class="icon-button modal-close" aria-label="关闭币种详情" @click="closeCoin">×</button></header>
        <div class="coin-detail-grid"><div><span>最新价</span><strong>{{ price(selectedCoin.last_price) }}</strong></div><div><span>24 小时涨跌</span><strong :class="changeClass(selectedCoin.change_24h_pct)">{{ changeText(selectedCoin.change_24h_pct) }}</strong></div><div><span>24 小时最高 / 最低</span><strong>{{ price(selectedCoin.high_24h) }} / {{ price(selectedCoin.low_24h) }}</strong></div><div><span>24 小时成交额</span><strong>{{ money(selectedCoin.volume_24h_usdt) }}</strong></div><div><span>标记价 / 指数价</span><strong>{{ price(selectedCoin.mark_price) }} / {{ price(selectedCoin.index_price) }}</strong></div><div><span>资金费率</span><strong :class="changeClass(selectedCoin.funding_rate)">{{ fundingText(selectedCoin.funding_rate) }}</strong><small>{{ fundingCountdown(selectedCoin.next_funding_at_ms) }}</small></div><div><span>上市时间</span><strong>{{ listedText(selectedCoin) }}</strong></div><div><span>分类 / 扫描状态</span><strong>{{ selectedCoin.category }} · {{ selectedCoin.scan_state }}</strong><small v-if="selectedCoin.scan_reason">{{ selectedCoin.scan_reason }}</small></div></div>
        <div class="coin-detail-placeholder"><strong>长周期状态待独立接入</strong><p>实时行情与历史研究数据保持分离；长周期状态将在独立行情计算服务完成后显示。</p></div>
      </section>
    </div>

    <section class="data-maintenance-layout">
        <article class="panel data-history-card">
          <div class="panel-head"><div><h3>最近数据更新</h3><p class="muted">只显示每次更新的最终结果，过程记录不会重复列出。</p></div></div>
          <div v-if="!historyRuns.length" class="structured-empty-state compact"><strong>还没有完成的更新</strong><p>任务结束后会在这里记录时间、更新量和结果。</p></div>
          <div v-else class="data-history-list">
            <article v-for="run in historyRuns" :key="run.id" class="data-history-row">
              <time :datetime="run.completed_at || run.updated_at"><strong>{{ historyDate(run) }}</strong><span>{{ historyTime(run) }}</span></time>
              <div class="data-history-volume"><span>本次更新</span><strong>{{ updateAmount(run) }}</strong></div>
              <div class="data-history-result"><span class="history-status" :class="run.status">{{ statusText(run.status) }}</span><small v-if="run.status === 'failed'">{{ failureText(run) }}</small><small v-else>{{ run.status === 'cancelled' ? '已完成内容保留，可继续更新' : '数据已校验并可使用' }}</small></div>
            </article>
          </div>
        </article>
    </section>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { cancelResearchRun, connectCurrentMarketStream, disconnectCurrentMarketStream, loadCurrentMarkets, loadDataCatalog, startShortlineDatasetBuild, store } from "../stores/appStore.js";

const category = ref("全部分类"); const scope = ref("全部范围"); const selectedCoin = ref(null); const sortKey = ref("volume_24h_usdt"); const sortDirection = ref("desc");
const startingUpdate = ref(false);
const nowMs = ref(Date.now()); let marketClockTimer = null;
const summary = computed(() => store.dataSummary);
const healthy = computed(() => summary.value?.dataset_state === "COMPLETE" && !summary.value?.quality?.unverified_missing_15m_candles);
const cutoff = computed(() => summary.value?.dataset_cutoff_ms ? new Date(summary.value.dataset_cutoff_ms).toLocaleDateString("zh-CN") : "尚未生成");
const marketUpdatedAt = computed(() => store.currentMarketsUpdatedAt ? new Date(store.currentMarketsUpdatedAt).toLocaleString("zh-CN", { hour12: false }) : "");
const streamStatusText = computed(() => ({ live: "实时", connecting: "连接中", reconnecting: "重连中", offline: "已断开" }[store.currentMarketStreamStatus] || "已断开"));
const filteredCoins = computed(() => store.currentMarkets.filter((coin) => (category.value === "全部分类" || coin.category === category.value) && (scope.value === "全部范围" || coin.scan_state === scope.value)).sort(compareCoins));
const recentRuns = computed(() => store.researchRuns.filter((item) => item.job_type === "shortline_dataset").slice(0, 5));
const activeRun = computed(() => recentRuns.value.find((item) => ["queued", "running", "cancelling"].includes(item.status)));
const displayRun = computed(() => activeRun.value || (startingUpdate.value ? { status: "creating", phase: "creating", progress: 0, message: "正在创建后台任务", error_count: 0 } : null));
const updateLocked = computed(() => startingUpdate.value || Boolean(activeRun.value));
const historyRuns = computed(() => store.researchRuns.filter((item) => item.job_type === "shortline_dataset" && ["succeeded", "failed", "cancelled"].includes(item.status)).slice(0, 5));
onMounted(() => { loadDataCatalog(); loadCurrentMarkets(); connectCurrentMarketStream(); marketClockTimer = setInterval(() => { nowMs.value = Date.now(); }, 30_000); document.addEventListener("keydown", onKeydown); });
onBeforeUnmount(() => { disconnectCurrentMarketStream(); clearInterval(marketClockTimer); document.removeEventListener("keydown", onKeydown); });
function openCoin(coin) { selectedCoin.value = coin; }
function closeCoin() { selectedCoin.value = null; }
function onKeydown(event) { if (event.key === "Escape") closeCoin(); }
function toggleSort(key) { if (sortKey.value === key) sortDirection.value = sortDirection.value === "asc" ? "desc" : "asc"; else { sortKey.value = key; sortDirection.value = key === "symbol" ? "asc" : "desc"; } }
function sortIndicator(key) { return sortKey.value === key ? (sortDirection.value === "asc" ? "▲\n▽" : "△\n▼") : "△\n▽"; }
function ariaSort(key) { return sortKey.value === key ? (sortDirection.value === "asc" ? "ascending" : "descending") : "none"; }
function compareCoins(left, right) { const key = sortKey.value; const direction = sortDirection.value === "asc" ? 1 : -1; if (key === "symbol") return left.symbol.localeCompare(right.symbol) * direction; const leftValue = Number(left[key]); const rightValue = Number(right[key]); const leftMissing = !Number.isFinite(leftValue); const rightMissing = !Number.isFinite(rightValue); if (leftMissing !== rightMissing) return leftMissing ? 1 : -1; if (leftValue === rightValue) return left.symbol.localeCompare(right.symbol); return (leftValue - rightValue) * direction; }
async function start() { if (updateLocked.value) return; startingUpdate.value = true; try { await startShortlineDatasetBuild({ confirm_full_download: true, workers: 4 }); } finally { startingUpdate.value = false; } }
function stopTask() { if (activeRun.value) cancelResearchRun(activeRun.value.id); }
function phaseLabel(value) { return { creating: "正在创建任务", queued: "等待开始", restarting: "正在恢复任务", starting: "正在启动", index: "正在核对合约与月份", download: "正在下载并校验", build: "正在生成多时间尺度数据", verify: "正在做最终完整性检查" }[value] || "正在更新历史数据"; }
function itemProgress(run) { return run.total_items ? `${Number(run.completed_items || 0).toLocaleString("zh-CN")} / ${Number(run.total_items).toLocaleString("zh-CN")}` : "等待统计"; }
function formatBytes(value) { const count = Number(value || 0); if (!count) return "0 B"; const units = ["B", "KB", "MB", "GB", "TB"]; const index = Math.min(Math.floor(Math.log(count) / Math.log(1024)), 4); return `${(count / 1024 ** index).toFixed(index ? 1 : 0)} ${units[index]}`; }
function byteProgress(run) { return run.total_bytes ? `${formatBytes(run.completed_bytes)} / ${formatBytes(run.total_bytes)}` : "等待校验"; }
function runDate(run) { return new Date(run.completed_at || run.updated_at || run.created_at); }
function historyDate(run) { return runDate(run).toLocaleDateString("zh-CN", { month: "numeric", day: "numeric" }); }
function historyTime(run) { return runDate(run).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" }); }
function statusText(status) { return { succeeded: "更新成功", failed: "更新失败", cancelled: "已停止" }[status] || "已结束"; }
function updateAmount(run) { if (run.contract_count || run.partition_count) return `覆盖 ${Number(run.contract_count || 0).toLocaleString("zh-CN")} 个合约 · ${Number(run.partition_count || 0).toLocaleString("zh-CN")} 个合约月份`; if (run.completed_items) return `已处理 ${Number(run.completed_items).toLocaleString("zh-CN")} 个数据文件${run.completed_bytes ? ` · ${formatBytes(run.completed_bytes)}` : ""}`; return run.status === "failed" ? "未完成" : "没有新增数据"; }
function failureText(run) { const text = String(run.error || run.message || "失败原因未记录"); return text.length > 72 ? `${text.slice(0, 72)}…` : text; }
function money(value) { const count = Number(value || 0); return count >= 100_000_000 ? `${(count / 100_000_000).toFixed(1)} 亿 USDT` : `${(count / 10_000).toFixed(0)} 万 USDT`; }
function price(value) { const count = Number(value || 0); if (!count) return "—"; return count >= 1000 ? count.toLocaleString("zh-CN", { maximumFractionDigits: 2 }) : count.toLocaleString("zh-CN", { maximumSignificantDigits: 8 }); }
function changeText(value) { const count = Number(value); return Number.isFinite(count) ? `${count > 0 ? "+" : ""}${count.toFixed(2)}%` : "—"; }
function changeClass(value) { const count = Number(value || 0); return count > 0 ? "positive" : count < 0 ? "negative" : ""; }
function fundingText(value) { const count = Number(value); return Number.isFinite(count) && value !== null && value !== undefined ? `${count >= 0 ? "+" : ""}${(count * 100).toFixed(4)}%` : "—"; }
function fundingCountdown(value) { const remaining = Number(value || 0) - nowMs.value; if (remaining <= 0) return "待更新"; const hours = Math.floor(remaining / 3_600_000); const minutes = Math.floor((remaining % 3_600_000) / 60_000); return `${hours}时 ${minutes}分`; }
function listedText(coin) { return coin.listed_at_ms ? `${new Date(coin.listed_at_ms).toLocaleDateString("zh-CN")} · ${coin.listing_days} 天` : "未知"; }
</script>
