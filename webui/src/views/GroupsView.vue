<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import GuardView from "@/views/GuardView.vue";
import { useFeedback } from "@/composables/feedback";
import {
  fetchGroupMeta,
  getGroupDetail,
  listAllGroups,
  updateGroup,
  type GroupDetail,
  type GroupListItem,
  type GroupMeta,
  type GroupUpdatePayload,
} from "@/services/api";

const route = useRoute();
const router = useRouter();
const { toast } = useFeedback();

function parseGroupId(value: unknown): number | null {
  if (typeof value !== "string") return null;
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) && parsed < 0 ? parsed : null;
}

const selectedGroupId = ref<number | null>(parseGroupId(route.params.id));
const groups = ref<GroupListItem[]>([]);
const groupsLoading = ref(false);
const groupsError = ref("");
const detail = ref<GroupDetail | null>(null);
const detailLoading = ref(false);
const detailError = ref("");
const meta = ref<GroupMeta | null>(null);
const saving = ref(false);
const search = ref("");
const enableFilter = ref<boolean | null>(null);
const chatFilter = ref<boolean | null>(null);
const activeWorkspace = ref("overview");
const mobileListOpen = ref(false);
let detailVersion = 0;

const form = reactive<GroupUpdatePayload>({});
const groupsWithDeepLink = computed<GroupListItem[]>(() => {
  if (
    selectedGroupId.value === null ||
    groups.value.some((group) => group.id === selectedGroupId.value)
  ) {
    return groups.value;
  }
  // Keep an unknown historical deep link visible while its detail request is
  // attempted.  This mirrors the old guard selector's temporary option and
  // avoids silently dropping a bookmarked group when list pagination fails.
  const temporary = detail.value && detail.value.id === selectedGroupId.value
    ? detail.value
    : {
        id: selectedGroupId.value,
        name: "当前链接群组",
        status: "unknown",
        enable: false,
        enable_chat: false,
        chat_mode: null,
        sanity_limit: 0,
        allow_r18g: false,
        allow_setu: false,
        admin_ids: [],
        message_count: 0,
        last_activity: null,
      };
  return [temporary, ...groups.value];
});
const filteredGroups = computed(() => {
  const query = search.value.trim().toLowerCase();
  return groupsWithDeepLink.value.filter((group) => {
    const matchesQuery = !query || `${group.id} ${group.name || ""}`.toLowerCase().includes(query);
    const matchesEnable = enableFilter.value === null || group.enable === enableFilter.value;
    const matchesChat = chatFilter.value === null || group.enable_chat === chatFilter.value;
    return matchesQuery && matchesEnable && matchesChat;
  });
});

function syncForm(group: GroupDetail | null) {
  Object.keys(form).forEach((key) => delete (form as Record<string, unknown>)[key]);
  if (!group) return;
  Object.assign(form, {
    name: group.name,
    enable: group.enable,
    enable_chat: group.enable_chat,
    chat_mode: group.chat_mode,
    sanity_limit: group.sanity_limit,
    allow_r18g: group.allow_r18g,
    allow_setu: group.allow_setu,
    admin_ids: [...group.admin_ids],
  });
}

async function loadGroups() {
  groupsLoading.value = true;
  groupsError.value = "";
  try {
    groups.value = await listAllGroups();
  } catch (error) {
    console.error(error);
    groupsError.value = "无法获取群组列表。";
  } finally {
    groupsLoading.value = false;
  }
}

async function loadDetail(id: number | null) {
  const version = ++detailVersion;
  if (id === null) {
    detail.value = null;
    syncForm(null);
    detailLoading.value = false;
    detailError.value = "";
    return;
  }
  detailLoading.value = true;
  detailError.value = "";
  try {
    const value = await getGroupDetail(id);
    if (version !== detailVersion) return;
    detail.value = value;
    if (!groups.value.some((group) => group.id === value.id)) {
      groups.value = [value, ...groups.value];
    }
    syncForm(value);
  } catch (error) {
    if (version !== detailVersion) return;
    console.error(error);
    detail.value = null;
    detailError.value = "无法获取该群组详情，请确认群组仍已登记。";
  } finally {
    if (version === detailVersion) detailLoading.value = false;
  }
}

