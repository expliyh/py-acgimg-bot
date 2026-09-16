<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue';

import { useFeedback } from '@/composables/feedback';
import {
  bulkDeleteIllustrations,
  bulkRefreshIllustrations,
  bulkUpdateIllustrations,
  deleteIllustration,
  getIllustration,
  getIllustrationTask,
  illustrationMediaUrl,
  listIllustrations,
  listIllustrationTasks,
  refreshIllustration,
  updateIllustration,
  type IllustrationBulkUpdatePayload,
  type IllustrationDetail,
  type IllustrationImportTask,
  type IllustrationListItem,
  type IllustrationListQuery,
  type IllustrationSourceType,
  type IllustrationUpdatePayload,
} from '@/services/api';

const { toast, confirm } = useFeedback();

const PAGE_SIZE_OPTIONS = [12, 24, 48, 100];
const sourceOptions = [
  { title: '全部来源', value: null },
  { title: 'Pixiv', value: 'pixiv' as IllustrationSourceType },
  { title: '手动图片', value: 'manual' as IllustrationSourceType },
];
const booleanOptions = [
  { title: '全部', value: null },
  { title: '是', value: true },
  { title: '否', value: false },
];
const xRestrictOptions = [
  { title: '全部分级', value: null },
  { title: '全年龄（0）', value: 0 },
  { title: '限制级（1）', value: 1 },
  { title: 'R18（2）', value: 2 },
];
const sortOptions = [
  { title: 'ID', value: 'id' },
  { title: '标题', value: 'title' },
  { title: '作者', value: 'author_name' },
  { title: '页数', value: 'page_count' },
  { title: '过滤等级', value: 'sanity_level' },
  { title: '限制级', value: 'x_restrict' },
  { title: '来源', value: 'source_type' },
];

const items = ref<IllustrationListItem[]>([]);
const total = ref(0);
const pages = ref(0);
const page = ref(1);
const pageSize = ref(24);
const search = ref('');
const sourceType = ref<IllustrationSourceType | null>(null);
const r18gFilter = ref<boolean | null>(null);
const aiFilter = ref<boolean | null>(null);
const xRestrictFilter = ref<number | null>(null);
const sanityMin = ref<number | null>(null);
const sanityMax = ref<number | null>(null);
const sortBy = ref('id');
const sortOrder = ref<'asc' | 'desc'>('desc');
const loading = ref(false);
const loadError = ref('');
let loadVersion = 0;

const selectedIds = ref<Set<string>>(new Set());
const selectedCount = computed(() => selectedIds.value.size);
const allPageSelected = computed(
  () => items.value.length > 0 && items.value.every((item) => selectedIds.value.has(item.id)),
);
const selectedItems = computed(() => items.value.filter((item) => selectedIds.value.has(item.id)));
const canBulkRefresh = computed(
  () => selectedCount.value > 0 && selectedItems.value.every((item) => item.source_type === 'pixiv'),
);

const detailOpen = ref(false);
const detailLoading = ref(false);
const detailSaving = ref(false);
const detail = ref<IllustrationDetail | null>(null);
const detailPage = ref(0);
const detailError = ref('');
const mediaErrors = ref<Set<string>>(new Set());
let detailVersion = 0;
const editForm = reactive<IllustrationUpdatePayload>({});
const editTagsText = ref('');

const bulkEditOpen = ref(false);
const bulkSaving = ref(false);
const bulkApply = reactive<Record<string, boolean>>({
  title: false,
  author_name: false,
  author_url: false,
  source_url: false,
  caption: false,
  tags: false,
  sanity_level: false,
  x_restrict: false,
  r18g: false,
  is_ai: false,
});
const bulkValues = reactive<{
  title: string;
  author_name: string;
  author_url: string;
  source_url: string;
  caption: string;
  tags: string;
  sanity_level: number | null;
  x_restrict: number | null;
  r18g: boolean;
  is_ai: boolean;
}>({
  title: '',
  author_name: '',
  author_url: '',
  source_url: '',
  caption: '',
  tags: '',
  sanity_level: null,
  x_restrict: null,
  r18g: false,
  is_ai: false,
});

const queueTasks = ref<IllustrationImportTask[]>([]);
const queueLoading = ref(false);
let queueTimer: number | null = null;
let queuePolling = false;

function parseTags(value: string): string[] {
  return value
    .split(/[,，、]/)
    .map((tag) => tag.trim())
    .filter(Boolean)
    .filter((tag, index, all) => all.indexOf(tag) === index);
}

function errorMessage(error: any, fallback: string): string {
  return error?.response?.data?.error?.message ?? error?.response?.data?.detail ?? error?.message ?? fallback;
}

