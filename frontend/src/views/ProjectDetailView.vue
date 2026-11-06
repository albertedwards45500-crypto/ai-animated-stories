<script setup lang="ts">
/**
 * 项目详情页 /projects/:id（UI 规范 4.2）：项目信息 + 剧集列表 + 生成剧本。
 */
import { ref, onMounted, computed } from 'vue'
import {
  ElAlert, ElBreadcrumb, ElBreadcrumbItem, ElCard, ElDialog, ElForm, ElFormItem,
  ElInput, ElSlider, ElTable, ElTableColumn,
} from 'element-plus'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  getProject, listEpisodes, generateScript, updateProject,
  listCharacters, type Project, type Episode, type Character,
} from '@/api/modules'
import { useTaskStore } from '@/stores/task'
import { useTaskSSE } from '@/composables/useTaskSSE'

const route = useRoute()
const router = useRouter()
const store = useTaskStore()
const projectId = Number(route.params.id)

const project = ref<Project | null>(null)
const episodes = ref<Episode[]>([])
const characters = ref<Character[]>([])
const loading = ref(true)
const loadError = ref(false)
const dialogVisible = ref(false)
const generating = ref(false)
const saving = ref(false)
const epForm = ref({ title: '', story_outline: '', target_duration: 60 })
const epTotal = ref(0)

/** 当前剧集状态标签。 */
const epStatusLabels = ['草稿', '剧本已生成', '素材就绪', '已合成']
const epStatusTypes = ['info', 'primary', 'success', 'success']

/** 项目标题。 */
const header = computed(() => project.value?.name ?? '项目详情')

/** 编辑项目抽屉。 */
const editVisible = ref(false)
const editForm = ref<Partial<Project>>({})

async function load() {
  loading.value = true
  loadError.value = false
  try {
    const [projectData, episodeData, characterData] = await Promise.all([
      getProject(projectId), listEpisodes(projectId), listCharacters(projectId),
    ])
    project.value = projectData
    episodes.value = episodeData
    characters.value = characterData
    epTotal.value = episodes.value.length
    try {
      await store.restore(projectId)
    } catch {
      // 任务恢复失败不阻断项目内容展示，任务中心可稍后手动刷新。
    }
  } catch {
    loadError.value = true
  } finally {
    loading.value = false
  }
}

async function createEpisodeAndGenerate() {
  if (!epForm.value.title?.trim() || !epForm.value.story_outline?.trim()) {
    ElMessage.warning('标题与故事梗概必填（梗概上限 2000 字）')
    return
  }
  generating.value = true
  try {
    const resp = await generateScript(projectId, {
      episode: {
        title: epForm.value.title,
        story_outline: epForm.value.story_outline,
        target_duration: epForm.value.target_duration,
      },
    })
    dialogVisible.value = false
    store.track(resp)
    useTaskSSE(resp.task_id)
    ElMessage.success('剧本生成任务已提交，可在任务中心查看进度')
    await load()
  } finally {
    generating.value = false
  }
}

