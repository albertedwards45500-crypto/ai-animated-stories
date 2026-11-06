<script setup lang="ts">
/**
 * 素材库页 /assets（UI 规范 4.6）：筛选 + 网格 + 上传 + 预览。
 */
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ElAlert, ElCard, ElCol, ElEmpty, ElPagination, ElRow, ElUpload } from 'element-plus'
import { listAssets, uploadAsset, deleteAsset, listProjects, type Asset, type Project } from '@/api/modules'
import MediaPreview from '@/components/MediaPreview.vue'

const assets = ref<Asset[]>([])
const route = useRoute()
const total = ref(0)
const page = ref(1)
const filterType = ref('')
const initialProjectId = Number(route.query.project_id)
const filterProject = ref<number | undefined>(Number.isFinite(initialProjectId) && initialProjectId > 0 ? initialProjectId : undefined)
const uploadProject = ref<number | undefined>(filterProject.value)
const projects = ref<Project[]>([])
const loading = ref(false)
const loadError = ref(false)
const uploading = ref(false)
const previewVisible = ref(false)
const previewAsset = ref<Asset | null>(null)

const typeOptions = [
  { label: '图片', value: 'image' },
  { label: '视频', value: 'video' },
  { label: '音频', value: 'audio' },
  { label: '字幕', value: 'subtitle' },
]

async function load() {
  loading.value = true
  loadError.value = false
  try {
    const resp = await listAssets({
      page: page.value,
      page_size: 24,
      project_id: filterProject.value,
      asset_type: filterType.value || undefined,
    })
    assets.value = resp.items
    total.value = resp.total
  } catch {
    loadError.value = true
  } finally {
    loading.value = false
  }
}

/** 处理拖拽/选择上传。 */
async function onUpload(file: File) {
  if (!uploadProject.value) return
  const supported = file.type.startsWith('image/') || file.type.startsWith('video/')
    || file.type.startsWith('audio/') || /\.(srt|vtt)$/i.test(file.name)
  if (!supported) {
    ElMessage.warning('仅支持图片、视频、音频、SRT 或 VTT 字幕文件')
    return
  }
  uploading.value = true
  try {
    const type = file.type.startsWith('image/') ? 'image' : file.type.startsWith('video/') ? 'video'
      : file.type.startsWith('audio/') ? 'audio' : 'subtitle'
    await uploadAsset(file, uploadProject.value, type)
    filterProject.value = uploadProject.value
    page.value = 1
    await load()
  } finally {
    uploading.value = false
  }
}

function beforeUpload(file: File) {
  void onUpload(file).catch(() => { /* 请求拦截器已显示上传错误，保留项目选择以便重试。 */ })
  return false
}

async function remove(a: Asset) {
  try {
    await ElMessageBox.confirm(`确定删除素材「${a.file_name || '未命名文件'}」？`, '删除确认', { type: 'warning' })
    await deleteAsset(a.id)
    await load()
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') throw error
  }
}

function changeFilter() {
  page.value = 1
  void load()
}

function openPreview(a: Asset) {
  previewAsset.value = a
  previewVisible.value = true
}

async function initialize() {
  const [assetsResult, projectResult] = await Promise.allSettled([
    load(), listProjects({ page: 1, page_size: 100 }),
  ])
  if (projectResult.status === 'fulfilled') projects.value = projectResult.value.items
  else loadError.value = true
  if (assetsResult.status === 'rejected') loadError.value = true
}

onMounted(initialize)
</script>

<template>
  <div class="page">
    <div class="header">
      <h2>素材库</h2>
      <div class="toolbar">
        <el-select v-model="filterProject" clearable placeholder="全部项目" class="project-filter" @change="changeFilter">
          <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
        </el-select>
        <el-select v-model="filterType" clearable placeholder="类型" class="type-filter" @change="changeFilter">
          <el-option v-for="t in typeOptions" :key="t.value" :label="t.label" :value="t.value" />
        </el-select>
        <el-select v-model="uploadProject" placeholder="选择上传项目" class="project-filter">
          <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
        </el-select>
        <el-upload accept="image/*,video/*,audio/*,.srt,.vtt" :show-file-list="false" :before-upload="beforeUpload" :disabled="!uploadProject || uploading">
          <el-button type="primary" :loading="uploading" :disabled="!uploadProject">上传素材</el-button>
        </el-upload>
      </div>
    </div>

    <el-alert v-if="loadError" type="error" :closable="false" class="load-error" title="素材或项目列表加载失败。">
      <el-button size="small" @click="initialize">重试</el-button>
    </el-alert>
    <el-row v-loading="loading" :gutter="12">
      <el-col v-if="!loading && !loadError && assets.length === 0" :span="24">
        <el-empty :description="filterProject || filterType ? '没有符合条件的素材' : '素材库还是空的，选择项目后上传素材。'" />
      </el-col>
      <el-col v-for="a in assets" :key="a.id" :xs="12" :sm="8" :md="6" :lg="4">
        <el-card shadow="hover" class="asset-card" tabindex="0" role="button" :aria-label="`预览 ${a.file_name || '素材'}`" @keydown.enter.self="openPreview(a)" @click="openPreview(a)">
          <img v-if="a.asset_type === 'image'" :src="a.raw_url" :alt="a.file_name || '素材预览'" loading="lazy" decoding="async" class="thumb" />
          <video v-else-if="a.asset_type === 'video'" :src="a.raw_url" preload="none" class="thumb" />
          <div v-else class="thumb placeholder">{{ a.asset_type === 'audio' ? '♪ 音频' : 'T 字幕' }}</div>
          <div class="name">{{ a.file_name }}</div>
          <el-button size="small" text type="danger" @click.stop="remove(a)">删除</el-button>
        </el-card>
      </el-col>
    </el-row>
    <el-pagination
      v-if="total > 24"
      v-model:current-page="page"
      class="pagination"
      background
      layout="prev, pager, next, total"
      :page-size="24"
      :total="total"
      @current-change="load"
    />

    <MediaPreview v-model="previewVisible" :url="previewAsset?.raw_url ?? ''" :type="previewAsset?.asset_type ?? 'image'"
      :name="previewAsset?.file_name ?? undefined" />
  </div>
</template>

<style scoped>
.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}
.toolbar { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; justify-content: flex-end; }
.project-filter { width: 180px; }
.type-filter { width: 120px; }
.pagination { justify-content: flex-end; margin-top: 16px; }
.load-error { margin-bottom: 12px; }
.asset-card {
  margin-bottom: 12px;
  cursor: pointer;
}
.thumb {
  width: 100%;
  height: 110px;
  object-fit: cover;
  border-radius: 6px;
}
.placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--el-fill-color);
}
.name {
  font-size: 12px;
  margin: 6px 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
@media (max-width: 760px) {
  .header { align-items: flex-start; flex-direction: column; gap: 12px; }
  .toolbar { width: 100%; flex-wrap: wrap; }
  .toolbar :deep(.el-upload) { flex: 1; }
  .toolbar :deep(.el-upload .el-button) { width: 100%; }
  .project-filter { min-width: 140px; flex: 1; }
}
</style>
