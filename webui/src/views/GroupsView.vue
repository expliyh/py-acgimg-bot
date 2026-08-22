<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue';
import { useFeedback } from '@/composables/feedback';
import type { DataTableHeader, DataTableSortItem } from 'vuetify';

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
import {
  createServerTableRequestGuard,
  toApiTableParams,
  type ServerTableOptions,
} from '@/utils/table-options';

const { toast } = useFeedback();
const loading = ref(true);
const groups = ref<GroupListItem[]>([]);
const meta = ref<GroupMeta | null>(null);
const detail = ref<GroupDetail | null>(null);
const dialogVisible = ref(false);

type NativeTableOptions = {
  page: number;
  itemsPerPage: number;
  sortBy: ReadonlyArray<DataTableSortItem>;
};

const headers: DataTableHeader<GroupListItem>[] = [
  { title: '群 ID', key: 'id', sortable: true },
  { title: '名称', key: 'name', sortable: true },
  { title: '状态', key: 'enable', sortable: false },
  { title: '聊天', key: 'enable_chat', sortable: false },
  { title: '消息量', key: 'message_count', sortable: false },
  { title: '最后活跃', key: 'last_activity', sortable: false },
  { title: '操作', key: 'actions', sortable: false },
];

const pagination = reactive<ServerTableOptions & { total: number }>({
  page: 1,
  itemsPerPage: 10,
  sortBy: [],
  total: 0,
});
const filters = reactive<{ q: string; enable: boolean | null; chatEnabled: boolean | null }>({
  q: '',
  enable: null,
  chatEnabled: null
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

async function ensureMeta() {
  if (!meta.value) {
    meta.value = await fetchGroupMeta();
  }
}

async function loadGroups(options: ServerTableOptions = pagination) {
  const requestId = requestGuard.begin(optionsKey(options));
  loading.value = true;
  try {
    const tableParams = toApiTableParams(options, ['id', 'name']);
    const query: GroupListQuery = {
      q: filters.q || undefined,
      enable: filters.enable === null ? undefined : filters.enable,
      chat_enabled: filters.chatEnabled === null ? undefined : filters.chatEnabled,
      ...tableParams,
    };
    const response: GroupListResponse = await listGroups(query);
    if (!requestGuard.isLatest(requestId)) return;
    groups.value = response.items;
    pagination.total = response.total;
  } catch (error) {
    if (!requestGuard.isLatest(requestId)) return;
    requestGuard.invalidateFailed(requestId);
    console.error(error);
    toast.add({
      severity: 'error',
      summary: '加载失败',
      detail: '无法获取群组列表。',
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
  void loadGroups(options);
}

function onTableOptions(nativeOptions: NativeTableOptions) {
  if (!tableReady) return;

  const options = toServerTableOptions(nativeOptions);
  const key = optionsKey(options);
  if (!requestGuard.shouldLoad(key)) return;

  pagination.page = options.page;
  pagination.itemsPerPage = options.itemsPerPage;
  pagination.sortBy = options.sortBy;
  void loadGroups(options);
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
    dialogVisible.value = false;
    toast.add({ severity: 'success', summary: '保存成功', detail: '群组配置已更新。', life: 2500 });
    await loadGroups();
  } catch (error) {
    console.error(error);
    toast.add({ severity: 'error', summary: '保存失败', detail: '请稍后重试。', life: 4000 });
  }
}

onMounted(async () => {
  try {
    await ensureMeta();
  } catch (error) {
    console.error(error);
    toast.add({
      severity: 'error',
      summary: '加载失败',
      detail: '无法获取群组元数据。',
      life: 4000,
    });
  }
  tableReady = true;
  await loadGroups(pagination);
});
</script>

<template>
  <section class="d-flex flex-column ga-4">
    <header class="d-flex flex-column ga-2">
      <h2 class="text-h5 font-weight-bold ma-0">群组管理</h2>
      <p class="text-medium-emphasis ma-0">
        查看机器人所覆盖的群组，快速调整群级别的权限与配置。
      </p>
      <VRow class="align-end ga-3">
        <VCol cols="12" md="4">
          <VTextField id="groups-search" label="搜索群 ID / 名称" v-model="filters.q" placeholder="输入关键字" prepend-inner-icon="mdi-magnify" class="w-100" @keydown.enter="onSearch" />
        </VCol>
        <VCol cols="6" md="3">
          <VSelect
            id="groups-enable"
            label="启用状态"
            v-model="filters.enable"
            :items="[
              { label: '全部', value: null },
              { label: '已启用', value: true },
              { label: '未启用', value: false },
            ]"
            item-title="label"
            item-value="value"
            class="w-100"
            @update:modelValue="onSearch"
          />
        </VCol>
        <VCol cols="6" md="3">
          <VSelect
            id="groups-chat-enabled"
            label="聊天功能"
            v-model="filters.chatEnabled"
            :items="[
              { label: '全部', value: null },
              { label: '已开放', value: true },
              { label: '已关闭', value: false },
            ]"
            item-title="label"
            item-value="value"
            class="w-100"
            @update:modelValue="onSearch"
          />
        </VCol>
        <VCol cols="12" md="2" class="d-flex justify-md-end">
          <VBtn prepend-icon="mdi-filter-variant" @click="onSearch">查询</VBtn>
        </VCol>
      </VRow>
    </header>

    <VDataTableServer
      :headers="headers"
      :items="groups"
      :loading="loading"
      item-value="id"
      :page="pagination.page"
      :items-length="pagination.total"
      :items-per-page="pagination.itemsPerPage"
      :items-per-page-options="[10, 20, 50]"
      :sort-by="pagination.sortBy"
      @update:options="onTableOptions"
      class="elevation-1 rounded-lg"
      v-if="groups.length || !loading"
    >
      <template #item.enable="{ item }">
        <VChip :color="item.enable ? 'success' : 'error'">{{ item.enable ? '启用' : '停用' }}</VChip>
      </template>
      <template #item.enable_chat="{ item }">
        <VChip :color="item.enable_chat ? 'info' : 'warning'">{{ item.enable_chat ? '开放' : '关闭' }}</VChip>
      </template>
      <template #item.message_count="{ item }">
        <span class="font-weight-medium">{{ item.message_count }}</span>
      </template>
      <template #item.last_activity="{ item }">
        {{ item.last_activity ? new Date(item.last_activity).toLocaleString() : '暂无' }}
      </template>
      <template #item.actions="{ item }">
        <VBtn size="small" variant="text" color="primary" prepend-icon="mdi-eye" @click="openDetail(item.id)">详情</VBtn>
      </template>
    </VDataTableServer>

    <VRow v-else>
      <VCol cols="12" v-for="index in 3" :key="index">
        <VSkeletonLoader height="7rem" class="rounded-lg" />
      </VCol>
    </VRow>

    <GroupDetailDialog
      v-model:visible="dialogVisible"
      :meta="meta"
      :group="detail"
      @submit="handleUpdate"
    />
  </section>
</template>