function statusColor(status: string): 'success' | 'warning' | 'error' | 'info' {
  if (status === 'success') return 'success';
  if (status === 'failed') return 'error';
  if (status === 'pending' || status === 'running') return 'warning';
  return 'info';
}

function statusLabel(status: string): string {
  return ({ pending: '排队中', running: '刷新中', success: '成功', failed: '失败' } as Record<string, string>)[status] ?? status;
}

function sourceLabel(source: string): string {
  return source === 'manual' ? '手动' : 'Pixiv';
}

function pageLabel(count: number): string {
  return `${count} 页`;
}

function queryParams(): IllustrationListQuery {
  const params: IllustrationListQuery = {
    page: page.value,
    page_size: pageSize.value,
    sort_by: sortBy.value,
    sort_order: sortOrder.value,
  };
  const text = search.value.trim();
  if (text) params.q = text;
  if (sourceType.value !== null) params.source_type = sourceType.value;
  if (r18gFilter.value !== null) params.r18g = r18gFilter.value;
  if (aiFilter.value !== null) params.is_ai = aiFilter.value;
  if (xRestrictFilter.value !== null) params.x_restrict = xRestrictFilter.value;
  if (sanityMin.value !== null) params.sanity_min = sanityMin.value;
  if (sanityMax.value !== null) params.sanity_max = sanityMax.value;
  return params;
}

async function loadIllustrations() {
  const version = ++loadVersion;
  loading.value = true;
  loadError.value = '';
  try {
    const response = await listIllustrations(queryParams());
    if (version !== loadVersion) return;
    items.value = response.items;
    total.value = response.total;
    pages.value = response.pages;
    const visibleIds = new Set(response.items.map((item) => item.id));
    selectedIds.value = new Set(
      [...selectedIds.value].filter((id) => visibleIds.has(id)),
    );
    if (pages.value > 0 && page.value > pages.value) page.value = pages.value;
  } catch (error) {
    if (version !== loadVersion) return;
    console.error(error);
    loadError.value = errorMessage(error, '无法加载图片图库。');
  } finally {
    if (version === loadVersion) loading.value = false;
  }
}

function clearSelection() {
  selectedIds.value = new Set();
}

function toggleSelect(id: string) {
  const next = new Set(selectedIds.value);
  if (next.has(id)) next.delete(id);
  else next.add(id);
  selectedIds.value = next;
}

function togglePageSelection() {
  const next = new Set(selectedIds.value);
  if (allPageSelected.value) items.value.forEach((item) => next.delete(item.id));
  else items.value.forEach((item) => next.add(item.id));
  selectedIds.value = next;
}

function mediaErrorKey(id: string, pageIndex: number): string {
  return `${id}:${pageIndex}`;
}

function hasMediaError(id: string, pageIndex: number): boolean {
  return mediaErrors.value.has(mediaErrorKey(id, pageIndex));
}

function markMediaError(id: string, pageIndex: number) {
  const next = new Set(mediaErrors.value);
  next.add(mediaErrorKey(id, pageIndex));
  mediaErrors.value = next;
}

function clearMediaError(id: string, pageIndex: number) {
  const next = new Set(mediaErrors.value);
  next.delete(mediaErrorKey(id, pageIndex));
  mediaErrors.value = next;
}

function syncEditForm(value: IllustrationDetail) {
  Object.keys(editForm).forEach((key) => delete (editForm as Record<string, unknown>)[key]);
  Object.assign(editForm, {
    title: value.title,
    author_name: value.author_name,
    author_url: value.author_url,
    source_url: value.source_url,
    caption: value.caption,
    tags: [...value.tags],
    sanity_level: value.sanity_level,
    x_restrict: value.x_restrict,
    r18g: value.r18g,
    is_ai: value.is_ai,
  });
  editTagsText.value = value.tags.join(', ');
}

async function openDetail(id: string) {
  const version = ++detailVersion;
  detailOpen.value = true;
  detailLoading.value = true;
  detailError.value = '';
  detail.value = null;
  detailPage.value = 0;
  mediaErrors.value = new Set();
  try {
    const value = await getIllustration(id);
    if (version !== detailVersion) return;
    detail.value = value;
    syncEditForm(value);
  } catch (error) {
    if (version !== detailVersion) return;
    console.error(error);
    detailError.value = errorMessage(error, '无法加载图片详情。');
  } finally {
    if (version === detailVersion) detailLoading.value = false;
  }
}

function closeDetail() {
  detailVersion += 1;
  detailOpen.value = false;
  detailError.value = '';
}

