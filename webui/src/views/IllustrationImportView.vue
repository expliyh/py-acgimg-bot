<script setup lang="ts">
import { onMounted, onUnmounted, ref, computed } from 'vue';
import { useFeedback } from '@/composables/feedback';
import type { DataTableHeader } from 'vuetify';
import {
  createIllustrationTaskHeaders,
  createIllustrationTaskRowProps,
} from '@/utils/illustration-task-table';

import type {
  IllustrationPreview,
  IllustrationImportTask,
  IllustrationImportResult
} from '@/services/api';
import {
  previewIllustration,
  importIllustration,
  listIllustrationTasks,
  getIllustrationTask,
  importManualIllustration
} from '@/services/api';

const { toast, confirm } = useFeedback();

const pixivIdInput = ref<number | null>(null);
const pixivStep = ref(1);
const loadingPreview = ref(false);
const importing = ref(false);
const preview = ref<IllustrationPreview | null>(null);
const manualFile = ref<File | null>(null);
const manualTitle = ref('');
const manualAuthor = ref('');
const manualSourceUrl = ref('');
const manualAuthorUrl = ref('');
const manualCaption = ref('');
const manualTags = ref('');
const manualAi = ref(false);
const manualR18 = ref(false);
const manualR18g = ref(false);
const manualUploading = ref(false);

function chooseManualFile(event: Event) {
  manualFile.value = (event.target as HTMLInputElement).files?.[0] ?? null;
}

async function submitManual() {
  if (!manualFile.value || !manualTitle.value.trim()) {
    toast.add({ severity: 'warning', summary: '信息不完整', detail: '请选择图片并填写名称。', life: 3000 });
    return;
  }
  manualUploading.value = true;
  try {
    const result = await importManualIllustration({
      image: manualFile.value,
      title: manualTitle.value.trim(),
      author_name: manualAuthor.value.trim(), source_url: manualSourceUrl.value.trim(),
      author_url: manualAuthorUrl.value.trim(), caption: manualCaption.value.trim(),
      tags: manualTags.value.trim(), is_ai: manualAi.value, is_r18: manualR18.value, is_r18g: manualR18g.value
    });
    toast.add({ severity: 'success', summary: '添加成功', detail: `${result.title}（${result.id}）已保存。`, life: 5000 });
    manualFile.value = null; manualTitle.value = ''; manualAuthor.value = '';
    manualSourceUrl.value = ''; manualAuthorUrl.value = ''; manualCaption.value = ''; manualTags.value = '';
    manualAi.value = false; manualR18.value = false; manualR18g.value = false;
  } catch (error: any) {
    toast.add({ severity: 'error', summary: '添加失败', detail: error?.response?.data?.error?.message ?? error?.response?.data?.detail ?? '无法保存图片。', life: 5000 });
  } finally { manualUploading.value = false; }
}

// 可编辑字段
const editTitle = ref('');
const editCaption = ref('');
const editTagsText = ref('');
const editSanityLevel = ref<number>(5);
const editR18g = ref(false);
const editIsAi = ref(false);

// 任务：当前活跃任务（轮询进度）+ 历史列表
const activeTask = ref<IllustrationImportTask | null>(null);
const tasks = ref<IllustrationImportTask[]>([]);
const loadingTasks = ref(false);
const selectedTask = ref<IllustrationImportTask | null>(null);
let pollTimer: number | null = null;
let pollTaskId: number | null = null;
let retryTimer: number | null = null;
let retryCount = 0;
const MAX_RETRIES = 5;

const headers = computed<DataTableHeader<IllustrationImportTask>[]>(() => createIllustrationTaskHeaders(tasks.value));

const activeProgress = computed(() => {
  const task = activeTask.value;
  if (!task || !task.total_pages || task.total_pages <= 0) return 0;
  return Math.min(100, Math.round(((task.current_page ?? 0) / task.total_pages) * 100));
});

const statusColor = (status: string): 'success' | 'warning' | 'error' | 'info' | 'secondary' => {
  switch (status) {
    case 'success':
      return 'success';
    case 'failed':
      return 'error';
    case 'running':
    case 'pending':
      return 'warning';
    default:
      return 'info';
  }
};

const statusLabel = (status: string): string => {
  switch (status) {
    case 'pending':
      return '等待中';
    case 'running':
      return '导入中';
    case 'success':
      return '成功';
    case 'failed':
      return '失败';
    default:
      return status;
  }
};

