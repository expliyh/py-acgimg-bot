<script setup lang="ts">
import { normalizeVuetifyColor } from '@/composables/feedback';

const props = defineProps<{
  label: string;
  value: number | string;
  icon?: string;
  accent?: 'primary' | 'success' | 'warning' | 'danger';
  hint?: string;
}>();
</script>

<template>
  <v-card class="h-100 elevation-2 rounded-lg">
    <v-card-title>
      <div class="d-flex align-center justify-space-between">
        <span class="text-body-2 text-medium-emphasis">{{ props.label }}</span>
        <v-chip v-if="hint" :color="normalizeVuetifyColor(accent ?? 'primary')" rounded="pill" size="small">
          {{ hint }}
        </v-chip>
      </div>
    </v-card-title>
    <v-card-text>
      <div class="d-flex align-center ga-3 mt-2">
        <v-icon
          v-if="icon"
          :icon="icon"
          :color="normalizeVuetifyColor(accent ?? 'primary')"
          class="text-h4"
        />
        <span class="text-h4 font-weight-bold">{{ value }}</span>
      </div>
    </v-card-text>
  </v-card>
</template>
