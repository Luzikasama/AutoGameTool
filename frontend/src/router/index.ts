import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    // 唯一主界面就是编辑器：`/` 直接进入，不再有落地页/首页。
    // 保留 `/editor` 这个路径（旧书签、外部链接仍可用）。
    { path: '/', redirect: '/editor' },
    { path: '/editor', name: 'editor', component: () => import('../views/Editor.vue') },
    // 未匹配的路径一律回主界面（旧版 `/home` 链接会落到这里）
    { path: '/:pathMatch(.*)*', redirect: '/editor' },
  ],
})

export default router