function taskRowProps({ item }: { item: IllustrationImportTask }) {
  return createIllustrationTaskRowProps(item, selectedTask.value?.id ?? null, selectTask);
}

const formatTime = (value: string | null): string => {
  if (!value) return '-';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
};

function parseTags(text: string): string[] {
  return text
    .split(/[,，、]/)
    .map((tag) => tag.trim())
    .filter(Boolean);
}

function proxyImageUrl(url: string): string {
  return `/api/illustrations/image?url=${encodeURIComponent(url)}`;
}

function applyPreview(data: IllustrationPreview) {
  preview.value = data;
  editTitle.value = data.title ?? '';
  editCaption.value = data.caption ?? '';
  editTagsText.value = (data.tags ?? []).join(', ');
  editSanityLevel.value = data.sanity_level;
  editR18g.value = data.r18g;
  editIsAi.value = data.is_ai;
}

async function loadPreview() {
  const pixivId = pixivIdInput.value;
  if (!pixivId) {
    toast.add({ severity: 'warning', summary: '无效输入', detail: '请输入 Pixiv ID。', life: 3000 });
    return;
  }
  loadingPreview.value = true;
  try {
    const data = await previewIllustration(pixivId);
    applyPreview(data);
    pixivStep.value = 2;
    toast.add({
      severity: data.exists ? 'info' : 'success',
      summary: data.exists ? '已存在' : '加载成功',
      detail: data.exists ? '该插画已在数据库中，导入将更新已有记录。' : '已从 Pixiv 获取插画信息，可修改后确认导入。'
    });
  } catch (error: any) {
    console.error(error);
    preview.value = null;
    const detail = error?.response?.data?.error?.message ?? error?.response?.data?.detail ?? '无法加载该 Pixiv ID，请检查 Pixiv Token 配置。';
    toast.add({ severity: 'error', summary: '加载失败', detail, life: 5000 });
  } finally {
    loadingPreview.value = false;
  }
}

function onConfirmImport() {
  if (!preview.value) return;
  pixivStep.value = 3;
  confirm.require({
    message: `确认导入 Pixiv ${preview.value.id}（共 ${preview.value.page_count} 页）？将下载原图并上传到存储服务。`,
    header: '确认导入',
    icon: 'mdi-download',
    acceptLabel: '导入',
    rejectLabel: '取消',
    accept: () => {
      confirm.close(); // 点击确认后立即关闭对话框
      doImport();
    }
  });
}

async function doImport() {
  if (!preview.value) return;
  const submittedId = preview.value.id;
  importing.value = true;
  try {
    const payload = {
      pixiv_id: Number(preview.value.id),
      title: editTitle.value.trim() || null,
      caption: editCaption.value.trim() || null,
      tags: parseTags(editTagsText.value),
      sanity_level: editSanityLevel.value,
      r18g: editR18g.value,
      is_ai: editIsAi.value
    };
    const task = await importIllustration(payload);
    activeTask.value = task;
    selectedTask.value = null;
    // 任务已创建，关闭预览/编辑卡片；若期间用户已加载新预览则保留
    if (preview.value && preview.value.id === submittedId) {
      preview.value = null;
    }
    toast.add({
      severity: 'info',
      summary: '任务已创建',
      detail: `Pixiv ${task.pixiv_id} 导入任务已开始（#${task.id}）。`
    });
    startPolling(task.id);
  } catch (error: any) {
    console.error(error);
    const detail = error?.response?.data?.error?.message ?? error?.response?.data?.detail ?? '创建导入任务失败，请稍后重试。';
    toast.add({ severity: 'error', summary: '创建失败', detail, life: 5000 });
  } finally {
    importing.value = false;
  }
}

function startPolling(taskId: number) {
  stopPolling();
  pollTaskId = taskId;
  pollTimer = window.setInterval(async () => {
    if (pollTaskId === null) return;
    try {
      const task = await getIllustrationTask(pollTaskId);
      activeTask.value = task;
      if (task.status === 'success' || task.status === 'failed') {
        stopPolling();
        selectedTask.value = task;
        await loadTasks();
        if (task.status === 'success') {
          toast.add({
            severity: 'success',
            summary: '导入完成',
            detail: `Pixiv ${task.pixiv_id} 已${task.created ? '新增' : '更新'}（${task.total_pages ?? '-'} 页）。`
          });
        } else {
          toast.add({
            severity: 'error',
            summary: '导入失败',
            detail: task.error_message ?? '未知错误',
            life: 6000
          });
        }
      }
    } catch (error) {
      console.error(error);
      stopPolling();
    }
  }, 2000);
}

