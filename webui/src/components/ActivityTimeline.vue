<script setup lang="ts">
import Timeline from 'primevue/timeline';
import Card from 'primevue/card';
import Tag from 'primevue/tag';

export interface ActivityEntry {
  message_id: number;
  scope: string;
  scope_id: number;
  preview: string | null;
  sent_at: string | null;
}

const props = defineProps<{ entries: ActivityEntry[] }>();

function scopeLabel(scope: string) {
  switch (scope) {
    case 'group':
      return { label: '群消息', severity: 'info' } as const;
    case 'group_bot':
      return { label: '机器人群推送', severity: 'success' } as const;
    case 'private':
      return { label: '私聊消息', severity: 'warn' } as const;
    case 'private_bot':
      return { label: '机器人私聊', severity: 'help' } as const;
    default:
      return { label: scope, severity: 'secondary' } as const;
  }
}
</script>

<template>
  <Timeline :value="props.entries" align="alternate" class="w-full">
    <template #opposite="slotProps">
      <span class="text-sm text-color-secondary">
        {{ slotProps.item.sent_at ? new Date(slotProps.item.sent_at).toLocaleString() : '未知时间' }}
      </span>
    </template>
    <template #marker="slotProps">
      <span class="flex align-items-center justify-content-center w-2rem h-2rem border-circle bg-primary text-white">
        <i class="pi pi-bolt"></i>
      </span>
    </template>
    <template #content="slotProps">
      <Card class="shadow-1">
        <template #title>
          <div class="flex align-items-center justify-content-between">
            <span class="text-sm">消息 ID #{{ slotProps.item.message_id }}</span>
            <Tag :value="scopeLabel(slotProps.item.scope).label" :severity="scopeLabel(slotProps.item.scope).severity" />
          </div>
        </template>
        <template #content>
          <div class="text-color-secondary text-sm">对象 ID：{{ slotProps.item.scope_id }}</div>
          <p class="mt-2 mb-0 white-space-pre-line">
            {{ slotProps.item.preview ?? '暂无文本内容' }}
          </p>
        </template>
      </Card>
    </template>
  </Timeline>
</template>
