import { createRouter, createWebHistory } from 'vue-router'
import Home from '../views/Home.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    // 打开即进编辑器：不再停在"新建脚本 / 编辑脚本"的落地页。
    // 首页组件仍挂在 /home（旧链接、历史截图里的地址依旧可用），只是不再作为入口。
    { path: '/', redirect: '/editor' },
    { path: '/home', name: 'home', component: Home },
    { path: '/editor', name: 'editor', component: () => import('../views/Editor.vue') },
  ],
})

export default router
