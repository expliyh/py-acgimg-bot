<script setup lang="ts">
import { computed } from 'vue';
import { useAIProviders } from '@/composables/ai-providers';
import { supportsModel, type AIModality, type AISelection } from '@/services/ai-api';

const props = withDefaults(defineProps<{
  modelValue: AISelection | null;
  label: string;
  disabled?: boolean;
  inherit?: boolean;
  inputTypes?: AIModality[];
  outputTypes?: AIModality[];
}>(), { disabled: false, inherit: false, inputTypes: () => ['text'], outputTypes: () => ['text'] });
const emit = defineEmits<{ 'update:modelValue': [value: AISelection | null] }>();
const { providers, loading, error, refresh } = useAIProviders();
const provider = computed(() => providers.value.find((item) => item.id === props.modelValue?.provider_id));
const models = computed(() => (provider.value?.models ?? []).filter((model) => supportsModel(model, props.inputTypes, props.outputTypes)));
const selectedModel = computed(() => provider.value?.models.find((model) => model.id === props.modelValue?.model));
const unavailable = computed(() => props.modelValue && !loading.value && !error.value &&
  (!provider.value || (props.modelValue.model && !models.value.some((model) => model.id === props.modelValue?.model))));

function selectProvider(id: string | null) {
  emit('update:modelValue', id ? { provider_id: id, model: '' } : null);
}

function selectModel(model: string | null) {
  if (props.modelValue) emit('update:modelValue', { ...props.modelValue, model: model || '' });
}
</script>

<template>
  <fieldset class="ai-model-select pa-0 ma-0">
    <legend class="text-subtitle-2 mb-3">{{ label }}</legend>
    <VAlert v-if="error" type="error" variant="tonal" density="compact" class="mb-3">
      {{ error }} <VBtn size="small" variant="text" @click="refresh">重试</VBtn>
    </VAlert>
    <VRow>
      <VCol cols="12" sm="6">
        <VSelect
          :model-value="modelValue?.provider_id ?? null" :items="providers" item-title="name" item-value="id"
          :label="`${label}提供商`" :disabled="disabled || loading || !!error" :loading="loading" clearable
          :hint="inherit ? '留空使用全局审核服务的默认选择' : '留空停用此项 AI 审核'" persistent-hint
          @update:model-value="selectProvider"
        />
      </VCol>
      <VCol cols="12" sm="6">
        <VSelect
          :model-value="modelValue?.model || null" :items="models" item-title="id" item-value="id" :label="`${label}模型`"
          :disabled="disabled || loading || !provider || !!error"
          :error-messages="modelValue && !modelValue.model ? '请选择模型' : undefined"
          @update:model-value="selectModel"
        />
      </VCol>
    </VRow>
    <VAlert v-if="unavailable" type="warning" variant="tonal" density="compact" class="mb-3">当前提供商或模型已不可用，或不支持所需输入输出类型，请重新选择。</VAlert>
    <p v-if="selectedModel" class="text-caption text-medium-emphasis mb-3">输入上限 {{ selectedModel.max_input_tokens?.toLocaleString() ?? '未设置' }} Token · 输出上限 {{ selectedModel.max_output_tokens?.toLocaleString() ?? '未设置' }} Token</p>
    <p v-if="provider?.models.length && !models.length" class="text-body-2 mb-3">此提供商没有支持当前功能输入输出类型的模型。</p>
    <p v-if="provider && !provider.models.length" class="text-body-2 mb-3">此提供商尚未添加模型，请先在提供商配置中添加。</p>
    <p v-if="!loading && !error && !providers.length" class="text-body-2 mb-3">暂无提供商，请先添加。</p>
    <VBtn size="small" variant="text" prepend-icon="mdi-cog-outline" :to="{ name: 'global-ai-providers' }">管理 AI 提供商</VBtn>
  </fieldset>
</template>

<style scoped>
.ai-model-select { border: 0; min-width: 0; }
</style>