function selectGroup(id: number) {
  selectedGroupId.value = id;
  activeWorkspace.value = "overview";
  mobileListOpen.value = false;
  void router.push({ name: "group-management", params: { id: String(id) } });
}

async function saveBaseConfig() {
  if (!detail.value) return;
  saving.value = true;
  try {
    const updated = await updateGroup(detail.value.id, {
      ...form,
      admin_ids: (form.admin_ids || [])
        .map((value) => Number(value))
        .filter((value) => Number.isSafeInteger(value)),
    });
    detail.value = updated;
    syncForm(updated);
    groups.value = groups.value.map((group) => (group.id === updated.id ? updated : group));
    toast.add({ severity: "success", summary: "保存成功", detail: "基础配置已更新。", life: 2500 });
  } catch (error) {
    console.error(error);
    toast.add({ severity: "error", summary: "保存失败", detail: "请稍后重试。", life: 4000 });
  } finally {
    saving.value = false;
  }
}

watch(
  () => route.params.id,
  (value) => {
    selectedGroupId.value = parseGroupId(value);
    activeWorkspace.value = "overview";
    mobileListOpen.value = false;
    void loadDetail(selectedGroupId.value);
  },
);

onMounted(async () => {
  try {
    meta.value = await fetchGroupMeta();
  } catch (error) {
    console.error(error);
    toast.add({ severity: "error", summary: "加载失败", detail: "无法获取群组元数据。", life: 4000 });
  }
  await Promise.all([loadGroups(), loadDetail(selectedGroupId.value)]);
});
</script>

