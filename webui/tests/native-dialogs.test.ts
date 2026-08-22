import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import {
  groupFormSnapshot,
  normalizeAdminIds,
  privateUserFormSnapshot,
} from '../src/utils/dialog-form.ts';
import type { GroupDetail, PrivateUserDetail } from '../src/services/api.ts';

const groupDialog = readFileSync(
  new URL('../src/components/GroupDetailDialog.vue', import.meta.url),
  'utf8',
);
const privateDialog = readFileSync(
  new URL('../src/components/PrivateUserDialog.vue', import.meta.url),
  'utf8',
);

const dialogs = [
  ['group detail dialog', groupDialog],
  ['private user dialog', privateDialog],
] as const;

test('dialog form helpers create pure reset snapshots and normalize admin IDs', () => {
  const group = {
    id: 7,
    name: 'Example group',
    status: 'active',
    enable: true,
    enable_chat: false,
    chat_mode: 'balanced',
    sanity_limit: 12,
    allow_r18g: true,
    allow_setu: false,
    admin_ids: [101, 202],
    message_count: 4,
    last_activity: null,
    recent_messages: [],
  } as GroupDetail;
  const user = {
    id: 9,
    nick_name: 'Example user',
    status: 'active',
    enable_chat: true,
    sanity_limit: 8,
    allow_r18g: false,
    message_count: 3,
    last_activity: null,
    recent_messages: [],
  } as PrivateUserDetail;

  const groupSnapshot = groupFormSnapshot(group);
  assert.deepEqual(groupSnapshot, {
    name: 'Example group',
    enable: true,
    enable_chat: false,
    chat_mode: 'balanced',
    sanity_limit: 12,
    allow_r18g: true,
    allow_setu: false,
    admin_ids: [101, 202],
  });
  groupSnapshot.admin_ids?.push(303);
  assert.deepEqual(group.admin_ids, [101, 202]);
  assert.deepEqual(groupFormSnapshot(null), {});

  assert.deepEqual(privateUserFormSnapshot(user), {
    nick_name: 'Example user',
    enable_chat: true,
    sanity_limit: 8,
    allow_r18g: false,
    status: 'active',
  });
  assert.deepEqual(privateUserFormSnapshot(null), {});

  assert.deepEqual(normalizeAdminIds([101, '202', 'invalid', 303]), [101, 202, 303]);
  assert.deepEqual(
    normalizeAdminIds(['12abc', '12.5', 12.5, Number.NaN, Number.POSITIVE_INFINITY, -7, '-8']),
    [],
  );
  assert.deepEqual(normalizeAdminIds([0, '0']), [0, 0]);
  assert.deepEqual(normalizeAdminIds(undefined), []);
});

