<template>
  <div class="position-chart-wrap">
    <svg viewBox="0 0 720 230" role="img" aria-label="持仓价格图">
      <g class="position-grid"><line v-for="y in [30,80,130,180]" :key="y" x1="24" x2="704" :y1="y" :y2="y" /></g>
      <rect v-if="direction" x="24" y="18" width="680" height="180" :class="direction === '做多' ? 'long-zone' : 'short-zone'" />
      <polyline v-if="path" :points="path" class="position-price-line" />
      <line v-if="entryY !== null" x1="24" x2="704" :y1="entryY" :y2="entryY" class="position-entry-line" />
      <circle v-if="lastPoint" :cx="lastPoint.x" :cy="lastPoint.y" r="5" class="position-current-dot" />
      <text v-if="entryY !== null" x="30" :y="entryY - 7" class="position-entry-label">进场</text>
      <text v-if="lastPoint" :x="Math.max(30,lastPoint.x-42)" :y="lastPoint.y-10" class="position-current-label">当前</text>
    </svg>
    <div v-if="!points.length" class="position-chart-empty">暂无可画的真实价格序列</div>
    <div class="chart-legend"><span>蓝线 价格</span><span>虚线 进场</span><span>底色 {{ direction || '持仓方向' }}</span></div>
  </div>
</template>
<script setup>
import { computed } from 'vue';
const props=defineProps({points:{type:Array,default:()=>[]},direction:{type:String,default:''},entry:{type:Number,default:null}});
const plotted=computed(()=>{const rows=props.points.slice(-120);if(!rows.length)return[];const values=rows.map(r=>Number(r.price));const min=Math.min(...values,props.entry ?? Infinity);const max=Math.max(...values,props.entry ?? -Infinity);const span=max-min||1;return rows.map((r,i)=>({x:24+i/Math.max(rows.length-1,1)*680,y:198-(Number(r.price)-min)/span*180,price:Number(r.price),min,max,span}))});
const path=computed(()=>plotted.value.map(p=>`${p.x},${p.y}`).join(' '));
const lastPoint=computed(()=>plotted.value.at(-1));
const entryY=computed(()=>props.entry!=null&&lastPoint.value?198-(Number(props.entry)-lastPoint.value.min)/lastPoint.value.span*180:null);
</script>
<style scoped>
.position-chart-wrap{position:relative}.position-chart-wrap svg{display:block;width:100%;height:230px;background:#0b1526;border:1px solid #203454;border-radius:8px}.position-grid line{stroke:#1d304d}.long-zone{fill:#153d35;opacity:.34}.short-zone{fill:#48232b;opacity:.34}.position-price-line{fill:none;stroke:#4aa3ff;stroke-width:2.4}.position-entry-line{stroke:#f5b94c;stroke-dasharray:6 5}.position-current-dot{fill:#fff;stroke:#4aa3ff;stroke-width:3}.position-entry-label{fill:#f5b94c;font-size:11px}.position-current-label{fill:#dce9fb;font-size:11px}.position-chart-empty{position:absolute;inset:0;display:grid;place-items:center;color:#71839e}.chart-legend{display:flex;gap:14px;color:#7f91ac;font-size:12px;margin-top:7px}
</style>
