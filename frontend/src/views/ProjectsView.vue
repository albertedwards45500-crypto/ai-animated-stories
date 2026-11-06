<script setup lang="ts">
/**
 * 项目列表页 /projects（UI 规范 4.1）。
 */
import { ref, onMounted } from 'vue'
import {
  ElCard, ElCol, ElDialog, ElEmpty, ElForm, ElFormItem, ElInput, ElRow,
  ElSelect, ElSkeleton, ElSlider,
} from 'element-plus'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowRight, EditPen, Film, Plus, VideoCameraFilled } from '@element-plus/icons-vue'
import {
  listProjects, createProject, deleteProject, updateProject, listStylePresets,
  type Project, type StylePreset,
} from '@/api/modules'

const projects = ref<Project[]>([])
const presets = ref<StylePreset[]>([])
const total = ref(0)
const page = ref(1)
const loading = ref(false)
const dialogVisible = ref(false)
const editing = ref<Project | null>(null)
const form = ref<Partial<Project>>({ name: '', genre: '', default_episode_duration: 60 })

async function load() {
  loading.value = true
  try {
    const resp = await listProjects({ page: page.value })
    projects.value = resp.items
    total.value = resp.total
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editing.value = null
  form.value = { name: '', genre: '', audience: '', default_episode_duration: 60, world_rules: undefined }
  dialogVisible.value = true
}

function openEdit(p: Project) {
  editing.value = p
  form.value = { ...p }
  dialogVisible.value = true
}

async function submit() {
  if (!form.value.name?.trim()) {
    ElMessage.warning('请填写项目名')
    return
  }
  if (editing.value) {
    await updateProject(editing.value.id, form.value)
  } else {
    await createProject(form.value)
  }
  dialogVisible.value = false
  await load()
}

async function remove(p: Project) {
  await ElMessageBox.confirm(`确定删除项目「${p.name}」？`, '删除确认', { type: 'warning' })
  await deleteProject(p.id)
  await load()
}

onMounted(async () => {
  await load()
  presets.value = await listStylePresets()
})
</script>

<template>
  <div class="page">
    <div class="header">
      <div>
        <div class="eyebrow">STUDIO / PROJECTS</div>
        <h2>我的项目</h2>
        <p class="intro">管理故事企划与剧集制作进度</p>
      </div>
      <el-button type="primary" class="create-button" @click="openCreate"><el-icon><Plus /></el-icon>新建项目</el-button>
    </div>
    <div class="collection-bar">
      <span>项目库</span>
      <span class="count">{{ total }} 个项目</span>
    </div>
    <el-skeleton v-if="loading" :rows="3" animated class="project-skeleton" />
    <el-empty v-else-if="projects.length === 0" description="还没有项目，从一个故事构想开始吧" class="empty-state">
      <el-button type="primary" @click="openCreate"><el-icon><Plus /></el-icon>创建第一个项目</el-button>
    </el-empty>
    <el-row v-else v-loading="loading" :gutter="18" class="project-grid">
      <el-col v-for="p in projects" :key="p.id" :xs="24" :sm="12" :md="8" :xl="6">
        <el-card class="project-card" shadow="never" tabindex="0" role="link" :aria-label="`打开项目 ${p.name}`" @click="$router.push(`/projects/${p.id}`)" @keydown.enter.self="$router.push(`/projects/${p.id}`)">
          <div class="cover" :class="`cover-tone-${p.id % 4}`">
            <div class="frame-corners" aria-hidden="true"><i /><i /><i /><i /></div>
            <el-icon class="cover-icon"><VideoCameraFilled /></el-icon>
            <span class="cover-label">STORY PROJECT</span>
          </div>
          <div class="project-info">
            <div class="title-row">
              <span class="name">{{ p.name }}</span>
              <el-tag size="small" effect="plain">{{ p.genre || '未分类' }}</el-tag>
            </div>
            <div class="sub"><span><el-icon><Film /></el-icon>{{ p.episode_count ?? 0 }} 集</span><span>更新于 {{ p.updated_at?.slice(0, 10) || '暂无' }}</span></div>
          </div>
          <div class="ops" @click.stop>
            <el-button size="small" text @click="openEdit(p)"><el-icon><EditPen /></el-icon>编辑</el-button>
            <el-button size="small" text type="danger" @click="remove(p)">删除</el-button>
            <el-button class="open-project" text aria-label="打开项目" @click="$router.push(`/projects/${p.id}`)"><el-icon><ArrowRight /></el-icon></el-button>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-dialog v-model="dialogVisible" :title="editing ? '编辑项目' : '新建项目'" width="520px">
      <el-form label-width="110px">
        <el-form-item label="项目名" required>
          <el-input v-model="form.name" maxlength="100" />
        </el-form-item>
        <el-form-item label="类型">
          <el-select v-model="form.genre" allow-create filterable placeholder="喜剧/悬疑/都市...">
            <el-option v-for="g in ['喜剧', '悬疑', '都市', '奇幻', '科幻']" :key="g" :label="g" :value="g" />
          </el-select>
        </el-form-item>
        <el-form-item label="目标受众">
          <el-input v-model="form.audience" placeholder="如：18-30 城市青年" />
        </el-form-item>
        <el-form-item label="默认画风">
          <el-select v-model="form.style_preset_id" clearable>
            <el-option v-for="s in presets" :key="s.id" :label="s.name" :value="s.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="单集时长(秒)">
          <el-slider v-model="form.default_episode_duration" :min="30" :max="90" show-input />
        </el-form-item>
        <el-form-item label="世界观/禁用">
          <el-input v-model="form.description" type="textarea" :rows="3" placeholder="世界观规则与禁用内容" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.page {
  max-width: 1440px;
  margin: 0 auto;
}
.header {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  margin: 4px 0 28px;
}
.eyebrow {
  color: var(--el-color-primary);
  font-size: 10px;
  font-weight: 700;
  line-height: 1.4;
}
h2 {
  margin: 5px 0 4px;
  color: var(--el-text-color-primary);
  font-size: 24px;
  font-weight: 650;
}
.intro {
  margin: 0;
  color: var(--el-text-color-secondary);
}
.create-button :deep(.el-icon) { margin-right: 5px; }
.collection-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 14px;
  color: var(--el-text-color-primary);
  font-size: 14px;
  font-weight: 600;
}
.count {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  font-weight: 400;
}
.project-card {
  position: relative;
  overflow: hidden;
  margin-bottom: 18px;
  cursor: pointer;
  border: 1px solid var(--workspace-line);
  border-radius: 6px;
  background: var(--el-bg-color);
  transition: transform 160ms ease, border-color 160ms ease, box-shadow 160ms ease;
}
.project-card:hover,
.project-card:focus-visible {
  transform: translateY(-2px);
  border-color: #8cbab5;
  box-shadow: 0 8px 22px rgb(20 56 52 / 9%);
}
.project-card :deep(.el-card__body) {
  padding: 0;
}
.cover {
  position: relative;
  display: grid;
  height: 132px;
  place-items: center;
  overflow: hidden;
  color: rgb(255 255 255 / 83%);
  background: #276e69;
}
.cover::after {
  position: absolute;
  inset: 0;
  background: linear-gradient(125deg, transparent 40%, rgb(255 255 255 / 12%) 40.2%, transparent 40.6%);
  content: '';
}
.cover-tone-1 { background: #435f77; }
.cover-tone-2 { background: #697050; }
.cover-tone-3 { background: #825f55; }
.cover-icon { font-size: 36px; opacity: .82; }
.cover-label {
  position: absolute;
  right: 12px;
  bottom: 10px;
  font-size: 9px;
  font-weight: 700;
}
.frame-corners i {
  position: absolute;
  z-index: 1;
  width: 13px;
  height: 13px;
  border-color: rgb(255 255 255 / 65%);
  border-style: solid;
}
.frame-corners i:nth-child(1) { top: 12px; left: 12px; border-width: 1px 0 0 1px; }
.frame-corners i:nth-child(2) { top: 12px; right: 12px; border-width: 1px 1px 0 0; }
.frame-corners i:nth-child(3) { bottom: 12px; left: 12px; border-width: 0 0 1px 1px; }
.frame-corners i:nth-child(4) { right: 12px; bottom: 12px; border-width: 0 1px 1px 0; }
.project-info { padding: 14px 14px 10px; }
.title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-width: 0;
}
.name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 600;
}
.sub {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
  margin-top: 11px;
}
.sub span:first-child { display: inline-flex; align-items: center; gap: 4px; }
.ops {
  display: flex;
  align-items: center;
  border-top: 1px solid var(--workspace-line);
  padding: 5px 8px;
}
.open-project {
  margin-left: auto;
  color: var(--el-color-primary);
}
.empty-state {
  padding: 50px 0;
  border: 1px dashed var(--workspace-line);
  border-radius: 6px;
  background: var(--el-bg-color);
}
.project-skeleton { max-width: 620px; }
@media (max-width: 600px) {
  .header { align-items: flex-start; gap: 12px; }
  h2 { font-size: 21px; }
  .intro { max-width: 220px; line-height: 1.5; }
  .create-button { flex-shrink: 0; }
  .cover { height: 118px; }
}
</style>
