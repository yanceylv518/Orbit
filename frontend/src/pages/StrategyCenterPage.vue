<template>
  <section class="page active strategy-detail-page">
    <div class="page-toolbar quant-toolbar">
      <div>
        <button class="text-link back-link" @click="setActivePage('strategy')">← 返回全部策略</button>
        <span class="eyebrow">{{ definition.kind }}</span>
        <h2>{{ definition.name }}</h2>
        <p>{{ definition.summary }}</p>
      </div>
      <StatusBadge :text="runtimeStatus" :color="runtimeColor" />
    </div>

    <div class="strategy-visual-grid">
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

    <article class="panel strategy-section">
      <div class="panel-head"><div><span class="section-number">01</span><h3>这个策略在找什么</h3></div><button class="button ghost small" @click="setActivePage(detailReplayRoute)">查看回放</button></div>
      <p class="strategy-lead">{{ definition.finds }}</p>
      <div class="sample-pair"><div class="sample-card success"><b>符合</b><span>{{ definition.success }}</span></div><div class="sample-card failure"><b>不符合</b><span>{{ definition.failure }}</span></div></div>
    </article>

    <div class="strategy-rules-grid">
      <article class="panel strategy-section"><div class="panel-head"><div><span class="section-number">02</span><h3>用到哪些指标</h3></div></div><dl class="plain-rule-list"><template v-for="row in definition.indicators" :key="row[0]"><dt>{{ row[0] }}</dt><dd>{{ row[1] }}</dd></template></dl></article>
      <article class="panel strategy-section"><div class="panel-head"><div><span class="section-number">03</span><h3>参数取什么值</h3></div></div><dl class="plain-rule-list"><template v-for="row in definition.parameters" :key="row[0]"><dt>{{ row[0] }}</dt><dd>{{ row[1] }}</dd></template></dl><div class="param-action"><button v-if="!isTrend" class="button ghost small" @click="setActivePage('signals')">去配置面板调整</button><p v-else class="muted">这些值与正在运行的自动交易绑定，页面上只读；调整需重新授权运行。</p></div></article>
      <article class="panel strategy-section"><div class="panel-head"><div><span class="section-number">04</span><h3>找信号之前排除什么</h3></div></div><ul class="human-rule-list"><li v-for="row in definition.before" :key="row">{{ row }}</li></ul></article>
      <article class="panel strategy-section"><div class="panel-head"><div><span class="section-number">05</span><h3>找到信号之后筛掉什么</h3></div></div><ul class="human-rule-list"><li v-for="row in definition.after" :key="row">{{ row }}</li></ul></article>
      <article class="panel strategy-section"><div class="panel-head"><div><span class="section-number">06</span><h3>怎样进场与出场</h3></div></div><ol class="entry-exit-list"><li v-for="row in definition.trading" :key="row">{{ row }}</li></ol></article>
    </div>

    <article class="panel strategy-process-panel">
      <div class="panel-head"><div><h3>它是怎样运转的？</h3><p class="muted">从收盘到风控停止，一个周期只做这五件事。</p></div></div>
      <ol class="strategy-five-answers"><li v-for="(step,index) in definition.steps" :key="step[0]"><span>第 {{ index + 1 }} 步</span><div><h4>{{ step[0] }}</h4><p>{{ step[1] }}</p></div></li></ol>
    </article>

    <details class="panel strategy-tech-details">
      <summary><span><b>技术详情</b><small>供排查问题使用，日常无需关注。</small></span><span>展开</span></summary>
      <div class="tech-detail-body"><dl class="plain-rule-list"><dt>策略编号</dt><dd>{{ slug }}</dd><dt>运行方式</dt><dd>{{ isTrend ? "自动执行" : "发出提醒，由你决定是否交易" }}</dd><dt>数据来源</dt><dd>Binance USDT 永续合约，仅使用已收盘 K 线</dd></dl></div>
    </details>
  </section>
</template>

<script setup>
import { computed, onMounted, ref, watch, watchEffect } from "vue";
import MultiLineChart from "../components/MultiLineChart.vue";
import StatusBadge from "../components/StatusBadge.vue";
import StrategyPositionChart from "../components/StrategyPositionChart.vue";
import { controlSignalService, isAdmin, isAuthenticated, loadSignalDesk, loadStrategyCatalog, post, setActivePage, store } from "../stores/appStore.js";

