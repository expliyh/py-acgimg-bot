<template>
  <div class="layout">
    <Menubar :model="menuItems" class="shadow-2">
      <template #start>
        <div class="flex align-items-center gap-2">
          <i class="pi pi-discord text-2xl text-primary"></i>
          <span class="font-bold text-lg">ACG 管理面板</span>
        </div>
      </template>
    </Menubar>

    <div class="layout-body">
      <div class="sidebar p-3 surface-card shadow-2 border-round hidden lg:block">
        <PanelMenu :model="menuItems" />
      </div>
      <div class="content">
        <router-view />
      </div>
    </div>
    <Toast />
    <ConfirmDialog />
  </div>
</template>

<script setup lang="ts">
import Menubar from "primevue/menubar";
import PanelMenu from "primevue/panelmenu";
import Toast from "primevue/toast";
import ConfirmDialog from "primevue/confirmdialog";
import type { MenuItem } from "primevue/menuitem";

const menuItems: MenuItem[] = [
  {
    label: "仪表盘",
    icon: "pi pi-chart-pie",
    to: "/"
  },
  {
    label: "群组管理",
    icon: "pi pi-users",
    to: "/groups"
  },
  {
    label: "私聊管理",
    icon: "pi pi-comments",
    to: "/private-chats"
  },
  {
    label: "功能配置",
    icon: "pi pi-sliders-h",
    to: "/features"
  },
  {
    label: "自动化规则",
    icon: "pi pi-cog",
    to: "/automations"
  }
];
</script>

<style scoped>
.layout {
  display: flex;
  flex-direction: column;
  min-height: 100vh;
}

.layout-body {
  display: flex;
  flex: 1;
  padding: 1.5rem;
  gap: 1.5rem;
}

.sidebar {
  width: 16rem;
  height: calc(100vh - 6rem);
  position: sticky;
  top: 1.5rem;
}

.content {
  flex: 1;
}

@media (max-width: 992px) {
  .layout-body {
    flex-direction: column;
  }

  .sidebar {
    display: none;
  }
}
</style>
