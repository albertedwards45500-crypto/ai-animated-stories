<script setup lang="ts">
/**
 * 全局任务中心页 /tasks：任务列表 + 成本统计（阶段五）。
 */
import { computed, ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElAlert, ElTable, ElTableColumn } from 'element-plus'
import { useTaskStore } from '@/stores/task'
import { getCostStats, listProjects, type CostStat, type Project } from '@/api/modules'
import TaskStatusTag from '@/components/TaskStatusTag.vue'

const store = useTaskStore()
const stats = ref<CostStat[]>([])
const projects = ref<Project[]>([])
const route = useRoute()
const initialProjectId = Number(route.query.project_id)
const selectedProjectId = ref<number | undefined>(Number.isFinite(initialProjectId) && initialProjectId > 0 ? initialProjectId : undefined)
const selectedTaskIds = ref<Set<string> | null>(null)
const loading = ref(false)
const loadError = ref(false)
let refreshVersion = 0

const visibleTasks = computed(() => {
  const all = [...store.tasks.values()]
  if (!selectedTaskIds.value) return all
  return all.filter((task) => selectedTaskIds.value?.has(task.task_id))
})

/** 恢复最近任务（全项目维度暂不查询，从本地缓存 + 刷新按钮恢复）。 */
async function refresh() {
  const version = ++refreshVersion
  const projectId = selectedProjectId.value
  loading.value = true
  loadError.value = false
  selectedTaskIds.value = projectId ? new Set() : null
  stats.value = []
  try {
    let taskIds: Set<string> | null = null
    if (projectId) {
      const items = await store.restore(projectId)
      taskIds = new Set(items.map((task) => task.task_id))
    }
    const nextStats = await getCostStats(projectId)
    if (version !== refreshVersion) return
    selectedTaskIds.value = taskIds
    stats.value = nextStats
  } catch {
    if (version === refreshVersion) loadError.value = true
  } finally {
    if (version === refreshVersion) loading.value = false
  }
}

async function initialize() {
  loading.value = true
  loadError.value = false
  try {
    const response = await listProjects({ page: 1, page_size: 100 })
    projects.value = response.items
    if (!selectedProjectId.value && projects.value[0]) selectedProjectId.value = projects.value[0].id
    await refresh()
  } catch {
    loadError.value = true
    loading.value = false
  }
}

onMounted(initialize)
</script>

<template>
  <div class="page">
    <div class="header">
      <h2>任务中心</h2>
      <div class="header-actions">
        <el-select v-model="selectedProjectId" clearable placeholder="全部缓存任务" class="project-select" @change="refresh">
          <el-option v-for="project in projects" :key="project.id" :label="project.name" :value="project.id" />
        </el-select>
        <el-button :loading="loading" @click="refresh">刷新</el-button>
      </div>
    </div>
    <el-alert v-if="loadError" type="error" :closable="false" title="任务或项目数据加载失败。">
      <el-button size="small" @click="initialize">重试</el-button>
    </el-alert>
    <el-alert v-else-if="visibleTasks.length === 0" type="info" :closable="false"
      title="当前项目暂无任务记录。生成剧本、分镜或成片后，任务会自动出现在这里。" />
    <el-table v-loading="loading" :data="visibleTasks" empty-text="暂无任务">
      <el-table-column prop="type" label="类型" width="90" />
      <el-table-column label="状态" width="100">
        <template #default="{ row }"><TaskStatusTag :status="row.status" /></template>
      </el-table-column>
      <el-table-column label="进度" width="180">
        <template #default="{ row }"><el-progress :percentage="row.progress" :stroke-width="8" /></template>
      </el-table-column>
      <el-table-column prop="provider" label="Provider" width="100" />
      <el-table-column prop="retry_count" label="重试" width="70" />
      <el-table-column label="费用" width="90">
        <template #default="{ row }">¥{{ (row.cost ?? 0).toFixed(2) }}</template>
      </el-table-column>
      <el-table-column prop="error_message" label="错误" min-width="200" show-overflow-tooltip />
      <el-table-column label="操作" width="140">
        <template #default="{ row }">
          <el-button v-if="['queued', 'processing'].includes(row.status)" size="small" type="danger" text
            @click="store.cancel(row.task_id)">取消</el-button>
          <el-button v-if="['failed', 'timeout', 'cancelled'].includes(row.status)" size="small" type="primary" text
            @click="store.retry(row.task_id)">重试</el-button>
        </template>
      </el-table-column>
    </el-table>

    <h3 style="margin: 24px 0 8px">成本统计（按 Provider/模型）</h3>
    <el-table :data="stats">
      <el-table-column prop="provider" label="Provider" width="110" />
      <el-table-column prop="model" label="模型" width="120" />
      <el-table-column prop="total_calls" label="调用量" width="90" />
      <el-table-column prop="succeeded" label="成功" width="80" />
      <el-table-column prop="failed" label="失败/超时" width="100" />
      <el-table-column label="成功率" width="90">
        <template #default="{ row }">{{ (row.success_rate * 100).toFixed(1) }}%</template>
      </el-table-column>
      <el-table-column label="总费用" width="100">
        <template #default="{ row }">¥{{ row.total_cost.toFixed(4) }}</template>
      </el-table-column>
      <el-table-column label="平均耗时(ms)" width="120">
        <template #default="{ row }">{{ row.avg_elapsed_ms ?? '-' }}</template>
      </el-table-column>
    </el-table>
  </div>
</template>

<style scoped>
.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}
.header-actions { display: flex; align-items: center; gap: 8px; }
.project-select { width: 190px; }
@media (max-width: 640px) {
  .header { align-items: flex-start; flex-direction: column; gap: 10px; }
  .header-actions { width: 100%; }
  .project-select { flex: 1; }
}
</style>
