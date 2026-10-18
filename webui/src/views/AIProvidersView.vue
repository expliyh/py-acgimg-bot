<script setup lang="ts">
import { reactive, ref } from 'vue';
import { useAIProviders } from '@/composables/ai-providers';
import { useFeedback } from '@/composables/feedback';
import { aiApi, modalityOptions, newAIModel, type AIModality, type AIProvider, type AIProviderInput } from '@/services/ai-api';

const { providers, loading, error, refresh } = useAIProviders();
const { toast, confirm } = useFeedback();
const dialog = ref(false);
const editingId = ref<string | null>(null);
const hasKey = ref(false);
const clearKey = ref(false);
const busy = ref(false);
const form = reactive<AIProviderInput>({ name: '', base_url: '', api_key: '', models: [], timeout: 20, concurrency: 2 });
const formError = ref('');

function message(error: unknown) {
  const response = error as { response?: { data?: { detail?: string; error?: { message?: string; fields?: Record<string, string[]> } } } };
  const detail = response.response?.data;
  return detail?.error?.fields ? Object.values(detail.error.fields).flat().join('；') : detail?.error?.message || detail?.detail || '操作失败，请稍后重试。';
}

function edit(provider?: AIProvider) {
  editingId.value = provider?.id ?? null;
  hasKey.value = provider?.has_api_key ?? false;
  clearKey.value = false;
  Object.assign(form, {
    name: provider?.name ?? '', base_url: provider?.base_url ?? '', api_key: '',
    models: provider?.models.map((model) => ({ ...model, input_types: [...model.input_types], output_types: [...model.output_types] })) ?? [], timeout: provider?.timeout ?? 20, concurrency: provider?.concurrency ?? 2,
  });
  formError.value = '';
  dialog.value = true;
}

async function save() {
  if (busy.value) return;
  if (!form.name.trim() || !form.base_url.trim()) {
    formError.value = '请填写名称和 API 地址。';
    return;
  }
  if (form.models.some((model) => !model.id.trim() || !model.input_types.length || !model.output_types.length)) {
    formError.value = '每个模型需要填写 ID，并至少选择一种输入类型和输出类型。';
    return;
  }
  if (new Set(form.models.map((model) => model.id.trim())).size !== form.models.length) {
    formError.value = '模型 ID 不能重复。';
    return;
  }
  if (form.models.some((model) => [model.max_input_tokens, model.max_output_tokens].some((value) => value !== null && (!Number.isInteger(value) || value < 1 || value > 1000000000)))) {
    formError.value = 'Token 上限需为 1 至 1,000,000,000 的整数，也可留空。';
    return;
  }
  busy.value = true;
  formError.value = '';
  try {
    const payload = { ...form, api_key: clearKey.value ? '' : form.api_key || null };
    if (editingId.value) await aiApi.update(editingId.value, payload);
    else await aiApi.create(payload);
    dialog.value = false;
    form.api_key = '';
    await refresh();
    toast.add({ severity: 'success', summary: '已保存', detail: 'AI 提供商配置已更新。' });
  } catch (error) {
    formError.value = message(error);
  } finally { busy.value = false; }
}

function typeNames(types: AIModality[]) {
  return types.map((type) => modalityOptions.find((option) => option.value === type)?.title).join('、');
}

function remove(provider: AIProvider) {
  confirm.require({
    header: '删除 AI 提供商', message: `确认删除「${provider.name}」？`,
    accept: async () => {
      busy.value = true;
      try {
        await aiApi.remove(provider.id);
        await refresh();
        toast.add({ severity: 'success', summary: '已删除', detail: provider.name });
      } catch (error) {
        toast.add({ severity: 'error', summary: '删除失败', detail: message(error), life: 5000 });
      } finally { busy.value = false; }
    },
  });
}
</script>

