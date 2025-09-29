<template>
  <div class="grid gap-4">
    <div class="col-12">
      <div class="text-2xl font-bold mb-2">控制台概览</div>
      <p class="text-600">集中展示机器人运行状态、会话活跃度以及自动化覆盖情况。</p>
    </div>

    <div class="col-12 lg:col-3" v-for="tile in tiles" :key="tile.label">
      <Card class="h-full">
        <template #title>
          <div class="flex align-items-center justify-content-between">
            <span>{{ tile.label }}</span>
            <i :class="['pi text-3xl', tile.icon, tile.color]"></i>
          </div>
        </template>
        <template #content>
          <div class="text-4xl font-bold">{{ tile.value }}</div>
          <p class="text-600 mt-2">{{ tile.hint }}</p>
        </template>
      </Card>
    </div>

    <div class="col-12 lg:col-6">
      <Card>
        <template #title>群组健康评分</template>
        <template #content>
          <div class="flex flex-column gap-3">
            <div class="flex justify-content-between align-items-center">
              <span>活跃度</span>
              <Tag :value="activeRateLabel" severity="success" />
            </div>
            <ProgressBar :value="activeRate" showValue></ProgressBar>
            <small class="text-600">保持活跃的群组占比越高，机器人服务触达越充分。</small>
          </div>
        </template>
      </Card>
    </div>

    <div class="col-12 lg:col-6">
      <Card>
        <template #title>运维提醒</template>
        <template #content>
          <Timeline :value="reminders">
            <template #content="slotProps">
              <span class="font-medium">{{ slotProps.item.title }}</span>
              <p class="m-0 text-600">{{ slotProps.item.description }}</p>
            </template>
          </Timeline>
        </template>
      </Card>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted } from "vue";
import Card from "primevue/card";
import ProgressBar from "primevue/progressbar";
import Tag from "primevue/tag";
import Timeline from "primevue/timeline";
import { useAdminStore } from "../stores/admin";

const store = useAdminStore();

const tiles = computed(() => {
  const stats = store.dashboard;
  return [
    {
      label: "群组总数",
      icon: "pi-users",
      color: "text-primary",
      value: stats?.groups ?? 0,
      hint: "已接入的 Telegram 群组总量"
    },
    {
      label: "活跃群组",
      icon: "pi-bolt",
      color: "text-green-500",
      value: stats?.active_groups ?? 0,
      hint: "近 7 天有互动的群组数"
    },
    {
      label: "私聊会话",
      icon: "pi-comments",
      color: "text-purple-500",
      value: stats?.private_chats ?? 0,
      hint: "与机器人保持沟通的私聊用户"
    },
    {
      label: "自动化规则",
      icon: "pi-cog",
      color: "text-orange-500",
      value: stats?.automations ?? 0,
      hint: "用于巡检、欢迎、应急的自动化脚本"
    }
  ];
});

const activeRate = computed(() => {
  if (!store.dashboard || store.dashboard.groups === 0) return 0;
  return Math.round((store.dashboard.active_groups / store.dashboard.groups) * 100);
});

const activeRateLabel = computed(() => `${activeRate.value}%`);

const reminders = computed(() => [
  {
    title: "私聊满意度调查",
    description: `当前有 ${store.dashboard?.muted_chats ?? 0} 位用户静音机器人，建议发布关怀通知。`
  },
  {
    title: "功能巡检",
    description: "请定期校验涩图及其他扩展功能的鉴权凭据。"
  },
  {
    title: "自动化体验优化",
    description: "为高频任务新增冷却提示，避免重复触发。"
  }
]);

onMounted(async () => {
  await Promise.all([
    store.refreshDashboard(),
    store.fetchGroups(),
    store.fetchPrivateChats(),
    store.fetchAutomationRules()
  ]);
});
</script>
