import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import type { IllustrationImportTask } from '../src/services/api.ts';
import {
  createIllustrationTaskHeaders,
  createIllustrationTaskRowProps,
} from '../src/utils/illustration-task-table.ts';

const viewFiles = [
  'DashboardView.vue',
  'FeatureConfigView.vue',
  'BotTokensView.vue',
  'PixivTokensView.vue',
  'IllustrationImportView.vue',
] as const;

const views = Object.fromEntries(
  viewFiles.map((file) => [
    file,
    readFileSync(new URL(`../src/views/${file}`, import.meta.url), 'utf8'),
  ]),
) as Record<(typeof viewFiles)[number], string>;

test('task views use only native Vuetify imports and auto-imported templates', () => {
  for (const [name, source] of Object.entries(views)) {
    assert.doesNotMatch(source, /@\/components\/ui|from ['"]vuetify\/components['"]/, name);
    assert.doesNotMatch(source, /from ['"]primevue\//, name);
    assert.doesNotMatch(source, /<Ui[A-Z]|\bUi[A-Z][A-Za-z0-9_]*/, name);
  }
});

test('dashboard and feature pages use native cards, buttons, chips, skeletons, and dividers', () => {
  const source = `${views['DashboardView.vue']}\n${views['FeatureConfigView.vue']}`;

  for (const component of ['VCard', 'VBtn', 'VChip', 'VSkeletonLoader', 'VDivider']) {
    assert.match(source, new RegExp(`<${component}\\b`), component);
  }
  assert.match(source, /<VBtn[^>]*>刷新<\/VBtn>/, 'native refresh button slot');
  assert.match(source, /<VChip[^>]*color="info"[^>]*>可配置<\/VChip>/, 'info chip');
  assert.match(source, /<VChip[^>]*color="warning"[^>]*>规划中<\/VChip>/, 'warning chip');
  assert.doesNotMatch(source, /<(?:Button|Tag|Chip)\b[^>]*(?:severity|label|outlined|text|value)=/, 'legacy aliases');
});

test('Pixiv and illustration task lists use typed native VDataTable headers and item slots', () => {
  const pixiv = views['PixivTokensView.vue'];
  const illustration = views['IllustrationImportView.vue'];

  assert.match(pixiv, /const headers: DataTableHeader<PixivTokenItem>\[\] = \[/);
  assert.match(illustration, /const headers = computed<DataTableHeader<IllustrationImportTask>\[\]>\(\(\) => createIllustrationTaskHeaders\(tasks\.value\)\)/);

  for (const [name, source] of [
    ['PixivTokensView.vue', pixiv],
    ['IllustrationImportView.vue', illustration],
  ] as const) {
    assert.match(source, /<VDataTable\b/, name);
    assert.match(source, /:headers="headers"/, name);
    assert.match(source, /item-value="id"/, name);
    assert.match(source, /#item\.[A-Za-z_]+/, name);
    assert.match(source, /#no-data/, name);
    assert.match(source, /:loading="loading/, name);
    assert.doesNotMatch(source, /<DataTable(?!Header)|<Column|data-key=|#body\b|\{\s*data\s*\}/, name);
  }
});

test('local table pagination matches the token and import-task requirements', () => {
  const pixiv = views['PixivTokensView.vue'];
  const illustration = views['IllustrationImportView.vue'];

  assert.match(pixiv, /:items-per-page="10"/);
  assert.match(pixiv, /:hide-default-footer="items\.length <= 10"/);
  assert.match(illustration, /:items-per-page="10"/);
  assert.doesNotMatch(illustration, /hide-default-footer/);
});

test('illustration task row props select the native item and return a mouse click handler', () => {
  const source = views['IllustrationImportView.vue'];

  assert.match(source, /function taskRowProps\(\{ item \}: \{ item: IllustrationImportTask \}\)/);
  assert.match(source, /return createIllustrationTaskRowProps\(item, selectedTask\.value\?\.id \?\? null, selectTask\);/);
  assert.match(source, /:row-props="taskRowProps"/);
  assert.doesNotMatch(source, /\{\s*data:\s*IllustrationImportTask\s*\}/);
});

test('illustration task headers retain the conditional error column', () => {
  const task = { id: 4, error_message: '' } as IllustrationImportTask;
  const failedTask = { id: 5, error_message: 'download failed' } as IllustrationImportTask;

  assert.deepEqual(
    createIllustrationTaskHeaders([task]).map((header) => header.key),
    ['id', 'pixiv_id', 'title', 'status', 'progress', 'created_at'],
  );
  assert.deepEqual(
    createIllustrationTaskHeaders([task, failedTask]).map((header) => header.key),
    ['id', 'pixiv_id', 'title', 'status', 'progress', 'created_at', 'error_message'],
  );
});

test('illustration task row helper exposes selected class and native click callback', () => {
  const task = { id: 12 } as IllustrationImportTask;
  const otherTask = { id: 13 } as IllustrationImportTask;
  const selectedItems: IllustrationImportTask[] = [];
  const onSelect = (item: IllustrationImportTask) => selectedItems.push(item);

  const selected = createIllustrationTaskRowProps(task, 12, onSelect);
  const unselected = createIllustrationTaskRowProps(otherTask, 12, onSelect);

  assert.equal(selected.class, 'selected-task-row');
  assert.equal(unselected.class, '');
  selected.onClick({ type: 'click' } as MouseEvent);
  assert.deepEqual(selectedItems, [task]);
});

test('local table action cells stop propagation and preserve awaited success-only dialog close checks', () => {
  const pixiv = views['PixivTokensView.vue'];
  assert.match(pixiv, /#item\.actions/);
  assert.match(pixiv, /@click\.stop="openEdit\(item\)"/);
  assert.match(pixiv, /@click\.stop="onDelete\(item\)"/);

  for (const source of [views['BotTokensView.vue'], pixiv]) {
    const save = source.match(/async function save\([\s\S]*?\n}\r?\n\r?\n(?:async function|function|onMounted)/)?.[0];
    assert.ok(save);
    assert.match(save, /await [A-Za-z]+(?:PixivToken|BotToken)[\s\S]*dialogVisible\.value = false;/);
    assert.doesNotMatch(save, /catch[\s\S]*dialogVisible\.value = false;/);
  }
});

test('token and import forms use native controls, dialog cards, and update:modelValue events', () => {
  const source = [views['BotTokensView.vue'], views['PixivTokensView.vue'], views['IllustrationImportView.vue']].join('\n');

  for (const component of ['VDialog', 'VCardTitle', 'VCardText', 'VCardActions', 'VTextField', 'VSwitch', 'VNumberInput', 'VTextarea', 'VChip']) {
    assert.match(source, new RegExp(`<${component}\\b`), component);
  }
  assert.match(source, /const dialogModel = computed\(\{/);
  assert.match(source, /<VDialog\s+v-model="dialogModel"/);
  assert.match(source, /@update:modelValue=/);
  assert.match(source, /<VProgressLinear[^>]*:model-value="activeProgress"/);
  assert.doesNotMatch(source, /useGrouping|<(?:Button|Tag|Chip)\b[^>]*(?:severity|label|outlined|text|chip-value)=/);
});

test('native colors normalize danger, warn, and help aliases', () => {
  const source = Object.values(views).join('\n');

  assert.doesNotMatch(source, /(?:severity|color)=['"](?:danger|warn|help)['"]/);
  assert.doesNotMatch(source, /statusSeverity/);
  assert.match(source, /color="error"|:color="[^\n]*(?:error)/);
  assert.match(source, /color="warning"|:color="[^\n]*(?:warning)/);
  assert.match(source, /color="info"|:color="[^\n]*(?:info)/);
});

test('submit dialogs close only after awaited API success', () => {
  for (const [name, source] of Object.entries({
    'BotTokensView.vue': views['BotTokensView.vue'],
    'PixivTokensView.vue': views['PixivTokensView.vue'],
  })) {
    const save = source.match(/async function save\([\s\S]*?\n}\r?\n\r?\n(?:async function|function|onMounted)/)?.[0];
    assert.ok(save, `${name} save handler`);
    assert.match(save, /try \{[\s\S]*?await [A-Za-z]+(?:PixivToken|BotToken)[\s\S]*?dialogVisible\.value = false;[\s\S]*?\} catch/, name);
    assert.doesNotMatch(save, /catch[\s\S]*dialogVisible\.value = false;/, name);
  }
});
