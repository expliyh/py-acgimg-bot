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

test('Vue templates use Vuetify layout utilities without PrimeFlex or UI aliases', () => {
  const styles = readFileSync(new URL('../src/styles/main.css', import.meta.url), 'utf8');
  assert.doesNotMatch(styles, /\.flex\s*\{/);
  assert.doesNotMatch(styles, /\.gap-[1-4]\s*\{/);
  assert.doesNotMatch(styles, /\.(?:grid|col-\d+|field|border-round(?:-(?:lg|xl))?|text-color-secondary|surface-card)\s*\{/);

  const legacyUtility = /(?:^|\s)(?:flex|gap-[1-4]|align-items-(?:start|center|end|baseline|stretch)|justify-content-(?:start|center|end|between|around|evenly)|grid|formgrid|p-fluid|field|col-\d+|(?:sm|md|lg|xl):(?:col-\d+|w-[^\s"]+)|p-inputtext|p-input-icon-left|w-full|h-full|[wh]-\d+rem|border-(?:circle|round(?:-(?:lg|xl))?)|shadow-[12]|font-(?:medium|semibold|bold)|text-(?:sm|base|lg|xl|2xl|3xl)|m-0|bg-primary-(?:50|100)|text-red-500|block)(?=\s|")/;
  for (const file of vueFiles(new URL('../src/', import.meta.url))) {
    const source = readFileSync(file, 'utf8');
    assert.doesNotMatch(source, legacyUtility, file.pathname);
    assert.doesNotMatch(source, /@\/components\/ui|<Ui[A-Z]|<Button\b|<Tag\b/, file.pathname);
  }
});
