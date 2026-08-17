import { computed, reactive } from "vue";
import { createCurrentMarketStream } from "../api/currentMarketStream.js";
import {
  cancelResearchRunRequest,
  createResearchCandidateRequest,
  createResearchDatasetFetchRequest,
  createResearchRunRequest,
  createR0RunRequest,
  createShortlineDatasetRequest,
  fetchAppState,
  fetchDataQuality,
  fetchDataSummary,
  fetchCurrentMarkets,
  fetchResearchCandidate,
  fetchResearchCandidates,
  fetchResearchDatasets,
  fetchResearchResult,
  fetchResearchRun,
  fetchR0Status,
  fetchR0Gallery,
  fetchR0GallerySamples,
  fetchResearchRuns,
  fetchResearchTemplates,
  fetchStrategies,
  fetchStrategy,
  fetchLiveExecutionReports,
  fetchSignalDesk,
  fetchMessages,
  readMessageRequest,
  readAllMessagesRequest,
  loginRequest,
  logoutRequest,
  postJson,
  recordSignalDecisionRequest,
  recordSignalExecutionRequest,
  configureSignalPushoverRequest,
  testSignalPushoverRequest,
  controlSignalServiceRequest,
  controlSignalFamilyRequest,
  bindSignalAccountRequest,
  resumeStoppedSymbolRequest,
} from "../api/client.js";

let currentMarketsNoticeTimer = null;
let currentMarketStream = null;
import { LEGACY_PAGE_ALIASES } from "../domain/labels.js";

export const store = reactive({
  state: null,
  activePage: (location.hash.replace("#", "") || "forward").split("/")[0],
  activeRoute: location.hash.replace("#", "") || "forward",
  selectedSymbol: "",
  selectedPlanAccount: "",
  loginBusy: false,
  loginError: "",
  stateError: "",
  syncAllBusy: false,
  recoveringStoppedSymbolId: "",
  researchDatasets: [],
  researchCandidates: [],
  researchCandidate: null,
  researchResult: null,
  researchTemplates: [],
  researchRuns: [],
  r0Status: null,
  r0Gallery: null,
  r0GallerySamples: {},
  r0GalleryBusy: false,
  researchBusy: false,
  dataBusy: false,
  dataCatalogLoadedAt: "",
  dataSummary: null,
  currentMarkets: [],
  currentMarketsUpdatedAt: "",
  currentMarketsBusy: false,
  currentMarketsError: "",
  currentMarketsNotice: "",
  currentMarketStreamStatus: "offline",
  dataQuality: null,
  dataQualityBusy: false,
  researchResultBusy: false,
  researchWorkflowBusy: false,
  researchError: "",
  dataError: "",
  strategies: [],
  selectedStrategy: null,
  strategyCatalogBusy: false,
  strategyCatalogError: "",
  liveExecutionReports: [],
  liveExecutionReportsBusy: false,
  liveExecutionReportsError: "",
  signalDesk: null,
  signalDeskBusy: false,
  signalDeskError: "",
  messages: [],
  messagesUnread: 0,
});

export async function loadMessages() { const {response,data}=await fetchMessages(); if(response.ok&&!data.error){store.messages=data.items||[];store.messagesUnread=data.unread_count||0;} }
export async function markMessageRead(id) { const {response,data}=await readMessageRequest(id); if(response.ok&&!data.error){await loadMessages();} }
export async function markAllMessagesRead() { const {response}=await readAllMessagesRequest(); if(response.ok) await loadMessages(); }

export async function loadSignalDesk(day = "") {
  if (store.signalDeskBusy) return null;
  store.signalDeskBusy = true;
  store.signalDeskError = "";
  try {
    const { response, data } = await fetchSignalDesk(day);
    if (!response.ok || data.error) throw new Error(data.error || `读取信号台失败（HTTP ${response.status}）。`);
    store.signalDesk = data;
    return data;
  } catch (error) {
    store.signalDeskError = error instanceof Error ? error.message : "读取信号台失败。";
    return null;
  } finally {
    store.signalDeskBusy = false;
  }
}

