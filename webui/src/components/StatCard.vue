<script setup lang="ts">
import Card from 'primevue/card';
import Tag from 'primevue/tag';

const props = defineProps<{
  label: string;
  value: number | string;
  icon?: string;
  accent?: 'primary' | 'success' | 'warning' | 'danger';
  hint?: string;
}>();
</script>

<template>
  <Card class="h-full shadow-2 border-round-lg">
    <template #title>
      <div class="flex align-items-center justify-content-between">
        <span class="text-sm text-color-secondary">{{ props.label }}</span>
        <Tag v-if="hint" :value="hint" :severity="accent ?? 'primary'" rounded />
      </div>
    </template>
    <template #content>
      <div class="flex align-items-center gap-3 mt-2">
        <i v-if="icon" :class="[icon, 'text-3xl', `text-${accent ?? 'primary'}`]"></i>
        <span class="text-3xl font-semibold">{{ value }}</span>
      </div>
    </template>
  </Card>
</template>
