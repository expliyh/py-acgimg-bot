import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import {
  changedGuardPolicy,
  cloneGuardPolicy,
} from '../src/utils/guard-policy.ts';

test('policy changes include only fields edited since load', () => {
  const baseline = {
    flood_enabled: false,
    verification_timeout: 60,
    domain_allowlist: ['example.com'],
  };
  const current = cloneGuardPolicy(baseline);
  current.flood_enabled = true;

  assert.deepEqual(changedGuardPolicy(current, baseline), {
    flood_enabled: true,
  });
});

test('policy snapshots do not share mutable arrays', () => {
  const policy = { domain_allowlist: ['example.com'] };
  const snapshot = cloneGuardPolicy(policy);
  policy.domain_allowlist.push('new.example');

  assert.deepEqual(snapshot.domain_allowlist, ['example.com']);
});

test('nested AI selections are isolated and compared by value', () => {
  const policy = { ai_text: { provider_id: 'provider', model: 'text' }, ai_vision: null };
  const snapshot = cloneGuardPolicy(policy);
  assert.deepEqual(changedGuardPolicy(policy, snapshot), {});
  policy.ai_text.model = 'different';
  assert.equal(snapshot.ai_text.model, 'text');
  assert.deepEqual(changedGuardPolicy(policy, snapshot), { ai_text: { provider_id: 'provider', model: 'different' } });
});

test('guard view patches the diff against its loaded snapshot', () => {
  const source = readFileSync(
    new URL('../src/views/GuardView.vue', import.meta.url),
    'utf8',
  );

  assert.match(
    source,
    /guardApi\.savePolicy\(\s*groupId\.value,\s*changedGuardPolicy\(\s*policy\.value!,\s*policySnapshot\.value!,?\s*\),?\s*\)/s,
  );
});
