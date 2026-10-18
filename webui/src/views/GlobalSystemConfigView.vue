<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { useFeedback } from '@/composables/feedback';
import {
  fetchSystemConfig, saveSystemConfig,
  type SystemConfigSection, type SystemConfigValues,
} from '@/services/api';

const props = defineProps<{ section: SystemConfigSection }>();
const { toast } = useFeedback();
const values = ref<SystemConfigValues>({});
const loading = ref(false);
const saving = ref(false);
const loaded = ref(false);
const error = ref('');
let loadVersion = 0;

interface ConfigField {
  key: string;
  label: string;
  type?: 'password' | 'number' | 'textarea';
  min?: number;
  hint?: string;
  options?: { title: string; value: string }[];
}
interface ConfigGroup { title: string; fields: ConfigField[] }
interface ConfigSection { title: string; description: string; groups: ConfigGroup[] }
const sections: Record<SystemConfigSection, ConfigSection> = {
  storage: {
    title: '存储服务',
    description: '选择图片存储驱动，并设置对应服务。保存后下次文件操作使用新配置。',
    groups: [
      { title: '存储驱动', fields: [
        { key: 'storage_service_use', label: '当前驱动', options: [
          { title: '本地存储', value: 'local' },
          { title: 'Backblaze B2', value: 'backblaze' },
          { title: 'WebDAV', value: 'webdav' },
          { title: '禁用存储', value: 'disabled' },
        ] },
      ] },
      { title: '本地存储', fields: [
        { key: 'local_storage_root', label: '存储根目录', hint: '相对路径以项目目录为基准，留空使用 storage。' },
        { key: 'local_storage_base_url', label: '公开访问地址', hint: '可选 HTTP(S) 地址，留空保存相对路径。' },
      ] },
      { title: 'Backblaze B2', fields: [
        { key: 'backblaze_app_id', label: 'Application Key ID' },
        { key: 'backblaze_app_key', label: 'Application Key', type: 'password' },
        { key: 'backblaze_bucket_name', label: '存储桶名称' },
        { key: 'backblaze_base_path', label: '存储前缀（可选）' },
        { key: 'backblaze_base_url', label: '公开访问地址' },
      ] },
      { title: 'WebDAV', fields: [
        { key: 'webdav_endpoint', label: 'WebDAV 服务地址' },
        { key: 'webdav_username', label: '用户名（可选）' },
        { key: 'webdav_password', label: '密码', type: 'password' },
        { key: 'webdav_base_path', label: '存储前缀（可选）' },
        { key: 'webdav_public_url', label: '公开访问地址（可选）' },
      ] },
    ],
  },
  cache: {
    title: 'Telegram 缓存',
    description: '设置 Telegram 群管理员列表的缓存。保存后自动清理旧缓存并使用新设置。',
    groups: [{ title: '缓存设置', fields: [
      { key: 'backend', label: '缓存后端', options: [
        { title: '内存', value: 'memory' }, { title: 'Redis', value: 'redis' },
      ] },
      { key: 'ttl_seconds', label: '缓存有效期（秒）', type: 'number', min: 30, hint: '最少 30 秒，默认 300 秒。' },
      { key: 'redis_url', label: 'Redis 连接地址', type: 'password', hint: '例如 redis://localhost:6379/0，选择 Redis 时必填。' },
    ] }],
  },
  access: {
    title: '超级管理员',
    description: '设置允许使用机器人管理命令的 Telegram 用户 ID，保存后即时生效。',
    groups: [{ title: '管理权限', fields: [
      { key: 'super_user', label: '超级管理员 ID', type: 'textarea', hint: '使用逗号或换行分隔。留空允许所有用户使用管理命令。' },
    ] }],
  },
};
const section = computed(() => sections[props.section]);

function errorMessage(value: unknown): string {
  const response = value as { response?: { data?: { error?: { message?: string; fields?: Record<string, string[]> } } } };
  const detail = response.response?.data?.error;
  if (detail?.fields) return Object.values(detail.fields).flat().join('；');
  return detail?.message || '无法完成操作，请稍后重试。';
}

async function load() {
  const version = ++loadVersion;
  const key = props.section;
  loading.value = true;
  loaded.value = false;
  error.value = '';
  values.value = {};
  try {
    const result = await fetchSystemConfig(key);
    if (version !== loadVersion) return;
    values.value = result;
    loaded.value = true;
  } catch (value) {
    if (version === loadVersion) error.value = errorMessage(value);
  } finally {
    if (version === loadVersion) loading.value = false;
  }
}

async function save() {
  if (!loaded.value || saving.value) return;
  const version = loadVersion;
  const key = props.section;
  saving.value = true;
  error.value = '';
  try {
    const result = await saveSystemConfig(key, values.value);
    if (version !== loadVersion) return;
    values.value = result;
    toast.add({ severity: 'success', summary: '已保存', detail: `${sections[key].title}已更新。` });
  } catch (value) {
    if (version === loadVersion) error.value = errorMessage(value);
  } finally {
    saving.value = false;
  }
}

watch(() => props.section, load, { immediate: true });
</script>

<template>
  <section class="d-flex flex-column ga-4">
    <header class="d-flex align-start justify-space-between ga-3 flex-wrap">
      <div>
        <h2 class="text-h5 font-weight-bold ma-0">{{ section.title }}</h2>
        <p class="text-body-2 text-medium-emphasis mt-2 mb-0">{{ section.description }}</p>
      </div>
      <VBtn prepend-icon="mdi-refresh" variant="outlined" :loading="loading" :disabled="saving" @click="load">刷新</VBtn>
    </header>
    <VAlert v-if="error" type="error" variant="tonal">{{ error }}</VAlert>
    <VSkeletonLoader v-if="loading" type="card" />
    <form v-else-if="loaded" class="d-flex flex-column ga-4" @submit.prevent="save">
      <VCard v-for="group in section.groups" :key="group.title" class="content-card">
        <VCardTitle>{{ group.title }}</VCardTitle>
        <VCardText class="d-flex flex-column ga-3">
          <template v-for="field in group.fields" :key="field.key">
            <VSelect v-if="field.options" :id="`global-${field.key}`" v-model="values[field.key]" :label="field.label" :items="field.options" :disabled="saving" />
            <VTextarea v-else-if="field.type === 'textarea'" :id="`global-${field.key}`" v-model="values[field.key]" :label="field.label" :hint="field.hint" persistent-hint rows="4" :disabled="saving" />
            <VTextField v-else-if="field.type === 'number'" :id="`global-${field.key}`" v-model.number="values[field.key]" type="number" :min="field.min" :label="field.label" :hint="field.hint" persistent-hint :disabled="saving" />
            <VTextField v-else :id="`global-${field.key}`" v-model="values[field.key]" :type="field.type || 'text'" :autocomplete="field.type === 'password' ? 'new-password' : undefined" :label="field.label" :hint="field.hint" :persistent-hint="!!field.hint" :disabled="saving" />
          </template>
        </VCardText>
      </VCard>
      <div><VBtn type="submit" color="primary" prepend-icon="mdi-check" :loading="saving">保存设置</VBtn></div>
    </form>
  </section>
</template>
