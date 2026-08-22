<script setup lang="ts">
defineProps<{ dark: boolean }>();
const emit = defineEmits<{ (e: 'toggle-theme'): void; (e: 'toggle-drawer'): void }>();
</script>

<template>
  <v-app-bar flat border="b" color="surface">
    <v-app-bar-nav-icon class="d-md-none" aria-label="打开导航菜单" @click="emit('toggle-drawer')" />
    <v-icon icon="mdi-shield-star-outline" color="primary" class="ml-2" />
    <v-app-bar-title>ACG 图像管控后台</v-app-bar-title>
    <span class="text-body-2 text-medium-emphasis mr-3 d-none d-sm-inline">Material 3 控制台</span>
    <v-btn icon="mdi-theme-light-dark" variant="text" :aria-label="dark ? '切换亮色主题' : '切换暗色主题'" @click="emit('toggle-theme')" />
  </v-app-bar>
</template>
