<script setup lang="ts">
import { onMounted, ref } from 'vue';
import { useFeedback } from '@/composables/feedback';

import StatCard from '@/components/StatCard.vue';
import ActivityTimeline from '@/components/ActivityTimeline.vue';
import type { DashboardSummary } from '@/services/api';
import { fetchDashboardSummary } from '@/services/api';

const { toast } = useFeedback();
const loading = ref(true);
const summary = ref<DashboardSummary | null>(null);

async function loadSummary() {
  loading.value = true;
  try {
    summary.value = await fetchDashboardSummary();
  } catch (error) {
    console.error(error);
    toast.add({
      severity: 'error',
      summary: '加载失败',
      detail: '无法获取仪表盘数据，请稍后重试。',
      life: 4000
    });
  } finally {
    loading.value = false;
  }
}

onMounted(loadSummary);
</script>

<template>
  <section class="d-flex flex-column ga-4">
    <div class="d-flex align-center justify-space-between flex-wrap ga-3">
      <div>
        <h2 class="text-h5 font-weight-bold ma-0">仪表盘</h2>
        <p class="text-medium-emphasis mt-1 mb-0">
          总览运营指标与最近消息动态。
        </p>
      </div>
      <VBtn prepend-icon="mdi-refresh" variant="outlined" :loading="loading" @click="loadSummary">刷新</VBtn>
    </div>

    <VRow v-if="!loading && summary">
      <VCol cols="12" md="6" xl="3">
        <StatCard
          label="总群组"
          :value="summary.total_groups"
          icon="mdi-office-building-outline"
          accent="primary"
          :hint="`${summary.active_groups} 个活跃`"
        />
      </VCol>
      <VCol cols="12" md="6" xl="3">
        <StatCard
          label="启用聊天的群"
          :value="summary.chat_enabled_groups"
          icon="mdi-microphone-outline"
          accent="success"
          :hint="`${summary.total_group_messages} 条群消息`"
        />
      </VCol>
      <VCol cols="12" md="6" xl="3">
        <StatCard
          label="用户数量"
          :value="summary.total_users"
          icon="mdi-account-outline"
          accent="primary"
          :hint="`${summary.chat_enabled_users} 可聊天`"
        />
      </VCol>
      <VCol cols="12" md="6" xl="3">
        <StatCard
          label="私聊消息"
          :value="summary.total_private_messages"
          icon="mdi-email-outline"
          accent="warning"
          :hint="`近 ${summary.recent_activity.length} 条动态`"
        />
      </VCol>
    </VRow>

    <VRow v-else>
      <VCol cols="12" md="6" xl="3" v-for="index in 4" :key="index">
        <VSkeletonLoader height="12rem" class="rounded-lg" />
      </VCol>
    </VRow>

    <VCard class="elevation-1">
      <VCardTitle>消息动态</VCardTitle>
      <VCardText>
        <template v-if="summary && summary.recent_activity.length">
          <ActivityTimeline :entries="summary.recent_activity" />
        </template>
        <template v-else-if="loading">
          <VRow>
            <VCol cols="12" v-for="index in 3" :key="index">
              <VSkeletonLoader height="6rem" class="rounded-lg" />
            </VCol>
          </VRow>
        </template>
        <template v-else>
          <div class="text-center py-6 text-medium-emphasis">
            暂无最新消息，系统保持稳定运行。
          </div>
        </template>
      </VCardText>
    </VCard>

    <VCard class="elevation-1">
      <VCardTitle>运营建议</VCardTitle>
      <VCardText>
        <p class="text-body-2 text-medium-emphasis mb-3">
          根据最近的消息分布，建议关注以下重点：
        </p>
        <VDivider />
        <ul class="ma-0 pl-3 text-body-2">
          <li>监控消息量激增的群组，合理设置理智值上限。</li>
          <li>私聊活跃用户可适当启用更多功能，增强粘性。</li>
          <li>预留功能配置已准备就绪，可随业务升级逐步开放。</li>
        </ul>
      </VCardText>
    </VCard>
  </section>
</template>
