import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const source = readFileSync(
  new URL('../src/views/GuardView.vue', import.meta.url),
  'utf8',
);
const apiSource = readFileSync(
  new URL('../src/services/api.ts', import.meta.url),
  'utf8',
);

test('smart guard selects known groups and routes immediately', () => {
  assert.match(source, /<VAutocomplete\b/);
  assert.match(source, /listAllGroups\(\)/);
  assert.match(source, /router\.push\(\{ name: "group-guard"/);
  assert.match(source, /id="guard-group-select"/);
  assert.match(source, /按名称或群 ID 搜索/);
  assert.doesNotMatch(source, /v-model\.number="inputGroupId"/);
  assert.doesNotMatch(source, /加载群组/);
});

test('known group API helper requests all pages in ascending ID order', () => {
  assert.match(apiSource, /export async function listAllGroups\(pageSize = 100\)/);
  assert.match(apiSource, /listGroups\(\{[\s\S]*page,[\s\S]*page_size: size,[\s\S]*sort_by: 'id',[\s\S]*sort_order: 'asc'/);
  assert.match(apiSource, /return collectAllPages\(/);
});

test('guard view keeps URL deep links loadable even when not in options', () => {
  assert.match(source, /当前链接群组/);
  assert.match(source, /if \(parsed\) void load\(\)/);
  assert.match(source, /selectedGroupId\.value = parsed \|\| null/);
});
