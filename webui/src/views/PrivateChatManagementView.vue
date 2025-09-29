<template>
  <div class="surface-card border-round shadow-1 p-4">
    <div class="flex justify-content-between align-items-center mb-4">
      <div>
        <h2 class="m-0">私聊管理</h2>
        <span class="text-600">掌握用户私聊动态，支持快速备注、静音及回访提醒。</span>
      </div>
      <Button label="新增私聊" icon="pi pi-user-plus" @click="openDialog()" />
    </div>

    <DataTable :value="store.privateChats" dataKey="id" responsiveLayout="scroll">
      <Column field="username" header="用户名"></Column>
      <Column field="alias" header="备注"></Column>
      <Column field="last_message_preview" header="最近互动"></Column>
      <Column field="is_muted" header="状态">
        <template #body="slotProps">
          <Tag :value="slotProps.data.is_muted ? '已静音' : '通知开启'" :severity="slotProps.data.is_muted ? 'warn' : 'success'" />
        </template>
      </Column>
      <Column header="操作" :exportable="false" style="width: 10rem">
        <template #body="slotProps">
          <div class="flex gap-2">
            <Button icon="pi pi-pencil" severity="secondary" rounded @click="openDialog(slotProps.data)" />
            <Button icon="pi pi-bell" severity="success" rounded @click="toggleMute(slotProps.data)" />
            <Button icon="pi pi-trash" severity="danger" rounded @click="confirmDelete(slotProps.data)" />
          </div>
        </template>
      </Column>
    </DataTable>

    <Dialog v-model:visible="dialogVisible" header="私聊详情" :modal="true" :style="{ width: '32rem' }">
      <div class="flex flex-column gap-3">
        <FloatLabel>
          <InputText id="username" v-model="form.username" />
          <label for="username">用户名</label>
        </FloatLabel>
        <FloatLabel>
          <InputText id="alias" v-model="form.alias" />
          <label for="alias">备注名</label>
        </FloatLabel>
        <FloatLabel>
          <Textarea id="preview" v-model="form.last_message_preview" rows="3" autoResize />
          <label for="preview">最近互动摘录</label>
        </FloatLabel>
        <div class="flex align-items-center justify-content-between">
          <span>静音提醒</span>
          <InputSwitch v-model="form.is_muted" />
        </div>
      </div>
      <template #footer>
        <Button label="取消" text severity="secondary" @click="dialogVisible = false" />
        <Button label="保存" icon="pi pi-check" @click="save" />
      </template>
    </Dialog>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref, watch, onMounted } from "vue";
import Button from "primevue/button";
import DataTable from "primevue/datatable";
import Column from "primevue/column";
import Dialog from "primevue/dialog";
import FloatLabel from "primevue/floatlabel";
import InputText from "primevue/inputtext";
import Textarea from "primevue/textarea";
import InputSwitch from "primevue/inputswitch";
import Tag from "primevue/tag";
import { useToast } from "primevue/usetoast";
import { useConfirm } from "primevue/useconfirm";
import { useAdminStore, type PrivateChat } from "../stores/admin";

const store = useAdminStore();
const toast = useToast();
const confirm = useConfirm();

const dialogVisible = ref(false);
const editingId = ref<string | null>(null);

const form = reactive({
  username: "",
  alias: "",
  last_message_preview: "",
  is_muted: false
});

watch(dialogVisible, value => {
  if (!value) {
    editingId.value = null;
    Object.assign(form, { username: "", alias: "", last_message_preview: "", is_muted: false });
  }
});

function openDialog(chat?: PrivateChat) {
  if (chat) {
    editingId.value = chat.id;
    Object.assign(form, chat);
  }
  dialogVisible.value = true;
}

async function save() {
  if (!form.username.trim()) {
    toast.add({ severity: "warn", summary: "校验失败", detail: "请输入用户名", life: 3000 });
    return;
  }
  if (editingId.value) {
    await store.updatePrivateChat(editingId.value, form);
    toast.add({ severity: "success", summary: "已更新", detail: "私聊信息已保存" });
  } else {
    await store.createPrivateChat(form);
    toast.add({ severity: "success", summary: "已记录", detail: "新的私聊用户已添加" });
  }
  dialogVisible.value = false;
}

async function toggleMute(chat: PrivateChat) {
  await store.updatePrivateChat(chat.id, { ...chat, is_muted: !chat.is_muted });
  toast.add({ severity: "info", summary: "状态更新", detail: chat.is_muted ? "已开启提醒" : "已设为静音" });
}

function confirmDelete(chat: PrivateChat) {
  confirm.require({
    message: `确认删除与 ${chat.username} 的记录吗？`,
    header: "删除私聊记录",
    icon: "pi pi-exclamation-triangle",
    acceptClass: "p-button-danger",
    accept: async () => {
      await store.deletePrivateChat(chat.id);
      toast.add({ severity: "info", summary: "已删除", detail: "私聊记录已清理" });
    }
  });
}

onMounted(() => {
  if (!store.privateChats.length) {
    store.fetchPrivateChats();
  }
});
</script>