<template>
  <section class="group-management d-flex flex-column ga-4">
    <header class="d-flex align-center justify-space-between ga-3 flex-wrap">
      <div>
        <h1 class="text-h4 font-weight-bold ma-0">群组管理</h1>
        <p class="text-body-2 text-medium-emphasis mt-2 mb-0">
          在一个工作区管理群组基础配置、智能审核和成员状态。
        </p>
      </div>
      <VBtn prepend-icon="mdi-refresh" variant="outlined" :loading="groupsLoading" @click="loadGroups">刷新群组</VBtn>
    </header>

    <VAlert v-if="groupsError" type="error" variant="tonal" closable @click:close="groupsError = ''">{{ groupsError }}</VAlert>

    <VRow class="align-start" no-gutters>
      <VCol
        cols="12"
        md="4"
        lg="3"
        class="pe-md-4"
        :class="{ 'group-list-col--mobile-hidden': selectedGroupId && !mobileListOpen }"
      >
        <VCard class="group-list-card" :class="{ 'group-list-card--mobile': mobileListOpen }">
          <VCardTitle class="d-flex align-center ga-2">
            <VIcon icon="mdi-account-group-outline" color="primary" />
            <span>群组</span>
            <VChip size="small" color="info">{{ filteredGroups.length }} / {{ groups.length }}</VChip>
            <VSpacer />
            <VBtn class="d-md-none" icon="mdi-close" variant="text" aria-label="关闭群组列表" @click="mobileListOpen = false" />
          </VCardTitle>
          <VCardText class="d-flex flex-column ga-3">
            <VTextField id="groups-search" v-model="search" label="搜索群 ID / 名称" prepend-inner-icon="mdi-magnify" hide-details />
            <div class="d-flex ga-2">
              <VSelect id="groups-enable" v-model="enableFilter" label="启用状态" :items="[{ title: '全部', value: null }, { title: '已启用', value: true }, { title: '已停用', value: false }]" hide-details />
              <VSelect id="groups-chat-enabled" v-model="chatFilter" label="聊天功能" :items="[{ title: '全部', value: null }, { title: '开放', value: true }, { title: '关闭', value: false }]" hide-details />
            </div>
            <VProgressLinear v-if="groupsLoading" indeterminate color="primary" />
            <VList v-if="filteredGroups.length" lines="two" class="pa-0 group-list" nav>
              <VListItem
                v-for="group in filteredGroups"
                :key="group.id"
                :active="selectedGroupId === group.id"
                color="primary"
                rounded="lg"
                class="mb-1"
                @click="selectGroup(group.id)"
              >
                <template #prepend>
                  <VAvatar size="34" color="primary" variant="tonal"><VIcon icon="mdi-account-group-outline" size="18" /></VAvatar>
                </template>
                <VListItemTitle>{{ group.name || '未命名群组' }}</VListItemTitle>
                <VListItemSubtitle>{{ group.id }} · 消息 {{ group.message_count }}</VListItemSubtitle>
                <template #append>
                  <VChip size="x-small" :color="group.enable ? 'success' : 'error'">{{ group.enable ? '启用' : '停用' }}</VChip>
                </template>
              </VListItem>
            </VList>
            <VAlert v-else type="info" variant="tonal" density="compact">暂无匹配群组。</VAlert>
          </VCardText>
        </VCard>
      </VCol>

      <VCol cols="12" md="8" lg="9">
        <VBtn v-if="selectedGroupId" class="d-md-none mb-3" prepend-icon="mdi-menu" variant="outlined" @click="mobileListOpen = true">切换群组</VBtn>
        <VCard v-if="detailLoading" class="pa-6"><VSkeletonLoader type="article, actions" /></VCard>
        <VCard v-else-if="detailError" class="pa-6"><VAlert type="error" variant="tonal">{{ detailError }}</VAlert></VCard>
        <VCard v-else-if="detail" class="workspace-card">
          <VCardTitle class="workspace-header d-flex align-start ga-3 flex-wrap">
            <VAvatar size="48" color="primary" variant="tonal"><VIcon icon="mdi-account-group-outline" /></VAvatar>
            <div class="flex-grow-1">
              <div class="d-flex align-center ga-2 flex-wrap">
                <h2 class="text-h5 font-weight-bold ma-0">{{ detail.name || '未命名群组' }}</h2>
                <VChip size="small" :color="detail.enable ? 'success' : 'error'">{{ detail.enable ? '已启用' : '已停用' }}</VChip>
                <VChip size="small" :color="detail.enable_chat ? 'info' : 'warning'">聊天 {{ detail.enable_chat ? '开放' : '关闭' }}</VChip>
              </div>
              <p class="text-caption text-medium-emphasis mb-0 mt-1">{{ detail.id }} · 最后活跃 {{ detail.last_activity ? new Date(detail.last_activity).toLocaleString() : '暂无' }}</p>
            </div>
            <VBtn icon="mdi-refresh" variant="text" aria-label="刷新群组详情" :loading="detailLoading" @click="loadDetail(detail.id)" />
          </VCardTitle>
          <VCardText>
            <div class="d-flex ga-2 flex-wrap mb-4">
              <VChip color="primary" variant="tonal">消息 {{ detail.message_count }}</VChip>
              <VChip color="secondary" variant="tonal">管理员 {{ detail.admin_ids.length }}</VChip>
              <VChip color="info" variant="tonal">聊天模式 {{ detail.chat_mode || '默认' }}</VChip>
            </div>
            <VTabs v-model="activeWorkspace" show-arrows color="primary" class="mb-4">
              <VTab value="overview">概览</VTab>
              <VTab value="base">基础配置</VTab>
              <VTab value="guard">智能群管</VTab>
              <VTab value="directory">群成员</VTab>
              <VTab value="audit">审核与日志</VTab>
            </VTabs>

            <VWindow v-model="activeWorkspace" :touch="false">
              <VWindowItem value="overview">
                <VRow>
                  <VCol cols="12" md="4"><VCard variant="tonal" color="primary"><VCardText><div class="text-caption">消息总量</div><div class="text-h5 font-weight-bold">{{ detail.message_count }}</div></VCardText></VCard></VCol>
                  <VCol cols="12" md="4"><VCard variant="tonal" color="info"><VCardText><div class="text-caption">群组状态</div><div class="text-h6 font-weight-bold">{{ detail.enable ? '正常运行' : '已停用' }}</div></VCardText></VCard></VCol>
                  <VCol cols="12" md="4"><VCard variant="tonal" color="secondary"><VCardText><div class="text-caption">内容分级上限</div><div class="text-h5 font-weight-bold">{{ detail.sanity_limit }}</div></VCardText></VCard></VCol>
                </VRow>
                <VDivider class="my-5" />
                <h3 class="text-subtitle-1 font-weight-bold mb-3">近期消息</h3>
                <VTimeline v-if="detail.recent_messages.length" density="compact" side="end">
                  <VTimelineItem v-for="item in detail.recent_messages.slice(0, 5)" :key="item.message_id" dot-color="primary">
                    <div class="text-caption text-medium-emphasis">{{ item.sent_at ? new Date(item.sent_at).toLocaleString() : '未知时间' }} · 消息 {{ item.message_id }}</div>
                    <div class="text-body-2 mt-1">{{ item.text || '无文本内容' }}</div>
                  </VTimelineItem>
                </VTimeline>
                <VAlert v-else type="info" variant="tonal">暂无近期消息记录。</VAlert>
                <GuardView v-if="activeWorkspace === 'overview'" embedded section="overview" :group-id="detail.id" />
              </VWindowItem>

              <VWindowItem value="base">
                <VForm @submit.prevent="saveBaseConfig">
                  <VRow>
                    <VCol cols="12" md="6"><VTextField id="group-name" v-model="form.name" label="群名称" /></VCol>
                    <VCol cols="12" md="6"><VSelect id="group-chat-mode" v-model="form.chat_mode" label="聊天模式" :items="meta?.chat_modes || []" item-title="label" item-value="value" /></VCol>
                    <VCol cols="6" md="3"><VSwitch id="group-enable" v-model="form.enable" label="群启用" color="primary" hide-details /></VCol>
                    <VCol cols="6" md="3"><VSwitch id="group-enable-chat" v-model="form.enable_chat" label="允许聊天" color="primary" hide-details /></VCol>
                    <VCol cols="6" md="3"><VSwitch id="group-allow-setu" v-model="form.allow_setu" label="允许涩图" color="primary" hide-details /></VCol>
                    <VCol cols="6" md="3"><VSwitch id="group-allow-r18g" v-model="form.allow_r18g" label="允许 R18G" color="primary" hide-details /></VCol>
                    <VCol cols="12" md="6"><VNumberInput id="group-sanity-limit" v-model="form.sanity_limit" label="理智值上限" :min="0" /></VCol>
                    <VCol cols="12"><VCombobox id="group-admin-ids" v-model="form.admin_ids" label="管理员 ID 列表" multiple chips :delimiters="[',']" /></VCol>
                  </VRow>
                  <VBtn type="submit" color="primary" prepend-icon="mdi-check" :loading="saving">保存基础配置</VBtn>
                </VForm>
              </VWindowItem>

              <VWindowItem value="guard">
                <GuardView v-if="activeWorkspace === 'guard'" embedded :group-id="detail.id" />
              </VWindowItem>

              <VWindowItem value="directory">
                <GuardView v-if="activeWorkspace === 'directory'" embedded section="directory" :group-id="detail.id" />
              </VWindowItem>

              <VWindowItem value="audit">
                <GuardView v-if="activeWorkspace === 'audit'" embedded section="audit" :group-id="detail.id" />
              </VWindowItem>
            </VWindow>
          </VCardText>
        </VCard>
        <VCard v-else class="pa-8">
          <VCardText class="text-center">
            <VIcon icon="mdi-account-group-outline" size="56" color="primary" class="mb-3" />
            <h2 class="text-h6 font-weight-bold">选择一个群组开始管理</h2>
            <p class="text-body-2 text-medium-emphasis">左侧列表包含所有已登记群组，包括已停用群组。</p>
          </VCardText>
        </VCard>
      </VCol>
    </VRow>
  </section>
</template>

<style scoped>
.group-list-card,
.workspace-card {
  overflow: hidden;
}
.group-list {
  max-height: calc(100vh - 280px);
  overflow-y: auto;
}
.workspace-header {
  background: color-mix(in srgb, rgb(var(--v-theme-primary)) 5%, rgb(var(--v-theme-surface)));
}
.group-list-col--mobile-hidden {
  display: none;
}
@media (min-width: 960px) {
  .group-list-col--mobile-hidden {
    display: block;
  }
}
</style>
