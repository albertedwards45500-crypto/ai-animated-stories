<script setup lang="ts">
/**
 * 全局布局：顶栏（Logo/任务角标/设置）+ router-view + 任务抽屉。
 * 支持暗色主题切换（Element Plus dark 模式，阶段五）。
 */
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useDark, useToggle } from '@vueuse/core'
import { useRoute, useRouter } from 'vue-router'
import { Files, Film, List, Moon, Setting, Sunny } from '@element-plus/icons-vue'
import TaskDrawer from '@/components/TaskDrawer.vue'
import { useTaskStore } from '@/stores/task'
import { getReadiness, type Readiness } from '@/api/modules'

const router = useRouter()
const route = useRoute()
const store = useTaskStore()
const isDark = useDark()
const toggleDark = useToggle(isDark)
const drawerRef = ref<InstanceType<typeof TaskDrawer> | null>(null)
const readiness = ref<Readiness | null>(null)
const checkingReadiness = ref(false)
const readinessDetails = computed(() => Object.entries(readiness.value?.checks ?? {})
  .filter(([, check]) => check.status === 'down')
  .map(([name, check]) => check.message || `${name} 未就绪`).join('；'))
let readinessTimer: ReturnType<typeof setTimeout> | null = null
let disposed = false

/** 打开任务抽屉。 */
function openDrawer() {
  drawerRef.value?.open()
}

function isWorkspaceRoute() {
  return route.path.startsWith('/projects') || route.path.startsWith('/episodes')
}

function pageTitle() {
  if (route.path.startsWith('/projects/') && route.path.endsWith('/characters')) return '角色库'
  if (route.path.startsWith('/projects')) return '项目制作'
  if (route.path.startsWith('/episodes')) return '剧集工作台'
  if (route.path.startsWith('/assets')) return '素材库'
  if (route.path.startsWith('/tasks')) return '任务中心'
  if (route.path.startsWith('/settings')) return '设置'
  return '制作台'
}

async function checkReadiness() {
  if (checkingReadiness.value || disposed) return
  if (readinessTimer) clearTimeout(readinessTimer)
  checkingReadiness.value = true
  try {
    const result = await getReadiness()
    if (!disposed) readiness.value = result
  } catch {
    if (!disposed) readiness.value = { service: 'ai-drama', status: 'down', profile: 'unknown', checks: { api: { status: 'down', message: '后端服务不可达，请检查启动窗口或 logs 中的服务日志' } } }
  } finally {
    checkingReadiness.value = false
    if (!disposed) readinessTimer = setTimeout(() => void checkReadiness(), 15000)
  }
}

onMounted(() => {
  return checkReadiness()
})
onUnmounted(() => {
  disposed = true
  if (readinessTimer) clearTimeout(readinessTimer)
})
</script>

