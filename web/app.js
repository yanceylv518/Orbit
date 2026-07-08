let state = null;
let selectedSymbol = "";
let activePage = "dashboard";
let selectedPlanAccount = "";

const $ = (id) => document.getElementById(id);

function esc(value = "") {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "\"": "&quot;",
    "'": "&#039;",
  }[char]));
}

function jsArg(value = "") {
  return JSON.stringify(String(value ?? ""));
}

const PAGE_META = {
  dashboard: ["总览", "用户总览", "核心资产、系统策略和币种状态。"],
  accounts: ["交易账户", "用户与账户", "业务用户、交易账户和真实账户同步。"],
  events: ["策略事件配置", "策略事件配置", "利润搬运、仓位恢复、亏损腿减仓。"],
  plans: ["执行计划", "第一阶段执行计划", "真实仓位触发判断、计划动作和风控拦截。"],
  symbol: ["币种详情", "币种详情 / 事件时间线", "单币种多空仓位、权益曲线和事件时间线。"],
  risk: ["风控中心", "管理员风控中心", "运行概览、风险告警、审计日志和快捷操作。"],
  reports: ["报表中心", "每日复盘报告", "Markdown 日报和 SVG 曲线图。"],
  logs: ["事件日志", "策略事件日志", "父事件、子成交和执行原因。"],
};

function fmt(n, digits = 2) {
  return Number(n || 0).toLocaleString("zh-CN", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function cls(n) {
  return Number(n || 0) >= 0 ? "positive" : "negative";
}

function stateLabel(value) {
  const map = {
    REAL_POSITION: "真实持仓",
    BALANCE: "平衡",
    TREND_UP: "趋势上涨",
    TREND_DOWN: "趋势下跌",
    TREND_UP_REDUCING_SHORT: "上涨减空",
    TREND_DOWN_REDUCING_LONG: "下跌减多",
    RECOVERING_FROM_UP: "上涨后恢复",
    RECOVERING_FROM_DOWN: "下跌后恢复",
  };
  return map[value] || value;
}

function eventLabel(value) {
  const map = {
    PROFIT_TRANSFER_UP: "利润搬运（向上）",
    PROFIT_TRANSFER_DOWN: "利润搬运（向下）",
    POSITION_RECOVERY_UP: "仓位恢复（上涨后）",
    POSITION_RECOVERY_DOWN: "仓位恢复（下跌后）",
    LOSS_SIDE_REDUCTION_UP: "亏损腿减仓（空头）",
    LOSS_SIDE_REDUCTION_DOWN: "亏损腿减仓（多头）",
    SYNC_REQUIRED: "等待账户同步",
    HEDGE_MODE_REQUIRED: "Hedge Mode 未通过",
    ACCOUNT_CONFIG_DISABLED: "运行配置未启用",
    NO_REAL_POSITION: "无真实持仓",
    NO_TRIGGER: "未触发",
  };
  return map[value] || value;
}

function statusLabel(value) {
  const map = {
    read_only: "只读",
    active: "正常",
    running: "运行中",
    paused: "已暂停",
    paused_by_admin: "管理员暂停",
    emergency_stopped: "急停中",
    unassigned: "未分配",
    disabled: "已禁用",
    synced: "已同步",
    unsynced: "未同步",
    missing_credentials: "未配置凭证",
    error: "同步失败",
    plan_only: "计划演练",
    planned: "已生成",
    blocked: "已拦截",
    no_action: "无动作",
    confirmed: "已确认",
  };
  return map[value] || value || "-";
}

function statusColor(value) {
  if (["active", "running"].includes(value)) return "green";
  if (["emergency_stopped", "disabled"].includes(value)) return "red";
  if (["paused", "paused_by_admin"].includes(value)) return "orange";
  return "blue";
}

function statusBadge(value) {
  return badge(statusLabel(value), statusColor(value));
}

function modeLabel(value) {
  const map = {
    dry_run: "只读",
    read_only: "只读",
    testnet: "测试网",
    live: "实盘",
  };
  return map[value] || value || "-";
}

function accountModeBadge(account) {
  if (account.dry_run) return badge("只读", "blue");
  if (account.testnet) return badge("测试网", "orange");
  return badge("实盘", "red");
}

function planStatusBadge(value) {
  const color = value === "planned" ? "green" : (value === "blocked" ? "orange" : "blue");
  return badge(statusLabel(value), color);
}

function badge(text, type = "blue") {
  return `<span class="badge ${type}">${text}</span>`;
}

function boolText(value) {
  return value ? "是" : "否";
}

function summaryItem(label, value, note = "") {
  return `
    <div class="summary-item">
      <span>${label}</span>
      <strong>${value}</strong>
      ${note ? `<small>${note}</small>` : ""}
    </div>
  `;
}

function metricTile(label, value, note = "", valueClass = "") {
  return `
    <article class="metric-card">
      <span>${label}</span>
      <strong class="${valueClass}">${value}</strong>
      <small>${note}</small>
    </article>
  `;
}

function emptyRow(colspan, text) {
  return `<tr><td colspan="${colspan}" class="muted">${text}</td></tr>`;
}

function currentUserIsAdmin() {
  const role = state?.auth?.current_user?.role;
  return role === "admin" || role === "super_admin";
}

function visibleBusinessUsers() {
  return state?.admin_overview?.users || [];
}

function overviewAccounts() {
  return state?.admin_overview?.accounts || [];
}

function accountSnapshot(accountId) {
  return (state?.binance_account_snapshots || {})[accountId] || {};
}

function clearEditor(id) {
  const el = $(id);
  el.innerHTML = "";
  el.classList.add("hidden");
}

async function fetchState() {
  const res = await fetch("/api/state");
  state = await res.json();
  if (!state.auth?.authenticated) {
    showLogin();
    return false;
  }
  hideLogin();
  if (isCredentialInputFocused()) {
    return true;
  }
  if (!state.symbols.find((s) => s.symbol === selectedSymbol)) {
    selectedSymbol = state.symbols[0]?.symbol || "";
  }
  render();
  return true;
}

async function post(path, payload = {}) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (res.status === 401) {
    state = await res.json();
    showLogin(state.error || "请先登录。", true);
    return;
  }
  if (!res.ok) {
    const payload = await res.json();
    alert(payload.error || "操作失败。");
    await fetchState();
    return null;
  }
  state = await res.json();
  if (!state.auth?.authenticated) {
    showLogin("", true);
    return null;
  }
  hideLogin();
  render();
  return state;
}

async function login(login, password) {
  setLoginBusy(true, "登录中...");
  try {
    const res = await fetch("/api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ login, password }),
    });
    const payload = await res.json();
    if (!res.ok || !payload.ok) {
      showLogin(payload.error || "登录失败。", true);
      return;
    }
    setLoginBusy(true, "加载控制台...");
    hideLogin();
    const loaded = await fetchState();
    if (!loaded) {
      showLogin("登录状态未生效，请重试。", true);
    }
  } catch (error) {
    showLogin("登录请求失败，请确认本地服务正在运行。");
  } finally {
    setLoginBusy(false);
  }
}

