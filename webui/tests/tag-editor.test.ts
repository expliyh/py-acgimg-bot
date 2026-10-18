import assert from 'node:assert/strict';
import test from 'node:test';

import {
  commitTagDraft,
  createTagEditorState,
  handleTagKey,
  moveTagGap,
  removeTag,
  selectTag,
  updateTagDraft,
} from '../src/utils/tag-editor.ts';

test('Backspace after a tag selects it before either deletion key removes it', () => {
  for (const secondKey of ['Backspace', 'Delete']) {
    const original = ['风景', '夜景'];
    const state = createTagEditorState(original);
    assert.equal(handleTagKey(state, 'Backspace', 0, 0), true);
    assert.equal(state.selected, 1);
    assert.deepEqual(state.tags, original);
    assert.equal(handleTagKey(state, secondKey, 0, 0), true);
    assert.deepEqual(state.tags, ['风景']);
    assert.deepEqual(original, ['风景', '夜景']);
    assert.equal(state.gap, 1);
    assert.equal(state.selected, null);
  }
});

test('Delete before any tag selects that tag and a second deletion key removes it', () => {
  for (const secondKey of ['Backspace', 'Delete']) {
    const state = createTagEditorState(['风景', '夜景', '星空']);
    moveTagGap(state, 1);
    assert.equal(handleTagKey(state, 'Delete', 0, 0), true);
    assert.equal(state.selected, 1);
    assert.equal(state.tags.length, 3);
    handleTagKey(state, secondKey, 0, 0);
    assert.deepEqual(state.tags, ['风景', '星空']);
    assert.equal(state.gap, 1);
  }
});

test('text deletion and text selections stay native except at a tag boundary', () => {
  const state = createTagEditorState(['风景', '夜景']);
  state.draft = '新标签';
  moveTagGap(state, 1);
  state.draft = '新内容';
  assert.equal(handleTagKey(state, 'Backspace', 2, 2), false);
  assert.equal(handleTagKey(state, 'Delete', 0, 0), false);
  assert.equal(handleTagKey(state, 'Backspace', 0, 2), false);
  assert.equal(handleTagKey(state, 'Delete', 1, 3), false);
  assert.equal(handleTagKey(state, 'Backspace', 0, 0), true);
  assert.equal(state.selected, 0);
  assert.equal(state.draft, '新内容');
});

test('holding a deletion key cannot delete the tag selected by the first keydown', () => {
  const state = createTagEditorState(['风景']);
  handleTagKey(state, 'Backspace', 0, 0);
  handleTagKey(state, 'Backspace', 0, 0, true);
  handleTagKey(state, 'Delete', 0, 0, true);
  assert.deepEqual(state.tags, ['风景']);
  assert.equal(state.selected, 0);
  handleTagKey(state, 'Delete', 0, 0);
  assert.deepEqual(state.tags, []);
  assert.equal(state.gap, 0);
});

test('Escape cancels selection and arrows move to either side of the selected tag', () => {
  const state = createTagEditorState(['风景', '夜景']);
  handleTagKey(state, 'Backspace', 0, 0);
  assert.equal(handleTagKey(state, 'Escape', 0, 0), true);
  assert.equal(state.selected, null);
  assert.equal(state.tags.length, 2);
  handleTagKey(state, 'Backspace', 0, 0);
  handleTagKey(state, 'ArrowLeft', 0, 0);
  assert.equal(state.gap, 1);
  handleTagKey(state, 'Delete', 0, 0);
  handleTagKey(state, 'ArrowRight', 0, 0);
  assert.equal(state.gap, 2);
  assert.equal(state.selected, null);
});

test('commas tokenize completed tags, preserve the draft, and ignore empty or duplicate tags', () => {
  const state = createTagEditorState(['风景']);
  updateTagDraft(state, ' 风景, 夜景，、星空\n 夜景\r\n 新草稿');
  assert.deepEqual(state.tags, ['风景', '夜景', '星空']);
  assert.equal(state.draft, ' 新草稿');
  assert.equal(state.gap, 3);
  commitTagDraft(state);
  assert.deepEqual(state.tags, ['风景', '夜景', '星空', '新草稿']);
  assert.equal(state.draft, '');
});

test('space and Enter commit tags and empty drafts never add a tag', () => {
  for (const key of [' ', 'Enter']) {
    const state = createTagEditorState([]);
    state.draft = ' 夜景 ';
    assert.equal(handleTagKey(state, key, state.draft.length, state.draft.length), true);
    assert.deepEqual(state.tags, ['夜景']);
    assert.equal(state.draft, '');
    handleTagKey(state, key, 0, 0);
    assert.deepEqual(state.tags, ['夜景']);
  }
});

test('pasted multiword tags preserve their spaces and insert at the chosen gap', () => {
  const state = createTagEditorState(['风景', '夜景']);
  moveTagGap(state, 1);
  state.draft = ' original character, 初音未来，original character\n night sky ';
  commitTagDraft(state);
  assert.deepEqual(state.tags, ['风景', 'original character', '初音未来', 'night sky', '夜景']);
  assert.equal(state.gap, 4);
});

test('moving or clicking a tag commits the draft without losing the intended position', () => {
  const state = createTagEditorState(['风景', '夜景']);
  moveTagGap(state, 0);
  state.draft = '星空';
  selectTag(state, 1);
  assert.deepEqual(state.tags, ['星空', '风景', '夜景']);
  assert.equal(state.selected, 2);
  removeTag(state, state.selected!);
  assert.deepEqual(state.tags, ['星空', '风景']);
  state.draft = '新标签';
  moveTagGap(state, 0);
  assert.deepEqual(state.tags, ['星空', '风景', '新标签']);
  assert.equal(state.gap, 0);
});

test('arrows, Home and End reach all tag gaps and stop at the outer boundaries', () => {
  const state = createTagEditorState(['风景', '夜景']);
  handleTagKey(state, 'Home', 0, 0);
  assert.equal(state.gap, 0);
  assert.equal(handleTagKey(state, 'Backspace', 0, 0), false);
  assert.equal(handleTagKey(state, 'ArrowLeft', 0, 0), false);
  handleTagKey(state, 'ArrowRight', 0, 0);
  assert.equal(state.gap, 1);
  handleTagKey(state, 'ArrowRight', 0, 0);
  assert.equal(state.gap, 2);
  assert.equal(handleTagKey(state, 'Delete', 0, 0), false);
  assert.equal(handleTagKey(state, 'ArrowRight', 0, 0), false);
  handleTagKey(state, 'Home', 0, 0);
  handleTagKey(state, 'End', 0, 0);
  assert.equal(state.gap, 2);
});
