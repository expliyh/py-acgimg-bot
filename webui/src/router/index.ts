import { createRouter, createWebHistory } from 'vue-router';

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/groups/:id/guard',
      redirect: (to) => ({ name: 'group-management', params: { id: to.params.id } }),
    },
    { path: '/guard', redirect: { name: 'groups' } },
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
      path: '/groups/:id',
      name: 'group-management',
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
      path: '/illustrations',
      name: 'illustrations',
      component: () => import('@/views/IllustrationGalleryView.vue')
    },
    {
      path: '/illustrations/import',
      name: 'illustration-import',
      component: () => import('@/views/IllustrationImportView.vue')
    },
    {
      path: '/image-push',
      name: 'image-push',
      component: () => import('@/views/ImagePushView.vue')
    },
    {
      path: '/:pathMatch(.*)*',
      redirect: '/dashboard'
    }
  ]
});

let recoveringFromChunkError = false;

function isDynamicImportError(error: unknown): boolean {
  const message = error instanceof Error ? error.message : String(error);
  return /failed to fetch dynamically imported module|importing a module script failed|loading chunk .* failed/i.test(message);
}

// Lazy-loaded views can briefly become unavailable after a deployment or while
// Vite refreshes optimized dependencies. Keep sidebar navigation pointed at
// the requested destination instead of leaving the user on the old page.
router.onError((error, to) => {
  if (!isDynamicImportError(error) || recoveringFromChunkError) return;
  recoveringFromChunkError = true;
  window.location.assign(router.resolve(to).href);
});

export default router;
