import { createRouter, createWebHistory } from 'vue-router';

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      redirect: '/dashboard'
    },
    {
      path: '/dashboard',
      name: 'dashboard',
      component: () => import('@/views/DashboardView.vue')
    },
    {
      path: '/groups',
      name: 'groups',
      component: () => import('@/views/GroupsView.vue')
    },
    {
      path: '/private',
      name: 'private',
      component: () => import('@/views/PrivateChatsView.vue')
    },
    {
      path: '/commands',
      name: 'commands',
      component: () => import('@/views/CommandHistoryView.vue')
    },
    {
      path: '/features',
      name: 'features',
      component: () => import('@/views/FeatureConfigView.vue')
    },
    {
      path: '/bot-tokens',
      name: 'bot-tokens',
      component: () => import('@/views/BotTokensView.vue')
    },
    {
      path: '/pixiv-tokens',
      name: 'pixiv-tokens',
      component: () => import('@/views/PixivTokensView.vue')
    },
    {
      path: '/illustrations/import',
      name: 'illustration-import',
      component: () => import('@/views/IllustrationImportView.vue')
    },
    {
      path: '/:pathMatch(.*)*',
      redirect: '/dashboard'
    }
  ]
});

export default router;
