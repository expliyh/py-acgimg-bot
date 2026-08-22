import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const pixivSource = readFileSync(new URL('../src/views/PixivTokensView.vue', import.meta.url), 'utf8');
const botTokenSource = readFileSync(new URL('../src/views/BotTokensView.vue', import.meta.url), 'utf8');
const styles = readFileSync(new URL('../src/styles/main.css', import.meta.url), 'utf8');

test('native switches use primary color and compact density where table controls need it', () => {
  assert.match(pixivSource, /<VSwitch\b[\s\S]*?color="primary"[\s\S]*?hide-details[\s\S]*?density="compact"/);
  assert.match(botTokenSource, /<VSwitch\b[^>]*color="primary"[^>]*hide-details[^>]*density="compact"/);
  assert.doesNotMatch(pixivSource, /<UiInputSwitch\b|<InputSwitch\b/);
});

test('switch styling relies on Vuetify props rather than flat-thumb overrides', () => {
  assert.doesNotMatch(styles, /\.v-switch--flat\s+\.v-switch__thumb/);
  assert.doesNotMatch(styles, /thumb-color|thumbColor/);
});
