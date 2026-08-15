<template>
  <section class="login-screen" :class="{ active: !isAuthenticated }">
    <form class="login-card" @submit.prevent="submitLogin">
      <div class="brand login-brand">
        <div class="brand-mark">O</div>
        <div>
          <strong>ORBIT</strong>
          <span>策略研究与实盘控制台</span>
        </div>
      </div>
      <label class="login-field">
        <span>管理员 ID 或邮箱</span>
        <input v-model="loginId" autocomplete="off" placeholder="admin_001" />
      </label>
      <label class="login-field">
        <span>密码</span>
        <input v-model="password" type="password" autocomplete="off" placeholder="请输入密码" />
      </label>
      <p class="login-error">{{ store.loginError || store.stateError }}</p>
      <button class="button" type="submit" :disabled="store.loginBusy">{{ store.loginBusy ? "登录中..." : "登录" }}</button>
      <small class="muted">请使用管理员分配的账号和密码登录。</small>
    </form>
  </section>

  <div class="app-shell" :class="{ 'auth-locked': !isAuthenticated }">
    <aside class="sidebar">
      <div class="brand">
        <div class="brand-mark">O</div>
        <div>
          <strong>ORBIT</strong>
          <span>纪律化策略研究与实盘</span>
        </div>
      </div>

      <nav>
        <div v-for="group in navGroups" :key="group.label" class="nav-group">
          <div v-if="group.label" class="nav-group-label">{{ group.label }}</div>
          <a
            v-for="item in group.items"
            :key="item.id"
            href="#"
            :class="{ active: store.activeRoute === item.route || store.activeRoute.startsWith(`${item.route}/`) }"
            @click.prevent="setActivePage(item.route)"
          >
            <NavIcon :name="item.id" />
            <span>{{ item.label }}</span>
          </a>
        </div>
      </nav>

    </aside>

    <main class="main">
      <header class="topbar">
        <div class="topbar-title"><span v-if="pageMeta[0]" class="eyebrow">{{ pageMeta[0] }}</span><h1>{{ pageMeta[1] }}</h1></div>
        <div class="topbar-right">
          <button class="global-status" :class="globalHealthy ? 'ok' : 'warn'" @click="setActivePage('forward')"><i></i>{{ globalHealthy ? '实盘与行情正常' : '系统需要检查' }}</button>
          <button class="message-bell" aria-label="打开消息中心" @click="messagesOpen=true">🔔<b v-if="store.messagesUnread">{{store.messagesUnread}}</b></button>
          <div ref="userMenuRef" class="user-menu-wrap">
            <button class="user-menu-button" aria-label="用户菜单" @click="userMenuOpen = !userMenuOpen"><span class="user-avatar" aria-hidden="true"><svg viewBox="0 0 24 24"><circle cx="12" cy="8" r="3.5"/><path d="M5 20c.5-4.1 2.8-6.2 7-6.2s6.5 2.1 7 6.2"/></svg></span><span class="user-copy"><strong>{{ currentUser?.name || '用户' }}</strong></span><span class="user-chevron">⌄</span></button>
            <div v-if="userMenuOpen" class="user-menu-popover"><div><span>当前账户</span><strong>{{ currentUser?.id || '-' }}</strong><small>{{ userRoleText }}</small></div><button v-if="store.state?.auth?.login_required !== false" class="button ghost small" @click="logout">退出登录</button></div>
          </div>
        </div>
      </header>

      <div v-if="store.stateError" class="service-alert">{{ store.stateError }}</div>

      <component :is="activeComponent" v-if="store.state" @messages="messagesOpen=true" />
    </main>
    <MessageCenter :open="messagesOpen" @close="messagesOpen=false" />
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from "vue";
import NavIcon from "./components/NavIcon.vue";
import AccountsPage from "./pages/AccountsPage.vue";
import DataPage from "./pages/DataPage.vue";
import HomePage from "./pages/HomePage.vue";
import ResearchPage from "./pages/ResearchPage.vue";
import DashboardPage from "./pages/DashboardPage.vue";
import PlansPage from "./pages/PlansPage.vue";
import SymbolPage from "./pages/SymbolPage.vue";
import RiskPage from "./pages/RiskPage.vue";
import ReportsPage from "./pages/ReportsPage.vue";
import LogsPage from "./pages/LogsPage.vue";
import ReviewPage from "./pages/ReviewPage.vue";
import MessageCenter from "./components/MessageCenter.vue";
import ForwardPage from "./pages/ForwardPage.vue";
import QuantPage from "./pages/QuantPage.vue";
import SignalPage from "./pages/SignalPage.vue";
import StrategyPage from "./pages/StrategyPage.vue";
import {
  currentUser,
  isAuthenticated,
  loadState,
  loadMessages,
  logout,
  setActivePage,
  store,
} from "./stores/appStore.js";
import { LEGACY_PAGE_ALIASES, PAGE_META } from "./domain/labels.js";
import { login } from "./stores/appStore.js";

