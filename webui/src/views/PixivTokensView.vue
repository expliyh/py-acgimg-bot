<script setup lang="ts">
import { onMounted, ref } from 'vue';
import DataTable from 'primevue/datatable';
import Column from 'primevue/column';
import InputSwitch from 'primevue/inputswitch';
import Button from 'primevue/button';
import Dialog from 'primevue/dialog';
import InputText from 'primevue/inputtext';
import ConfirmDialog from 'primevue/confirmdialog';
import Skeleton from 'primevue/skeleton';
import Tag from 'primevue/tag';
import Toast from 'primevue/toast';
import { useToast } from 'primevue/usetoast';
import { useConfirm } from 'primevue/useconfirm';

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

const toast = useToast();
const confirm = useConfirm();

const loading = ref(true);
const saving = ref(false);
const items = ref<PixivTokenItem[]>([]);

const dialogVisible = ref(false);
const editingId = ref<number | null>(null);
const dialogToken = ref('');
const dialogEnabled = ref(true);
const showFull = ref<Record<number, boolean>>({});

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
    toast.add({ severity: 'warn', summary: '无效输入', detail: 'Refresh Token 不能为空。', life: 3000 });
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
    icon: 'pi pi-exclamation-triangle',
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
  <section class="flex flex-column gap-4">
    <Toast />
    <ConfirmDialog />
    <header class="flex flex-column gap-2">
      <h2 class="text-2xl font-semibold m-0">Pixiv Token 管理</h2>
      <p class="text-color-secondary m-0">
        可配置多个 Pixiv Refresh Token（轮询负载均衡）；修改后点击“重新加载”即可生效，无需重启后端。
      </p>
      <div class="flex flex-wrap gap-2">
        <Button label="刷新" icon="pi pi-refresh" outlined @click="load" :loading="loading" />
        <Button label="添加" icon="pi pi-plus" @click="openCreate" />
        <Button label="全部启用" icon="pi pi-check-square" severity="success" outlined @click="toggleAll(true)" :disabled="!items.length" />
        <Button label="全部停用" icon="pi pi-ban" severity="warning" outlined @click="toggleAll(false)" :disabled="!items.length" />
        <Button label="重新加载" icon="pi pi-refresh" @click="onReload" />
      </div>
    </header>

    <Skeleton v-if="loading" height="14rem" class="border-round" />

    <DataTable v-else :value="items" :loading="loading" striped-rows class="shadow-1 border-round" :paginator="items.length > 10" :rows="10" paginator-template="FirstPageLink PrevPageLink PageLinks NextPageLink LastPageLink" data-key="id">
      <template #empty>
        <div class="p-4 text-center text-color-secondary">尚未配置 Pixiv Refresh Token，点击右上角“添加”开始配置。</div>
      </template>
      <Column field="id" header="ID" :style="{ width: '4rem' }" />
      <Column header="Refresh Token">
        <template #body="{ data }">
          <div class="flex align-items-center gap-2">
            <code class="text-sm bg-primary-50 px-2 py-1 border-round" style="word-break: break-all">
              {{ showFull[data.id] ? data.token : data.masked }}
            </code>
            <Button
              :icon="showFull[data.id] ? 'pi pi-eye-slash' : 'pi pi-eye'"
              text
              severity="secondary"
              @click="showFull[data.id] = !showFull[data.id]"
            />
          </div>
        </template>
      </Column>
      <Column header="状态" :style="{ width: '6rem' }">
        <template #body="{ data }">
          <Tag :value="data.enabled ? '启用' : '停用'" :severity="data.enabled ? 'success' : 'warning'" />
        </template>
      </Column>
      <Column header="启用" :style="{ width: '5rem' }">
        <template #body="{ data }">
          <InputSwitch :modelValue="data.enabled" @update:modelValue="(value) => toggleEnabled(data, value)" />
        </template>
      </Column>
      <Column header="操作" :style="{ width: '9rem' }">
        <template #body="{ data }">
          <div class="flex gap-1">
            <Button icon="pi pi-pencil" text severity="secondary" @click="openEdit(data)" />
            <Button icon="pi pi-trash" text severity="danger" @click="onDelete(data)" />
          </div>
        </template>
      </Column>
    </DataTable>

    <Dialog
      v-model:visible="dialogVisible"
      :header="editingId === null ? '添加 Pixiv Token' : `修改 Pixiv Token #${editingId}`"
      modal
      :style="{ width: '30rem' }"
    >
      <div class="flex flex-column gap-4 p-2">
        <div class="flex flex-column gap-2">
          <label for="pixiv-token-input" class="font-medium">Refresh Token</label>
          <InputText
            id="pixiv-token-input"
            v-model="dialogToken"
            placeholder="从 Pixiv 申请到的 refresh_token"
            autocomplete="off"
            class="w-full"
          />
        </div>
        <div class="flex justify-content-between gap-3 align-items-center">
          <span class="font-medium">配置后立即启用</span>
          <InputSwitch v-model="dialogEnabled" />
        </div>
        <div class="flex justify-content-end gap-2">
          <Button label="取消" severity="secondary" outlined @click="dialogVisible = false" />
          <Button label="保存" icon="pi pi-check" :loading="saving" @click="save" />
        </div>
      </div>
    </Dialog>
  </section>
</template>
