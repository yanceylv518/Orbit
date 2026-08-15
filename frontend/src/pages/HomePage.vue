<template><section class="page active dashboard-v2">
  <div class="answer"><span class="eyebrow">首页</span><h2>系统正常吗？</h2><strong>{{ attentionCount ? `有 ${attentionCount} 件事需要处理` : "一切正常" }}</strong></div>
  <div class="metric-grid four"><MetricCard label="自动实盘" :value="liveOk ? '正常' : '需检查'"/><MetricCard label="信号扫描" :value="signalOk ? '正常' : '需检查'"/><MetricCard label="行情数据" :value="feedOk ? '正常' : '中断'"/><MetricCard label="消息" :value="store.messagesUnread" note="条未读"/></div>
  <div class="content-columns">
    <article v-if="attentionCount" class="panel"><h3>等你处理</h3><p v-if="store.messagesUnread">有 {{ store.messagesUnread }} 条未读消息。</p><p v-if="!feedOk">实时行情需要检查。</p><button class="button small" @click="$emit('messages')">查看消息</button></article>
    <article v-else class="panel calm"><h3>今天没有待办</h3><p class="muted">异常、核对差异和过期数据会在这里自动出现。</p></article>
    <aside class="panel"><h3>钱怎么样了</h3><div class="money"><span>自动策略累计盈亏</span><strong>{{ pnl }} USDT</strong></div><div class="money"><span>手动交易累计盈亏</span><strong>暂无汇总</strong></div></aside>
  </div>
</section></template>
<script setup>import { computed } from 'vue'; import MetricCard from '../components/MetricCard.vue'; import { store } from '../stores/appStore.js'; defineEmits(['messages']);
const liveOk=computed(()=>!store.state?.risk_state?.global_stop); const signalOk=computed(()=>store.signalDesk?.health?.status !== 'STOPPED'); const feedOk=computed(()=>!store.state?.market_feed?.last_error); const attentionCount=computed(()=>store.messagesUnread+(!liveOk.value)+(!signalOk.value)+(!feedOk.value)); const pnl=computed(()=>Number(store.state?.strategy?.total_pnl||0).toLocaleString('zh-CN',{maximumFractionDigits:2}));
</script>
