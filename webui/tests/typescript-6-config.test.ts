import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const packageJson = JSON.parse(
  readFileSync(new URL('../package.json', import.meta.url), 'utf8'),
) as { scripts: Record<string, string> };
const tsconfig = JSON.parse(
  readFileSync(new URL('../tsconfig.json', import.meta.url), 'utf8'),
) as { compilerOptions: Record<string, unknown> };
const nodeTsconfig = JSON.parse(
  readFileSync(new URL('../tsconfig.node.json', import.meta.url), 'utf8'),
) as { compilerOptions: Record<string, unknown> };

test('TypeScript 6 uses Vite-compatible module resolution without deprecated baseUrl', () => {
  assert.equal(tsconfig.compilerOptions.moduleResolution, 'Bundler');
  assert.equal(tsconfig.compilerOptions.baseUrl, undefined);
  assert.equal(nodeTsconfig.compilerOptions.moduleResolution, 'Bundler');
  assert.match(packageJson.scripts.typecheck, /--skipLibCheck/);
});