function stopPolling() {
  if (pollTimer !== null) {
    window.clearInterval(pollTimer);
    pollTimer = null;
  }
  pollTaskId = null;
}

async function loadTasks() {
  loadingTasks.value = true;
  try {
    const response = await listIllustrationTasks(1, 20);
    tasks.value = response.items;
    retryCount = 0;
  } catch (error) {
    console.error(error);
    // 后端刚重启尚未就绪时首次请求可能失败，自动重试
    if (retryCount < MAX_RETRIES) {
      retryCount += 1;
      scheduleRetry();
    } else {
      toast.add({
        severity: 'error',
        summary: '加载历史失败',
        detail: '无法获取导入历史，请确认后端已启动完成。',
        life: 5000
      });
    }
  } finally {
    loadingTasks.value = false;
  }
}

function scheduleRetry() {
  clearRetry();
  retryTimer = window.setTimeout(() => {
    loadTasks();
  }, 3000);
}

function clearRetry() {
  if (retryTimer !== null) {
    window.clearTimeout(retryTimer);
    retryTimer = null;
  }
}

function selectTask(task: IllustrationImportTask) {
  selectedTask.value = task;
}

function reset() {
  stopPolling();
  pixivStep.value = 1;
  pixivIdInput.value = null;
  preview.value = null;
  activeTask.value = null;
  selectedTask.value = null;
}

onMounted(loadTasks);
onUnmounted(() => {
  stopPolling();
  clearRetry();
});
</script>

