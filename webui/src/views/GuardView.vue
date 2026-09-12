<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { listAllGroups, type GroupListItem } from "@/services/api";
import type { DataTableHeader, DataTableSortItem } from "vuetify";
import {
  guardApi,
  type GuardPolicy,
  type GuardCategory,
  type GuardRule,
  type GuardContent,
  type GuardRecord,
  type GuardMember,
  type GuardAction,
  type GuardActionResult,
  type GuardReview,
  type GuardPage,
  type GuardEvent,
  type GuardStats,
  type AIConfig,
  type GuardTask,
  type ReviewDecision,
  type GroupMemberListItem,
  type GroupMemberListResponse,
} from "@/services/guard-api";
import {
  changedGuardPolicy,
  cloneGuardPolicy,
} from "@/utils/guard-policy";
import { shouldRetainActionRequest } from "@/utils/guard-action";
import { createRequestId } from "@/utils/request-id";
import { useFeedback } from "@/composables/feedback";

const route = useRoute();
const router = useRouter();
const { confirm } = useFeedback();
const props = withDefaults(
  defineProps<{
    embedded?: boolean;
    section?: "overview" | "directory" | "audit";
    groupId?: number | null;
  }>(),
  { embedded: false, section: undefined, groupId: null },
);
function parseRouteGroupId(value: unknown): number {
  if (typeof value !== "string") return 0;
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) && parsed < 0 ? parsed : 0;
}
const initialGroupId = props.groupId ?? parseRouteGroupId(route.params.id);
const groupId = ref(initialGroupId);
const selectedGroupId = ref<number | null>(initialGroupId || null);
const knownGroups = ref<GroupListItem[]>([]);
const groupsLoading = ref(false);
interface GroupOption {
  id: number;
  title: string;
}
const groupOptions = computed<GroupOption[]>(() => {
  const options = knownGroups.value.map((group) => ({
    id: group.id,
    title: `${group.name || "未命名群组"}（${group.id}）`,
  }));
  if (
    selectedGroupId.value !== null &&
    !options.some((option) => option.id === selectedGroupId.value)
  ) {
    options.unshift({
      id: selectedGroupId.value,
      title: `当前链接群组（${selectedGroupId.value}）`,
    });
  }
  return options;
});
const loading = ref(false),
  busy = ref(false),
  error = ref(""),
  groupListError = ref(""),
  success = ref(""),
  tab = ref(props.section === "directory" ? "directory" : props.section === "audit" ? "reviews" : "overview");
const policy = ref<GuardPolicy | null>(null);
const policySnapshot = ref<GuardPolicy | null>(null);
const permissions = ref<Record<string, unknown>>({});
const rules = ref<GuardRecord<GuardRule>[]>([]),
  legacy = ref<{ id: number; pattern: string; is_regex: boolean }[]>([]);
const contents = ref<Record<string, GuardRecord<GuardContent>[]>>({});
const reviewPage = ref(1),
  logPage = ref(1),
  taskPage = ref(1),
  logStatus = ref("");
const reviews = ref<GuardPage<GuardRecord<GuardReview>> | null>(null),
  logs = ref<GuardPage<GuardEvent> | null>(null),
  tasks = ref<GuardPage<GuardTask> | null>(null);
const stats = ref<GuardStats | null>(null),
  member = ref<GuardMember | null>(null),
  actionResult = ref<GuardActionResult | null>(null);
const memberList = ref<GroupMemberListResponse | null>(null);
const memberListLoading = ref(false);
const memberListPage = ref(1);
const memberListPageSize = ref(20);
const memberListSort = ref<ReadonlyArray<DataTableSortItem>>([
  { key: "last_activity", order: "desc" },
]);
const memberListFilters = reactive<{
  q: string;
  role: "admin" | "member" | null;
  state: "warned" | "restricted" | "exempt" | null;
}>({ q: "", role: null, state: null });
const selectedMemberRow = ref<GroupMemberListItem | null>(null);
const memberDrawer = ref(false);
let memberDetailVersion = 0;
const userId = ref<number | null>(null),
  messageId = ref<number | null>(null),
  endMessageId = ref<number | null>(null);
const action = ref<GuardAction>("delete"),
  actionReason = ref("管理员操作"),
  actionMinutes = ref(60);
const ruleName = ref("");
const ruleForm = reactive<GuardRule>({
  kind: "keyword",
  pattern: "",
  case_sensitive: false,
  action: "delete_warn",
  enabled: true,
});
const contentForm = reactive<GuardContent>({
  kind: "note",
  name: "",
  text: "",
  enabled: true,
  repeat: "once",
  timezone: "Asia/Shanghai",
});
const dueAt = ref("");
const aiConfig = ref<AIConfig>({
    base_url: "",
    text_model: "",
    vision_model: "",
    timeout: 20,
    concurrency: 2,
  }),
  apiKey = ref("");
const categories: Record<
  GuardCategory,
  { title: string; fields: (keyof GuardPolicy)[] }
