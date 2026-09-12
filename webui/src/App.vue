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
  { label: '仪表盘', icon: 'mdi-view-dashboard-outline', to: '/dashboard' },
  { label: '群组管理', icon: 'mdi-account-group-outline', to: '/groups' },
  { label: '私聊管理', icon: 'mdi-message-processing-outline', to: '/private' },
  { label: '命令历史', icon: 'mdi-history', to: '/commands' },
  { label: '功能配置', icon: 'mdi-tune-variant', to: '/features' },
  { label: 'Bot Token', icon: 'mdi-key-outline', to: '/bot-tokens' },
  { label: 'Pixiv Token', icon: 'mdi-palette-outline', to: '/pixiv-tokens' },
  { label: '插画导入', icon: 'mdi-image-plus-outline', to: '/illustrations/import' }
];
const activePath = computed(() => route.path);
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
    <AppHeader :dark="dark" @toggle-theme="toggleTheme" @toggle-drawer="drawer = !drawer" />
    <v-navigation-drawer v-model="drawer" :permanent="mdAndUp" :temporary="!mdAndUp" width="264" color="surface">
      <AppSidebar :items="navItems" :active-path="activePath" @navigate="closeDrawer" />
    </v-navigation-drawer>
    <v-main>
      <v-container fluid class="pa-4 pa-md-6 page-container"><RouterView /></v-container>
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
