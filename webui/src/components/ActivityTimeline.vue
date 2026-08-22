<script setup lang="ts">
import { normalizeVuetifyColor } from '@/composables/feedback';

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
  <v-timeline class="w-100">
    <v-timeline-item
      v-for="entry in props.entries"
      :key="entry.message_id"
      dot-color="primary"
      fill-dot
    >
      <template #opposite>
        <span class="text-body-2 text-medium-emphasis">
          {{ entry.sent_at ? new Date(entry.sent_at).toLocaleString() : '未知时间' }}
        </span>
      </template>
      <template #icon>
        <v-icon icon="mdi-flash" color="white" />
      </template>
      <template #default>
        <v-card class="elevation-1">
          <v-card-title>
            <div class="d-flex align-center justify-space-between">
              <span class="text-body-2">消息 ID #{{ entry.message_id }}</span>
              <v-chip
                :color="normalizeVuetifyColor(scopeLabel(entry.scope).severity)"
                size="small"
              >
                {{ scopeLabel(entry.scope).label }}
              </v-chip>
            </div>
          </v-card-title>
          <v-card-text>
            <div class="text-medium-emphasis text-body-2">对象 ID：{{ entry.scope_id }}</div>
            <p class="mt-2 mb-0 white-space-pre-line">
              {{ entry.preview ?? '暂无文本内容' }}
            </p>
          </v-card-text>
        </v-card>
      </template>
    </v-timeline-item>
  </v-timeline>
</template>