async function logout() {
  await fetch("/api/logout", { method: "POST" });
  state = null;
  showLogin("", true);
}

async function syncBinanceAccount(accountId) {
  await post("/api/binance/sync", { account_id: accountId });
  activatePage("accounts");
}

async function saveBinanceCredentials(accountId) {
  const safeId = safeDomId(accountId);
  const apiKey = $(`apiKey-${safeId}`).value.trim();
  const apiSecret = $(`apiSecret-${safeId}`).value.trim();
  if (!apiKey || !apiSecret) {
    alert("请填写 Binance API Key 和 Secret。");
    return;
  }
  await post("/api/binance/credentials", {
    account_id: accountId,
    api_key: apiKey,
    api_secret: apiSecret,
  });
  activatePage("accounts");
}

async function generateExecutionPlans(accountId = "") {
  await post("/api/execution-plans/generate", accountId ? { account_id: accountId } : {});
  activatePage("plans");
}

async function confirmExecutionPlan(planId) {
  const plan = (state.execution_plans || []).find((item) => item.id === planId);
  if (!plan) return;
  const note = prompt("确认该计划已人工核对。当前阶段只记录确认，不会下单。", "人工核对通过");
  if (note === null) return;
  await post("/api/execution-plans/confirm", { plan_id: planId, note });
  activatePage("plans");
}

async function recordExecutionPlanExport(planIds) {
  const updated = await post("/api/execution-plans/export", { plan_ids: planIds });
  return updated?.execution_plan_export_result || null;
}

async function saveBusinessUser() {
  await post("/api/users/upsert", {
    user_id: $("userFormId").value.trim(),
    name: $("userFormName").value.trim(),
    email: $("userFormEmail").value.trim(),
    status: $("userFormStatus").value,
  });
  clearEditor("userEditor");
  activatePage("accounts");
}

async function saveExchangeAccount() {
  await post("/api/accounts/upsert", {
    account_id: $("accountFormId").value.trim(),
    user_id: $("accountFormUser").value,
    account_label: $("accountFormLabel").value.trim(),
    status: $("accountFormStatus").value,
    testnet: $("accountFormTestnet").checked,
    dry_run: $("accountFormDryRun").checked,
    hedge_mode_required: $("accountFormHedge").checked,
  });
  clearEditor("accountEditor");
  activatePage("accounts");
}

function safeDomId(value) {
  return String(value).replace(/[^a-zA-Z0-9_-]/g, "_");
}

function showLogin(message = "", clearPassword = false) {
  const wasActive = $("loginScreen").classList.contains("active");
  document.body.classList.add("auth-locked");
  $("loginScreen").classList.add("active");
  if (message || clearPassword || !wasActive) {
    $("loginError").textContent = message;
  }
  if (clearPassword || !wasActive) {
    $("loginPassword").value = "";
  }
}

function hideLogin() {
  document.body.classList.remove("auth-locked");
  $("loginScreen").classList.remove("active");
  $("loginError").textContent = "";
}

function setLoginBusy(busy, text = "登录") {
  const button = $("loginSubmit");
  button.disabled = busy;
  button.textContent = busy ? text : "登录";
  $("loginId").disabled = busy;
  $("loginPassword").disabled = busy;
}

function activatePage(page) {
  if (!PAGE_META[page]) return;
  activePage = page;
  document.querySelectorAll("[data-page-panel]").forEach((panel) => {
    panel.classList.toggle("active", panel.dataset.pagePanel === page);
  });
  document.querySelectorAll("[data-nav-page]").forEach((item) => {
    item.classList.toggle("active", item.dataset.navPage === page);
  });
  const [kicker, title, desc] = PAGE_META[page];
  $("pageKicker").textContent = kicker;
  $("pageTitle").textContent = title;
  $("pageDesc").textContent = desc;
  if (location.hash !== `#${page}`) {
    history.replaceState(null, "", `#${page}`);
  }
  if (state && page === "symbol") renderSymbolDetail();
}

function render() {
  renderTop();
  renderDashboard();
  renderAccounts();
  renderPlans();
  renderEventConfig();
  renderSymbolDetail();
  renderRisk();
  renderReports();
  renderEventLog();
}

function renderTop() {
  const readOnlyMode = state.strategy.mode === "read_only";
  const loginRequired = state.auth?.login_required !== false;
  $("serverTime").textContent = `Tick ${state.tick_index} / ${state.server_time}`;
  $("toggleBtn").textContent = readOnlyMode ? "只读模式" : (state.running ? "暂停" : "启动");
  $("toggleBtn").disabled = readOnlyMode;
  $("tickBtn").disabled = readOnlyMode;
  $("resetBtn").disabled = readOnlyMode;
  $("runStatus").textContent = statusLabel(state.strategy.status);
  const currentUser = state.auth?.current_user;
  $("currentUser").textContent = currentUser ? `${currentUser.name} / ${currentUser.role}` : "-";
  $("sidebarMode").textContent = `${modeLabel(state.strategy.mode)} · ${statusLabel(state.strategy.status)}`;
  $("logoutBtn").style.display = loginRequired ? "" : "none";
  $("sidebarLogoutBtn").style.display = loginRequired ? "" : "none";
  $("switchUserBtn").style.display = loginRequired ? "" : "none";
}

