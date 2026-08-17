<template>
  <section class="page active strategy-detail-page">
    <div class="page-toolbar quant-toolbar">
      <div>
        <button class="text-link back-link" @click="setActivePage('strategy')">← 返回全部策略</button>
        <span class="eyebrow">{{ isTrend ? '自动策略' : '信号策略 · 推给你决定' }}</span>
        <h2>{{ detail.name }}</h2>
        <p class="detail-summary">{{ detail.summary }}</p>
      </div>
      <div class="strategy-status-stack"><StatusBadge :text="runtimeStatus" :color="runtimeColor" /><small>{{ runtimeContext }}</small></div>
    </div>

    <article v-if="!isTrend" class="panel strategy-understanding compact-panel">
      <div class="panel-head"><div><h3>策略说明</h3></div></div>
      <div class="strategy-explain-grid"><div><span>寻找</span><b>{{ detail.thesis }}</b></div><div><span>命中标准</span><b>{{ detail.success }}</b></div><div><span>需要避开</span><b>{{ detail.falsePositive }}</b></div><div><span>命中以后</span><b>{{ detail.tradeFlow }}</b></div></div>
    </article>

    <article v-if="!isTrend" class="panel strategy-section compact-panel">
      <div class="panel-head"><div><h3>近 30 天表现</h3></div></div>
      <div class="strategy-score-grid"><div><span>信号</span><b>{{ familyPerformance.signal_count || 0 }}</b></div><div><span>已了结 / 进行中</span><b>{{ familyPerformance.closed_count || 0 }} / {{ familyPerformance.open_count || 0 }}</b></div><div><span>累计结果</span><b>{{ r(familyPerformance.realized_r_total) }}</b></div><div><span>赚 / 亏</span><b>{{ familyPerformance.wins || 0 }} / {{ familyPerformance.losses || 0 }}</b></div></div>
      <MultiLineChart v-if="familyCurve.length" :data="familyCurve" :keys="['result']" :colors="['#4aa3ff']" :width="720" :height="180" />
      <div v-else class="strategy-chart-empty"><span>还没有可画的已了结样本</span><small>信号完成机械退出后，累计 R 曲线会出现在这里。</small></div>
    </article>

    <article v-if="!isTrend" class="panel strategy-section">
      <div class="panel-head"><div><h3>最近样本</h3></div></div>
      <div v-if="familySamples.length" class="strategy-sample-grid"><div v-for="sample in familySamples" :key="sample.signal_id" class="strategy-sample"><SignalCandleChart :symbol="sample.symbol" :before="sample.chart_before || []" :after="sample.simulation?.chart_after || []" :entry="Number(sample.simulation?.entry_price || sample.reference_entry_price)" :stop="Number(sample.simulation?.stop_price || sample.suggested_stop_price)" /><b>{{ sample.symbol }} · {{ simulationResult(sample) }}</b></div></div>
      <div v-else class="strategy-chart-empty"><span>还没有真实样本</span><small>不会用演示数据填充这里。</small></div>
    </article>

    <div v-if="isTrend" class="strategy-visual-grid">
      <article class="panel strategy-trend-score"><div class="panel-head"><div><span class="section-number">01</span><h3>它替我干了什么</h3><p class="muted">收益和回撤只来自前向账本与真实账户观测。</p></div></div><div class="strategy-score-grid"><div><span>策略累计</span><b>{{ trendMetric(trendScore.paperReturn, '%') }}</b></div><div><span>实际账户</span><b>{{ trendMetric(trendScore.liveReturn, '%') }}</b></div><div><span>策略 / 实盘回撤</span><b>{{ trendMetric(trendScore.paperDrawdown, '%') }} / {{ trendMetric(trendScore.liveDrawdown, '%') }}</b></div><div><span>前向进度</span><b>{{ trendProgress }}</b></div></div></article>
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

      <article class="panel strategy-holdings-panel"><div class="panel-head"><div><span class="section-number">02</span><h3>现在持有什么</h3><p class="muted">正权重做多、负权重做空；没有方向的币也明确列出。</p></div></div><div class="strategy-holdings"><div v-for="row in allHoldingRows" :key="row.symbol"><b>{{ row.symbol }}</b><span :class="row.directionClass">{{ row.direction }}</span><strong>{{ pct(row.weight) }}</strong><i><em :class="row.weight >= 0 ? 'long' : 'short'" :style="{width: `${Math.min(100,Math.abs(row.weight)*100)}%`}"></em></i><small>{{ row.reason }}</small></div></div></article>
    </div>

    <article class="panel strategy-control-panel">
      <div><span class="eyebrow">运行控制</span><h3>{{ runtimeStatus }}</h3></div>
      <div v-if="isAdmin" class="action-row">
        <button v-if="isTrend && trendLiveEnabled" class="button danger" :disabled="controlBusy" @click="stopTrend">停止自动策略</button>
        <button v-else-if="isTrend" class="button" @click="setActivePage('forward')">前往实盘启用</button>
        <button v-else class="button" :class="{ danger: signalEnabled }" :disabled="controlBusy" @click="toggleSignal">{{ signalEnabled ? '停用提醒' : '启用提醒' }}</button>
      </div>
      <p v-else class="muted">只有管理员可以启用或停用策略。</p>
    </article>

    <div class="strategy-rules-grid">
      <article class="panel strategy-section"><div class="panel-head"><div><h3>生效参数</h3><p v-if="!isTrend && familyFields.some(isShared)" class="muted">“共用”参数会同步影响三个信号策略。</p></div></div><template v-if="isTrend"><dl class="plain-rule-list"><template v-for="row in trendParameters" :key="row[0]"><dt>{{ row[0] }}</dt><dd>{{ row[1] }}</dd></template></dl><p class="muted">冻结参数只读 · 指纹 {{ shortHash(strategyDefinition.spec_sha256) }}</p></template><form v-else-if="familyFields.length" class="strategy-param-form" @submit.prevent="saveParameters"><label v-for="field in familyFields" :key="field.key"><span>{{ field.label }} <em v-if="isShared(field)">共用</em></span><small>{{ field.help }}<i>{{ displayFieldValue(field, field.minimum) }} – {{ displayFieldValue(field, field.maximum) }}</i></small><select v-if="field.kind === 'choice'" v-model="parameterDraft[field.key]"><option v-for="choice in field.choices" :key="choice" :value="choice">{{ choiceLabel(choice) }}</option></select><input v-else v-model="parameterDraft[field.key]" type="number" :min="field.minimum" :max="field.maximum" :step="field.kind === 'int' ? 1 : 'any'"></label><label class="param-note"><span>变更备注</span><small>记录这次为什么调整，便于以后追溯。</small><input v-model="parameterNote" maxlength="200" placeholder="例如：放宽放量门槛，观察两周"></label><div class="action-row"><button type="button" class="button ghost" :disabled="!hasParameterChanges||store.signalReplayBusy" @click="previewParameters">预览差异</button><button class="button" :disabled="savingParameters||!hasParameterChanges">保存参数</button></div><div v-if="familyPreview" class="strategy-preview"><b>{{ familyPreview.before }} 条 → {{ familyPreview.after }} 条</b><span>新增 {{ familyPreview.added }} · 消失 {{ familyPreview.removed }}</span></div></form><div v-else class="strategy-chart-empty"><span>暂时无法读取当前生效参数</span><small>请检查信号服务。</small></div></article>
      <article class="panel strategy-section"><div class="panel-head"><div><h3>判断指标</h3></div></div><dl v-if="detail.indicators.length" class="plain-rule-list indicator-list"><template v-for="row in detail.indicators" :key="row[0]"><dt>{{ row[0] }}</dt><dd>{{ row[1] }}<strong v-if="indicatorEvidence[row[0]]">{{ indicatorEvidence[row[0]] }}</strong></dd></template></dl><div v-else class="strategy-chart-empty"><span>暂时无法读取指标定义</span></div></article>
      <article class="panel strategy-section"><div class="panel-head"><div><h3>排除条件</h3></div></div><ul class="human-rule-list"><li v-for="row in detail.exclusions" :key="row">{{ row }}</li></ul></article>
    </div>

    <details v-if="!isTrend" class="panel strategy-tech-details">
      <summary><span><b>最近一轮扫描</b><small>查看市场、命中、入账和推送数量</small></span><span>展开</span></summary>
      <div class="tech-detail-body">
      <div v-if="latestRound.available"><ol class="strategy-five-answers round-summary"><li><span>1</span><div><h4>可用市场</h4><p>三个策略共用的本轮币池</p></div><b>{{ valueOrDash(latestRound.market_count) }}</b></li><li><span>2</span><div><h4>本策略初步命中</h4><p>规则识别出的全部机会</p></div><b>{{ valueOrDash(latestRound.detected_count) }}</b></li><li><span>3</span><div><h4>通过人工候选筛选</h4><p>进入当日可处理范围</p></div><b>{{ valueOrDash(latestRound.included_count) }}</b></li><li><span>4</span><div><h4>写入模拟账</h4><p>去重后不可覆盖地记录</p></div><b>{{ valueOrDash(latestRound.recorded_count) }}</b></li><li><span>5</span><div><h4>成功推送</h4><p>投递限制不会删除模拟记录</p></div><b>{{ valueOrDash(latestRound.pushed_count) }}</b></li></ol><p v-if="!latestRound.complete_family_counts" class="honesty-note">这轮来自旧版扫描记录，无法可靠拆出当前策略的“初步命中”数量；缺失项显示为 —。</p></div><div v-else class="strategy-chart-empty"><span>还没有成功扫描记录</span><small>这里不会把缺失数据显示成 0。</small></div>
      </div>
    </details>

    <details class="panel strategy-tech-details">
      <summary><span><b>运行流程</b><small>查看策略每轮如何处理</small></span><span>展开</span></summary>
      <div class="tech-detail-body"><ol class="strategy-five-answers"><li v-for="(step,index) in detail.steps" :key="stepTitle(step)"><span>{{ index + 1 }}</span><div><h4>{{ stepTitle(step) }}</h4><p>{{ stepBody(step) }}</p></div></li></ol></div>
    </details>

    <details class="panel strategy-tech-details">
      <summary><span><b>技术详情</b><small>供排查问题使用，日常无需关注。</small></span><span>展开</span></summary>
      <div class="tech-detail-body"><dl class="plain-rule-list"><dt>策略名称</dt><dd>{{ detail.name }}</dd><dt>运行方式</dt><dd>{{ isTrend ? "自动执行" : "发出提醒，由你决定是否交易" }}</dd><dt>进程与新鲜度</dt><dd>{{ runtimeStatus }}</dd><dt>最近成功</dt><dd>{{ isTrend ? time(trend.runner?.last_close_time_ms) : time(store.signalDesk?.operations?.service?.last_scan_at_ms) }}</dd><dt>最近失败</dt><dd>{{ latestFailure }}</dd><dt>规则指纹</dt><dd>{{ isTrend ? strategyDefinition.spec_sha256 : store.signalDesk?.operations?.scope_version || '—' }}</dd><dt>定义哈希</dt><dd>{{ isTrend ? strategyDefinition.definition_hash || '—' : '—' }}</dd><dt>配置修订号</dt><dd>{{ store.signalDesk?.operations?.configuration?.revision ?? '—' }}</dd><dt>账本记录 / 链头</dt><dd>{{ ledgerDiagnostic }}</dd><dt v-if="isTrend">前向起点 / 进度</dt><dd v-if="isTrend">{{ trend.started_at || '—' }} · {{ trendProgress }}</dd></dl></div>
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
const latestRound=computed(()=>store.signalDesk?.operations?.latest_round_by_family?.[familyId.value]||{});
const strategyDefinition=computed(()=>store.selectedStrategy||{});
const trendParameters=computed(()=>{const display=strategyDefinition.value.display||{};return [["观察周期",(display.momentum_lookback_days||[]).join(" / ")+"天"],["波动观察",`${display.volatility_lookback_days??"—"}天`],["调仓间隔",`${display.rebalance_days??"—"}天`],["目标组合波动",`${display.target_portfolio_vol_pct??"—"}%`],["总仓位上限",`${display.gross_cap_pct??"—"}%`]]});
const detail=computed(()=>{if(!isTrend.value)return store.signalDesk?.operations?.strategy_families?.[familyId.value]||{name:"信号策略",summary:"服务未部署，暂时无法读取规则。",thesis:"规则定义尚未从信号服务返回。",success:"暂时无法判断。",falsePositive:"暂时无法判断。",tradeFlow:"信号只提醒，不自动下单。",indicators:[],exclusions:[],steps:[]};const mechanics=strategyDefinition.value.mechanics||[];return{name:strategyDefinition.value.name||"多周期趋势",summary:strategyDefinition.value.summary||"策略定义暂时不可用。",indicators:mechanics.slice(0,5).map(row=>[row.title,row.body]),exclusions:strategyDefinition.value.known_risks||[],steps:mechanics}});
const trend = computed(() => store.state?.trend_forward || {});
const equity = computed(() => store.state?.live_reconciliation?.equity || {});
const equityPoints = computed(() => (equity.value.points || []).map(row => ({ strategy:Number(row.paper_normalized), actual:Number(row.live_normalized) })).filter(row => Number.isFinite(row.strategy) && Number.isFinite(row.actual)));
const holdingRows = computed(() => isTrend.value ? Object.entries(trend.value.runner?.weights || {}).filter(([,weight]) => Math.abs(Number(weight)) > 1e-9).map(([symbol,weight]) => ({ symbol, weight:Number(weight), direction:Number(weight)>0?'做多':'做空', entry:null, reason:'多个时间尺度的趋势投票决定方向，近期波动决定权重。' })) : []);
const allHoldingRows=computed(()=>{const weights=trend.value.runner?.weights||{};const symbols=strategyDefinition.value.spec?.symbols||Object.keys(weights);return symbols.map(symbol=>{const weight=Number(weights[symbol]||0);return{symbol,weight,direction:weight>0?'做多':weight<0?'做空':'无方向',directionClass:weight>0?'positive':weight<0?'negative':'muted',reason:weight===0?'多个时间尺度互相冲突，当前不持仓。':'方向由多尺度趋势投票决定，仓位按近期波动缩放。'}})});
const chartSymbol = ref('');
watchEffect(() => { if (!holdingRows.value.some(row => row.symbol === chartSymbol.value)) chartSymbol.value = holdingRows.value[0]?.symbol || ''; });
const selectedHolding = computed(() => holdingRows.value.find(row => row.symbol === chartSymbol.value));
const pricePoints = computed(() => (store.state?.price_history?.[chartSymbol.value] || []).map(row => ({ time:row.timestamp || row.tick, price:Number(row.price) })).filter(row => Number.isFinite(row.price)));
const trendScore=computed(()=>{const points=equity.value.points||[],last=points.at(-1)||{};return{paperReturn:last.paper_normalized==null?null:(Number(last.paper_normalized)-1)*100,liveReturn:last.live_normalized==null?null:(Number(last.live_normalized)-1)*100,paperDrawdown:equity.value.paper_drawdown_pct,liveDrawdown:equity.value.live_drawdown_pct}});
const trendProgress=computed(()=>trend.value.elapsed_days==null?'—':`${trend.value.elapsed_days} / ${trend.value.minimum_forward_days||365} 天`);
const runtimeStatus = computed(() => {if(isTrend.value)return !store.state?.trend_forward?'状态未知':trend.value.status==='NOT_STARTED'?'尚未启动':trend.value.data_fresh===false?'已启动但数据超时':'运行中';const service=store.signalDesk?.operations?.service;if(!service)return'未部署 / 状态未知';if(!signalEnabled.value||!service.enabled)return`已停用${familyControl.value.disabled_reason?`：${familyControl.value.disabled_reason}`:''}`;return service.running&&service.market_data_fresh?'扫描正常运行':'已启用但超过 30 分钟没有成功扫描'});
const runtimeColor = computed(() => /正常运行|运行中/.test(runtimeStatus.value) ? 'green' : /30 分钟|超时/.test(runtimeStatus.value)?'red':'orange');
const runtimeContext=computed(()=>isTrend.value?`最近推进 ${time(trend.value.runner?.last_close_time_ms)} · ${trendProgress.value}`:`最近扫描 ${time(store.signalDesk?.operations?.service?.last_scan_at_ms)}`);
const pct = value => `${(Number(value || 0) * 100).toFixed(1)}%`;
const r=value=>value===null||value===undefined?"—":`${Number(value)>=0?"+":""}${Number(value).toFixed(2)}R`;
const simulationResult=sample=>sample.simulation?.status==="CLOSED"?r(sample.simulation.realized_r):sample.simulation?.status==="OPEN"?"进行中":"等待进场";
function changedValues(){return Object.fromEntries(familyFields.value.map(field=>[field.key,field.kind==="choice"?parameterDraft.value[field.key]:Number(parameterDraft.value[field.key])]).filter(([key,value])=>value!==familyFields.value.find(field=>field.key===key)?.value))}
const hasParameterChanges=computed(()=>Object.keys(changedValues()).length>0);
const latestSample=computed(()=>familySamples.value[0]||{});
const indicatorEvidence=computed(()=>{const sample=latestSample.value,reason=sample.reason||{};if(!sample.signal_id)return{};if(familyId.value==='BREAKOUT_MOMENTUM')return{'通道高点':`最近样本：回看 ${reason.channel_lookback_candles??'—'} 根`,'成交量比':`实际 ${number(reason.relative_quote_volume)} 倍 / 门槛 ${number(reason.minimum_relative_quote_volume)} 倍`,'趋势强度':`记录值 ${number(sample.trend_strength_96)}`};if(familyId.value==='OVERSOLD_REBOUND')return{'短期跌幅':`实际 ${percentValue(reason.drop_fraction)} / 门槛 ${percentValue(reason.minimum_drop_fraction)}`,'长周期方向':`实际 ${choiceLabel(reason.long_cycle_state)}`,'双重高点':`中期回撤 ${percentValue(reason.drawdown_from_high)} · 起点回撤 ${percentValue(reason.start_drawdown_from_high)}`};return{'趋势强度':`记录值 ${number(sample.trend_strength_96)} · 要求分位 ${percentValue(reason.trend_strength_quantile)}`,'持续量比':`实际 ${number(reason.volume_ratio_3d_10d)} 倍`,'距高点比例':`实际 ${percentValue(reason.distance_from_high)}`}});
const latestFailure=computed(()=>{const failure=store.signalDesk?.operations?.diagnostics?.latest_failure;return failure?`${time(failure.recorded_at_ms)} · ${failure.error_type||'未知错误'}`:'没有记录到失败'});
const ledgerDiagnostic=computed(()=>{const d=store.signalDesk?.operations?.diagnostics;if(!d)return'—';return`${d.ledger_event_count??'—'} 条 · ${shortHash(d.ledger_head_hash)}`});
const choiceLabel=value=>({UP:'上升',RANGE:'震荡',DOWN:'下跌'}[value]||value||'—');
const percentKeys=new Set(['pullback_drop','collapse_drawdown','pullback_start_drawdown','strength_quantile','strength_high_distance']);
const moneyKeys=new Set(['liquidity_minimum']);
function displayFieldValue(field,value){if(value===null||value===undefined)return'—';if(field.kind==='choice')return choiceLabel(value);if(moneyKeys.has(field.key))return`${Number(value).toLocaleString('zh-CN')} USDT`;if(percentKeys.has(field.key))return`${(Number(value)*100).toFixed(1)}%`;if(/days/.test(field.key))return`${value} 天`;if(/candles|channel|return_candles/.test(field.key))return`${value} 根`;if(/hours/.test(field.key))return`${value} 小时`;return String(value)}
const time=value=>value?new Date(Number(value)).toLocaleString('zh-CN',{hour12:false}):'—';
const shortHash=value=>value?`${String(value).slice(0,10)}…`:'—';
const number=value=>value===null||value===undefined?'—':Number(value).toFixed(2);
const percentValue=value=>value===null||value===undefined?'—':`${(Number(value)*100).toFixed(1)}%`;
const valueOrDash=value=>value===null||value===undefined?'—':value;
const trendMetric=(value,suffix='')=>value===null||value===undefined?'—':`${Number(value)>=0?'+':''}${Number(value).toFixed(2)}${suffix}`;
const stepTitle=step=>Array.isArray(step)?step[0]:step.title;
const stepBody=step=>Array.isArray(step)?step[1]:step.body;
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
.strategy-score-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}.strategy-score-grid>div{display:grid;gap:4px;padding:11px 12px;background:#0b1525;border:1px solid #1b2d49;border-radius:9px}.strategy-score-grid span,.strategy-param-form small{color:#8293aa}.strategy-score-grid b{font-size:20px}.strategy-sample-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}.strategy-sample{background:#0b1525;border:1px solid #1b2d49;border-radius:9px;padding:8px}.strategy-sample b{font-size:13px}.strategy-param-form{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:0 18px;align-items:start}
.strategy-status-stack{display:grid;justify-items:end;gap:6px;text-align:right}.strategy-status-stack small{color:#8293aa}.strategy-explain-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.strategy-explain-grid>div{display:grid;gap:5px;padding:12px;border:1px solid #1b2d49;border-radius:8px;background:#0b1525}.strategy-explain-grid span{color:#70adf6;font-size:12px}.strategy-explain-grid b{font-size:13px;line-height:1.6}.strategy-trend-score,.strategy-holdings-panel{grid-column:1/-1}.strategy-holdings{display:grid}.strategy-holdings>div{display:grid;grid-template-columns:110px 60px 75px minmax(100px,1fr) minmax(240px,1.4fr);align-items:center;gap:12px;padding:9px 0;border-top:1px solid #1b2d49}.strategy-holdings>div:first-child{border-top:0}.strategy-holdings i{height:8px;background:#15233a;border-radius:999px;overflow:hidden}.strategy-holdings i em{display:block;height:100%;border-radius:inherit}.strategy-holdings i .long{background:#64d3aa}.strategy-holdings i .short{background:#ef6a79}.strategy-holdings small{color:#8293aa}.indicator-list dd{display:grid;gap:5px}.indicator-list strong{color:#dce9f8;font-size:12px}.strategy-param-form small i{display:block;margin-top:3px;color:#a8b8cc;font-style:normal}
/* 每项一格：名称与输入同一行，说明在下方整行——10 项参数占 5 行而不是 10 行。 */
.strategy-param-form label{display:grid;grid-template-columns:minmax(0,1fr) 116px;gap:3px 10px;align-items:center;border-top:1px solid #1b2d49;padding:8px 0}
.strategy-param-form label>span{grid-area:1/1;font-weight:600;font-size:13px}
.strategy-param-form label>small{grid-area:2/1/3/3;font-size:12px;line-height:1.45}
.strategy-param-form label>input,.strategy-param-form label>select{grid-area:1/2}
.strategy-param-form>label.param-note{grid-column:1/-1;grid-template-columns:minmax(0,120px) minmax(0,1fr)}
.strategy-param-form>div{grid-column:1/-1;margin-top:10px}.strategy-param-form em{font-style:normal;color:#e2ad59;border:1px solid #765724;border-radius:5px;padding:2px 5px;font-size:11px}.strategy-param-form input,.strategy-param-form select{background:#081321;border:1px solid #29405f;color:#e9f0fa;border-radius:6px;padding:8px}@media(max-width:700px){.strategy-status-stack{justify-items:start;text-align:left}.strategy-score-grid,.strategy-explain-grid{grid-template-columns:1fr}.strategy-sample-grid{grid-template-columns:1fr}.strategy-param-form{grid-template-columns:1fr}.strategy-param-form label,.strategy-param-form>label.param-note{grid-template-columns:minmax(0,1fr) 110px}.strategy-holdings>div{grid-template-columns:1fr auto auto}.strategy-holdings i,.strategy-holdings small{grid-column:1/-1}}
</style>
