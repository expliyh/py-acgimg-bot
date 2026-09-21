<script setup lang="ts">
import { computed } from 'vue';

interface NavItem { label: string; icon: string; to: string; group?: string }
const props = defineProps<{ items: NavItem[]; activePath: string }>();
const emit = defineEmits<{ (e: 'navigate'): void }>();
const groups = computed(() => [...new Set(props.items.map((item) => item.group ?? '控制台导航'))]
  .map((title) => ({ title, items: props.items.filter((item) => (item.group ?? '控制台导航') === title) })));

function isActive(item: NavItem): boolean {
  // Prefer an exact item when a route has a more specific sibling (for
  // example /illustrations/import); nested group routes still highlight the
  // /groups entry when there is no exact navigation item.
  const exact = props.items.find((candidate) => props.activePath === candidate.to);
  if (exact) return exact.to === item.to;
  return props.activePath.startsWith(`${item.to}/`);
}
</script>

<template>
  <nav aria-label="主导航" class="app-sidebar">
    <v-list v-for="group in groups" :key="group.title" nav density="comfortable" class="sidebar-group">
    <v-list-subheader>{{ group.title }}</v-list-subheader>
    <v-list-item
      v-for="item in group.items"
      :key="item.to"
      :active="isActive(item)"
      :aria-current="isActive(item) ? 'page' : undefined"
      color="primary"
      rounded="lg"
      :to="item.to"
      :prepend-icon="item.icon"
      :title="item.label"
      @click="emit('navigate')"
    />
    </v-list>
    <div class="sidebar-footer">
      <v-icon icon="mdi-shield-check-outline" size="18" color="primary" />
      <span>内容与群组，一处管理</span>
    </div>
  </nav>
</template>
