<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue';
import { useFeedback } from '@/composables/feedback';
import { guardApi, type AIConfig } from '@/services/guard-api';
import AIModelSelect from '@/components/AIModelSelect.vue';

const { toast } = useFeedback();
const loading = ref(true);
const loaded = ref(false);
const loadError = ref('');
const savingAI = ref(false);
const savingUsername = ref(false);
const aiConfig = reactive<AIConfig>({
  ai_text: null,
  ai_vision: null,
  ai_username: null,
});
const usernameWords = ref('');

function showError(summary: string, error: unknown) {
  console.error(error);
  const response = error as { response?: { data?: { error?: { message?: string; fields?: Record<string, string[]> } } } };
  const detail = response.response?.data?.error;
  const message = detail?.fields ? Object.values(detail.fields).flat().join('；') : detail?.message;
  toast.add({ severity: 'error', summary, detail: message || '请稍后重试。', life: 4000 });
}

async function load() {
  loading.value = true;
  loaded.value = false;
  loadError.value = '';
  try {
    const [model, username] = await Promise.all([
      guardApi.ai(),
      guardApi.usernameConfig(),
    ]);
    Object.assign(aiConfig, model);
    usernameWords.value = username.sensitive_words.join('\n');
    loaded.value = true;
  } catch (error) {
    loadError.value = '无法获取审核服务配置，请点击刷新重试。';
    showError('加载失败', error);
  } finally {
    loading.value = false;
  }
}

async function saveAI() {
  if (!loaded.value || savingAI.value) return;
  savingAI.value = true;
  try {
    Object.assign(aiConfig, await guardApi.saveAI({ ...aiConfig }));
    toast.add({ severity: 'success', summary: '已保存', detail: 'AI 审核服务配置已更新。' });
  } catch (error) {
    showError('保存失败', error);
  } finally {
    savingAI.value = false;
  }
}

async function saveUsername() {
  if (!loaded.value || savingUsername.value) return;
  savingUsername.value = true;
  try {
    const saved = await guardApi.saveUsernameConfig({
      sensitive_words: usernameWords.value
        .split(/[,，\n]+/)
        .map((word) => word.trim())
        .filter(Boolean),
    });
    usernameWords.value = saved.sensitive_words.join('\n');
    toast.add({ severity: 'success', summary: '已保存', detail: '全局用户名敏感词已更新。' });
  } catch (error) {
    showError('保存失败', error);
  } finally {
    savingUsername.value = false;
  }
}

async function restoreUsernameDefaults() {
  if (!loaded.value || savingUsername.value) return;
  savingUsername.value = true;
  try {
    const defaults = await guardApi.usernameDefaults();
    usernameWords.value = defaults.sensitive_words.join('\n');
    toast.add({ severity: 'info', summary: '已填入默认值', detail: '请点击保存后生效。' });
  } catch (error) {
    showError('读取默认值失败', error);
  } finally {
    savingUsername.value = false;
  }
}

onMounted(load);
</script>

<template>
  <div class="d-flex flex-column ga-4">
    <header class="d-flex align-center justify-space-between ga-3 flex-wrap">
      <div>
        <h2 class="text-h5 font-weight-bold ma-0">审核服务</h2>
        <p class="text-body-2 text-medium-emphasis mt-2 mb-0">这些配置由所有启用智能审核的群组共用。</p>
      </div>
      <VBtn prepend-icon="mdi-refresh" variant="outlined" :loading="loading" :disabled="savingAI || savingUsername" @click="load">刷新</VBtn>
    </header>

    <VSkeletonLoader v-if="loading" type="card" class="rounded-lg" />
    <VAlert v-else-if="loadError" type="error" variant="tonal">{{ loadError }}</VAlert>
    <template v-else-if="loaded">
      <VCard class="content-card">
        <VCardTitle>AI 审核默认模型</VCardTitle>
        <VCardText class="d-flex flex-column ga-4">
          <VAlert type="info" variant="tonal" density="compact">
            各群未单独选择时使用这里的默认模型。未配置或模型异常时，仅运行规则审核。图片遵循群现有分级，无法判断时进入复核。
          </VAlert>
          <AIModelSelect v-model="aiConfig.ai_text" label="文本审核" :disabled="savingAI" />
          <AIModelSelect v-model="aiConfig.ai_vision" label="图片审核" :input-types="['text', 'image']" :disabled="savingAI" />
          <AIModelSelect v-model="aiConfig.ai_username" label="用户名审核" :disabled="savingAI" />
          <div><VBtn color="primary" :loading="savingAI" @click="saveAI">保存默认模型</VBtn></div>
        </VCardText>
      </VCard>

      <VCard class="content-card">
        <VCardTitle>全局用户名敏感词</VCardTitle>
        <VCardText class="d-flex flex-column ga-3">
          <p class="text-body-2 text-medium-emphasis ma-0">对所有启用用户名审核的群组生效，并叠加本群追加词；每行一个，也可以使用逗号分隔。最多 200 个词，每词最多 100 个字符。</p>
          <VTextarea id="global-username-words" v-model="usernameWords" label="敏感词" rows="8" auto-grow :disabled="savingUsername" />
          <div class="d-flex ga-2 flex-wrap">
            <VBtn color="primary" :loading="savingUsername" @click="saveUsername">保存全局敏感词</VBtn>
            <VBtn variant="outlined" :disabled="savingUsername" @click="restoreUsernameDefaults">恢复默认</VBtn>
          </div>
          <p class="text-caption ma-0">恢复默认会填入默认词，保存后生效；清空并保存可停用全局词库。</p>
        </VCardText>
      </VCard>
    </template>
  </div>
</template>
