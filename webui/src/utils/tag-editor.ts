export interface TagEditorState {
  tags: string[];
  draft: string;
  gap: number;
  selected: number | null;
}

const separators = /[,，、\r\n]+/;

export function createTagEditorState(tags: readonly string[]): TagEditorState {
  return { tags: [...tags], draft: '', gap: tags.length, selected: null };
}

function insertTags(state: TagEditorState, values: string[]) {
  const known = new Set(state.tags);
  const added = values.map((value) => value.trim()).filter((value) => {
    if (!value || known.has(value)) return false;
    known.add(value);
    return true;
  });
  state.tags.splice(state.gap, 0, ...added);
  state.gap += added.length;
  state.selected = null;
  return added.length;
}

export function commitTagDraft(state: TagEditorState): number {
  const added = insertTags(state, state.draft.split(separators));
  state.draft = '';
  return added;
}

export function updateTagDraft(state: TagEditorState, value: string) {
  const parts = value.split(separators);
  state.draft = parts.pop() ?? '';
  if (parts.length) insertTags(state, parts);
  state.selected = null;
}

export function moveTagGap(state: TagEditorState, gap: number) {
  const previousGap = state.gap;
  const added = commitTagDraft(state);
  state.gap = Math.max(0, Math.min(state.tags.length, gap + (gap >= previousGap ? added : 0)));
  state.selected = null;
}

export function selectTag(state: TagEditorState, index: number) {
  const previousGap = state.gap;
  const added = commitTagDraft(state);
  const adjusted = index + (index >= previousGap ? added : 0);
  state.selected = adjusted;
  state.gap = adjusted + 1;
}

export function removeTag(state: TagEditorState, index: number) {
  state.tags.splice(index, 1);
  if (state.gap > index) state.gap -= 1;
  state.selected = null;
}

export function handleTagKey(
  state: TagEditorState,
  key: string,
  start: number,
  end: number,
  repeat = false,
): boolean {
  if (key === 'Backspace' || key === 'Delete') {
    if (state.selected !== null) {
      // A held key must not turn the initial selection into an accidental deletion.
      if (!repeat) removeTag(state, state.selected);
      return true;
    }
    if (start !== end) return false;
    if (key === 'Backspace' && start === 0 && state.gap > 0) {
      state.selected = state.gap - 1;
      return true;
    }
    if (key === 'Delete' && end === state.draft.length && state.gap < state.tags.length) {
      state.selected = state.gap;
      return true;
    }
    return false;
  }
  if (key === 'Escape' && state.selected !== null) {
    state.selected = null;
    return true;
  }
  if (key === 'Enter' || key === ' ') {
    commitTagDraft(state);
    return true;
  }
  if (start !== end) return false;
  if (key === 'ArrowLeft' && (state.selected !== null || start === 0 && state.gap > 0)) {
    moveTagGap(state, state.selected ?? state.gap - 1);
    return true;
  }
  if (key === 'ArrowRight' && (state.selected !== null || end === state.draft.length && state.gap < state.tags.length)) {
    moveTagGap(state, state.selected !== null ? state.selected + 1 : state.gap + 1);
    return true;
  }
  if ((key === 'Home' || key === 'End') && !state.draft) {
    moveTagGap(state, key === 'Home' ? 0 : state.tags.length);
    return true;
  }
  return false;
}
