<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { useFeedback } from '@/composables/feedback';

import type { DataTableHeader } from 'vuetify';
import type { PixivTokenItem } from '@/services/api';
import {
  listPixivTokens,
  addPixivToken,
  updatePixivToken,
  setPixivTokenEnabled,
  setAllPixivTokensEnabled,
  deletePixivToken,
  reloadPixivTokens
} from '@/services/api';

const { toast, confirm } = useFeedback();

const loading = ref(true);
const saving = ref(false);
const items = ref<PixivTokenItem[]>([]);

const dialogVisible = ref(false);
const editingId = ref<number | null>(null);
const dialogToken = ref('');
const dialogEnabled = ref(true);
const showFull = ref<Record<number, boolean>>({});

const dialogModel = computed({
  get: () => dialogVisible.value,
  set: (value: boolean) => {
    dialogVisible.value = value;
  },
});

const headers: DataTableHeader<PixivTokenItem>[] = [
  { title: 'ID', key: 'id', sortable: false },
  { title: 'Refresh Token', key: 'token', sortable: false },
  { title: '状态', key: 'status', sortable: false },
  { title: '启用', key: 'enabled', sortable: false },
  { title: '操作', key: 'actions', sortable: false },
];

async function load() {
  loading.value = true;
  try {
    const response = await listPixivTokens();
    items.value = response.items;
  } catch (error) {
    console.error(error);
    toast.add({ severity: 'error', summary: '加载失败', detail: '无法获取 Pixiv Token 列表。', life: 4000 });
  } finally {
    loading.value = false;
  }
}

function openCreate() {
  editingId.value = null;
  dialogToken.value = '';
  dialogEnabled.value = true;
  dialogVisible.value = true;
}

function openEdit(item: PixivTokenItem) {
  editingId.value = item.id;
  dialogToken.value = item.token;
  dialogEnabled.value = item.enabled;
  dialogVisible.value = true;
}

async function save() {
  const token = dialogToken.value.trim();
  if (!token) {
    toast.add({ severity: 'warning', summary: '无效输入', detail: 'Refresh Token 不能为空。', life: 3000 });
    return;
  }
  saving.value = true;
  try {
    if (editingId.value === null) {
      await addPixivToken(token, dialogEnabled.value);
      toast.add({ severity: 'success', summary: '已添加', detail: 'Pixiv Token 已添加，点击“重新加载”使其生效。' });
    } else {
      await updatePixivToken(editingId.value, token);
      await setPixivTokenEnabled(editingId.value, dialogEnabled.value);
      toast.add({ severity: 'success', summary: '已更新', detail: 'Pixiv Token 已更新，点击“重新加载”使其生效。' });
    }
    dialogVisible.value = false;
    await load();
  } catch (error) {
    console.error(error);
    toast.add({ severity: 'error', summary: '保存失败', detail: '请检查输入后重试。', life: 4000 });
  } finally {
    saving.value = false;
  }
}

async function toggleEnabled(item: PixivTokenItem, value: boolean) {
  try {
    await setPixivTokenEnabled(item.id, value);
    item.enabled = value;
    toast.add({ severity: 'success', summary: '已更新', detail: value ? '已启用，点击“重新加载”生效。' : '已停用，点击“重新加载”生效。' });
  } catch (error) {
    console.error(error);
    toast.add({ severity: 'error', summary: '更新失败', detail: '请稍后重试。', life: 4000 });
  }
}

async function toggleAll(value: boolean) {
  try {
    await setAllPixivTokensEnabled(value);
    await load();
    toast.add({ severity: 'success', summary: '已更新', detail: value ? '已全部启用，点击“重新加载”生效。' : '已全部停用。' });
  } catch (error) {
    console.error(error);
    toast.add({ severity: 'error', summary: '更新失败', detail: '请稍后重试。', life: 4000 });
  }
}

function onDelete(item: PixivTokenItem) {
  confirm.require({
    message: `确定要删除第 ${item.id} 个 Pixiv Token 吗？`,
    header: '删除确认',
    icon: 'mdi-alert-outline',
    acceptLabel: '删除',
    rejectLabel: '取消',
    accept: async () => {
      try {
        await deletePixivToken(item.id);
        toast.add({ severity: 'success', summary: '已删除', detail: 'Pixiv Token 已删除。' });
        await load();
      } catch (error) {
        console.error(error);
        toast.add({ severity: 'error', summary: '删除失败', detail: '请稍后重试。', life: 4000 });
      }
    }
  });
}

async function onReload() {
  try {
    await reloadPixivTokens();
    toast.add({ severity: 'success', summary: '已重新加载', detail: 'Pixiv 已按最新配置重新初始化。' });
    await load();
  } catch (error) {
    console.error(error);
    toast.add({ severity: 'error', summary: '重新加载失败', detail: '请检查 Refresh Token 是否有效。', life: 4000 });
  }
}