> = {
  join: {
    title: "入群管理",
    fields: [
      "bot_join_approval_enabled",
      "verification_enabled",
      "verification_mode",
      "verification_timeout",
      "verification_message",
      "kick_on_timeout",
      "join_auto_approve",
      "join_requests_enabled",
      "raid_enabled",
      "raid_window",
      "raid_limit",
      "raid_duration",
    ],
  },
  rules: {
    title: "规则审核",
    fields: [
      "bot_moderation_enabled",
      "keyword_filter_enabled",
      "rules_enabled",
      "domain_allowlist",
      "flood_enabled",
      "flood_window",
      "flood_limit",
      "repeat_window",
      "repeat_limit",
    ],
  },
  ai: {
    title: "AI 审核",
    fields: [
      "ai_spam",
      "ai_abuse",
      "ai_images",
      "ai_auto_threshold",
      "ai_review_threshold",
      "ai_daily_limit",
    ],
  },
  members: {
    title: "消息高级操作",
    fields: ["warning_limit", "warning_days", "mute_seconds"],
  },
  content: {
    title: "群运营",
    fields: [
      "rules_text",
      "welcome_enabled",
      "welcome_text",
      "goodbye_enabled",
      "goodbye_text",
      "replies_enabled",
      "clean_service_messages",
      "timezone",
      "log_days",
    ],
  },
};
const labels: Record<keyof GuardPolicy, string> = {
  bot_join_approval_enabled: "机器人入群需管理员批准",
  bot_moderation_enabled: "对机器人启用违规检测",
  verification_enabled: "启用入群验证",
  verification_mode: "验证方式",
  verification_timeout: "验证超时（秒）",
  verification_message: "验证提示（留空使用默认）",
  kick_on_timeout: "超时移出群组",
  keyword_filter_enabled: "启用原有关键词过滤",
  join_auto_approve: "自动批准入群申请",
  join_requests_enabled: "启用入群申请处理",
  rules_enabled: "启用规则审核",
  domain_allowlist: "域名白名单（逗号分隔）",
  flood_enabled: "启用反刷屏",
  flood_window: "刷屏统计窗口（秒）",
  flood_limit: "窗口内允许消息数",
  repeat_window: "重复消息统计窗口（秒）",
  repeat_limit: "重复消息触发次数",
  raid_enabled: "启用防突袭",
  raid_window: "入群统计窗口（秒）",
  raid_limit: "入群触发人数",
  raid_duration: "保护时长（秒）",
  warning_limit: "警告触发禁言次数",
  warning_days: "警告有效天数",
  mute_seconds: "默认禁言时长（秒）",
  log_days: "日志保存天数",
  welcome_enabled: "启用欢迎语",
  welcome_text: "欢迎语",
  goodbye_enabled: "启用离群提示",
  goodbye_text: "离群提示",
  rules_text: "群规",
  replies_enabled: "启用关键词自动回复",
  clean_service_messages: "清理入群和离群消息",
  ai_spam: "广告诈骗与引流审核",
  ai_abuse: "辱骂与仇恨审核",
  ai_images: "色情与暴力图片审核",
  ai_auto_threshold: "自动处罚模型评分阈值",
  ai_review_threshold: "人工复核模型评分阈值",
  ai_daily_limit: "每日 AI 调用上限",
  timezone: "群时区",
};
const activeCategory = computed(() => categories[tab.value as GuardCategory]);
const numberFields = new Set([
  "verification_timeout",
  "flood_window",
  "flood_limit",
  "repeat_window",
  "repeat_limit",
  "raid_window",
  "raid_limit",
  "raid_duration",
  "warning_limit",
  "warning_days",
  "mute_seconds",
  "log_days",
  "ai_auto_threshold",
  "ai_review_threshold",
  "ai_daily_limit",
]);
const textFields = new Set([
  "verification_message",
  "welcome_text",
  "goodbye_text",
  "rules_text",
]);
const messageActions = new Set(["delete", "pin", "unpin", "purge"]);
function displayValue(key: keyof GuardPolicy) {
  const value = policy.value?.[key];
  return Array.isArray(value) ? value.join(", ") : String(value ?? "");
}
function setField(key: keyof GuardPolicy, value: unknown) {
  if (!policy.value) return;
  const converted =
    key === "domain_allowlist"
      ? String(value)
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean)
      : numberFields.has(key)
        ? Number(value)
        : value;
  Object.assign(policy.value, { [key]: converted });
}
function detailError(e: unknown): string {
  const response = e as {
    response?: {
      data?: {
        error?: { message?: string; fields?: Record<string, string[]> };
        detail?: string;
      };
    };
    message?: string;
  };
  const fields = response.response?.data?.error?.fields;
  if (fields)
    return (
      "请检查以下配置：" +
      Object.keys(fields)
        .map((key) => labels[key as keyof GuardPolicy] || key)
        .join("、")
    );
  return (
    response.response?.data?.error?.message ||
    response.response?.data?.detail ||
    response.message ||
    "操作失败"
  );
}
async function run(fn: () => Promise<unknown>, message = "已保存") {
  busy.value = true;
  error.value = "";
  success.value = "";
  try {
    await fn();
    success.value = message;
  } catch (e) {
    error.value = detailError(e);
  } finally {
    busy.value = false;
  }
}
let loadVersion = 0;
async function load() {
  const id = selectedGroupId.value;
  if (id === null || !Number.isSafeInteger(id) || id >= 0) {
    error.value = "请选择有效的群组";
    return;
  }
  const version = ++loadVersion;
  loading.value = true;
  error.value = "";
  success.value = "";
  policy.value = null;
  policySnapshot.value = null;
  member.value = null;
  actionResult.value = null;
  memberList.value = null;
  selectedMemberRow.value = null;
  memberDrawer.value = false;
  ++memberDetailVersion;
  try {
    const values = await Promise.all([
      guardApi.policy(id),
      guardApi.rules(id),
      guardApi.contents(id),
      guardApi.reviews(id, 1),
      guardApi.logs(id, 1),
      guardApi.stats(id),
      guardApi.ai(),
      guardApi.tasks(id),
    ]);
    if (version !== loadVersion) return;
    groupId.value = id;
    [
      policy.value,
      ,
      contents.value,
      reviews.value,
      logs.value,
      stats.value,
      aiConfig.value,
      tasks.value,
    ] = values;
    policySnapshot.value = cloneGuardPolicy(policy.value!);
    // New scheduled announcements should follow the group's configured zone.
    contentForm.timezone = policy.value!.timezone;
    rules.value = values[1].items;
    legacy.value = values[1].legacy;
    reviewPage.value = 1;
    logPage.value = 1;
    taskPage.value = 1;
    const loadedPermissions = await guardApi
      .permissions(id)
      .catch((e) => ({ error: detailError(e) }));
    if (version !== loadVersion) return;
    permissions.value = loadedPermissions;
    if (tab.value === "directory") await loadMemberList();
  } catch (e) {
    if (version === loadVersion) error.value = detailError(e);
  } finally {
    if (version === loadVersion) loading.value = false;
  }
}
async function loadKnownGroups() {
  groupsLoading.value = true;
  groupListError.value = "";
  try {
    knownGroups.value = await listAllGroups();
  } catch (e) {
    groupListError.value = detailError(e);
  } finally {
    groupsLoading.value = false;
  }
}