<template>
  <el-container class="app-root">
    <el-aside class="sidebar" width="236px">
      <div class="sidebar-inner">
        <button class="brand" type="button" @click="router.push('/projects')">
          <span class="brand-mark"><Film /></span>
          <span class="brand-copy"><strong>AI 漫剧</strong><small>STUDIO WORKSPACE</small></span>
        </button>

        <div class="nav-section-label">制作导航</div>
        <nav class="main-nav" aria-label="主要功能">
          <router-link to="/projects" class="nav-item" :class="{ 'is-active': isWorkspaceRoute() }" aria-label="项目制作" title="项目制作">
            <el-icon><Film /></el-icon><span>项目制作</span>
          </router-link>
          <router-link to="/assets" class="nav-item" :class="{ 'is-active': route.path.startsWith('/assets') }" aria-label="素材库" title="素材库">
            <el-icon><Files /></el-icon><span>素材库</span>
          </router-link>
          <router-link to="/tasks" class="nav-item" :class="{ 'is-active': route.path.startsWith('/tasks') }" aria-label="任务中心" title="任务中心">
            <el-icon><List /></el-icon><span>任务中心</span>
            <el-badge v-if="store.runningCount > 0" :value="store.runningCount" class="nav-badge" />
          </router-link>
        </nav>

        <div class="sidebar-footer">
          <router-link to="/settings" class="nav-item" :class="{ 'is-active': route.path.startsWith('/settings') }" aria-label="设置" title="设置">
            <el-icon><Setting /></el-icon><span>设置</span>
          </router-link>
          <div class="sidebar-note">创作流程<br><strong>企划 · 分镜 · 成片</strong></div>
        </div>
      </div>
    </el-aside>

    <el-container class="workspace">
      <el-header class="topbar" height="64px">
        <div class="page-heading">
          <span class="heading-kicker">AI DRAMA /</span>
          <span>{{ pageTitle() }}</span>
        </div>
        <div class="spacer" />
        <el-badge :value="store.runningCount" :hidden="store.runningCount === 0" class="task-badge">
          <el-button text class="quick-action" @click="openDrawer"><el-icon><List /></el-icon><span>打开任务</span></el-button>
        </el-badge>
        <el-button text class="theme-button" :aria-label="isDark ? '切换浅色主题' : '切换深色主题'" :title="isDark ? '切换浅色主题' : '切换深色主题'" @click="toggleDark()">
          <el-icon><Sunny v-if="isDark" /><Moon v-else /></el-icon>
        </el-button>
          <button v-if="readiness" class="service-status" type="button" :class="`is-${readiness.status}`" :disabled="checkingReadiness" :title="readinessDetails || '后端依赖已就绪，点击重新检查'" :aria-label="readiness.status === 'up' ? '后端服务就绪，点击重新检查' : '后端服务异常，点击重试'" @click="checkReadiness">
            <span class="status-dot" /><span>{{ readiness.status === 'up' ? '服务就绪' : '服务异常' }}</span>
          </button>
      </el-header>
      <el-main>
        <div v-if="readiness?.status === 'down'" class="service-warning" role="status" aria-live="polite">
          <span><strong>服务尚未就绪</strong> {{ readinessDetails }}</span>
          <el-button size="small" :loading="checkingReadiness" @click="checkReadiness">重新检查</el-button>
        </div>
        <router-view v-slot="{ Component }">
          <component :is="Component" :key="route.path" />
        </router-view>
      </el-main>
    </el-container>
    <TaskDrawer ref="drawerRef" />
  </el-container>
</template>