function renderDashboard() {
  const strategy = state.strategy;
  const overview = state.admin_overview || { accounts: [], users: [] };
  const lastBySymbol = latestEventsBySymbol();
  const sourceLabel = state.storage.driver === "mysql" ? "MySQL / Binance" : "JSON fallback";

  $("totalEquity").textContent = fmt(strategy.total_equity);
  $("todayPnl").innerHTML = `<span class="${cls(strategy.today_pnl)}">${fmt(strategy.today_pnl)}</span>`;
  $("todayPnlPct").textContent = `${fmt(strategy.today_pnl_pct, 3)}%`;
  $("runMode").textContent = modeLabel(strategy.mode);
  $("riskStatus").innerHTML = strategy.risk_status === "normal" ? badge("正常", "green") : badge("关注", "orange");
  $("storageStatus").textContent = state.storage.driver === "mysql" ? "MySQL" : "JSON fallback";
  $("dashboardTick").textContent = `Tick ${state.tick_index}`;

  $("dashboardStrategyRows").innerHTML = `
    <tr>
      <td><strong>${esc(strategy.name)} ${esc(strategy.version)}</strong><div class="muted">${esc(strategy.id || "system")}</div></td>
      <td>${modeLabel(strategy.mode)}</td>
      <td>${statusBadge(strategy.status)}</td>
      <td>${strategy.symbol_count}</td>
      <td class="${cls(strategy.today_pnl)}">${fmt(strategy.today_pnl)} USDT</td>
      <td>${fmt(strategy.total_equity)} USDT</td>
      <td>${sourceLabel}</td>
      <td><button class="button ghost small" onclick="activatePage('events')">查看</button></td>
    </tr>
  `;

  $("dashboardSymbolBrief").innerHTML = state.symbols.length ? state.symbols.map((s) => `
    <tr>
      <td><button class="tab ${selectedSymbol === s.symbol ? "active" : ""}" onclick="selectSymbol('${s.symbol}', true)">${s.symbol}</button></td>
      <td>${badge(stateLabel(s.state), stateColor(s.state))}</td>
      <td>${fmt(s.price, s.symbol === "SOLUSDT" ? 3 : 2)}</td>
      <td>${fmt(s.long_qty, 6)}</td>
      <td>${fmt(s.short_qty, 6)}</td>
      <td class="${cls(s.unrealized_pnl)}">${fmt(s.unrealized_pnl)} USDT</td>
      <td>${lastBySymbol[s.symbol] ? eventLabel(lastBySymbol[s.symbol].event_type) : "无"}</td>
      <td>${s.updated_at || state.server_time}</td>
    </tr>
  `).join("") : emptyRow(8, "暂无真实仓位。请在交易账户页同步 Binance 后查看。");
}

function renderAccounts() {
  if (isCredentialInputFocused() || isInlineEditorFocused()) return;
  const overview = state.admin_overview || { users: [], accounts: [] };
  const exchangeById = Object.fromEntries((state.exchange_accounts || []).map((account) => [account.id, account]));
  const snapshots = state.binance_account_snapshots || {};
  const canManage = currentUserIsAdmin();

  $("newUserBtn").style.display = canManage ? "" : "none";
  $("newAccountBtn").style.display = canManage ? "" : "none";

  $("userRows").innerHTML = overview.users.length ? overview.users.map((user) => `
    <tr>
      <td><strong>${esc(user.user_name)}</strong><div class="muted">${esc(user.user_id)} · ${esc(user.role)}</div></td>
      <td>${statusBadge(user.status)}</td>
      <td>${user.account_count}</td>
      <td>${fmt(user.total_equity)} USDT</td>
      <td class="${cls(user.today_pnl)}">${fmt(user.today_pnl)} USDT</td>
      <td>${user.risk_status === "normal" ? badge("正常", "green") : badge("关注", "orange")}</td>
      <td>${canManage ? `<button class="button ghost small" onclick="openUserEditor(${jsArg(user.user_id)})">编辑</button>` : `<span class="muted">-</span>`}</td>
    </tr>
  `).join("") : emptyRow(7, "暂无业务用户。");

  $("accountRows").innerHTML = overview.accounts.length ? overview.accounts.map((row) => {
    const account = exchangeById[row.account_id] || {};
    const snapshot = snapshots[row.account_id] || {};
    const positionMode = snapshot.position_mode || {};
    const safeId = safeDomId(row.account_id);
    const credentialConfigured = account.api_key_configured && account.secret_configured;
    const credentialUsable = account.api_key_present && account.secret_present;
    const credentialBadge = credentialUsable
      ? badge("API 可用", "green")
      : (credentialConfigured ? badge("API 已保存", "orange") : badge("API 未配置", "orange"));
    const syncStatus = snapshot.status || (credentialConfigured ? "unsynced" : "missing_credentials");
    const currentUser = state.auth?.current_user || {};
    const canOperate = currentUserIsAdmin() || row.user_id === currentUser.id;
    const hedgeHtml = positionMode.hedge_mode_ok === undefined
      ? (row.hedge_mode_required ? badge("需双向", "blue") : "-")
      : (positionMode.hedge_mode_ok ? badge("通过", "green") : badge("未通过", "orange"));
    const apiActions = canOperate ? `
      <div class="account-api-fields">
        <input id="apiKey-${safeId}" type="password" autocomplete="off" placeholder="API Key" />
        <input id="apiSecret-${safeId}" type="password" autocomplete="off" placeholder="Secret" />
        <button class="button small" onclick="saveBinanceCredentials('${row.account_id}')">保存</button>
        <button class="button ghost small" onclick="syncBinanceAccount('${row.account_id}')">同步</button>
      </div>
    ` : `<span class="muted">无操作权限</span>`;
    return `
      <tr>
        <td>
          <strong>${esc(row.account_label)}</strong>
          <div class="account-meta-line">
            <span>${esc(row.account_id)}</span>
            <span>${esc(row.exchange)} / ${esc(row.market_type)}</span>
            ${accountModeBadge(row)}
            ${hedgeHtml}
          </div>
        </td>
        <td><strong>${esc(row.user_name)}</strong><div class="muted">${esc(row.user_id)}</div></td>
        <td>${statusBadge(row.account_status)}</td>
        <td>
          <div class="account-inline-actions">
            <div>
              ${credentialBadge}
              <span class="muted">${statusLabel(syncStatus)}${account.api_key_fingerprint ? ` · ${esc(account.api_key_fingerprint)}` : ""}${snapshot.synced_at ? ` · ${esc(snapshot.synced_at)}` : ""}</span>
              ${account.credential_error ? `<div class="sync-error compact">${esc(account.credential_error)}</div>` : ""}
              ${snapshot.error ? `<div class="sync-error compact">${esc(snapshot.error)}</div>` : ""}
            </div>
            ${apiActions}
          </div>
        </td>
        <td><strong>${fmt(row.total_equity)} USDT</strong><div class="${cls(row.today_pnl)}">今日 ${fmt(row.today_pnl)} USDT</div></td>
        <td>${canManage ? `<button class="button ghost small" onclick="openAccountEditor(${jsArg(row.account_id)})">编辑</button>` : `<span class="muted">-</span>`}</td>
      </tr>
    `;
  }).join("") : emptyRow(6, "暂无交易账户。");
}

