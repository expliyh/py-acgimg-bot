<template>
  <div class="surface-card border-round shadow-1 p-4">
    <div class="flex justify-content-between align-items-center mb-4">
      <div>
        <h2 class="m-0">功能配置</h2>
        <span class="text-600">除涩图外，还可配置自动翻译、内容审查、活动推送等扩展能力。</span>
      </div>
      <Button label="新增功能" icon="pi pi-plus" @click="openDialog()" />
    </div>

    <DataView :value="store.featureConfigs" layout="grid" :paginator="true" :rows="6">
      <template #grid="slotProps">
        <div class="col-12 md:col-6 xl:col-4 p-2">
          <Card class="h-full">
            <template #title>
              <div class="flex justify-content-between align-items-center">
                <span>{{ slotProps.data.name }}</span>
                <Tag :value="slotProps.data.enabled ? '已启用' : '停用中'" :severity="slotProps.data.enabled ? 'success' : 'danger'" />
              </div>
            </template>
            <template #content>
              <p class="text-600">{{ slotProps.data.description || '暂无描述' }}</p>
              <ul class="m-0 pl-3">
                <li v-for="(value, key) in slotProps.data.options" :key="key">
                  <span class="font-medium">{{ key }}：</span>{{ value }}
                </li>
              </ul>
            </template>
            <template #footer>
              <div class="flex gap-2">
                <Button label="编辑" icon="pi pi-pencil" text @click="openDialog(slotProps.data)" />
                <Button label="删除" icon="pi pi-trash" text severity="danger" @click="confirmDelete(slotProps.data.id)" />
              </div>
            </template>
          </Card>
        </div>
      </template>
    </DataView>

    <Dialog v-model:visible="dialogVisible" header="功能配置" :modal="true" :style="{ width: '32rem' }">
      <div class="flex flex-column gap-3">
        <FloatLabel>
          <InputText id="feature-name" v-model="form.name" />
          <label for="feature-name">功能名称</label>
        </FloatLabel>
        <FloatLabel>
          <Textarea id="feature-desc" v-model="form.description" rows="3" autoResize />
          <label for="feature-desc">功能描述</label>
        </FloatLabel>
        <div class="flex align-items-center justify-content-between">
          <span>启用功能</span>
          <InputSwitch v-model="form.enabled" />
        </div>
        <div>
          <label class="block mb-2">高级参数（键=值，每行一组）</label>
          <Textarea v-model="optionDraft" rows="5" placeholder="如：\nlocale=zh-CN\nautoReply=true" />
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
import { computed, reactive, ref, watch, onMounted } from "vue";
import Button from "primevue/button";
import DataView from "primevue/dataview";
import Card from "primevue/card";
import Tag from "primevue/tag";
import Dialog from "primevue/dialog";
import FloatLabel from "primevue/floatlabel";
import InputText from "primevue/inputtext";
import Textarea from "primevue/textarea";
import InputSwitch from "primevue/inputswitch";
import { useToast } from "primevue/usetoast";
import { useConfirm } from "primevue/useconfirm";
import { useAdminStore, type FeatureConfig } from "../stores/admin";

const store = useAdminStore();
const toast = useToast();
const confirm = useConfirm();

const dialogVisible = ref(false);
const editingName = ref<string | null>(null);
const optionDraft = ref("");

const form = reactive({
  name: "",
  enabled: true,
  description: "",
  options: {} as Record<string, string>
});

watch(dialogVisible, value => {
  if (!value) {
    editingName.value = null;
    optionDraft.value = "";
    Object.assign(form, { name: "", enabled: true, description: "", options: {} });
  }
});

function openDialog(feature?: FeatureConfig) {
  if (feature) {
    editingName.value = feature.name;
    Object.assign(form, feature);
    optionDraft.value = Object.entries(feature.options)
      .map(([key, value]) => `${key}=${value}`)
      .join("\n");
  }
  dialogVisible.value = true;
}

const parsedOptions = computed(() => {
  const entries = optionDraft.value
    .split(/\n+/)
    .map(line => line.trim())
    .filter(Boolean)
    .map(line => {
      const [key, ...rest] = line.split("=");
      return [key.trim(), rest.join("=").trim()];
    })
    .filter(([key]) => key);
  return Object.fromEntries(entries as [string, string][]);
});

async function save() {
  if (!form.name.trim()) {
    toast.add({ severity: "warn", summary: "校验失败", detail: "请输入功能名称", life: 3000 });
    return;
  }
  try {
    await store.upsertFeatureConfig({
      name: form.name,
      enabled: form.enabled,
      description: form.description,
      options: parsedOptions.value
    });
    toast.add({ severity: "success", summary: "已保存", detail: "功能配置已更新" });
    dialogVisible.value = false;
  } catch (error) {
    toast.add({ severity: "error", summary: "保存失败", detail: String(error) });
  }
}

function confirmDelete(id: string) {
  confirm.require({
    message: "确定删除该功能配置吗？",
    header: "删除配置",
    icon: "pi pi-exclamation-triangle",
    acceptClass: "p-button-danger",
    accept: async () => {
      await store.deleteFeatureConfig(id);
      toast.add({ severity: "info", summary: "已删除", detail: "配置已移除" });
    }
  });
}

onMounted(() => {
  if (!store.featureConfigs.length) {
    store.fetchFeatureConfigs();
  }
});
</script>
