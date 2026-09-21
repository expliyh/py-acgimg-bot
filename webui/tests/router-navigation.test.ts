import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const source = readFileSync(new URL('../src/router/index.ts', import.meta.url), 'utf8');

test('route chunk failures recover to the requested destination', () => {
  assert.match(source, /router\.onError\(\(error, to\) =>/);
  assert.match(source, /isDynamicImportError\(error\)/);
  assert.match(source, /window\.location\.assign\(router\.resolve\(to\)\.href\)/);
  assert.match(source, /recoveringFromChunkError/);
});
