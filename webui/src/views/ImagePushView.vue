<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref } from "vue";
import { listAllGroups, type GroupListItem } from "@/services/api";
import { useFeedback } from "@/composables/feedback";
import {
  createImagePushPlan,
  createManualImagePush,
  deleteImagePushPlan,
  getImagePushBatch,
  listImagePushBatches,
  listImagePushPlans,
  runImagePushPlan,
  updateImagePushPlan,
  type ImagePushBatch,
  type ImagePushConfig,
  type ImagePushMode,
  type ImagePushPlan,
  type ImagePushPlanPayload,
  type ImagePushRepeat,
} from "@/services/image-push-api";

const { toast } = useFeedback();
const groups = ref<GroupListItem[]>([]);
const groupsLoading = ref(false);
const selectedScope = ref<"selected" | "all">("selected");
const selectedGroups = ref<number[]>([]);
const mode = ref<ImagePushMode>("random_different");
const pid = ref("");
const pidByGroup = reactive<Record<string, string>>({});
const planName = ref("");
const repeat = ref<ImagePushRepeat>("daily");
const dueAt = ref("");
const intervalSeconds = ref(3600);
const timezone = ref("Asia/Shanghai");
const manualBusy = ref(false);
const planBusy = ref(false);
const plans = ref<ImagePushPlan[]>([]);
const batches = ref<ImagePushBatch[]>([]);
const activeBatch = ref<ImagePushBatch | null>(null);
let pollTimer: number | null = null;

const groupOptions = computed(() => groups.value.map((group) => ({
  title: `${group.name || "未命名群组"}（${group.id}）${group.enable && !["Disabled", "Blocked", "disabled", "blocked"].includes(group.status) ? "" : " · 已停用"}`,
  value: group.id,
})));
const mappingGroups = computed(() => selectedScope.value === "all"
  ? groups.value
  : groups.value.filter((group) => selectedGroups.value.includes(group.id)));
const modeOptions = [
  { title: "固定相同图片", value: "fixed_same" },
  { title: "固定不同图片", value: "fixed_different" },
  { title: "随机相同图片", value: "random_same" },
  { title: "随机不同图片", value: "random_different" },
];
const repeatOptions = [
  { title: "一次", value: "once" },
  { title: "每日", value: "daily" },
  { title: "每周", value: "weekly" },
  { title: "固定间隔", value: "interval" },
];

function syncMappingKeys() {
  const valid = new Set(mappingGroups.value.map((group) => String(group.id)));
  Object.keys(pidByGroup).forEach((key) => {
    if (!valid.has(key)) delete pidByGroup[key];
  });
  mappingGroups.value.forEach((group) => {
    if (!(String(group.id) in pidByGroup)) pidByGroup[String(group.id)] = "";
  });
}

function config(): ImagePushConfig {
  const value: ImagePushConfig = {
    target_scope: selectedScope.value,
    group_ids: selectedScope.value === "selected" ? [...selectedGroups.value] : [],
    mode: mode.value,
  };
  if (mode.value === "fixed_same") value.pid = pid.value.trim();
  if (mode.value === "fixed_different") {
    syncMappingKeys();
    value.pid_by_group = { ...pidByGroup };
  }
  return value;
}

function validateConfig(value: ImagePushConfig) {
  if (value.target_scope === "selected" && !value.group_ids.length) throw new Error("请选择至少一个群组。");
  if (value.mode === "fixed_same" && !value.pid) throw new Error("请输入 PID[:页码]。");
  if (value.mode === "fixed_different") {
    const missing = Object.entries(value.pid_by_group || {}).filter(([, item]) => !item.trim());
    if (missing.length) throw new Error(`请补充 ${missing.length} 个群组的 PID 映射。`);
  }
}

function dueAtIso(): string {
  if (!dueAt.value) throw new Error("请选择首次执行时间。");
  const date = new Date(dueAt.value);
  if (Number.isNaN(date.getTime())) throw new Error("执行时间格式无效。");
  return date.toISOString();
}