function editPayload(): IllustrationUpdatePayload {
  return {
    title: typeof editForm.title === 'string' ? editForm.title.trim() || null : null,
    author_name: typeof editForm.author_name === 'string' ? editForm.author_name.trim() || null : null,
    author_url: typeof editForm.author_url === 'string' ? editForm.author_url.trim() || null : null,
    source_url: typeof editForm.source_url === 'string' ? editForm.source_url.trim() || null : null,
    caption: typeof editForm.caption === 'string' ? editForm.caption.trim() || null : null,
    tags: parseTags(editTagsText.value),
    sanity_level: editForm.sanity_level ?? null,
    x_restrict: editForm.x_restrict ?? null,
    r18g: editForm.r18g ?? false,
    is_ai: editForm.is_ai ?? false,
  };
}

async function saveDetail() {
  if (!detail.value) return;
  detailSaving.value = true;
  try {
    const updated = await updateIllustration(detail.value.id, editPayload());
    detail.value = updated;
    syncEditForm(updated);
    items.value = items.value.map((item) => item.id === updated.id ? { ...item, ...updated } : item);
    toast.add({ severity: 'success', summary: '保存成功', detail: '图片元数据已更新。', life: 2800 });
  } catch (error) {
    console.error(error);
    toast.add({ severity: 'error', summary: '保存失败', detail: errorMessage(error, '无法保存图片元数据。'), life: 5000 });
  } finally {
    detailSaving.value = false;
  }
}

function resetBulkForm() {
  Object.keys(bulkApply).forEach((key) => { bulkApply[key] = false; });
  bulkValues.title = '';
  bulkValues.author_name = '';
  bulkValues.author_url = '';
  bulkValues.source_url = '';
  bulkValues.caption = '';
  bulkValues.tags = '';
  bulkValues.sanity_level = null;
  bulkValues.x_restrict = null;
  bulkValues.r18g = false;
  bulkValues.is_ai = false;
}

function openBulkEdit() {
  if (!selectedCount.value) return;
  resetBulkForm();
  bulkEditOpen.value = true;
}

function bulkPatch(): IllustrationUpdatePayload {
  const patch: IllustrationUpdatePayload = {};
  if (bulkApply.title) patch.title = bulkValues.title.trim() || null;
  if (bulkApply.author_name) patch.author_name = bulkValues.author_name.trim() || null;
  if (bulkApply.author_url) patch.author_url = bulkValues.author_url.trim() || null;
  if (bulkApply.source_url) patch.source_url = bulkValues.source_url.trim() || null;
  if (bulkApply.caption) patch.caption = bulkValues.caption.trim() || null;
  if (bulkApply.tags) patch.tags = parseTags(bulkValues.tags);
  if (bulkApply.sanity_level) patch.sanity_level = bulkValues.sanity_level;
  if (bulkApply.x_restrict) patch.x_restrict = bulkValues.x_restrict;
  if (bulkApply.r18g) patch.r18g = bulkValues.r18g;
  if (bulkApply.is_ai) patch.is_ai = bulkValues.is_ai;
  return patch;
}

async function saveBulkEdit() {
  const patch = bulkPatch();
  if (!Object.keys(patch).length) {
    toast.add({ severity: 'warning', summary: '未选择字段', detail: '请先打开至少一个字段的启用开关。', life: 3200 });
    return;
  }
  bulkSaving.value = true;
  try {
    const payload: IllustrationBulkUpdatePayload = { ids: [...selectedIds.value], patch };
    await bulkUpdateIllustrations(payload);
    bulkEditOpen.value = false;
    clearSelection();
    await loadIllustrations();
    toast.add({ severity: 'success', summary: '批量保存成功', detail: `已更新 ${payload.ids.length} 张图片。`, life: 3500 });
  } catch (error) {
    console.error(error);
    toast.add({ severity: 'error', summary: '批量保存失败', detail: errorMessage(error, '无法批量更新图片。'), life: 5000 });
  } finally {
    bulkSaving.value = false;
  }
}

function cleanupSummary(response: { cleanup_failures?: Array<{ illustration_id: string; page: number; error: string }> }): string {
  const failures = response.cleanup_failures?.length ?? 0;
  return failures ? `数据库记录已删除，但有 ${failures} 个文件清理失败，请查看日志。` : '数据库记录和未共享的存储文件已清理。';
}

async function executeDelete(ids: string[], closeDetailAfter = false) {
  try {
    const response = ids.length === 1
      ? await deleteIllustration(ids[0])
      : await bulkDeleteIllustrations(ids);
    if (closeDetailAfter) closeDetail();
    clearSelection();
    await loadIllustrations();
    toast.add({
      severity: response.cleanup_failures.length ? 'warning' : 'success',
      summary: '删除完成',
      detail: `${response.removed_ids.length} 张图片已删除。${cleanupSummary(response)}`,
      life: 5500,
    });
  } catch (error) {
    console.error(error);
    toast.add({ severity: 'error', summary: '删除失败', detail: errorMessage(error, '无法删除图片。'), life: 5000 });
  }
}

