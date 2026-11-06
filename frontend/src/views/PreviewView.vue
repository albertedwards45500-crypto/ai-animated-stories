<script setup lang="ts">
/**
 * 预览播放页 /episodes/:id/preview（UI 规范 4.5）。
 */
import { ref, onMounted, onUnmounted } from 'vue'
import { ElAlert, ElBreadcrumb, ElBreadcrumbItem } from 'element-plus'
import { useRoute } from 'vue-router'
import { listEpisodeJobs, type RenderJob } from '@/api/modules'
import TaskStatusTag from '@/components/TaskStatusTag.vue'

const route = useRoute()
const episodeId = Number(route.params.id)
const jobs = ref<RenderJob[]>([])
const current = ref<RenderJob | null>(null)
const loading = ref(true)
const loadError = ref(false)
let pollTimer: ReturnType<typeof setTimeout> | null = null
let disposed = false
let pending = false

/** 播放器跳转（分镜跳转列表简化为重新加载）。 */
function seekTo(job: RenderJob) {
  current.value = job
}

async function loadJobs() {
  if (pending || disposed) return
  pending = true
  stopPolling()
  try {
    const nextJobs = await listEpisodeJobs(episodeId)
    if (disposed) return
    jobs.value = nextJobs
    current.value = nextJobs.find((j) => j.job_id === current.value?.job_id)
      ?? nextJobs[0]
      ?? null
    loadError.value = false
  } catch {
    loadError.value = true
  } finally {
    pending = false
    loading.value = false
    if (!disposed && jobs.value.some((job) => ['queued', 'processing'].includes(job.status))) {
      pollTimer = setTimeout(() => void loadJobs(), 3000)
    }
  }
}

function stopPolling() {
  if (pollTimer) {
    clearTimeout(pollTimer)
    pollTimer = null
  }
}

onMounted(loadJobs)
onUnmounted(() => {
  disposed = true
  stopPolling()
})
</script>

<template>
  <div class="page">
    <el-breadcrumb style="margin-bottom: 12px">
      <el-breadcrumb-item :to="`/episodes/${episodeId}`">剧集工作台</el-breadcrumb-item>
      <el-breadcrumb-item>预览</el-breadcrumb-item>
    </el-breadcrumb>

    <div v-if="loading" v-loading="loading" class="loading-state" aria-label="加载合成记录" />
    <el-alert v-else-if="loadError" type="error" :closable="false" title="合成记录加载失败，请重试。">
      <el-button size="small" @click="loadJobs">重试</el-button>
    </el-alert>
    <el-empty v-else-if="!current" description="先完成合成">
      <el-button type="primary" @click="$router.push(`/episodes/${episodeId}`)">去工作台</el-button>
    </el-empty>

    <div v-else class="layout">
      <div class="player">
        <video v-if="current.status === 'succeeded'" :key="current.job_id" :src="current.preview_url" controls autoplay style="width: 100%; border-radius: 8px" />
        <div v-else class="rendering">
          <el-progress type="dashboard" :percentage="current.progress" />
          <p>{{ ['queued', 'processing'].includes(current.status) ? '合成中：拼接 → 混音 → 字幕 → 封装' : '本次合成未完成，请返回工作台重新合成。' }}</p>
          <TaskStatusTag :status="current.status" />
          <p v-if="current.error_message" class="err">{{ current.error_message }}</p>
          <el-button v-if="!['queued', 'processing'].includes(current.status)" @click="$router.push(`/episodes/${episodeId}`)">返回工作台</el-button>
        </div>
        <div class="ops">
          <a v-if="current.status === 'succeeded'" :href="current.download_url">
            <el-button type="primary">下载 MP4</el-button>
          </a>
        </div>
      </div>
      <div class="side">
        <h4>合成历史</h4>
        <button v-for="j in jobs" :key="j.job_id" type="button" class="job-item" :class="{ active: j.job_id === current?.job_id }" :aria-pressed="j.job_id === current?.job_id" @click="seekTo(j)">
          <span>{{ j.job_id.slice(0, 8) }}</span>
          <TaskStatusTag :status="j.status" />
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.layout {
  display: grid;
  grid-template-columns: 1fr 260px;
  gap: 16px;
}
.loading-state { min-height: 280px; }
.rendering {
  text-align: center;
  padding: 60px;
  border: 1px dashed var(--el-border-color);
  border-radius: 8px;
}
.err {
  color: var(--el-color-danger);
}
.side {
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color-light);
  border-radius: 8px;
  padding: 12px;
}
.job-item {
  display: flex;
  align-items: center;
  width: 100%;
  border: 0;
  color: var(--el-text-color-primary);
  background: transparent;
  font: inherit;
  justify-content: space-between;
  padding: 8px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 13px;
}
.job-item.active, .job-item:hover {
  background: var(--el-fill-color-light);
}
@media (max-width: 800px) {
  .layout { grid-template-columns: 1fr; }
  .side { order: -1; }
  .rendering { padding: 36px 16px; }
}
</style>
