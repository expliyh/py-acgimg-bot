<script setup lang="ts">
import { onMounted, onUnmounted, ref, computed } from 'vue';
import Card from 'primevue/card';
import Button from 'primevue/button';
import InputText from 'primevue/inputtext';
import Textarea from 'primevue/textarea';
import InputNumber from 'primevue/inputnumber';
import InputSwitch from 'primevue/inputswitch';
import Tag from 'primevue/tag';
import Chip from 'primevue/chip';
import ProgressBar from 'primevue/progressbar';
import DataTable from 'primevue/datatable';
import Column from 'primevue/column';
import Toast from 'primevue/toast';
import ConfirmDialog from 'primevue/confirmdialog';
import Skeleton from 'primevue/skeleton';
import Divider from 'primevue/divider';
import { useToast } from 'primevue/usetoast';
import { useConfirm } from 'primevue/useconfirm';

import type {
  IllustrationPreview,
  IllustrationImportTask,
  IllustrationImportResult
} from '@/services/api';
import {
  previewIllustration,
  importIllustration,
  listIllustrationTasks,
  getIllustrationTask
} from '@/services/api';

const toast = useToast();
const confirm = useConfirm();

const pixivIdInput = ref<number | null>(null);
const loadingPreview = ref(false);
const importing = ref(false);
const preview = ref<IllustrationPreview | null>(null);

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

const activeProgress = computed(() => {
  const task = activeTask.value;
  if (!task || !task.total_pages || task.total_pages <= 0) return 0;
  return Math.min(100, Math.round(((task.current_page ?? 0) / task.total_pages) * 100));
});

const statusSeverity = (status: string): 'success' | 'warning' | 'danger' | 'info' | 'secondary' => {
  switch (status) {
    case 'success':
      return 'success';
    case 'failed':
      return 'danger';
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
    toast.add({ severity: 'warn', summary: '无效输入', detail: '请输入 Pixiv ID。', life: 3000 });
    return;
  }
  loadingPreview.value = true;
  try {
    const data = await previewIllustration(pixivId);
    applyPreview(data);
    toast.add({
      severity: data.exists ? 'info' : 'success',
      summary: data.exists ? '已存在' : '加载成功',
      detail: data.exists ? '该插画已在数据库中，导入将更新已有记录。' : '已从 Pixiv 获取插画信息，可修改后确认导入。'
    });
  } catch (error: any) {
    console.error(error);
    preview.value = null;
    const detail = error?.response?.data?.detail ?? '无法加载该 Pixiv ID，请检查 Pixiv Token 配置。';
    toast.add({ severity: 'error', summary: '加载失败', detail, life: 5000 });
  } finally {
    loadingPreview.value = false;
  }
}