const loginId = ref("admin_001");
const password = ref("");
const messagesOpen = ref(false);
const userMenuOpen = ref(false);
const userMenuRef = ref(null);
let timer = null;
let messageTimer = null;

const navGroups = [
  {
    label: "",
    items: [
      { id: "home", route: "home", label: "首页" },
      { id: "forward", route: "forward", label: "实盘" },
      { id: "signals", route: "signals", label: "信号" },
      { id: "strategy", route: "strategy", label: "策略" },
      { id: "research", route: "research", label: "研究" },
      { id: "data", route: "data", label: "数据" },
      { id: "accounts", route: "accounts", label: "账户" },
    ],
  },
];

const globalHealthy = computed(() => !store.stateError && !store.state?.market_feed?.last_error && !store.state?.risk_state?.global_stop);
const pageMeta = computed(() => PAGE_META[store.activePage] || PAGE_META.forward);
const userRoleText = computed(() => ({ admin: "管理员", super_admin: "超级管理员" }[currentUser.value?.role] || "用户"));
const pageComponents = {
  home: HomePage,
  data: DataPage,
  strategy: StrategyPage,
  accounts: AccountsPage,
  forward: QuantPage,
  signals: SignalPage,
  research: ResearchPage,
  dashboard: DashboardPage,
  plans: PlansPage,
  symbol: SymbolPage,
  risk: RiskPage,
  reports: ReportsPage,
  logs: LogsPage,
  review: ReviewPage,
};
const activeComponent = computed(() => (
  store.activeRoute === "forward/legacy"
    ? ForwardPage
    : (pageComponents[store.activePage] || QuantPage)
));

async function submitLogin() {
  const ok = await login(loginId.value, password.value);
  if (ok) password.value = "";
}

function syncHash() {
  const raw = location.hash.replace("#", "") || "home";
  const route = LEGACY_PAGE_ALIASES[raw] || raw;
  const base = route.split("/")[0];
  if (pageComponents[base]) {
    setActivePage(route);
  } else {
    setActivePage("forward");
  }
}

function closeUserMenu(event) {
  if (event.type === "keydown" && event.key !== "Escape") return;
  if (event.type === "pointerdown" && userMenuRef.value?.contains(event.target)) return;
  userMenuOpen.value = false;
}

onMounted(() => {
  syncHash();
  loadState();
  loadMessages();
  window.addEventListener("hashchange", syncHash);
  document.addEventListener("pointerdown", closeUserMenu);
  document.addEventListener("keydown", closeUserMenu);
  timer = window.setInterval(loadState, 2500);
  messageTimer = window.setInterval(loadMessages, 15000);
});

onUnmounted(() => {
  window.removeEventListener("hashchange", syncHash);
  document.removeEventListener("pointerdown", closeUserMenu);
  document.removeEventListener("keydown", closeUserMenu);
  window.clearInterval(timer);
  window.clearInterval(messageTimer);
});
</script>
