<script setup lang="ts">
import { ElTag } from 'element-plus'
/**
 * 任务状态标签：统一色彩映射（UI 设计规范 3.1）。
 */
defineProps<{ status: string }>()

const typeMap: Record<string, 'success' | 'warning' | 'primary' | 'danger' | 'info'> = {
  succeeded: 'success',
  queued: 'warning',
  processing: 'primary',
  failed: 'danger',
  timeout: 'danger',
  cancelled: 'info',
}
const labelMap: Record<string, string> = {
  succeeded: '成功',
  queued: '排队中',
  processing: '处理中',
  failed: '失败',
  timeout: '超时',
  cancelled: '已取消',
}
</script>

<template>
  <el-tag :type="typeMap[status] ?? 'info'" :class="{ spinning: status === 'processing' }" size="small">
    {{ labelMap[status] ?? status }}
  </el-tag>
</template>

<style scoped>
.spinning {
  animation: pulse 1.2s infinite;
}
@keyframes pulse {
  50% {
    opacity: 0.6;
  }
}
</style>
