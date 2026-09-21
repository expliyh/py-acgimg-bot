<script setup lang="ts">
import { useAttrs } from 'vue';

defineProps<{ dark: boolean }>();
const attrs = useAttrs();
const emit = defineEmits<{ (e: 'toggle-theme'): void; (e: 'toggle-drawer'): void }>();
</script>

<template>
  <v-app-bar flat height="72" color="surface" class="app-header">
    <v-app-bar-nav-icon class="d-md-none" aria-label="打开导航菜单" @click="emit('toggle-drawer')" />
    <RouterLink to="/dashboard" class="app-brand" aria-label="ACG 管理后台首页">
      <span class="brand-mark"><v-icon icon="mdi-shield-star-outline" size="22" /></span>
      <span class="brand-name">ACG<span class="brand-subtitle">图像管理后台</span></span>
    </RouterLink>
    <div class="header-location d-none d-md-flex">
      <span class="text-medium-emphasis">控制台</span>
      <v-icon icon="mdi-chevron-right" size="16" class="text-disabled" />
      <span>{{ attrs.pageTitle ?? attrs['page-title'] }}</span>
    </div>
    <v-spacer />
    <v-btn icon="mdi-theme-light-dark" variant="text" class="mr-3" :aria-label="dark ? '切换亮色主题' : '切换暗色主题'" :title="dark ? '切换亮色主题' : '切换暗色主题'" @click="emit('toggle-theme')" />
  </v-app-bar>
</template>