function planPayload(): ImagePushPlanPayload {
  const value = config();
  validateConfig(value);
  return {
    ...value,
    name: planName.value.trim(),
    enabled: true,
    repeat: repeat.value,
    due_at: dueAtIso(),
    interval_seconds: repeat.value === "interval" ? Number(intervalSeconds.value) : null,
    timezone: timezone.value.trim() || "Asia/Shanghai",
  };
}

async function loadGroups() {
  groupsLoading.value = true;
  try {
    groups.value = await listAllGroups();
    syncMappingKeys();
  } catch (error) {
    console.error(error);
    toast.add({ severity: "error", summary: "加载失败", detail: "无法获取群组列表。", life: 4000 });
  } finally {
    groupsLoading.value = false;
  }
}

async function loadPlans() {
  try {
    plans.value = (await listImagePushPlans(1, 100)).items;
  } catch (error) {
    console.error(error);
    toast.add({ severity: "error", summary: "加载失败", detail: "无法获取图片推送计划。", life: 4000 });
  }
}

async function loadBatches() {
  try {
    batches.value = (await listImagePushBatches(1, 100)).items;
  } catch (error) {
    console.error(error);
  }
}

async function submitManual() {
  manualBusy.value = true;
  try {
    const value = config();
    validateConfig(value);
    const batch = await createManualImagePush(value);
    activeBatch.value = batch;
    startPolling(batch.id);
    await loadBatches();
    toast.add({ severity: "success", summary: "已排队", detail: `图片推送批次 ${batch.id} 已创建。`, life: 3500 });
  } catch (error: any) {
    toast.add({ severity: "error", summary: "创建失败", detail: error?.response?.data?.error?.message ?? error?.message ?? "无法创建推送批次。", life: 5000 });
  } finally {
    manualBusy.value = false;
  }
}

async function submitPlan() {
  planBusy.value = true;
  try {
    if (!planName.value.trim()) throw new Error("请输入计划名称。");
    const plan = await createImagePushPlan(planPayload());
    plans.value.unshift(plan);
    toast.add({ severity: "success", summary: "计划已保存", detail: `计划“${plan.name}”已创建。`, life: 3500 });
  } catch (error: any) {
    toast.add({ severity: "error", summary: "保存失败", detail: error?.response?.data?.error?.message ?? error?.message ?? "无法保存推送计划。", life: 5000 });
  } finally {
    planBusy.value = false;
  }
}

async function togglePlan(plan: ImagePushPlan) {
  try {
    const updated = await updateImagePushPlan(plan.id, { enabled: !plan.enabled });
    plans.value = plans.value.map((item) => item.id === updated.id ? updated : item);
  } catch (error) {
    console.error(error);
    toast.add({ severity: "error", summary: "操作失败", detail: "无法更新计划状态。", life: 4000 });
  }
}

async function runPlan(plan: ImagePushPlan) {
  try {
    const batch = await runImagePushPlan(plan.id);
    activeBatch.value = batch;
    startPolling(batch.id);
    await loadBatches();
  } catch (error: any) {
    toast.add({ severity: "error", summary: "执行失败", detail: error?.response?.data?.error?.message ?? "无法创建执行批次。", life: 5000 });
  }
}

async function removePlan(plan: ImagePushPlan) {
  try {
    await deleteImagePushPlan(plan.id);
    plans.value = plans.value.filter((item) => item.id !== plan.id);
  } catch (error) {
    console.error(error);
    toast.add({ severity: "error", summary: "删除失败", detail: "无法停用计划。", life: 4000 });
  }
}

function stateColor(state: string) {
  if (state === "success") return "success";
  if (["failed", "uncertain"].includes(state)) return "error";
  if (["pending", "running"].includes(state)) return "warning";
  return "info";
}

function stateLabel(state: string) {
  return ({ pending: "排队中", running: "执行中", success: "成功", partial: "部分成功", failed: "失败", skipped: "全部跳过", uncertain: "结果不确定", cancelled: "已取消" } as Record<string, string>)[state] || state;
}

function groupName(id: number) {
  return groups.value.find((group) => group.id === id)?.name || String(id);
}

