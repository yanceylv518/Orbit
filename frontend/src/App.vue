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
          <button class="risk-pill" :class="riskStatusClass" @click="setActivePage('risk')" title="点击进入风控中心">
            风控 {{ riskStatusText }}
          </button>
          <!-- 只读模式：第一阶段主动作；模拟模式：dry_run 控件 -->
          <template v-if="readOnlyMode">
            <button class="button ghost" :disabled="store.syncAllBusy" @click="syncAllAccounts">
              {{ store.syncAllBusy ? "同步中..." : "同步全部账户" }}
            </button>
            <button class="button" @click="generateExecutionPlans('')">生成执行计划</button>
          </template>
          <template v-else>
            <span class="pill">Tick {{ store.state?.tick_index ?? "--" }}</span>
            <button class="button ghost" @click="tick">执行 Tick</button>
            <button class="button" @click="toggleRunning">{{ store.state?.running ? "暂停" : "启动" }}</button>
            <button class="button danger" @click="resetRuntime">重置</button>
          </template>
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
import PlansPage from "./pages/PlansPage.vue";
import ReportsPage from "./pages/ReportsPage.vue";
import RiskPage from "./pages/RiskPage.vue";
import StrategyPage from "./pages/StrategyPage.vue";
import SymbolPage from "./pages/SymbolPage.vue";
import {
  currentUser,
  generateExecutionPlans,
  isAuthenticated,
  loadState,
  logout,
  resetRuntime,
  setActivePage,
  store,
  syncAllAccounts,
  tick,
  toggleRunning,
} from "./stores/appStore.js";
import { LEGACY_PAGE_ALIASES, PAGE_META, modeLabel, statusLabel } from "./domain/labels.js";
import { login } from "./stores/appStore.js";

const loginId = ref("admin_001");
const password = ref("");
let timer = null;

const navItems = [
  ["dashboard", "工作台", "主流程与待办"],
  ["accounts", "用户与账户", "凭证与同步"],
  ["strategy", "策略中心", "挂载与参数"],
  ["plans", "执行计划", "审查与确认"],
  ["symbol", "币种视图", "相位与净敞口"],
  ["risk", "风控中心", "拦截、审计、急停"],
  ["reports", "报表", "日报与事件日志"],
].map(([id, label, note]) => ({ id, label, note }));

const pageMeta = computed(() => PAGE_META[store.activePage] || PAGE_META.dashboard);
const readOnlyMode = computed(() => store.state?.strategy?.mode === "read_only");
const riskStatusText = computed(() => (store.state?.strategy?.risk_status === "normal" ? "正常" : "关注"));
const riskStatusClass = computed(() => (store.state?.strategy?.risk_status === "normal" ? "ok" : "warn"));
const pageComponents = {
  dashboard: DashboardPage,
  accounts: AccountsPage,
  strategy: StrategyPage,
  plans: PlansPage,
  symbol: SymbolPage,
  risk: RiskPage,
  reports: ReportsPage,
};
const activeComponent = computed(() => pageComponents[store.activePage] || DashboardPage);

async function submitLogin() {
  const ok = await login(loginId.value, password.value);
  if (ok) password.value = "";
}

function syncHash() {
  const raw = location.hash.replace("#", "") || "dashboard";
  const page = LEGACY_PAGE_ALIASES[raw] || raw;
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
