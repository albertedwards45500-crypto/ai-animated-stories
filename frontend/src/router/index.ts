/**
 * 路由配置：页面地图遵循《前端UI设计文档.md》第 1 节。
 */
import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/projects' },
    { path: '/projects', component: () => import('@/views/ProjectsView.vue') },
    { path: '/projects/:id/characters', component: () => import('@/views/CharacterLibraryView.vue') },
    { path: '/projects/:id', component: () => import('@/views/ProjectDetailView.vue') },
    { path: '/episodes/:id', component: () => import('@/views/EpisodeWorkbenchView.vue') },
    { path: '/episodes/:id/preview', component: () => import('@/views/PreviewView.vue') },
    { path: '/assets', component: () => import('@/views/AssetsView.vue') },
    { path: '/settings', component: () => import('@/views/SettingsView.vue') },
    { path: '/tasks', component: () => import('@/views/TasksView.vue') },
  ],
})

export default router