function startPolling(batchId: string) {
  stopPolling();
  pollTimer = window.setInterval(async () => {
    try {
      const batch = await getImagePushBatch(batchId);
      activeBatch.value = batch;
      if (!["pending", "running"].includes(batch.state)) {
        stopPolling();
        await loadBatches();
      }
    } catch (error) {
      console.error(error);
      stopPolling();
    }
  }, 2000);
}

function stopPolling() {
  if (pollTimer !== null) window.clearInterval(pollTimer);
  pollTimer = null;
}

onMounted(async () => {
  await Promise.all([loadGroups(), loadPlans(), loadBatches()]);
});
onUnmounted(stopPolling);
</script>

<template>
  <section class="d-flex flex-column ga-4">
    <header>
      <h1 class="text-h4 font-weight-bold ma-0">图片推送</h1>
      <p class="text-body-2 text-medium-emphasis mt-2 mb-0">向一个群、多个群或当前所有登记群发送图库图片，并管理自动推送计划。</p>
    </header>

    <VCard>
      <VCardTitle>立即推送</VCardTitle>
      <VCardText class="d-flex flex-column ga-3">
        <VRow>
          <VCol cols="12" md="4">
            <VSelect v-model="selectedScope" label="目标范围" :items="[{ title: '选择群组', value: 'selected' }, { title: '所有群（每次执行动态取当前全量）', value: 'all' }]" @update:model-value="syncMappingKeys" />
          </VCol>
          <VCol v-if="selectedScope === 'selected'" cols="12" md="8">
            <VSelect v-model="selectedGroups" label="群组（可多选）" :items="groupOptions" multiple chips :loading="groupsLoading" @update:model-value="syncMappingKeys" />
          </VCol>
          <VCol cols="12" md="6"><VSelect v-model="mode" label="图片分配方式" :items="modeOptions" @update:model-value="syncMappingKeys" /></VCol>
          <VCol v-if="mode === 'fixed_same'" cols="12" md="6"><VTextField v-model="pid" label="PID[:页码]" placeholder="12345678 或 12345678:2" /></VCol>
        </VRow>
        <VAlert v-if="mode === 'random_same'" density="compact" variant="tonal" type="info">随机相同会按所有可发送群的最严格图片限制抽取一张。</VAlert>
        <VAlert v-if="selectedScope === 'all' && mode === 'fixed_different'" density="compact" variant="tonal" type="warning">动态全量下，后来新增且没有映射的群会在批次中跳过并告警。</VAlert>
        <div v-if="mode === 'fixed_different'" class="d-flex flex-column ga-2">
          <div class="text-subtitle-2">逐群 PID 映射（省略页码时随机页面）</div>
          <VRow v-for="group in mappingGroups" :key="group.id" dense>
            <VCol cols="12" md="5" class="d-flex align-center text-body-2">{{ group.name || '未命名群组' }}（{{ group.id }}）</VCol>
            <VCol cols="12" md="7"><VTextField v-model="pidByGroup[String(group.id)]" density="compact" hide-details placeholder="PID[:页码]" /></VCol>
          </VRow>
          <VAlert v-if="!mappingGroups.length" density="compact" variant="tonal" type="info">先选择目标群组后填写映射。</VAlert>
        </div>
        <VBtn prepend-icon="mdi-send" :loading="manualBusy" @click="submitManual">立即推送</VBtn>
      </VCardText>
    </VCard>

    <VCard>
      <VCardTitle>自动推送计划</VCardTitle>
      <VCardText class="d-flex flex-column ga-3">
        <VTextField v-model="planName" label="计划名称" />
        <VRow>
          <VCol cols="12" md="4"><VSelect v-model="repeat" label="重复方式" :items="repeatOptions" /></VCol>
          <VCol cols="12" md="4"><VTextField v-model="dueAt" type="datetime-local" label="首次执行时间（本机时间）" /></VCol>
          <VCol v-if="repeat === 'interval'" cols="12" md="4"><VNumberInput v-model="intervalSeconds" :min="60" :max="2592000" label="间隔秒数" /></VCol>
          <VCol cols="12" md="4"><VTextField v-model="timezone" label="计划时区" /></VCol>
        </VRow>
        <VAlert density="compact" variant="tonal" type="info">自动计划沿用立即推送的目标和图片分配设置；手动与自动批次共用队列。</VAlert>
        <VBtn prepend-icon="mdi-calendar-plus" :loading="planBusy" @click="submitPlan">保存计划</VBtn>
      </VCardText>
    </VCard>

    <VCard v-if="activeBatch">
      <VCardTitle class="d-flex align-center ga-2">当前批次 {{ activeBatch.id }} <VChip size="small" :color="stateColor(activeBatch.state)">{{ stateLabel(activeBatch.state) }}</VChip></VCardTitle>
      <VCardText>
        <div class="d-flex flex-wrap ga-3 text-body-2 mb-3">
          <span>总数 {{ activeBatch.summary.total ?? activeBatch.deliveries?.length ?? 0 }}</span>
          <span>成功 {{ activeBatch.summary.success ?? 0 }}</span>
          <span>跳过 {{ activeBatch.summary.skipped ?? 0 }}</span>
          <span>失败 {{ activeBatch.summary.failed ?? 0 }}</span>
          <span>不确定 {{ activeBatch.summary.uncertain ?? 0 }}</span>
        </div>
        <VTable v-if="activeBatch.deliveries?.length" density="comfortable"><thead><tr><th>群组</th><th>图片</th><th>状态</th><th>原因</th></tr></thead><tbody><tr v-for="row in activeBatch.deliveries" :key="row.id"><td>{{ groupName(row.group_id) }}（{{ row.group_id }}）</td><td>{{ row.pixiv_id || '-' }}<span v-if="row.page !== null"> · 第 {{ row.page + 1 }} 页</span></td><td><VChip size="small" :color="stateColor(row.state)">{{ stateLabel(row.state) }}</VChip></td><td>{{ row.reason || '-' }}</td></tr></tbody></VTable>
      </VCardText>
    </VCard>

    <VCard>
      <VCardTitle>计划列表</VCardTitle>
      <VCardText><VTable density="comfortable"><thead><tr><th>名称</th><th>计划</th><th>目标/模式</th><th>下次执行</th><th>状态</th><th>操作</th></tr></thead><tbody><tr v-for="plan in plans" :key="plan.id"><td>{{ plan.name }}</td><td>{{ plan.repeat }} · {{ plan.timezone }}</td><td>{{ plan.target_scope }} · {{ plan.mode }}</td><td>{{ new Date(plan.next_run_at).toLocaleString() }}</td><td class="d-flex flex-column align-start ga-1"><VChip size="small" :color="plan.enabled ? 'success' : 'secondary'">{{ plan.enabled ? '启用' : '停用' }}</VChip><span v-if="plan.latest_batch_state" class="text-caption text-medium-emphasis">最近批次：{{ stateLabel(plan.latest_batch_state) }}</span></td><td class="d-flex ga-1"><VBtn size="small" variant="text" @click="togglePlan(plan)">{{ plan.enabled ? '暂停' : '恢复' }}</VBtn><VBtn size="small" variant="text" @click="runPlan(plan)">立即执行</VBtn><VBtn size="small" color="error" variant="text" @click="removePlan(plan)">删除</VBtn></td></tr><tr v-if="!plans.length"><td colspan="6" class="text-center text-medium-emphasis">暂无计划。</td></tr></tbody></VTable></VCardText>
    </VCard>

    <VCard>
      <VCardTitle>批次历史</VCardTitle>
      <VCardText><VTable density="comfortable"><thead><tr><th>批次</th><th>来源</th><th>创建时间</th><th>状态</th><th>汇总</th></tr></thead><tbody><tr v-for="batch in batches" :key="batch.id" @click="activeBatch = batch; startPolling(batch.id)"><td>{{ batch.id }}</td><td>{{ batch.trigger === 'auto' ? '自动' : '手动' }}</td><td>{{ new Date(batch.created_at).toLocaleString() }}</td><td><VChip size="small" :color="stateColor(batch.state)">{{ stateLabel(batch.state) }}</VChip></td><td>{{ batch.result || '-' }}</td></tr><tr v-if="!batches.length"><td colspan="5" class="text-center text-medium-emphasis">暂无批次。</td></tr></tbody></VTable></VCardText>
    </VCard>
  </section>
</template>
