<script setup lang="ts">
import { computed, reactive, ref } from 'vue';
import { isAxiosError } from 'axios';
import { useRoute, useRouter, RouterView } from 'vue-router';
import { useDisplay, useTheme } from 'vuetify';

import AppHeader from '@/components/AppHeader.vue';
import AppSidebar from '@/components/AppSidebar.vue';
import { useAdminAuth } from '@/composables/admin-auth';
import {
  acceptConfirmation,
  confirmState,
  feedbackState,
  rejectConfirmation,
  useFeedback
} from '@/composables/feedback';

const route = useRoute();
const router = useRouter();
const theme = useTheme();
const { mdAndUp } = useDisplay();
const { state: authState, signOut, updatePassword } = useAdminAuth();
const { toast } = useFeedback();
const drawer = ref<boolean | null>(null);
const isPublicPage = computed(() => route.meta.public === true);
const passwordDialog = ref(false);
const passwordSaving = ref(false);
const passwordError = ref('');
const passwordForm = reactive({ current: '', next: '', confirm: '' });
const navItems = [
  { label: '仪表盘', icon: 'mdi-view-dashboard-outline', to: '/dashboard', group: '工作空间' },
  { label: '群组管理', icon: 'mdi-account-group-outline', to: '/groups', group: '工作空间' },
  { label: '私聊管理', icon: 'mdi-message-processing-outline', to: '/private', group: '工作空间' },
  { label: '命令历史', icon: 'mdi-history', to: '/commands', group: '工作空间' },
  { label: '图片图库', icon: 'mdi-image-multiple-outline', to: '/illustrations', group: '内容管理' },
  { label: '插画导入', icon: 'mdi-image-plus-outline', to: '/illustrations/import', group: '内容管理' },
  { label: '图片推送', icon: 'mdi-send-check-outline', to: '/image-push', group: '内容管理' },
  { label: '全局配置', icon: 'mdi-cog-outline', to: '/global-config', group: '系统设置' }
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

async function handleLogout() {
  await signOut();
  passwordDialog.value = false;
  await router.replace({ name: 'login' });
}

function openPasswordDialog() {
  passwordError.value = '';
  passwordForm.current = '';
  passwordForm.next = '';
  passwordForm.confirm = '';
  passwordDialog.value = true;
}

function passwordErrorDetail(error: unknown): string {
  if (isAxiosError(error)) {
    const data = error.response?.data as { error?: { message?: string } } | undefined;
    if (data?.error?.message) return data.error.message;
  }
  return '修改密码失败，请稍后重试。';
}

async function submitPassword() {
  if (passwordSaving.value) return;
  passwordError.value = '';
  if (passwordForm.next.length < 8) {
    passwordError.value = '新密码至少需要 8 个字符。';
    return;
  }
  if (passwordForm.next !== passwordForm.confirm) {
    passwordError.value = '两次输入的新密码不一致。';
    return;
  }
  passwordSaving.value = true;
  try {
    await updatePassword(passwordForm.current, passwordForm.next);
    passwordDialog.value = false;
    toast.add({ severity: 'success', summary: '密码已更新', detail: '下次登录请使用新密码。' });
  } catch (error) {
    passwordError.value = passwordErrorDetail(error);
  } finally {
    passwordSaving.value = false;
  }
}
</script>

<template>
  <v-app>
    <RouterView v-if="isPublicPage" />
    <template v-else>
      <a class="skip-link" href="#main-content">跳转到主要内容</a>
      <AppHeader
        :dark="dark"
        :page-title="activeItem?.label"
        :username="authState.username"
        @toggle-theme="toggleTheme"
        @toggle-drawer="drawer = !drawer"
        @change-password="openPasswordDialog"
        @logout="handleLogout"
      />
      <v-navigation-drawer v-model="drawer" :permanent="mdAndUp" :temporary="!mdAndUp" width="248" color="surface" class="app-drawer">
        <AppSidebar :items="navItems" :active-path="activePath" @navigate="closeDrawer" />
      </v-navigation-drawer>
      <v-main id="main-content" tabindex="-1">
        <v-container fluid class="page-container"><RouterView /></v-container>
      </v-main>
    </template>
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
    <v-dialog v-model="passwordDialog" max-width="460">
      <v-card>
        <v-card-title class="d-flex align-center ga-2">
          <v-icon icon="mdi-lock-reset" />
          <span>修改登录密码</span>
          <v-spacer />
          <v-btn icon="mdi-close" variant="text" aria-label="关闭修改密码对话框" @click="passwordDialog = false" />
        </v-card-title>
        <v-card-text>
          <v-alert v-if="passwordError" type="error" variant="tonal" density="comfortable" class="mb-4" role="alert">
            {{ passwordError }}
          </v-alert>
          <v-form @submit.prevent="submitPassword">
            <v-text-field
              v-model="passwordForm.current"
              label="当前密码"
              type="password"
              autocomplete="current-password"
              :disabled="passwordSaving"
            />
            <v-text-field
              v-model="passwordForm.next"
              label="新密码（至少 8 位）"
              type="password"
              autocomplete="new-password"
              :disabled="passwordSaving"
            />
            <v-text-field
              v-model="passwordForm.confirm"
              label="确认新密码"
              type="password"
              autocomplete="new-password"
              :disabled="passwordSaving"
            />
          </v-form>
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="text" :disabled="passwordSaving" @click="passwordDialog = false">取消</v-btn>
          <v-btn color="primary" :loading="passwordSaving" @click="submitPassword">保存</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
    <v-snackbar v-model="feedbackState.open" :color="feedbackState.severity" :timeout="feedbackState.life">
      <strong v-if="feedbackState.summary">{{ feedbackState.summary }}：</strong>{{ feedbackState.detail }}
    </v-snackbar>
  </v-app>
</template>
