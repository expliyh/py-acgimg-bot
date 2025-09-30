<script setup lang="ts">
import { computed } from 'vue';
import Listbox from 'primevue/listbox';

interface NavItem {
  label: string;
  icon: string;
  to: string;
}

const props = defineProps<{ items: NavItem[]; activePath: string }>();
const emit = defineEmits<{ (e: 'navigate', to: string): void }>();

interface SidebarOption {
  to: string;
  icon: string;
  label: string;
  value: string;
}

const options = computed<SidebarOption[]>(() =>
  props.items.map((item) => ({
    label: item.label,
    value: item.to,
    icon: item.icon,
    to: item.to
  }))
);

const selected = computed({
  get: () => props.activePath,
  set: (value: string) => emit('navigate', value)
});
</script>

<template>
  <aside class="h-full">
    <div class="p-3 border-bottom-1 surface-border text-sm text-color-secondary">
      控制台导航
    </div>
    <Listbox
      v-model="selected"
      :options="options"
      optionLabel="label"
      optionValue="value"
      class="w-full border-none"
    >
      <template #option="{ option, selected }">
        <div
          class="flex align-items-center gap-2 px-3 py-2 border-round transition-colors"
          :class="selected ? 'bg-primary-100 text-primary' : ''"
        >
          <i :class="[option.icon, 'text-lg']"></i>
          <span class="font-medium">{{ option.label }}</span>
        </div>
      </template>
    </Listbox>
  </aside>
</template>
