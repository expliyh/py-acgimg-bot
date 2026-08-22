import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { parseCommandHistoryUserId } from '../src/utils/command-history.ts';
import {
  createServerTableRequestGuard,
  toApiTableParams,
} from '../src/utils/table-options.ts';

const viewFiles = [
  'GroupsView.vue',
  'PrivateChatsView.vue',
  'CommandHistoryView.vue',
] as const;

const views = Object.fromEntries(
  viewFiles.map((file) => [
    file,
    readFileSync(new URL(`../src/views/${file}`, import.meta.url), 'utf8'),
  ]),
) as Record<(typeof viewFiles)[number], string>;

test('converts supported server-table sorting into API pagination parameters', () => {
  assert.deepEqual(
    toApiTableParams(
      { page: 2, itemsPerPage: 20, sortBy: [{ key: 'name', order: 'asc' }] },
      ['id', 'name'],
    ),
    { page: 2, page_size: 20, sort_by: 'name', sort_order: 'asc' },
  );
  assert.deepEqual(
    toApiTableParams(
      { page: 3, itemsPerPage: 50, sortBy: [{ key: 'id', order: 'desc' }] },
      ['id', 'name'],
    ),
    { page: 3, page_size: 50, sort_by: 'id', sort_order: 'desc' },
  );
});

test('omits unsupported, invalid, and absent server-table sorting', () => {
  const base = { page: 1, page_size: 10 };
  assert.deepEqual(
    toApiTableParams(
      { page: 1, itemsPerPage: 10, sortBy: [{ key: 'status', order: 'asc' }] },
      ['id', 'name'],
    ),
    base,
  );
  assert.deepEqual(
    toApiTableParams(
      { page: 1, itemsPerPage: 10, sortBy: [{ key: 'id', order: 'invalid' as never }] },
      ['id', 'name'],
    ),
    base,
  );
  assert.deepEqual(
    toApiTableParams({ page: 1, itemsPerPage: 10, sortBy: [] }, ['id', 'name']),
    base,
  );
});

test('server-table request guard handles concurrency and retry invalidation', () => {
  const guard = createServerTableRequestGuard();

  assert.equal(guard.shouldLoad('page-a'), true);
  const firstRequest = guard.begin('page-a');
  assert.equal(guard.shouldLoad('page-a'), false);

  const newerRequest = guard.begin('page-b');
  assert.equal(guard.isLatest(firstRequest), false);
  assert.equal(guard.isLatest(newerRequest), true);

  guard.invalidateFailed(firstRequest);
  assert.equal(guard.shouldLoad('page-b'), false);

  guard.invalidateFailed(newerRequest);
  assert.equal(guard.shouldLoad('page-b'), true);

  const retryRequest = guard.begin('page-b');
  assert.equal(guard.isLatest(retryRequest), true);
  assert.equal(guard.shouldLoad('page-b'), false);
  guard.invalidateFailed(retryRequest);
  assert.equal(guard.shouldLoad('page-b'), true);
});