<template>
  <div class="d-flex flex-column ga-4">
    <header class="d-flex align-center justify-space-between ga-3 flex-wrap">
      <div>
        <h2 class="text-h5 font-weight-bold ma-0">AI 提供商</h2>
        <p class="text-body-2 text-medium-emphasis mt-2 mb-0">统一管理兼容 Chat Completions 的服务，各功能独立选择提供商和模型。</p>
      </div>
      <div class="d-flex ga-2">
        <VBtn icon="mdi-refresh" height="40" width="40" aria-label="刷新提供商" variant="outlined" :loading="loading" :disabled="busy" @click="refresh" />
        <VBtn height="40" color="primary" prepend-icon="mdi-plus" :disabled="busy || loading || !!error" @click="edit()">添加提供商</VBtn>
      </div>
    </header>
    <VAlert v-if="error" type="error" variant="tonal">{{ error }}</VAlert>
    <VSkeletonLoader v-if="loading" type="card" />
    <VAlert v-else-if="!error && !providers.length" type="info" variant="tonal">还没有 AI 提供商，添加后即可在各功能中选择。</VAlert>
    <VCard v-for="provider in providers" :key="provider.id" class="content-card">
      <VCardTitle class="d-flex align-center justify-space-between ga-2 flex-wrap">
        <span>{{ provider.name }}</span>
        <div class="d-flex ga-1">
          <VBtn size="small" variant="text" prepend-icon="mdi-pencil-outline" :disabled="busy" @click="edit(provider)">编辑</VBtn>
          <VBtn size="small" variant="text" color="error" prepend-icon="mdi-delete-outline" :disabled="busy" @click="remove(provider)">删除</VBtn>
        </div>
      </VCardTitle>
      <VCardText>
        <p class="text-body-2 text-break">{{ provider.base_url }}</p>
        <p class="text-caption text-medium-emphasis">{{ provider.has_api_key ? '已配置密钥' : '无需密钥 / 未配置' }} · 超时 {{ provider.timeout }} 秒 · 提供商并发 {{ provider.concurrency }}</p>
        <div class="d-flex flex-column ga-3 mt-3">
          <div v-for="model in provider.models" :key="model.id" class="model-summary pa-3 rounded-lg">
            <div class="font-weight-medium text-break">{{ model.id }}</div>
            <div class="text-caption mt-1">输入：{{ typeNames(model.input_types) }} · 输出：{{ typeNames(model.output_types) }}</div>
            <div class="text-caption text-medium-emphasis">输入上限 {{ model.max_input_tokens?.toLocaleString() ?? '未设置' }} Token · 输出上限 {{ model.max_output_tokens?.toLocaleString() ?? '未设置' }} Token</div>
          </div>
        </div>
      </VCardText>
    </VCard>
    <VDialog v-model="dialog" max-width="800" scrollable :persistent="busy" aria-labelledby="ai-provider-title">
      <VCard>
        <VCardTitle id="ai-provider-title">{{ editingId ? '编辑' : '添加' }} AI 提供商</VCardTitle>
        <VCardText class="d-flex flex-column ga-3">
          <VAlert v-if="formError" type="error" variant="tonal">{{ formError }}</VAlert>
          <VTextField v-model="form.name" label="提供商名称" :disabled="busy" maxlength="100" />
          <VTextField v-model="form.base_url" label="API 地址" placeholder="https://api.example.com/v1" hint="通常以 /v1 结尾，服务会追加 /chat/completions" persistent-hint :disabled="busy" />
          <VTextField v-model="form.api_key" label="API 密钥" type="password" autocomplete="new-password" :hint="hasKey ? '已配置，留空保留原密钥' : '可留空，用于无需密钥的服务'" persistent-hint :disabled="busy || clearKey" />
          <VCheckbox v-if="hasKey" v-model="clearKey" label="清除已保存的密钥" :disabled="busy" hide-details />
          <VRow>
            <VCol cols="12" sm="6"><VNumberInput v-model="form.timeout" label="请求超时（秒）" :min="5" :max="120" :disabled="busy" /></VCol>
            <VCol cols="12" sm="6"><VNumberInput v-model="form.concurrency" label="提供商并发上限" :min="1" :max="10" hint="所有功能共用此上限" persistent-hint :disabled="busy" /></VCol>
          </VRow>
          <div class="d-flex align-center justify-space-between ga-2">
            <h3 class="text-subtitle-1">模型配置</h3>
            <VBtn variant="tonal" prepend-icon="mdi-plus" :disabled="busy || form.models.length >= 100" @click="form.models.push(newAIModel())">添加模型</VBtn>
          </div>
          <p class="text-caption text-medium-emphasis">每个模型独立配置能力。Token 上限留空表示未设置；输入容量由提供商计量，输出上限随请求发送。类型用于功能筛选，当前审核服务使用文本输出。</p>
          <VAlert v-if="!form.models.length" type="info" variant="tonal" density="compact">尚未添加模型，可先保存提供商。</VAlert>
          <VSheet v-for="(model, index) in form.models" :key="index" border rounded class="pa-4">
            <div class="d-flex align-center justify-space-between mb-3">
              <span class="text-subtitle-2">模型 {{ index + 1 }}</span>
              <VBtn variant="text" color="error" size="small" :aria-label="`移除模型 ${index + 1}`" :disabled="busy" @click="form.models.splice(index, 1)">移除</VBtn>
            </div>
            <VTextField v-model="model.id" label="模型 ID" maxlength="200" :disabled="busy" />
            <VRow>
              <VCol cols="12" sm="6"><VNumberInput v-model="model.max_input_tokens" label="输入上限（Token）" :min="1" :max="1000000000" clearable :disabled="busy" /></VCol>
              <VCol cols="12" sm="6"><VNumberInput v-model="model.max_output_tokens" label="输出上限（Token）" :min="1" :max="1000000000" clearable :disabled="busy" /></VCol>
              <VCol cols="12" sm="6"><VSelect v-model="model.input_types" label="可接受的输入类型" :items="modalityOptions" multiple chips :disabled="busy" /></VCol>
              <VCol cols="12" sm="6"><VSelect v-model="model.output_types" label="可接受的输出类型" :items="modalityOptions" multiple chips :disabled="busy" /></VCol>
            </VRow>
          </VSheet>
        </VCardText>
        <VCardActions><VSpacer /><VBtn :disabled="busy" @click="dialog = false">取消</VBtn><VBtn color="primary" :loading="busy" @click="save">保存</VBtn></VCardActions>
      </VCard>
    </VDialog>
  </div>
</template>

<style scoped>
.model-summary { background: color-mix(in srgb, var(--v-theme-on-surface) 4%, transparent); }
</style>
