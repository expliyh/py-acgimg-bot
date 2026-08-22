<script setup lang="ts">
import { computed, reactive, watch } from 'vue';

import type { PrivateMeta, PrivateUserDetail, PrivateUserUpdatePayload } from '@/services/api';
import { privateUserFormSnapshot } from '@/utils/dialog-form';

const props = defineProps<{
  visible: boolean;
  meta: PrivateMeta | null;
  user: PrivateUserDetail | null;
}>();

const emit = defineEmits<{
  (e: 'update:visible', value: boolean): void;
  (e: 'submit', value: PrivateUserUpdatePayload): void;
}>();

const form = reactive<PrivateUserUpdatePayload>({});

function syncForm(user: PrivateUserDetail | null) {
  Object.keys(form).forEach((key) => delete (form as any)[key]);
  Object.assign(form, privateUserFormSnapshot(user));
}

watch(
  [() => props.user, () => props.visible],
  ([user]) => syncForm(user),
  { immediate: true },
);

const dialogModel = computed({
  get: () => props.visible && Boolean(props.user),
  set: (value) => emit('update:visible', value),
});

function close() {
  emit('update:visible', false);
}

function updateStatus(value: string | null) {
  form.status = value;
}

function save() {
  emit('submit', { ...form });
}
</script>

<template>
  <VDialog v-model="dialogModel" max-width="720" aria-labelledby="private-dialog-title">
    <VCard v-if="user">
      <VCardTitle id="private-dialog-title">私聊用户详情</VCardTitle>
      <VCardText>
        <section class="d-flex flex-column ga-4">
          <div>
            <h3 class="text-h6 font-weight-bold mb-3">基础信息</h3>
            <VRow>
              <VCol cols="12" md="6" class="d-flex flex-column ga-2">
                <label for="private-nick-name" class="text-body-2 text-medium-emphasis">昵称</label>
                <VTextField id="private-nick-name" v-model="form.nick_name" hide-details="auto" />
              </VCol>
              <VCol cols="12" md="6" class="d-flex flex-column ga-2">
                <label for="private-status" class="text-body-2 text-medium-emphasis">状态</label>
                <VSelect
                  id="private-status"
                  :model-value="form.status"
                  :items="meta?.statuses ?? []"
                  item-title="label"
                  item-value="value"
                  hide-details="auto"
                  @update:modelValue="updateStatus"
                />
              </VCol>
              <VCol cols="6" class="d-flex flex-column ga-2">
                <label for="private-enable-chat" class="text-body-2 text-medium-emphasis">允许聊天</label>
                <VSwitch id="private-enable-chat" v-model="form.enable_chat" color="primary" hide-details density="compact" />
              </VCol>
              <VCol cols="6" class="d-flex flex-column ga-2">
                <label for="private-allow-r18g" class="text-body-2 text-medium-emphasis">允许 R18G</label>
                <VSwitch id="private-allow-r18g" v-model="form.allow_r18g" color="primary" hide-details density="compact" />
              </VCol>
              <VCol cols="12" md="6" class="d-flex flex-column ga-2">
                <label for="private-sanity-limit" class="text-body-2 text-medium-emphasis">理智值上限</label>
                <VNumberInput id="private-sanity-limit" v-model="form.sanity_limit" :min="0" hide-details="auto" />
              </VCol>
            </VRow>
          </div>
          <VDivider />
          <div>
            <h3 class="text-h6 font-weight-bold mb-3">运行指标</h3>
            <div class="d-flex ga-3 flex-wrap">
              <VChip size="small" color="info">用户 ID #{{ user.id }}</VChip>
              <VChip size="small" color="success">消息量 {{ user.message_count }}</VChip>
              <VChip size="small" color="warning">
                最后活跃 {{ user.last_activity ? new Date(user.last_activity).toLocaleString() : '暂无' }}
              </VChip>
            </div>
          </div>
          <VDivider />
          <div>
            <h3 class="text-h6 font-weight-bold mb-3">近期消息</h3>
            <VTimeline direction="vertical" align="start" density="compact">
              <VTimelineItem v-for="item in user.recent_messages" :key="item.message_id">
                <template #icon>
                  <VIcon icon="mdi-inbox" color="primary" />
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
