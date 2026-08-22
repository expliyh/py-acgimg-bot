<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { useFeedback } from '@/composables/feedback';

import type { FeatureFlag, FeatureFlagResponse } from '@/services/api';
import { fetchFeatureFlags, updateFeatureFlag } from '@/services/api';

const { toast } = useFeedback();
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
  <section class="d-flex flex-column ga-4">
    <header class="d-flex flex-column ga-2">
      <h2 class="text-h5 font-weight-bold ma-0">功能配置</h2>
      <p class="text-medium-emphasis ma-0">
        管理全局功能开关，并预留未来拓展的配置位。
      </p>
      <VBtn prepend-icon="mdi-refresh" variant="outlined" @click="loadFlags" :loading="loading" class="w-100 w-md-auto">刷新</VBtn>
    </header>

    <VRow v-if="loading">
      <VCol cols="12" md="6" v-for="index in 4" :key="index">
        <VSkeletonLoader height="8rem" class="rounded-lg" />
      </VCol>
    </VRow>

    <div v-else class="d-flex flex-column ga-4">
      <div>
        <h3 class="text-h6 font-weight-bold mb-3">已上线功能</h3>
        <VRow>
          <VCol cols="12" md="6" v-for="[category, items] in grouped" :key="category">
            <VCard class="elevation-1 h-100">
              <VCardTitle>
                <div class="d-flex align-center justify-space-between">
                  <span>{{ category }}</span>
                  <VChip size="small" color="info">可配置</VChip>
                </div>
              </VCardTitle>
              <VCardText>
                <div class="d-flex flex-column ga-3">
                  <div
                    v-for="item in items"
                    :key="item.key"
                    class="d-flex justify-space-between ga-3 align-start"
                  >
                    <div class="d-flex flex-column ga-1">
                      <span class="font-weight-medium">{{ item.label }}</span>
                      <span class="text-body-2 text-medium-emphasis">{{ item.description }}</span>
                    </div>
                    <VSwitch
                      :model-value="item.value ?? false"
                      color="primary"
                      hide-details
                      density="compact"
                      :disabled="!item.editable"
                      @update:modelValue="(value: boolean | null) => toggleFlag(item, value ?? false)"
                    />
                  </div>
                </div>
              </VCardText>
            </VCard>
          </VCol>
          </VRow>
      </div>

      <div>
        <h3 class="text-h6 font-weight-bold mb-3">预留能力</h3>
        <VRow>
          <VCol cols="12" md="4" v-for="placeholder in placeholders" :key="placeholder.key">
            <VCard class="elevation-1 h-100">
              <VCardTitle>
                <div class="d-flex align-center justify-space-between">
                  <span>{{ placeholder.label }}</span>
                  <VChip size="small" color="warning">规划中</VChip>
                </div>
              </VCardTitle>
              <VCardText>
                <p class="text-body-2 text-medium-emphasis mb-0">
                  {{ placeholder.description }}
                </p>
              </VCardText>
            </VCard>
          </VCol>
          </VRow>
      </div>
    </div>
  </section>
</template>
