<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { useFeedback } from '@/composables/feedback';

import type { BotTokenInfo } from '@/services/api';
import {
  fetchBotToken,
  setBotToken,
  setBotTokenEnabled,
  deleteBotToken,
  reloadBotToken
} from '@/services/api';

const { toast, confirm } = useFeedback();

const loading = ref(true);
const saving = ref(false);
const info = ref<BotTokenInfo | null>(null);

const dialogVisible = ref(false);
const dialogToken = ref('');
const dialogEnabled = ref(true);
const showFullToken = ref(false);

const dialogModel = computed({
  get: () => dialogVisible.value,
  set: (value: boolean) => {
    dialogVisible.value = value;
  },
});

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
    toast.add({ severity: 'warning', summary: '无效输入', detail: 'Bot Token 不能为空。', life: 3000 });
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

async function toggleEnabled(value: boolean | null) {
  const enabled = value ?? false;
  try {
    info.value = await setBotTokenEnabled(enabled);
    toast.add({
      severity: 'success',
      summary: '已更新',
      detail: enabled ? 'Bot 已启用，点击“重新加载”使其生效。' : 'Bot 已停用，点击“重新加载”使其生效。'
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
    icon: 'mdi-alert-outline',
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
  <section class="d-flex flex-column ga-4">
    <header class="d-flex flex-column ga-2">
      <h2 class="text-h5 font-weight-bold ma-0">Bot Token 管理</h2>
      <p class="text-medium-emphasis ma-0">
        配置 Telegram Bot Token 与启用状态；修改后点击“重新加载”即可生效，无需重启后端。
      </p>
      <div class="d-flex ga-2">
        <VBtn prepend-icon="mdi-refresh" variant="outlined" @click="load" :loading="loading">刷新</VBtn>
        <VBtn prepend-icon="mdi-plus" :disabled="info?.configured" @click="openCreate">配置</VBtn>
      </div>
    </header>

    <VSkeletonLoader v-if="loading" height="12rem" class="rounded-lg" />

    <VCard v-else class="elevation-1">
      <VCardTitle>
        <div class="d-flex align-center justify-space-between">
          <span>Telegram Bot</span>
          <VChip v-if="info?.configured" size="small" :color="info?.enabled ? 'success' : 'warning'">{{ info?.enabled ? '已启用' : '已停用' }}</VChip>
          <VChip v-else size="small" color="error">未配置</VChip>
        </div>
      </VCardTitle>
      <VCardText>
        <div v-if="info?.configured" class="d-flex flex-column ga-4">
          <div class="d-flex flex-column ga-2">
            <span class="text-body-2 text-medium-emphasis">Bot Token</span>
            <div class="d-flex align-center ga-2">
              <code class="text-body-1 px-3 py-2 rounded-lg token-code" style="word-break: break-all">
                {{ showFullToken ? info.token : info.masked }}
              </code>
              <VBtn
                :icon="showFullToken ? 'mdi-eye-off' : 'mdi-eye'"
                variant="text"
                color="secondary"
                :aria-label="showFullToken ? '隐藏' : '显示'"
                @click="showFullToken = !showFullToken"
              />
            </div>
          </div>

          <div class="d-flex justify-space-between ga-3 align-center">
            <div class="d-flex flex-column ga-1">
              <span class="font-weight-medium">启用 Bot</span>
              <span class="text-body-2 text-medium-emphasis">停用后 Telegram 集成将停止接收消息。</span>
            </div>
            <VSwitch :model-value="info.enabled ?? false" color="primary" hide-details density="compact" @update:modelValue="toggleEnabled" />
          </div>

          <div class="d-flex flex-wrap ga-2">
            <VBtn prepend-icon="mdi-refresh" @click="onReload">重新加载</VBtn>
            <VBtn prepend-icon="mdi-pencil" variant="outlined" @click="openEdit">修改</VBtn>
            <VBtn prepend-icon="mdi-delete" color="error" variant="outlined" @click="onDelete">删除</VBtn>
          </div>
        </div>

        <div v-else class="d-flex flex-column ga-3">
          <p class="text-medium-emphasis ma-0">
            尚未配置 Bot Token。点击右上角“配置”按钮设置 Telegram Bot Token。
          </p>
        </div>
      </VCardText>
    </VCard>

    <VDialog v-model="dialogModel" max-width="448" aria-labelledby="bot-token-dialog-title">
      <VCard>
        <VCardTitle id="bot-token-dialog-title">{{ editing ? '修改 Bot Token' : '配置 Bot Token' }}</VCardTitle>
        <VCardText>
          <div class="d-flex flex-column ga-4">
        <div class="d-flex flex-column ga-2">
          <label for="bot-token-input" class="font-weight-medium">Bot Token</label>
          <VTextField
            id="bot-token-input"
            v-model="dialogToken"
            placeholder="123456789:AA...（从 @BotFather 获取）"
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