export async function decideSignal(payload) {
  const { response, data } = await recordSignalDecisionRequest(payload);
  if (!response.ok || data.error) {
    store.signalDeskError = data.error || `登记决定失败（HTTP ${response.status}）。`;
    return false;
  }
  store.signalDesk = data;
  return true;
}

export async function recordSignalExecution(payload) {
  const { response, data } = await recordSignalExecutionRequest(payload);
  if (!response.ok || data.error) {
    store.signalDeskError = data.error || `登记成交失败（HTTP ${response.status}）。`;
    return false;
  }
  store.signalDesk = data;
  return true;
}

async function applySignalCommand(request) {
  store.signalDeskError = "";
  try {
    const { response, data } = await request;
    if (!response.ok || data.error || data.detail) throw new Error(data.error || data.detail || `操作失败（HTTP ${response.status}）。`);
    if (data.protocol === "ORBIT_SIGNAL_DESK_V2") store.signalDesk = data;
    return data;
  } catch (error) {
    store.signalDeskError = error instanceof Error ? error.message : "信号服务操作失败。";
    return null;
  }
}

export function configureSignalPushover(payload) { return applySignalCommand(configureSignalPushoverRequest(payload)); }
export function testSignalPushover() { return applySignalCommand(testSignalPushoverRequest()); }
export function controlSignalService(enabled) { return applySignalCommand(controlSignalServiceRequest(enabled)); }
export function controlSignalFamily(familyId, enabled, reason = null) { return applySignalCommand(controlSignalFamilyRequest(familyId, enabled, reason)); }
export function bindSignalAccount(accountId) { return applySignalCommand(bindSignalAccountRequest(accountId)); }

export const isAuthenticated = computed(() => Boolean(store.state?.auth?.authenticated));
export const currentUser = computed(() => store.state?.auth?.current_user || null);
export const isAdmin = computed(() => ["admin", "super_admin"].includes(currentUser.value?.role));
export const symbols = computed(() => store.state?.symbols || []);
export const accounts = computed(() => store.state?.admin_overview?.accounts || []);
export const users = computed(() => store.state?.admin_overview?.users || []);
export const executionPlans = computed(() => store.state?.execution_plans || []);
export const exchangeAccounts = computed(() => store.state?.exchange_accounts || []);
export const accountSnapshots = computed(() => store.state?.binance_account_snapshots || {});
export const riskState = computed(() => store.state?.risk_state || {
  global_stop: false,
  stopped_symbols: [],
  blocked_decisions: [],
});
// 账户级生命周期状态（行情循环实时驱动，独立于执行计划存在）
export const planSymbolStates = computed(() => store.state?.plan_symbol_states || []);
export const marketFeed = computed(() => store.state?.market_feed || null);

export function currentSymbol() {
  return symbols.value.find((item) => item.symbol === store.selectedSymbol) || symbols.value[0] || null;
}

// 第一阶段主流程漏斗：账户同步 → Hedge 检查 → 计划生成 → 确认/拦截
export const syncFunnel = computed(() => {
  const snaps = accountSnapshots.value;
  const rows = exchangeAccounts.value.map((account) => ({
    account,
    snapshot: snaps[account.id] || null,
  }));
  const synced = rows.filter((row) => row.snapshot?.status === "synced");
  const failed = rows.filter((row) => row.snapshot && row.snapshot.status !== "synced");
  const hedgeFail = synced.filter((row) => row.snapshot?.position_mode?.hedge_mode_ok === false);
  const lastSyncedAt = synced
    .map((row) => row.snapshot?.synced_at)
    .filter(Boolean)
    .sort()
    .at(-1) || null;
  return {
    rows,
    total: rows.length,
    syncedCount: synced.length,
    failed,
    unsynced: rows.filter((row) => !row.snapshot),
    hedgeOkCount: synced.length - hedgeFail.length,
    hedgeFail,
    lastSyncedAt,
  };
});

export const planFunnel = computed(() => {
  const plans = executionPlans.value;
  const planned = plans.filter((plan) => plan.status === "planned");
  return {
    total: plans.length,
    planned,
    pendingConfirm: planned.filter((plan) => plan.manual_review?.status !== "confirmed"),
    blocked: plans.filter((plan) => plan.status === "blocked"),
    noActionCount: plans.filter((plan) => plan.status === "no_action").length,
    confirmedCount: plans.filter((plan) => plan.manual_review?.status === "confirmed").length,
  };
});

