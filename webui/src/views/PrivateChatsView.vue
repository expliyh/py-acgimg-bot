<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue';
import DataTable from 'primevue/datatable';
import Column from 'primevue/column';
import InputText from 'primevue/inputtext';
import Dropdown from 'primevue/dropdown';
import Button from 'primevue/button';
import Tag from 'primevue/tag';
import Toast from 'primevue/toast';
import { useToast } from 'primevue/usetoast';
import Skeleton from 'primevue/skeleton';

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

const toast = useToast();
const loading = ref(true);
const meta = ref<PrivateMeta | null>(null);
const users = ref<PrivateUserListItem[]>([]);
const detail = ref<PrivateUserDetail | null>(null);
const dialogVisible = ref(false);

const pagination = reactive({ page: 0, rows: 10, total: 0 });
const filters = reactive<{ q: string; chatEnabled: boolean | null; status: string | null }>({
  q: '',
  chatEnabled: null,
  status: null
});

const statusOptions = computed(() => [
  { label: '全部状态', value: null },
  ...(meta.value?.statuses ?? [])
]);

async function ensureMeta() {
  if (!meta.value) {
    meta.value = await fetchPrivateMeta();
  }
}

async function loadUsers() {
  loading.value = true;
  try {
    const query: PrivateUserListQuery = {
      q: filters.q || undefined,
      chat_enabled: filters.chatEnabled === null ? undefined : filters.chatEnabled,
      status: filters.status || undefined,
      limit: pagination.rows,
      offset: pagination.page * pagination.rows
    };
    const response: PrivateUserListResponse = await listPrivateUsers(query);
    users.value = response.items;
    pagination.total = response.total;
  } catch (error) {
    console.error(error);
    toast.add({ severity: 'error', summary: '加载失败', detail: '无法获取私聊用户列表。', life: 4000 });
  } finally {
    loading.value = false;
  }
}

function onSearch() {
  pagination.page = 0;
  loadUsers();
}

function onPage(event: { page: number; rows: number }) {
  pagination.page = event.page;
  pagination.rows = event.rows;
  loadUsers();
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
    toast.add({ severity: 'success', summary: '保存成功', detail: '用户设置已更新。', life: 2500 });
    await loadUsers();
  } catch (error) {
    console.error(error);
    toast.add({ severity: 'error', summary: '保存失败', detail: '请稍后重试。', life: 4000 });
  }
}

onMounted(async () => {
  await ensureMeta();
  await loadUsers();
});
</script>

<template>
  <section class="flex flex-column gap-4">
    <Toast />
    <header class="flex flex-column gap-2">
      <h2 class="text-2xl font-semibold m-0">私聊管理</h2>
      <p class="text-color-secondary m-0">
        管理私聊用户的权限，追踪消息互动情况。
      </p>
      <div class="grid align-items-end gap-3">
        <div class="col-12 md:col-4">
          <label class="block text-sm text-color-secondary mb-2">搜索用户 ID / 昵称</label>
          <span class="p-input-icon-left w-full">
            <i class="pi pi-search" />
            <InputText v-model="filters.q" placeholder="输入关键字" class="w-full" @keydown.enter="onSearch" />
          </span>
        </div>
        <div class="col-6 md:col-3">
          <label class="block text-sm text-color-secondary mb-2">聊天状态</label>
          <Dropdown
            v-model="filters.chatEnabled"
            :options="[
              { label: '全部', value: null },
              { label: '可聊天', value: true },
              { label: '已禁用', value: false }
            ]"
            optionLabel="label"
            optionValue="value"
            class="w-full"
            @change="onSearch"
          />
        </div>
        <div class="col-6 md:col-3">
          <label class="block text-sm text-color-secondary mb-2">用户状态</label>
          <Dropdown
            v-model="filters.status"
            :options="statusOptions"
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
      :value="users"
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
      v-if="users.length || !loading"
    >
      <Column field="id" header="用户 ID" sortable />
      <Column field="nick_name" header="昵称" sortable />
      <Column header="聊天">
        <template #body="{ data }">
          <Tag :value="data.enable_chat ? '可用' : '禁用'" :severity="data.enable_chat ? 'success' : 'danger'" />
        </template>
      </Column>
      <Column header="状态">
        <template #body="{ data }">
          <Tag :value="data.status" severity="info" />
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

    <PrivateUserDialog
      v-model:visible="dialogVisible"
      :meta="meta"
      :user="detail"
      @submit="handleUpdate"
    />
  </section>
</template>
