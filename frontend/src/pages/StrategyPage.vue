<template>
  <StrategyCenterPage v-if="store.activeRoute !== 'strategy'" />
  <section v-else class="page active strategy-hub-page">
    <article class="panel data-overview-card strategy-overview-card">
      <div class="data-overview-head"><div><h2>策略中心</h2><p class="muted">先看每套规则在找什么、现在是否工作，再进入详情检查规则。</p></div><button class="button ghost small" :disabled="busy" @click="refresh">{{ busy ? "刷新中…" : "刷新策略" }}</button></div>
      <div class="data-overview-metrics strategy-overview-metrics"><div><span>全部策略</span><strong>{{ cards.length }}</strong><small>套已配置规则</small></div><div><span>自动执行</span><strong>1</strong><small>机器负责调仓</small></div><div><span>推给你决定</span><strong>3</strong><small>你决定是否交易</small></div><div><span>今日信号</span><strong>{{ signals.length }}</strong><small>个已记录机会</small></div></div>
    </article>
    <div v-if="store.strategyCatalogError || store.signalDeskError" class="service-alert">{{ store.strategyCatalogError || store.signalDeskError }} <button class="button ghost small" @click="refresh">重试</button></div>
    <section v-for="group in groups" :key="group.title" class="strategy-group">
      <div class="strategy-group-head"><div><h3>{{ group.title }}</h3><p>{{ group.description }}</p></div><span>{{ group.items.length }} 套</span></div>
      <div class="strategy-row-list">
        <article v-for="item in group.items" :key="item.slug" class="panel strategy-directory-row">
          <div class="strategy-row-name"><span class="eyebrow">{{ item.kind }}</span><h3>{{ item.name }}</h3><p>{{ item.summary }}</p></div>
          <StrategyThumbnail :points="item.points" :signal="item.signal" :empty-text="item.emptyText" />
          <div class="strategy-row-dynamics"><span v-for="metric in item.metrics" :key="metric.label"><small>{{ metric.label }}</small><b>{{ metric.value }}</b></span></div>
          <div class="strategy-row-state"><StatusBadge :text="item.status" :color="item.color" /><small>{{ item.reason }}</small><button class="button ghost small" @click="setActivePage(`strategy/${item.slug}`)">查看详情</button></div>
        </article>
      </div>
    </section>
  </section>
</template>
<script setup>
import{computed,onMounted,watch}from"vue";import StatusBadge from"../components/StatusBadge.vue";import StrategyThumbnail from"../components/StrategyThumbnail.vue";import StrategyCenterPage from"./StrategyCenterPage.vue";import{isAuthenticated,loadSignalDesk,loadStrategyCatalog,setActivePage,store}from"../stores/appStore.js";
const signals=computed(()=>store.signalDesk?.signals||[]);const busy=computed(()=>store.strategyCatalogBusy||store.signalDeskBusy);const weights=computed(()=>store.state?.trend_forward?.runner?.weights||{});const holdingCount=computed(()=>Object.values(weights.value).filter(v=>Math.abs(Number(v))>1e-9).length);const serviceEnabled=computed(()=>Boolean(store.signalDesk?.operations?.service?.enabled));const equityPoints=computed(()=>(store.state?.live_reconciliation?.equity?.points||[]).map(r=>Number(r.paper_normalized)).filter(Number.isFinite));
const familyEntries=computed(()=>Object.entries(store.signalDesk?.recent_samples_by_family||{}));const count=p=>signals.value.filter(r=>p.test(String(r.family_id||r.family||r.type||""))).length;const rollingCount=p=>Object.entries(store.signalDesk?.rolling_30d_by_family||{}).reduce((sum,[family,value])=>sum+(p.test(family)?Number(value):0),0);const sample=p=>signals.value.find(r=>p.test(String(r.family_id||r.family||r.type||"")))||familyEntries.value.find(([family])=>p.test(family))?.[1]||null;const prices=s=>[...(s?.chart_before||[]),...(s?.chart_after||[])].map(r=>Number(r.close)).filter(Number.isFinite);const reason=computed(()=>serviceEnabled.value?"扫描服务正常运行":store.signalDesk?.health?.status==="NOT_DEPLOYED"?"扫描服务尚未部署":"提醒服务已关闭");
const cards=computed(()=>{const trendStarted=store.state?.trend_forward?.status&&store.state.trend_forward.status!=="NOT_STARTED";const make=(slug,name,summary,pattern,empty)=>{const s=sample(pattern);return{slug,name,kind:"推给你决定",summary,signal:s,points:prices(s),emptyText:empty,status:serviceEnabled.value?"提醒已启用":"提醒未启用",color:serviceEnabled.value?"green":"orange",reason:reason.value,metrics:[{label:"今日推送",value:`${count(pattern)} 个`},{label:"近 30 天",value:`${rollingCount(pattern)} 个`}]}};return[{slug:"trend",name:"趋势策略",kind:"自动执行",summary:"12 个主流币，谁在涨就跟谁，每周调一次仓。",points:equityPoints.value,emptyText:"等待净值记录",status:trendStarted?"运行中":"尚未启动",color:trendStarted?"green":"orange",reason:trendStarted?"按每周目标自动调仓":"尚未开始模拟计分",metrics:[{label:"当前持仓",value:`${holdingCount.value} / 12`},{label:"近 30 天",value:"观测不足"}]},make("breakout","突破信号","价格冲破近期高点、成交明显放大时提醒你。",/break|突破/i,"尚无突破样本"),make("oversold","超跌反弹","短时间暴跌后出现企稳迹象时提醒你。",/oversold|超跌/i,"尚无超跌样本"),make("strength","持续强势","价格连续走强、成交持续活跃时提醒你。",/strong|强势/i,"尚无强势样本")]});
const groups=computed(()=>[{title:"自动执行",description:"机器按规则决策，你只需查看结果和风险。",items:cards.value.filter(i=>i.kind==="自动执行")},{title:"推给你决定",description:"系统筛选机会，是否交易由你判断。",items:cards.value.filter(i=>i.kind==="推给你决定")}]);function refresh(){loadStrategyCatalog();loadSignalDesk()}onMounted(()=>{if(isAuthenticated.value)refresh()});watch(isAuthenticated,v=>{if(v)refresh()});
</script>