function requestDelete(ids: string[], closeDetailAfter = false) {
  if (!ids.length) return;
  confirm.require({
    header: '确认删除图片',
    icon: 'mdi-delete-alert-outline',
    message: `确定删除当前选中的 ${ids.length} 张图片吗？数据库记录会被删除，未共享的存储文件会尝试清理；Telegram 文件 ID 无法由 Bot API 撤销。`,
    acceptLabel: '删除',
    rejectLabel: '取消',
    accept: () => { void executeDelete(ids, closeDetailAfter); },
  });
}

function requestBulkDelete() {
  requestDelete([...selectedIds.value]);
}

async function enqueueRefresh(ids: string[]) {
  try {
    const response = ids.length === 1
      ? { tasks: [await refreshIllustration(ids[0])] }
      : await bulkRefreshIllustrations(ids);
    const byId = new Map(queueTasks.value.map((task) => [task.id, task]));
    response.tasks.forEach((task) => byId.set(task.id, task));
    queueTasks.value = [...byId.values()];
    startQueuePolling();
    clearSelection();
    toast.add({ severity: 'info', summary: '刷新任务已排队', detail: `已加入 ${response.tasks.length} 个 Pixiv 刷新任务。`, life: 3500 });
  } catch (error) {
    console.error(error);
    toast.add({ severity: 'error', summary: '刷新失败', detail: errorMessage(error, '无法创建刷新任务。'), life: 5000 });
  }
}

function requestBulkRefresh() {
  if (!canBulkRefresh.value) return;
  void enqueueRefresh([...selectedIds.value]);
}

function requestDetailRefresh() {
  if (!detail.value || detail.value.source_type !== 'pixiv') return;
  void enqueueRefresh([detail.value.id]);
}

function mergeQueueTask(task: IllustrationImportTask) {
  const index = queueTasks.value.findIndex((item) => item.id === task.id);
  if (index < 0) queueTasks.value = [...queueTasks.value, task];
  else queueTasks.value = queueTasks.value.map((item) => item.id === task.id ? task : item);
}

async function pollQueue() {
  if (queuePolling || !queueTasks.value.some((task) => task.status === 'pending' || task.status === 'running')) return;
  queuePolling = true;
  try {
    const active = queueTasks.value.filter((task) => task.status === 'pending' || task.status === 'running');
    const updates = await Promise.all(active.map(async (task) => {
      try { return await getIllustrationTask(task.id); }
      catch (error) { console.error(error); return task; }
    }));
    updates.forEach(mergeQueueTask);
    if (updates.some((task) => task.status === 'success')) await loadIllustrations();
    updates.filter((task) => task.status === 'failed').forEach((task) => {
      toast.add({ severity: 'error', summary: `刷新任务 #${task.id} 失败`, detail: task.error_message ?? '未知错误', life: 6000 });
    });
  } finally {
    queuePolling = false;
    if (!queueTasks.value.some((task) => task.status === 'pending' || task.status === 'running')) stopQueuePolling();
  }
}

function startQueuePolling() {
  if (queueTimer !== null) return;
  queueTimer = window.setInterval(() => { void pollQueue(); }, 2000);
  void pollQueue();
}

function stopQueuePolling() {
  if (queueTimer !== null) window.clearInterval(queueTimer);
  queueTimer = null;
}

async function loadExistingQueue() {
  queueLoading.value = true;
  try {
    const response = await listIllustrationTasks(1, 100);
    queueTasks.value = response.items.filter((task) => task.status === 'pending' || task.status === 'running');
    if (queueTasks.value.length) startQueuePolling();
  } catch (error) {
    // The gallery remains usable if task history is temporarily unavailable.
    console.error(error);
  } finally {
    queueLoading.value = false;
  }
}

function mediaUrl(id: string, pageIndex = 0): string {
  return illustrationMediaUrl(id, pageIndex);
}

function imageAlt(item: IllustrationListItem, pageIndex = 0): string {
  return `${item.title || '插画'}（${item.id}）第 ${pageIndex + 1} 页`;
}

function onFilterChanged() {
  page.value = 1;
  clearSelection();
}

watch(
  [search, sourceType, r18gFilter, aiFilter, xRestrictFilter, sanityMin, sanityMax],
  () => {
    clearSelection();
    if (page.value !== 1) {
      page.value = 1;
      return;
    }
    void loadIllustrations();
  },
);

watch(
  [sortBy, sortOrder, page, pageSize],
  () => {
    clearSelection();
    void loadIllustrations();
  },
);

