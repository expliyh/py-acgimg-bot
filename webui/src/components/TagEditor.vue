<script setup lang="ts">
import { computed, nextTick, reactive, ref, useId, watch } from 'vue';

import {
  commitTagDraft,
  createTagEditorState,
  handleTagKey,
  moveTagGap,
  removeTag,
  selectTag,
  updateTagDraft,
} from '@/utils/tag-editor';

const props = defineProps<{ modelValue: string[] }>();
const emit = defineEmits<{ 'update:modelValue': [value: string[]] }>();
const state = reactive(createTagEditorState(props.modelValue));
const root = ref<HTMLElement | null>(null);
const id = useId();
const composing = ref(false);
const focused = ref(false);
let literalSpace = false;
const selectionMessage = computed(() => state.selected === null
  ? ''
  : `已选中「${state.tags[state.selected]}」，再按退格或 Delete 删除，Esc 取消。`);

watch(() => props.modelValue, (tags) => {
  if (tags.length === state.tags.length && tags.every((tag, index) => tag === state.tags[index])) return;
  Object.assign(state, createTagEditorState(tags));
  composing.value = false;
});

function publish() {
  if (props.modelValue.length !== state.tags.length || state.tags.some((tag, index) => tag !== props.modelValue[index])) {
    emit('update:modelValue', [...state.tags]);
  }
}

async function focusInput(position?: number) {
  await nextTick();
  const input = root.value?.querySelector<HTMLInputElement>(`input[data-gap="${state.gap}"]`);
  input?.focus();
  const caret = Math.max(0, position ?? state.draft.length);
  input?.setSelectionRange(caret, caret);
}

function activateGap(gap: number) {
  focused.value = true;
  if (gap === state.gap) return;
  moveTagGap(state, gap);
  publish();
  void focusInput();
}

function commit() {
  commitTagDraft(state);
  publish();
}

function onInput(event: Event) {
  const input = event.target as HTMLInputElement;
  state.draft = input.value;
  state.selected = null;
  if (composing.value || (event as InputEvent).isComposing) return;
  const caret = input.selectionStart ?? input.value.length;
  const previousGap = state.gap;
  updateTagDraft(state, input.value);
  // Virtual keyboards may insert a space without dispatching a keydown event.
  if (!literalSpace && (event as InputEvent).inputType === 'insertText' && /^[ \u3000]$/.test((event as InputEvent).data ?? '')) {
    commitTagDraft(state);
  }
  literalSpace = false;
  publish();
  if (state.gap !== previousGap || state.draft !== input.value) {
    void focusInput(state.draft.length - (input.value.length - caret));
  }
}

function onCompositionEnd(event: CompositionEvent) {
  composing.value = false;
  onInput(event);
}

function onKeydown(event: KeyboardEvent) {
  literalSpace = event.key === ' ' && event.shiftKey;
  if (composing.value || event.isComposing || event.keyCode === 229 || event.ctrlKey || event.metaKey || event.altKey || event.shiftKey) return;
  const input = event.target as HTMLInputElement;
  const start = input.selectionStart ?? 0;
  const end = input.selectionEnd ?? start;
  if (!handleTagKey(state, event.key, start, end, event.repeat)) return;
  event.preventDefault();
  event.stopPropagation();
  publish();
  const caret = event.key === 'ArrowRight' || event.key === 'Home' ? 0 : start;
  void focusInput(event.key === 'ArrowLeft' || event.key === 'End' ? undefined : Math.min(caret, state.draft.length));
}

function onPaste(event: ClipboardEvent) {
  if (composing.value || !event.clipboardData) return;
  const input = event.target as HTMLInputElement;
  const text = event.clipboardData.getData('text/plain');
  event.preventDefault();
  state.draft = state.draft.slice(0, input.selectionStart ?? 0) + text + state.draft.slice(input.selectionEnd ?? state.draft.length);
  commit();
  void focusInput();
}

function onSelect(index: number) {
  selectTag(state, index);
  publish();
  void focusInput();
}

function onRemove(index: number) {
  selectTag(state, index);
  removeTag(state, state.selected!);
  publish();
  void focusInput();
}

function onFocusout(event: FocusEvent) {
  if (event.relatedTarget instanceof Node && root.value?.contains(event.relatedTarget)) return;
  focused.value = false;
  state.selected = null;
  commit();
}

defineExpose({ commit });
</script>

