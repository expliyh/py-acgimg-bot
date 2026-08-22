import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

function source(path: string): string {
  return readFileSync(new URL(`../src/${path}`, import.meta.url), 'utf8');
}

const appSource = source('App.vue');
const headerSource = source('components/AppHeader.vue');
const sidebarSource = source('components/AppSidebar.vue');
const timelineSource = source('components/ActivityTimeline.vue');
const statCardSource = source('components/StatCard.vue');
const feedbackSource = source('composables/feedback.ts');
const stylesSource = source('styles/main.css');

test('shared components use native Vuetify cards, chips, timeline items, icons, and no UI adapter imports', () => {
  for (const [name, content] of Object.entries({
    'AppHeader.vue': headerSource,
    'AppSidebar.vue': sidebarSource,
    'ActivityTimeline.vue': timelineSource,
    'StatCard.vue': statCardSource
  })) {
    assert.doesNotMatch(content, /@\/components\/ui/, name);
    assert.doesNotMatch(content, /\bUi[A-Z][A-Za-z0-9_]*/, name);
    assert.doesNotMatch(content, /<i\b/, name);
  }

  assert.match(headerSource, /defineProps<\{\s*dark: boolean\s*\}>/);
  assert.doesNotMatch(headerSource, /items|activePath/);
  assert.match(headerSource, /<v-icon\b[^>]*icon="mdi-shield-star-outline"/);
  assert.match(headerSource, /<v-btn\b[^>]*icon="mdi-theme-light-dark"/);
  assert.match(timelineSource, /<v-timeline\b/);
  assert.match(timelineSource, /<v-timeline-item\b/);
  assert.match(timelineSource, /function activityKey\(entry: ActivityEntry\)/);
  assert.match(timelineSource, /:key="activityKey\(entry\)"/);
  assert.match(timelineSource, /#opposite/);
  assert.match(timelineSource, /#icon/);
  assert.match(timelineSource, /#default/);
  assert.match(timelineSource, /<v-icon\b[^>]*icon="mdi-flash"/);
  assert.match(timelineSource, /<v-card\b/);
  assert.match(timelineSource, /<v-card-title\b/);
  assert.match(timelineSource, /<v-card-text\b/);
  assert.match(timelineSource, /<v-chip\b[^>]*:color="[^"]*normalizeVuetifyColor/);
  assert.match(statCardSource, /<v-card\b/);
  assert.match(statCardSource, /<v-card-title\b/);
  assert.match(statCardSource, /<v-card-text\b/);
  assert.match(statCardSource, /<v-chip\b[^>]*:color="[^"]*normalizeVuetifyColor/);
  assert.match(statCardSource, /<v-icon\b[^>]*:icon="icon"/);
});

test('sidebar delegates route navigation to VListItem and App does not push a second route', () => {
  assert.match(sidebarSource, /<v-list-item[\s\S]*:to="item\.to"/);
  assert.match(sidebarSource, /@click="emit\('navigate'\)"/);
  assert.doesNotMatch(sidebarSource, /emit\('navigate',\s*item\.to/);
  assert.doesNotMatch(appSource, /\brouter\.push\s*\(/);
  assert.match(appSource, /@navigate="closeDrawer"/);
});

test('App starts open on desktop and closed on mobile while rendering an accessible confirmation dialog', () => {
  assert.match(appSource, /const drawer = ref<boolean \| null>\(null\)/);
  assert.match(appSource, /:permanent="mdAndUp"/);
  assert.match(appSource, /:temporary="!mdAndUp"/);
  assert.match(appSource, /const confirmationDialog = computed\(\{/);
  assert.match(appSource, /<v-dialog\b[^>]*v-model="confirmationDialog"/);
  assert.match(appSource, /<v-dialog\b[^>]*aria-labelledby="confirmation-title"[^>]*aria-describedby="confirmation-message"/);
  assert.match(appSource, /<v-card-title\b[^>]*id="confirmation-title"/);
  assert.match(appSource, /<v-card-text\b[^>]*id="confirmation-message"/);
  assert.match(appSource, /confirmState\.icon/);
  assert.match(appSource, /confirmState\.header/);
  assert.match(appSource, /confirmState\.header\s*\|\|\s*'确认操作'/);
  assert.match(appSource, /confirmState\.message/);
  assert.match(appSource, /confirmState\.acceptLabel/);
  assert.match(appSource, /confirmState\.rejectLabel/);
  assert.match(appSource, /@click:outside="rejectConfirmation"/);
  assert.match(appSource, /aria-label="关闭确认对话框"/);
  assert.match(appSource, /rejectConfirmation\(\)/);
  assert.match(appSource, /@click="acceptConfirmation"/);
});

test('navigation drawer button has a localized accessible label', () => {
  assert.match(headerSource, /<v-app-bar-nav-icon\b[^>]*aria-label="打开导航菜单"/);
});

test('feedback normalizes legacy colors before the root snackbar consumes them', () => {
  assert.match(feedbackSource, /export function normalizeVuetifyColor/);
  assert.match(feedbackSource, /danger.*error/s);
  assert.match(feedbackSource, /warn.*warning/s);
  assert.match(feedbackSource, /help.*info/s);
  assert.match(feedbackSource, /add\(payload:\s*\{\s*severity\?: string;/);
  assert.match(feedbackSource, /feedbackState\.severity\s*=\s*normalizeVuetifyColor\(payload\.severity/);
  assert.match(appSource, /<v-snackbar\b[^>]*:color="feedbackState\.severity"/);
});

test('feedback exposes reactive confirmation resolvers without blocking browser confirmation', async () => {
  assert.match(feedbackSource, /export const confirmState = reactive/);
  assert.match(feedbackSource, /export function acceptConfirmation/);
  assert.match(feedbackSource, /export function rejectConfirmation/);
  assert.match(feedbackSource, /export function closeConfirmation/);
  assert.match(feedbackSource, /confirmState\.open\s*=\s*true/);
  assert.match(feedbackSource, /close\(\)\s*\{[\s\S]*closeConfirmation\(\);/);
  assert.doesNotMatch(feedbackSource, /window\.confirm/);

  const feedback = await import('../src/composables/feedback.ts');
  assert.equal(typeof feedback.confirmState, 'object');
  assert.equal(typeof feedback.acceptConfirmation, 'function');
  assert.equal(typeof feedback.rejectConfirmation, 'function');
  assert.equal(typeof feedback.closeConfirmation, 'function');

  const events: string[] = [];
  const { confirm } = feedback.useFeedback();
  confirm.require({
    message: '确认继续？',
    header: '测试确认',
    acceptLabel: '继续',
    rejectLabel: '返回',
    accept: () => events.push('accept'),
    reject: () => events.push('reject')
  });
  assert.equal(feedback.confirmState.open, true);
  assert.equal(feedback.confirmState.header, '测试确认');
  feedback.acceptConfirmation();
  assert.deepEqual(events, ['accept']);
  assert.equal(feedback.confirmState.open, false);

  confirm.require({ message: '确认取消？', reject: () => events.push('reject') });
  assert.equal(feedback.confirmState.header, '确认操作');
  feedback.rejectConfirmation();
  assert.deepEqual(events, ['accept', 'reject']);
  assert.equal(feedback.confirmState.open, false);

  confirm.require({ message: '仅关闭', reject: () => events.push('unexpected-reject') });
  confirm.close();
  assert.deepEqual(events, ['accept', 'reject']);
  assert.equal(feedback.confirmState.open, false);
  assert.equal(feedback.confirmState.accept, undefined);
  assert.equal(feedback.confirmState.reject, undefined);

  confirm.require({
    message: '新对话框',
    accept: () => events.push('new-accept'),
    reject: () => events.push('new-reject')
  });
  feedback.rejectConfirmation();
  assert.deepEqual(events, ['accept', 'reject', 'new-reject']);
});

test('Vuetify theme CSS uses color-mix and does not force a color scheme or rgba theme variables', () => {
  assert.doesNotMatch(stylesSource, /color-scheme\s*:\s*light\s+dark/);
  assert.doesNotMatch(stylesSource, /rgba\(var\(--v-theme-/);
  assert.match(stylesSource, /color-mix\(in srgb, rgb\(var\(--v-theme-primary\)\) 20%, transparent\)/);
  assert.match(stylesSource, /color-mix\(in srgb, rgb\(var\(--v-theme-primary\)\) 35%, transparent\)/);
});
