<template>
  <section class="page active">
    <div class="content-grid accounts-grid">
      <article class="panel">
        <div class="panel-head">
          <h3>用户列表</h3>
          <button v-if="isAdmin" class="button ghost small" @click="openUser()">新增用户</button>
        </div>
        <div v-if="userEditor.open" class="inline-editor">
          <h4>{{ userEditor.editing ? "编辑业务用户" : "新增业务用户" }}</h4>
          <div class="inline-editor-form">
            <div class="editor-grid">
              <label><span>用户 ID</span><input v-model="userEditor.form.user_id" :readonly="userEditor.editing" /></label>
              <label><span>显示名称</span><input v-model="userEditor.form.name" /></label>
              <label><span>邮箱</span><input v-model="userEditor.form.email" /></label>
              <label><span>状态</span><select v-model="userEditor.form.status"><option value="active">正常</option><option value="paused">已暂停</option><option value="disabled">已禁用</option></select></label>
            </div>
            <div class="editor-actions">
              <button class="button ghost small" @click="userEditor.open = false">取消</button>
              <button class="button small" @click="submitUser">保存用户</button>
            </div>
          </div>
        </div>
        <div class="table-wrap">
          <table>
            <thead><tr><th>用户</th><th>状态</th><th>账户数</th><th>总权益</th><th>今日盈亏</th><th>风险</th><th>操作</th></tr></thead>
            <tbody>
              <tr v-for="user in users" :key="user.user_id">
                <td><strong>{{ user.user_name }}</strong><div class="muted">{{ user.user_id }} · {{ user.role }}</div></td>
                <td><StatusBadge :text="statusLabel(user.status)" :color="statusColor(user.status)" /></td>
                <td>{{ user.account_count }}</td>
                <td>{{ fmt(user.total_equity) }} USDT</td>
                <td :class="cls(user.today_pnl)">{{ fmt(user.today_pnl) }} USDT</td>
                <td><StatusBadge :text="user.risk_status === 'normal' ? '正常' : '关注'" :color="user.risk_status === 'normal' ? 'green' : 'orange'" /></td>
                <td><button v-if="isAdmin" class="button ghost small" @click="openUser(user)">编辑</button><span v-else class="muted">-</span></td>
              </tr>
              <tr v-if="!users.length"><td colspan="7" class="muted">暂无业务用户。</td></tr>
            </tbody>
          </table>
        </div>
      </article>

      <article class="panel">
        <div class="panel-head">
          <h3>账户列表</h3>
          <button v-if="isAdmin" class="button ghost small" @click="openAccount()">新增账户</button>
        </div>
        <div v-if="accountEditor.open" class="inline-editor">
          <h4>{{ accountEditor.editing ? "编辑交易账户" : "新增交易账户" }}</h4>
          <div class="inline-editor-form">
            <div class="editor-grid">
              <label><span>账户 ID</span><input v-model="accountEditor.form.account_id" :readonly="accountEditor.editing" /></label>
              <label><span>所属用户</span><select v-model="accountEditor.form.user_id"><option v-for="user in users" :key="user.user_id" :value="user.user_id">{{ user.user_name }} / {{ user.user_id }}</option></select></label>
              <label><span>账户名称</span><input v-model="accountEditor.form.account_label" /></label>
              <label><span>状态</span><select v-model="accountEditor.form.status"><option value="active">正常</option><option value="disabled">已禁用</option><option value="paused_by_admin">管理员暂停</option></select></label>
              <label class="inline-check"><input v-model="accountEditor.form.testnet" type="checkbox" /><span>测试网</span></label>
              <label class="inline-check"><input v-model="accountEditor.form.dry_run" type="checkbox" /><span>只读 / 不下单</span></label>
              <label class="inline-check"><input v-model="accountEditor.form.hedge_mode_required" type="checkbox" /><span>要求 Hedge Mode</span></label>
            </div>
            <div class="editor-actions">
              <button class="button ghost small" @click="accountEditor.open = false">取消</button>
              <button class="button small" @click="submitAccount">保存账户</button>
            </div>
          </div>
        </div>
        <div class="table-wrap">
          <table>
            <thead><tr><th>账户</th><th>所属用户</th><th>账户状态</th><th>API / 同步</th><th>权益</th><th>操作</th></tr></thead>
            <tbody>
              <tr v-for="row in accounts" :key="row.account_id">
                <td>
                  <strong>{{ row.account_label }}</strong>
                  <div class="account-meta-line">
                    <span>{{ row.account_id }}</span>
                    <span>{{ row.exchange }} / {{ row.market_type }}</span>
                    <StatusBadge :text="accountModeLabel(row)" :color="accountModeColor(row)" />
                    <StatusBadge v-if="positionMode(row).hedge_mode_ok !== undefined" :text="positionMode(row).hedge_mode_ok ? '通过' : '未通过'" :color="positionMode(row).hedge_mode_ok ? 'green' : 'orange'" />
                    <StatusBadge v-else-if="row.hedge_mode_required" text="需双向" color="blue" />
                  </div>
                </td>
                <td><strong>{{ row.user_name }}</strong><div class="muted">{{ row.user_id }}</div></td>
                <td><StatusBadge :text="statusLabel(row.account_status)" :color="statusColor(row.account_status)" /></td>
                <td>
                  <div class="account-inline-actions">
                    <div>
                      <StatusBadge :text="credentialText(row)" :color="credentialColor(row)" />
                      <span class="muted">{{ statusLabel(snapshot(row).status || (exchangeAccount(row).api_key_configured ? 'unsynced' : 'missing_credentials')) }}</span>
                      <div v-if="exchangeAccount(row).credential_error" class="sync-error compact">{{ exchangeAccount(row).credential_error }}</div>
                      <div v-if="snapshot(row).error" class="sync-error compact">{{ snapshot(row).error }}</div>
                    </div>
                    <div v-if="canOperate(row)" class="account-api-fields">
                      <input v-model="credentialForms[row.account_id].apiKey" type="password" autocomplete="off" placeholder="API Key" />
                      <input v-model="credentialForms[row.account_id].apiSecret" type="password" autocomplete="off" placeholder="Secret" />
                      <button class="button small" @click="submitCredentials(row.account_id)">保存</button>
                      <button class="button ghost small" @click="syncBinanceAccount(row.account_id)">同步</button>
                    </div>
                    <span v-else class="muted">无操作权限</span>
                  </div>
                </td>
                <td><strong>{{ fmt(row.total_equity) }} USDT</strong><div :class="cls(row.today_pnl)">今日 {{ fmt(row.today_pnl) }} USDT</div></td>
                <td><button v-if="isAdmin" class="button ghost small" @click="openAccount(row)">编辑</button><span v-else class="muted">-</span></td>
              </tr>
              <tr v-if="!accounts.length"><td colspan="6" class="muted">暂无交易账户。</td></tr>
            </tbody>
          </table>
        </div>
      </article>
    </div>
  </section>
