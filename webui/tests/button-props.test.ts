import assert from 'node:assert/strict';
import { existsSync, readdirSync, readFileSync } from 'node:fs';
import test from 'node:test';

function sourceFiles(directory: URL): URL[] {
  const files: URL[] = [];
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    const child = new URL(`${entry.name}${entry.isDirectory() ? '/' : ''}`, directory);
    if (entry.isDirectory()) files.push(...sourceFiles(child));
    else if (/\.(?:vue|ts|js)$/.test(entry.name)) files.push(child);
  }
  return files;
}

const files = sourceFiles(new URL('../src/', import.meta.url));
const sources = files.map((file) => [file.pathname, readFileSync(file, 'utf8')] as const);
const allSource = sources.map(([, content]) => content).join('\n');

test('WebUI has no compatibility layer or legacy component contracts', () => {
  for (const path of [
    '../src/components/ui.ts',
    '../src/components/ui.js',
    '../src/components/button-props.ts',
    '../src/components/button-props.js',
    '../src/composables/feedback.js',
    '../src/services/api.js',
    '../src/router/index.js',
    '../src/main.js',
  ]) {
    assert.equal(existsSync(new URL(path, import.meta.url)), false, path);
  }

  for (const [name, source] of sources) {
    assert.doesNotMatch(source, /@\/components\/ui/, name);
    assert.doesNotMatch(source, /from ['"]vuetify\/components['"]/, name);
    assert.doesNotMatch(source, /from ['"]primevue\//, name);
    assert.doesNotMatch(source, /<(?:Ui[A-Z][A-Za-z0-9_]*|Button|Tag|Input(?:Text|Number|Switch)?|Dropdown|Chips|Dialog|DataTable|Column)\b/, name);
    assert.doesNotMatch(source, /<i\b[^>]*\bmdi\b/i, name);
    if (name.endsWith('.vue')) {
      assert.doesNotMatch(source, /\bseverity\s*=/, name);
      assert.doesNotMatch(source, /\b(?:useGrouping|data-key)\s*=/, name);
      assert.doesNotMatch(source, /<(?:VChip|v-chip)\b[^>]*\bvalue\s*=/s, name);
      assert.doesNotMatch(source, /<(?:Ui[A-Z][A-Za-z0-9_]*|Button|Tag|Input[A-Za-z0-9_]*|Dropdown|Chips|Dialog|DataTable|Column)\b[^>]*\b(?:label|outlined|text|value|severity)\s*=/s, name);
    }
  }

  assert.doesNotMatch(allSource, /<(?:VCard|v-card)(?![-A-Za-z0-9_])[^>]*\b(?:outlined|text)\b/);
  assert.doesNotMatch(allSource, /<(?:VBtn|v-btn)[^>]*\b(?:outlined|text)\s*=/);
});

test('shared UI uses native Vuetify components', () => {
  assert.match(allSource, /<(?:VCard|v-card)\b/);
  assert.match(allSource, /<(?:VSwitch|v-switch)\b/);
  assert.match(allSource, /<(?:VBtn|v-btn)\b/);
  assert.match(allSource, /<VDataTable(?:Server)?\b/);
  assert.doesNotMatch(allSource, /\bUi(?:Card|InputSwitch|Button|DataTable)\b/);
});

test('icon-only native buttons are labelled and icons use the icon prop', () => {
  const buttonTags = allSource.match(/<(?:VBtn|v-btn)\b[\s\S]*?(?:\/>|>)/g) ?? [];
  assert.ok(buttonTags.length > 0);

  for (const tag of buttonTags) {
    if (/(?:^|\s):?icon\s*=/.test(tag)) {
      assert.match(tag, /(?:^|\s):?aria-label\s*=/, tag);
    }
    assert.doesNotMatch(tag, /(?:^|\s)(?:label|outlined|text)\s*=/, tag);
  }

  const iconTags = allSource.match(/<(?:VIcon|v-icon)\b[\s\S]*?(?:\/>|>)/g) ?? [];
  assert.ok(iconTags.length > 0);
  for (const tag of iconTags) {
    assert.match(tag, /(?:^|\s):?icon\s*=/, tag);
  }
});
