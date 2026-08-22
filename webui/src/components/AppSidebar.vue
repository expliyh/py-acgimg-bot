<script setup lang="ts">
interface NavItem { label: string; icon: string; to: string }
defineProps<{ items: NavItem[]; activePath: string }>();
const emit = defineEmits<{ (e: 'navigate'): void }>();
</script>

<template>
  <v-list nav density="comfortable" class="pa-3">
    <v-list-subheader>控制台导航</v-list-subheader>
    <v-list-item
      v-for="item in items"
      :key="item.to"
      :active="activePath.startsWith(item.to)"
      color="primary"
      rounded="lg"
      :to="item.to"
      :prepend-icon="item.icon"
      :title="item.label"
      @click="emit('navigate')"
    />
  </v-list>
</template>
