import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const styles = readFileSync(new URL('../src/styles/main.css', import.meta.url), 'utf8');

test('token code blocks use theme-aware color-mix backgrounds and readable text', () => {
  assert.match(
    styles,
    /\.token-code\s*\{[^}]*background-color:\s*color-mix\(in srgb, rgb\(var\(--v-theme-primary\)\) 20%, transparent\)[^}]*color:\s*rgb\(var\(--v-theme-on-surface\)\)/s,
  );
  assert.match(
    styles,
    /\.token-code\s*\{[^}]*border:\s*1px solid color-mix\(in srgb, rgb\(var\(--v-theme-primary\)\) 35%, transparent\)/s,
  );
  assert.doesNotMatch(styles, /rgba\(var\(--v-theme-/);
});
