<script setup lang="ts">
/**
 * 项目级角色库：集中维护角色卡、参考图和锁定版本。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { ElBreadcrumb, ElBreadcrumbItem, ElEmpty, ElForm, ElFormItem, ElInput } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  createCharacter, listCharacters, updateCharacter, confirmCharacter,
  uploadCharacterAsset, setPrimaryCharacterAsset, generateCharacterImage,
  type Character,
} from '@/api/modules'
import { useTaskStore } from '@/stores/task'
import { useTaskSSE } from '@/composables/useTaskSSE'

const route = useRoute()
const router = useRouter()
const projectId = Number(route.params.id)
const taskStore = useTaskStore()

const characters = ref<Character[]>([])
const selectedId = ref<number | null>(null)
const loading = ref(false)
const editing = ref(false)
type CharacterForm = Partial<Pick<Character, 'name' | 'age_range' | 'gender_presentation' | 'hair' | 'face_features' | 'body_shape' | 'clothing' | 'voice_id'>>
const form = ref<CharacterForm>({})
const fileInput = ref<HTMLInputElement | null>(null)
const generatingTaskId = ref<string | null>(null)
const generating = computed(() => !!generatingTaskId.value &&
  ['queued', 'processing'].includes(taskStore.tasks.get(generatingTaskId.value)?.status ?? ''))

const selected = computed(() => characters.value.find((item) => item.id === selectedId.value) ?? null)
const selectedAssets = computed(() => selected.value?.reference_assets ?? [])

async function load() {
  loading.value = true
  try {
    characters.value = await listCharacters(projectId)
    if (!selectedId.value && characters.value[0]) selectedId.value = characters.value[0].id
    if (selectedId.value && !characters.value.some((item) => item.id === selectedId.value)) {
      selectedId.value = characters.value[0]?.id ?? null
    }
    if (selected.value) form.value = { ...selected.value }
  } finally {
    loading.value = false
  }
}

function selectCharacter(character: Character) {
  selectedId.value = character.id
  form.value = { ...character }
  editing.value = false
}

function startCreate() {
  selectedId.value = null
  form.value = { name: '', hair: '', face_features: '', body_shape: '', clothing: '', voice_id: '' }
  editing.value = true
}

function startEdit() {
  if (!selected.value || selected.value.confirmed) return
  form.value = { ...selected.value }
  editing.value = true
}

async function save() {
  const name = String(form.value.name ?? '').trim()
  if (!name) {
    ElMessage.warning('角色名不能为空')
    return
  }
  if (selected.value) {
    await updateCharacter(selected.value.id, form.value)
    ElMessage.success('角色卡已保存')
  } else {
    const created = await createCharacter(projectId, form.value)
    selectedId.value = created.id
    ElMessage.success('角色卡已创建')
  }
  editing.value = false
  await load()
}

async function lockSelected() {
  if (!selected.value) return
  await confirmCharacter(selected.value.id)
  ElMessage.success('角色卡已锁定，后续分镜将固定引用当前版本')
  await load()
}

function openUpload() {
  if (!selected.value || selected.value.confirmed) return
  fileInput.value?.click()
}

async function onFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file || !selected.value) return
  await uploadCharacterAsset(selected.value.id, file)
  input.value = ''
  ElMessage.success('参考图已上传')
  await load()
}

async function makePrimary(assetId: number) {
  if (!selected.value || selected.value.confirmed) return
  await setPrimaryCharacterAsset(selected.value.id, assetId)
  ElMessage.success('主参考图已更新')
  await load()
}

async function generatePortrait(confirm = false) {
  if (!selected.value || generating.value) return
  const characterId = selected.value.id
  const variantId = crypto.randomUUID()
  try {
    let accepted = await generateCharacterImage(characterId, confirm, variantId)
    if (accepted.require_confirm) {
      await ElMessageBox.confirm('即将调用真实图片模型，可能产生费用。确定生成角色形象图吗？', '确认生成', {
        confirmButtonText: '生成', cancelButtonText: '取消', type: 'warning',
      })
      accepted = await generateCharacterImage(characterId, true, variantId)
    }
    generatingTaskId.value = accepted.task_id
    if (!accepted.cached && (accepted.status === 'queued' || accepted.status === 'processing')) {
      taskStore.track(accepted)
      taskStore.update(accepted.task_id, { type: 'image', project_id: projectId })
    }
    if (!accepted.cached && (accepted.status === 'queued' || accepted.status === 'processing')) useTaskSSE(accepted.task_id)
    if (accepted.status === 'succeeded') {
      generatingTaskId.value = null
      await load()
      ElMessage.success('角色形象已生成，可选择主参考图并确认锁定')
    } else {
      ElMessage.info('角色形象生成中，完成后会加入参考图')
    }
  } catch (error) {
    if (error !== 'cancel') ElMessage.error('角色形象生成未能提交')
  }
}

watch(() => generatingTaskId.value && taskStore.tasks.get(generatingTaskId.value)?.status,
  async (status) => {
    if (status === 'succeeded') {
      generatingTaskId.value = null
      await load()
      ElMessage.success('角色形象已生成，可选择主参考图并确认锁定')
    } else if (status && ['failed', 'timeout', 'cancelled'].includes(status)) {
      generatingTaskId.value = null
      ElMessage.error('角色形象生成失败，请在任务中心查看原因')
    }
  })

onMounted(load)
</script>

<template>
  <div class="page character-library">
    <div class="library-head">
      <div>
        <el-breadcrumb>
          <el-breadcrumb-item @click="router.push('/projects')">项目</el-breadcrumb-item>
          <el-breadcrumb-item @click="router.push(`/projects/${projectId}`)">项目详情</el-breadcrumb-item>
          <el-breadcrumb-item>角色库</el-breadcrumb-item>
        </el-breadcrumb>
        <h2>角色库</h2>
        <p>统一维护人物设定、参考图和锁定版本，供所有剧集分镜引用。</p>
      </div>
      <el-button type="primary" @click="startCreate">新建角色</el-button>
    </div>

    <div class="library-layout" v-loading="loading">
      <section class="character-list" aria-label="角色列表">
        <div v-if="!characters.length" class="empty-state">
          <strong>还没有角色</strong>
          <span>先建立角色卡，再为分镜选择出场人物。</span>
          <el-button type="primary" plain @click="startCreate">创建第一张角色卡</el-button>
        </div>
        <button
          v-for="character in characters"
          :key="character.id"
          type="button"
          class="character-row"
          :class="{ selected: character.id === selectedId }"
          @click="selectCharacter(character)"
        >
          <img v-if="character.reference_assets[0]" :src="character.reference_assets[0].raw_url" :alt="`${character.name}参考图`" />
          <div v-else class="avatar-placeholder">人</div>
          <span class="character-row-copy">
            <strong>{{ character.name }}</strong>
            <small>{{ character.code }} · v{{ character.version }}</small>
          </span>
          <el-tag v-if="character.confirmed" size="small" type="success">已锁定</el-tag>
        </button>
      </section>

      <section v-if="selected || editing" class="character-detail">
        <div v-if="editing" class="detail-form">
          <div class="detail-heading"><div><span class="eyebrow">CHARACTER CARD</span><h3>{{ selected ? '编辑角色卡' : '新建角色卡' }}</h3></div></div>
          <el-form label-position="top">
            <el-form-item label="角色名" required><el-input v-model="form.name" placeholder="如：林夏" /></el-form-item>
            <div class="form-grid">
              <el-form-item label="年龄段"><el-input v-model="form.age_range" placeholder="如：20-25岁" /></el-form-item>
              <el-form-item label="性别呈现"><el-input v-model="form.gender_presentation" placeholder="如：女性" /></el-form-item>
            </div>
            <el-form-item label="发型发色"><el-input v-model="form.hair" placeholder="固定外观描述" /></el-form-item>
            <el-form-item label="五官特征"><el-input v-model="form.face_features" placeholder="脸型、眼睛、标志性特征" /></el-form-item>
            <el-form-item label="体型"><el-input v-model="form.body_shape" placeholder="如：纤细、修长" /></el-form-item>
            <el-form-item label="服装"><el-input v-model="form.clothing" placeholder="固定服装和配饰" /></el-form-item>
            <el-form-item label="音色 ID"><el-input v-model="form.voice_id" placeholder="供应商音色 ID" /></el-form-item>
          </el-form>
          <div class="form-actions"><el-button @click="editing = false">取消</el-button><el-button type="primary" @click="save">保存角色卡</el-button></div>
        </div>

        <div v-else class="detail-content">
          <div class="detail-heading">
            <div><span class="eyebrow">CHARACTER CARD / {{ selected?.code }}</span><h3>{{ selected?.name }}</h3></div>
            <el-tag v-if="selected?.confirmed" type="success">已锁定 v{{ selected?.version }}</el-tag>
            <el-tag v-else type="warning">草稿 v{{ selected?.version }}</el-tag>
          </div>

          <div class="reference-section">
            <div class="section-heading"><div><h4>参考图</h4><span>先生成或上传角色形象，选择主图，再确认锁定；分镜将引用相同角色版本。</span></div><div class="reference-actions" v-if="!selected?.confirmed"><el-button size="small" :loading="generating" @click="generatePortrait()">AI 生成形象</el-button><el-button size="small" @click="openUpload">上传参考图</el-button></div></div>
            <input ref="fileInput" class="hidden-input" type="file" accept="image/png,image/jpeg,image/webp" @change="onFileChange" />
            <div v-if="selectedAssets.length" class="asset-grid">
              <button v-for="asset in selectedAssets" :key="asset.id" type="button" class="asset-tile" @click="makePrimary(asset.asset_id)">
                <img :src="asset.raw_url" :alt="asset.file_name || '角色参考图'" />
                <span v-if="asset.is_primary" class="primary-mark">主参考图</span>
                <span v-else class="asset-name">设为主参考图</span>
              </button>
            </div>
            <div v-else class="reference-empty">根据角色卡 AI 生成正面形象，或上传已有图片；选定主参考图后再确认锁定。</div>
          </div>

          <div class="traits-grid">
            <div><span>年龄段</span><strong>{{ selected?.age_range || '未设置' }}</strong></div>
            <div><span>性别呈现</span><strong>{{ selected?.gender_presentation || '未设置' }}</strong></div>
            <div><span>发型发色</span><strong>{{ selected?.hair || '未设置' }}</strong></div>
            <div><span>五官特征</span><strong>{{ selected?.face_features || '未设置' }}</strong></div>
            <div><span>体型</span><strong>{{ selected?.body_shape || '未设置' }}</strong></div>
            <div><span>服装</span><strong>{{ selected?.clothing || '未设置' }}</strong></div>
          </div>

          <div class="detail-actions"><el-button v-if="!selected?.confirmed" @click="startEdit">编辑角色卡</el-button><el-button v-if="!selected?.confirmed" type="primary" @click="lockSelected">确认并锁定</el-button><el-button @click="router.push(`/projects/${projectId}`)">返回项目</el-button></div>
        </div>
      </section>
      <section v-else class="character-detail empty-detail"><span>选择左侧角色查看详情</span></section>
    </div>
  </div>
</template>

<style scoped>
.character-library { padding: 8px; }
.library-head { display: flex; align-items: flex-end; justify-content: space-between; gap: 24px; margin-bottom: 20px; }
.library-head h2 { margin: 16px 0 6px; font-size: 24px; }
.library-head p { margin: 0; color: var(--el-text-color-secondary); font-size: 13px; }
.library-layout { display: grid; grid-template-columns: minmax(260px, 320px) minmax(0, 1fr); gap: 16px; min-height: 520px; }
.character-list, .character-detail { border: 1px solid var(--workspace-line); background: var(--el-bg-color); }
.character-list { padding: 8px; }
.character-row { display: flex; align-items: center; gap: 10px; width: 100%; border: 0; border-bottom: 1px solid var(--workspace-line); padding: 10px 8px; color: var(--el-text-color-primary); background: transparent; text-align: left; cursor: pointer; }
.character-row:last-child { border-bottom: 0; }
.character-row:hover, .character-row.selected { background: var(--el-color-primary-light-9); }
.character-row img, .avatar-placeholder { width: 42px; height: 42px; flex: 0 0 42px; border-radius: 5px; object-fit: cover; background: var(--el-fill-color); }
.avatar-placeholder { display: grid; place-items: center; color: var(--el-text-color-secondary); font-size: 16px; }
.character-row-copy { display: grid; min-width: 0; flex: 1; gap: 4px; }
.character-row-copy strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.character-row-copy small { color: var(--el-text-color-secondary); }
.empty-state, .empty-detail { display: grid; place-items: center; align-content: center; gap: 10px; min-height: 480px; color: var(--el-text-color-secondary); text-align: center; }
.empty-state strong { color: var(--el-text-color-primary); }
.character-detail { padding: 24px; }
.detail-heading, .section-heading, .detail-actions, .form-actions { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.detail-heading { margin-bottom: 24px; }
.detail-heading h3 { margin: 6px 0 0; font-size: 22px; }
.eyebrow { color: var(--el-color-primary); font-size: 10px; font-weight: 700; letter-spacing: .12em; }
.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.form-actions { justify-content: flex-end; margin-top: 8px; }
.section-heading { margin-bottom: 12px; }
.section-heading h4 { margin: 0 0 4px; }
.section-heading span { color: var(--el-text-color-secondary); font-size: 12px; }
.reference-actions { display: flex; flex-wrap: wrap; gap: 8px; flex-shrink: 0; }
.reference-actions .el-button + .el-button { margin-left: 0; }
.hidden-input { display: none; }
.asset-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 10px; }
.asset-tile { position: relative; overflow: hidden; min-height: 160px; border: 1px solid var(--workspace-line); padding: 0; background: var(--el-fill-color-lighter); cursor: pointer; }
.asset-tile img { display: block; width: 100%; height: 160px; object-fit: cover; }
.primary-mark, .asset-name { position: absolute; right: 6px; bottom: 6px; left: 6px; padding: 4px 6px; color: white; background: rgb(20 27 35 / 78%); font-size: 11px; text-align: center; }
.primary-mark { color: var(--el-color-success-light-3); }
.reference-empty { border: 1px dashed var(--el-border-color); padding: 28px 16px; color: var(--el-text-color-secondary); font-size: 13px; text-align: center; }
.traits-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 1px; margin: 24px 0; border: 1px solid var(--workspace-line); background: var(--workspace-line); }
.traits-grid > div { display: grid; gap: 7px; min-height: 70px; padding: 12px; background: var(--el-bg-color); }
.traits-grid span { color: var(--el-text-color-secondary); font-size: 12px; }
.traits-grid strong { font-size: 13px; font-weight: 500; }
.detail-actions { justify-content: flex-start; }
@media (max-width: 800px) { .library-head { align-items: flex-start; flex-direction: column; } .library-layout { grid-template-columns: 1fr; } .character-list { max-height: 280px; overflow: auto; } }
@media (max-width: 480px) { .character-detail { padding: 16px; } .form-grid, .traits-grid { grid-template-columns: 1fr; } .section-heading { align-items: flex-start; flex-direction: column; } }
</style>