onMounted(load);
</script>

<template>
  <section class="d-flex flex-column ga-4">
    <header class="d-flex flex-column ga-2">
      <h2 class="text-h5 font-weight-bold ma-0">Pixiv Token 管理</h2>
      <p class="text-medium-emphasis ma-0">
        可配置多个 Pixiv Refresh Token（轮询负载均衡）；修改后点击“重新加载”即可生效，无需重启后端。
      </p>
      <div class="d-flex flex-wrap ga-2">
        <VBtn prepend-icon="mdi-refresh" variant="outlined" @click="load" :loading="loading">刷新</VBtn>
        <VBtn prepend-icon="mdi-plus" @click="openCreate">添加</VBtn>
        <VBtn prepend-icon="mdi-checkbox-marked-outline" color="success" variant="outlined" @click="toggleAll(true)" :disabled="!items.length">全部启用</VBtn>
        <VBtn prepend-icon="mdi-cancel" color="warning" variant="outlined" @click="toggleAll(false)" :disabled="!items.length">全部停用</VBtn>
        <VBtn prepend-icon="mdi-refresh" @click="onReload">重新加载</VBtn>
      </div>
    </header>

    <VSkeletonLoader v-if="loading" height="14rem" class="rounded-lg" />

    <VDataTable
      v-else
      :headers="headers"
      :items="items"
      :loading="loading"
      item-value="id"
      :items-per-page="10"
      :hide-default-footer="items.length <= 10"
      class="elevation-1 rounded-lg"
    >
      <template #no-data>
        <div class="p-4 text-center text-medium-emphasis">尚未配置 Pixiv Refresh Token，点击右上角“添加”开始配置。</div>
      </template>
      <template #item.token="{ item }">
          <div class="d-flex align-center ga-2">
            <code class="text-body-2 px-2 py-1 rounded-lg token-code" style="word-break: break-all">
              {{ showFull[item.id] ? item.token : item.masked }}
            </code>
            <VBtn
              :icon="showFull[item.id] ? 'mdi-eye-off' : 'mdi-eye'"
              variant="text"
              color="secondary"
              :aria-label="showFull[item.id] ? '隐藏' : '显示'"
              @click.stop="showFull[item.id] = !showFull[item.id]"
            />
          </div>
      </template>
      <template #item.status="{ item }">
          <div class="d-flex align-center justify-start w-100">
            <VChip size="small" :color="item.enabled ? 'success' : 'warning'">{{ item.enabled ? '启用' : '停用' }}</VChip>
          </div>
      </template>
      <template #item.enabled="{ item }">
          <div class="d-flex align-center justify-start w-100">
            <VSwitch
              :model-value="item.enabled"
              color="primary"
              hide-details
              density="compact"
              @update:modelValue="(value: boolean | null) => toggleEnabled(item, value ?? false)"
            />
          </div>
      </template>
      <template #item.actions="{ item }">
          <div class="d-flex align-center justify-start w-100 ga-1">
            <VBtn icon="mdi-pencil" variant="text" color="secondary" aria-label="修改" @click.stop="openEdit(item)" />
            <VBtn icon="mdi-delete" variant="text" color="error" aria-label="删除" @click.stop="onDelete(item)" />
          </div>
      </template>
    </VDataTable>

    <VDialog v-model="dialogModel" max-width="480" aria-labelledby="pixiv-token-dialog-title">
      <VCard>
        <VCardTitle id="pixiv-token-dialog-title">{{ editingId === null ? '添加 Pixiv Token' : `修改 Pixiv Token #${editingId}` }}</VCardTitle>
        <VCardText>
          <div class="d-flex flex-column ga-4">
        <div class="d-flex flex-column ga-2">
          <label for="pixiv-token-input" class="font-weight-medium">Refresh Token</label>
          <VTextField
            id="pixiv-token-input"
            v-model="dialogToken"
            placeholder="从 Pixiv 申请到的 refresh_token"
            autocomplete="off"
            class="w-100"
          />
        </div>
        <div class="d-flex justify-space-between ga-3 align-center">
          <span class="font-weight-medium">配置后立即启用</span>
          <VSwitch v-model="dialogEnabled" color="primary" hide-details density="compact" />
        </div>
          </div>
        </VCardText>
        <VCardActions class="justify-end ga-2">
          <VBtn color="secondary" variant="outlined" @click="dialogModel = false">取消</VBtn>
          <VBtn prepend-icon="mdi-check" :loading="saving" @click="save">保存</VBtn>
        </VCardActions>
      </VCard>
    </VDialog>
  </section>
</template>