const memberHeaders: DataTableHeader<GroupMemberListItem>[] = [
  { title: "成员", key: "display_name", sortable: true },
  { title: "用户 ID", key: "id", sortable: true },
  { title: "角色", key: "role", sortable: false },
  { title: "状态", key: "state", sortable: false },
  { title: "消息", key: "message_count", sortable: true },
  { title: "最后活跃", key: "last_activity", sortable: true },
  { title: "操作", key: "actions", sortable: false },
];
let memberListVersion = 0;
async function loadMemberList() {
  const id = groupId.value;
  if (!id || id >= 0) return;
  const version = ++memberListVersion;
  memberListLoading.value = true;
  try {
    const sort = memberListSort.value[0];
    const response = await guardApi.members(id, {
      q: memberListFilters.q || undefined,
      role: memberListFilters.role || undefined,
      state: memberListFilters.state || undefined,
      page: memberListPage.value,
      page_size: memberListPageSize.value,
      sort_by:
        sort?.key === "id" ||
        sort?.key === "display_name" ||
        sort?.key === "message_count" ||
        sort?.key === "last_activity"
          ? sort.key
          : "last_activity",
      sort_order: sort?.order === "asc" ? "asc" : "desc",
    });
    if (version !== memberListVersion) return;
    memberList.value = response;
    if (selectedMemberRow.value) {
      const refreshed = response.items.find(
        (item) => item.user_id === selectedMemberRow.value!.user_id,
      );
      if (refreshed) selectedMemberRow.value = refreshed;
    }
  } catch (e) {
    if (version === memberListVersion) error.value = detailError(e);
  } finally {
    if (version === memberListVersion) memberListLoading.value = false;
  }
}
function searchMembers() {
  memberListPage.value = 1;
  void loadMemberList();
}
function onMemberOptions(options: {
  page: number;
  itemsPerPage: number;
  sortBy: ReadonlyArray<DataTableSortItem>;
}) {
  memberListPage.value = options.page;
  memberListPageSize.value = options.itemsPerPage;
  memberListSort.value = options.sortBy;
  void loadMemberList();
}
function onMemberRowClick(_: unknown, row: { item: GroupMemberListItem }) {
  openMember(row.item);
}
async function openMember(row: GroupMemberListItem) {
  const version = ++memberDetailVersion;
  selectedMemberRow.value = row;
  memberDrawer.value = true;
  member.value = null;
  try {
    const value = await guardApi.member(groupId.value, row.user_id);
    if (version === memberDetailVersion) member.value = value;
  } catch (e) {
    if (version === memberDetailVersion) error.value = detailError(e);
  }
}
async function openMemberAction(row: GroupMemberListItem, next: GuardAction) {
  await openMember(row);
  if (
    member.value?.user_id === row.user_id &&
    selectedMemberRow.value?.user_id === row.user_id
  ) {
    runMemberAction(next);
  }
}
async function toggleSelectedMemberExempt() {
  if (!member.value) return;
  await run(async () => {
    await guardApi.exempt(
      groupId.value,
      member.value!.user_id,
      !member.value!.exempt,
    );
    member.value = await guardApi.member(groupId.value, member.value!.user_id);
    await loadMemberList();
  }, member.value.exempt ? "已取消豁免" : "已设置豁免");
}
function runMemberAction(next: GuardAction) {
  if (!selectedMemberRow.value) return;
  action.value = next;
  userId.value = selectedMemberRow.value.user_id;
  // Warning and mute actions need an intentional reason (and mute needs a
  // duration), so leave the drawer open for the operator to review/edit the
  // form before sending the request.  The other member actions can execute
  // immediately, with destructive actions still guarded by confirmation.
  if (next === "warn" || next === "mute") return;
  if (next === "kick" || next === "ban") {
    confirm.require({
      header: next === "ban" ? "确认封禁成员" : "确认移出成员",
      message: `将对成员 ${selectedMemberRow.value.user_id} 执行${next === "ban" ? "封禁" : "移出"}，是否继续？`,
      icon: "mdi-alert",
      acceptLabel: "继续",
      accept: () => void perform(),
    });
    return;
  }
  void perform();
}
function selectGroup(value: number | null) {
  selectedGroupId.value = value;
  if (value === null) {
    void router.push({ name: "groups" });
  } else if (parseRouteGroupId(route.params.id) !== value) {
    void router.push({ name: "group-management", params: { id: String(value) } });
  }
}
async function savePolicy() {
  await run(async () => {
    policy.value = await guardApi.savePolicy(
      groupId.value,
      changedGuardPolicy(policy.value!, policySnapshot.value!),
    );
    policySnapshot.value = cloneGuardPolicy(policy.value);
  });
}
async function refreshRules() {
  const value = await guardApi.rules(groupId.value);
  rules.value = value.items;
  legacy.value = value.legacy;
}
async function saveRule() {
  await run(async () => {
    if (!ruleName.value.trim()) throw new Error("请填写规则名称");
    await guardApi.saveRule(groupId.value, ruleName.value.trim(), ruleForm);
    await refreshRules();
  });
}
async function saveContent() {
  await run(async () => {
    const value = { ...contentForm };
    if (value.kind === "announcement") {
      if (!dueAt.value || !/[zZ]|[+-]\d{2}:\d{2}$/.test(dueAt.value))
        throw new Error("时间必须包含时区，例如 2026-09-07T09:00:00+08:00");
      value.due_at = new Date(dueAt.value).toISOString();
    }
    await guardApi.saveContent(groupId.value, value);
    contents.value = await guardApi.contents(groupId.value);
    tasks.value = await guardApi.tasks(groupId.value);
  });
}
function editContent(row: GuardRecord<GuardContent>) {
  Object.assign(contentForm, row.data);
  dueAt.value = row.data.due_at || "";
}
let pendingAction: { fingerprint: string; requestId: string } | null = null;
async function perform() {
  await run(async () => {
    if ((action.value === "warn" || action.value === "mute") && !actionReason.value.trim())
      throw new Error("请填写操作理由");
    if (action.value === "mute" && (!Number.isFinite(actionMinutes.value) || actionMinutes.value <= 0))
      throw new Error("禁言时长必须大于 0 分钟");
    const payload = {
      action: action.value,
      user_id: messageActions.has(action.value)
        ? undefined
        : userId.value || undefined,
      message_id: messageId.value || undefined,
      end_message_id:
        action.value === "purge" ? endMessageId.value || undefined : undefined,
      reason: actionReason.value,
      duration: actionMinutes.value * 60,
    };
    const fingerprint = JSON.stringify([groupId.value, payload]);
    if (pendingAction?.fingerprint !== fingerprint)
      pendingAction = { fingerprint, requestId: createRequestId() };
    actionResult.value = await guardApi.action(groupId.value, {
      ...payload,
      request_id: pendingAction!.requestId,
    });
    if (actionResult.value.status !== "success") {
      if (!shouldRetainActionRequest(actionResult.value.status))
        pendingAction = null;
      throw new Error(
        `操作${actionResult.value.status}：${JSON.stringify(actionResult.value.data)}`,
      );
    }
    pendingAction = null;
    if (userId.value)
      member.value = await guardApi.member(groupId.value, userId.value);
    if (tab.value === "directory") await loadMemberList();
  }, "操作成功");
}
async function decide(row: GuardRecord<GuardReview>, decision: ReviewDecision) {
  await run(async () => {
    const result = await guardApi.decide(groupId.value, row.id, decision);
    reviews.value = await guardApi.reviews(groupId.value, reviewPage.value);
    if (result.data.state !== "resolved")
      throw new Error(`复核处理失败：${JSON.stringify(result.data.results)}`);
  }, "复核已处理");
}
async function saveAI() {
  await run(async () => {
    const { has_api_key, ...value } = aiConfig.value;
    aiConfig.value = await guardApi.saveAI({
      ...value,
      api_key: apiKey.value || null,
    });
    apiKey.value = "";
  });
}
watch(reviewPage, (p) => {
  if (policy.value)
    void run(async () => {
      reviews.value = await guardApi.reviews(groupId.value, p);
    }, "");
});
watch([logPage, logStatus], () => {
  if (policy.value)
    void run(async () => {
      logs.value = await guardApi.logs(
        groupId.value,
        logPage.value,
        logStatus.value,
      );
    }, "");
});
watch(taskPage, (p) => {
  if (policy.value)
    void run(async () => {
      tasks.value = await guardApi.tasks(groupId.value, p);
    }, "");
});
watch(tab, (value) => {
  if (value === "directory" && policy.value) void loadMemberList();
});
onMounted(async () => {
  if (!props.embedded) await loadKnownGroups();
  if (groupId.value) void load();
});
watch(
  () => route.params.id,
  (id) => {
    const parsed = parseRouteGroupId(id);
    selectedGroupId.value = parsed || null;
    if (parsed) void load();
    else {
      ++loadVersion;
      groupId.value = 0;
      policy.value = null;
    }
  },
);
</script>

