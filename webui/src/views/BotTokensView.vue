<script setup lang="ts">
import { onMounted, ref } from 'vue';
import Card from 'primevue/card';
import InputSwitch from 'primevue/toggleswitch';
import Tag from 'primevue/tag';
import Button from 'primevue/button';
import Toast from 'primevue/toast';
import Dialog from 'primevue/dialog';
import InputText from 'primevue/inputtext';
import ConfirmDialog from 'primevue/confirmdialog';
import Skeleton from 'primevue/skeleton';
import { useToast } from 'primevue/usetoast';
import { useConfirm } from 'primevue/useconfirm';

import type { BotTokenInfo } from '@/services/api';
import {
  fetchBotToken,
  setBotToken,
  setBotTokenEnabled,
  deleteBotToken,
  reloadBotToken
} from '@/services/api';

const toast = useToast();
const confirm = useConfirm();

const loading = ref(true);
const saving = ref(false);
const info = ref<BotTokenInfo | null>(null);

const dialogVisible = ref(false);
const dialogToken = ref('');
const dialogEnabled = ref(true);
const showFullToken = ref(false);

const editing = ref(false);

async function load() {
  loading.value = true;
  try {
    info.value = await fetchBotToken();
  } catch (error) {
    console.error(error);
    toast.add({ severity: 'error', summary: '加载失败', detail: '无法获取 Bot Token 配置。', life: 4000 });
  } finally {
    loading.value = false;
  }
}

function openCreate() {
  editing.value = false;
  dialogToken.value = '';
  dialogEnabled.value = true;
  dialogVisible.value = true;
}

function openEdit() {
  editing.value = true;
  dialogToken.value = info.value?.token ?? '';
  dialogEnabled.value = info.value?.enabled ?? true;
  dialogVisible.value = true;
}

async function save() {
  const token = dialogToken.value.trim();
  if (!token) {
    toast.add({ severity: 'warn', summary: '无效输入', detail: 'Bot Token 不能为空。', life: 3000 });
    return;
  }
  saving.value = true;
  try {
    info.value = await setBotToken(token, dialogEnabled.value);
    dialogVisible.value = false;
    toast.add({
      severity: 'success',
      summary: '已保存',
      detail: editing.value ? 'Bot Token 已更新，点击“重新加载”使其生效。' : 'Bot Token 已配置。'
    });
  } catch (error) {
    console.error(error);
    toast.add({ severity: 'error', summary: '保存失败', detail: '请检查输入后重试。', life: 4000 });
  } finally {
    saving.value = false;
  }
}

async function toggleEnabled(value: boolean) {
  try {
    info.value = await setBotTokenEnabled(value);
    toast.add({
      severity: 'success',
      summary: '已更新',
      detail: value ? 'Bot 已启用，点击“重新加载”使其生效。' : 'Bot 已停用，点击“重新加载”使其生效。'
    });
  } catch (error) {
    console.error(error);
    toast.add({ severity: 'error', summary: '更新失败', detail: '请稍后重试。', life: 4000 });
  }
}

function onDelete() {
  confirm.require({
    message: '确定要删除 Bot Token 吗？删除后 Telegram 集成将停止工作。',
    header: '删除确认',
    icon: 'pi pi-exclamation-triangle',
    acceptLabel: '删除',
    rejectLabel: '取消',
    accept: async () => {
      try {
        info.value = await deleteBotToken();
        toast.add({ severity: 'success', summary: '已删除', detail: 'Bot Token 已清除。' });
      } catch (error) {
        console.error(error);
        toast.add({ severity: 'error', summary: '删除失败', detail: '请稍后重试。', life: 4000 });
      }
    }
  });
}

async function onReload() {
  try {
    info.value = await reloadBotToken();
    toast.add({
      severity: 'success',
      summary: '已重新加载',
      detail: info.value?.configured ? 'Telegram Bot 已按最新配置重新初始化。' : 'Telegram Bot 已停止（未配置或未启用）。'
    });
  } catch (error) {
    console.error(error);
    toast.add({ severity: 'error', summary: '重新加载失败', detail: '请检查 Token 是否有效。', life: 4000 });
  }
}

onMounted(load);
</script>

<template>
  <section class="flex flex-column gap-4">
    <Toast />
    <ConfirmDialog />
    <header class="flex flex-column gap-2">
      <h2 class="text-2xl font-semibold m-0">Bot Token 管理</h2>
      <p class="text-color-secondary m-0">
        配置 Telegram Bot Token 与启用状态；修改后点击“重新加载”即可生效，无需重启后端。
      </p>
      <div class="flex gap-2">
        <Button label="刷新" icon="pi pi-refresh" outlined @click="load" :loading="loading" />
        <Button label="配置" icon="pi pi-plus" :disabled="info?.configured" @click="openCreate" />
      </div>
    </header>

    <Skeleton v-if="loading" height="12rem" class="border-round" />

    <Card v-else class="shadow-1">
      <template #title>
        <div class="flex align-items-center justify-content-between">
          <span>Telegram Bot</span>
          <Tag v-if="info?.configured" :value="info?.enabled ? '已启用' : '已停用'" :severity="info?.enabled ? 'success' : 'warning'" />
          <Tag v-else value="未配置" severity="danger" />
        </div>
      </template>
      <template #content>
        <div v-if="info?.configured" class="flex flex-column gap-4">
          <div class="flex flex-column gap-2">
            <span class="text-sm text-color-secondary">Bot Token</span>
            <div class="flex align-items-center gap-2">
              <code class="text-base bg-primary-50 px-3 py-2 border-round" style="word-break: break-all">
                {{ showFullToken ? info.token : info.masked }}
              </code>
              <Button
                :icon="showFullToken ? 'pi pi-eye-slash' : 'pi pi-eye'"
                :label="showFullToken ? '隐藏' : '显示'"
                text
                severity="secondary"
                @click="showFullToken = !showFullToken"
              />
            </div>
          </div>

          <div class="flex justify-content-between gap-3 align-items-center">
            <div class="flex flex-column gap-1">
              <span class="font-medium">启用 Bot</span>
              <span class="text-sm text-color-secondary">停用后 Telegram 集成将停止接收消息。</span>
            </div>
            <InputSwitch :modelValue="info.enabled ?? false" @update:modelValue="toggleEnabled" />
          </div>

          <div class="flex flex-wrap gap-2">
            <Button label="重新加载" icon="pi pi-refresh" @click="onReload" />
            <Button label="修改" icon="pi pi-pencil" outlined @click="openEdit" />
            <Button label="删除" icon="pi pi-trash" severity="danger" outlined @click="onDelete" />
          </div>
        </div>

        <div v-else class="flex flex-column gap-3">
          <p class="text-color-secondary m-0">
            尚未配置 Bot Token。点击右上角“配置”按钮设置 Telegram Bot Token。
          </p>
        </div>
      </template>
    </Card>

    <Dialog
      v-model:visible="dialogVisible"
      :header="editing ? '修改 Bot Token' : '配置 Bot Token'"
      modal
      :style="{ width: '28rem' }"
    >
      <div class="flex flex-column gap-4 p-2">
        <div class="flex flex-column gap-2">
          <label for="bot-token-input" class="font-medium">Bot Token</label>
          <InputText
            id="bot-token-input"
            v-model="dialogToken"
            placeholder="123456789:AA...（从 @BotFather 获取）"
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
