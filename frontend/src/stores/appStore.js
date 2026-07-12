import { computed, reactive } from "vue";
import { fetchAppState, loginRequest, logoutRequest, postJson } from "../api/client.js";

export const store = reactive({
  state: null,
  activePage: location.hash.replace("#", "") || "dashboard",
  selectedSymbol: "",
  selectedPlanAccount: "",
  loginBusy: false,
  loginError: "",
  stateError: "",
});

export const isAuthenticated = computed(() => Boolean(store.state?.auth?.authenticated));
export const currentUser = computed(() => store.state?.auth?.current_user || null);
export const isAdmin = computed(() => ["admin", "super_admin"].includes(currentUser.value?.role));
export const symbols = computed(() => store.state?.symbols || []);
export const accounts = computed(() => store.state?.admin_overview?.accounts || []);
export const users = computed(() => store.state?.admin_overview?.users || []);
export const executionPlans = computed(() => store.state?.execution_plans || []);

export function currentSymbol() {
  return symbols.value.find((item) => item.symbol === store.selectedSymbol) || symbols.value[0] || null;
}

export function setActivePage(page) {
  store.activePage = page;
  if (location.hash !== `#${page}`) {
    history.replaceState(null, "", `#${page}`);
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
    return loadState();
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

export async function saveEventConfig(eventConfig) {
  return post("/api/config/events", { event_config: eventConfig });
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
