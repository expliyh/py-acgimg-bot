import assert from 'node:assert/strict';
import { afterEach, test } from 'node:test';
import axios, { AxiosError, type InternalAxiosRequestConfig } from 'axios';
import type { AIConfig, GuardActionRequest, GuardContent, GuardRule } from '../src/services/guard-api.ts';

// Exercise the real API client and Axios serialization, with no HTTP requests.
const requests: InternalAxiosRequestConfig[] = [];
let response: unknown = {};
let failure: Error | undefined;
const originalAdapter = axios.defaults.adapter;
axios.defaults.adapter = async (config) => {
  requests.push(config);
  if (failure) throw failure;
  return { data: response, status: 200, statusText: 'OK', headers: {}, config };
};
const { guardApi } = await import('../src/services/guard-api.ts');
axios.defaults.adapter = originalAdapter;

afterEach(() => {
  requests.length = 0;
  response = {};
  failure = undefined;
});

const group = -1001234567890;
const root = `/groups/${group}/guard`;

test('policy saves only changed fields to the selected group', async () => {
  response = { flood_enabled: true, verification_enabled: false };
  assert.equal(await guardApi.savePolicy(group, { flood_enabled: true }), response);
  assert.equal(requests[0].baseURL, '/api');
  assert.equal(requests[0].timeout, 30000);
  assert.equal(requests[0].method, 'patch');
  assert.equal(requests[0].url, root);
  assert.deepEqual(JSON.parse(requests[0].data), { flood_enabled: true });
  await guardApi.policy(group + 1);
  assert.equal(requests[1].url, `/groups/${group + 1}/guard`);
});

test('rule and content names are encoded as a single URL parameter', async () => {
  const name = '广告 #1? enabled=true';
  const rule: GuardRule = { kind: 'keyword', pattern: 'spam', action: 'delete_warn', enabled: true, case_sensitive: false };
  await guardApi.saveRule(group, name, rule);
  await guardApi.deleteRule(group, name);
  await guardApi.deleteContent(group, 'note', name);
  assert.equal(requests[0].url, `${root}/rules/${encodeURIComponent(name)}`);
  assert.equal(requests[1].url, requests[0].url);
  assert.equal(requests[2].url, `${root}/contents/note/${encodeURIComponent(name)}`);
  assert.deepEqual(JSON.parse(requests[0].data), rule);
});

test('punishment retries preserve the caller idempotency key and actual result', async () => {
  const action: GuardActionRequest = { action: 'mute', user_id: 1234567890123, duration: 3600, reason: 'spam', request_id: 'same-operation' };
  response = { id: 'event', action: 'mute', status: 'uncertain', reason: 'spam', data: { error: 'TimedOut' } };
  assert.equal(await guardApi.action(group, action), response);
  assert.equal(await guardApi.action(group, action), response);
  assert.equal(requests.length, 2);
  for (const request of requests) {
    assert.equal(request.url, `${root}/actions`);
    assert.deepEqual(JSON.parse(request.data), action);
  }
});

test('timeouts propagate without automatically repeating a punishment', async () => {
  failure = new AxiosError('timeout', 'ECONNABORTED');
  await assert.rejects(guardApi.action(group, { action: 'warn', user_id: 2, reason: 'spam', request_id: 'retry-me' }), (error) => error === failure);
  assert.equal(requests.length, 1);
});

test('pagination and filters remain query parameters on the current group', async () => {
  response = { items: [], total: 0, page: 3, page_size: 20, pages: 0 };
  assert.equal(await guardApi.logs(group, 3, 'failed'), response);
  await guardApi.logs(group, 1, '');
  await guardApi.reviews(group, 2);
  await guardApi.tasks(group);
  assert.deepEqual(requests.map((request) => [request.url, request.params]), [
    [`${root}/logs`, { page: 3, status: 'failed' }],
    [`${root}/logs`, { page: 1, status: undefined }],
    [`${root}/reviews`, { page: 2 }],
    [`${root}/tasks`, { page: 1 }],
  ]);
});

test('review decisions and disabling an exemption use their intended contract', async () => {
  response = { id: 'review-id', data: { state: 'resolved' } };
  assert.equal(await guardApi.decide(group, 'review-id', 'reject_join'), response);
  await guardApi.exempt(group, 2, false);
  assert.equal(requests[0].url, `${root}/reviews/review-id`);
  assert.deepEqual(JSON.parse(requests[0].data), { decision: 'reject_join' });
  assert.equal(requests[1].url, `${root}/members/2/exempt`);
  assert.deepEqual(requests[1].params, { enabled: false });
});

test('model secret preservation and clearing remain distinguishable on the wire', async () => {
  const config: AIConfig = { base_url: 'https://model.example/v1', text_model: 'text', vision_model: 'vision', timeout: 20, concurrency: 2 };
  await guardApi.saveAI(config);
  await guardApi.saveAI({ ...config, api_key: null });
  await guardApi.saveAI({ ...config, api_key: '' });
  assert.equal('api_key' in JSON.parse(requests[0].data), false);
  assert.equal(JSON.parse(requests[1].data).api_key, null);
  assert.equal(JSON.parse(requests[2].data).api_key, '');
  assert.ok(requests.every((request) => request.url === '/guard-ai'));
});

test('announcement saves preserve the explicit offset and recurrence timezone', async () => {
  const content: GuardContent = { kind: 'announcement', name: 'morning', text: 'Hello', enabled: true, due_at: '2026-09-08T09:00:00+08:00', repeat: 'daily', timezone: 'Asia/Shanghai' };
  await guardApi.saveContent(group, content);
  assert.equal(requests[0].url, `${root}/contents`);
  assert.deepEqual(JSON.parse(requests[0].data), content);
});
