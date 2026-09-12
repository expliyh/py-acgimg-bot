import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const groups = readFileSync(new URL('../src/views/GroupsView.vue', import.meta.url), 'utf8');
const guard = readFileSync(new URL('../src/views/GuardView.vue', import.meta.url), 'utf8');
const router = readFileSync(new URL('../src/router/index.ts', import.meta.url), 'utf8');
const app = readFileSync(new URL('../src/App.vue', import.meta.url), 'utf8');

test('group management is the canonical unified workspace', () => {
  assert.match(groups, /listAllGroups\(\)/);
  assert.match(groups, /当前链接群组/);
  assert.match(groups, /groupsWithDeepLink/);
  assert.match(groups, /name: "group-management"/);
  assert.match(groups, /<VTab value="overview">概览<\/VTab>/);
  assert.match(groups, /<VTab value="base">基础配置<\/VTab>/);
  assert.match(groups, /<VTab value="guard">智能群管<\/VTab>/);
  assert.match(groups, /<VTab value="directory">群成员<\/VTab>/);
  assert.match(groups, /<VTab value="audit">审核与日志<\/VTab>/);
  assert.match(groups, /section="overview"/);
  assert.match(groups, /group-list-col--mobile-hidden/);
  assert.match(router, /path: '\/groups\/:id'[\s\S]*name: 'group-management'/);
  assert.match(router, /path: '\/groups\/:id\/guard'[\s\S]*redirect:/);
  assert.match(router, /path: '\/guard', redirect: \{ name: 'groups' \}/);
  assert.doesNotMatch(app, /label: '智能群管'/);
});

test('member workspace identifies observed coverage and uses guarded actions', () => {
  assert.match(guard, /guardApi\.members\(id,/);
  assert.match(guard, /<VDataTableServer[\s\S]*item-value="user_id"/);
  assert.match(guard, /<VMenu>[\s\S]*成员操作/);
  assert.match(guard, /消息级高级操作/);
  assert.doesNotMatch(guard, /查看成员状态/);
  assert.match(guard, /机器人已观测记录/);
  assert.match(guard, /state: "warned" \| "restricted" \| "exempt"/);
  assert.match(guard, /confirm\.require\(/);
  assert.match(guard, /next === "kick" \|\| next === "ban"/);
  assert.match(guard, /shouldRetainActionRequest\(actionResult\.value\.status\)/);
});
