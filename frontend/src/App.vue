<template>
  <section class="login-screen" :class="{ active: !isAuthenticated }">
    <form class="login-card" @submit.prevent="submitLogin">
      <div class="brand login-brand">
        <div class="brand-mark">D</div>
        <div>
          <strong>Dynamic Dual Grid</strong>
          <span>实盘测试控制台</span>
        </div>
      </div>
      <label class="login-field">
        <span>用户 ID 或邮箱</span>
        <input v-model="loginId" autocomplete="off" placeholder="admin_001" />
      </label>
      <label class="login-field">
        <span>密码</span>
        <input v-model="password" type="password" autocomplete="off" placeholder="请输入密码" />
      </label>
      <p class="login-error">{{ store.loginError || store.stateError }}</p>
      <button class="button" type="submit" :disabled="store.loginBusy">{{ store.loginBusy ? "登录中..." : "登录" }}</button>
      <small class="muted">本地开发默认：admin_001 / admin123456，实盘前请使用脚本修改密码。</small>
    </form>
  </section>

  <div class="app-shell" :class="{ 'auth-locked': !isAuthenticated }">
    <aside class="sidebar">
      <div class="brand">
        <div class="brand-mark">D</div>
        <div>
          <strong>Dynamic Dual Grid</strong>
          <span>V1 控制台</span>
        </div>
      </div>

      <nav>
        <a
          v-for="item in navItems"
          :key="item.id"
          href="#"
          :class="{ active: store.activePage === item.id }"
          @click.prevent="setActivePage(item.id)"
        >
          <span>{{ item.label }}</span>
          <small>{{ item.note }}</small>
        </a>
      </nav>

      <div class="operator-card">
        <span>当前用户</span>
        <strong>{{ currentUser ? `${currentUser.name} / ${currentUser.role}` : "-" }}</strong>
        <small>{{ modeLabel(store.state?.strategy?.mode) }} · {{ statusLabel(store.state?.strategy?.status) }}</small>
        <div class="operator-actions" v-if="store.state?.auth?.login_required !== false">
          <button class="button ghost small" @click="logout">切换用户</button>
          <button class="button ghost small" @click="logout">退出登录</button>
        </div>
      </div>
    </aside>

    <main class="main">
      <header class="topbar">
        <div class="page-heading">
          <span class="eyebrow">{{ pageMeta[0] }}</span>
          <h1>{{ pageMeta[1] }}</h1>
          <p>{{ pageMeta[2] }}</p>
        </div>
        <div class="toolbar">
          <span class="pill">Tick {{ store.state?.tick_index ?? "--" }} / {{ store.state?.server_time ?? "--" }}</span>
          <button class="button ghost" :disabled="readOnlyMode" @click="tick">执行 Tick</button>
          <button class="button" :disabled="readOnlyMode" @click="toggleRunning">{{ readOnlyMode ? "只读模式" : (store.state?.running ? "暂停" : "启动") }}</button>
          <button class="button danger" :disabled="readOnlyMode" @click="resetRuntime">重置</button>
          <button class="button ghost" v-if="store.state?.auth?.login_required !== false" @click="logout">退出登录</button>
        </div>
      </header>

      <div v-if="store.stateError" class="service-alert">{{ store.stateError }}</div>

      <component :is="activeComponent" v-if="store.state" />
    </main>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from "vue";
import AccountsPage from "./pages/AccountsPage.vue";
import DashboardPage from "./pages/DashboardPage.vue";
import EventsPage from "./pages/EventsPage.vue";
import LogsPage from "./pages/LogsPage.vue";
import PlansPage from "./pages/PlansPage.vue";
import ReportsPage from "./pages/ReportsPage.vue";
import RiskPage from "./pages/RiskPage.vue";
import SymbolPage from "./pages/SymbolPage.vue";
import {
  currentUser,
  isAuthenticated,
  loadState,
  logout,
  resetRuntime,
  setActivePage,
  store,
  tick,
  toggleRunning,
} from "./stores/appStore.js";
import { PAGE_META, modeLabel, statusLabel } from "./domain/labels.js";
import { login } from "./stores/appStore.js";

const loginId = ref("admin_001");
const password = ref("");
let timer = null;

const navItems = [
  ["dashboard", "总览", "用户与运行"],
  ["accounts", "交易账户", "用户与交易账户"],
  ["events", "策略事件配置", "三类核心事件"],
  ["plans", "执行计划", "只读演练"],
  ["symbol", "币种详情", "多空与时间线"],
  ["risk", "风控中心", "急停、风险、审计"],
  ["reports", "复盘日报", "Markdown 与曲线"],
  ["logs", "事件日志", "父事件与成交"],
].map(([id, label, note]) => ({ id, label, note }));

const pageMeta = computed(() => PAGE_META[store.activePage] || PAGE_META.dashboard);
const readOnlyMode = computed(() => store.state?.strategy?.mode === "read_only");
const pageComponents = {
  dashboard: DashboardPage,
  accounts: AccountsPage,
  events: EventsPage,
  plans: PlansPage,
  symbol: SymbolPage,
  risk: RiskPage,
  reports: ReportsPage,
  logs: LogsPage,
};
const activeComponent = computed(() => pageComponents[store.activePage] || DashboardPage);

async function submitLogin() {
  const ok = await login(loginId.value, password.value);
  if (ok) password.value = "";
}

function syncHash() {
  const page = location.hash.replace("#", "") || "dashboard";
  if (PAGE_META[page]) setActivePage(page);
}

onMounted(() => {
  syncHash();
  loadState();
  window.addEventListener("hashchange", syncHash);
  timer = window.setInterval(loadState, 2500);
});

onUnmounted(() => {
  window.removeEventListener("hashchange", syncHash);
  window.clearInterval(timer);
});
</script>
