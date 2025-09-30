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

import GroupDetailDialog from '@/components/GroupDetailDialog.vue';
import type {
  GroupDetail,
  GroupListItem,
  GroupMeta,
  GroupUpdatePayload,
  GroupListResponse,
  GroupListQuery
} from '@/services/api';
import {
  fetchGroupMeta,
  getGroupDetail,
  listGroups,
  updateGroup
} from '@/services/api';

const toast = useToast();
const loading = ref(true);
const groups = ref<GroupListItem[]>([]);
const meta = ref<GroupMeta | null>(null);
const detail = ref<GroupDetail | null>(null);
const dialogVisible = ref(false);

const pagination = reactive({ page: 0, rows: 10, total: 0 });
const filters = reactive<{ q: string; enable: boolean | null; chatEnabled: boolean | null }>({
  q: '',
  enable: null,
  chatEnabled: null
});

async function ensureMeta() {
  if (!meta.value) {
    meta.value = await fetchGroupMeta();
  }
}

async function loadGroups() {
  loading.value = true;
  try {
    const query: GroupListQuery = {
      q: filters.q || undefined,
      enable: filters.enable === null ? undefined : filters.enable,
      chat_enabled: filters.chatEnabled === null ? undefined : filters.chatEnabled,
      limit: pagination.rows,
      offset: pagination.page * pagination.rows
    };
    const response: GroupListResponse = await listGroups(query);
    groups.value = response.items;
    pagination.total = response.total;
  } catch (error) {
    console.error(error);
    toast.add({
      severity: 'error',
      summary: '加载失败',
      detail: '无法获取群组列表。',
      life: 4000
    });
  } finally {
    loading.value = false;
  }
}

function onSearch() {
  pagination.page = 0;
  loadGroups();
}

function onPage(event: { page: number; rows: number }) {
  pagination.page = event.page;
  pagination.rows = event.rows;
  loadGroups();
}

async function openDetail(groupId: number) {
  try {
    await ensureMeta();
    detail.value = await getGroupDetail(groupId);
    dialogVisible.value = true;
  } catch (error) {
    console.error(error);
    toast.add({
      severity: 'error',
      summary: '加载失败',
      detail: '无法获取群组详情。',
      life: 4000
    });
  }
}

async function handleUpdate(payload: GroupUpdatePayload) {
  if (!detail.value) return;
  try {
    const updated = await updateGroup(detail.value.id, payload);
    detail.value = updated;
    groups.value = groups.value.map((item) => (item.id === updated.id ? updated : item));
    toast.add({ severity: 'success', summary: '保存成功', detail: '群组配置已更新。', life: 2500 });
    await loadGroups();
  } catch (error) {
    console.error(error);
    toast.add({ severity: 'error', summary: '保存失败', detail: '请稍后重试。', life: 4000 });
  }
}

onMounted(async () => {
  await ensureMeta();
  await loadGroups();
});
</script>

<template>
  <section class="flex flex-column gap-4">
    <Toast />
    <header class="flex flex-column gap-2">
      <h2 class="text-2xl font-semibold m-0">群组管理</h2>
      <p class="text-color-secondary m-0">
        查看机器人所覆盖的群组，快速调整群级别的权限与配置。
      </p>
      <div class="grid align-items-end gap-3">
        <div class="col-12 md:col-4">
          <label class="block text-sm text-color-secondary mb-2">搜索群 ID / 名称</label>
          <span class="p-input-icon-left w-full">
            <i class="pi pi-search" />
            <InputText v-model="filters.q" placeholder="输入关键字" class="w-full" @keydown.enter="onSearch" />
          </span>
        </div>
        <div class="col-6 md:col-3">
          <label class="block text-sm text-color-secondary mb-2">启用状态</label>
          <Dropdown
            v-model="filters.enable"
            :options="[
              { label: '全部', value: null },
              { label: '已启用', value: true },
              { label: '未启用', value: false }
            ]"
            optionLabel="label"
            optionValue="value"
            class="w-full"
            @change="onSearch"
          />
        </div>
        <div class="col-6 md:col-3">
          <label class="block text-sm text-color-secondary mb-2">聊天功能</label>
          <Dropdown
            v-model="filters.chatEnabled"
            :options="[
              { label: '全部', value: null },
              { label: '已开放', value: true },
              { label: '已关闭', value: false }
            ]"
            optionLabel="label"
            optionValue="value"
            class="w-full"
            @change="onSearch"
          />
        </div>
        <div class="col-12 md:col-2 flex md:justify-content-end">
          <Button label="查询" icon="pi pi-filter" @click="onSearch" />
        </div>
      </div>
    </header>

    <DataTable
      :value="groups"
      :loading="loading"
      dataKey="id"
      responsiveLayout="scroll"
      :rows="pagination.rows"
      :first="pagination.page * pagination.rows"
      :totalRecords="pagination.total"
      paginator
      lazy
      :rowsPerPageOptions="[10, 20, 50]"
      @page="onPage"
      class="shadow-1 border-round-xl"
      v-if="groups.length || !loading"
    >
      <Column field="id" header="群 ID" sortable />
      <Column field="name" header="名称" sortable />
      <Column header="状态">
        <template #body="{ data }">
          <Tag :value="data.enable ? '启用' : '停用'" :severity="data.enable ? 'success' : 'danger'" />
        </template>
      </Column>
      <Column header="聊天">
        <template #body="{ data }">
          <Tag :value="data.enable_chat ? '开放' : '关闭'" :severity="data.enable_chat ? 'info' : 'warning'" />
        </template>
      </Column>
      <Column header="消息量">
        <template #body="{ data }">
          <span class="font-medium">{{ data.message_count }}</span>
        </template>
      </Column>
      <Column header="最后活跃">
        <template #body="{ data }">
          {{ data.last_activity ? new Date(data.last_activity).toLocaleString() : '暂无' }}
        </template>
      </Column>
      <Column header="操作" style="width: 8rem">
        <template #body="{ data }">
          <Button label="详情" size="small" icon="pi pi-eye" @click="openDetail(data.id)" />
        </template>
      </Column>
    </DataTable>

    <div v-else class="grid">
      <div class="col-12" v-for="index in 3" :key="index">
        <Skeleton height="7rem" class="border-round" />
      </div>
    </div>

    <GroupDetailDialog
      v-model:visible="dialogVisible"
      :meta="meta"
      :group="detail"
      @submit="handleUpdate"
    />
  </section>
</template>