function openUserEditor(userId = "") {
  const user = visibleBusinessUsers().find((item) => item.user_id === userId);
  const editing = Boolean(user);
  $("userEditor").classList.remove("hidden");
  $("userEditor").innerHTML = `
    <h4>${editing ? "编辑业务用户" : "新增业务用户"}</h4>
    <div class="inline-editor-form">
      <div class="editor-grid">
        <label>
          <span>用户 ID</span>
          <input id="userFormId" value="${esc(user?.user_id || "")}" placeholder="user_002" ${editing ? "readonly" : ""} />
        </label>
        <label>
          <span>显示名称</span>
          <input id="userFormName" value="${esc(user?.user_name || "")}" placeholder="业务用户名称" />
        </label>
        <label>
          <span>邮箱</span>
          <input id="userFormEmail" value="${esc(user?.email || "")}" placeholder="可选" />
        </label>
        <label>
          <span>状态</span>
          <select id="userFormStatus">
            ${["active", "paused", "disabled"].map((status) => `
              <option value="${status}" ${status === (user?.status || "active") ? "selected" : ""}>${statusLabel(status)}</option>
            `).join("")}
          </select>
        </label>
      </div>
      <div class="editor-actions">
        <button class="button ghost small" onclick="clearEditor('userEditor')">取消</button>
        <button class="button small" onclick="saveBusinessUser()">保存用户</button>
      </div>
    </div>
  `;
  $(editing ? "userFormName" : "userFormId").focus();
}

function openAccountEditor(accountId = "") {
  const account = (state.exchange_accounts || []).find((item) => item.id === accountId);
  const editing = Boolean(account);
  const users = visibleBusinessUsers();
  if (!users.length) {
    $("accountEditor").classList.remove("hidden");
    $("accountEditor").innerHTML = `<p class="muted">请先新增业务用户，再绑定 Binance 交易账户。</p>`;
    return;
  }
  const status = account?.status || "active";
  $("accountEditor").classList.remove("hidden");
  $("accountEditor").innerHTML = `
    <h4>${editing ? "编辑交易账户" : "新增交易账户"}</h4>
    <div class="inline-editor-form">
      <div class="editor-grid">
        <label>
          <span>账户 ID</span>
          <input id="accountFormId" value="${esc(account?.id || "")}" placeholder="binance_live_001" ${editing ? "readonly" : ""} />
        </label>
        <label>
          <span>所属用户</span>
          <select id="accountFormUser">
            ${users.map((user) => `
              <option value="${esc(user.user_id)}" ${user.user_id === (account?.user_id || users[0]?.user_id) ? "selected" : ""}>${esc(user.user_name)} / ${esc(user.user_id)}</option>
            `).join("")}
          </select>
        </label>
        <label>
          <span>账户名称</span>
          <input id="accountFormLabel" value="${esc(account?.account_label || "")}" placeholder="Binance Futures Read Only" />
        </label>
        <label>
          <span>状态</span>
          <select id="accountFormStatus">
            ${["active", "disabled", "paused_by_admin"].map((item) => `
              <option value="${item}" ${item === status ? "selected" : ""}>${statusLabel(item)}</option>
            `).join("")}
          </select>
        </label>
        <label class="inline-check">
          <input id="accountFormTestnet" type="checkbox" ${account?.testnet ?? true ? "checked" : ""} />
          <span>测试网</span>
        </label>
        <label class="inline-check">
          <input id="accountFormDryRun" type="checkbox" ${account?.dry_run ?? true ? "checked" : ""} />
          <span>只读 / 不下单</span>
        </label>
        <label class="inline-check">
          <input id="accountFormHedge" type="checkbox" ${account?.hedge_mode_required ?? true ? "checked" : ""} />
          <span>要求 Hedge Mode</span>
        </label>
      </div>
      <div class="editor-actions">
        <button class="button ghost small" onclick="clearEditor('accountEditor')">取消</button>
        <button class="button small" onclick="saveExchangeAccount()">保存账户</button>
      </div>
    </div>
  `;
  $(editing ? "accountFormLabel" : "accountFormId").focus();
}

function isCredentialInputFocused() {
  const active = document.activeElement;
  if (!active || !["INPUT", "SELECT", "TEXTAREA"].includes(active.tagName)) return false;
  if (active.closest?.(".account-api-fields")) return true;
  return active.id?.startsWith("apiKey-") || active.id?.startsWith("apiSecret-");
}

function isInlineEditorFocused() {
  const active = document.activeElement;
  return Boolean(active?.closest?.(".inline-editor-form"));
}

function renderPlanControls() {
  const accounts = overviewAccounts();
  const canSelectAll = currentUserIsAdmin();
  const validIds = accounts.map((account) => account.account_id);
  if (selectedPlanAccount && !validIds.includes(selectedPlanAccount)) {
    selectedPlanAccount = "";
  }
  if (!canSelectAll && !selectedPlanAccount && validIds.length) {
    selectedPlanAccount = validIds[0];
  }
  $("planAccountSelect").innerHTML = [
    canSelectAll ? `<option value="">全部可见账户</option>` : "",
    ...accounts.map((account) => `
      <option value="${esc(account.account_id)}">${esc(account.account_label)} / ${esc(account.user_name)}</option>
    `),
  ].join("");
  $("planAccountSelect").value = selectedPlanAccount;
  $("planAccountSelect").disabled = accounts.length <= 1 && !canSelectAll;
}

function filteredExecutionPlans() {
  const plans = state.execution_plans || [];
  return selectedPlanAccount
    ? plans.filter((plan) => plan.account_id === selectedPlanAccount)
    : plans;
}

