<script setup lang="ts">
import { computed, reactive, watch } from 'vue';

import type { GroupDetail, GroupMeta, GroupUpdatePayload } from '@/services/api';
import { groupFormSnapshot, normalizeAdminIds } from '@/utils/dialog-form';

const props = defineProps<{
  visible: boolean;
  meta: GroupMeta | null;
  group: GroupDetail | null;
}>();

const emit = defineEmits<{
  (e: 'update:visible', value: boolean): void;
  (e: 'submit', value: GroupUpdatePayload): void;
}>();

const form = reactive<GroupUpdatePayload>({});

function syncForm(group: GroupDetail | null) {
  Object.keys(form).forEach((key) => delete (form as any)[key]);
  Object.assign(form, groupFormSnapshot(group));
}

watch(
  [() => props.group, () => props.visible],
  ([group]) => syncForm(group),
  { immediate: true },
);

const dialogModel = computed({
  get: () => props.visible && Boolean(props.group),
  set: (value) => emit('update:visible', value),
});

const recentMessages = computed(() => props.group?.recent_messages ?? []);

function close() {
  emit('update:visible', false);
}

function updateChatMode(value: string | null) {
  form.chat_mode = value;
}

function save() {
  const adminIds = normalizeAdminIds(form.admin_ids);

  emit('submit', { ...form, admin_ids: adminIds });
}
</script>

<template>
  <VDialog v-model="dialogModel" max-width="800" aria-labelledby="group-dialog-title">
    <VCard v-if="group">
      <VCardTitle id="group-dialog-title">群组详情</VCardTitle>
      <VCardText>
        <section class="d-flex flex-column ga-4">
          <div>
            <h3 class="text-h6 font-weight-bold mb-3">基础配置</h3>
            <VRow>
              <VCol cols="12" md="6" class="d-flex flex-column ga-2">
                <label for="group-name" class="text-body-2 text-medium-emphasis">群名称</label>
                <VTextField id="group-name" v-model="form.name" hide-details="auto" />
              </VCol>
              <VCol cols="12" md="6" class="d-flex flex-column ga-2">
                <label for="group-chat-mode" class="text-body-2 text-medium-emphasis">聊天模式</label>
                <VSelect
                  id="group-chat-mode"
                  :model-value="form.chat_mode"
                  :items="meta?.chat_modes ?? []"
                  item-title="label"
                  item-value="value"
                  placeholder="选择聊天模式"
                  hide-details="auto"
                  @update:modelValue="updateChatMode"
                />
              </VCol>
              <VCol cols="6" md="3" class="d-flex flex-column ga-2">
                <label for="group-enable" class="text-body-2 text-medium-emphasis">群启用</label>
                <VSwitch id="group-enable" v-model="form.enable" color="primary" hide-details density="compact" />
              </VCol>
              <VCol cols="6" md="3" class="d-flex flex-column ga-2">
                <label for="group-enable-chat" class="text-body-2 text-medium-emphasis">允许聊天</label>
                <VSwitch id="group-enable-chat" v-model="form.enable_chat" color="primary" hide-details density="compact" />
              </VCol>
              <VCol cols="6" md="3" class="d-flex flex-column ga-2">
                <label for="group-allow-setu" class="text-body-2 text-medium-emphasis">允许涩图</label>
                <VSwitch id="group-allow-setu" v-model="form.allow_setu" color="primary" hide-details density="compact" />
              </VCol>
              <VCol cols="6" md="3" class="d-flex flex-column ga-2">
                <label for="group-allow-r18g" class="text-body-2 text-medium-emphasis">允许 R18G</label>
                <VSwitch id="group-allow-r18g" v-model="form.allow_r18g" color="primary" hide-details density="compact" />
              </VCol>
              <VCol cols="12" md="6" class="d-flex flex-column ga-2">
                <label for="group-sanity-limit" class="text-body-2 text-medium-emphasis">理智值上限</label>
                <VNumberInput id="group-sanity-limit" v-model="form.sanity_limit" :min="0" hide-details="auto" />
              </VCol>
              <VCol cols="12" class="d-flex flex-column ga-2">
                <label for="group-admin-ids" class="text-body-2 text-medium-emphasis">管理员 ID 列表</label>
                <VCombobox
                  id="group-admin-ids"
                  v-model="form.admin_ids"
                  multiple
                  chips
                  :delimiters="[',']"
                  hide-details="auto"
                />
              </VCol>
            </VRow>
          </div>
          <VDivider />
          <div>
            <h3 class="text-h6 font-weight-bold mb-3">运行状态</h3>
            <div class="d-flex ga-3 flex-wrap">
              <VChip size="small" color="info">群 ID #{{ group.id }}</VChip>
              <VChip size="small" color="info">状态 {{ group.status }}</VChip>
              <VChip size="small" color="success">消息量 {{ group.message_count }}</VChip>
              <VChip size="small" color="warning">
                最后活跃 {{ group.last_activity ? new Date(group.last_activity).toLocaleString() : '暂无' }}
              </VChip>
            </div>
          </div>
          <VDivider />
          <div>
            <h3 class="text-h6 font-weight-bold mb-3">近期消息</h3>
            <VTimeline direction="vertical" align="start" density="compact">
              <VTimelineItem v-for="item in recentMessages" :key="item.message_id">
                <template #icon>
                  <VIcon icon="mdi-comment-outline" color="primary" />
                </template>
                <div class="rounded-lg surface-panel p-3 elevation-1">
                  <div class="d-flex justify-space-between text-body-2 text-medium-emphasis">
                    <span>消息 ID: {{ item.message_id }}</span>
                    <span>{{ item.sent_at ? new Date(item.sent_at).toLocaleString() : '未知' }}</span>
                  </div>
                  <p class="mt-2 mb-0 white-space-pre-line text-body-2">{{ item.text ?? '无内容' }}</p>
                </div>
              </VTimelineItem>
            </VTimeline>
          </div>
        </section>
      </VCardText>
      <VCardActions class="justify-end ga-2">
        <VBtn variant="outlined" color="secondary" @click="close">取消</VBtn>
        <VBtn color="primary" prepend-icon="mdi-check" @click="save">保存</VBtn>
      </VCardActions>
    </VCard>
  </VDialog>
</template>