function onConfirmImport() {
  if (!preview.value) return;
  confirm.require({
    message: `确认导入 Pixiv ${preview.value.id}（共 ${preview.value.page_count} 页）？将下载原图并上传到存储服务。`,
    header: '确认导入',
    icon: 'pi pi-download',
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
    const detail = error?.response?.data?.detail ?? '创建导入任务失败，请稍后重试。';
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
    const response = await listIllustrationTasks(20);
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
  <section class="flex flex-column gap-4">
    <Toast />
    <ConfirmDialog />
    <header class="flex flex-column gap-2">
      <h2 class="text-2xl font-semibold m-0">插画导入</h2>
      <p class="text-color-secondary m-0">
        输入 Pixiv ID 加载插画信息，可修改标题/描述/标签等字段后确认导入；导入在后台执行，进度显示在下方历史任务中。
      </p>
    </header>

    <Card class="shadow-1">
      <template #content>
        <div class="flex flex-column md:flex-row gap-3 align-items-center">
          <InputNumber
            v-model="pixivIdInput"
            :min="1"
            placeholder="Pixiv ID，例如 12345678"
            class="w-full md:w-20rem"
            :useGrouping="false"
          />
          <div class="flex gap-2 w-full md:w-auto">
            <Button label="加载" icon="pi pi-search" :loading="loadingPreview" @click="loadPreview" />
            <Button label="重置" icon="pi pi-times" outlined severity="secondary" @click="reset" />
          </div>
        </div>
      </template>
    </Card>

    <Skeleton v-if="loadingPreview" height="18rem" class="border-round" />

    <Card v-else-if="preview" class="shadow-1">
      <template #title>
        <div class="flex align-items-center justify-content-between flex-wrap gap-2">
          <span>Pixiv {{ preview.id }}</span>
          <div class="flex gap-2">
            <Tag :value="preview.exists ? '已存在（将更新）' : '新插画'" :severity="preview.exists ? 'warning' : 'success'" />
            <Tag v-if="preview.r18g" value="R18G" severity="danger" />
            <Tag v-if="preview.is_ai" value="AI 作品" severity="info" />
          </div>
        </div>
      </template>
      <template #content>
        <div class="flex flex-column gap-4">
          <div class="flex flex-wrap gap-4 text-sm text-color-secondary">
            <span>作者：{{ preview.author_name }}（{{ preview.author_id }}）</span>
            <span>页数：{{ preview.page_count }}</span>
            <span>限制级：{{ preview.x_restrict }}</span>
          </div>

          <div v-if="preview.preview_urls.length" class="flex flex-wrap gap-2">
            <img
              v-for="(url, index) in preview.preview_urls"
              :key="index"
              :src="proxyImageUrl(url)"
              :alt="`第 ${index + 1} 页预览`"
              class="border-round shadow-1"
              style="max-width: 12rem; max-height: 12rem; object-fit: cover"
              loading="lazy"
            />
          </div>

          <Divider />

          <div class="flex flex-column gap-4">
            <div class="flex flex-column gap-2">
              <label class="font-medium">标题</label>
              <InputText v-model="editTitle" class="w-full" />
            </div>
            <div class="flex flex-column gap-2">
              <label class="font-medium">描述</label>
              <Textarea v-model="editCaption" rows="4" class="w-full" />
            </div>
            <div class="flex flex-column gap-2">
              <label class="font-medium">标签（逗号分隔）</label>
              <InputText v-model="editTagsText" class="w-full" />
              <div v-if="parseTags(editTagsText).length" class="flex flex-wrap gap-2">
                <Chip v-for="tag in parseTags(editTagsText)" :key="tag" :label="tag" />
              </div>
            </div>
            <div class="flex justify-content-between gap-3 align-items-center">
              <span class="font-medium">过滤等级（0-10）</span>
              <InputNumber v-model="editSanityLevel" :min="0" :max="10" :useGrouping="false" />
            </div>
            <div class="flex justify-content-between gap-3 align-items-center">
              <span class="font-medium">R18G</span>
              <InputSwitch v-model="editR18g" />
            </div>
            <div class="flex justify-content-between gap-3 align-items-center">
              <span class="font-medium">AI 作品</span>
              <InputSwitch v-model="editIsAi" />
            </div>
          </div>

          <Divider />

          <div class="flex justify-content-end gap-2">
            <Button label="确认导入" icon="pi pi-download" :loading="importing" @click="onConfirmImport" />
          </div>
        </div>
      </template>
    </Card>

    <!-- 当前任务进度 -->
    <Card v-if="activeTask && (activeTask.status === 'pending' || activeTask.status === 'running')" class="shadow-1">
      <template #title>
        <div class="flex align-items-center justify-content-between flex-wrap gap-2">
          <span>导入任务 #{{ activeTask.id }}：Pixiv {{ activeTask.pixiv_id }}</span>
          <Tag :value="statusLabel(activeTask.status)" :severity="statusSeverity(activeTask.status)" />
        </div>
      </template>
      <template #content>
        <div class="flex flex-column gap-2">
          <ProgressBar :value="activeProgress" />
          <span class="text-sm text-color-secondary">
            {{ activeTask.status === 'pending' ? '排队等待执行…' : `正在处理第 ${activeTask.current_page ?? 0} / ${activeTask.total_pages ?? '-'} 页` }}
          </span>
        </div>
      </template>
    </Card>

    <!-- 历史任务 -->
    <Card class="shadow-1">
      <template #title>
        <div class="flex align-items-center justify-content-between">
          <span>历史任务</span>
          <Button label="刷新" icon="pi pi-refresh" outlined size="small" :loading="loadingTasks" @click="loadTasks" />
        </div>
      </template>
      <template #content>
        <DataTable :value="tasks" :loading="loadingTasks" striped-rows data-key="id" :rows="10" paginator paginator-template="FirstPageLink PrevPageLink PageLinks NextPageLink LastPageLink" :row-class="(row) => (selectedTask && selectedTask.id === row.id ? 'bg-primary-100' : '')" @row-click="({ data }) => selectTask(data)">
          <template #empty>
            <div class="p-4 text-center text-color-secondary">暂无导入历史。确认导入后任务会显示在这里。</div>
          </template>
          <Column field="id" header="ID" :style="{ width: '4rem' }" />
          <Column field="pixiv_id" header="Pixiv ID" :style="{ width: '7rem' }" />
          <Column field="title" header="标题">
            <template #body="{ data }">{{ data.title || '-' }}</template>
          </Column>
          <Column header="状态" :style="{ width: '6rem' }">
            <template #body="{ data }">
              <Tag :value="statusLabel(data.status)" :severity="statusSeverity(data.status)" />
            </template>
          </Column>
          <Column header="进度" :style="{ width: '9rem' }">
            <template #body="{ data }">
              <span v-if="data.status === 'running' || data.status === 'pending'">
                {{ data.current_page ?? 0 }} / {{ data.total_pages ?? '-' }}
              </span>
              <span v-else-if="data.status === 'success'">{{ data.total_pages ?? '-' }} 页</span>
              <span v-else>-</span>
            </template>
          </Column>
          <Column header="创建时间" :style="{ width: '12rem' }">
            <template #body="{ data }">{{ formatTime(data.created_at) }}</template>
          </Column>
          <Column v-if="tasks.some((t) => t.error_message)" header="错误信息">
            <template #body="{ data }">
              <span v-if="data.error_message" class="text-red-500 text-sm">{{ data.error_message }}</span>
            </template>
          </Column>
        </DataTable>
      </template>
    </Card>

    <!-- 选中任务的结果 -->
    <Card v-if="selectedTask && selectedTask.status === 'success' && selectedTask.result" class="shadow-1">
      <template #title>
        <div class="flex align-items-center gap-2">
          <i class="pi pi-check-circle text-green-500"></i>
          <span>导入结果：Pixiv {{ selectedTask.result.id }}（{{ selectedTask.result.created ? '新增' : '更新' }}）</span>
        </div>
      </template>
      <template #content>
        <div v-if="!selectedTask.result.telegram_cache_enabled" class="mb-3 text-sm text-color-secondary">
          当前配置为导入阶段不缓存，首次发送时自动在 Telegram 缓存文件 ID。
        </div>
        <div class="flex flex-column gap-2 text-sm">
          <div v-for="page in selectedTask.result.pages" :key="page.index" class="flex flex-wrap gap-2 align-items-center">
            <Tag value="存储" :severity="page.storage_url ? 'success' : 'danger'" />
            <Tag value="PhotoID" :severity="page.compressed_file_id ? 'success' : 'warning'" />
            <Tag value="DocumentID" :severity="page.original_file_id ? 'success' : 'warning'" />
            <span>第 {{ page.index + 1 }} 页</span>
          </div>
        </div>
      </template>
    </Card>
  </section>
</template>
