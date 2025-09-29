<template>
  <div class="surface-card border-round shadow-1 p-4">
    <div class="flex justify-content-between align-items-center mb-4">
      <div>
        <h2 class="m-0">自动化规则</h2>
        <span class="text-600">配置巡检、欢迎、关键词联动等自动化流程，保障运维效率。</span>
      </div>
      <Button label="新建规则" icon="pi pi-magic" @click="openDialog()" />
    </div>

    <DataTable :value="store.automationRules" dataKey="id" responsiveLayout="scroll">
      <Column field="name" header="规则名称"></Column>
      <Column field="trigger" header="触发条件"></Column>
      <Column field="action" header="执行动作"></Column>
      <Column field="enabled" header="状态">
        <template #body="slotProps">
          <Tag :value="slotProps.data.enabled ? '启用' : '停用'" :severity="slotProps.data.enabled ? 'success' : 'danger'" />
        </template>
      </Column>
      <Column header="操作" :exportable="false" style="width: 10rem">
        <template #body="slotProps">
          <div class="flex gap-2">
            <Button icon="pi pi-pencil" severity="secondary" rounded @click="openDialog(slotProps.data)" />
            <Button icon="pi pi-power-off" severity="help" rounded @click="toggleStatus(slotProps.data)" />
            <Button icon="pi pi-trash" severity="danger" rounded @click="confirmDelete(slotProps.data.id)" />
          </div>
        </template>
      </Column>
    </DataTable>

    <Dialog v-model:visible="dialogVisible" header="规则设置" :modal="true" :style="{ width: '32rem' }">
      <div class="flex flex-column gap-3">
        <FloatLabel>
          <InputText id="rule-name" v-model="form.name" />
          <label for="rule-name">规则名称</label>
        </FloatLabel>
        <FloatLabel>
          <Textarea id="rule-trigger" v-model="form.trigger" rows="2" autoResize />
          <label for="rule-trigger">触发条件（支持关键字/计划任务）</label>
        </FloatLabel>
        <FloatLabel>
          <Textarea id="rule-action" v-model="form.action" rows="3" autoResize />
          <label for="rule-action">执行动作描述</label>
        </FloatLabel>
        <div class="flex align-items-center justify-content-between">
          <span>启用规则</span>
          <InputSwitch v-model="form.enabled" />
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
import { useAdminStore, type AutomationRule } from "../stores/admin";

const store = useAdminStore();
const toast = useToast();
const confirm = useConfirm();

const dialogVisible = ref(false);
const editingId = ref<string | null>(null);

const form = reactive({
  name: "",
  trigger: "",
  action: "",
  enabled: true
});

watch(dialogVisible, value => {
  if (!value) {
    editingId.value = null;
    Object.assign(form, { name: "", trigger: "", action: "", enabled: true });
  }
});

function openDialog(rule?: AutomationRule) {
  if (rule) {
    editingId.value = rule.id;
    Object.assign(form, rule);
  }
  dialogVisible.value = true;
}

async function save() {
  if (!form.name.trim() || !form.trigger.trim() || !form.action.trim()) {
    toast.add({ severity: "warn", summary: "校验失败", detail: "请完整填写规则信息", life: 3000 });
    return;
  }
  if (editingId.value) {
    await store.updateAutomationRule(editingId.value, form);
    toast.add({ severity: "success", summary: "已更新", detail: "自动化规则已保存" });
  } else {
    await store.createAutomationRule(form);
    toast.add({ severity: "success", summary: "已创建", detail: "新的自动化规则已启用" });
  }
  dialogVisible.value = false;
}

async function toggleStatus(rule: AutomationRule) {
  await store.updateAutomationRule(rule.id, { ...rule, enabled: !rule.enabled });
  toast.add({ severity: "info", summary: "状态更新", detail: rule.enabled ? "规则已停用" : "规则已启用" });
}

function confirmDelete(id: string) {
  confirm.require({
    message: "确定删除该自动化规则吗？",
    header: "删除规则",
    icon: "pi pi-exclamation-triangle",
    acceptClass: "p-button-danger",
    accept: async () => {
      await store.deleteAutomationRule(id);
      toast.add({ severity: "info", summary: "已删除", detail: "自动化规则已移除" });
    }
  });
}

onMounted(() => {
  if (!store.automationRules.length) {
    store.fetchAutomationRules();
  }
});
</script>