<template>
  <div ref="root" class="tag-editor" @focusout="onFocusout">
    <label :id="`${id}-label`" :for="`${id}-input-${state.gap}`" class="tag-editor__label">标签</label>
    <div
      class="tag-editor__field"
      :class="{ 'tag-editor__field--focused': focused }"
      role="group"
      :aria-labelledby="`${id}-label`"
      @click.self="focusInput()"
    >
      <template v-for="gap in state.tags.length + 1" :key="gap - 1">
        <span class="tag-editor__entry" :class="{ 'tag-editor__entry--last': gap === state.tags.length + 1 }">
          <span class="tag-editor__sizer" aria-hidden="true">{{ gap - 1 === state.gap ? state.draft || '\u200b' : '\u200b' }}</span>
          <input
            :id="`${id}-input-${gap - 1}`"
            :data-gap="gap - 1"
            :value="gap - 1 === state.gap ? state.draft : ''"
            :tabindex="gap - 1 === state.gap ? 0 : -1"
            :aria-label="gap === state.tags.length + 1 ? '添加标签' : `在「${state.tags[gap - 1]}」前添加标签`"
            :aria-describedby="`${id}-hint ${id}-selection`"
            :placeholder="!state.tags.length ? '输入或粘贴标签' : undefined"
            autocomplete="off"
            @focus="activateGap(gap - 1)"
            @click="state.selected = null"
            @input="onInput"
            @keydown="onKeydown"
            @paste="onPaste"
            @compositionstart="composing = true"
            @compositionend="onCompositionEnd"
          />
        </span>
        <VChip
          v-if="gap - 1 < state.tags.length"
          :key="state.tags[gap - 1]"
          class="tag-editor__chip"
          :class="{ 'tag-editor__chip--selected': state.selected === gap - 1 }"
          :color="state.selected === gap - 1 ? 'primary' : undefined"
          :variant="state.selected === gap - 1 ? 'flat' : 'tonal'"
          :aria-pressed="state.selected === gap - 1"
          :aria-label="`标签：${state.tags[gap - 1]}`"
          :title="state.tags[gap - 1]"
          :tabindex="-1"
          closable
          :close-label="`删除标签：${state.tags[gap - 1]}`"
          @mousedown.prevent
          @click="onSelect(gap - 1)"
          @click:close="onRemove(gap - 1)"
        >{{ state.tags[gap - 1] }}</VChip>
      </template>
    </div>
    <div :id="`${id}-hint`" class="tag-editor__hint">逗号、空格或回车添加，可批量粘贴；Shift+空格输入词内空格。</div>
    <div :id="`${id}-selection`" class="tag-editor__hint" aria-live="polite" aria-atomic="true">
      {{ selectionMessage || '退格 / Delete 先选中相邻标签，再按一次删除；方向键移动光标。' }}
    </div>
  </div>
</template>

<style scoped>
.tag-editor {
  min-width: 0;
  margin-bottom: 1.25rem;
}

.tag-editor__label {
  display: inline-block;
  margin-bottom: 0.35rem;
  color: rgb(var(--v-theme-on-surface), 0.7);
  font-size: 0.875rem;
}

.tag-editor__field {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  row-gap: 0.45rem;
  min-height: 3.5rem;
  padding: 0.6rem;
  border: 1px solid rgb(var(--v-theme-on-surface), 0.56);
  border-radius: 4px;
  cursor: text;
}

.tag-editor__field--focused {
  border-color: rgb(var(--v-theme-primary));
  box-shadow: inset 0 0 0 1px rgb(var(--v-theme-primary));
}

.tag-editor__entry {
  position: relative;
  display: inline-grid;
  flex: 0 1 auto;
  min-width: 0.65rem;
  max-width: 100%;
  align-items: center;
  font-size: 0.9375rem;
}

.tag-editor__entry--last {
  flex-grow: 1;
  min-width: 3rem;
}

.tag-editor__sizer,
.tag-editor__entry input {
  padding: 0 0.15rem;
  font: inherit;
}

.tag-editor__sizer {
  min-height: 2rem;
  line-height: 2rem;
  visibility: hidden;
  overflow: hidden;
  white-space: pre;
}

.tag-editor__entry input {
  position: absolute;
  inset: 0;
  width: 100%;
  min-width: 0;
  height: 2rem;
  border: 0;
  outline: none;
  background: transparent;
  color: rgb(var(--v-theme-on-surface));
}

.tag-editor__chip {
  flex: 0 1 auto;
  max-width: calc(100% - 0.65rem);
  height: auto;
  min-height: 2rem;
}

.tag-editor__chip :deep(.v-chip__content) {
  min-width: 0;
  padding-block: 0.2rem;
  white-space: normal;
  overflow-wrap: anywhere;
}

.tag-editor__chip--selected {
  outline: 2px solid rgb(var(--v-theme-primary));
  outline-offset: 2px;
}

.tag-editor__hint {
  margin: 0.3rem 0.6rem 0;
  color: rgb(var(--v-theme-on-surface), 0.65);
  font-size: 0.75rem;
  line-height: 1.5;
}
</style>
