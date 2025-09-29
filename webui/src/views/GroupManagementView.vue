<template>
  <div class="surface-card border-round shadow-1 p-4">
    <div class="flex justify-content-between align-items-center mb-4">
      <div>
        <h2 class="m-0">群组管理</h2>
        <span class="text-600">配置机器人群组、欢迎语以及标签，快速定位重点社群。</span>
      </div>
      <Button label="新增群组" icon="pi pi-plus" @click="openDialog()" />
    </div>

    <DataTable :value="store.groups" dataKey="id" responsiveLayout="scroll">
      <Column field="name" header="名称"></Column>
      <Column field="description" header="描述"></Column>
      <Column header="标签">
        <template #body="slotProps">
          <div class="flex gap-2 flex-wrap">
            <Tag v-for="tag in slotProps.data.tags" :key="tag" :value="tag" severity="info" />
          </div>
        </template>
      </Column>
      <Column field="is_active" header="状态">
        <template #body="slotProps">
          <Tag :value="slotProps.data.is_active ? '运行中' : '已暂停'" :severity="slotProps.data.is_active ? 'success' : 'danger'" />
        </template>
      </Column>
      <Column header="操作" :exportable="false" style="width: 10rem">
        <template #body="slotProps">
          <div class="flex gap-2">
            <Button icon="pi pi-pencil" severity="secondary" rounded @click="openDialog(slotProps.data)" />
            <Button icon="pi pi-trash" severity="danger" rounded @click="confirmDelete(slotProps.data)" />
          </div>
        </template>
      </Column>
    </DataTable>

    <Dialog v-model:visible="dialogVisible" header="群组详情" :modal="true" :style="{ width: '32rem' }">
      <div class="flex flex-column gap-3">
        <FloatLabel>
          <InputText id="name" v-model="form.name" />
          <label for="name">群组名称</label>
        </FloatLabel>
        <FloatLabel>
          <Textarea id="description" v-model="form.description" rows="3" autoResize />
          <label for="description">群组描述</label>
        </FloatLabel>
        <div>
          <label class="block mb-2">标签</label>
          <Chips v-model="form.tags" separator="," />
        </div>
        <div class="flex align-items-center justify-content-between">
          <span>启用机器人</span>
          <InputSwitch v-model="form.is_active" />
        </div>
      </div>
      <template #footer>
        <Button label="取消" text severity="secondary" @click="dialogVisible = false" />
        <Button label="保存" icon="pi pi-check" @click="saveGroup" />
      </template>
    </Dialog>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref, watch, onMounted } from "vue";
import { storeToRefs } from "pinia";
import Button from "primevue/button";
import DataTable from "primevue/datatable";
import Column from "primevue/column";
import Dialog from "primevue/dialog";
import FloatLabel from "primevue/floatlabel";
import InputText from "primevue/inputtext";
import Textarea from "primevue/textarea";
import Chips from "primevue/chips";
import InputSwitch from "primevue/inputswitch";
import Tag from "primevue/tag";
import { useToast } from "primevue/usetoast";
import { useConfirm } from "primevue/useconfirm";
import { useAdminStore } from "../stores/admin";

const store = useAdminStore();
const { groups } = storeToRefs(store);
const toast = useToast();
const confirm = useConfirm();

const dialogVisible = ref(false);
const editingId = ref<string | null>(null);

const form = reactive({
  name: "",
  description: "",
  tags: [] as string[],
  is_active: true
});

watch(dialogVisible, value => {
  if (!value) {
    editingId.value = null;
    Object.assign(form, { name: "", description: "", tags: [], is_active: true });
  }
});

function openDialog(group?: typeof groups.value[number]) {
  if (group) {
    editingId.value = group.id;
    Object.assign(form, group);
  }
  dialogVisible.value = true;
}

async function saveGroup() {
  try {
    if (!form.name.trim()) {
      toast.add({ severity: "warn", summary: "校验失败", detail: "请输入群组名称", life: 3000 });
      return;
    }
    if (editingId.value) {
      await store.updateGroup(editingId.value, form);
      toast.add({ severity: "success", summary: "已更新", detail: "群组信息已保存" });
    } else {
      await store.createGroup(form);
      toast.add({ severity: "success", summary: "已创建", detail: "新的群组已纳入管理" });
    }
    dialogVisible.value = false;
  } catch (error) {
    toast.add({ severity: "error", summary: "保存失败", detail: String(error) });
  }
}

function confirmDelete(group: typeof groups.value[number]) {
  confirm.require({
    message: `确认移除群组「${group.name}」?`,
    header: "删除群组",
    icon: "pi pi-exclamation-triangle",
    acceptClass: "p-button-danger",
    accept: async () => {
      await store.deleteGroup(group.id);
      toast.add({ severity: "info", summary: "已删除", detail: "群组配置已移除" });
    }
  });
}

onMounted(() => {
  if (!store.groups.length) {
    store.fetchGroups();
  }
});
</script>