function riskCheckText(plan) {
  const checks = plan.risk_checks || [];
  return checks.length ? checks.map((check) => `
    ${check.ok ? badge("通过", "green") : badge("拦截", "orange")}
    <span>${esc(check.message || check.name)}</span>
  `).join("<br />") : "-";
}

function planReviewCell(plan) {
  const review = plan.manual_review || {};
  const lastExport = plan.last_export || {};
  const confirmed = review.status === "confirmed";
  const lines = [];
  if (confirmed) {
    lines.push(`${badge("已确认", "green")}<div class="muted">${esc(review.reviewed_at || "-")} / ${esc(review.reviewed_by || "-")}</div>`);
    if (review.note) {
      lines.push(`<div class="muted">${esc(review.note)}</div>`);
    }
  } else if (plan.status === "planned") {
    lines.push(`<button class="button small" onclick="confirmExecutionPlan(${jsArg(plan.id)})">确认</button>`);
  } else {
    lines.push(`<span class="muted">不可确认</span>`);
  }
  if (lastExport.exported_at) {
    lines.push(`<div class="muted">导出：${esc(lastExport.exported_at)}</div>`);
  }
  return `<div class="plan-review">${lines.join("")}</div>`;
}

async function exportExecutionPlans() {
  const plans = filteredExecutionPlans();
  if (!plans.length) {
    alert("当前筛选下没有可导出的执行计划。");
    return;
  }
  const planIds = plans.map((plan) => plan.id);
  const exportAudit = await recordExecutionPlanExport(planIds);
  if (!exportAudit) return;
  const auditedPlans = filteredExecutionPlans().filter((plan) => planIds.includes(plan.id));
  const payload = {
    exported_at: exportAudit.exported_at,
    export_id: exportAudit.export_id,
    account_id: selectedPlanAccount || "ALL_VISIBLE_ACCOUNTS",
    mode: "plan_only",
    note: "第一阶段只读执行计划，不包含下单指令确认；导出动作已写入审计日志。",
    audit: exportAudit,
    plans: auditedPlans,
  };
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  link.href = url;
  link.download = `ddg-execution-plans-${selectedPlanAccount || "all"}-${stamp}.json`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function renderPlans() {
  renderPlanControls();
  const plans = filteredExecutionPlans();
  const accountsById = Object.fromEntries((state.admin_overview?.accounts || []).map((account) => [account.account_id, account]));
  const planned = plans.filter((item) => item.status === "planned").length;
  const blocked = plans.filter((item) => item.status === "blocked").length;
  const noAction = plans.filter((item) => item.status === "no_action").length;
  const confirmed = plans.filter((item) => item.manual_review?.status === "confirmed").length;
  $("exportPlansBtn").disabled = !plans.length;
  $("executionPlanSummary").innerHTML = [
    summaryItem("计划总数", plans.length, "当前可见账户"),
    summaryItem("待演练", planned, "只生成计划，不下单"),
    summaryItem("已确认", confirmed, "人工核对记录"),
    summaryItem("风控拦截", blocked, "需要处理后再演练"),
    summaryItem("无动作", noAction, "未满足触发条件"),
  ].join("");

  $("executionPlanRows").innerHTML = plans.length ? plans.map((plan) => {
    const account = accountsById[plan.account_id] || {};
    const actionText = plan.actions?.length
      ? plan.actions.map((action) => {
        const blockedNote = action.status === "blocked" ? `（拦截：${action.block_reason || "风控"}）` : "";
        return `${esc(action.action)} ${fmt(action.quantity, 6)} / ${fmt(action.notional_usdt)} USDT${esc(blockedNote)}`;
      }).join("<br />")
      : "-";
    return `
      <tr>
        <td>${esc(plan.created_at || "-")}</td>
        <td><strong>${esc(account.account_label || plan.account_id)}</strong><div class="muted">${esc(plan.account_id)}</div></td>
        <td>${esc(plan.symbol)}</td>
        <td>${eventLabel(plan.event_type)}</td>
        <td>${planStatusBadge(plan.status)}</td>
        <td>${actionText}</td>
        <td>${riskCheckText(plan)}</td>
        <td>${planReviewCell(plan)}</td>
        <td>${esc(plan.reason)}</td>
      </tr>
    `;
  }).join("") : emptyRow(9, "暂无执行计划。请先同步账户，然后生成执行计划。");
}

function renderEventConfig() {
  if (document.activeElement?.dataset?.configPath) return;
  const cfg = state.event_config;
  const cards = [
    {
      title: "利润搬运",
      color: "green",
      priority: "优先级 2",
      fields: [
        ["触发利润（资金池%）", "profit_transfer.trigger.min_profit_pct_of_symbol_budget", cfg.profit_transfer.trigger.min_profit_pct_of_symbol_budget],
        ["价格偏离触发", "profit_transfer.trigger.min_price_move_pct_from_base", cfg.profit_transfer.trigger.min_price_move_pct_from_base],
        ["盈利腿减仓比例", "profit_transfer.sizing.reduce_profit_side_ratio", cfg.profit_transfer.sizing.reduce_profit_side_ratio * 100, "percent"],
        ["亏损腿恢复比例", "profit_transfer.sizing.use_realized_profit_ratio_for_loss_side", cfg.profit_transfer.sizing.use_realized_profit_ratio_for_loss_side * 100, "percent"],
        ["最多搬运次数", "profit_transfer.guard.max_times_per_trend", cfg.profit_transfer.guard.max_times_per_trend],
      ],
      desc: "盈利腿减仓实现净利润，再按配置恢复或增加亏损腿。",
    },
    {
      title: "仓位恢复",
      color: "blue",
      priority: "优先级 3",
      fields: [
        ["回调触发", "position_recovery.trigger.pullback_pct_from_trend_extreme", cfg.position_recovery.trigger.pullback_pct_from_trend_extreme],
        ["盈利侧恢复比例", "position_recovery.sizing.restore_profit_side_ratio", cfg.position_recovery.sizing.restore_profit_side_ratio * 100, "percent"],
        ["亏损侧归一比例", "position_recovery.sizing.normalize_loss_side_ratio", cfg.position_recovery.sizing.normalize_loss_side_ratio * 100, "percent"],
        ["目标仓位偏差", "position_recovery.target.target_balance_position_distance_pct", cfg.position_recovery.target.target_balance_position_distance_pct * 100, "percent"],
      ],
      desc: "价格回调或反弹后，逐步把多空仓位拉回目标结构。",
    },
    {
      title: "亏损腿减仓",
      color: "orange",
      priority: "优先级 1",
      fields: [
        ["单边确认幅度", "loss_side_reduction.trigger.trend_confirm_move_pct_from_base", cfg.loss_side_reduction.trigger.trend_confirm_move_pct_from_base],
        ["每步减仓触发", "loss_side_reduction.trigger.reduce_step_pct", cfg.loss_side_reduction.trigger.reduce_step_pct],
        ["每步减仓比例", "loss_side_reduction.sizing.reduce_loss_side_ratio", cfg.loss_side_reduction.sizing.reduce_loss_side_ratio * 100, "percent"],
        ["最低保留仓位", "loss_side_reduction.sizing.min_loss_side_position_ratio_of_base", cfg.loss_side_reduction.sizing.min_loss_side_position_ratio_of_base * 100, "percent"],
      ],
      desc: "单边趋势确认后，停止逆势恢复并逐步削减亏损腿。",
    },
  ];

  $("eventConfig").innerHTML = cards.map((card) => `
    <article class="event-card ${card.color}">
      <div class="event-card-header">
        <h3>${card.title}</h3>
        ${badge(card.priority, card.color)}
      </div>
      ${card.fields.map(([label, path, value, unit]) => `
        <label class="field">
          <span>${label}</span>
          <input type="number" step="0.01" min="0" data-config-path="${path}" data-unit="${unit || "raw"}" value="${fmt(value, 2).replace(/,/g, "")}" />
        </label>
      `).join("")}
      <p class="muted">${card.desc}</p>
    </article>
  `).join("");
}

function renderSymbolDetail() {
  const s = state.symbols.find((item) => item.symbol === selectedSymbol);
  if (!s) {
    $("symbolMetricStrip").innerHTML = [
      summaryItem("当前币种", "暂无", "请先同步 Binance"),
      summaryItem("当前价格", "--"),
      summaryItem("确认幅度", "--"),
      summaryItem("事件状态", "等待数据"),
    ].join("");
    $("selectedState").textContent = "-";
    $("symbolRows").innerHTML = emptyRow(7, "暂无真实仓位。请先同步 Binance 账户。");
    $("symbolTabs").innerHTML = "";
    $("positionCards").innerHTML = `<p class="muted">暂无真实仓位。</p>`;
    $("stateFacts").innerHTML = "";
    $("priceChart").innerHTML = "";
    $("positionChart").innerHTML = "";
    $("equityChart").innerHTML = "";
    $("timeline").innerHTML = `<p class="muted">暂无策略事件。</p>`;
    return;
  }
  const lastBySymbol = latestEventsBySymbol();

  $("symbolMetricStrip").innerHTML = [
    summaryItem("当前币种", s.symbol, badge(stateLabel(s.state), stateColor(s.state))),
    summaryItem("当前价格", fmt(s.price, s.symbol === "SOLUSDT" ? 3 : 2), "Binance mark price"),
    summaryItem("基准价", fmt(s.base_price, 2), `偏离 ${fmt(s.move_pct, 2)}%`),
    summaryItem("浮动盈亏", `<span class="${cls(s.unrealized_pnl)}">${fmt(s.unrealized_pnl)} USDT</span>`, `净敞口 ${fmt(s.net_exposure)} USDT`),
  ].join("");

  $("selectedState").innerHTML = badge(stateLabel(s.state), stateColor(s.state));
  $("symbolRows").innerHTML = state.symbols.map((item) => `
    <tr>
      <td><button class="tab ${selectedSymbol === item.symbol ? "active" : ""}" onclick="selectSymbol('${item.symbol}')">${item.symbol}</button></td>
      <td>${badge(stateLabel(item.state), stateColor(item.state))}</td>
      <td>${fmt(item.price, item.symbol === "SOLUSDT" ? 3 : 2)}</td>
      <td>${fmt(item.long_qty, 6)}</td>
      <td>${fmt(item.short_qty, 6)}</td>
      <td class="${cls(item.unrealized_pnl)}">${fmt(item.unrealized_pnl)} USDT</td>
      <td>${lastBySymbol[item.symbol] ? eventLabel(lastBySymbol[item.symbol].event_type) : "无"}</td>
    </tr>
  `).join("");

  $("symbolTabs").innerHTML = state.symbols.map((item) => `
    <button class="tab ${item.symbol === selectedSymbol ? "active" : ""}" onclick="selectSymbol('${item.symbol}')">${item.symbol}</button>
  `).join("");

  $("positionCards").innerHTML = `
    <div class="position-card long">
      <strong>多头仓位</strong>
      <p>数量：${fmt(s.long_qty, 6)}</p>
      <p>入场价：${fmt(s.long_entry_price, 2)}</p>
      <p class="${cls(s.long_unrealized_pnl)}">浮动盈亏：${fmt(s.long_unrealized_pnl)} USDT</p>
    </div>
    <div class="position-card short">
      <strong>空头仓位</strong>
      <p>数量：${fmt(s.short_qty, 6)}</p>
      <p>入场价：${fmt(s.short_entry_price, 2)}</p>
      <p class="${cls(s.short_unrealized_pnl)}">浮动盈亏：${fmt(s.short_unrealized_pnl)} USDT</p>
    </div>
  `;

  $("stateFacts").innerHTML = `
    <dt>当前价格</dt><dd>${fmt(s.price, 2)}</dd>
    <dt>基准价</dt><dd>${fmt(s.base_price, 2)}</dd>
    <dt>偏离幅度</dt><dd class="${cls(s.move_pct)}">${fmt(s.move_pct, 2)}%</dd>
    <dt>总敞口</dt><dd>${fmt(s.gross_exposure)} USDT</dd>
    <dt>净敞口</dt><dd class="${cls(s.net_exposure)}">${fmt(s.net_exposure)} USDT</dd>
    <dt>已实现盈亏</dt><dd class="${cls(s.realized_pnl)}">${fmt(s.realized_pnl)}</dd>
    <dt>手续费</dt><dd>${fmt(s.fee_total)}</dd>
    <dt>搬运次数</dt><dd>${s.profit_transfer_count}</dd>
  `;

  drawLineChart("priceChart", state.price_history[selectedSymbol] || [], "price", s.symbol);
  drawSymbolMiniCharts(s);
  renderTimeline();
}

function renderTimeline() {
  const events = state.strategy_events.filter((e) => e.symbol === selectedSymbol).slice(0, 8);
  $("timeline").innerHTML = events.length ? events.map((event) => `
    <div class="timeline-item">
      <strong>${eventLabel(event.event_type)}</strong>
      <div class="muted">${event.timestamp}</div>
      <p>${event.reason}</p>
      <small>${event.trades.map((t) => `${t.action} ${fmt(t.qty, 6)}`).join(" / ")}</small>
    </div>
  `).join("") : `<p class="muted">暂无事件，等待价格触发策略条件。</p>`;
}

function renderRisk() {
  const overview = state.admin_overview || { users: [], accounts: [] };
  const planned = (state.execution_plans || []).filter((plan) => plan.status === "planned").length;
  const blocked = (state.execution_plans || []).filter((plan) => plan.status === "blocked").length;
  const confirmed = (state.execution_plans || []).filter((plan) => plan.manual_review?.status === "confirmed").length;
  const accountsById = Object.fromEntries((overview.accounts || []).map((account) => [account.account_id, account]));
  $("riskControlSummary").innerHTML = [
    metricTile("运行用户", overview.users.length, "业务用户"),
    metricTile("运行账户", overview.accounts.length, "Binance futures"),
    metricTile("待演练计划", planned, "plan_only"),
    metricTile("计划拦截", blocked, "来自计划风控检查", blocked ? "negative" : ""),
    metricTile("已确认计划", confirmed, "人工核对记录"),
    metricTile("风险告警", state.risk_events.length, state.strategy.risk_status === "normal" ? "当前正常" : "需要关注", state.risk_events.length ? "negative" : ""),
  ].join("");

  $("riskRows").innerHTML = state.risk_events.length ? state.risk_events.slice(0, 12).map((r) => `
    <tr>
      <td>${r.timestamp}</td>
      <td>${r.user_id || "-"}</td>
      <td>${r.exchange_account_id || "-"}</td>
      <td>${r.symbol || "-"}</td>
      <td>${badge(r.risk_type, r.risk_level === "high" ? "red" : "orange")}</td>
      <td>${badge(r.risk_level || "-", r.risk_level === "high" ? "red" : "orange")}</td>
      <td>${r.action_taken}</td>
    </tr>
  `).join("") : emptyRow(7, "暂无风险告警");

  $("planRiskRows").innerHTML = (state.execution_plans || []).length ? (state.execution_plans || []).slice(0, 14).map((plan) => {
    const account = accountsById[plan.account_id] || {};
    const checks = plan.risk_checks || [];
    const failed = checks.filter((check) => !check.ok);
    const checkText = failed.length
      ? failed.map((check) => `${badge("拦截", "orange")} ${esc(check.message || check.name)}`).join("<br />")
      : `${badge("通过", "green")} ${checks.length ? "计划检查通过" : "无检查项"}`;
    const review = plan.manual_review || {};
    const reviewText = review.status === "confirmed"
      ? `${badge("已确认", "green")}<div class="muted">${esc(review.reviewed_at || "-")}</div>`
      : `<span class="muted">未确认</span>`;
    return `
      <tr>
        <td><strong>${esc(account.account_label || plan.account_id)}</strong><div class="muted">${esc(plan.account_id)}</div></td>
        <td>${esc(plan.symbol)}</td>
        <td>${planStatusBadge(plan.status)}</td>
        <td>${checkText}</td>
        <td>${reviewText}</td>
      </tr>
    `;
  }).join("") : emptyRow(5, "暂无执行计划风控记录");

  $("auditLogs").innerHTML = state.admin_audit_logs.length ? state.admin_audit_logs.slice(0, 12).map((item) => `
    <div class="audit-item">
      <strong>${item.action_type}</strong>
      <div class="muted">${item.timestamp} / ${item.admin_user_id}</div>
      <p>${item.reason}</p>
    </div>
  `).join("") : `<p class="muted">暂无管理员操作。</p>`;
}

function renderReports() {
  const reports = state.daily_reports || [];
  $("reportList").innerHTML = reports.length ? reports.map((report) => `
    <div class="event-item">
      <strong>${report.date} 日报</strong>
      <div class="muted">生成时间：${report.generated_at || "-"} / 策略：${report.strategy_instance_id}</div>
      <p>
        PnL：<span class="${cls(report.daily_pnl)}">${fmt(report.daily_pnl)} USDT</span>
        · 手续费：${fmt(report.fee_total)}
        · 利润搬运：${report.profit_transfer_count}
        · 亏损腿减仓：${report.loss_side_reduce_count}
      </p>
      <p>
        <a href="/${report.markdown_path}" target="_blank">打开 Markdown</a>
        ${(report.charts || []).slice(0, 6).map((chart) => ` · <a href="/${chart.path}" target="_blank">${chart.title}</a>`).join("")}
      </p>
    </div>
  `).join("") : `<p class="muted">暂无日报。</p>`;
}

function renderEventLog() {
  $("eventLog").innerHTML = state.strategy_events.length ? state.strategy_events.slice(0, 24).map((event) => `
    <div class="event-item">
      <strong>${eventLabel(event.event_type)} · ${event.symbol}</strong>
      <div class="muted">${event.timestamp} / ${stateLabel(event.state_before)} -> ${stateLabel(event.state_after)}</div>
      <p>${event.reason}</p>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>动作</th>
              <th>方向</th>
              <th>数量</th>
              <th>成交价</th>
              <th>手续费</th>
              <th>已实现盈亏</th>
            </tr>
          </thead>
          <tbody>
            ${event.trades.map((t) => `
              <tr>
                <td>${t.action}</td>
                <td>${t.position_side}</td>
                <td>${fmt(t.qty, 6)}</td>
                <td>${fmt(t.fill_price, 4)}</td>
                <td>${fmt(t.fee, 4)}</td>
                <td class="${cls(t.realized_pnl)}">${fmt(t.realized_pnl, 4)}</td>
              </tr>
            `).join("")}
          </tbody>
        </table>
      </div>
    </div>
  `).join("") : `<p class="muted">暂无策略事件。</p>`;
}

function drawSymbolMiniCharts(s) {
  const history = state.price_history[selectedSymbol] || [];
  const posData = history.map((p) => ({
    tick: p.tick,
    long: s.long_qty * p.price,
    short: s.short_qty * p.price,
  }));
  drawMultiLineChart("positionChart", posData, ["long", "short"], ["#078f52", "#d92d20"]);

  const latest = history.at(-1)?.price || s.price;
  const eqData = history.map((p) => ({
    tick: p.tick,
    equity: s.equity - (latest - p.price) * (s.long_qty - s.short_qty),
  }));
  drawLineChart("equityChart", eqData, "equity", "equity");
}

function drawLineChart(id, data, key, label) {
  const el = $(id);
  if (!data.length) {
    el.innerHTML = "";
    return;
  }
  const w = el.clientWidth || 640;
  const h = el.clientHeight || 248;
  const pad = 28;
  const values = data.map((d) => Number(d[key]));
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const points = data.map((d, i) => {
    const x = pad + (i / Math.max(data.length - 1, 1)) * (w - pad * 2);
    const y = h - pad - ((Number(d[key]) - min) / span) * (h - pad * 2);
    return `${x},${y}`;
  }).join(" ");
  el.innerHTML = `
    <svg viewBox="0 0 ${w} ${h}" width="100%" height="100%" preserveAspectRatio="none">
      <rect x="0" y="0" width="${w}" height="${h}" fill="transparent"/>
      <line x1="${pad}" x2="${w - pad}" y1="${h - pad}" y2="${h - pad}" stroke="#dce3ee"/>
      <line x1="${pad}" x2="${pad}" y1="${pad}" y2="${h - pad}" stroke="#dce3ee"/>
      <polyline points="${points}" fill="none" stroke="#1f6feb" stroke-width="2.5"/>
      <text x="${pad}" y="18" fill="#667085" font-size="12">${label}: ${fmt(values.at(-1), 2)}</text>
    </svg>`;
}

function drawMultiLineChart(id, data, keys, colors) {
  const el = $(id);
  if (!data.length) {
    el.innerHTML = "";
    return;
  }
  const w = el.clientWidth || 300;
  const h = el.clientHeight || 150;
  const pad = 22;
  const values = data.flatMap((d) => keys.map((key) => Number(d[key])));
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const lines = keys.map((key, idx) => {
    const points = data.map((d, i) => {
      const x = pad + (i / Math.max(data.length - 1, 1)) * (w - pad * 2);
      const y = h - pad - ((Number(d[key]) - min) / span) * (h - pad * 2);
      return `${x},${y}`;
    }).join(" ");
    return `<polyline points="${points}" fill="none" stroke="${colors[idx]}" stroke-width="2"/>`;
  }).join("");
  el.innerHTML = `
    <svg viewBox="0 0 ${w} ${h}" width="100%" height="100%" preserveAspectRatio="none">
      <line x1="${pad}" x2="${w - pad}" y1="${h - pad}" y2="${h - pad}" stroke="#dce3ee"/>
      ${lines}
    </svg>`;
}

function latestEventsBySymbol() {
  const result = {};
  state.strategy_events.forEach((event) => {
    if (!result[event.symbol]) result[event.symbol] = event;
  });
  return result;
}

function stateColor(value) {
  if (value === "REAL_POSITION") return "green";
  if (value === "BALANCE") return "blue";
  if (value.includes("REDUCING")) return "orange";
  if (value.includes("RECOVERING")) return "green";
  if (value.includes("DOWN")) return "red";
  return "green";
}

function selectSymbol(symbol, openPage = false) {
  selectedSymbol = symbol;
  renderSymbolDetail();
  renderDashboard();
  if (openPage) activatePage("symbol");
}

function setByPath(target, path, value) {
  const parts = path.split(".");
  let node = target;
  for (let i = 0; i < parts.length - 1; i += 1) {
    node = node[parts[i]];
  }
  node[parts.at(-1)] = value;
}

function collectEventConfig() {
  const next = structuredClone(state.event_config);
  document.querySelectorAll("[data-config-path]").forEach((input) => {
    let value = Number(input.value);
    if (!Number.isFinite(value)) value = 0;
    if (input.dataset.unit === "percent") value = value / 100;
    setByPath(next, input.dataset.configPath, value);
  });
  return next;
}

document.querySelectorAll("[data-nav-page]").forEach((item) => {
  item.addEventListener("click", (event) => {
    event.preventDefault();
    activatePage(item.dataset.navPage);
  });
});

document.querySelectorAll("[data-jump-page]").forEach((item) => {
  item.addEventListener("click", () => activatePage(item.dataset.jumpPage));
});

window.addEventListener("hashchange", () => {
  activatePage(location.hash.replace("#", "") || "dashboard");
});

$("tickBtn").addEventListener("click", () => post("/api/tick"));
$("toggleBtn").addEventListener("click", () => post("/api/toggle", { running: !state.running }));
$("resetBtn").addEventListener("click", () => {
  if (confirm("确认重置 dry_run 状态？")) post("/api/reset");
});
$("saveConfigBtn").addEventListener("click", () => {
  post("/api/config/events", { event_config: collectEventConfig() });
});
$("generateReportBtn").addEventListener("click", () => {
  post("/api/report/daily");
});
$("newUserBtn").addEventListener("click", () => openUserEditor());
$("newAccountBtn").addEventListener("click", () => openAccountEditor());
$("generatePlansBtn").addEventListener("click", () => {
  if (!overviewAccounts().length) {
    alert("当前没有可生成计划的账户。");
    return;
  }
  generateExecutionPlans(selectedPlanAccount);
});
$("planAccountSelect").addEventListener("change", () => {
  selectedPlanAccount = $("planAccountSelect").value;
  renderPlans();
});
$("exportPlansBtn").addEventListener("click", exportExecutionPlans);
$("emergencyStopBtn").addEventListener("click", () => {
  if (confirm("确认触发全局急停？dry_run 策略会立即暂停，账户状态会标记为管理员暂停。")) {
    post("/api/admin/emergency-stop");
  }
});
$("resumeBtn").addEventListener("click", () => {
  post("/api/admin/resume");
});
$("logoutBtn").addEventListener("click", logout);
$("sidebarLogoutBtn").addEventListener("click", logout);
$("switchUserBtn").addEventListener("click", logout);
$("loginForm").addEventListener("submit", (event) => {
  event.preventDefault();
  login($("loginId").value, $("loginPassword").value);
});

activatePage(location.hash.replace("#", "") || "dashboard");
fetchState();
setInterval(fetchState, 2500);
