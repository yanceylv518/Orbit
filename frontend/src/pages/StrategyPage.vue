<template>
  <section class="strategy-workspace-page">
    <div class="page-toolbar">
      <div>
        <h2>正式策略目录</h2>
        <p>这里只展示已经冻结的交易规则、证据和准入阶段，不在这里下载数据或运行研究实验。</p>
      </div>
    </div>

    <StrategyCenterPage />
  </section>
</template>

<script setup>
import StrategyCenterPage from "./StrategyCenterPage.vue";
</script>
