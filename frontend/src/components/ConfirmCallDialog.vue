<script setup lang="ts">
import { ElDescriptions, ElDescriptionsItem, ElDialog } from 'element-plus'
/**
 * 真实 API 调用确认弹窗（UI 规范 5.1）。
 * 展示供应商、模型、预估信息，确认后回调。
 */
const visible = defineModel<boolean>({ default: false })
const props = defineProps<{ estimate: Record<string, unknown> }>()
const emit = defineEmits<{ confirm: [] }>()

/** 确认调用。 */
function onConfirm() {
  visible.value = false
  emit('confirm')
}
</script>

<template>
  <el-dialog v-model="visible" title="调用确认（将消耗真实 API 额度）" width="440px">
    <el-descriptions :column="1" border>
      <el-descriptions-item v-for="(v, k) in estimate" :key="k" :label="String(k)">{{ v }}</el-descriptions-item>
    </el-descriptions>
    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="warning" @click="onConfirm">确认调用</el-button>
    </template>
  </el-dialog>
</template>
