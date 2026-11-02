<script setup lang="ts">
import { computed, ref } from 'vue';
import { isAxiosError } from 'axios';
import { useRoute, useRouter } from 'vue-router';

import { signIn } from '@/composables/admin-auth';

const route = useRoute();
const router = useRouter();
const username = ref('');
const password = ref('');
const showPassword = ref(false);
const loading = ref(false);
const errorMessage = ref('');

const canSubmit = computed(() => username.value.trim().length > 0 && password.value.length > 0);

function redirectTarget(): string {
  const value = route.query.redirect;
  if (typeof value === 'string' && value.startsWith('/') && !value.startsWith('//') && !value.startsWith('/login')) {
    return value;
  }
  return '/dashboard';
}

function errorDetail(error: unknown): string {
  if (isAxiosError(error)) {
    const data = error.response?.data as { error?: { message?: string } } | undefined;
    if (data?.error?.message) return data.error.message;
    if (error.response?.status === 429) return '登录尝试过于频繁，请稍后再试。';
  }
  return '无法连接服务器，请检查网络后重试。';
}

async function submit() {
  if (!canSubmit.value || loading.value) return;
  loading.value = true;
  errorMessage.value = '';
  try {
    await signIn(username.value.trim(), password.value);
    await router.replace(redirectTarget());
  } catch (error) {
    errorMessage.value = errorDetail(error);
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <div class="login-page">
    <v-card class="login-card" max-width="440" width="100%">
      <v-card-text class="pa-8 pa-sm-10">
        <div class="login-brand">
          <span class="brand-mark"><v-icon icon="mdi-shield-star-outline" size="26" /></span>
          <div>
            <div class="text-h5 font-weight-bold">ACG 图像管理后台</div>
            <div class="text-body-2 text-medium-emphasis mt-1">请登录后继续操作</div>
          </div>
        </div>

        <v-alert
          v-if="errorMessage"
          type="error"
          variant="tonal"
          density="comfortable"
          class="mt-6"
          role="alert"
        >{{ errorMessage }}</v-alert>

        <v-form class="mt-6" @submit.prevent="submit">
          <v-text-field
            v-model="username"
            label="用户名"
            autocomplete="username"
            prepend-inner-icon="mdi-account-outline"
            :disabled="loading"
            autofocus
          />
          <v-text-field
            v-model="password"
            label="密码"
            :type="showPassword ? 'text' : 'password'"
            autocomplete="current-password"
            prepend-inner-icon="mdi-lock-outline"
            :append-inner-icon="showPassword ? 'mdi-eye-off-outline' : 'mdi-eye-outline'"
            :disabled="loading"
            @click:append-inner="showPassword = !showPassword"
          />
          <v-btn
            type="submit"
            color="primary"
            size="large"
            class="mt-3 w-100"
            :loading="loading"
            :disabled="!canSubmit"
          >登录</v-btn>
        </v-form>

        <p class="login-hint text-caption text-medium-emphasis mt-6 mb-0">
          首次部署的初始密码可查看服务器上的
          <code>storage/admin-initial-password.txt</code>，或通过
          <code>ADMIN_USERNAME</code> / <code>ADMIN_PASSWORD</code> 环境变量配置。
        </p>
      </v-card-text>
    </v-card>
  </div>
</template>

<style scoped>
.login-page {
  display: grid;
  min-height: 100vh;
  padding: 24px;
  place-items: center;
  background:
    radial-gradient(circle at 15% 15%, color-mix(in srgb, rgb(var(--v-theme-primary)) 18%, transparent), transparent 42%),
    radial-gradient(circle at 85% 85%, color-mix(in srgb, rgb(var(--v-theme-info)) 14%, transparent), transparent 46%),
    rgb(var(--v-theme-background));
}
.login-card {
  border: 1px solid color-mix(in srgb, rgb(var(--v-theme-on-surface)) 9%, transparent);
  box-shadow: 0 24px 60px color-mix(in srgb, rgb(var(--v-theme-on-surface)) 12%, transparent) !important;
}
.login-brand {
  display: flex;
  gap: 14px;
  align-items: center;
}
.login-brand .brand-mark {
  display: grid;
  flex: none;
  width: 48px;
  height: 48px;
  color: white;
  background: rgb(var(--v-theme-primary));
  border-radius: 14px;
  place-items: center;
}
.login-hint {
  line-height: 1.6;
}
.login-hint code {
  padding: 1px 5px;
  border-radius: 5px;
  background: color-mix(in srgb, rgb(var(--v-theme-primary)) 10%, transparent);
}
</style>
