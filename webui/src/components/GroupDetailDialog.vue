<script setup lang="ts">
import { computed, reactive, watch } from 'vue';
import Dialog from 'primevue/dialog';
import InputSwitch from 'primevue/inputswitch';
import Dropdown from 'primevue/dropdown';
import Chips from 'primevue/chips';
import Button from 'primevue/button';
import Divider from 'primevue/divider';
import Tag from 'primevue/tag';
import Timeline from 'primevue/timeline';

import type { GroupDetail, GroupMeta, GroupUpdatePayload } from '@/services/api';

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

watch(
  () => props.group,
  (group) => {
    if (!group) {
      Object.keys(form).forEach((key) => delete (form as any)[key]);
      return;
    }
    form.name = group.name;
    form.enable = group.enable;
    form.enable_chat = group.enable_chat;
    form.chat_mode = group.chat_mode;
    form.sanity_limit = group.sanity_limit;
    form.allow_r18g = group.allow_r18g;
    form.allow_setu = group.allow_setu;
    form.admin_ids = [...group.admin_ids];
  },
  { immediate: true }
);

const recentMessages = computed(() => props.group?.recent_messages ?? []);

function close() {
  emit('update:visible', false);
}

function save() {
  const adminIds = (form.admin_ids ?? [])
    .map((value) => (typeof value === 'number' ? value : Number.parseInt(String(value), 10)))
    .filter((value) => Number.isFinite(value));

  emit('submit', { ...form, admin_ids: adminIds });
}
</script>

<template>
  <Dialog
    :visible="visible && !!group"
    :modal="true"
    header="群组详情"
    style="width: min(800px, 95vw)"
    @update:visible="emit('update:visible', $event)"
  >
    <template v-if="group">
      <section class="grid gap-4">
        <div class="col-12">
          <h3 class="text-lg font-semibold mb-3">基础配置</h3>
          <div class="grid formgrid p-fluid">
            <div class="field col-12 md:col-6">
              <label class="text-sm text-color-secondary">群名称</label>
              <input v-model="form.name" type="text" class="p-inputtext" />
            </div>
            <div class="field col-12 md:col-6">
              <label class="text-sm text-color-secondary">聊天模式</label>
              <Dropdown
                v-model="form.chat_mode"
                :options="meta?.chat_modes ?? []"
                optionLabel="label"
                optionValue="value"
                placeholder="选择聊天模式"
              />
            </div>
            <div class="field col-6 md:col-3">
              <label class="text-sm text-color-secondary">群启用</label>
              <InputSwitch v-model="form.enable" />
            </div>
            <div class="field col-6 md:col-3">
              <label class="text-sm text-color-secondary">允许聊天</label>
              <InputSwitch v-model="form.enable_chat" />
            </div>
            <div class="field col-6 md:col-3">
              <label class="text-sm text-color-secondary">允许涩图</label>
              <InputSwitch v-model="form.allow_setu" />
            </div>
            <div class="field col-6 md:col-3">
              <label class="text-sm text-color-secondary">允许 R18G</label>
              <InputSwitch v-model="form.allow_r18g" />
            </div>
            <div class="field col-12 md:col-6">
              <label class="text-sm text-color-secondary">理智值上限</label>
              <input v-model.number="form.sanity_limit" type="number" class="p-inputtext" min="0" />
            </div>
            <div class="field col-12">
              <label class="text-sm text-color-secondary">管理员 ID 列表</label>
              <Chips v-model="form.admin_ids" separator="," />
            </div>
          </div>
        </div>
        <Divider />
        <div class="col-12">
          <h3 class="text-lg font-semibold mb-3">运行状态</h3>
          <div class="flex gap-3 flex-wrap">
            <Tag :value="`群 ID #${group.id}`" severity="info" />
            <Tag :value="`状态 ${group.status}`" severity="help" />
            <Tag :value="`消息量 ${group.message_count}`" severity="success" />
            <Tag
              :value="`最后活跃 ${group.last_activity ? new Date(group.last_activity).toLocaleString() : '暂无'}`"
              severity="warning"
            />
          </div>
        </div>
        <Divider />
        <div class="col-12">
          <h3 class="text-lg font-semibold mb-3">近期消息</h3>
          <Timeline :value="recentMessages" layout="vertical" align="left">
            <template #marker>
              <i class="pi pi-comment text-primary"></i>
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
      <div v-if="group" class="flex justify-content-end gap-2">
        <Button label="取消" severity="secondary" outlined @click="close" />
        <Button label="保存" icon="pi pi-check" @click="save" />
      </div>
    </template>
  </Dialog>
</template>