<style>
html.dark {
  color-scheme: dark;
}
.app-root {
  min-height: 100vh;
  background: var(--workspace-bg);
}
.sidebar {
  position: sticky;
  top: 0;
  z-index: 20;
  height: 100vh;
  flex-shrink: 0;
  border-right: 1px solid var(--workspace-line);
  background: var(--el-bg-color);
}
.sidebar-inner {
  display: flex;
  height: 100%;
  flex-direction: column;
  padding: 24px 14px 18px;
  box-sizing: border-box;
}
.brand {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  border: 0;
  padding: 0 10px;
  color: var(--el-text-color-primary);
  background: transparent;
  font: inherit;
  text-align: left;
  cursor: pointer;
}
.brand-copy {
  display: flex;
  flex-direction: column;
  gap: 2px;
  line-height: 1.1;
}
.brand-copy strong { font-size: 16px; }
.brand-copy small { color: var(--el-text-color-secondary); font-size: 8px; letter-spacing: .08em; }
.nav-section-label {
  margin: 42px 10px 10px;
  color: var(--el-text-color-secondary);
  font-size: 10px;
  font-weight: 700;
  letter-spacing: .12em;
}
.main-nav { display: grid; gap: 4px; }
.nav-item {
  position: relative;
  display: flex;
  align-items: center;
  gap: 11px;
  min-height: 42px;
  border-radius: 5px;
  padding: 0 12px;
  color: var(--el-text-color-regular);
  font-size: 13px;
  text-decoration: none;
  transition: color 160ms ease, background-color 160ms ease;
}
.nav-item:hover { color: var(--el-color-primary); background: var(--el-color-primary-light-9); }
.nav-item.is-active {
  color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
  font-weight: 600;
}
.nav-item.is-active::before {
  position: absolute;
  left: 0;
  width: 3px;
  height: 20px;
  border-radius: 0 2px 2px 0;
  background: var(--el-color-primary);
  content: '';
}
.nav-item .el-icon { font-size: 17px; }
.nav-badge { margin-left: auto; }
.sidebar-footer { display: grid; gap: 14px; margin-top: auto; }
.sidebar-note {
  border-top: 1px solid var(--workspace-line);
  padding: 14px 10px 0;
  color: var(--el-text-color-secondary);
  font-size: 11px;
  line-height: 1.7;
}
.sidebar-note strong { color: var(--el-text-color-regular); font-weight: 500; }
.workspace { min-width: 0; }
.topbar {
  position: sticky;
  top: 0;
  z-index: 10;
  display: flex;
  align-items: center;
  gap: 10px;
  border-bottom: 1px solid var(--workspace-line);
  background: var(--el-bg-color);
  padding: 0 24px;
}
.brand-mark {
  display: grid;
  width: 30px;
  height: 30px;
  place-items: center;
  border-radius: 6px;
  color: white;
  background: var(--el-color-primary);
  font-size: 17px;
}
.brand-mark :deep(svg) { width: 18px; height: 18px; }
.spacer { flex: 1; }
.page-heading { display: flex; align-items: baseline; gap: 8px; color: var(--el-text-color-primary); font-size: 15px; font-weight: 600; }
.heading-kicker { color: var(--el-color-primary); font-size: 9px; font-weight: 700; letter-spacing: .1em; }
.task-badge {
  margin-right: 4px;
}
.quick-action {
  min-height: 34px;
  color: var(--el-text-color-regular);
}
.theme-button {
  width: 34px;
  height: 34px;
  color: var(--el-text-color-regular);
}
.service-status { display: inline-flex; align-items: center; gap: 6px; border: 1px solid var(--workspace-line); border-radius: 5px; padding: 7px 9px; color: var(--el-text-color-regular); background: transparent; font: inherit; font-size: 11px; cursor: pointer; }
.status-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--el-color-success); }
.service-status.is-down .status-dot { background: var(--el-color-danger); }
.service-status:focus-visible { outline: 2px solid var(--el-color-primary); outline-offset: 2px; }
.service-warning { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 18px; border: 1px solid var(--el-color-warning-light-5); border-radius: 6px; padding: 12px 14px; color: var(--el-text-color-regular); background: var(--el-color-warning-light-9); font-size: 13px; line-height: 1.6; }
.service-warning strong { color: var(--el-color-warning-dark-2); margin-right: 8px; }
.service-warning .el-button { flex-shrink: 0; }
.app-root :deep(.el-main) {
  padding: 24px clamp(16px, 3vw, 40px);
}
@media (max-width: 600px) {
  .sidebar { width: 64px !important; }
  .sidebar-inner { padding: 18px 8px 12px; }
  .brand { justify-content: center; padding: 0; }
  .brand-copy, .nav-section-label, .nav-item span, .sidebar-note { display: none; }
  .nav-item { justify-content: center; padding: 0; }
  .nav-item.is-active::before { left: -8px; }
  .sidebar-footer { gap: 4px; }
  .topbar { gap: 4px; padding: 0 10px; }
  .page-heading { font-size: 13px; }
  .heading-kicker { display: none; }
  .service-status > span:last-child { display: none; }
  .service-warning { align-items: flex-start; flex-direction: column; }
  .quick-action span { display: none; }
  .brand-mark { width: 27px; height: 27px; }
  .app-root :deep(.el-main) { padding: 16px 12px; }
}
</style>
