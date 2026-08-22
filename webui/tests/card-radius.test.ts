import assert from 'node:assert/strict';
import { readdirSync, readFileSync } from 'node:fs';
import test from 'node:test';

function vueFiles(directory: URL): URL[] {
  const files: URL[] = [];
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    const child = new URL(`${entry.name}${entry.isDirectory() ? '/' : ''}`, directory);
    if (entry.isDirectory()) files.push(...vueFiles(child));
    else if (entry.name.endsWith('.vue')) files.push(child);
  }
  return files;
}

test('native cards use the shared large radius without compatibility adapters', () => {
  const statCardSource = readFileSync(new URL('../src/components/StatCard.vue', import.meta.url), 'utf8');
  const allVue = vueFiles(new URL('../src/', import.meta.url))
    .map((file) => readFileSync(file, 'utf8'))
    .join('\n');

  assert.match(statCardSource, /<v-card\b[^>]*\brounded-lg\b/);
  assert.doesNotMatch(allVue, /rounded-xl/);
  assert.doesNotMatch(allVue, /<UiCard\b/);
});
