import { createRouter, createWebHistory } from "vue-router";

const Dashboard = () => import("../views/DashboardView.vue");
const Groups = () => import("../views/GroupManagementView.vue");
const PrivateChats = () => import("../views/PrivateChatManagementView.vue");
const Features = () => import("../views/FeatureConfigView.vue");
const Automations = () => import("../views/AutomationRuleView.vue");

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", component: Dashboard, name: "dashboard" },
    { path: "/groups", component: Groups, name: "groups" },
    { path: "/private-chats", component: PrivateChats, name: "private-chats" },
    { path: "/features", component: Features, name: "features" },
    { path: "/automations", component: Automations, name: "automations" }
  ]
});

export default router;