// 最近一份带净敞口内核上下文的计划，用于展示币种相位/Δ*
export function latestKernelPlan(symbolName) {
  return executionPlans.value.find(
    (plan) => plan.symbol === symbolName && plan.trigger?.exposure_model,
  ) || null;
}

// 按币种聚合真实持仓行（real_symbol_views 每行是一个账户+方向），得到 Δ 净敞口视图
export function aggregateSymbols(rows) {
  const map = new Map();
  for (const row of rows) {
    const entry = map.get(row.symbol) || {
      symbol: row.symbol,
      price: 0,
      long_qty: 0,
      short_qty: 0,
      unrealized_pnl: 0,
      accountLabels: new Set(),
    };
    entry.long_qty += Number(row.long_qty) || 0;
    entry.short_qty += Number(row.short_qty) || 0;
    entry.unrealized_pnl += Number(row.unrealized_pnl) || 0;
    entry.price = Number(row.price) || entry.price;
    if (row.account_id) entry.accountLabels.add(row.account_label || row.account_id);
    map.set(row.symbol, entry);
  }
  return [...map.values()].map((entry) => {
    const delta = entry.long_qty - entry.short_qty;
    return {
      ...entry,
      accountLabels: [...entry.accountLabels],
      delta_qty: delta,
      delta_notional: delta * entry.price,
      plan: latestKernelPlan(entry.symbol),
    };
  });
}

export const symbolOverviews = computed(() => aggregateSymbols(symbols.value));

export function setActivePage(page) {
  const requested = String(page || "forward");
  const route = LEGACY_PAGE_ALIASES[requested] || requested;
  const [base] = route.split("/");
  store.activePage = base;
  store.activeRoute = route;
  if (location.hash !== `#${route}`) {
    history.replaceState(null, "", `#${route}`);
  }
}

export function selectSymbol(symbol, openPage = false) {
  store.selectedSymbol = symbol;
  if (openPage) setActivePage("symbol");
}

export async function loadState() {
  try {
    const nextState = await fetchAppState();
    if (nextState.__error) {
      store.stateError = nextState.__error;
      if (!store.state) store.loginError = nextState.__error;
      return false;
    }
    store.state = nextState;
    store.stateError = "";
    const availableSymbols = symbols.value;
    if (!availableSymbols.find((item) => item.symbol === store.selectedSymbol)) {
      store.selectedSymbol = availableSymbols[0]?.symbol || "";
    }
    return isAuthenticated.value;
  } catch (error) {
    const message = error instanceof Error ? error.message : "读取本地服务状态失败。";
    store.stateError = message;
    if (!store.state) store.loginError = message;
    return false;
  }
}

function researchErrorMessage(response, data, fallback) {
  if (response.status === 401) return "请先登录后查看研究档案。";
  if (response.status === 403) return "当前用户无权查看研究档案。";
  if (Array.isArray(data.detail)) {
    return data.detail.map((item) => `${item.loc?.at(-1) || "字段"}: ${item.msg || "无效"}`).join("；");
  }
  return data.detail || data.error || `${fallback}（HTTP ${response.status}）`;
}

