async function readJson(response) {
  const text = await response.text();
  if (!text.trim()) {
    return {
      error: `服务没有返回 JSON（HTTP ${response.status}）。请确认 8765 后端服务已经启动。`,
    };
  }
  try {
    return JSON.parse(text);
  } catch {
    return {
      error: `服务返回了非 JSON 响应（HTTP ${response.status}）。请确认 8765 后端服务已经启动。`,
    };
  }
}

export async function fetchAppState() {
  const response = await fetch("/api/state", {
    headers: { Accept: "application/json" },
  });
  const data = await readJson(response);
  if (!response.ok || data.error) {
    return {
      __error: data.error || `读取系统状态失败（HTTP ${response.status}）。`,
    };
  }
  return data;
}

export async function getJson(path) {
  const response = await fetch(path, {
    headers: { Accept: "application/json" },
  });
  const data = await readJson(response);
  return { response, data };
}

export function fetchResearchDatasets() {
  return getJson("/api/research/datasets");
}

export function fetchResearchCandidates() {
  return getJson("/api/research/candidates");
}

export function fetchResearchCandidate(candidateId) {
  return getJson(`/api/research/candidates/${encodeURIComponent(candidateId)}`);
}

export function fetchResearchResult(resultId) {
  return getJson(`/api/research/results/${encodeURIComponent(resultId)}`);
}

export function fetchResearchTemplates() {
  return getJson("/api/research/templates");
}

export function fetchResearchRuns() {
  return getJson("/api/research/runs");
}

export function fetchResearchRun(runId) {
  return getJson(`/api/research/runs/${encodeURIComponent(runId)}`);
}

export function fetchR0Status() {
  return getJson("/api/research/r0");
}

export function fetchR0Gallery() {
  return getJson("/api/research/r0/gallery");
}

export function fetchR0GallerySamples(parameterId, filters = {}) {
  const query = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => {
    if (value !== "" && value !== null && value !== undefined) query.set(key, value);
  });
  return getJson(`/api/research/r0/gallery/${encodeURIComponent(parameterId)}/samples?${query}`);
}

export function fetchDataSummary() {
  return getJson("/api/data/summary");
}
export function fetchCurrentMarkets(refresh = false) { return getJson(`/api/data/markets?refresh=${refresh ? "true" : "false"}`); }

export function fetchDataQuality(kind = "halts", page = 1, pageSize = 50) {
  return getJson(
    `/api/data/quality?kind=${encodeURIComponent(kind)}&page=${encodeURIComponent(page)}&page_size=${encodeURIComponent(pageSize)}`,
  );
}
export function fetchMessages() { return getJson("/api/messages?limit=100"); }
export function readMessageRequest(id) { return postJson(`/api/messages/${encodeURIComponent(id)}/read`); }
export function readAllMessagesRequest() { return postJson("/api/messages/read-all"); }

export function fetchStrategies() {
  return getJson("/api/strategies");
}

export function fetchStrategy(strategyId) {
  return getJson(`/api/strategies/${encodeURIComponent(strategyId)}`);
}

export function fetchLiveExecutionReports(limit = 50) {
  return getJson(`/api/live-execution/reports?limit=${encodeURIComponent(limit)}`);
}

export function fetchSignalDesk(day = "", limit = 200) {
  const query = new URLSearchParams({ limit: String(limit) });
  if (day) query.set("day", day);
  return getJson(`/api/signals?${query}`);
}

export function recordSignalDecisionRequest(payload) {
  return postJson("/api/signals/decisions", payload);
}

export function recordSignalExecutionRequest(payload) {
  return postJson("/api/signals/executions", payload);
}

export function configureSignalPushoverRequest(payload) { return postJson("/api/signals/pushover", payload); }
export function testSignalPushoverRequest() { return postJson("/api/signals/pushover/test"); }
export function controlSignalServiceRequest(enabled) { return postJson("/api/signals/service", { enabled }); }
export function controlSignalFamilyRequest(familyId, enabled, reason) { return postJson("/api/signals/families/control", { family_id: familyId, enabled, reason }); }
export function bindSignalAccountRequest(accountId) { return postJson("/api/signals/binding", { account_id: accountId || null }); }

export async function postJson(path, payload = {}) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await readJson(response);
  return { response, data };
}

export function createResearchCandidateRequest(payload) {
  return postJson("/api/research/candidates", payload);
}

export function createResearchRunRequest(payload) {
  return postJson("/api/research/runs", payload);
}

export function createR0RunRequest(payload) {
  return postJson("/api/research/r0/runs", payload);
}

export function createResearchDatasetFetchRequest(payload) {
  return postJson("/api/research/datasets/fetch", payload);
}

export function createShortlineDatasetRequest(payload) {
  return postJson("/api/research/datasets/shortline", payload);
}

export function cancelResearchRunRequest(runId) {
  return postJson(`/api/research/runs/${encodeURIComponent(runId)}/cancel`);
}

export function resumeStoppedSymbolRequest(accountId, symbol, reason) {
  return postJson("/api/admin/stopped-symbols/resume", {
    account_id: accountId,
    symbol,
    reason,
  });
}

export async function loginRequest(login, password) {
  const response = await fetch("/api/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ login, password }),
  });
  const data = await readJson(response);
  return { response, data };
}

export async function logoutRequest() {
  await fetch("/api/logout", { method: "POST" });
}
