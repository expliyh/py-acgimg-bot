import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import { shouldRetainActionRequest } from '../src/utils/guard-action.ts';

test('only ambiguous server results retain the punishment request ID', () => {
  assert.equal(shouldRetainActionRequest('uncertain'), true);
  assert.equal(shouldRetainActionRequest('failed'), false);
  assert.equal(shouldRetainActionRequest('partial'), false);
  assert.equal(shouldRetainActionRequest('success'), false);
});

test('guard action handling uses the ambiguity decision before throwing', () => {
  const source = readFileSync(
    new URL('../src/views/GuardView.vue', import.meta.url),
    'utf8',
  );
  assert.match(
    source,
    /if \(!shouldRetainActionRequest\(actionResult\.value\.status\)\)\s+pendingAction = null;/,
  );
});