export async function loadResearchCatalog() {
  if (store.researchBusy) return false;
  store.researchBusy = true;
  store.researchError = "";
  store.dataError = "";
  try {
    const [datasetsResponse, candidatesResponse, templatesResponse, runsResponse, r0Response] = await Promise.all([
      fetchResearchDatasets(),
      fetchResearchCandidates(),
      fetchResearchTemplates(),
      fetchResearchRuns(),
      fetchR0Status(),
    ]);
    if (!datasetsResponse.response.ok || datasetsResponse.data.error) {
      throw new Error(researchErrorMessage(
        datasetsResponse.response,
        datasetsResponse.data,
        "读取研究数据目录失败",
      ));
    }
    if (!candidatesResponse.response.ok || candidatesResponse.data.error) {
      throw new Error(researchErrorMessage(
        candidatesResponse.response,
        candidatesResponse.data,
        "读取候选履历失败",
      ));
    }
    if (!templatesResponse.response.ok || templatesResponse.data.error) {
      throw new Error(researchErrorMessage(
        templatesResponse.response,
        templatesResponse.data,
        "读取研究协议模板失败",
      ));
    }
    if (!runsResponse.response.ok || runsResponse.data.error) {
      throw new Error(researchErrorMessage(runsResponse.response, runsResponse.data, "读取研究任务失败"));
    }
    if (!r0Response.response.ok || r0Response.data.error) {
      throw new Error(researchErrorMessage(r0Response.response, r0Response.data, "读取短线筛查状态失败"));
    }
    store.researchDatasets = datasetsResponse.data.items || [];
    store.researchCandidates = candidatesResponse.data.items || [];
    store.researchTemplates = templatesResponse.data.items || [];
    store.researchRuns = runsResponse.data.items || [];
    store.r0Status = r0Response.data;
    const selectedId = store.researchCandidate?.id || store.researchCandidates[0]?.id;
    if (selectedId) await selectResearchCandidate(selectedId);
    return true;
  } catch (error) {
    const message = error instanceof Error ? error.message : "读取研究档案失败。";
    store.researchError = message;
    store.dataError = message;
    return false;
  } finally {
    store.researchBusy = false;
  }
}

export async function loadDataCatalog() {
  if (store.dataBusy) return Boolean(store.dataCatalogLoadedAt);
  store.dataBusy = true;
  store.dataError = "";
  try {
    const [datasetsResponse, runsResponse, summaryResponse] = await Promise.all([
      fetchResearchDatasets(),
      fetchResearchRuns(),
      fetchDataSummary(),
    ]);
    if (!datasetsResponse.response.ok || datasetsResponse.data.error) {
      throw new Error(researchErrorMessage(
        datasetsResponse.response,
        datasetsResponse.data,
        "读取历史数据目录失败",
      ));
    }
    if (!runsResponse.response.ok || runsResponse.data.error) {
      throw new Error(researchErrorMessage(runsResponse.response, runsResponse.data, "读取数据更新记录失败"));
    }
    if (!summaryResponse.response.ok || summaryResponse.data.error) {
      throw new Error(researchErrorMessage(summaryResponse.response, summaryResponse.data, "读取数据质量摘要失败"));
    }
    store.researchDatasets = datasetsResponse.data.items || [];
    store.researchRuns = runsResponse.data.items || [];
    store.dataSummary = summaryResponse.data;
    store.dataCatalogLoadedAt = new Date().toISOString();
    return true;
  } catch (error) {
    store.dataError = error instanceof Error ? error.message : "读取历史数据失败。";
    return false;
  } finally {
    store.dataBusy = false;
  }
}

export async function loadCurrentMarkets(refresh = false) {
  if (store.currentMarketsBusy) return false;
  if (currentMarketsNoticeTimer) {
    clearTimeout(currentMarketsNoticeTimer);
    currentMarketsNoticeTimer = null;
  }
  store.currentMarketsBusy = true;
  store.currentMarketsError = "";
  store.currentMarketsNotice = refresh ? "正在从交易所刷新当前币种…" : "";
  try {
    const { response, data } = await fetchCurrentMarkets(refresh);
    if (!response.ok || data.error || data.detail) throw new Error(data.error || data.detail || "读取当前币种失败");
    store.currentMarkets = data.items || [];
    store.currentMarketsUpdatedAt = data.updated_at || "";
    store.currentMarketsNotice = refresh ? `刷新完成，共 ${store.currentMarkets.length.toLocaleString("zh-CN")} 个当前币种` : "";
    if (refresh) {
      currentMarketsNoticeTimer = setTimeout(() => {
        store.currentMarketsNotice = "";
        currentMarketsNoticeTimer = null;
      }, 3000);
    }
    return true;
  } catch (error) {
    store.currentMarketsError = error instanceof Error ? error.message : "读取当前币种失败";
    store.currentMarketsNotice = "";
    return false;
  } finally {
    store.currentMarketsBusy = false;
  }
}

