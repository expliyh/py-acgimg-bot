<script setup lang="ts">
import { onMounted, ref } from 'vue';
import Card from 'primevue/card';
import Skeleton from 'primevue/skeleton';
import Button from 'primevue/button';
import Divider from 'primevue/divider';
import Toast from 'primevue/toast';
import { useToast } from 'primevue/usetoast';

import StatCard from '@/components/StatCard.vue';
import ActivityTimeline from '@/components/ActivityTimeline.vue';
import type { DashboardSummary } from '@/services/api';
import { fetchDashboardSummary } from '@/services/api';

const toast = useToast();
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
  <section class="flex flex-column gap-4">
    <Toast />
    <div class="flex align-items-center justify-content-between flex-wrap gap-3">
      <div>
        <h2 class="text-2xl font-semibold m-0">仪表盘</h2>
        <p class="text-color-secondary mt-1 mb-0">
          总览运营指标与最近消息动态。
        </p>
      </div>
      <Button label="刷新" icon="pi pi-refresh" @click="loadSummary" :loading="loading" outlined />
    </div>

    <div class="grid" v-if="!loading && summary">
      <div class="col-12 md:col-6 xl:col-3">
        <StatCard
          label="总群组"
          :value="summary.total_groups"
          icon="pi pi-building"
          accent="primary"
          :hint="`${summary.active_groups} 个活跃`"
        />
      </div>
      <div class="col-12 md:col-6 xl:col-3">
        <StatCard
          label="启用聊天的群"
          :value="summary.chat_enabled_groups"
          icon="pi pi-microphone"
          accent="success"
          :hint="`${summary.total_group_messages} 条群消息`"
        />
      </div>
      <div class="col-12 md:col-6 xl:col-3">
        <StatCard
          label="用户数量"
          :value="summary.total_users"
          icon="pi pi-user"
          accent="primary"
          :hint="`${summary.chat_enabled_users} 可聊天`"
        />
      </div>
      <div class="col-12 md:col-6 xl:col-3">
        <StatCard
          label="私聊消息"
          :value="summary.total_private_messages"
          icon="pi pi-envelope"
          accent="warning"
          :hint="`近 ${summary.recent_activity.length} 条动态`"
        />
      </div>
    </div>

    <div v-else class="grid">
      <div class="col-12 md:col-6 xl:col-3" v-for="index in 4" :key="index">
        <Skeleton height="12rem" class="border-round-xl" />
      </div>
    </div>

    <Card class="shadow-1">
      <template #title>消息动态</template>
      <template #content>
        <template v-if="summary && summary.recent_activity.length">
          <ActivityTimeline :entries="summary.recent_activity" />
        </template>
        <template v-else-if="loading">
          <div class="grid">
            <div class="col-12" v-for="index in 3" :key="index">
              <Skeleton height="6rem" class="border-round" />
            </div>
          </div>
        </template>
        <template v-else>
          <div class="text-center py-6 text-color-secondary">
            暂无最新消息，系统保持稳定运行。
          </div>
        </template>
      </template>
    </Card>

    <Card class="shadow-1">
      <template #title>运营建议</template>
      <template #content>
        <p class="text-sm text-color-secondary mb-3">
          根据最近的消息分布，建议关注以下重点：
        </p>
        <Divider />
        <ul class="m-0 pl-3 text-sm">
          <li>监控消息量激增的群组，合理设置理智值上限。</li>
          <li>私聊活跃用户可适当启用更多功能，增强粘性。</li>
          <li>预留功能配置已准备就绪，可随业务升级逐步开放。</li>
        </ul>
      </template>
    </Card>
  </section>
</template>
