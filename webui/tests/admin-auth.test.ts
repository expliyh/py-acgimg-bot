import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

function source(path: string): string {
  return readFileSync(new URL(`../src/${path}`, import.meta.url), 'utf8');
}

const routerSource = source('router/index.ts');
const appSource = source('App.vue');
const headerSource = source('components/AppHeader.vue');
const loginSource = source('views/LoginView.vue');
const authSource = source('composables/admin-auth.ts');

test('the admin router guards protected views behind the login route', () => {
  assert.match(routerSource, /path: '\/login'/);
  assert.match(routerSource, /meta: \{ public: true \}/);
  assert.match(routerSource, /router\.beforeEach\(async \(to\) =>/);
  assert.match(routerSource, /await refreshAdminAuth\(true\)/);
  assert.match(routerSource, /name: 'login', query: \{ redirect: to\.fullPath \}/);
});

test('the login view submits credentials through the auth composable', () => {
  assert.match(loginSource, /await signIn\(username\.value\.trim\(\), password\.value\)/);
  assert.match(loginSource, /autocomplete="current-password"/);
  assert.match(loginSource, /@submit\.prevent="submit"/);
  assert.match(authSource, /loginAdmin/);
  assert.match(authSource, /fetchCurrentAdmin/);
});

test('the authenticated shell renders a login-only layout and account actions', () => {
  assert.match(appSource, /<RouterView v-if="isPublicPage" \/>/);
  assert.match(appSource, /@change-password="openPasswordDialog"/);
  assert.match(appSource, /@logout="handleLogout"/);
  assert.match(headerSource, /title="修改密码"/);
  assert.match(headerSource, /title="退出登录"/);
});