export function connectCurrentMarketStream() {
  if (currentMarketStream) return;
  const rowsBySymbol = () => new Map(store.currentMarkets.map((row) => [row.symbol, row]));
  currentMarketStream = createCurrentMarketStream({
    onStatus(status) { store.currentMarketStreamStatus = status; },
    onTicker(rows) {
      const index = rowsBySymbol();
      rows.forEach((ticker) => {
        if (ticker.st !== undefined && Number(ticker.st) !== 1) return;
        const row = index.get(ticker.s);
        if (!row) return;
        Object.assign(row, {
          last_price: Number(ticker.c || 0),
          change_24h_pct: Number(ticker.P || 0),
          open_24h: Number(ticker.o || 0),
          high_24h: Number(ticker.h || 0),
          low_24h: Number(ticker.l || 0),
          weighted_average_24h: Number(ticker.w || 0),
          volume_24h_base: Number(ticker.v || 0),
          volume_24h_usdt: Number(ticker.q || 0),
          trade_count_24h: Number(ticker.n || 0),
          ticker_updated_at_ms: Number(ticker.E || Date.now()),
        });
      });
    },
    onMarkPrice(rows) {
      const index = rowsBySymbol();
      rows.forEach((ticker) => {
        if (ticker.st !== undefined && Number(ticker.st) !== 1) return;
        const row = index.get(ticker.s);
        if (!row) return;
        Object.assign(row, {
          mark_price: Number(ticker.p || 0),
          index_price: Number(ticker.i || 0),
          funding_rate: Number(ticker.r || 0),
          next_funding_at_ms: Number(ticker.T || 0),
        });
      });
    },
  });
}

export function disconnectCurrentMarketStream() {
  currentMarketStream?.stop();
  currentMarketStream = null;
}

export async function loadDataQuality(kind = "halts", page = 1, pageSize = 50) {
  if (store.dataQualityBusy) return false;
  store.dataQualityBusy = true;
  store.dataError = "";
  try {
    const { response, data } = await fetchDataQuality(kind, page, pageSize);
    if (!response.ok || data.error) {
      throw new Error(researchErrorMessage(response, data, "读取数据质量明细失败"));
    }
    store.dataQuality = data;
    return true;
  } catch (error) {
    store.dataError = error instanceof Error ? error.message : "读取数据质量明细失败。";
    return false;
  } finally {
    store.dataQualityBusy = false;
  }
}

export async function loadStrategyCatalog() {
  if (store.strategyCatalogBusy) return false;
  store.strategyCatalogBusy = true;
  store.strategyCatalogError = "";
  try {
    const catalog = await fetchStrategies();
    if (!catalog.response.ok || catalog.data.error) {
      throw new Error(catalog.data.error || `读取策略目录失败（HTTP ${catalog.response.status}）。`);
    }
    store.strategies = catalog.data.items || [];
    const strategyId = store.selectedStrategy?.id || store.strategies[0]?.id;
    if (!strategyId) {
      store.selectedStrategy = null;
      return true;
    }
    const detail = await fetchStrategy(strategyId);
    if (!detail.response.ok || detail.data.error) {
      throw new Error(detail.data.error || `读取策略定义失败（HTTP ${detail.response.status}）。`);
    }
    store.selectedStrategy = detail.data;
    return true;
  } catch (error) {
    store.strategyCatalogError = error instanceof Error ? error.message : "读取策略目录失败。";
    return false;
  } finally {
    store.strategyCatalogBusy = false;
  }
}

export async function loadLiveExecutionReports(limit = 50) {
  if (store.liveExecutionReportsBusy) return false;
  store.liveExecutionReportsBusy = true;
  store.liveExecutionReportsError = "";
  try {
    const { response, data } = await fetchLiveExecutionReports(limit);
    if (!response.ok || data.error) {
      throw new Error(data.error || `读取执行报告失败（HTTP ${response.status}）。`);
    }
    store.liveExecutionReports = data.items || [];
    return true;
  } catch (error) {
    store.liveExecutionReportsError = error instanceof Error ? error.message : "读取执行报告失败。";
    return false;
  } finally {
    store.liveExecutionReportsBusy = false;
  }
}