test('server-table views use native Vuetify components and options wiring', () => {
  for (const [name, source] of Object.entries(views)) {
    assert.match(source, /<VDataTableServer\b/, name);
    assert.match(source, /:headers="headers"/, name);
    assert.match(source, /item-value="id"/, name);
    assert.match(source, /:items-length="pagination\.total"/, name);
    assert.match(source, /:items-per-page="pagination\.itemsPerPage"/, name);
    assert.match(source, /:page="pagination\.page"/, name);
    assert.match(source, /:loading="loading"/, name);
    assert.match(source, /@update:options="onTableOptions"/, name);
    assert.match(source, /#item\.[A-Za-z_]+/, name);
    assert.doesNotMatch(source, /@page\b|\bdataKey\b|\bdata-key\b/, name);
    assert.doesNotMatch(
      source,
      /from ['"]primevue\/|from ['"]@\/components\/ui|<Ui[A-Z]|\bUi[A-Z][A-Za-z0-9_]*/,
      name,
    );
    assert.match(source, /<VTextField\b/, `${name} text field`);
    assert.match(source, /<VSelect\b/, `${name} select`);
    assert.match(source, /<VBtn\b[^>]*>[^<]+<\/VBtn>/, `${name} button slot`);
    assert.match(source, /<VChip\b/, `${name} chip`);
    assert.match(source, /<VSkeletonLoader\b/, `${name} loading skeleton`);
    assert.match(source, /@update:modelValue=/, `${name} native select event`);
    assert.doesNotMatch(source, /\b(?:severity|optionLabel|optionValue|rowsPerPageOptions|totalRecords)=/, name);
  }
});

test('server-table pagination defaults and sortable-key whitelists remain explicit', () => {
  assert.match(views['GroupsView.vue'], /page: 1,\s*itemsPerPage: 10/);
  assert.match(views['GroupsView.vue'], /\[10, 20, 50\]/);
  assert.match(views['GroupsView.vue'], /\['id', 'name'\]/);

  assert.match(views['PrivateChatsView.vue'], /page: 1,\s*itemsPerPage: 10/);
  assert.match(views['PrivateChatsView.vue'], /\[10, 20, 50\]/);
  assert.match(views['PrivateChatsView.vue'], /\['id', 'nick_name'\]/);

  assert.match(views['CommandHistoryView.vue'], /page: 1,\s*itemsPerPage: 20/);
  assert.match(views['CommandHistoryView.vue'], /\[20, 50, 100\]/);
  assert.match(views['CommandHistoryView.vue'], /\['command', 'triggered_at'\]/);
});

test('server-table headers disable sorting for unsupported backend fields', () => {
  const nonSortableHeaders = {
    'GroupsView.vue': ['enable', 'enable_chat', 'message_count', 'last_activity', 'actions'],
    'PrivateChatsView.vue': ['enable_chat', 'status', 'message_count', 'last_activity', 'actions'],
    'CommandHistoryView.vue': ['arguments', 'user_id', 'chat_id', 'success', 'duration_ms', 'error_message'],
  } as const;

  for (const name of viewFiles) {
    for (const key of nonSortableHeaders[name]) {
      assert.match(views[name], new RegExp(`key: '${key}', sortable: false`), `${name} ${key}`);
    }
  }
});

test('legacy chip colors are mapped to native Vuetify colors', () => {
  const allViews = Object.values(views).join('\n');
  assert.match(allViews, /<VChip[^>]*:color="[^\"]*'error'/);
  assert.match(allViews, /<VChip[^>]*:color="[^\"]*'warning'/);
  assert.match(allViews, /color="info"/);
  assert.doesNotMatch(allViews, /severity=|color="danger"|color="warn"|color="help"/);
});

test('detail dialogs close only after their awaited update succeeds', () => {
  const updateHandlers = {
    'GroupsView.vue': 'updateGroup',
    'PrivateChatsView.vue': 'updatePrivateUser',
  } as const;

  for (const name of ['GroupsView.vue', 'PrivateChatsView.vue'] as const) {
    const updateFunction = updateHandlers[name];
    const handler = views[name].match(/async function handleUpdate[\s\S]*?\n}\r?\n\r?\nonMounted/)?.[0];
    assert.ok(handler, `${name} handler`);
    assert.match(
      handler,
      new RegExp(`try \\{[\\s\\S]*?const updated = await ${updateFunction}\\([\\s\\S]*?dialogVisible\\.value = false;[\\s\\S]*?\\} catch`),
      `${name} success close`,
    );
    assert.doesNotMatch(handler, /catch[\s\S]*dialogVisible\.value = false;/, `${name} failure close`);
  }
});

test('duplicate-request guards compare only native table options', () => {
  for (const name of viewFiles) {
    const source = views[name];
    assert.match(source, /let tableReady = false;/, name);
    assert.match(source, /if \(!tableReady\) return;/, name);
    assert.match(source, /const requestGuard = createServerTableRequestGuard\(\);/, name);
    assert.match(source, /const key = optionsKey\(options\);/, name);
    assert.match(source, /if \(!requestGuard\.shouldLoad\(key\)\) return;/, name);
    assert.doesNotMatch(source, /lastLoadedOptionsKey|requestSequence/, name);
    assert.match(
      source,
      /return JSON\.stringify\(\{\s*page: options\.page,\s*itemsPerPage: options\.itemsPerPage,\s*sortBy: options\.sortBy,?\s*\}\);/s,
      name,
    );
  }
});

test('groups and private users recover from metadata failures before loading rows', () => {
  const metadataViews = {
    'GroupsView.vue': 'loadGroups',
    'PrivateChatsView.vue': 'loadUsers',
  } as const;

  for (const name of ['GroupsView.vue', 'PrivateChatsView.vue'] as const) {
    const listFunction = metadataViews[name];
    assert.match(
      views[name],
      new RegExp(
        `onMounted\\(async \\(\\) => \\{[\\s\\S]*?try \\{[\\s\\S]*?await ensureMeta\\(\\);[\\s\\S]*?\\} catch \\(error\\)[\\s\\S]*?toast\\.add[\\s\\S]*?\\}[\\s\\S]*?tableReady = true;[\\s\\S]*?await ${listFunction}\\(pagination\\);`,
      ),
      name,
    );
  }
});

test('server-table loaders ignore stale responses and only latest requests clear loading', () => {
  for (const name of viewFiles) {
    const source = views[name];
    assert.match(source, /const requestId = requestGuard\.begin\(optionsKey\(options\)\);/, name);
    assert.match(source, /if \(!requestGuard\.isLatest\(requestId\)\) return;/, name);
    assert.match(source, /requestGuard\.invalidateFailed\(requestId\);/, name);
    assert.match(
      source,
      /finally \{[\s\S]*?if \(requestGuard\.isLatest\(requestId\)\) \{\s*loading\.value = false;\s*\}[\s\S]*?\}/,
      name,
    );
  }
});

test('native controls own their labels through stable IDs', () => {
  const controls = {
    'GroupsView.vue': [
      ['VTextField', 'groups-search', '搜索群 ID / 名称'],
      ['VSelect', 'groups-enable', '启用状态'],
      ['VSelect', 'groups-chat-enabled', '聊天功能'],
    ],
    'PrivateChatsView.vue': [
      ['VTextField', 'private-search', '搜索用户 ID / 昵称'],
      ['VSelect', 'private-chat-enabled', '聊天状态'],
      ['VSelect', 'private-status', '用户状态'],
    ],
    'CommandHistoryView.vue': [
      ['VTextField', 'command-history-command', '命令名称'],
      ['VTextField', 'command-history-user-id', '用户 ID'],
      ['VSelect', 'command-history-success', '执行状态'],
    ],
  } as const;

  for (const name of viewFiles) {
    const expectedControls = controls[name];
    assert.doesNotMatch(views[name], /<label\b/, `${name} orphan label`);
    for (const [component, id, label] of expectedControls) {
      assert.match(
        views[name],
        new RegExp(`<${component}[^>]*\\bid="${id}"[^>]*\\blabel="${label}"`),
        `${name} ${id}`,
      );
    }
  }
});

test('command-history user ID parser accepts only safe non-negative integers', () => {
  assert.equal(parseCommandHistoryUserId(''), undefined);
  assert.equal(parseCommandHistoryUserId('  '), undefined);
  assert.equal(parseCommandHistoryUserId('42'), 42);
  assert.equal(parseCommandHistoryUserId('0007'), 7);
  assert.equal(parseCommandHistoryUserId('1.5'), undefined);
  assert.equal(parseCommandHistoryUserId('Infinity'), undefined);
  assert.equal(parseCommandHistoryUserId('1e3'), undefined);
  assert.equal(parseCommandHistoryUserId('-1'), undefined);
  assert.equal(parseCommandHistoryUserId(String(Number.MAX_SAFE_INTEGER)), Number.MAX_SAFE_INTEGER);
  assert.equal(parseCommandHistoryUserId('9007199254740992'), undefined);
});