const slug = computed(() => store.activeRoute.split('/')[1] || 'trend');
const isTrend = computed(() => slug.value === 'trend' || slug.value === 'tb4');
const signalEnabled = computed(() => Boolean(store.signalDesk?.operations?.service?.enabled));
const trendLiveEnabled = computed(() => Boolean(store.state?.live_execution?.enabled));
const controlBusy = ref(false);
const definitions = {
  trend: { name:'多周期趋势', kind:'自动策略', summary:'跟随多个市场的中长期方向，并按风险分配仓位。', finds:'寻找多个时间尺度方向一致、且风险可以被组合承受的上涨或下跌趋势。', success:'不同时间尺度多数同向，波动可控，组合中没有单一市场过重。', failure:'方向来回反转、多个时间尺度互相冲突，或组合风险已经过高。', indicators:[['趋势投票','分别观察五段历史的涨跌，多数意见决定方向。'],['近期波动','价格跳动越大，分到的仓位越小。'],['组合风险','把所有持仓放在一起检查，避免总体波动失控。']], before:['只使用已经收盘的 4 小时价格。','只看目录内可交易的永续合约。','数据未对齐或缺失时不产生新仓位。'], after:['总仓位价值不能超过账户资金。','单个市场按波动缩小权重。','账户回撤触及 30% 停止线时停止新增风险。'], trading:['每 7 天计算一次新的目标仓位。','下一根完整 4 小时周期按目标差额调整。','趋势转向时反向；没有方向时降为零仓位。','触及账户停止线时停止执行。'], parameters:[['观察周期','14 / 28 / 56 / 84 / 168 天'],['波动观察','28 天'],['调仓间隔','7 天'],['目标组合波动','年化 10%'],['总仓位上限','资金的 100%']], steps:[['收完一根 K 线','每 4 小时只读取已经结束的行情。'],['逐个判断方向','对每个市场分别询问五个时间尺度最近在涨还是在跌。'],['计算下周仓位','按投票方向和各市场波动大小分配权重。'],['统一调仓','每 7 天按新目标自动调整一次。'],['守住停止线','实盘按 3 倍风险投影运行，亏损触及 30% 时自动停止。']] },
  breakout: { name:'放量突破', kind:'信号策略', summary:'价格冲出近期区间且成交明显活跃时发出提醒。', finds:'寻找价格带着明显成交量突破近期高点的时刻。', success:'突破后价格站稳区间外，成交量同时放大。', failure:'只有瞬间刺穿、收盘回到区间内，或成交没有配合。', indicators:[['通道高点','近期价格曾到达的最高位置。'],['成交量比','当前成交量相对平时放大了多少。'],['趋势强度','判断突破是不是顺着更大的方向。'],['真实波幅','用近期日常波动决定止损距离。']], before:['市场仍可正常交易且数据连续。','大方向不能明显向下。','黑名单中的市场不参与。'], after:['同一天提醒达到上限后不再推送。','同一市场冷却期内不重复提醒。','多个机会同时出现时，优先保留更强的。'], trading:['信号后的下一根 K 线开盘作为计划进场。','止损放在按真实波幅计算的保护位置。','先触及止损则退出，否则到最长持有时间退出。'], parameters:[['回放与筛选值','由用户在信号配置面板设置'],['每日提醒上限','以当前配置为准'],['不可修改项','成交顺序与账本规则用于保证回放一致']], steps:[['等待收盘','只在一根完整 K 线结束后判断。'],['检查突破','确认价格是否真正离开近期区间。'],['检查成交','确认市场参与度同步放大。'],['排序提醒','通过过滤后按强弱保留机会。'],['跟踪结果','记录进场、止损与退出，供以后回放。']] },
  oversold: { name:'高位回调', kind:'信号策略', summary:'上涨途中的一次急跌企稳，避开已经转跌的市场。', finds:'寻找仍在上升趋势、从高位急跌后开始企稳的市场。', success:'急跌后不再创新低，成交恢复，价格出现修复。', failure:'跌势仍在加速，市场连续破位，没有止跌证据。', indicators:[['短期跌幅','衡量价格在短时间内下跌了多少。'],['真实波幅','区分正常波动与异常急跌。'],['成交量比','观察恐慌成交是否集中出现。'],['长周期方向','避免在大级别崩塌中贸然接刀。']], before:['市场可交易且 K 线完整。','排除流动性不足与黑名单市场。','长期状态过弱时不找反弹。'], after:['崩塌保护触发时全部丢弃。','同一市场冷却期内不重复提醒。','达到每日提醒上限后只入账、不推送。'], trading:['下一根 K 线开盘作为计划进场。','止损优先，避免反弹判断失败后扩大亏损。','在规定持有时间内未修复则退出。'], parameters:[['回放与筛选值','由用户在信号配置面板设置'],['提醒与冷却','以当前配置为准'],['不可修改项','止损优先与最晚退出顺序保持固定']], steps:[['观察急跌','比较短期跌幅与平时波动。'],['排除崩塌','确认更大方向和市场状态允许观察反弹。'],['等待确认','只保留跌速缓和且成交有响应的样本。'],['发出提醒','按强弱排序后推送有限数量。'],['记录结果','跟踪止损或时间退出，供回放判断。']] },
  strength: { name:'持续强势', kind:'信号策略', summary:'寻找价格和成交持续配合、方向没有转弱的市场。', finds:'寻找不是一根 K 线冲高，而是连续保持强势的市场。', success:'价格沿趋势推进，回撤有限，成交没有突然枯竭。', failure:'冲高后立即回落，或相对大盘的优势快速消失。', indicators:[['趋势强度','衡量上涨是否连续而非偶然。'],['长周期均线','检查大方向有没有转弱。'],['成交量比','确认上涨时有人持续参与。'],['相对强弱','比较该市场与同期大盘表现。']], before:['市场与数据必须可用。','长周期价格保持在健康区域。','黑名单市场不参与。'], after:['重复机会处于冷却期时筛掉。','市场整体快速下跌时暂停提醒。','超过每日上限的机会只保存记录。'], trading:['下一根 K 线开盘作为计划进场。','保护位随日常波动设置。','趋势破坏、触及止损或到期时退出。'], parameters:[['回放与筛选值','由用户在信号配置面板设置'],['提醒数量','以当前配置为准'],['不可修改项','入账与回放的成交先后规则']], steps:[['确认大方向','先检查长周期状态。'],['寻找持续性','判断强势是否延续而非瞬间冲高。'],['检查成交','成交活跃度必须与价格配合。'],['过滤与提醒','按强弱排序并控制重复提醒。'],['跟踪退出','记录趋势破坏、止损或到期结果。']] }
};
const definition = computed(() => definitions[isTrend.value ? 'trend' : slug.value] || definitions.breakout);
const trend = computed(() => store.state?.trend_forward || {});
const equity = computed(() => store.state?.live_reconciliation?.equity || {});
const equityPoints = computed(() => (equity.value.points || []).map(row => ({ strategy:Number(row.paper_normalized), actual:Number(row.live_normalized) })).filter(row => Number.isFinite(row.strategy) && Number.isFinite(row.actual)));
const holdingRows = computed(() => isTrend.value ? Object.entries(trend.value.runner?.weights || {}).filter(([,weight]) => Math.abs(Number(weight)) > 1e-9).map(([symbol,weight]) => ({ symbol, weight:Number(weight), direction:Number(weight)>0?'做多':'做空', entry:null, reason:'多个时间尺度的趋势投票决定方向，近期波动决定权重。' })) : []);
const chartSymbol = ref('');
watchEffect(() => { if (!holdingRows.value.some(row => row.symbol === chartSymbol.value)) chartSymbol.value = holdingRows.value[0]?.symbol || ''; });
const selectedHolding = computed(() => holdingRows.value.find(row => row.symbol === chartSymbol.value));
const pricePoints = computed(() => (store.state?.price_history?.[chartSymbol.value] || []).map(row => ({ time:row.timestamp || row.tick, price:Number(row.price) })).filter(row => Number.isFinite(row.price)));
const runtimeStatus = computed(() => isTrend.value ? (trend.value.status === 'NOT_STARTED' ? '尚未启动' : '运行中') : (signalEnabled.value ? '提醒已启用' : '提醒未启用'));
const runtimeColor = computed(() => /运行中|已启用/.test(runtimeStatus.value) ? 'green' : 'orange');
const detailReplayRoute = computed(() => isTrend.value ? 'review' : 'signals');
const pct = value => `${(Number(value || 0) * 100).toFixed(1)}%`;
function refresh(){ loadStrategyCatalog(); loadSignalDesk(); }
async function toggleSignal(){ controlBusy.value=true;try{await controlSignalService(!signalEnabled.value);await loadSignalDesk();}finally{controlBusy.value=false;} }
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