export async function selectResearchCandidate(candidateId) {
  store.researchResultBusy = true;
  store.researchError = "";
  try {
    const { response, data } = await fetchResearchCandidate(candidateId);
    if (!response.ok || data.error) {
      throw new Error(researchErrorMessage(response, data, "读取候选明细失败"));
    }
    store.researchCandidate = data;
    const resultId = data.results?.find((item) => item.available)?.id || "";
    if (resultId) return selectResearchResult(resultId);
    store.researchResult = null;
    return true;
  } catch (error) {
    store.researchError = error instanceof Error ? error.message : "读取候选明细失败。";
    return false;
  } finally {
    store.researchResultBusy = false;
  }
}

export async function selectResearchResult(resultId) {
  store.researchResultBusy = true;
  store.researchError = "";
  try {
    const { response, data } = await fetchResearchResult(resultId);
    if (!response.ok || data.error) {
      throw new Error(researchErrorMessage(response, data, "读取研究结果失败"));
    }
    store.researchResult = data;
    return true;
  } catch (error) {
    store.researchError = error instanceof Error ? error.message : "读取研究结果失败。";
    return false;
  } finally {
    store.researchResultBusy = false;
  }
}

export async function createResearchCandidate(payload) {
  if (store.researchWorkflowBusy) return null;
  store.researchWorkflowBusy = true;
  store.researchError = "";
  try {
    const { response, data } = await createResearchCandidateRequest(payload);
    if (!response.ok || data.error) {
      throw new Error(researchErrorMessage(response, data, "冻结研究候选失败"));
    }
    await loadResearchCatalog();
    await selectResearchCandidate(data.id);
    return data;
  } catch (error) {
    store.researchError = error instanceof Error ? error.message : "冻结研究候选失败。";
    return null;
  } finally {
    store.researchWorkflowBusy = false;
  }
}

export async function startResearchRun(candidateId, openLockbox = false) {
  if (store.researchWorkflowBusy) return null;
  store.researchWorkflowBusy = true;
  store.researchError = "";
  try {
    const { response, data } = await createResearchRunRequest({
      candidate_id: candidateId,
      open_lockbox: openLockbox,
    });
    if (!response.ok || data.error) {
      throw new Error(researchErrorMessage(response, data, "启动研究任务失败"));
    }
    store.researchRuns = [data, ...store.researchRuns.filter((item) => item.id !== data.id)];
    return data;
  } catch (error) {
    store.researchError = error instanceof Error ? error.message : "启动研究任务失败。";
    return null;
  } finally {
    store.researchWorkflowBusy = false;
  }
}

export async function startR0Run(phase, confirmation = "") {
  if (store.researchWorkflowBusy) return null;
  store.researchWorkflowBusy = true;
  store.researchError = "";
  try {
    const { response, data } = await createR0RunRequest({ phase, confirmation });
    if (!response.ok || data.error) {
      throw new Error(researchErrorMessage(response, data, "启动短线筛查任务失败"));
    }
    store.researchRuns = [data, ...store.researchRuns.filter((item) => item.id !== data.id)];
    return data;
  } catch (error) {
    store.researchError = error instanceof Error ? error.message : "启动短线筛查任务失败。";
    return null;
  } finally {
    store.researchWorkflowBusy = false;
  }
}

export async function refreshR0Status() {
  const { response, data } = await fetchR0Status();
  if (!response.ok || data.error) {
    store.researchError = researchErrorMessage(response, data, "读取短线筛查状态失败");
    return null;
  }
  store.r0Status = data;
  return data;
}

export async function loadR0Gallery() {
  const { response, data } = await fetchR0Gallery();
  if (!response.ok || data.error) {
    store.researchError = researchErrorMessage(response, data, "读取信号图库失败");
    return null;
  }
  store.r0Gallery = data;
  return data;
}

export async function loadR0GallerySamples(parameterId, filters = {}) {
  if (store.r0GalleryBusy) return null;
  store.r0GalleryBusy = true;
  try {
    const { response, data } = await fetchR0GallerySamples(parameterId, filters);
    if (!response.ok || data.error) {
      throw new Error(researchErrorMessage(response, data, "读取信号样本失败"));
    }
    store.r0GallerySamples[parameterId] = data;
    return data;
  } catch (error) {
    store.researchError = error instanceof Error ? error.message : "读取信号样本失败。";
    return null;
  } finally {
    store.r0GalleryBusy = false;
  }
}