onMounted(async () => {
  await Promise.all([loadIllustrations(), loadExistingQueue()]);
});

onUnmounted(stopQueuePolling);
</script>

<template>
  <section class="illustration-gallery d-flex flex-column ga-4">
    <header class="d-flex align-start justify-space-between flex-wrap ga-3">
      <div>
        <h1 class="text-h4 font-weight-bold ma-0">图片图库</h1>
        <p class="text-body-2 text-medium-emphasis mt-2 mb-0">浏览和维护已添加的 Pixiv 与手动图片。媒体通过受控接口读取，不暴露原始存储地址。</p>
      </div>
      <div class="d-flex ga-2">
        <VBtn prepend-icon="mdi-image-plus-outline" variant="outlined" to="/illustrations/import">添加图片</VBtn>
        <VBtn prepend-icon="mdi-refresh" :loading="loading" variant="outlined" @click="loadIllustrations">刷新列表</VBtn>
      </div>
    </header>

    <VCard class="toolbar-card">
      <VCardText class="d-flex flex-column ga-3">
        <VRow density="compact">
          <VCol cols="12" md="4"><VTextField v-model="search" label="搜索 ID、标题、作者、描述或标签" prepend-inner-icon="mdi-magnify" clearable hide-details /></VCol>
          <VCol cols="12" sm="6" md="2"><VSelect v-model="sourceType" label="来源" :items="sourceOptions" hide-details /></VCol>
          <VCol cols="12" sm="6" md="2"><VSelect v-model="r18gFilter" label="R18G" :items="booleanOptions" hide-details /></VCol>
          <VCol cols="12" sm="6" md="2"><VSelect v-model="aiFilter" label="AI 标记" :items="booleanOptions" hide-details /></VCol>
          <VCol cols="12" sm="6" md="2"><VSelect v-model="xRestrictFilter" label="分级" :items="xRestrictOptions" hide-details /></VCol>
        </VRow>
        <VRow density="compact" align="center">
          <VCol cols="12" sm="6" md="2"><VNumberInput v-model="sanityMin" label="过滤等级 ≥" :min="0" :max="10" clearable hide-details @update:model-value="onFilterChanged" /></VCol>
          <VCol cols="12" sm="6" md="2"><VNumberInput v-model="sanityMax" label="过滤等级 ≤" :min="0" :max="10" clearable hide-details @update:model-value="onFilterChanged" /></VCol>
          <VCol cols="12" sm="6" md="3"><VSelect v-model="sortBy" label="排序字段" :items="sortOptions" hide-details /></VCol>
          <VCol cols="12" sm="6" md="2"><VSelect v-model="sortOrder" label="顺序" :items="[{ title: '降序', value: 'desc' }, { title: '升序', value: 'asc' }]" hide-details /></VCol>
          <VCol cols="12" md="3" class="d-flex justify-end align-center ga-2 text-body-2 text-medium-emphasis">共 {{ total }} 张 · 当前第 {{ page }} / {{ pages || 1 }} 页</VCol>
        </VRow>
      </VCardText>
    </VCard>

    <VCard v-if="selectedCount" class="bulk-toolbar" variant="tonal" color="primary">
      <VCardText class="d-flex align-center justify-space-between flex-wrap ga-3">
        <span class="font-weight-medium">已选择当前页 {{ selectedCount }} / {{ items.length }} 张</span>
        <div class="d-flex flex-wrap ga-2">
          <VBtn size="small" prepend-icon="mdi-pencil-outline" @click="openBulkEdit">批量编辑</VBtn>
          <VBtn size="small" prepend-icon="mdi-refresh" :disabled="!canBulkRefresh" @click="requestBulkRefresh">批量刷新 Pixiv</VBtn>
          <VBtn size="small" color="error" prepend-icon="mdi-delete-outline" @click="requestBulkDelete">批量删除</VBtn>
        </div>
      </VCardText>
    </VCard>

    <VAlert v-if="loadError" type="error" variant="tonal" closable @click:close="loadError = ''">{{ loadError }}</VAlert>
    <VProgressLinear v-if="loading" indeterminate color="primary" />

    <VCard v-if="queueTasks.length" class="queue-card">
      <VCardTitle class="d-flex align-center ga-2"><VIcon icon="mdi-refresh-auto" color="primary" /><span>刷新队列</span><VChip size="small" color="info">{{ queueTasks.length }}</VChip><VSpacer /><VProgressCircular v-if="queueLoading" indeterminate size="18" width="2" /></VCardTitle>
      <VCardText>
        <VList density="compact" class="pa-0">
          <VListItem v-for="task in queueTasks" :key="task.id" :title="`任务 #${task.id} · Pixiv ${task.pixiv_id}`" :subtitle="task.error_message || (task.status === 'running' ? `第 ${task.current_page ?? 0} / ${task.total_pages ?? '-'} 页` : '等待执行')">
            <template #prepend><VChip size="small" :color="statusColor(task.status)">{{ statusLabel(task.status) }}</VChip></template>
            <template #append><span v-if="task.finished_at" class="text-caption text-medium-emphasis">{{ new Date(task.finished_at).toLocaleString() }}</span></template>
          </VListItem>
        </VList>
      </VCardText>
    </VCard>

    <VCard class="gallery-card">
      <VCardTitle class="d-flex align-center justify-space-between flex-wrap ga-2">
        <div class="d-flex align-center ga-2"><VCheckbox :model-value="allPageSelected" :indeterminate="selectedCount > 0 && !allPageSelected" hide-details density="compact" aria-label="选择当前页" @update:model-value="togglePageSelection" /><span>图片列表</span></div>
        <VSelect v-model="pageSize" class="page-size-select" label="每页" :items="PAGE_SIZE_OPTIONS" density="compact" hide-details />
      </VCardTitle>
      <VCardText>
        <VRow v-if="items.length" class="gallery-grid">
          <VCol v-for="item in items" :key="item.id" cols="12" sm="6" md="4" lg="3" xl="2">
            <VCard class="illustration-card h-100" :class="{ 'illustration-card--selected': selectedIds.has(item.id) }" hover @click="openDetail(item.id)">
              <div class="illustration-cover">
                <VCheckbox :model-value="selectedIds.has(item.id)" class="card-checkbox" density="compact" hide-details aria-label="选择图片" @click.stop @update:model-value="toggleSelect(item.id)" />
                <img v-if="item.thumbnail_url && item.has_media && !hasMediaError(item.id, 0)" :src="item.thumbnail_url" :alt="imageAlt(item)" loading="lazy" @error="markMediaError(item.id, 0)" @load="clearMediaError(item.id, 0)" />
                <div v-else class="media-placeholder"><VIcon icon="mdi-image-off-outline" size="42" /><span>{{ item.has_media ? '媒体读取失败' : '暂无已存媒体' }}</span></div>
                <div class="cover-overlay"><VChip size="x-small" :color="item.source_type === 'pixiv' ? 'primary' : 'secondary'">{{ sourceLabel(item.source_type) }}</VChip><VChip v-if="item.r18g" size="x-small" color="error">R18G</VChip><VChip v-if="item.is_ai" size="x-small" color="info">AI</VChip></div>
              </div>
              <VCardText class="d-flex flex-column ga-2">
                <div class="text-subtitle-2 font-weight-bold text-truncate" :title="item.title || item.id">{{ item.title || '未命名图片' }}</div>
                <div class="text-caption text-medium-emphasis d-flex justify-space-between ga-2"><span>ID {{ item.id }}</span><span>{{ pageLabel(item.page_count) }}</span></div>
                <div class="text-caption text-medium-emphasis text-truncate">作者：{{ item.author_name || item.author_id || '未知' }}</div>
                <div class="d-flex align-center flex-wrap ga-1"><VChip size="x-small" variant="tonal">等级 {{ item.sanity_level }}</VChip><VChip size="x-small" variant="tonal">{{ item.x_restrict === 0 ? '全年龄' : item.x_restrict === 1 ? '限制级' : 'R18' }}</VChip></div>
                <div v-if="item.tags.length" class="d-flex flex-wrap ga-1"><VChip v-for="tag in item.tags.slice(0, 4)" :key="tag" size="x-small" variant="outlined">{{ tag }}</VChip><span v-if="item.tags.length > 4" class="text-caption text-medium-emphasis">+{{ item.tags.length - 4 }}</span></div>
              </VCardText>
            </VCard>
          </VCol>
        </VRow>
        <VAlert v-else type="info" variant="tonal" class="text-center">{{ loading ? '正在加载图片…' : '暂无符合条件的图片。' }}</VAlert>
      </VCardText>
      <VCardActions v-if="pages > 1" class="justify-center"><VPagination v-model="page" :length="pages" :total-visible="7" /></VCardActions>
    </VCard>

    <VDialog v-model="detailOpen" max-width="1120" scrollable>
      <VCard>
        <VCardTitle class="d-flex align-center ga-2"><VIcon icon="mdi-image-multiple-outline" color="primary" /><span>{{ detail?.title || detail?.id || '图片详情' }}</span><VSpacer /><VBtn icon="mdi-close" variant="text" aria-label="关闭详情" @click="closeDetail" /></VCardTitle>
        <VCardText>
          <VProgressLinear v-if="detailLoading" indeterminate color="primary" />
          <VAlert v-if="detailError" type="error" variant="tonal">{{ detailError }}</VAlert>
          <template v-if="detail && !detailLoading">
            <VRow>
              <VCol cols="12" md="7">
                <div class="detail-media-panel">
                  <template v-if="detail.pages.length && detail.pages[detailPage]?.has_storage_url && !hasMediaError(detail.id, detailPage)">
                    <img :src="detail.pages[detailPage].media_url || mediaUrl(detail.id, detailPage)" :alt="imageAlt(detail, detailPage)" class="detail-image" @error="markMediaError(detail.id, detailPage)" @load="clearMediaError(detail.id, detailPage)" />
                  </template>
                  <div v-else class="media-placeholder detail-placeholder"><VIcon icon="mdi-image-off-outline" size="64" /><span>{{ detail.pages.length ? '该页媒体缺失或读取失败' : '没有可用媒体' }}</span></div>
                </div>
                <div v-if="detail.pages.length > 1" class="d-flex align-center justify-center ga-3 mt-3"><VBtn icon="mdi-chevron-left" variant="outlined" aria-label="上一页" :disabled="detailPage <= 0" @click="detailPage -= 1" /><span class="text-body-2">第 {{ detailPage + 1 }} / {{ detail.pages.length }} 页</span><VBtn icon="mdi-chevron-right" variant="outlined" aria-label="下一页" :disabled="detailPage >= detail.pages.length - 1" @click="detailPage += 1" /></div>
              </VCol>
              <VCol cols="12" md="5">
                <div class="d-flex flex-wrap ga-2 mb-3"><VChip size="small" :color="detail.source_type === 'pixiv' ? 'primary' : 'secondary'">{{ sourceLabel(detail.source_type) }}</VChip><VChip size="small" variant="tonal">ID {{ detail.id }}</VChip><VChip size="small" variant="tonal">{{ pageLabel(detail.page_count) }}</VChip><VChip v-if="detail.r18g" size="small" color="error">R18G</VChip><VChip v-if="detail.is_ai" size="small" color="info">AI</VChip></div>
                <VTextField v-model="editForm.title" label="标题" maxlength="64" />
                <VTextField v-model="editForm.author_name" label="作者显示名" maxlength="64" />
                <VTextField v-model="editForm.author_url" label="作者链接" type="url" />
                <VTextField v-model="editForm.source_url" label="来源链接" type="url" />
                <VTextarea v-model="editForm.caption" label="描述" rows="3" />
                <VTextField v-model="editTagsText" label="标签（逗号分隔）" hint="留空可清空标签" persistent-hint />
                <VRow density="compact"><VCol cols="6"><VNumberInput v-model="editForm.sanity_level" label="过滤等级" :min="0" :max="10" /></VCol><VCol cols="6"><VSelect v-model="editForm.x_restrict" label="限制级" :items="xRestrictOptions.slice(1)" /></VCol></VRow>
                <div class="d-flex flex-wrap ga-4"><VSwitch v-model="editForm.r18g" label="R18G" color="error" hide-details /><VSwitch v-model="editForm.is_ai" label="AI 作品" color="info" hide-details /></div>
                <VDivider class="my-3" />
                <div class="text-caption text-medium-emphasis">作者 ID：{{ detail.author_id }} · 文件地址、页数和 Telegram 文件 ID 为只读。</div>
                <div class="d-flex flex-wrap ga-2 mt-4"><VBtn color="primary" prepend-icon="mdi-content-save-outline" :loading="detailSaving" @click="saveDetail">保存元数据</VBtn><VBtn v-if="detail.source_type === 'pixiv'" variant="outlined" prepend-icon="mdi-refresh" @click="requestDetailRefresh">刷新 Pixiv</VBtn><VBtn color="error" variant="text" prepend-icon="mdi-delete-outline" @click="requestDelete([detail.id], true)">删除</VBtn></div>
              </VCol>
            </VRow>
          </template>
        </VCardText>
      </VCard>
    </VDialog>

    <VDialog v-model="bulkEditOpen" max-width="760" scrollable>
      <VCard>
        <VCardTitle>批量编辑当前页选中项</VCardTitle>
        <VCardText class="d-flex flex-column ga-3">
          <VAlert density="compact" variant="tonal" type="info">每个字段都需要先打开“应用”开关；关闭的字段不会提交，布尔值关闭也会明确写入 false。</VAlert>
          <div class="bulk-field"><VCheckbox v-model="bulkApply.title" label="应用标题" hide-details /><VTextField v-model="bulkValues.title" :disabled="!bulkApply.title" maxlength="64" hide-details /></div>
          <div class="bulk-field"><VCheckbox v-model="bulkApply.author_name" label="应用作者显示名" hide-details /><VTextField v-model="bulkValues.author_name" :disabled="!bulkApply.author_name" maxlength="64" hide-details /></div>
          <div class="bulk-field"><VCheckbox v-model="bulkApply.author_url" label="应用作者链接" hide-details /><VTextField v-model="bulkValues.author_url" :disabled="!bulkApply.author_url" type="url" hide-details /></div>
          <div class="bulk-field"><VCheckbox v-model="bulkApply.source_url" label="应用来源链接" hide-details /><VTextField v-model="bulkValues.source_url" :disabled="!bulkApply.source_url" type="url" hide-details /></div>
          <div class="bulk-field"><VCheckbox v-model="bulkApply.caption" label="应用描述" hide-details /><VTextarea v-model="bulkValues.caption" :disabled="!bulkApply.caption" rows="2" hide-details /></div>
          <div class="bulk-field"><VCheckbox v-model="bulkApply.tags" label="应用标签" hide-details /><VTextField v-model="bulkValues.tags" :disabled="!bulkApply.tags" placeholder="逗号分隔；留空清空" hide-details /></div>
          <div class="bulk-field"><VCheckbox v-model="bulkApply.sanity_level" label="应用过滤等级" hide-details /><VNumberInput v-model="bulkValues.sanity_level" :disabled="!bulkApply.sanity_level" :min="0" :max="10" hide-details /></div>
          <div class="bulk-field"><VCheckbox v-model="bulkApply.x_restrict" label="应用限制级" hide-details /><VSelect v-model="bulkValues.x_restrict" :disabled="!bulkApply.x_restrict" :items="xRestrictOptions.slice(1)" hide-details /></div>
          <div class="bulk-field"><VCheckbox v-model="bulkApply.r18g" label="应用 R18G" hide-details /><VSwitch v-model="bulkValues.r18g" :disabled="!bulkApply.r18g" color="error" hide-details /></div>
          <div class="bulk-field"><VCheckbox v-model="bulkApply.is_ai" label="应用 AI 标记" hide-details /><VSwitch v-model="bulkValues.is_ai" :disabled="!bulkApply.is_ai" color="info" hide-details /></div>
        </VCardText>
        <VCardActions><VSpacer /><VBtn variant="text" @click="bulkEditOpen = false">取消</VBtn><VBtn color="primary" :loading="bulkSaving" @click="saveBulkEdit">应用修改</VBtn></VCardActions>
      </VCard>
    </VDialog>
  </section>
