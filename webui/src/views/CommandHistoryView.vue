<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue';
import { useFeedback } from '@/composables/feedback';
import type { DataTableHeader, DataTableSortItem } from 'vuetify';

import type { CommandHistoryItem, CommandHistoryQuery } from '@/services/api';
import { listCommandHistory } from '@/services/api';
import { parseCommandHistoryUserId } from '@/utils/command-history';
import {
  createServerTableRequestGuard,
  toApiTableParams,
  type ServerTableOptions,
} from '@/utils/table-options';

const { toast } = useFeedback();
const loading = ref(true);
const entries = ref<CommandHistoryItem[]>([]);

type NativeTableOptions = {
  page: number;
  itemsPerPage: number;
  sortBy: ReadonlyArray<DataTableSortItem>;
};

const headers: DataTableHeader<CommandHistoryItem>[] = [
  { title: '时间', key: 'triggered_at', sortable: true },
  { title: '命令', key: 'command', sortable: true },
  { title: '参数', key: 'arguments', sortable: false },
  { title: '用户', key: 'user_id', sortable: false },
  { title: '会话', key: 'chat_id', sortable: false },
  { title: '结果', key: 'success', sortable: false },
  { title: '耗时', key: 'duration_ms', sortable: false },
  { title: '错误信息', key: 'error_message', sortable: false },
];

const pagination = reactive<ServerTableOptions & { total: number }>({
  page: 1,
  itemsPerPage: 20,
  sortBy: [],
  total: 0,
});
const filters = reactive<{ command: string; userId: string; success: boolean | null }>({
  command: '',
  userId: '',
  success: null
});

let tableReady = false;
const requestGuard = createServerTableRequestGuard();

function toServerTableOptions(options: NativeTableOptions): ServerTableOptions {
  return {
    page: options.page,
    itemsPerPage: options.itemsPerPage,
    sortBy: options.sortBy.map(({ key, order }) => ({
      key,
      ...(order === 'asc' || order === 'desc' ? { order } : {}),
    })),
  };
}

function optionsKey(options: ServerTableOptions): string {
  return JSON.stringify({
    page: options.page,
    itemsPerPage: options.itemsPerPage,
    sortBy: options.sortBy,
  });
}

async function loadHistory(options: ServerTableOptions = pagination) {
  const requestId = requestGuard.begin(optionsKey(options));
  loading.value = true;
  try {
    const tableParams = toApiTableParams(options, ['command', 'triggered_at']);
    const query: CommandHistoryQuery = {
      command: filters.command.trim() || undefined,
      user_id: parseCommandHistoryUserId(filters.userId),
      success: filters.success === null ? undefined : filters.success,
      ...tableParams,
    };
    const { items, total } = await listCommandHistory(query);
    if (!requestGuard.isLatest(requestId)) return;
    entries.value = items;
    pagination.total = total;
  } catch (error) {
    if (!requestGuard.isLatest(requestId)) return;
    requestGuard.invalidateFailed(requestId);
    console.error(error);
    toast.add({
      severity: 'error',
      summary: '加载失败',
      detail: '无法获取命令历史记录。',
      life: 4000
    });
  } finally {
    if (requestGuard.isLatest(requestId)) {
      loading.value = false;
    }
  }
}

function onSearch() {
  const options = { ...pagination, page: 1 };
  pagination.page = 1;
  void loadHistory(options);
}

function onTableOptions(nativeOptions: NativeTableOptions) {
  if (!tableReady) return;

  const options = toServerTableOptions(nativeOptions);
  const key = optionsKey(options);
  if (!requestGuard.shouldLoad(key)) return;

  pagination.page = options.page;
  pagination.itemsPerPage = options.itemsPerPage;
  pagination.sortBy = options.sortBy;
  void loadHistory(options);
}

function formatArguments(args: string[] | null): string {
  if (!args || args.length === 0) return '—';
  return args.join(' ');
}

function formatDuration(duration: number | null): string {
  if (typeof duration !== 'number') return '—';
  return `${duration} ms`;
}

function formatTimestamp(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

onMounted(async () => {
  tableReady = true;
  await loadHistory(pagination);
});
</script>

<template>
  <section class="d-flex flex-column ga-4">
    <header class="d-flex flex-column ga-2">
      <h2 class="text-h5 font-weight-bold ma-0">命令历史</h2>
      <p class="text-medium-emphasis ma-0">
        记录最近触发的机器人命令，帮助排查问题与追踪使用情况。
      </p>
      <VRow class="align-end ga-3">
        <VCol cols="12" md="4">
          <VTextField id="command-history-command" label="命令名称" v-model="filters.command" placeholder="如 setu" class="w-100" @keydown.enter="onSearch" />
        </VCol>
        <VCol cols="12" md="3">
          <VTextField id="command-history-user-id" label="用户 ID" v-model="filters.userId" placeholder="精准匹配" class="w-100" @keydown.enter="onSearch" />
        </VCol>
        <VCol cols="6" md="3">
          <VSelect
            id="command-history-success"
            label="执行状态"
            v-model="filters.success"
            :items="[
              { label: '全部', value: null },
              { label: '成功', value: true },
              { label: '失败', value: false },
            ]"
            item-title="label"
            item-value="value"
            class="w-100"
            @update:modelValue="onSearch"
          />
        </VCol>
        <VCol cols="12" md="2" class="d-flex justify-md-end">
          <VBtn prepend-icon="mdi-magnify" @click="onSearch">查询</VBtn>
        </VCol>
      </VRow>
    </header>

    <VDataTableServer
      v-if="entries.length || !loading"
      :headers="headers"
      :items="entries"
      :loading="loading"
      item-value="id"
      :page="pagination.page"
      :items-length="pagination.total"
      :items-per-page="pagination.itemsPerPage"
      :items-per-page-options="[20, 50, 100]"
      :sort-by="pagination.sortBy"
      @update:options="onTableOptions"
      class="elevation-1 rounded-lg"
    >
      <template #item.triggered_at="{ item }">
        {{ formatTimestamp(item.triggered_at) }}
      </template>
      <template #item.arguments="{ item }">
        {{ formatArguments(item.arguments) }}
      </template>
      <template #item.user_id="{ item }">
        {{ item.user_id ?? '—' }}
      </template>
      <template #item.chat_id="{ item }">
          <div class="d-flex flex-column">
            <span>{{ item.chat_id ?? '—' }}</span>
            <small class="text-medium-emphasis">{{ item.chat_type ?? '未知' }}</small>
          </div>
      </template>
      <template #item.success="{ item }">
        <VChip :color="item.success ? 'success' : 'error'">{{ item.success ? '成功' : '失败' }}</VChip>
      </template>
      <template #item.duration_ms="{ item }">
        {{ formatDuration(item.duration_ms) }}
      </template>
      <template #item.error_message="{ item }">
        <span class="text-body-2">{{ item.error_message || '—' }}</span>
      </template>
    </VDataTableServer>

    <VRow v-else>
      <VCol cols="12" v-for="index in 3" :key="index">
        <VSkeletonLoader height="6rem" class="rounded-lg" />
      </VCol>
    </VRow>
  </section>
</template>
