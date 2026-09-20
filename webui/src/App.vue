<script setup lang="ts">
import { computed, ref } from 'vue';
import { useRoute, RouterView } from 'vue-router';
import { useDisplay, useTheme } from 'vuetify';

import AppHeader from '@/components/AppHeader.vue';
import AppSidebar from '@/components/AppSidebar.vue';
import {
  acceptConfirmation,
  confirmState,
  feedbackState,
  rejectConfirmation
} from '@/composables/feedback';

const route = useRoute();
const theme = useTheme();
const { mdAndUp } = useDisplay();
const drawer = ref<boolean | null>(null);
const navItems = [
  { label: '仪表盘', icon: 'mdi-view-dashboard-outline', to: '/dashboard', group: '工作空间' },
  { label: '群组管理', icon: 'mdi-account-group-outline', to: '/groups', group: '工作空间' },
  { label: '私聊管理', icon: 'mdi-message-processing-outline', to: '/private', group: '工作空间' },
  { label: '命令历史', icon: 'mdi-history', to: '/commands', group: '工作空间' },
  { label: '图片图库', icon: 'mdi-image-multiple-outline', to: '/illustrations', group: '内容管理' },
  { label: '插画导入', icon: 'mdi-image-plus-outline', to: '/illustrations/import', group: '内容管理' },
  { label: '图片推送', icon: 'mdi-send-check-outline', to: '/image-push', group: '内容管理' },
  { label: '功能配置', icon: 'mdi-tune-variant', to: '/features', group: '系统设置' },
  { label: 'Bot Token', icon: 'mdi-key-outline', to: '/bot-tokens', group: '系统设置' },
  { label: 'Pixiv Token', icon: 'mdi-palette-outline', to: '/pixiv-tokens', group: '系统设置' }
];
const activePath = computed(() => route.path);
const activeItem = computed(() => navItems.find((item) => item.to === route.path)
  ?? navItems.find((item) => route.path.startsWith(`${item.to}/`)));
const dark = computed(() => theme.global.current.value.dark);
const confirmationDialog = computed({
  get: () => confirmState.open,
  set: (value: boolean) => {
    if (!value) rejectConfirmation();
  }
});

function closeDrawer() {
  if (!mdAndUp.value) drawer.value = false;
}

function toggleTheme() {
  const next = dark.value ? 'light' : 'dark';
  theme.global.name.value = next;
  localStorage.setItem('acgimg-theme', next);
}
</script>

<template>
  <v-app>
    <a class="skip-link" href="#main-content">跳转到主要内容</a>
    <AppHeader :dark="dark" :page-title="activeItem?.label" @toggle-theme="toggleTheme" @toggle-drawer="drawer = !drawer" />
    <v-navigation-drawer v-model="drawer" :permanent="mdAndUp" :temporary="!mdAndUp" width="248" color="surface" class="app-drawer">
      <AppSidebar :items="navItems" :active-path="activePath" @navigate="closeDrawer" />
    </v-navigation-drawer>
    <v-main id="main-content" tabindex="-1">
      <v-container fluid class="page-container"><RouterView /></v-container>
    </v-main>
    <v-dialog
      v-model="confirmationDialog"
      max-width="480"
      aria-labelledby="confirmation-title"
      aria-describedby="confirmation-message"
      @click:outside="rejectConfirmation"
    >
      <v-card>
        <v-card-title id="confirmation-title" class="d-flex align-center ga-2">
          <v-icon v-if="confirmState.icon" :icon="confirmState.icon" />
          <span>{{ confirmState.header || '确认操作' }}</span>
          <v-spacer />
          <v-btn
            icon="mdi-close"
            variant="text"
            aria-label="关闭确认对话框"
            @click="rejectConfirmation"
          />
        </v-card-title>
        <v-card-text id="confirmation-message">{{ confirmState.message }}</v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="text" @click="rejectConfirmation">{{ confirmState.rejectLabel }}</v-btn>
          <v-btn color="primary" @click="acceptConfirmation">{{ confirmState.acceptLabel }}</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
    <v-snackbar v-model="feedbackState.open" :color="feedbackState.severity" :timeout="feedbackState.life">
      <strong v-if="feedbackState.summary">{{ feedbackState.summary }}：</strong>{{ feedbackState.detail }}
    </v-snackbar>
  </v-app>
</template>
