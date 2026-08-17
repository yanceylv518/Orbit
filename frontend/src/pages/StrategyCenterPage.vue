<template>
  <section class="page active strategy-detail-page">
    <div class="page-toolbar quant-toolbar">
      <div>
        <button class="text-link back-link" @click="setActivePage('strategy')">← 返回全部策略</button>
        <span class="eyebrow">{{ isTrend ? '自动策略' : '信号策略 · 推给你决定' }}</span>
        <h2>{{ detail.name }}</h2>
        <p>{{ detail.summary }}</p>
      </div>
      <StatusBadge :text="runtimeStatus" :color="runtimeColor" />
    </div>

    <article v-if="!isTrend" class="panel strategy-section">
      <div class="panel-head"><div><span class="section-number">01</span><h3>它替我干了什么</h3><p class="muted">只统计近 30 天真实模拟账，没有了结样本时不估算成绩。</p></div></div>
      <div class="strategy-score-grid"><div><span>信号</span><b>{{ familyPerformance.signal_count || 0 }}</b></div><div><span>已了结 / 进行中</span><b>{{ familyPerformance.closed_count || 0 }} / {{ familyPerformance.open_count || 0 }}</b></div><div><span>累计结果</span><b>{{ r(familyPerformance.realized_r_total) }}</b></div><div><span>赚 / 亏</span><b>{{ familyPerformance.wins || 0 }} / {{ familyPerformance.losses || 0 }}</b></div></div>
      <MultiLineChart v-if="familyCurve.length" :data="familyCurve" :keys="['result']" :colors="['#4aa3ff']" :width="720" :height="180" />
      <div v-else class="strategy-chart-empty"><span>还没有可画的已了结样本</span><small>信号完成机械退出后，累计 R 曲线会出现在这里。</small></div>
    </article>

    <article v-if="!isTrend" class="panel strategy-section">
      <div class="panel-head"><div><span class="section-number">02</span><h3>最近它挑出的样子</h3></div></div>
      <div v-if="familySamples.length" class="strategy-sample-grid"><div v-for="sample in familySamples" :key="sample.signal_id" class="strategy-sample"><SignalCandleChart :symbol="sample.symbol" :before="sample.chart_before || []" :after="sample.simulation?.chart_after || []" :entry="Number(sample.simulation?.entry_price || sample.reference_entry_price)" :stop="Number(sample.simulation?.stop_price || sample.suggested_stop_price)" /><b>{{ sample.symbol }} · {{ simulationResult(sample) }}</b></div></div>
      <div v-else class="strategy-chart-empty"><span>还没有真实样本</span><small>不会用演示数据填充这里。</small></div>
    </article>

    <div v-if="isTrend" class="strategy-visual-grid">
      <article class="panel strategy-chart-panel">
        <div class="panel-head"><div><span class="eyebrow">运行结果</span><h3>权益曲线</h3><p class="muted">只画账本已经记录的观测；没有记录时不补造走势。</p></div></div>
        <div v-if="equityPoints.length" class="strategy-equity-chart"><MultiLineChart :data="equityPoints" :keys="['strategy','actual']" :colors="['#4aa3ff','#64d3aa']" :width="720" :height="230" /></div>
        <div v-else class="strategy-chart-empty"><span>等待第一笔权益观测</span><small>策略开始计分后，曲线会从这里生长。</small></div>
        <div class="chart-legend"><span class="strategy-line-key">策略</span><span class="actual-line-key">实际账户</span></div>
      </article>

      <article class="panel strategy-chart-panel">
        <div class="panel-head"><div><span class="eyebrow">当前持仓</span><h3>{{ chartSymbol || '价格与持仓位置' }}</h3><p class="muted">进场点、当前价和持仓方向使用当前运行快照。</p></div><select v-if="holdingRows.length > 1" v-model="chartSymbol"><option v-for="row in holdingRows" :key="row.symbol">{{ row.symbol }}</option></select></div>
        <StrategyPositionChart :points="pricePoints" :direction="selectedHolding?.direction" :entry="selectedHolding?.entry" />
        <div v-if="selectedHolding" class="holding-explanation"><strong>{{ selectedHolding.direction }} · 权重 {{ pct(selectedHolding.weight) }}</strong><span>{{ selectedHolding.reason }}</span></div>
        <div v-else class="holding-explanation"><strong>当前没有持仓</strong><span>产生下一次有效调仓或进场信号后，这里会显示真实位置。</span></div>
      </article>
    </div>

    <article class="panel strategy-control-panel">
      <div><span class="eyebrow">运行控制</span><h3>{{ runtimeStatus }}</h3><p class="muted">{{ isTrend ? '停止自动策略会立即关闭真钱执行闸门，模拟记录仍会保留。' : '这里只控制提醒扫描，不会自动下单。' }}</p></div>
      <div v-if="isAdmin" class="action-row">
        <button v-if="isTrend && trendLiveEnabled" class="button danger" :disabled="controlBusy" @click="stopTrend">停止自动策略</button>
        <button v-else-if="isTrend" class="button" @click="setActivePage('forward')">前往实盘启用</button>
        <button v-else class="button" :class="{ danger: signalEnabled }" :disabled="controlBusy" @click="toggleSignal">{{ signalEnabled ? '停用提醒' : '启用提醒' }}</button>
      </div>
      <p v-else class="muted">只有管理员可以启用或停用策略。</p>
    </article>

    <div class="strategy-rules-grid">
      <article class="panel strategy-section"><div class="panel-head"><div><span class="section-number">03</span><h3>它按什么规则做</h3></div></div><template v-if="isTrend"><dl class="plain-rule-list"><template v-for="row in trendParameters" :key="row[0]"><dt>{{ row[0] }}</dt><dd>{{ row[1] }}</dd></template></dl><p class="muted">冻结参数只读，来自后端正在运行的策略定义。</p></template><form v-else class="strategy-param-form" @submit.prevent="saveParameters"><label v-for="field in familyFields" :key="field.key"><span>{{ field.label }} <em v-if="isShared(field)">共用</em></span><small>{{ field.help }}<template v-if="isShared(field)">；这项三个信号策略共用，保存后另外两个策略同步生效。</template></small><select v-if="field.kind === 'choice'" v-model="parameterDraft[field.key]"><option v-for="choice in field.choices" :key="choice" :value="choice">{{ choice }}</option></select><input v-else v-model="parameterDraft[field.key]" type="number" :min="field.minimum" :max="field.maximum" :step="field.kind === 'int' ? 1 : 'any'"></label><label><span>变更备注</span><input v-model="parameterNote" maxlength="200"></label><div class="action-row"><button type="button" class="button ghost" @click="previewParameters">改完先回放看差异</button><button class="button" :disabled="savingParameters">保存参数</button></div><div v-if="familyPreview" class="strategy-preview"><b>当前 {{ familyPreview.before }} 条 → 改后 {{ familyPreview.after }} 条</b><span>新增 {{ familyPreview.added }} · 消失 {{ familyPreview.removed }}</span><small>这里只统计当前策略；历史回放不预测未来，真实效果由未来模拟账裁决。</small></div></form></article>
      <article class="panel strategy-section"><div class="panel-head"><div><h3>这些指标怎么理解</h3></div></div><dl class="plain-rule-list"><template v-for="row in detail.indicators" :key="row[0]"><dt>{{ row[0] }}</dt><dd>{{ row[1] }}</dd></template></dl></article>
      <article class="panel strategy-section"><div class="panel-head"><div><span class="section-number">04</span><h3>什么时候它不动作</h3></div></div><ul class="human-rule-list"><li v-for="row in detail.exclusions" :key="row">{{ row }}</li></ul></article>
    </div>

    <article v-if="!isTrend" class="panel strategy-section">
      <div class="panel-head"><div><span class="section-number">05</span><h3>刚才那一轮做了什么</h3><p class="muted">只显示最近一次成功扫描留下的真实数字。</p></div></div>
      <ol class="strategy-five-answers"><li><span>1</span><div><h4>可用市场</h4><p>通过数据与交易性准入</p></div><b>{{ latestRound.market_count || 0 }}</b></li><li><span>2</span><div><h4>初步命中</h4><p>当轮规则识别的全部信号</p></div><b>{{ latestRound.detected_count || 0 }}</b></li><li><span>3</span><div><h4>新增入账</h4><p>去重后写入模拟账</p></div><b>{{ latestRound.new_signal_count || 0 }}</b></li></ol>
    </article>

    <article class="panel strategy-process-panel">
      <div class="panel-head"><div><h3>它是怎样运转的？</h3><p class="muted">从收盘到风控停止，一个周期只做这五件事。</p></div></div>
      <ol class="strategy-five-answers"><li v-for="(step,index) in detail.steps" :key="step[0]"><span>第 {{ index + 1 }} 步</span><div><h4>{{ step[0] }}</h4><p>{{ step[1] }}</p></div></li></ol>
    </article>

    <details class="panel strategy-tech-details">
      <summary><span><b>技术详情</b><small>供排查问题使用，日常无需关注。</small></span><span>展开</span></summary>
      <div class="tech-detail-body"><dl class="plain-rule-list"><dt>策略名称</dt><dd>{{ detail.name }}</dd><dt>运行方式</dt><dd>{{ isTrend ? "自动执行" : "发出提醒，由你决定是否交易" }}</dd><dt>最近扫描</dt><dd>{{ runtimeStatus }}</dd><dt>规则指纹</dt><dd>{{ isTrend ? strategyDefinition.spec_sha256 : store.signalDesk?.operations?.scope_version || '—' }}</dd><dt>配置修订号</dt><dd>{{ store.signalDesk?.operations?.configuration?.revision ?? '—' }}</dd></dl></div>
    </details>
  </section>