export async function startResearchDatasetFetch(payload) {
  if (store.researchWorkflowBusy) return null;
  store.researchWorkflowBusy = true;
  store.dataError = "";
  try {
    const { response, data } = await createResearchDatasetFetchRequest(payload);
    if (!response.ok || data.error) {
      throw new Error(researchErrorMessage(response, data, "启动数据拉取失败"));
    }
    store.researchRuns = [data, ...store.researchRuns.filter((item) => item.id !== data.id)];
    return data;
  } catch (error) {
    store.dataError = error instanceof Error ? error.message : "启动数据拉取失败。";
    return null;
  } finally {
    store.researchWorkflowBusy = false;
  }
}

export async function startShortlineDatasetBuild(payload) {
  if (store.researchWorkflowBusy) return null;
  store.researchWorkflowBusy = true;
  store.dataError = "";
  try {
    const { response, data } = await createShortlineDatasetRequest(payload);
    if (!response.ok || data.error) {
      throw new Error(researchErrorMessage(response, data, "启动全市场数据任务失败"));
    }
    store.researchRuns = [data, ...store.researchRuns.filter((item) => item.id !== data.id)];
    return data;
  } catch (error) {
    store.dataError = error instanceof Error ? error.message : "启动全市场数据任务失败。";
    return null;
  } finally {
    store.researchWorkflowBusy = false;
  }
}

export async function cancelResearchRun(runId) {
  if (store.researchWorkflowBusy) return null;
  store.researchWorkflowBusy = true;
  const existing = store.researchRuns.find((item) => item.id === runId);
  const errorKey = ["dataset_fetch", "shortline_dataset"].includes(existing?.job_type)
    ? "dataError" : "researchError";
  store[errorKey] = "";
  try {
    const { response, data } = await cancelResearchRunRequest(runId);
    if (!response.ok || data.error) {
      throw new Error(researchErrorMessage(response, data, "停止数据任务失败"));
    }
    store.researchRuns = [data, ...store.researchRuns.filter((item) => item.id !== data.id)];
    return data;
  } catch (error) {
    store[errorKey] = error instanceof Error ? error.message : "停止任务失败。";
    return null;
  } finally {
    store.researchWorkflowBusy = false;
  }
}

export async function refreshResearchRun(runId) {
  const { response, data } = await fetchResearchRun(runId);
  // A run may retain its last domain error while a resumable data task is
  // running again. Only an error-shaped API response should become a page
  // error; the run's own error remains visible in its task-history row.
  if (!response.ok || (data.error && !data.id)) {
    const existing = store.researchRuns.find((item) => item.id === runId);
    const errorKey = ["dataset_fetch", "shortline_dataset"].includes(existing?.job_type)
      ? "dataError" : "researchError";
    store[errorKey] = researchErrorMessage(response, data, "读取研究任务失败");
    return null;
  }
  store.researchRuns = [data, ...store.researchRuns.filter((item) => item.id !== data.id)];
  if (["succeeded", "failed", "cancelled"].includes(data.status)) {
    if (["dataset_fetch", "shortline_dataset"].includes(data.job_type)) await loadDataCatalog();
    else await loadResearchCatalog();
  }
  return data;
}

export async function post(path, payload = {}) {
  let response;
  let data;
  try {
    ({ response, data } = await postJson(path, payload));
  } catch (error) {
    alert(error instanceof Error ? error.message : "操作请求失败。");
    return null;
  }
  store.state = data;
  if (response.status === 401) {
    store.loginError = data.error || "请先登录。";
    return null;
  }
  if (!response.ok) {
    alert(data.error || "操作失败。");
    await loadState();
    return null;
  }
  return data;
}