<template>
  <section class="d-flex flex-column ga-4">
    <header class="d-flex flex-column ga-2">
      <h2 class="text-h5 font-weight-bold ma-0">插画导入</h2>
      <p class="text-medium-emphasis ma-0">
        输入 Pixiv ID 加载插画信息，可修改标题/描述/标签等字段后确认导入；导入在后台执行，进度显示在下方历史任务中。
      </p>
    </header>

    <VCard class="elevation-1">
      <VCardTitle>手动添加非 Pixiv 图片</VCardTitle>
      <VCardText>
        <p class="text-body-2 text-medium-emphasis">仅名称和图片为必填项；来源、作者及其链接均可留空。</p>
        <VRow>
          <VCol cols="12" md="6" class="d-flex flex-column ga-2"><label>图片 *</label><input type="file" accept="image/jpeg,image/png,image/gif,image/webp" @change="chooseManualFile" /></VCol>
          <VCol cols="12" md="6" class="d-flex flex-column ga-2"><label for="manual-title">名称 *</label><VTextField id="manual-title" v-model="manualTitle" maxlength="64" hide-details="auto" /></VCol>
          <VCol cols="12" md="6" class="d-flex flex-column ga-2"><label for="manual-author">作者</label><VTextField id="manual-author" v-model="manualAuthor" hide-details="auto" /></VCol>
          <VCol cols="12" md="6" class="d-flex flex-column ga-2"><label for="manual-tags">标签（逗号分隔）</label><VTextField id="manual-tags" v-model="manualTags" hide-details="auto" /></VCol>
          <VCol cols="12" md="6" class="d-flex flex-column ga-2"><label for="manual-source-url">来源链接</label><VTextField id="manual-source-url" v-model="manualSourceUrl" type="url" placeholder="可留空" hide-details="auto" /></VCol>
          <VCol cols="12" md="6" class="d-flex flex-column ga-2"><label for="manual-author-url">作者链接</label><VTextField id="manual-author-url" v-model="manualAuthorUrl" type="url" placeholder="可留空" hide-details="auto" /></VCol>
          <VCol cols="12" class="d-flex flex-column ga-2"><label for="manual-caption">描述</label><VTextarea id="manual-caption" v-model="manualCaption" rows="2" hide-details="auto" /></VCol>
          <VCol cols="12" class="d-flex ga-4 flex-wrap">
            <label class="d-flex align-center ga-2"><VSwitch v-model="manualAi" color="primary" hide-details /> AI</label>
            <label class="d-flex align-center ga-2"><VSwitch v-model="manualR18" color="primary" hide-details /> R18</label>
            <label class="d-flex align-center ga-2"><VSwitch v-model="manualR18g" color="primary" hide-details /> R18G</label>
          </VCol>
          <VCol cols="12"><VBtn prepend-icon="mdi-upload" :loading="manualUploading" @click="submitManual">添加图片</VBtn></VCol>
        </VRow>
      </VCardText>
    </VCard>

    <VCard class="elevation-1">
      <VCardText>
        <v-stepper v-model="pixivStep" alt-labels flat class="mb-4">
          <v-stepper-header>
            <v-stepper-item :value="1" title="选择来源" subtitle="输入 Pixiv ID" />
            <v-divider />
            <v-stepper-item :value="2" title="编辑元数据" subtitle="预览并调整" />
            <v-divider />
            <v-stepper-item :value="3" title="确认提交" subtitle="后台导入" />
          </v-stepper-header>
        </v-stepper>
        <div class="d-flex flex-column flex-md-row ga-3 align-center">
          <VNumberInput
            v-model="pixivIdInput"
            :min="1"
            placeholder="Pixiv ID，例如 12345678"
            class="w-100"
            style="max-width: 20rem"
            hide-details="auto"
          />
          <div class="d-flex ga-2 w-100 w-md-auto">
            <VBtn prepend-icon="mdi-magnify" :loading="loadingPreview" @click="loadPreview">加载</VBtn>
            <VBtn prepend-icon="mdi-close" variant="outlined" color="secondary" @click="reset">重置</VBtn>
          </div>
        </div>
      </VCardText>
    </VCard>

    <VSkeletonLoader v-if="loadingPreview" height="18rem" class="rounded-lg" />

    <VCard v-else-if="preview" class="elevation-1">
      <VCardTitle>
        <div class="d-flex align-center justify-space-between flex-wrap ga-2">
          <span>Pixiv {{ preview.id }}</span>
          <div class="d-flex ga-2">
            <VChip size="small" :color="preview.exists ? 'warning' : 'success'">{{ preview.exists ? '已存在（将更新）' : '新插画' }}</VChip>
            <VChip v-if="preview.r18g" size="small" color="error">R18G</VChip>
            <VChip v-if="preview.is_ai" size="small" color="info">AI 作品</VChip>
          </div>
        </div>
      </VCardTitle>
      <VCardText>
        <div class="d-flex flex-column ga-4">
          <div class="d-flex flex-wrap ga-4 text-body-2 text-medium-emphasis">
            <span>作者：{{ preview.author_name }}（{{ preview.author_id }}）</span>
            <span>页数：{{ preview.page_count }}</span>
            <span>限制级：{{ preview.x_restrict }}</span>
          </div>

          <div v-if="preview.preview_urls.length" class="d-flex flex-wrap ga-2">
            <img
              v-for="(url, index) in preview.preview_urls"
              :key="index"
              :src="proxyImageUrl(url)"
              :alt="`第 ${index + 1} 页预览`"
              class="rounded-lg elevation-1"
              style="max-width: 12rem; max-height: 12rem; object-fit: cover"
              loading="lazy"
            />
          </div>

          <VDivider />

          <div class="d-flex flex-column ga-4">
            <div class="d-flex flex-column ga-2">
              <label class="font-weight-medium">标题</label>
              <VTextField v-model="editTitle" class="w-100" hide-details="auto" />
            </div>
            <div class="d-flex flex-column ga-2">
              <label class="font-weight-medium">描述</label>
              <VTextarea v-model="editCaption" rows="4" class="w-100" hide-details="auto" />
            </div>
            <div class="d-flex flex-column ga-2">
              <label class="font-weight-medium">标签（逗号分隔）</label>
              <VTextField v-model="editTagsText" class="w-100" hide-details="auto" />
              <div v-if="parseTags(editTagsText).length" class="d-flex flex-wrap ga-2">
                <VChip v-for="tag in parseTags(editTagsText)" :key="tag" size="small">{{ tag }}</VChip>
              </div>
            </div>
            <div class="d-flex justify-space-between ga-3 align-center">
              <span class="font-weight-medium">过滤等级（0-10）</span>
              <VNumberInput v-model="editSanityLevel" :min="0" :max="10" hide-details="auto" />
            </div>
            <div class="d-flex justify-space-between ga-3 align-center">
              <span class="font-weight-medium">R18G</span>
              <VSwitch v-model="editR18g" color="primary" hide-details />
            </div>
            <div class="d-flex justify-space-between ga-3 align-center">
              <span class="font-weight-medium">AI 作品</span>
              <VSwitch v-model="editIsAi" color="primary" hide-details />
            </div>
          </div>

          <VDivider />

          <div class="d-flex justify-end ga-2">
            <VBtn prepend-icon="mdi-download" :loading="importing" @click="onConfirmImport">确认导入</VBtn>
          </div>
        </div>
      </VCardText>
    </VCard>

    <!-- 当前任务进度 -->
    <VCard v-if="activeTask && (activeTask.status === 'pending' || activeTask.status === 'running')" class="elevation-1">
      <VCardTitle>
        <div class="d-flex align-center justify-space-between flex-wrap ga-2">
          <span>导入任务 #{{ activeTask.id }}：Pixiv {{ activeTask.pixiv_id }}</span>
          <VChip size="small" :color="statusColor(activeTask.status)">{{ statusLabel(activeTask.status) }}</VChip>
        </div>
      </VCardTitle>
      <VCardText>
        <div class="d-flex flex-column ga-2">
          <VProgressLinear :model-value="activeProgress" color="primary" />
          <span class="text-body-2 text-medium-emphasis">
            {{ activeTask.status === 'pending' ? '排队等待执行…' : `正在处理第 ${activeTask.current_page ?? 0} / ${activeTask.total_pages ?? '-'} 页` }}
          </span>
        </div>
      </VCardText>
    </VCard>

    <!-- 历史任务 -->
    <VCard class="elevation-1">
      <VCardTitle>
        <div class="d-flex align-center justify-space-between">
          <span>历史任务</span>
          <VBtn prepend-icon="mdi-refresh" variant="outlined" size="small" :loading="loadingTasks" @click="loadTasks">刷新</VBtn>
        </div>
      </VCardTitle>
      <VCardText>
        <VDataTable
          :headers="headers"
          :items="tasks"
          :loading="loadingTasks"
          item-value="id"
          :items-per-page="10"
          :row-props="taskRowProps"
          class="rounded-lg"
        >
          <template #no-data>
            <div class="p-4 text-center text-medium-emphasis">暂无导入历史。确认导入后任务会显示在这里。</div>
          </template>
          <template #item.title="{ item }">{{ item.title || '-' }}</template>
          <template #item.status="{ item }">
            <VChip size="small" :color="statusColor(item.status)">{{ statusLabel(item.status) }}</VChip>
          </template>
          <template #item.progress="{ item }">
            <span v-if="item.status === 'running' || item.status === 'pending'">
              {{ item.current_page ?? 0 }} / {{ item.total_pages ?? '-' }}
            </span>
            <span v-else-if="item.status === 'success'">{{ item.total_pages ?? '-' }} 页</span>
            <span v-else>-</span>
          </template>
          <template #item.created_at="{ item }">{{ formatTime(item.created_at) }}</template>
          <template #item.error_message="{ item }">
            <span v-if="item.error_message" class="text-body-2 text-error">{{ item.error_message }}</span>
          </template>
        </VDataTable>
      </VCardText>
    </VCard>

    <!-- 选中任务的结果 -->
    <VCard v-if="selectedTask && selectedTask.status === 'success' && selectedTask.result" class="elevation-1">
      <VCardTitle>
        <div class="d-flex align-center ga-2">
          <VIcon icon="mdi-check-circle" color="success" />
          <span>导入结果：Pixiv {{ selectedTask.result.id }}（{{ selectedTask.result.created ? '新增' : '更新' }}）</span>
        </div>
      </VCardTitle>
      <VCardText>
        <div v-if="!selectedTask.result.telegram_cache_enabled" class="mb-3 text-body-2 text-medium-emphasis">
          当前配置为导入阶段不缓存，首次发送时自动在 Telegram 缓存文件 ID。
        </div>
        <div class="d-flex flex-column ga-2 text-body-2">
          <div v-for="page in selectedTask.result.pages" :key="page.index" class="d-flex flex-wrap ga-2 align-center">
            <VChip size="small" :color="page.storage_url ? 'success' : 'error'">存储</VChip>
            <VChip size="small" :color="page.compressed_file_id ? 'success' : 'warning'">PhotoID</VChip>
            <VChip size="small" :color="page.original_file_id ? 'success' : 'warning'">DocumentID</VChip>
            <span>第 {{ page.index + 1 }} 页</span>
          </div>
        </div>
      </VCardText>
    </VCard>
  </section>
</template>
