<script setup lang="ts">
import { computed } from 'vue';
import Menubar from 'primevue/menubar';
import type { MenuItem } from 'primevue/menuitem';

interface NavItem {
  label: string;
  icon: string;
  to: string;
}

const props = defineProps<{ items: NavItem[]; activePath: string }>();
const emit = defineEmits<{ (e: 'navigate', to: string): void }>();

const menuModel = computed<MenuItem[]>(() =>
  props.items.map((item) => ({
    label: item.label,
    icon: item.icon,
    command: () => emit('navigate', item.to),
    class: { active: props.activePath.startsWith(item.to) }
  }))
);
</script>

<template>
  <header class="surface-card border-bottom-1 surface-border">
    <Menubar :model="menuModel" class="max-w-full border-none">
      <template #start>
        <div class="flex align-items-center gap-2 pl-2">
          <i class="pi pi-shield text-primary text-xl"></i>
          <span class="font-semibold text-lg">ACG 图像管控后台</span>
        </div>
      </template>
      <template #end>
        <div class="pr-3 text-sm text-color-secondary">
          数据实时刷新，保障多群运营。
        </div>
      </template>
    </Menubar>
  </header>
</template>