async function saveProject() {
  saving.value = true
  try {
    await updateProject(projectId, editForm.value)
    editVisible.value = false
    await load()
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="page">
    <el-breadcrumb style="margin-bottom: 12px">
      <el-breadcrumb-item to="/projects">项目</el-breadcrumb-item>
      <el-breadcrumb-item>{{ header }}</el-breadcrumb-item>
    </el-breadcrumb>

    <el-card shadow="never" class="info-card">
      <div class="info-row">
        <div>
          <h3 style="margin: 0">{{ project?.name }}</h3>
          <span class="sub">{{ project?.genre }} · 受众 {{ project?.audience || '-' }} · 单集 {{ project?.default_episode_duration }}s</span>
        </div>
        <el-button @click="editVisible = true; editForm = { ...project! }">编辑项目</el-button>
      </div>
    </el-card>

    <section class="role-library-band">
      <div class="role-band-copy">
        <span class="eyebrow">PROJECT SETTINGS</span>
        <h3>角色库</h3>
        <p>先固定人物设定和参考图，再让每一集的分镜引用同一套角色版本。</p>
        <div class="role-names">
          <span v-for="character in characters.slice(0, 4)" :key="character.id" class="role-name">
            <img v-if="character.reference_assets[0]" :src="character.reference_assets[0].raw_url" :alt="`${character.name}参考图`" />
            <span v-else class="role-dot">人</span>
            {{ character.name }}
          </span>
          <span v-if="characters.length > 4" class="role-more">+{{ characters.length - 4 }}</span>
          <span v-if="!characters.length" class="role-empty">还没有角色卡</span>
        </div>
      </div>
      <div class="role-band-side">
        <div class="role-count"><strong>{{ characters.length }}</strong><span>角色卡</span></div>
        <div class="role-count"><strong>{{ characters.filter((character) => character.confirmed).length }}</strong><span>已锁定</span></div>
        <el-button type="primary" @click="router.push(`/projects/${projectId}/characters`)">{{ characters.length ? '管理角色库' : '建立角色库' }}</el-button>
      </div>
    </section>

    <div class="header">
      <h3>剧集列表（{{ epTotal }}）</h3>
      <el-button type="primary" :disabled="generating" @click="dialogVisible = true; epForm = { title: '', story_outline: '', target_duration: project?.default_episode_duration ?? 60 }">
        新建剧集并生成剧本
      </el-button>
    </div>

    <el-alert v-if="loadError" type="error" :closable="false" title="项目数据加载失败，请检查网络后重试。">
      <el-button size="small" @click="load">重试</el-button>
    </el-alert>
    <el-table v-else :data="episodes" v-loading="loading" empty-text="还没有剧集，创建一集开始制作。">
      <el-table-column prop="episode_no" label="集号" width="70" />
      <el-table-column prop="title" label="标题" min-width="140" />
      <el-table-column prop="logline" label="简介" min-width="180" show-overflow-tooltip />
      <el-table-column label="状态" width="110">
        <template #default="{ row }">
          <el-tag :type="epStatusTypes[row.status]" size="small">{{ epStatusLabels[row.status] }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="shot_count" label="分镜数" width="80" />
      <el-table-column label="操作" width="220">
        <template #default="{ row }">
          <el-button size="small" type="primary" @click="router.push(`/episodes/${row.id}`)">进入工作台</el-button>
          <el-button size="small" @click="router.push(`/episodes/${row.id}/preview`)">预览</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialogVisible" title="新建剧集" width="560px">
      <el-form label-width="90px">
        <el-form-item label="标题" required>
          <el-input v-model="epForm.title" maxlength="200" />
        </el-form-item>
        <el-form-item label="故事梗概" required>
          <el-input v-model="epForm.story_outline" type="textarea" :rows="6" show-word-limit maxlength="2000"
            placeholder="输入故事梗概（2000 字以内），AI 将生成结构化剧本" />
        </el-form-item>
        <el-form-item label="目标时长">
          <el-slider v-model="epForm.target_duration" :min="30" :max="90" show-input />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="generating" @click="createEpisodeAndGenerate">生成剧本（异步任务）</el-button>
      </template>
    </el-dialog>

    <el-drawer v-model="editVisible" title="编辑项目" size="420px">
      <el-form label-width="110px">
        <el-form-item label="项目名"><el-input v-model="editForm.name" /></el-form-item>
        <el-form-item label="类型"><el-input v-model="editForm.genre" /></el-form-item>
        <el-form-item label="受众"><el-input v-model="editForm.audience" /></el-form-item>
        <el-form-item label="单集时长">
          <el-slider v-model="editForm.default_episode_duration" :min="30" :max="90" show-input />
        </el-form-item>
      </el-form>
      <el-button type="primary" :loading="saving" style="width: 100%" @click="saveProject">保存</el-button>
    </el-drawer>
  </div>
</template>

<style scoped>
.page {
  padding: 8px;
}
.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin: 16px 0 12px;
}
.info-card {
  margin-bottom: 8px;
}
.role-library-band {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  border: 1px solid var(--workspace-line);
  margin: 16px 0 24px;
  padding: 20px 22px;
  background: var(--el-bg-color);
}
.role-band-copy { min-width: 0; }
.eyebrow { color: var(--el-color-primary); font-size: 10px; font-weight: 700; letter-spacing: .12em; }
.role-band-copy h3 { margin: 6px 0 4px; font-size: 18px; }
.role-band-copy p { margin: 0 0 14px; color: var(--el-text-color-secondary); font-size: 13px; }
.role-names { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }
.role-name, .role-more, .role-empty { display: inline-flex; align-items: center; gap: 5px; color: var(--el-text-color-regular); font-size: 12px; }
.role-name { padding-right: 5px; }
.role-name img, .role-dot { width: 24px; height: 24px; border-radius: 4px; object-fit: cover; }
.role-dot { display: grid; place-items: center; color: var(--el-text-color-secondary); background: var(--el-fill-color); }
.role-more { color: var(--el-color-primary); }
.role-empty { color: var(--el-text-color-secondary); }
.role-band-side { display: flex; align-items: center; gap: 18px; flex-shrink: 0; }
.role-count { display: grid; gap: 3px; min-width: 48px; text-align: center; }
.role-count strong { font-size: 20px; line-height: 1; }
.role-count span { color: var(--el-text-color-secondary); font-size: 11px; }
.info-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.sub {
  color: var(--el-text-color-secondary);
  font-size: 13px;
}
@media (max-width: 720px) {
  .role-library-band { align-items: flex-start; flex-direction: column; }
  .role-band-side { width: 100%; flex-wrap: wrap; }
  .role-band-side .el-button { margin-left: auto; }
}
</style>
