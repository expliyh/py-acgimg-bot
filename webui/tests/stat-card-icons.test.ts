import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const statCardSource = readFileSync(
  new URL('../src/components/StatCard.vue', import.meta.url),
  'utf8',
);

test('StatCard renders icons through native VIcon props', () => {
  assert.match(statCardSource, /<v-icon\b/);
  assert.match(statCardSource, /:icon="icon"/);
  assert.doesNotMatch(statCardSource, /class=.*\bmdi\b/);
  assert.doesNotMatch(statCardSource, /<i\b/);
});
