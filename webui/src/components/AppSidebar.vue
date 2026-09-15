<script setup lang="ts">
interface NavItem { label: string; icon: string; to: string }
const props = defineProps<{ items: NavItem[]; activePath: string }>();
const emit = defineEmits<{ (e: 'navigate'): void }>();

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
  <v-list nav density="comfortable" class="pa-3">
    <v-list-subheader>控制台导航</v-list-subheader>
    <v-list-item
      v-for="item in items"
      :key="item.to"
      :active="isActive(item)"
      color="primary"
      rounded="lg"
      :to="item.to"
      :prepend-icon="item.icon"
      :title="item.label"
      @click="emit('navigate')"
    />
  </v-list>
</template>
