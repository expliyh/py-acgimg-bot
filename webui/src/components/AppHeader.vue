<script setup lang="ts">
import { useAttrs } from 'vue';

defineProps<{ dark: boolean }>();
const attrs = useAttrs();
const emit = defineEmits<{
  (e: 'toggle-theme'): void;
  (e: 'toggle-drawer'): void;
  (e: 'change-password'): void;
  (e: 'logout'): void;
}>();
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
    <v-btn icon="mdi-theme-light-dark" variant="text" class="mr-2" :aria-label="dark ? '切换亮色主题' : '切换暗色主题'" :title="dark ? '切换亮色主题' : '切换暗色主题'" @click="emit('toggle-theme')" />
    <v-menu location="bottom end">
      <template #activator="{ props: menuProps }">
        <v-btn
          v-bind="menuProps"
          variant="text"
          prepend-icon="mdi-account-circle-outline"
          :aria-label="`当前账号 ${attrs.username ?? attrs['username'] ?? '管理员'}`"
        >
          <span class="d-none d-sm-inline">{{ attrs.username ?? attrs['username'] ?? '管理员' }}</span>
          <v-icon icon="mdi-chevron-down" size="18" class="ml-1" />
        </v-btn>
      </template>
      <v-list density="compact" min-width="180">
        <v-list-item prepend-icon="mdi-lock-reset" title="修改密码" @click="emit('change-password')" />
        <v-list-item prepend-icon="mdi-logout" title="退出登录" @click="emit('logout')" />
      </v-list>
    </v-menu>
  </v-app-bar>
</template>
