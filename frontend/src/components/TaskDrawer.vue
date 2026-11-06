<script setup lang="ts">
/**
 * 全局任务抽屉：任何页面可查看任务进度（UI 规范 4.4）。
 * 行操作：进行中→取消；失败/超时→重试；点击展开错误详情。
 */
import { ref, computed } from 'vue'
import { ElDrawer, ElEmpty, ElProgress } from 'element-plus'
import { useTaskStore } from '@/stores/task'
import TaskStatusTag from './TaskStatusTag.vue'

const store = useTaskStore()
const visible = ref(false)
const expanded = ref<string | null>(null)
const filterType = ref('')
const filterStatus = ref('')

/** 暴露 open 方法给父组件。 */
function open() {
  visible.value = true
}
defineExpose({ open })

const typeLabels: Record<string, string> = {
  text: '剧本/文本', image: '关键帧', video: '视频', audio: '语音', asr: '字幕', render: '合成', unknown: '任务',
}

const filtered = computed(() =>
  [...store.tasks.values()]
    .filter((t) => (!filterType.value || t.type === filterType.value) && (!filterStatus.value || t.status === filterStatus.value))
    .sort((a, b) => b.task_id.localeCompare(a.task_id)),
)

/** 切换错误详情展开。 */
function toggleDetail(id: string) {
  expanded.value = expanded.value === id ? null : id
}
</script>

<template>
  <el-drawer v-model="visible" title="任务中心" size="480px">
    <div class="filters">
      <el-select v-model="filterType" placeholder="类型" clearable size="small" style="width: 120px">
        <el-option v-for="(label, key) in typeLabels" :key="key" :label="label" :value="key" />
      </el-select>
      <el-select v-model="filterStatus" placeholder="状态" clearable size="small" style="width: 120px">
        <el-option v-for="s in ['queued', 'processing', 'succeeded', 'failed', 'timeout', 'cancelled']" :key="s" :label="s" :value="s" />
      </el-select>
    </div>
    <el-empty v-if="filtered.length === 0" description="暂无任务" />
    <div v-for="t in filtered" :key="t.task_id" class="task-item" @click="toggleDetail(t.task_id)">
      <div class="row">
        <span class="type">{{ typeLabels[t.type] ?? t.type }}</span>
        <TaskStatusTag :status="t.status" />
        <span class="grow" />
        <span class="meta">{{ t.provider ?? '-' }} · ¥{{ t.cost.toFixed(2) }} · 重试{{ t.retry_count }}</span>
      </div>
      <el-progress v-if="t.status === 'processing' || t.status === 'queued'" :percentage="t.progress" :stroke-width="6" />
      <div v-if="expanded === t.task_id" class="detail">
        <div v-if="t.error_message" class="err">错误：{{ t.error_message }}</div>
        <pre class="payload">{{ JSON.stringify(t.request_payload ?? {}, null, 2) }}</pre>
      </div>
      <div class="actions" @click.stop>
        <el-button v-if="t.status === 'queued' || t.status === 'processing'" size="small" type="danger" text
          @click="store.cancel(t.task_id)">取消</el-button>
        <el-button v-if="['failed', 'timeout', 'cancelled'].includes(t.status)" size="small" type="primary" text
          @click="store.retry(t.task_id)">重试</el-button>
      </div>
    </div>
  </el-drawer>
</template>

<style scoped>
.filters {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}
.task-item {
  border: 1px solid var(--el-border-color-light);
  border-radius: 8px;
  padding: 10px;
  margin-bottom: 8px;
  cursor: pointer;
}
.row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.type {
  font-weight: 600;
}
.grow {
  flex: 1;
}
.meta {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.detail {
  margin-top: 8px;
  font-size: 12px;
}
.err {
  color: var(--el-color-danger);
}
.payload {
  max-height: 160px;
  overflow: auto;
  background: var(--el-fill-color-light);
  border-radius: 6px;
  padding: 6px;
}
.actions {
  display: flex;
  justify-content: flex-end;
}
</style>
