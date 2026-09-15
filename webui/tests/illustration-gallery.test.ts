import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const api = readFileSync(new URL('../src/services/api.ts', import.meta.url), 'utf8');
const view = readFileSync(new URL('../src/views/IllustrationGalleryView.vue', import.meta.url), 'utf8');
const router = readFileSync(new URL('../src/router/index.ts', import.meta.url), 'utf8');
const app = readFileSync(new URL('../src/App.vue', import.meta.url), 'utf8');

test('gallery API covers queries, encoded IDs, bulk bodies, refresh, and media URLs', () => {
  assert.match(api, /client\.get<IllustrationListResponse>\('\/illustrations', \{ params \}\)/);
  assert.match(api, /`\/illustrations\/\$\{encodeURIComponent\(id\)\}`/);
  assert.match(api, /client\.patch<IllustrationDetail>/);
  assert.match(api, /client\.delete<IllustrationDeleteResponse>/);
  assert.match(api, /'\/illustrations\/bulk\/update'/);
  assert.match(api, /'\/illustrations\/bulk\/delete', \{ ids \}/);
  assert.match(api, /'\/illustrations\/bulk\/refresh'/);
  assert.match(api, /`\/illustrations\/\$\{encodeURIComponent\(id\)\}\/refresh`/);
  assert.match(api, /`\/api\/illustrations\/\$\{encodeURIComponent\(id\)\}\/pages\/\$\{page\}\/media`/);
});

test('gallery navigation and current-page management controls are present', () => {
  assert.match(router, /path: '\/illustrations'[\s\S]*IllustrationGalleryView\.vue/);
  assert.match(app, /label: '图片图库'[\s\S]*to: '\/illustrations'/);
  assert.match(view, /const pageSize = ref\(24\)/);
  assert.match(view, /function clearSelection\(\)/);
  assert.match(view, /bulkApply/);
  assert.match(view, /批量刷新 Pixiv/);
  assert.match(view, /Telegram 文件 ID 无法由 Bot API 撤销/);
  assert.match(view, /loading="lazy"/);
  assert.match(view, /getIllustrationTask/);
});

test('bulk patch includes only fields whose apply switch is enabled', () => {
  for (const field of ['title', 'author_name', 'author_url', 'source_url', 'caption', 'tags', 'sanity_level', 'x_restrict', 'r18g', 'is_ai']) {
    assert.match(view, new RegExp(`if \\(bulkApply\\.${field}\\) patch\\.${field} =`));
  }
  assert.match(view, /if \(!Object\.keys\(patch\)\.length\)/);
  assert.match(view, /selectedItems\.value\.every\(\(item\) => item\.source_type === 'pixiv'\)/);
});
