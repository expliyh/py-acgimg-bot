<script setup lang="ts">
import { computed } from 'vue';
import { useRoute, useRouter, RouterView } from 'vue-router';

import AppHeader from '@/components/AppHeader.vue';
import AppSidebar from '@/components/AppSidebar.vue';

const router = useRouter();
const route = useRoute();

const navItems = [
  { label: '仪表盘', icon: 'pi pi-chart-line', to: '/dashboard' },
  { label: '群组管理', icon: 'pi pi-users', to: '/groups' },
  { label: '私聊管理', icon: 'pi pi-comments', to: '/private' },
  { label: '命令历史', icon: 'pi pi-list', to: '/commands' },
  { label: '功能配置', icon: 'pi pi-sliders-h', to: '/features' }
];

const activePath = computed(() => route.path);

function handleNavigate(path: string) {
  if (path !== route.path) {
    router.push(path);
  }
}
</script>

<template>
  <div class="layout-shell">
    <AppHeader :items="navItems" :active-path="activePath" @navigate="handleNavigate" />
    <div class="layout-content">
      <AppSidebar
        class="layout-sidebar"
        :items="navItems"
        :active-path="activePath"
        @navigate="handleNavigate"
      />
      <main class="layout-main">
        <RouterView />
      </main>
    </div>
  </div>
</template>
