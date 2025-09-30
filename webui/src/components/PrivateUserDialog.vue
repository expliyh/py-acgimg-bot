<script setup lang="ts">
import { reactive, watch } from 'vue';
import Dialog from 'primevue/dialog';
import InputSwitch from 'primevue/inputswitch';
import Dropdown from 'primevue/dropdown';
import Button from 'primevue/button';
import Tag from 'primevue/tag';
import Divider from 'primevue/divider';
import Timeline from 'primevue/timeline';

import type { PrivateMeta, PrivateUserDetail, PrivateUserUpdatePayload } from '@/services/api';

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

watch(
  () => props.user,
  (user) => {
    if (!user) {
      Object.keys(form).forEach((key) => delete (form as any)[key]);
      return;
    }
    form.nick_name = user.nick_name;
    form.enable_chat = user.enable_chat;
    form.sanity_limit = user.sanity_limit;
    form.allow_r18g = user.allow_r18g;
    form.status = user.status;
  },
  { immediate: true }
);

function close() {
  emit('update:visible', false);
}

function save() {
  emit('submit', { ...form });
}
</script>

<template>
  <Dialog
    :visible="visible && !!user"
    :modal="true"
    header="私聊用户详情"
    style="width: min(720px, 95vw)"
    @update:visible="emit('update:visible', $event)"
  >
    <template v-if="user">
      <section class="grid gap-4">
        <div class="col-12">
          <h3 class="text-lg font-semibold mb-3">基础信息</h3>
          <div class="grid formgrid p-fluid">
            <div class="field col-12 md:col-6">
              <label class="text-sm text-color-secondary">昵称</label>
              <input v-model="form.nick_name" type="text" class="p-inputtext" />
            </div>
            <div class="field col-12 md:col-6">
              <label class="text-sm text-color-secondary">状态</label>
              <Dropdown
                v-model="form.status"
                :options="meta?.statuses ?? []"
                optionLabel="label"
                optionValue="value"
              />
            </div>
            <div class="field col-6">
              <label class="text-sm text-color-secondary">允许聊天</label>
              <InputSwitch v-model="form.enable_chat" />
            </div>
            <div class="field col-6">
              <label class="text-sm text-color-secondary">允许 R18G</label>
              <InputSwitch v-model="form.allow_r18g" />
            </div>
            <div class="field col-12 md:col-6">
              <label class="text-sm text-color-secondary">理智值上限</label>
              <input v-model.number="form.sanity_limit" type="number" min="0" class="p-inputtext" />
            </div>
          </div>
        </div>
        <Divider />
        <div class="col-12">
          <h3 class="text-lg font-semibold mb-3">运行指标</h3>
          <div class="flex gap-3 flex-wrap">
            <Tag :value="`用户 ID #${user.id}`" severity="info" />
            <Tag :value="`消息量 ${user.message_count}`" severity="success" />
            <Tag
              :value="`最后活跃 ${user.last_activity ? new Date(user.last_activity).toLocaleString() : '暂无'}`"
              severity="warning"
            />
          </div>
        </div>
        <Divider />
        <div class="col-12">
          <h3 class="text-lg font-semibold mb-3">近期消息</h3>
          <Timeline :value="user.recent_messages" layout="vertical" align="left">
            <template #marker>
              <i class="pi pi-inbox text-primary"></i>
            </template>
            <template #content="{ item }">
              <div class="border-round surface-card p-3 shadow-1">
                <div class="flex justify-content-between text-sm text-color-secondary">
                  <span>消息 ID: {{ item.message_id }}</span>
                  <span>{{ item.sent_at ? new Date(item.sent_at).toLocaleString() : '未知' }}</span>
                </div>
                <p class="mt-2 mb-0 white-space-pre-line text-sm">
                  {{ item.text ?? '无内容' }}
                </p>
              </div>
            </template>
          </Timeline>
        </div>
      </section>
    </template>
    <template #footer>
      <div v-if="user" class="flex justify-content-end gap-2">
        <Button label="取消" severity="secondary" outlined @click="close" />
        <Button label="保存" icon="pi pi-check" @click="save" />
      </div>
    </template>
  </Dialog>
</template>
