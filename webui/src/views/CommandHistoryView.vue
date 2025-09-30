<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue';
import DataTable from 'primevue/datatable';
import Column from 'primevue/column';
import InputText from 'primevue/inputtext';
import Dropdown from 'primevue/dropdown';
import Button from 'primevue/button';
import Tag from 'primevue/tag';
import Toast from 'primevue/toast';
import { useToast } from 'primevue/usetoast';
import Skeleton from 'primevue/skeleton';

import type { CommandHistoryItem, CommandHistoryQuery } from '@/services/api';
import { listCommandHistory } from '@/services/api';

const toast = useToast();
const loading = ref(true);
const entries = ref<CommandHistoryItem[]>([]);

const pagination = reactive({ page: 0, rows: 20, total: 0 });
const filters = reactive<{ command: string; userId: string; success: boolean | null }>({
  command: '',
  userId: '',
  success: null
});

function parseUserId(): number | undefined {
  const trimmed = filters.userId.trim();
  if (!trimmed) return undefined;
  const parsed = Number(trimmed);
  return Number.isNaN(parsed) ? undefined : parsed;
}

async function loadHistory() {
  loading.value = true;
  try {
    const query: CommandHistoryQuery = {
      command: filters.command.trim() || undefined,
      user_id: parseUserId(),
      success: filters.success === null ? undefined : filters.success,
      limit: pagination.rows,
      offset: pagination.page * pagination.rows
    };
    const { items, total } = await listCommandHistory(query);
    entries.value = items;
    pagination.total = total;
  } catch (error) {
    console.error(error);
    toast.add({
      severity: 'error',
      summary: '加载失败',
      detail: '无法获取命令历史记录。',
      life: 4000
    });
  } finally {
    loading.value = false;
  }
}

function onSearch() {
  pagination.page = 0;
  loadHistory();
}

function onPage(event: { page: number; rows: number }) {
  pagination.page = event.page;
  pagination.rows = event.rows;
  loadHistory();
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

onMounted(loadHistory);
</script>

<template>
  <section class="flex flex-column gap-4">
    <Toast />
    <header class="flex flex-column gap-2">
      <h2 class="text-2xl font-semibold m-0">命令历史</h2>
      <p class="text-color-secondary m-0">
        记录最近触发的机器人命令，帮助排查问题与追踪使用情况。
      </p>
      <div class="grid align-items-end gap-3">
        <div class="col-12 md:col-4">
          <label class="block text-sm text-color-secondary mb-2">命令名称</label>
          <InputText v-model="filters.command" placeholder="如 setu" class="w-full" @keydown.enter="onSearch" />
        </div>
        <div class="col-12 md:col-3">
          <label class="block text-sm text-color-secondary mb-2">用户 ID</label>
          <InputText v-model="filters.userId" placeholder="精准匹配" class="w-full" @keydown.enter="onSearch" />
        </div>
        <div class="col-6 md:col-3">
          <label class="block text-sm text-color-secondary mb-2">执行状态</label>
          <Dropdown
            v-model="filters.success"
            :options="[
              { label: '全部', value: null },
              { label: '成功', value: true },
              { label: '失败', value: false }
            ]"
            optionLabel="label"
            optionValue="value"
            class="w-full"
            @change="onSearch"
          />
        </div>
        <div class="col-12 md:col-2 flex md:justify-content-end">
          <Button label="查询" icon="pi pi-search" @click="onSearch" />
        </div>
      </div>
    </header>

    <DataTable
      v-if="entries.length || !loading"
      :value="entries"
      :loading="loading"
      dataKey="id"
      responsiveLayout="scroll"
      :rows="pagination.rows"
      :first="pagination.page * pagination.rows"
      :totalRecords="pagination.total"
      paginator
      lazy
      :rowsPerPageOptions="[20, 50, 100]"
      @page="onPage"
      class="shadow-1 border-round-xl"
    >
      <Column field="triggered_at" header="时间" sortable>
        <template #body="{ data }">
          {{ formatTimestamp(data.triggered_at) }}
        </template>
      </Column>
      <Column field="command" header="命令" sortable />
      <Column header="参数">
        <template #body="{ data }">
          {{ formatArguments(data.arguments) }}
        </template>
      </Column>
      <Column header="用户">
        <template #body="{ data }">
          {{ data.user_id ?? '—' }}
        </template>
      </Column>
      <Column header="会话">
        <template #body="{ data }">
          <div class="flex flex-column">
            <span>{{ data.chat_id ?? '—' }}</span>
            <small class="text-color-secondary">{{ data.chat_type ?? '未知' }}</small>
          </div>
        </template>
      </Column>
      <Column header="结果">
        <template #body="{ data }">
          <Tag :value="data.success ? '成功' : '失败'" :severity="data.success ? 'success' : 'danger'" />
        </template>
      </Column>
      <Column header="耗时">
        <template #body="{ data }">
          {{ formatDuration(data.duration_ms) }}
        </template>
      </Column>
      <Column header="错误信息" style="min-width: 16rem">
        <template #body="{ data }">
          <span class="text-sm">{{ data.error_message || '—' }}</span>
        </template>
      </Column>
    </DataTable>

    <div v-else class="grid">
      <div class="col-12" v-for="index in 3" :key="index">
        <Skeleton height="6rem" class="border-round" />
      </div>
    </div>
  </section>
</template>