export async function login(loginId, password) {
  store.loginBusy = true;
  store.loginError = "";
  store.stateError = "";
  try {
    const { response, data } = await loginRequest(loginId, password);
    if (!response.ok || !data.ok) {
      store.loginError = data.error || "登录失败。";
      return false;
    }
    const authenticated = await loadState();
    if (!authenticated) {
      store.loginError = "凭证已验证，但服务未能建立有效会话。请联系管理员检查用户目录。";
      return false;
    }
    return true;
  } catch (error) {
    store.loginError = error instanceof Error ? error.message : "登录请求失败，请确认本地服务正在运行。";
    return false;
  } finally {
    store.loginBusy = false;
  }
}

export async function logout() {
  await logoutRequest();
  store.state = null;
  store.researchDatasets = [];
  store.researchCandidates = [];
  store.researchCandidate = null;
  store.researchResult = null;
  store.researchTemplates = [];
  store.researchRuns = [];
  store.dataCatalogLoadedAt = "";
  store.dataSummary = null;
  store.dataQuality = null;
  store.liveExecutionReports = [];
  store.liveExecutionReportsError = "";
  store.signalDesk = null;
  store.signalDeskError = "";
}

export async function tick() {
  return post("/api/tick");
}

export async function toggleRunning() {
  return post("/api/toggle", { running: !store.state?.running });
}

export async function resetRuntime() {
  if (confirm("确认重置 dry_run 状态？")) {
    return post("/api/reset");
  }
  return null;
}

export async function generateReport() {
  return post("/api/report/daily");
}

export async function emergencyStop() {
  if (confirm("确认触发全局急停？dry_run 策略会立即暂停，账户状态会标记为管理员暂停。")) {
    return post("/api/admin/emergency-stop");
  }
  return null;
}

export async function resumeSystem() {
  return post("/api/admin/resume");
}

export async function resumeStoppedSymbol(accountId, symbol, reason) {
  const targetId = `${accountId}::${symbol}`;
  if (store.recoveringStoppedSymbolId) return false;
  store.recoveringStoppedSymbolId = targetId;
  try {
    const { response, data } = await resumeStoppedSymbolRequest(accountId, symbol, reason);
    if (!response.ok || data.ok === false || data.error) {
      alert(data.error || "复核恢复失败。");
      await loadState();
      return false;
    }
    store.state = data;
    return true;
  } catch (error) {
    alert(error instanceof Error ? error.message : "复核恢复请求失败。");
    return false;
  } finally {
    store.recoveringStoppedSymbolId = "";
  }
}

export async function saveBusinessUser(payload) {
  return post("/api/users/upsert", payload);
}

export async function saveExchangeAccount(payload) {
  return post("/api/accounts/upsert", payload);
}

export async function saveBinanceCredentials(accountId, apiKey, apiSecret) {
  return post("/api/binance/credentials", {
    account_id: accountId,
    api_key: apiKey,
    api_secret: apiSecret,
  });
}

export async function syncBinanceAccount(accountId) {
  return post("/api/binance/sync", { account_id: accountId });
}

export async function syncAllAccounts() {
  if (store.syncAllBusy) return;
  store.syncAllBusy = true;
  try {
    for (const account of exchangeAccounts.value) {
      // 顺序同步，避免并发打爆 Binance 限频；单账户失败不阻断后续
      await post("/api/binance/sync", { account_id: account.id });
    }
  } finally {
    store.syncAllBusy = false;
  }
}

export async function generateExecutionPlans(accountId = "") {
  await post("/api/execution-plans/generate", accountId ? { account_id: accountId } : {});
  setActivePage("plans");
}

export async function confirmExecutionPlan(planId) {
  const note = prompt("确认该计划已人工核对。当前阶段只记录确认，不会下单。", "人工核对通过");
  if (note === null) return null;
  return post("/api/execution-plans/confirm", { plan_id: planId, note });
}

export async function exportExecutionPlans(planIds, scope = "all") {
  const updated = await post("/api/execution-plans/export", { plan_ids: planIds });
  if (!updated) return null;
  const auditedPlans = executionPlans.value.filter((plan) => planIds.includes(plan.id));
  const payload = {
    exported_at: updated.execution_plan_export_result?.exported_at,
    export_id: updated.execution_plan_export_result?.export_id,
    plans: auditedPlans,
  };
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  link.href = url;
  link.download = `orbit-execution-plans-${scope || "all"}-${stamp}.json`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
  return updated;
}
