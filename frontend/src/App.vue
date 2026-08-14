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
            :class="{ active: store.activePage === item.id }"
            @click.prevent="setActivePage(item.id)"
          >
            <NavIcon :name="item.id" />
            <span>{{ item.label }}</span>
          </a>
        </div>
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
          <button class="button ghost" @click="glossaryOpen = true">术语帮助</button>
          <button class="risk-pill" :class="riskStatusClass" @click="setActivePage('forward/live-small')" title="查看量化实例的风险与停止状态">
            风控 {{ riskStatusText }}
          </button>
          <!-- 只读模式：第一阶段主动作；模拟模式：dry_run 控件 -->
          <template v-if="store.activePage === 'strategy'">
            <span class="pill">冻结定义 · 只读</span>
          </template>
          <template v-else-if="store.activePage === 'data'">
            <span class="pill">历史研究数据 · 与实盘隔离</span>
          </template>
          <template v-else-if="store.activePage === 'research'">
            <span class="pill">预注册 · 结果只追加</span>
          </template>
          <template v-else-if="store.activePage === 'signals'">
            <span class="pill">人工决策 · 不自动下单</span>
          </template>
          <template v-else-if="store.activePage === 'forward'">
            <span class="pill">自动执行与核对</span>
          </template>
          <template v-else-if="store.activePage === 'review'">
            <span class="pill">只读复盘 · 不修改执行状态</span>
          </template>
          <template v-else-if="store.activePage === 'risk'">
            <span class="pill" title="协议阶段：LIVE-SMALL">小资金实盘 · 30% 强制停机线</span>
          </template>
          <template v-else-if="store.activePage === 'accounts'">
            <button class="button ghost" :disabled="store.syncAllBusy" @click="syncAllAccounts">
              {{ store.syncAllBusy ? "同步中..." : "同步全部账户" }}
            </button>
          </template>
          <template v-else-if="readOnlyMode">
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
    <GlossaryModal :open="glossaryOpen" @close="glossaryOpen = false" />
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from "vue";
import NavIcon from "./components/NavIcon.vue";
import GlossaryModal from "./components/GlossaryModal.vue";
import AccountsPage from "./pages/AccountsPage.vue";
import DataPage from "./pages/DataPage.vue";
import ForwardPage from "./pages/ForwardPage.vue";
import QuantPage from "./pages/QuantPage.vue";
import SignalPage from "./pages/SignalPage.vue";
import StrategyPage from "./pages/StrategyPage.vue";
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
const glossaryOpen = ref(false);
let timer = null;

const navGroups = [
  {
    label: "",
    items: [
      { id: "data", label: "数据" },
      { id: "strategy", label: "策略与研究" },
      { id: "forward", label: "量化" },
      { id: "signals", label: "信号" },
      { id: "accounts", label: "账户" },
    ],
  },
];

const pageMeta = computed(() => PAGE_META[store.activePage] || PAGE_META.forward);
const readOnlyMode = computed(() => store.state?.strategy?.mode === "read_only");
const riskStatusText = computed(() => statusLabel(store.state?.strategy?.risk_status || "normal"));
const riskStatusClass = computed(() => (store.state?.strategy?.risk_status === "normal" ? "ok" : "warn"));
const pageComponents = {
  data: DataPage,
  strategy: StrategyPage,
  accounts: AccountsPage,
  forward: QuantPage,
  signals: SignalPage,
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
  const raw = location.hash.replace("#", "") || "forward";
  const route = LEGACY_PAGE_ALIASES[raw] || raw;
  const base = route.split("/")[0];
  if (PAGE_META[base]) {
    setActivePage(route);
  } else {
    setActivePage("forward");
  }
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
