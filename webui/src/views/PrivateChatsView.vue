<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue';
import { useFeedback } from '@/composables/feedback';
import type { DataTableHeader, DataTableSortItem } from 'vuetify';

import PrivateUserDialog from '@/components/PrivateUserDialog.vue';
import type {
  PrivateMeta,
  PrivateUserDetail,
  PrivateUserListItem,
  PrivateUserListResponse,
  PrivateUserListQuery,
  PrivateUserUpdatePayload
} from '@/services/api';
import {
  fetchPrivateMeta,
  getPrivateUserDetail,
  listPrivateUsers,
  updatePrivateUser
} from '@/services/api';
import {
  createServerTableRequestGuard,
  toApiTableParams,
  type ServerTableOptions,
} from '@/utils/table-options';

const { toast } = useFeedback();
const loading = ref(true);
const meta = ref<PrivateMeta | null>(null);
const users = ref<PrivateUserListItem[]>([]);
const detail = ref<PrivateUserDetail | null>(null);
const dialogVisible = ref(false);

type NativeTableOptions = {
  page: number;
  itemsPerPage: number;
  sortBy: ReadonlyArray<DataTableSortItem>;
};

const headers: DataTableHeader<PrivateUserListItem>[] = [
  { title: '用户 ID', key: 'id', sortable: true },
  { title: '昵称', key: 'nick_name', sortable: true },
  { title: '聊天', key: 'enable_chat', sortable: false },
  { title: '状态', key: 'status', sortable: false },
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
const filters = reactive<{ q: string; chatEnabled: boolean | null; status: string | null }>({
  q: '',
  chatEnabled: null,
  status: null
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

const statusOptions = computed(() => [
  { label: '全部状态', value: null },
  ...(meta.value?.statuses ?? [])
]);

async function ensureMeta() {
  if (!meta.value) {
    meta.value = await fetchPrivateMeta();
  }
}

async function loadUsers(options: ServerTableOptions = pagination) {
  const requestId = requestGuard.begin(optionsKey(options));
  loading.value = true;
  try {
    const tableParams = toApiTableParams(options, ['id', 'nick_name']);
    const query: PrivateUserListQuery = {
      q: filters.q || undefined,
      chat_enabled: filters.chatEnabled === null ? undefined : filters.chatEnabled,
      status: filters.status || undefined,
      ...tableParams,
    };
    const response: PrivateUserListResponse = await listPrivateUsers(query);
    if (!requestGuard.isLatest(requestId)) return;
    users.value = response.items;
    pagination.total = response.total;
  } catch (error) {
    if (!requestGuard.isLatest(requestId)) return;
    requestGuard.invalidateFailed(requestId);
    console.error(error);
    toast.add({ severity: 'error', summary: '加载失败', detail: '无法获取私聊用户列表。', life: 4000 });
  } finally {
    if (requestGuard.isLatest(requestId)) {
      loading.value = false;
    }
  }
}

function onSearch() {
  const options = { ...pagination, page: 1 };
  pagination.page = 1;
  void loadUsers(options);
}

function onTableOptions(nativeOptions: NativeTableOptions) {
  if (!tableReady) return;

  const options = toServerTableOptions(nativeOptions);
  const key = optionsKey(options);
  if (!requestGuard.shouldLoad(key)) return;

  pagination.page = options.page;
  pagination.itemsPerPage = options.itemsPerPage;
  pagination.sortBy = options.sortBy;
  void loadUsers(options);
}

async function openDetail(userId: number) {
  try {
    await ensureMeta();
    detail.value = await getPrivateUserDetail(userId);
    dialogVisible.value = true;
  } catch (error) {
    console.error(error);
    toast.add({ severity: 'error', summary: '加载失败', detail: '无法获取用户详情。', life: 4000 });
  }
}

async function handleUpdate(payload: PrivateUserUpdatePayload) {
  if (!detail.value) return;
  try {
    const updated = await updatePrivateUser(detail.value.id, payload);
    detail.value = updated;
    users.value = users.value.map((user) => (user.id === updated.id ? updated : user));
    dialogVisible.value = false;
    toast.add({ severity: 'success', summary: '保存成功', detail: '用户设置已更新。', life: 2500 });
    await loadUsers();
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
      detail: '无法获取私聊元数据。',
      life: 4000,
    });
  }
  tableReady = true;
  await loadUsers(pagination);
});
</script>

<template>
  <section class="d-flex flex-column ga-4">
    <header class="d-flex flex-column ga-2">
      <h2 class="text-h5 font-weight-bold ma-0">私聊管理</h2>
      <p class="text-medium-emphasis ma-0">
        管理私聊用户的权限，追踪消息互动情况。
      </p>
      <VRow class="align-end ga-3">
        <VCol cols="12" md="4">
          <VTextField id="private-search" label="搜索用户 ID / 昵称" v-model="filters.q" placeholder="输入关键字" prepend-inner-icon="mdi-magnify" class="w-100" @keydown.enter="onSearch" />
        </VCol>
        <VCol cols="6" md="3">
          <VSelect
            id="private-chat-enabled"
            label="聊天状态"
            v-model="filters.chatEnabled"
            :items="[
              { label: '全部', value: null },
              { label: '可聊天', value: true },
              { label: '已禁用', value: false },
            ]"
            item-title="label"
            item-value="value"
            class="w-100"
            @update:modelValue="onSearch"
          />
        </VCol>
        <VCol cols="6" md="3">
          <VSelect
            id="private-status"
            label="用户状态"
            v-model="filters.status"
            :items="statusOptions"
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
      :items="users"
      :loading="loading"
      item-value="id"
      :page="pagination.page"
      :items-length="pagination.total"
      :items-per-page="pagination.itemsPerPage"
      :items-per-page-options="[10, 20, 50]"
      :sort-by="pagination.sortBy"
      @update:options="onTableOptions"
      class="elevation-1 rounded-lg"
      v-if="users.length || !loading"
    >
      <template #item.enable_chat="{ item }">
        <VChip :color="item.enable_chat ? 'success' : 'error'">{{ item.enable_chat ? '可用' : '禁用' }}</VChip>
      </template>
      <template #item.status="{ item }">
        <VChip color="info">{{ item.status }}</VChip>
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

    <PrivateUserDialog
      v-model:visible="dialogVisible"
      :meta="meta"
      :user="detail"
      @submit="handleUpdate"
    />
  </section>
</template>
