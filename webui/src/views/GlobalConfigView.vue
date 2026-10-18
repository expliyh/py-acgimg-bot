<script setup lang="ts">
import { computed } from 'vue';
import { RouterView, useRoute, useRouter } from 'vue-router';

const route = useRoute();
const router = useRouter();
const sections = [
  {
    label: '功能开关',
    description: '管理内容安全与推荐相关的全局功能。',
    icon: 'mdi-tune-variant',
    name: 'features',
  },
  {
    label: 'Telegram Bot',
    description: '配置 Bot Token、启用状态与运行时重载。',
    icon: 'mdi-key-outline',
    name: 'bot-tokens',
  },
  {
    label: 'Pixiv Token',
    description: '管理 Pixiv Refresh Token 轮询池。',
    icon: 'mdi-palette-outline',
    name: 'pixiv-tokens',
  },
  {
    label: 'AI 提供商',
    description: '统一管理多个 AI 服务、密钥和模型列表。',
    icon: 'mdi-creation-outline',
    name: 'global-ai-providers',
  },
  {
    label: '审核服务',
    description: '选择各类审核的默认模型，管理全局用户名词库。',
    icon: 'mdi-shield-check-outline',
    name: 'global-moderation',
  },
  {
    label: '存储服务',
    description: '选择本地、Backblaze B2 或 WebDAV 存储。',
    icon: 'mdi-database-cog-outline',
    name: 'global-storage',
  },
  {
    label: 'Telegram 缓存',
    description: '管理缓存后端、有效期与 Redis 连接。',
    icon: 'mdi-cached',
    name: 'global-cache',
  },
  {
    label: '超级管理员',
    description: '管理可以执行机器人管理命令的用户。',
    icon: 'mdi-account-key-outline',
    name: 'global-access',
  },
] as const;

const activeName = computed(() => String(route.name ?? 'features'));

function selectSection(name: string) {
  void router.push({ name });
}
</script>

<template>
  <section class="global-config d-flex flex-column ga-5">
    <header class="page-heading flex-wrap">
      <div>
        <h1 class="text-h4 font-weight-bold ma-0">全局配置</h1>
        <p class="text-body-1 text-medium-emphasis mt-2 mb-0">
          集中管理会影响整个部署的功能、凭据与审核服务配置。
        </p>
      </div>
      <VChip prepend-icon="mdi-earth" color="primary" variant="tonal">部署级设置</VChip>
    </header>

    <VRow class="align-start">
      <VCol cols="12" md="4" lg="3">
        <VSelect
          id="global-config-section"
          class="d-md-none"
          label="配置分类"
          :model-value="activeName"
          :items="sections.map((item) => ({ title: item.label, value: item.name }))"
          hide-details
          @update:model-value="selectSection"
        />
        <VCard class="global-config-nav content-card d-none d-md-block">
          <VCardTitle class="text-subtitle-1">配置分类</VCardTitle>
          <VList nav density="comfortable" class="pa-2" aria-label="全局配置分类">
            <VListItem
              v-for="section in sections"
              :key="section.name"
              :active="activeName === section.name"
              :aria-current="activeName === section.name ? 'page' : undefined"
              color="primary"
              rounded="lg"
              :to="{ name: section.name }"
              :prepend-icon="section.icon"
              :title="section.label"
              :subtitle="section.description"
            />
          </VList>
        </VCard>
      </VCol>
      <VCol cols="12" md="8" lg="9">
        <RouterView />
      </VCol>
    </VRow>
  </section>
</template>

<style scoped>
.global-config-nav :deep(.v-list-item-subtitle) {
  white-space: normal;
  -webkit-line-clamp: 2;
  line-height: 1.35;
  margin-top: 3px;
}
</style>
