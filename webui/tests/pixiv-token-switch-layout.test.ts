import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const pixivTokensView = readFileSync(
  new URL('../src/views/PixivTokensView.vue', import.meta.url),
  'utf8',
);

test('Pixiv token enabled switches are compact and left-aligned in native table cells', () => {
  assert.match(
    pixivTokensView,
    /<template #item\.enabled="\{ item \}">\s*<div class="d-flex align-center justify-start w-100">\s*<VSwitch\s+:model-value="item\.enabled"\s+color="primary"\s+hide-details\s+density="compact"/s,
  );
});

test('Pixiv token status, enabled, and action cells share left-aligned content', () => {
  assert.match(
    pixivTokensView,
    /<template #item\.status="\{ item \}">[\s\S]*?<div class="d-flex align-center justify-start w-100">\s*<VChip\b/s,
  );
  assert.match(
    pixivTokensView,
    /<template #item\.actions="\{ item \}">[\s\S]*?<div class="d-flex align-center justify-start w-100 ga-1">\s*<VBtn\b/s,
  );
  assert.match(pixivTokensView, /<VBtn\b[^>]*aria-label="修改"/);
  assert.match(pixivTokensView, /<VBtn\b[^>]*aria-label="删除"/);
});

test('Refresh Token content uses Vuetify vertical alignment and accessible icon buttons', () => {
  assert.match(
    pixivTokensView,
    /<template #item\.token="\{ item \}">\s*<div class="d-flex align-center ga-2">/s,
  );
  assert.match(pixivTokensView, /<VBtn\b[\s\S]*?:aria-label="showFull\[item\.id\]/);
  assert.doesNotMatch(pixivTokensView, /<Column\b|<InputSwitch\b|<Tag\b/);
});