</template>

<script setup>
import { computed, onMounted, ref, watch, watchEffect } from "vue";
import MultiLineChart from "../components/MultiLineChart.vue";
import StatusBadge from "../components/StatusBadge.vue";
import StrategyPositionChart from "../components/StrategyPositionChart.vue";
import SignalCandleChart from "../components/SignalCandleChart.vue";
import { controlSignalFamily, isAdmin, isAuthenticated, loadSignalDesk, loadStrategyCatalog, post, replaySignals, setActivePage, store, updateSignalConfiguration } from "../stores/appStore.js";

const slug = computed(() => store.activeRoute.split('/')[1] || 'trend');
const isTrend = computed(() => slug.value === 'trend' || slug.value === 'tb4');
const familyId = computed(() => ({ breakout:'BREAKOUT_MOMENTUM', oversold:'OVERSOLD_REBOUND', strength:'SUSTAINED_STRENGTH' })[slug.value]);
const familyControl = computed(() => store.signalDesk?.operations?.family_controls?.[familyId.value] || {});
const signalEnabled = computed(() => Boolean(familyControl.value.enabled));
const trendLiveEnabled = computed(() => Boolean(store.state?.live_execution?.enabled));
const controlBusy = ref(false);
const savingParameters=ref(false);const parameterNote=ref("");const parameterDraft=ref({});
// 按后端给出的 family 归属过滤：family 为空即三个信号策略共用，在每一页都要出现且可改。
// 不按分组标签匹配——标签是给人看的，改一次措辞就会静默清空整页参数。
const familyFields=computed(()=>(store.signalDesk?.operations?.configuration?.fields||[]).filter(field=>field.key!=="daily_push_limit"&&(!field.family||field.family===familyId.value)));
const isShared=field=>!field.family;
watch(familyFields,fields=>{parameterDraft.value=Object.fromEntries(fields.map(field=>[field.key,field.value]))},{immediate:true});
const familyPerformance=computed(()=>store.signalDesk?.rolling_30d_performance_by_family?.[familyId.value]||{});
const familyCurve=computed(()=>(familyPerformance.value.curve||[]).map(row=>({result:Number(row.cumulative_r)})));
const familySamples=computed(()=>store.signalDesk?.recent_samples_by_family?.[familyId.value]||[]);
const familyPreview=computed(()=>{const comparison=store.signalReplay?.comparison;if(!comparison||!familyId.value)return null;return{before:Number(comparison.before?.by_family?.[familyId.value]||0),after:Number(comparison.after?.by_family?.[familyId.value]||0),added:(comparison.added||[]).filter(row=>row.family===familyId.value||row.family_id===familyId.value).length,removed:(comparison.removed||[]).filter(row=>row.family===familyId.value||row.family_id===familyId.value).length}});
const latestRound=computed(()=>store.signalDesk?.operations?.latest_round||{});
const strategyDefinition=computed(()=>store.selectedStrategy||{});
const trendParameters=computed(()=>{const display=strategyDefinition.value.display||{};return [["观察周期",(display.momentum_lookback_days||[]).join(" / ")+"天"],["波动观察",`${display.volatility_lookback_days??"—"}天`],["调仓间隔",`${display.rebalance_days??"—"}天`],["目标组合波动",`${display.target_portfolio_vol_pct??"—"}%`],["总仓位上限",`${display.gross_cap_pct??"—"}%`]]});
const detail=computed(()=>{if(!isTrend.value)return store.signalDesk?.operations?.strategy_families?.[familyId.value]||{name:"信号策略",summary:"服务未部署，暂时无法读取规则。",indicators:[],exclusions:[],steps:[]};const mechanics=strategyDefinition.value.mechanics||[];return{name:strategyDefinition.value.name||"多周期趋势",summary:strategyDefinition.value.summary||"策略定义暂时不可用。",indicators:mechanics.map(row=>[row.title,row.body]),exclusions:strategyDefinition.value.known_risks||[],steps:mechanics.map(row=>[row.title,row.body])}});
const trend = computed(() => store.state?.trend_forward || {});
const equity = computed(() => store.state?.live_reconciliation?.equity || {});
const equityPoints = computed(() => (equity.value.points || []).map(row => ({ strategy:Number(row.paper_normalized), actual:Number(row.live_normalized) })).filter(row => Number.isFinite(row.strategy) && Number.isFinite(row.actual)));
const holdingRows = computed(() => isTrend.value ? Object.entries(trend.value.runner?.weights || {}).filter(([,weight]) => Math.abs(Number(weight)) > 1e-9).map(([symbol,weight]) => ({ symbol, weight:Number(weight), direction:Number(weight)>0?'做多':'做空', entry:null, reason:'多个时间尺度的趋势投票决定方向，近期波动决定权重。' })) : []);
const chartSymbol = ref('');
watchEffect(() => { if (!holdingRows.value.some(row => row.symbol === chartSymbol.value)) chartSymbol.value = holdingRows.value[0]?.symbol || ''; });
const selectedHolding = computed(() => holdingRows.value.find(row => row.symbol === chartSymbol.value));
const pricePoints = computed(() => (store.state?.price_history?.[chartSymbol.value] || []).map(row => ({ time:row.timestamp || row.tick, price:Number(row.price) })).filter(row => Number.isFinite(row.price)));
const runtimeStatus = computed(() => {if(isTrend.value)return !store.state?.trend_forward?'状态未知':trend.value.status==='NOT_STARTED'?'尚未启动':trend.value.data_fresh===false?'已启动但数据超时':'运行中';const service=store.signalDesk?.operations?.service;if(!service)return'未部署 / 状态未知';if(!signalEnabled.value||!service.enabled)return`已停用${familyControl.value.disabled_reason?`：${familyControl.value.disabled_reason}`:''}`;return service.running&&service.market_data_fresh?'扫描正常运行':'已启用但超过 30 分钟没有成功扫描'});
const runtimeColor = computed(() => /正常运行|运行中/.test(runtimeStatus.value) ? 'green' : /30 分钟|超时/.test(runtimeStatus.value)?'red':'orange');
const detailReplayRoute = computed(() => isTrend.value ? 'review' : 'signals');
const pct = value => `${(Number(value || 0) * 100).toFixed(1)}%`;
const r=value=>value===null||value===undefined?"—":`${Number(value)>=0?"+":""}${Number(value).toFixed(2)}R`;
const simulationResult=sample=>sample.simulation?.status==="CLOSED"?r(sample.simulation.realized_r):sample.simulation?.status==="OPEN"?"进行中":"等待进场";
function changedValues(){return Object.fromEntries(familyFields.value.map(field=>[field.key,field.kind==="choice"?parameterDraft.value[field.key]:Number(parameterDraft.value[field.key])]).filter(([key,value])=>value!==familyFields.value.find(field=>field.key===key)?.value))}
async function saveParameters(){const values=changedValues();if(!Object.keys(values).length)return;savingParameters.value=true;try{await updateSignalConfiguration(values,parameterNote.value);parameterNote.value="";await loadSignalDesk()}finally{savingParameters.value=false}}
async function previewParameters(){const values=changedValues();await replaySignals(7,Object.keys(values).length?values:null)}
function refresh(){ loadStrategyCatalog(); loadSignalDesk(); }
async function toggleSignal(){
  const enabled=!signalEnabled.value;
  const reason=enabled?'重新启用':prompt('请填写停用原因，停用后会显示在策略页与配置页。','管理员从策略详情页停用');
  if(!enabled&&!reason?.trim())return;
  controlBusy.value=true;try{await controlSignalFamily(familyId.value,enabled,reason?.trim()||null);await loadSignalDesk();}finally{controlBusy.value=false;}
}
async function stopTrend(){
  if(!confirm('确认停止自动策略？这会关闭真钱执行，现有持仓不会在此页面自动平仓。'))return;
  if(!confirm('再次确认：立即停止自动执行？'))return;
  const reason=prompt('请填写停用原因，供以后查看。','管理员从策略详情页停用');
  if(!reason?.trim())return;
  controlBusy.value=true;try{await post('/api/admin/live-execution/emergency-stop',{reason:reason.trim()});}finally{controlBusy.value=false;}
}
onMounted(() => { if(isAuthenticated.value) refresh(); });
watch(isAuthenticated, value => { if(value) refresh(); });
</script>
<style scoped>
.strategy-score-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}.strategy-score-grid>div{display:grid;gap:5px;padding:14px;background:#0b1525;border:1px solid #1b2d49;border-radius:9px}.strategy-score-grid span,.strategy-param-form small{color:#8293aa}.strategy-score-grid b{font-size:22px}.strategy-sample-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}.strategy-sample{background:#0b1525;border:1px solid #1b2d49;border-radius:9px;padding:10px}.strategy-param-form{display:grid;gap:10px}.strategy-param-form label{display:grid;grid-template-columns:minmax(150px,1fr) minmax(220px,2fr) minmax(110px,1fr);gap:10px;align-items:center;border-top:1px solid #1b2d49;padding-top:10px}.strategy-param-form em{font-style:normal;color:#e2ad59;border:1px solid #765724;border-radius:5px;padding:2px 5px;font-size:11px}.strategy-param-form input,.strategy-param-form select{background:#081321;border:1px solid #29405f;color:#e9f0fa;border-radius:6px;padding:8px}@media(max-width:700px){.strategy-score-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.strategy-sample-grid{grid-template-columns:1fr}.strategy-param-form label{grid-template-columns:1fr;gap:5px}}
</style>
