<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import Card from 'primevue/card';
import InputSwitch from 'primevue/inputswitch';
import Tag from 'primevue/tag';
import Button from 'primevue/button';
import Toast from 'primevue/toast';
import { useToast } from 'primevue/usetoast';
import Skeleton from 'primevue/skeleton';

import type { FeatureFlag, FeatureFlagResponse } from '@/services/api';
import { fetchFeatureFlags, updateFeatureFlag } from '@/services/api';

const toast = useToast();
const loading = ref(true);
const features = ref<FeatureFlag[]>([]);
const placeholders = ref<FeatureFlag[]>([]);

const grouped = computed(() => {
  const map = new Map<string, FeatureFlag[]>();
  for (const feature of features.value) {
    if (!map.has(feature.category)) {
      map.set(feature.category, []);
    }
    map.get(feature.category)!.push(feature);
  }
  return Array.from(map.entries());
});

async function loadFlags() {
  loading.value = true;
  try {
    const response: FeatureFlagResponse = await fetchFeatureFlags();
    features.value = response.features;
    placeholders.value = response.placeholders;
  } catch (error) {
    console.error(error);
    toast.add({ severity: 'error', summary: '加载失败', detail: '无法获取功能配置。', life: 4000 });
  } finally {
    loading.value = false;
  }
}

async function toggleFlag(flag: FeatureFlag, value: boolean) {
  if (!flag.editable) return;
  try {
    const updated = await updateFeatureFlag(flag.key, value);
    features.value = features.value.map((item) => (item.key === updated.key ? updated : item));
    toast.add({ severity: 'success', summary: '已更新', detail: `${flag.label} 已${value ? '启用' : '停用'}` });
  } catch (error) {
    console.error(error);
    toast.add({ severity: 'error', summary: '更新失败', detail: '请稍后重试。', life: 4000 });
  }
}

onMounted(loadFlags);
</script>

<template>
  <section class="flex flex-column gap-4">
    <Toast />
    <header class="flex flex-column gap-2">
      <h2 class="text-2xl font-semibold m-0">功能配置</h2>
      <p class="text-color-secondary m-0">
        管理全局功能开关，并预留未来拓展的配置位。
      </p>
      <Button label="刷新" icon="pi pi-refresh" outlined @click="loadFlags" :loading="loading" class="w-full md:w-auto" />
    </header>

    <div v-if="loading" class="grid">
      <div class="col-12 md:col-6" v-for="index in 4" :key="index">
        <Skeleton height="8rem" class="border-round" />
      </div>
    </div>

    <div v-else class="grid gap-4">
      <div class="col-12">
        <h3 class="text-xl font-semibold mb-3">已上线功能</h3>
        <div class="grid">
          <div class="col-12 md:col-6" v-for="[category, items] in grouped" :key="category">
            <Card class="shadow-1 h-full">
              <template #title>
                <div class="flex align-items-center justify-content-between">
                  <span>{{ category }}</span>
                  <Tag value="可配置" severity="info" />
                </div>
              </template>
              <template #content>
                <div class="flex flex-column gap-3">
                  <div
                    v-for="item in items"
                    :key="item.key"
                    class="flex justify-content-between gap-3 align-items-start"
                  >
                    <div class="flex flex-column gap-1">
                      <span class="font-medium">{{ item.label }}</span>
                      <span class="text-sm text-color-secondary">{{ item.description }}</span>
                    </div>
                    <InputSwitch
                      :modelValue="item.value ?? false"
                      :disabled="!item.editable"
                      @update:modelValue="(value) => toggleFlag(item, value)"
                    />
                  </div>
                </div>
              </template>
            </Card>
          </div>
        </div>
      </div>

      <div class="col-12">
        <h3 class="text-xl font-semibold mb-3">预留能力</h3>
        <div class="grid">
          <div class="col-12 md:col-4" v-for="placeholder in placeholders" :key="placeholder.key">
            <Card class="shadow-1 h-full">
              <template #title>
                <div class="flex align-items-center justify-content-between">
                  <span>{{ placeholder.label }}</span>
                  <Tag value="规划中" severity="warning" />
                </div>
              </template>
              <template #content>
                <p class="text-sm text-color-secondary mb-0">
                  {{ placeholder.description }}
                </p>
              </template>
            </Card>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>