test('dialogs use native Vuetify card sections and writable v-model bridges', () => {
  for (const [name, source] of dialogs) {
    assert.match(source, /<VDialog\s+v-model="dialogModel"/, name);
    assert.match(source, /<VCard\b/, name);
    assert.match(source, /<VCardTitle\b/, name);
    assert.match(source, /<VCardText\b/, name);
    assert.match(source, /<VCardActions\b/, name);
    assert.match(source, /const dialogModel = computed\(\{/, name);
    assert.match(source, /get: \(\) => props\.visible && Boolean\(props\.(?:group|user)\)/, name);
    assert.match(source, /set: \(value\) => emit\('update:visible', value\)/, name);
    assert.doesNotMatch(source, /:visible=|@update:visible=/, name);
  }
});

test('dialogs preserve declared and called parent-facing emits', () => {
  for (const [name, source] of dialogs) {
    assert.match(source, /const emit = defineEmits<\{[\s\S]*\(e: 'update:visible', value: boolean\): void;[\s\S]*\(e: 'submit', value:/, name);
    assert.match(source, /function close\(\) \{[\s\S]*emit\('update:visible', false\);[\s\S]*\}/, `${name} close wiring`);
    assert.match(source, /function save\(\) \{[\s\S]*emit\('submit',/, `${name} save wiring`);
    assert.match(source, /<VBtn[^>]*@click="close"[^>]*>取消<\/VBtn>/, `${name} cancel button`);
    assert.match(source, /<VBtn[^>]*@click="save"[^>]*>保存<\/VBtn>/, `${name} save button`);
  }
});

test('dialogs contain only native imports and timeline icon slots', () => {
  for (const [name, source] of dialogs) {
    assert.doesNotMatch(source, /from ['"]primevue\//, `${name} PrimeVue import`);
    assert.doesNotMatch(source, /(?:from ['"]@\/components\/ui|\bUi[A-Z][A-Za-z0-9_]*)/, `${name} compatibility import`);
    assert.match(source, /<VTimeline\b/, `${name} timeline`);
    assert.match(source, /<template #icon>/, `${name} timeline icon slot`);
    assert.match(source, /<VIcon\b/, `${name} native icon`);
    assert.doesNotMatch(source, /<i\b/, `${name} raw icon element`);
  }
});

test('dialogs use native Vuetify form controls and option props', () => {
  assert.match(groupDialog, /<VTextField\b/, 'group text field');
  assert.match(groupDialog, /<VNumberInput\b/, 'group number input');
  assert.match(groupDialog, /<VSelect\b/, 'group select');
  assert.match(groupDialog, /<VSwitch\b/, 'group switches');
  assert.match(groupDialog, /<VCombobox\b/, 'group admin IDs');
  assert.match(groupDialog, /:items="meta\?\.chat_modes \?\? \[\]"/, 'group select items');
  assert.match(groupDialog, /item-title="label"/, 'group select titles');
  assert.match(groupDialog, /item-value="value"/, 'group select values');
  assert.match(groupDialog, /:delimiters="\[','\]"/, 'group combobox delimiters');

  assert.match(privateDialog, /<VTextField\b/, 'private text field');
  assert.match(privateDialog, /<VNumberInput\b/, 'private number input');
  assert.match(privateDialog, /<VSelect\b/, 'private select');
  assert.match(privateDialog, /<VSwitch\b/, 'private switches');
  assert.match(privateDialog, /:items="meta\?\.statuses \?\? \[\]"/, 'private select items');
  assert.match(privateDialog, /@update:modelValue=/, 'native update event');

  for (const [name, source] of dialogs) {
    assert.doesNotMatch(source, /@change\b/, name);
    assert.doesNotMatch(source, /\b(?:severity|separator|useGrouping|modal|header|label|outlined|text)=/, name);
    assert.doesNotMatch(source, /#(?:content|footer)\b/, name);
  }
});

test('dialogs use native colors, variants, and button slots without compatibility imports', () => {
  for (const [name, source] of dialogs) {
    assert.doesNotMatch(source, /@\/components\/ui|from ['"]vuetify\/components['"]/, name);
    assert.match(source, /color="info"/, `${name} info color`);
    assert.match(source, /color="warning"/, `${name} warning color`);
    assert.match(source, /variant="outlined"/, `${name} outlined variant`);
    assert.match(source, /<VBtn[^>]*>\s*(?:取消|保存)/, `${name} button default slots`);
  }
});

test('group status formerly using help severity uses native info color', () => {
  assert.match(
    groupDialog,
    /<VChip[^>]*color="info"[^>]*>\s*状态 \{\{ group\.status \}\}<\/VChip>/,
  );
  assert.doesNotMatch(groupDialog, /severity="help"/);
});

test('dialogs repopulate forms when visible changes or the entity changes', () => {
  assert.match(groupDialog, /function syncForm\(group: GroupDetail \| null\)/, 'group reset helper');
  assert.match(
    groupDialog,
    /watch\(\s*\[\s*\(\) => props\.group,\s*\(\) => props\.visible\s*\],/s,
    'group visible-driven watcher',
  );
  assert.match(groupDialog, /\(\[group\]\) => syncForm\(group\)/, 'group watcher callback');

  assert.match(privateDialog, /function syncForm\(user: PrivateUserDetail \| null\)/, 'private reset helper');
  assert.match(
    privateDialog,
    /watch\(\s*\[\s*\(\) => props\.user,\s*\(\) => props\.visible\s*\],/s,
    'private visible-driven watcher',
  );
  assert.match(privateDialog, /\(\[user\]\) => syncForm\(user\)/, 'private watcher callback');
});

test('dialogs expose accessible names for every standalone form control', () => {
  const controls = [
    ['group-name', '群名称', 'VTextField'],
    ['group-chat-mode', '聊天模式', 'VSelect'],
    ['group-enable', '群启用', 'VSwitch'],
    ['group-enable-chat', '允许聊天', 'VSwitch'],
    ['group-allow-setu', '允许涩图', 'VSwitch'],
    ['group-allow-r18g', '允许 R18G', 'VSwitch'],
    ['group-sanity-limit', '理智值上限', 'VNumberInput'],
    ['group-admin-ids', '管理员 ID 列表', 'VCombobox'],
  ] as const;

  for (const [id, label, component] of controls) {
    assert.match(groupDialog, new RegExp(`<label[^>]*\\bfor="${id}"[^>]*>[^<]*${label}`), `group label ${id}`);
    assert.match(groupDialog, new RegExp(`<${component}[^>]*\\bid="${id}"`), `group control ${id}`);
  }

  const privateControls = [
    ['private-nick-name', '昵称', 'VTextField'],
    ['private-status', '状态', 'VSelect'],
    ['private-enable-chat', '允许聊天', 'VSwitch'],
    ['private-allow-r18g', '允许 R18G', 'VSwitch'],
    ['private-sanity-limit', '理智值上限', 'VNumberInput'],
  ] as const;

  for (const [id, label, component] of privateControls) {
    assert.match(privateDialog, new RegExp(`<label[^>]*\\bfor="${id}"[^>]*>[^<]*${label}`), `private label ${id}`);
    assert.match(privateDialog, new RegExp(`<${component}[^>]*\\bid="${id}"`), `private control ${id}`);
  }
});

test('dialogs label their cards and preserve normalized submit payloads', () => {
  assert.match(groupDialog, /<VDialog[^>]*aria-labelledby="group-dialog-title"/);
  assert.match(groupDialog, /<VCardTitle id="group-dialog-title">群组详情<\/VCardTitle>/);
  assert.match(privateDialog, /<VDialog[^>]*aria-labelledby="private-dialog-title"/);
  assert.match(privateDialog, /<VCardTitle id="private-dialog-title">私聊用户详情<\/VCardTitle>/);

  assert.match(
    groupDialog,
    /const adminIds = normalizeAdminIds\(form\.admin_ids\);[\s\S]*emit\('submit', \{ \.\.\.form, admin_ids: adminIds \}\)/,
    'group payload normalization and submit',
  );
  assert.match(privateDialog, /function save\(\) \{[\s\S]*emit\('submit', \{ \.\.\.form \}\);/, 'private submit payload');
});