</template>

<style scoped>
.toolbar-card,
.gallery-card,
.queue-card {
  overflow: hidden;
}

.page-size-select {
  max-width: 7rem;
}

.illustration-card {
  overflow: hidden;
  transition: border-color 0.18s ease, transform 0.18s ease;
  border: 1px solid transparent;
}

.illustration-card:hover {
  transform: translateY(-2px);
}

.illustration-card--selected {
  border-color: rgb(var(--v-theme-primary));
}

.illustration-cover {
  position: relative;
  height: 220px;
  overflow: hidden;
  background: color-mix(in srgb, rgb(var(--v-theme-primary)) 8%, rgb(var(--v-theme-surface)));
}

.illustration-cover img {
  width: 100%;
  height: 100%;
  display: block;
  object-fit: cover;
}

.card-checkbox {
  position: absolute;
  z-index: 2;
  top: 0.35rem;
  left: 0.35rem;
  border-radius: 999px;
  background: color-mix(in srgb, black 45%, transparent);
}

.cover-overlay {
  position: absolute;
  right: 0.5rem;
  bottom: 0.5rem;
  left: 0.5rem;
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 0.3rem;
}

.media-placeholder {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.45rem;
  color: rgb(var(--v-theme-on-surface-variant));
  font-size: 0.78rem;
  text-align: center;
}

.detail-media-panel {
  min-height: 31rem;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  border-radius: 0.75rem;
  background: color-mix(in srgb, rgb(var(--v-theme-primary)) 7%, rgb(var(--v-theme-surface)));
}

.detail-image {
  width: 100%;
  max-height: 68vh;
  object-fit: contain;
}

.detail-placeholder {
  min-height: 31rem;
}

.bulk-field {
  display: grid;
  grid-template-columns: minmax(10rem, 14rem) minmax(0, 1fr);
  align-items: center;
  gap: 0.75rem;
}

@media (max-width: 600px) {
  .bulk-field {
    grid-template-columns: 1fr;
    gap: 0.25rem;
  }
  .detail-media-panel,
  .detail-placeholder {
    min-height: 18rem;
  }
}
</style>