<template>
  <div class="d-flex flex-column ga-5">
    <div v-if="!props.embedded">
      <h1 class="text-h4 font-weight-bold">智能群管</h1>
      <p class="text-body-2 text-medium-emphasis mt-2">
        按群配置审核、入群和运营。新增自动功能需要手动启用。
      </p>
    </div>
    <VCard v-if="!props.embedded"
      ><VCardText class="d-flex ga-3 align-center flex-wrap"
        ><VAutocomplete
          id="guard-group-select"
          :model-value="selectedGroupId"
          :items="groupOptions"
          item-title="title"
          item-value="id"
          label="选择已知群组"
          placeholder="按名称或群 ID 搜索"
          clearable
          hide-details
          :loading="groupsLoading"
          :disabled="busy || loading"
          @update:model-value="selectGroup"
        /><VChip v-if="policy" color="primary"
          >当前群：{{ groupOptions.find((item) => item.id === groupId)?.title || groupId }}</VChip
        ></VCardText
      ></VCard
    >
    <VAlert v-if="error" type="error" closable @click:close="error = ''">{{
      error
    }}</VAlert>
    <VAlert
      v-if="groupListError"
      type="error"
      closable
      @click:close="groupListError = ''"
      >无法加载已知群组：{{ groupListError }}</VAlert
    >
    <VAlert
      v-if="success"
      type="success"
      closable
      @click:close="success = ''"
      >{{ success }}</VAlert
    >
    <template v-if="policy && !loading">
      <VTabs v-if="props.section !== 'directory'" v-model="tab" show-arrows>
        <template v-if="props.section === 'audit'">
          <VTab value="reviews">举报复核</VTab>
          <VTab value="logs">日志与任务</VTab>
        </template>
        <template v-else-if="props.section === 'overview'">
          <VTab value="overview">概览</VTab>
        </template>
        <template v-else>
          <VTab value="overview">概览</VTab>
          <VTab v-for="(category, key) in categories" :key="key" :value="key">{{ category.title }}</VTab>
          <VTab value="reviews">举报复核</VTab>
          <VTab value="logs">日志与任务</VTab>
        </template>
      </VTabs>
      <VCard v-if="tab === 'overview'"
        ><VCardTitle>最近 30 天</VCardTitle
        ><VCardText class="d-flex flex-column ga-4">
          <div class="d-flex ga-2 flex-wrap">
            <VChip v-for="(count, name) in stats?.actions" :key="name"
              >{{ name }}：{{ count }}</VChip
            ><VChip>AI token 用量：{{ stats?.total_tokens || 0 }}</VChip>
          </div>
          <VAlert type="info" variant="tonal"
            >Web 操作由部署管理员执行，访问控制沿用外部网关。群内操作始终校验
            Telegram 管理员身份。</VAlert
          >
          <div>
            <h3 class="text-subtitle-1">机器人权限</h3>
            <p v-for="(value, key) in permissions" :key="key">
              {{ key }}：{{ value }}
            </p>
          </div>
          <VTable
            ><thead>
              <tr>
                <th>日期</th>
                <th>审核与操作次数</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="day in stats?.days" :key="day.date">
                <td>{{ day.date }}</td>
                <td>
                  {{
                    Object.entries(day.counts)
                      .map(([k, v]) => `${k}: ${v}`)
                      .join(" · ")
                  }}
                </td>
              </tr>
            </tbody></VTable
          >
        </VCardText></VCard
      >
      <VCard v-if="activeCategory"
        ><VCardTitle>{{ activeCategory.title }}设置</VCardTitle
        ><VCardText
          ><VRow>
            <VCol
              v-for="field in activeCategory.fields"
              :key="field"
              cols="12"
              :md="textFields.has(field) ? 12 : 6"
            >
              <VSwitch
                v-if="typeof policy[field] === 'boolean'"
                :model-value="Boolean(policy[field])"
                :label="labels[field]"
                color="primary"
                hide-details
                @update:model-value="setField(field, $event)"
              />
              <VSelect
                v-else-if="field === 'verification_mode'"
                :model-value="policy.verification_mode"
                :items="[
                  { title: '按钮验证', value: 'button' },
                  { title: '算术选择题', value: 'math' },
                ]"
                :label="labels[field]"
                @update:model-value="setField(field, $event)"
              />
              <VTextarea
                v-else-if="textFields.has(field)"
                :model-value="displayValue(field)"
                :label="labels[field]"
                rows="3"
                auto-grow
                @update:model-value="setField(field, $event)"
              />
              <VTextField
                v-else
                :model-value="displayValue(field)"
                :label="labels[field]"
                :type="numberFields.has(field) ? 'number' : 'text'"
                @update:model-value="setField(field, $event)"
              />
            </VCol>
          </VRow>
          <p v-if="tab === 'content' || tab === 'join'" class="text-caption">
            模板支持 {user}、{chat}、{timeout}；内容以纯文本发送。
          </p>
          <VBtn :loading="busy" @click="savePolicy"
            >保存群级设置</VBtn
          ></VCardText
        ></VCard
      >
      <VCard v-if="tab === 'rules'"
        ><VCardTitle>审核规则</VCardTitle
        ><VCardText class="d-flex flex-column ga-3">
          <VRow
            ><VCol cols="12" md="4"
              ><VTextField v-model="ruleName" label="规则名称" /></VCol
            ><VCol cols="12" md="4"
              ><VSelect
                v-model="ruleForm.kind"
                :items="[
                  'keyword',
                  'regex',
                  'link',
                  'invite',
                  'forward',
                  'media',
                ]"
                label="规则类型" /></VCol
            ><VCol cols="12" md="4"
              ><VSelect
                v-model="ruleForm.action"
                :items="[
                  { title: '删除并警告', value: 'delete_warn' },
                  { title: '仅删除', value: 'delete' },
                ]"
                label="处理方式" /></VCol
          ></VRow>
          <VTextField
            v-model="ruleForm.pattern"
            label="关键词 / 正则 / 媒体类型"
            hint="media 支持 photo、video、audio、voice、document、sticker、animation、poll、video_note、album"
            persistent-hint
          />
          <div class="d-flex ga-4">
            <VSwitch
              v-model="ruleForm.enabled"
              label="启用此规则"
              color="primary"
            /><VSwitch
              v-model="ruleForm.case_sensitive"
              label="区分大小写"
              color="primary"
            />
          </div>
          <VBtn :loading="busy" @click="saveRule">保存规则</VBtn>
          <VTable
            ><thead>
              <tr>
                <th>名称</th>
                <th>类型 / 内容</th>
                <th>状态</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in rules" :key="row.id">
                <td>{{ row.key }}</td>
                <td>{{ row.data.kind }} / {{ row.data.pattern }}</td>
                <td>{{ row.enabled ? "启用" : "停用" }}</td>
                <td>
                  <VBtn
                    variant="text"
                    @click="
                      ruleName = row.key;
                      Object.assign(ruleForm, row.data);
                    "
                    >编辑</VBtn
                  ><VBtn
                    variant="text"
                    color="error"
                    :disabled="busy"
                    @click="
                      run(async () => {
                        await guardApi.deleteRule(groupId, row.key);
                        await refreshRules();
                      }, '已删除')
                    "
                    >删除</VBtn
                  >
                </td>
              </tr>
            </tbody></VTable
          >
          <p v-if="!rules.length">暂无新规则。</p>
          <h3 v-if="legacy.length" class="text-subtitle-1">
            原有关键词规则（仅删除）
          </h3>
          <div v-for="row in legacy" :key="row.id">
            #{{ row.id }} {{ row.pattern }}
            <VBtn
              variant="text"
              :disabled="busy"
              @click="
                run(async () => {
                  await guardApi.deleteLegacy(groupId, row.id);
                  await refreshRules();
                }, '已删除')
              "
              >删除</VBtn
            >
          </div>
        </VCardText></VCard
      >
      <VCard v-if="tab === 'ai'"
        ><VCardTitle>模型服务（所有群共用）</VCardTitle
        ><VCardText class="d-flex flex-column ga-3">
          <VAlert type="info" variant="tonal"
            >未配置或模型异常时，仅运行规则审核。模型评分不是准确率。图片遵循群现有分级，无法判断时进入复核。</VAlert
          >
          <VTextField
            v-model="aiConfig.base_url"
            label="兼容 API 地址（通常以 /v1 结尾）"
          /><VTextField
            v-model="apiKey"
            type="password"
            autocomplete="new-password"
            label="API 密钥"
            :hint="aiConfig.has_api_key ? '已配置，留空保留原密钥' : '尚未配置'"
            persistent-hint
          />
          <VRow
            ><VCol cols="12" md="6"
              ><VTextField
                v-model="aiConfig.text_model"
                label="文本模型" /></VCol
            ><VCol cols="12" md="6"
              ><VTextField
                v-model="aiConfig.vision_model"
                label="视觉模型" /></VCol
            ><VCol cols="12" md="6"
              ><VTextField
                v-model.number="aiConfig.timeout"
                type="number"
                label="请求超时（秒）" /></VCol
            ><VCol cols="12" md="6"
              ><VTextField
                v-model.number="aiConfig.concurrency"
                type="number"
                label="全局并发" /></VCol
          ></VRow>
          <VBtn :loading="busy" @click="saveAI">保存模型服务</VBtn
          ><VBtn
            variant="text"
            :disabled="busy"
            @click="
              run(async () => {
                const { has_api_key, ...value } = aiConfig;
                aiConfig = await guardApi.saveAI({ ...value, api_key: '' });
              }, '密钥已清除')
            "
            >清除密钥</VBtn
          >
        </VCardText></VCard
      >
      <VCard v-if="tab === 'members'"
        ><VCardTitle>消息级高级操作</VCardTitle
        ><VCardText class="d-flex flex-column ga-3">
          <VAlert type="info" variant="tonal" density="compact">
            成员查询与单成员处罚已迁移到“群成员”目录；这里仅保留需要消息 ID 的删除、置顶和批量清理。
          </VAlert>
          <VSelect
            v-model="action"
            :items="[
              { title: '删除消息', value: 'delete' },
              { title: '置顶消息', value: 'pin' },
              { title: '取消置顶', value: 'unpin' },
              { title: '批量清理', value: 'purge' },
            ]"
            label="操作"
          />
          <VTextField
            v-if="messageActions.has(action)"
            v-model.number="messageId"
            type="number"
            label="目标消息 ID / 清理起点"
          /><VTextField
            v-if="action === 'purge'"
            v-model.number="endMessageId"
            type="number"
            label="清理终点消息 ID（最多 100 条）"
          /><VTextField v-model="actionReason" label="操作理由" />
          <VBtn color="error" :loading="busy" @click="perform"
            >执行消息操作</VBtn
          ><VAlert
            v-if="actionResult"
            :type="actionResult.status === 'success' ? 'success' : 'warning'"
            >{{ actionResult.status }} · {{ actionResult.data }}</VAlert
          >
        </VCardText></VCard
      >
      <VCard v-if="tab === 'content'"
        ><VCardTitle>自动回复、笔记与公告</VCardTitle
        ><VCardText class="d-flex flex-column ga-3">
          <VSelect
            v-model="contentForm.kind"
            :items="[
              { title: '关键词自动回复', value: 'reply' },
              { title: '命名笔记', value: 'note' },
              { title: '定时公告', value: 'announcement' },
            ]"
            label="内容类型"
          /><VTextField
            v-model="contentForm.name"
            label="名称 / 触发关键词"
          /><VTextarea v-model="contentForm.text" label="发送内容" /><VSwitch
            v-model="contentForm.enabled"
            label="启用"
            color="primary"
          />
          <template v-if="contentForm.kind === 'announcement'"
            ><VTextField
              v-model="dueAt"
              label="首次发送时间（含时区）"
              placeholder="2026-09-07T09:00:00+08:00" /><VSelect
              v-model="contentForm.repeat"
              :items="[
                { title: '单次', value: 'once' },
                { title: '每日', value: 'daily' },
                { title: '每周', value: 'weekly' },
              ]"
              label="重复" /><VTextField
              v-model="contentForm.timezone"
              label="重复计划时区"
          /></template>
          <VBtn :loading="busy" @click="saveContent">保存内容</VBtn>
          <template v-for="(rows, kind) in contents" :key="kind"
            ><h3 class="text-subtitle-1">{{ kind }}</h3>
            <div
              v-for="row in rows"
              :key="row.id"
              class="d-flex ga-2 align-center flex-wrap"
            >
              <span>{{ row.key }} · {{ row.enabled ? "启用" : "停用" }}</span
              ><VBtn variant="text" @click="editContent(row)">编辑</VBtn
              ><VBtn
                variant="text"
                color="error"
                :disabled="busy"
                @click="
                  run(async () => {
                    await guardApi.deleteContent(groupId, row.kind, row.key);
                    contents = await guardApi.contents(groupId);
                  }, '已删除')
                "
                >删除</VBtn
              >
            </div>
            <p v-if="!rows.length">暂无内容</p></template
          >
        </VCardText></VCard
      >
      <VCard v-if="tab === 'directory'" class="group-members-card">
        <VCardTitle class="d-flex align-center ga-2 flex-wrap">
          <VIcon icon="mdi-account-multiple-outline" color="primary" />
          <span>群成员</span>
          <VChip size="small" color="info">已观测 {{ memberList?.total || 0 }}</VChip>
          <VChip v-if="memberList?.telegram_member_count != null" size="small" color="secondary">
            Telegram 总数 {{ memberList.telegram_member_count }}
          </VChip>
        </VCardTitle>
        <VCardText class="d-flex flex-column ga-3">
          <VAlert type="info" variant="tonal" density="compact">
            列表来自机器人已观测记录（消息、管理员和群管事件），不代表 Telegram 普通成员的完整名单。
          </VAlert>
          <VRow class="align-end">
            <VCol cols="12" md="5">
              <VTextField
                id="group-members-search"
                v-model="memberListFilters.q"
                label="搜索成员"
                placeholder="用户 ID、用户名或显示名"
                prepend-inner-icon="mdi-magnify"
                hide-details
                @keydown.enter="searchMembers"
              />
            </VCol>
            <VCol cols="6" md="3">
              <VSelect
                id="group-members-role"
                v-model="memberListFilters.role"
                label="角色"
                :items="[
                  { title: '全部角色', value: null },
                  { title: '管理员', value: 'admin' },
                  { title: '普通成员', value: 'member' },
                ]"
                hide-details
                @update:model-value="searchMembers"
              />
            </VCol>
            <VCol cols="6" md="3">
              <VSelect
                id="group-members-state"
                v-model="memberListFilters.state"
                label="状态"
                :items="[
                  { title: '全部状态', value: null },
                  { title: '有警告', value: 'warned' },
                  { title: '受限中', value: 'restricted' },
                  { title: '已豁免', value: 'exempt' },
                ]"
                hide-details
                @update:model-value="searchMembers"
              />
            </VCol>
            <VCol cols="12" md="1" class="d-flex justify-end">
              <VBtn icon="mdi-refresh" variant="text" aria-label="刷新成员列表" :loading="memberListLoading" @click="searchMembers" />
            </VCol>
          </VRow>
          <VDataTableServer
            :headers="memberHeaders"
            :items="memberList?.items || []"
            :loading="memberListLoading"
            item-value="user_id"
            :page="memberListPage"
            :items-length="memberList?.total || 0"
            :items-per-page="memberListPageSize"
            :items-per-page-options="[20, 50, 100]"
            :sort-by="memberListSort"
            class="rounded-lg border"
            @update:options="onMemberOptions"
            @click:row="onMemberRowClick"
          >
            <template #item.display_name="{ item }">
              <div class="d-flex align-center ga-2 py-1">
                <VAvatar size="32" color="primary" variant="tonal">
                  <span class="text-caption">{{ (item.display_name || '用').slice(0, 1) }}</span>
                </VAvatar>
                <div class="d-flex flex-column">
                  <span class="font-weight-medium">{{ item.display_name || `用户 ${item.user_id}` }}</span>
                  <span class="text-caption text-medium-emphasis">
                    {{ item.username ? `@${item.username}` : '无用户名' }} · {{ item.user_id }}
                  </span>
                </div>
              </div>
            </template>
            <template #item.role="{ item }">
              <VChip size="small" :color="item.role === 'admin' ? 'primary' : 'default'">
                {{ item.role === 'admin' ? '管理员' : '成员' }}
              </VChip>
            </template>
            <template #item.id="{ item }">
              <span class="text-body-2 text-medium-emphasis">{{ item.user_id }}</span>
            </template>
            <template #item.state="{ item }">
              <div class="d-flex ga-1 flex-wrap">
                <VChip v-if="item.warning_count" size="small" color="warning">警告 {{ item.warning_count }}</VChip>
                <VChip v-if="item.restriction_active" size="small" color="error">受限</VChip>
                <VChip v-if="item.exempt" size="small" color="success">豁免</VChip>
                <span v-if="!item.warning_count && !item.restriction_active && !item.exempt" class="text-caption text-medium-emphasis">正常</span>
              </div>
            </template>
            <template #item.last_activity="{ item }">
              {{ item.last_activity ? new Date(item.last_activity).toLocaleString() : '暂无' }}
            </template>
            <template #item.actions="{ item }">
              <VMenu>
                <template #activator="{ props }">
                  <VBtn v-bind="props" icon="mdi-dots-vertical" size="small" variant="text" aria-label="成员操作" />
                </template>
                <VList density="compact">
                  <VListItem title="查看详情" @click="openMember(item)" />
                  <VListItem title="警告" @click="openMemberAction(item, 'warn')" />
                  <VListItem title="禁言" @click="openMemberAction(item, 'mute')" />
                  <VListItem title="移出" @click="openMemberAction(item, 'kick')" />
                  <VListItem title="封禁" @click="openMemberAction(item, 'ban')" />
                </VList>
              </VMenu>
            </template>
          </VDataTableServer>
          <VAlert v-if="!memberListLoading && !memberList?.items.length" type="info" variant="tonal">
            暂无符合条件的已观测成员。
          </VAlert>
        </VCardText>
      </VCard>
      <VCard v-if="tab === 'reviews'"
        ><VCardTitle>举报、机器人与 AI 复核</VCardTitle
        ><VCardText
          ><div v-for="row in reviews?.items" :key="row.id" class="mb-5">
            <div class="d-flex ga-2 align-center">
              <VChip>{{ row.data.state }}</VChip
              ><span v-if="row.data.kind === 'bot_join'">
                机器人 {{ row.data.name || "未命名" }}
                <span v-if="row.data.username">@{{ row.data.username }}</span>
                · ID {{ row.data.user_id }}
              </span><span v-else
                >成员 {{ row.data.user_id }} · 消息
                {{ row.data.message_id }}</span
              >
            </div>
            <p class="mt-2">{{ row.data.reason }}</p>
            <p v-if="row.data.confidence != null">
              模型评分：{{ row.data.confidence }}
            </p>
            <p v-if="row.data.evidence">依据：{{ row.data.evidence }}</p>
            <div v-if="row.data.state === 'pending'">
              <template v-if="row.data.kind === 'join'"
                ><VBtn
                  variant="text"
                  :disabled="busy"
                  @click="decide(row, 'approve_join')"
                  >批准入群</VBtn
                ><VBtn
                  variant="text"
                  color="error"
                  :disabled="busy"
                  @click="decide(row, 'reject_join')"
                  >拒绝</VBtn
                ></template
              ><template v-else-if="row.data.kind === 'bot_join'"
                ><VBtn
                  variant="text"
                  :disabled="busy"
                  @click="decide(row, 'approve_bot')"
                  >批准发言</VBtn
                ><VBtn
                  variant="text"
                  color="error"
                  :disabled="busy"
                  @click="decide(row, 'reject_bot')"
                  >移出机器人</VBtn
                ></template
              ><template v-else
                ><VBtn
                  variant="text"
                  color="error"
                  :disabled="busy"
                  @click="decide(row, 'punish')"
                  >删信并警告</VBtn
                ><VBtn
                  variant="text"
                  :disabled="busy"
                  @click="decide(row, 'dismiss')"
                  >忽略</VBtn
                ></template
              >
            </div>
            <div v-else-if="row.data.state === 'uncertain'">
              <VAlert type="warning" variant="tonal" class="my-2"
                >上次处理被中断，请人工核查 Telegram 实际状态后关闭。</VAlert
              ><VBtn
                variant="text"
                :disabled="busy"
                @click="decide(row, 'dismiss')"
                >确认已核查并关闭</VBtn
              >
            </div>
            <p v-if="row.data.results">{{ row.data.results }}</p>
          </div>
          <p v-if="!reviews?.items.length">暂无复核记录</p>
          <VPagination
            v-model="reviewPage"
            :length="reviews?.pages || 1" /></VCardText
      ></VCard>
      <template v-if="tab === 'logs'">
        <VCard
          ><VCardTitle>操作日志</VCardTitle
          ><VCardText
            ><VSelect
              v-model="logStatus"
              :items="[
                { title: '全部', value: '' },
                ...['success', 'failed', 'partial', 'uncertain', 'revoked'].map(
                  (value) => ({ title: value, value }),
                ),
              ]"
              label="结果筛选" /><VTable
              ><thead>
                <tr>
                  <th>时间</th>
                  <th>动作 / 来源</th>
                  <th>成员</th>
                  <th>结果与理由</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in logs?.items" :key="row.id">
                  <td>{{ row.created_at }}</td>
                  <td>{{ row.action }}<br />{{ row.source }}</td>
                  <td>{{ row.user_id }}</td>
                  <td>
                    {{ row.status }} · {{ row.reason }}
                    <details>
                      <summary>详情</summary>
                      <pre class="guard-data">{{
                        JSON.stringify(row.data, null, 2)
                      }}</pre>
                    </details>
                  </td>
                </tr>
              </tbody></VTable
            ><VPagination
              v-model="logPage"
              :length="logs?.pages || 1" /></VCardText
        ></VCard>
        <VCard
          ><VCardTitle>后台任务</VCardTitle
          ><VCardText
            ><VTable
              ><thead>
                <tr>
                  <th>类型</th>
                  <th>计划时间（UTC）</th>
                  <th>状态</th>
                  <th>结果</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="job in tasks?.items" :key="job.id">
                  <td>{{ job.kind }}</td>
                  <td>{{ job.due_at }}</td>
                  <td>{{ job.state }}</td>
                  <td>{{ job.result }}</td>
                </tr>
              </tbody></VTable
            ><VPagination
              v-model="taskPage"
              :length="tasks?.pages || 1" /></VCardText
        ></VCard>
      </template>
      <VNavigationDrawer
        v-model="memberDrawer"
        location="right"
        temporary
        width="420"
      >
        <VCard flat v-if="selectedMemberRow">
          <VCardTitle class="d-flex align-center ga-2">
            <VAvatar color="primary" variant="tonal">
              {{ (selectedMemberRow.display_name || '用').slice(0, 1) }}
            </VAvatar>
            <div class="d-flex flex-column">
              <span>{{ selectedMemberRow.display_name || `用户 ${selectedMemberRow.user_id}` }}</span>
              <span class="text-caption text-medium-emphasis">{{ selectedMemberRow.user_id }}</span>
            </div>
            <VSpacer />
            <VBtn icon="mdi-close" variant="text" aria-label="关闭成员详情" @click="memberDrawer = false" />
          </VCardTitle>
          <VCardText class="d-flex flex-column ga-3">
            <div class="d-flex ga-2 flex-wrap">
              <VChip size="small" :color="selectedMemberRow.role === 'admin' ? 'primary' : 'default'">
                {{ selectedMemberRow.role === 'admin' ? '管理员' : '成员' }}
              </VChip>
              <VChip v-if="selectedMemberRow.warning_count" size="small" color="warning">
                警告 {{ selectedMemberRow.warning_count }}
              </VChip>
              <VChip v-if="selectedMemberRow.restriction_active" size="small" color="error">受限</VChip>
              <VChip v-if="selectedMemberRow.exempt" size="small" color="success">豁免</VChip>
            </div>
            <p class="text-body-2 text-medium-emphasis mb-0">
              {{ selectedMemberRow.username ? `@${selectedMemberRow.username}` : '暂无用户名' }} · 消息 {{ selectedMemberRow.message_count }}
            </p>
            <VAlert v-if="!member" type="info" variant="tonal">正在读取成员状态…</VAlert>
            <template v-else>
              <VAlert v-if="member.verification" type="warning" variant="tonal">
                验证：{{ member.verification.state }} · {{ member.verification.result }}
              </VAlert>
              <VAlert v-if="member.restriction" type="warning" variant="tonal">
                本系统限制：{{ member.restriction.data }}
              </VAlert>
              <VAlert v-if="member.bot_approval" type="info" variant="tonal">
                机器人审批：{{ member.bot_approval.data.state || '已记录' }}
              </VAlert>
              <div v-if="member.warnings.length" class="d-flex flex-column ga-2">
                <h3 class="text-subtitle-2">有效警告</h3>
                <div v-for="warning in member.warnings" :key="warning.id" class="d-flex align-center ga-2">
                  <span class="text-body-2 flex-grow-1">{{ warning.reason || '未填写理由' }}</span>
                  <VBtn size="small" variant="text" :disabled="busy" @click="run(async () => { const r = await guardApi.revoke(groupId, warning.id); if (r.status !== 'success') throw new Error(JSON.stringify(r.data)); member = await guardApi.member(groupId, member!.user_id); await loadMemberList(); }, '已撤销警告')">撤销</VBtn>
                </div>
              </div>
              <VBtn variant="tonal" :disabled="busy" @click="toggleSelectedMemberExempt">
                {{ member.exempt ? '取消豁免' : '豁免内容和刷屏审核' }}
              </VBtn>
              <VDivider />
              <h3 class="text-subtitle-2">快捷处罚</h3>
              <div class="d-flex ga-2 flex-wrap">
                <VBtn size="small" color="warning" variant="tonal" :disabled="busy" @click="runMemberAction('warn')">警告</VBtn>
                <VBtn size="small" color="warning" variant="tonal" :disabled="busy" @click="runMemberAction('mute')">禁言</VBtn>
                <VBtn size="small" variant="outlined" :disabled="busy" @click="runMemberAction('unmute')">解除禁言</VBtn>
                <VBtn size="small" color="error" variant="tonal" :disabled="busy" @click="runMemberAction('kick')">移出</VBtn>
                <VBtn size="small" color="error" variant="tonal" :disabled="busy" @click="runMemberAction('ban')">封禁</VBtn>
                <VBtn size="small" variant="outlined" :disabled="busy" @click="runMemberAction('unban')">解除封禁</VBtn>
              </div>
              <VTextField v-if="action === 'mute'" v-model.number="actionMinutes" type="number" label="禁言分钟数" min="1" />
              <VTextField v-model="actionReason" label="操作理由" />
              <VBtn
                v-if="action === 'warn' || action === 'mute'"
                color="warning"
                :loading="busy"
                @click="perform"
              >
                执行{{ action === 'warn' ? '警告' : '禁言' }}
              </VBtn>
            </template>
            <VAlert v-if="actionResult" :type="actionResult.status === 'success' ? 'success' : 'warning'">
              {{ actionResult.status }} · {{ actionResult.data }}
            </VAlert>
          </VCardText>
        </VCard>
      </VNavigationDrawer>
    </template>
  </div>
</template>

<style scoped>
.guard-data {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  max-width: 42rem;
}
</style>
