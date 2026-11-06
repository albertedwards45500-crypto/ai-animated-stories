<script setup lang="ts">
import { ElDialog } from 'element-plus'
/**
 * 素材/媒体预览弹窗：图片、视频、音频、字幕（UI 规范组件清单）。
 */
import { computed } from 'vue'

const props = defineProps<{ url: string; type: string; name?: string }>()
const visible = defineModel<boolean>({ default: false })

const mimePrefix = computed(() => {
  if (props.type === 'image') return 'image'
  if (props.type === 'video') return 'video'
  if (props.type === 'audio') return 'audio'
  return 'text'
})
</script>

<template>
  <el-dialog v-model="visible" :title="name ?? '预览'" width="720px" destroy-on-close>
    <img v-if="type === 'image'" :src="url" style="max-width: 100%" />
    <video v-else-if="type === 'video'" :src="url" controls style="width: 100%" />
    <audio v-else-if="type === 'audio'" :src="url" controls style="width: 100%" />
    <iframe v-else :src="url" style="width: 100%; height: 400px; border: none" />
    <template #footer>
      <el-button @click="visible = false">关闭</el-button>
      <a :href="url" :download="name ?? 'asset'">
        <el-button type="primary">下载</el-button>
      </a>
    </template>
  </el-dialog>
</template>