</template>

<script setup>
import { reactive, watchEffect } from "vue";
import StatusBadge from "../components/StatusBadge.vue";
import { cls, fmt } from "../core/format.js";
import { accountModeColor, accountModeLabel, statusColor, statusLabel } from "../domain/labels.js";
import {
  accounts,
  currentUser,
  isAdmin,
  saveBinanceCredentials,
  saveBusinessUser,
  saveExchangeAccount,
  store,
  syncBinanceAccount,
  users,
} from "../stores/appStore.js";

const credentialForms = reactive({});
const userEditor = reactive({ open: false, editing: false, form: {} });
const accountEditor = reactive({ open: false, editing: false, form: {} });

watchEffect(() => {
  for (const account of accounts.value) {
    credentialForms[account.account_id] ||= { apiKey: "", apiSecret: "" };
  }
});

function exchangeAccount(row) {
  return (store.state?.exchange_accounts || []).find((item) => item.id === row.account_id) || {};
}

function snapshot(row) {
  return (store.state?.binance_account_snapshots || {})[row.account_id] || {};
}

function positionMode(row) {
  return snapshot(row).position_mode || {};
}

function canOperate(row) {
  return isAdmin.value || row.user_id === currentUser.value?.id;
}

function credentialText(row) {
  const account = exchangeAccount(row);
  if (account.api_key_present && account.secret_present) return "API 可用";
  if (account.api_key_configured && account.secret_configured) return "API 已保存";
  return "API 未配置";
}

function credentialColor(row) {
  const account = exchangeAccount(row);
  if (account.api_key_present && account.secret_present) return "green";
  return "orange";
}

function openUser(user = null) {
  userEditor.open = true;
  userEditor.editing = Boolean(user);
  userEditor.form = {
    user_id: user?.user_id || "",
    name: user?.user_name || "",
    email: user?.email || "",
    status: user?.status || "active",
  };
}

async function submitUser() {
  await saveBusinessUser(userEditor.form);
  userEditor.open = false;
}

function openAccount(row = null) {
  const account = row ? exchangeAccount(row) : null;
  accountEditor.open = true;
  accountEditor.editing = Boolean(row);
  accountEditor.form = {
    account_id: row?.account_id || "",
    user_id: row?.user_id || users.value[0]?.user_id || "",
    account_label: row?.account_label || "",
    status: account?.status || row?.account_status || "active",
    testnet: account?.testnet ?? true,
    dry_run: account?.dry_run ?? true,
    hedge_mode_required: account?.hedge_mode_required ?? true,
  };
}

async function submitAccount() {
  await saveExchangeAccount(accountEditor.form);
  accountEditor.open = false;
}

async function submitCredentials(accountId) {
  const form = credentialForms[accountId];
  if (!form?.apiKey || !form?.apiSecret) {
    alert("请填写 Binance API Key 和 Secret。");
    return;
  }
  await saveBinanceCredentials(accountId, form.apiKey, form.apiSecret);
  form.apiKey = "";
  form.apiSecret = "";
}
</script>
