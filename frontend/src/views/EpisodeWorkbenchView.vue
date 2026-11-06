<script setup lang="ts">
/**
 * 剧集工作台 /episodes/:id（UI 规范 4.3，核心页面）。
 * 左栏剧本树；中栏分镜卡片流/时间轴切换；右栏角色/场景/画风面板；底部操作条。
 */
import { ref, computed, onMounted, watch, nextTick } from 'vue'
import { useMediaQuery } from '@vueuse/core'
import { Delete, EditPen, Microphone, Picture, Plus, VideoCamera } from '@element-plus/icons-vue'
import {
  ElAlert, ElCard, ElDialog, ElEmpty, ElForm, ElFormItem, ElInput, ElInputNumber,
  ElRadioButton, ElRadioGroup, ElTabPane, ElTabs,
} from 'element-plus'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  getEpisode, listEpisodeShots, updateShot, deleteShot, createScene, createShot,
  generateImage, generateVideo, generateAudio, generateAsr, createRenderJob,
  listCharacters, createCharacter, confirmCharacter, listLocations, createLocation,
  listStylePresets, type Episode, type Shot, type Character, type LocationCard, type StylePreset,
  type TaskAccept,
} from '@/api/modules'
import { useTaskStore } from '@/stores/task'
import { useTaskSSE } from '@/composables/useTaskSSE'

const route = useRoute()
const router = useRouter()
const store = useTaskStore()
const episodeId = Number(route.params.id)

const episode = ref<Episode | null>(null)
const shots = ref<Shot[]>([])
const characters = ref<Character[]>([])
const locations = ref<LocationCard[]>([])
const presets = ref<StylePreset[]>([])
const viewMode = ref<'cards' | 'timeline'>('cards')
const activeTab = ref('characters')
const compact = useMediaQuery('(max-width: 1100px)')
const panel = ref('shots')
const loading = ref(false)
const loadError = ref(false)
const activeShotId = ref<number | null>(null)

const readyShots = computed(() => shots.value.filter((shot) => shot.keyframe_asset_id && shot.video_asset_id).length)
const targetDuration = computed(() => episode.value?.target_duration ?? 60)
const episodeCharacters = computed(() => {
  const ids = new Set(shots.value.flatMap((shot) => shot.character_ids ?? []))
  return characters.value.filter((character) => ids.has(character.id))
})

// ---- 数据加载 ----
async function load() {
  loading.value = true
  loadError.value = false
  try {
    const [episodeData, shotData] = await Promise.all([getEpisode(episodeId), listEpisodeShots(episodeId)])
    episode.value = episodeData
    shots.value = shotData
  } catch {
    loadError.value = true
  } finally {
    loading.value = false
  }
}
async function loadSettings() {
  const pid = episode.value?.project_id
  if (!pid) return
  const [characterData, locationData, presetData] = await Promise.all([
    listCharacters(pid), listLocations(pid), listStylePresets(pid),
  ])
  characters.value = characterData
  locations.value = locationData
  presets.value = presetData
}
async function initialize() {
  await load()
  if (!episode.value) return
  try {
    await Promise.all([loadSettings(), store.restore(episode.value.project_id)])
  } catch {
    loadError.value = true
  }
}
onMounted(initialize)
watch(
  () => [...store.tasks.values()].filter((task) => task.episode_id === episodeId || shots.value.some((shot) => shot.id === task.shot_id)).map((task) => `${task.task_id}:${task.status}`),
  (next, previous = []) => {
    const terminal = next.some((entry) => {
      const [taskId, status] = entry.split(':')
      const before = previous.find((item) => item.startsWith(`${taskId}:`))
      return before && before !== entry && ['succeeded', 'failed', 'timeout', 'cancelled'].includes(status)
    })
    if (terminal) void load()
  },
)

// ---- 任务进度映射（shotId → 进行中任务） ----
const shotTasks = computed(() => {
  const map = new Map<number, { type: string; progress: number; status: string }[]>()
  for (const t of store.tasks.values()) {
    if (t.shot_id && ['queued', 'processing'].includes(t.status)) {
      const list = map.get(t.shot_id) ?? []
      list.push({ type: t.type, progress: t.progress, status: t.status })
      map.set(t.shot_id, list)
    }
  }
  return map
})

/** 任务登记 + SSE 订阅。 */
function trackTask(resp: { task_id: string; status: string }, shotId?: number) {
  store.track(resp)
  store.update(resp.task_id, { shot_id: shotId ?? null, episode_id: episodeId, project_id: episode.value?.project_id ?? null })
  useTaskSSE(resp.task_id)
}

// ---- 生成操作 ----
async function genKeyframe(shot: Shot) {
  await submitVisualTask(shot, 'image')
}
async function genVideoClip(shot: Shot) {
  await submitVisualTask(shot, 'video')
}
async function submitVisualTask(shot: Shot, kind: 'image' | 'video') {
  const submit = (confirm: boolean): Promise<TaskAccept> => kind === 'image'
    ? generateImage(shot.id, { mock_scenario: 'success' }, confirm)
    : generateVideo(shot.id, { mock_scenario: 'success' }, confirm)
  let accepted = await submit(false)
  if (accepted.require_confirm) {
    try {
      await ElMessageBox.confirm(
        kind === 'image' ? '即将调用真实图片模型，可能产生费用。确定生成吗？' : '即将调用真实视频模型，可能产生费用。确定生成吗？',
        '确认生成', { confirmButtonText: '生成', cancelButtonText: '取消', type: 'warning' },
      )
    } catch { return }
    accepted = await submit(true)
  }
  if (!accepted.task_id) return
  if (accepted.cached) {
    await load()
    ElMessage.success('已复用相同设定的生成结果')
  } else {
    trackTask(accepted, shot.id)
  }
}
async function genVoice(shot: Shot, line: { character_id: number; text: string; emotion?: string }) {
  trackTask(await generateAudio(shot.id, {
    track_type: 'dialogue', character_id: line.character_id,
    text: line.text, emotion: line.emotion, speed: 1.0,
  }, false), shot.id)
}
async function genAllVoices(shot: Shot) {
  for (const line of shot.dialogue ?? []) await genVoice(shot, line)
}

async function selectShot(shotId: number) {
  activeShotId.value = shotId
  if (compact.value) panel.value = 'shots'
  await nextTick()
  document.querySelector<HTMLElement>(`[data-shot-card="${shotId}"]`)?.scrollIntoView({
    behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth',
    block: 'center',
  })
}

function shotCharacters(shot: Shot): Character[] {
  return (shot.character_ids ?? [])
    .map((id) => characters.value.find((character) => character.id === id))
    .filter((character): character is Character => !!character)
}

function shotState(shot: Shot): { label: string; tone: string } {
  const tasks = shotTasks.value.get(shot.id) ?? []
  if (tasks.length) return { label: tasks.some((task) => task.status === 'processing') ? '生成中' : '排队中', tone: 'running' }
  if (shot.keyframe_asset_id && shot.video_asset_id) return { label: '视频就绪', tone: 'ready' }
  if (shot.keyframe_asset_id) return { label: '关键帧就绪', tone: 'frame' }
  return { label: '待生成', tone: 'waiting' }
}

/** 分镜总时长（秒）。 */
const totalDuration = computed(() => shots.value.reduce((s, x) => s + (x.duration ?? 0), 0))
/** 时长是否超出目标 ±20%。 */
const durationWarn = computed(() => {
  const target = episode.value?.target_duration ?? 60
  return totalDuration.value > 0 && Math.abs(totalDuration.value - target) / target > 0.2
})

// ---- 合成 ----
const rendering = ref(false)
async function render() {
  rendering.value = true
  try {
    const job = await createRenderJob({ episode_id: episodeId, subtitle_burn_in: true })
    ElMessage.success('合成任务已提交')
    trackTask({ task_id: job.task_id!, status: job.status })
  } finally {
    rendering.value = false
  }
}

// ---- 生成字幕 ----
async function genSubtitles() {
  trackTask(await generateAsr(episodeId, [], false))
}

// ---- 分镜编辑 ----
const shotDialog = ref(false)
const editingShot = ref<Shot | null>(null)
type ShotForm = Pick<Shot, 'shot_type' | 'camera_movement' | 'duration' | 'character_ids' | 'action_description'> & { dialogue: NonNullable<Shot['dialogue']> }
const shotForm = ref<ShotForm>({ shot_type: '中景', camera_movement: '固定', duration: 5, character_ids: [], action_description: '', dialogue: [] })
const shotTypes = ['远景', '全景', '中景', '近景', '特写']
const movements = ['固定', '推', '拉', '摇', '移']

function openShotEdit(shot: Shot) {
  editingShot.value = shot
  shotForm.value = {
    shot_type: shot.shot_type, camera_movement: shot.camera_movement,
    duration: shot.duration, character_ids: shot.character_ids ?? [],
    action_description: shot.action_description, dialogue: (shot.dialogue ?? []).map((d) => ({ ...d })),
  }
  shotDialog.value = true
}

async function saveShot() {
  await updateShot(editingShot.value!.id, shotForm.value)
  shotDialog.value = false
  await load()
}

async function removeShot(shot: Shot) {
  await deleteShot(shot.id)
  await load()
}

// ---- 新建分镜 ----
const newShotVisible = ref(false)
const newShotForm = ref({ shot_no: 1, shot_type: '中景', camera_movement: '固定', duration: 5, action_description: '', dialogue: [] as { character_id: number; text: string; emotion?: string }[] })

async function addShot() {
  const scenes = episode.value?.scenes ?? []
  const scene = scenes[scenes.length - 1]
  if (!scene) {
    ElMessage.warning('请先创建场景')
    return
  }
  await createShot(scene.id, { ...newShotForm.value, shot_no: (scene.shots?.length ?? 0) + 1 })
  newShotVisible.value = false
  await load()
}

// ---- 新建场景 ----
async function addScene() {
  await createScene(episodeId, {
    scene_no: (episode.value?.scenes?.length ?? 0) + 1,
    purpose: '新场景',
  })
  await load()
}

// ---- 角色卡 ----
const charDialog = ref(false)
const charForm = ref({ name: '', hair: '', clothing: '', voice_id: '' })

async function addCharacter() {
  await createCharacter(episode.value!.project_id, charForm.value)
  charDialog.value = false
  await loadSettings()
}

async function lockCharacter(c: Character) {
  await confirmCharacter(c.id)
  ElMessage.success(`角色「${c.name}」已锁定（v${c.version + 1}），生成任务将按版本引用`)
  await loadSettings()
}

// ---- 场景卡 ----
const locDialog = ref(false)
const locForm = ref<{ name: string; time_of_day?: string; lighting?: string }>({ name: '' })

async function addLocation() {
  await createLocation(episode.value!.project_id, locForm.value)
  locDialog.value = false
  await loadSettings()
}

/** 角色名称。 */
function charName(id: number): string {
  return characters.value.find((c) => c.id === id)?.name ?? `#${id}`
}
/** 素材 raw 地址。 */
function assetUrl(assetId: number | null): string | null {
  return assetId ? `/api/assets/${assetId}/raw` : null
}
/** 分镜完成度状态点颜色。 */
function shotDotColor(shot: Shot): string {
  if (shot.keyframe_asset_id && shot.video_asset_id) return 'var(--el-color-success)'
  if (shot.keyframe_asset_id) return 'var(--el-color-warning)'
  return 'var(--el-text-color-placeholder)'
}
</script>

<template>
  <div v-loading="loading" class="workbench" :class="{ compact }">
    <el-alert v-if="loadError" class="workbench-notice" title="工作台数据加载失败，请重试。" type="error" :closable="false">
      <el-button size="small" @click="initialize">重试</el-button>
    </el-alert>
    <el-radio-group v-if="compact" v-model="panel" class="workbench-switcher" aria-label="工作台面板">
      <el-radio-button value="shots">分镜</el-radio-button>
      <el-radio-button value="script">剧本树</el-radio-button>
      <el-radio-button value="settings">角色与设定</el-radio-button>
    </el-radio-group>
    <!-- 左栏：剧本树 -->
    <div v-show="!compact || panel === 'script'" class="left-panel">
      <div class="panel-heading">
        <div><span class="panel-kicker">EPISODE MAP</span><h2>剧本树</h2></div>
        <span class="panel-count">{{ shots.length }} 镜</span>
      </div>
      <div v-for="sc in episode?.scenes ?? []" :key="sc.id" class="scene-node">
        <div class="scene-label"><span class="scene-marker" /><span>场景 {{ String(sc.scene_no).padStart(2, '0') }}</span></div>
        <p class="scene-purpose">{{ sc.purpose || '场景描述待补充' }}</p>
        <button v-for="sh in sc.shots ?? []" :key="sh.id" type="button" class="shot-node"
          :class="{ active: activeShotId === sh.id }" :data-shot="sh.id" @click="selectShot(sh.id)">
          <span class="dot" :style="{ background: shotDotColor(sh) }" />
          <span class="shot-node-name">{{ sh.code ?? `shot_${sh.id}` }}</span>
          <span class="shot-node-time">{{ Number(sh.duration ?? 0).toFixed(0) }}s</span>
        </button>
      </div>
      <div class="left-ops">
        <el-button size="small" @click="addScene"><el-icon><Plus /></el-icon>场景</el-button>
        <el-button size="small" @click="newShotVisible = true; newShotForm.shot_no = (shots.length ?? 0) + 1"><el-icon><Plus /></el-icon>分镜</el-button>
      </div>
    </div>

    <!-- 中栏：分镜卡片流 / 时间轴 -->
    <div v-show="!compact || panel === 'shots'" class="center-panel">
      <header class="episode-heading">
        <div class="episode-copy">
          <span class="panel-kicker">STORYBOARD / EPISODE {{ String(episode?.episode_no ?? 1).padStart(2, '0') }}</span>
          <h1>{{ episode?.title || '未命名剧集' }}</h1>
          <p v-if="episode?.logline">{{ episode.logline }}</p>
        </div>
        <div class="episode-progress" :aria-label="`完成 ${readyShots} / ${shots.length} 个分镜`">
          <div class="progress-ring" :style="{ '--ring-progress': `${shots.length ? Math.round(readyShots / shots.length * 100) : 0}%` }"><strong>{{ shots.length ? Math.round(readyShots / shots.length * 100) : 0 }}<small>%</small></strong></div>
          <span><b>{{ readyShots }} / {{ shots.length }}</b><small>素材就绪</small></span>
        </div>
      </header>
      <div class="center-head">
        <el-radio-group v-model="viewMode" size="small">
          <el-radio-button value="cards">卡片流</el-radio-button>
          <el-radio-button value="timeline">时间轴</el-radio-button>
        </el-radio-group>
        <span class="grow" />
        <div class="total"><strong>{{ shots.length }}</strong><span>镜头</span><i /><strong>{{ totalDuration.toFixed(1) }}s</strong><span>总时长</span></div>
      </div>

      <!-- 卡片流 -->
      <div v-if="viewMode === 'cards'" class="shot-list">
        <el-alert v-if="shots.some(shot => (shot.character_ids?.length ?? 0) > 0)" class="consistency-note" type="info" :closable="false" show-icon
          title="角色一致性 · 锁定角色主参考图后，再按关键帧生成视频。" />
        <el-empty v-if="!loading && !loadError && shots.length === 0" description="还没有分镜，在剧本树中创建场景和分镜。" />
        <div v-if="shots.length" class="scene-divider"><span>分镜序列</span><i /><small>{{ shots.length }} CUTS</small></div>
        <el-card v-for="shot in shots" :key="shot.id" class="shot-card" shadow="never"
          :class="{ 'is-selected': activeShotId === shot.id }" :data-shot-card="shot.id">
          <div class="shot-grid">
            <div class="keyframe">
              <img v-if="assetUrl(shot.keyframe_asset_id)" :src="assetUrl(shot.keyframe_asset_id)!" :alt="`${shot.code || '分镜'}关键帧`" loading="lazy" decoding="async" />
              <div v-else class="placeholder"><el-icon><Picture /></el-icon><span>等待关键帧</span></div>
              <span class="frame-label">{{ shot.code ?? `CUT ${shot.shot_no}` }}</span>
              <span class="frame-state" :class="`tone-${shotState(shot).tone}`"><i />{{ shotState(shot).label }}</span>
              <div class="kf-ops" @click.stop>
                <el-button size="small" type="primary" plain @click="genKeyframe(shot)"><el-icon><Picture /></el-icon>{{ shot.keyframe_asset_id ? '重生成' : '生成关键帧' }}</el-button>
              </div>
              <div v-if="shotTasks.get(shot.id)?.length" class="mini-progress">
                <div v-for="t in shotTasks.get(shot.id)" :key="t.type + String(t.progress)" class="mini-bar">
                  <div class="mini-fill" :style="{ width: `${t.progress}%` }" />
                </div>
              </div>
            </div>
            <div class="info">
              <div class="tags">
                <el-tag size="small" effect="plain">{{ shot.shot_type ?? '中景' }}</el-tag>
                <el-tag size="small" effect="plain" type="info">{{ shot.camera_movement ?? '固定' }}镜头</el-tag>
                <el-tag size="small" effect="plain" type="warning"><span class="duration-value">{{ Number(shot.duration ?? 0).toFixed(1) }}</span>s</el-tag>
              </div>
              <p class="action-text">{{ shot.action_description || '动作描述待补充' }}</p>
              <div v-if="shotCharacters(shot).length" class="shot-characters">
                <span class="detail-label">出场角色</span>
                <span v-for="character in shotCharacters(shot)" :key="character.id" class="character-chip">
                  <img v-if="character.reference_assets?.[0]" :src="character.reference_assets[0].raw_url" :alt="''" />
                  <span v-else class="chip-placeholder">{{ character.name.slice(0, 1) }}</span>
                  {{ character.name }}<small>{{ character.confirmed ? '锁定' : '草稿' }} · v{{ character.version }}</small>
                </span>
              </div>
              <div v-for="(line, i) in shot.dialogue ?? []" :key="i" class="dialogue-line">
                <span class="quote-mark">“</span>
                <span class="char-name">{{ charName(line.character_id) }}</span>
                <span class="line-text">{{ line.text }}</span>
                <el-tag v-if="line.emotion" size="small" type="danger" effect="plain">{{ line.emotion }}</el-tag>
              </div>
              <div class="ops" @click.stop>
                <el-button size="small" text @click="openShotEdit(shot)"><el-icon><EditPen /></el-icon>编辑分镜</el-button>
                <el-button size="small" text :disabled="!shot.dialogue?.length" @click="genVoice(shot, shot.dialogue![0])"><el-icon><Microphone /></el-icon>生成语音</el-button>
                <span class="ops-spacer" />
                <el-button size="small" type="primary" plain :disabled="!shot.keyframe_asset_id" @click="genVideoClip(shot)"><el-icon><VideoCamera /></el-icon>{{ shot.video_asset_id ? '重生成视频' : '生成视频' }}</el-button>
                <el-button size="small" text type="danger" aria-label="删除分镜" title="删除分镜" @click="removeShot(shot)"><el-icon><Delete /></el-icon></el-button>
              </div>
            </div>
          </div>
        </el-card>
      </div>

      <!-- 时间轴视图（阶段五） -->
      <div v-else class="timeline-view">
        <div class="timeline-ruler"><span>镜头</span><div><i>00:00</i><i>{{ (totalDuration / 2).toFixed(0) }}s</i><i>{{ totalDuration.toFixed(0) }}s</i></div><span>素材状态</span></div>
        <div v-for="shot in shots" :key="shot.id" class="tl-row">
          <button type="button" class="tl-label" @click="selectShot(shot.id)"><span>{{ String(shot.shot_no).padStart(2, '0') }}</span>{{ shot.code ?? shot.id }}</button>
          <div class="tl-track" :class="{ 'has-video': shot.video_asset_id }">
            <div class="tl-bar"
              :style="{ width: `${Math.max(((shot.duration ?? 5) / Math.max(totalDuration, 1)) * 100, 4)}%` }">
              <span>{{ shot.action_description || shot.code || '分镜' }}</span><small>{{ Number(shot.duration ?? 0).toFixed(1) }}s</small>
            </div>
          </div>
          <span class="timeline-state" :class="`tone-${shotState(shot).tone}`"><i />{{ shotState(shot).label }}</span>
        </div>
      </div>
    </div>

    <!-- 右栏：设定面板 -->
    <div v-show="!compact || panel === 'settings'" class="right-panel">
      <el-tabs v-model="activeTab">
        <el-tab-pane label="角色" name="characters">
          <div class="setting-tab-head">
            <span>本集出场角色 <b>{{ episodeCharacters.length }}</b></span>
            <el-button size="small" text type="primary" @click="router.push(`/projects/${episode?.project_id}/characters`)">打开角色库</el-button>
          </div>
          <el-empty v-if="!episodeCharacters.length" :image-size="48" description="分镜尚未关联角色" />
          <div v-for="c in episodeCharacters" :key="c.id" class="card-item character-item">
            <img v-if="c.reference_assets?.[0]" :src="c.reference_assets[0].raw_url" :alt="`${c.name}参考图`" />
            <div v-else class="character-placeholder">人</div>
            <div class="character-item-copy">
              <div>
                <b>{{ c.name }}</b>
                <el-tag size="small" style="margin-left: 6px">v{{ c.version }}</el-tag>
                <el-tag v-if="c.confirmed" size="small" type="success" style="margin-left: 4px">已锁定</el-tag>
              </div>
              <div class="sub character-description">{{ c.hair || '外观描述待补充' }}</div>
              <div v-if="!c.reference_assets?.length" class="reference-warning">尚无主参考图</div>
            </div>
            <div class="ops-mini">
              <el-button v-if="!c.confirmed" size="small" text type="warning" @click="lockCharacter(c)">确认锁定</el-button>
            </div>
          </div>
          <el-button size="small" style="width: 100%" @click="charDialog = true; charForm = { name: '', hair: '', clothing: '', voice_id: '' }">+ 新建角色</el-button>
        </el-tab-pane>
        <el-tab-pane label="场景" name="locations">
          <div v-for="l in locations" :key="l.id" class="card-item">
            <b>{{ l.name }}</b>
            <div class="sub">{{ l.time_of_day }} · {{ l.lighting || '光线未设置' }}</div>
          </div>
          <el-button size="small" style="width: 100%" @click="locDialog = true; locForm = { name: '' }">+ 新建场景</el-button>
        </el-tab-pane>
        <el-tab-pane label="画风" name="styles">
          <div v-for="s in presets" :key="s.id" class="card-item">
            <b>{{ s.name }}</b>
            <div class="sub">{{ s.style_prompt?.slice(0, 60) }}</div>
          </div>
        </el-tab-pane>
      </el-tabs>
    </div>

    <!-- 底部操作条 -->
    <div class="bottom-bar">
      <div class="duration-summary" :class="{ warn: durationWarn }">
        <span class="summary-label">片长</span><strong>{{ totalDuration.toFixed(1) }}<small>s</small></strong>
        <span class="target-duration">目标 {{ targetDuration }}s</span>
        <span class="duration-alert" v-if="durationWarn">超出目标 ±20%</span>
      </div>
      <span class="grow" />
      <el-button @click="genSubtitles"><el-icon><Microphone /></el-icon>生成字幕</el-button>
      <el-button type="primary" :loading="rendering" :disabled="!shots.length" @click="render"><el-icon><VideoCamera /></el-icon>合成成片</el-button>
      <el-button @click="$router.push(`/episodes/${episodeId}/preview`)" :disabled="!shots.length"><el-icon><VideoCamera /></el-icon>预览</el-button>
    </div>

    <!-- 分镜编辑弹窗 -->
    <el-dialog v-model="shotDialog" :title="`编辑分镜 ${editingShot?.code ?? ''}`" width="640px">
      <el-form label-width="90px">
        <el-form-item label="景别">
          <el-select v-model="shotForm.shot_type">
            <el-option v-for="t in shotTypes" :key="t" :label="t" :value="t" />
          </el-select>
        </el-form-item>
        <el-form-item label="运镜">
          <el-select v-model="shotForm.camera_movement">
            <el-option v-for="m in movements" :key="m" :label="m" :value="m" />
          </el-select>
        </el-form-item>
        <el-form-item label="时长(秒)">
          <el-input-number v-model="shotForm.duration" :min="1" :max="8" :step="0.5" />
          <span class="sub" style="margin-left: 8px">建议 3~8s</span>
        </el-form-item>
        <el-form-item label="出场角色">
          <el-select v-model="shotForm.character_ids" multiple>
            <el-option v-for="c in characters" :key="c.id" :label="c.name" :value="c.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="动作描述">
          <el-input v-model="shotForm.action_description" type="textarea" :rows="3" />
        </el-form-item>
        <el-form-item v-for="(line, i) in shotForm.dialogue" :key="i" :label="`对白${i + 1}`">
          <div style="display: flex; gap: 6px; width: 100%">
            <el-select v-model="line.character_id" style="width: 140px" placeholder="角色">
              <el-option v-for="c in characters" :key="c.id" :label="c.name" :value="c.id" />
            </el-select>
            <el-input v-model="line.text" placeholder="台词" />
            <el-button text type="danger" @click="(shotForm.dialogue as Array<unknown>).splice(i, 1)">删</el-button>
          </div>
        </el-form-item>
        <el-form-item label=" ">
          <el-button size="small" @click="(shotForm.dialogue as Array<unknown>).push({ character_id: characters[0]?.id ?? 1, text: '' })">+ 对白</el-button>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="shotDialog = false">取消</el-button>
        <el-button type="primary" @click="saveShot">保存</el-button>
      </template>
    </el-dialog>

    <!-- 新建分镜 -->
    <el-dialog v-model="newShotVisible" title="新建分镜" width="480px">
      <el-form label-width="90px">
        <el-form-item label="景别">
          <el-select v-model="newShotForm.shot_type">
            <el-option v-for="t in shotTypes" :key="t" :label="t" :value="t" />
          </el-select>
        </el-form-item>
        <el-form-item label="时长(秒)">
          <el-input-number v-model="newShotForm.duration" :min="3" :max="8" :step="0.5" />
        </el-form-item>
        <el-form-item label="动作描述">
          <el-input v-model="newShotForm.action_description" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="newShotVisible = false">取消</el-button>
        <el-button type="primary" @click="addShot">创建</el-button>
      </template>
    </el-dialog>

    <!-- 新建角色 -->
    <el-dialog v-model="charDialog" title="新建角色卡" width="480px">
      <el-form label-width="90px">
        <el-form-item label="角色名" required><el-input v-model="charForm.name" /></el-form-item>
        <el-form-item label="发型发色"><el-input v-model="charForm.hair" placeholder="外观固定词" /></el-form-item>
        <el-form-item label="服装"><el-input v-model="charForm.clothing" /></el-form-item>
        <el-form-item label="音色 ID"><el-input v-model="charForm.voice_id" placeholder="供应商音色 ID（同角色固定）" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="charDialog = false">取消</el-button>
        <el-button type="primary" @click="addCharacter">创建</el-button>
      </template>
    </el-dialog>

    <!-- 新建场景卡 -->
    <el-dialog v-model="locDialog" title="新建场景卡" width="480px">
      <el-form label-width="90px">
        <el-form-item label="地点名" required><el-input v-model="locForm.name" /></el-form-item>
        <el-form-item label="时段">
          <el-select v-model="locForm.time_of_day">
            <el-option v-for="t in ['dawn', 'day', 'dusk', 'night']" :key="t" :label="t" :value="t" />
          </el-select>
        </el-form-item>
        <el-form-item label="光线"><el-input v-model="locForm.lighting" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="locDialog = false">取消</el-button>
        <el-button type="primary" @click="addLocation">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.workbench {
  display: grid;
  grid-template-columns: 232px minmax(0, 1fr) 276px;
  grid-template-rows: minmax(560px, 1fr) auto;
  gap: 12px;
  min-height: calc(100vh - 124px);
  align-items: stretch;
}
.workbench.compact { grid-template-columns: minmax(0, 1fr); grid-template-rows: auto minmax(620px, 1fr) auto; }
.workbench-switcher, .workbench-notice { grid-column: 1 / -1; }
.left-panel, .right-panel, .center-panel, .info { min-width: 0; min-height: 0; }
.left-panel, .right-panel {
  background: var(--el-bg-color);
  border: 1px solid var(--workspace-line);
  border-radius: 6px;
  padding: 14px 12px;
  overflow: auto;
}
.center-panel {
  background: var(--el-bg-color);
  border: 1px solid var(--workspace-line);
  border-radius: 6px;
  padding: 0 16px 16px;
  overflow: auto;
}
.panel-heading {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 8px;
  margin: 2px 2px 18px;
}
.panel-heading h2 { margin: 4px 0 0; font-size: 15px; font-weight: 650; }
.panel-kicker { color: var(--el-color-primary); font-size: 9px; font-weight: 700; letter-spacing: .08em; }
.panel-count { color: var(--el-text-color-secondary); font-size: 11px; }
.scene-node {
  margin: 0 0 18px;
}
.scene-label {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--el-text-color-primary);
  font-size: 12px;
  font-weight: 650;
}
.scene-marker { width: 7px; height: 7px; border-radius: 2px; background: #d28b47; }
.scene-purpose { margin: 6px 0 7px 15px; color: var(--el-text-color-secondary); font-size: 11px; line-height: 1.5; }
.shot-node {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  min-height: 32px;
  border: 0;
  border-radius: 4px;
  padding: 0 7px 0 14px;
  color: var(--el-text-color-regular);
  background: transparent;
  font: inherit;
  font-size: 11px;
  text-align: left;
  cursor: pointer;
}
.shot-node:hover, .shot-node.active { color: var(--el-color-primary-dark-2); background: var(--el-color-primary-light-9); }
.shot-node:focus-visible { outline: 2px solid var(--el-color-primary); outline-offset: 1px; }
.dot { width: 7px; height: 7px; flex: 0 0 7px; border-radius: 50%; }
.shot-node-name { min-width: 0; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.shot-node-time { color: var(--el-text-color-placeholder); font-variant-numeric: tabular-nums; }
.left-ops {
  display: flex;
  gap: 6px;
  margin: 18px 0 0;
}
.left-ops .el-button { flex: 1; margin-left: 0; }
.left-ops .el-icon { margin-right: 3px; }
.episode-heading { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 20px 2px 16px; }
.episode-copy { min-width: 0; }
.episode-copy h1 { margin: 6px 0 0; color: var(--el-text-color-primary); font-size: 22px; line-height: 1.25; font-weight: 680; }
.episode-copy p { max-width: 660px; margin: 6px 0 0; color: var(--el-text-color-secondary); font-size: 12px; line-height: 1.5; }
.episode-progress { display: flex; align-items: center; gap: 9px; flex: 0 0 auto; }
.progress-ring { position: relative; display: grid; width: 43px; height: 43px; place-items: center; border-radius: 50%; color: var(--el-text-color-primary); background: conic-gradient(var(--el-color-primary) var(--ring-progress), var(--el-color-primary-light-8) 0); }
.progress-ring::before { position: absolute; inset: 4px; border-radius: 50%; background: var(--el-bg-color); content: ''; }
.progress-ring strong { position: relative; z-index: 1; font-size: 11px; font-variant-numeric: tabular-nums; }
.progress-ring small { font-size: 8px; }
.episode-progress > span { display: grid; gap: 3px; }
.episode-progress b { font-size: 11px; font-variant-numeric: tabular-nums; }
.episode-progress small { color: var(--el-text-color-secondary); font-size: 10px; }
.center-head {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 44px;
  border-top: 1px solid var(--workspace-line);
  border-bottom: 1px solid var(--workspace-line);
  margin: 0 -16px 14px;
  padding: 0 16px;
}
.grow {
  flex: 1;
}
.total {
  display: flex;
  align-items: baseline;
  gap: 5px;
  color: var(--el-text-color-secondary);
  font-size: 10px;
}
.total strong { color: var(--el-text-color-primary); font-size: 13px; font-variant-numeric: tabular-nums; }
.total i { width: 1px; height: 13px; margin: 0 5px; background: var(--workspace-line); }
.consistency-note { margin-bottom: 14px; }
.consistency-note :deep(.el-alert__title) { font-size: 11px; }
.scene-divider { display: flex; align-items: center; gap: 10px; margin: 4px 0 10px; color: var(--el-text-color-primary); font-size: 11px; font-weight: 650; }
.scene-divider i { height: 1px; flex: 1; background: var(--workspace-line); }
.scene-divider small { color: var(--el-text-color-placeholder); font-size: 9px; font-weight: 500; letter-spacing: .08em; }
.shot-card { margin-bottom: 10px; border: 1px solid var(--workspace-line); border-radius: 6px; }
.shot-card.is-selected { border-color: var(--el-color-primary-light-3); box-shadow: 0 0 0 1px var(--el-color-primary-light-8); }
.shot-card:focus-visible { outline: 2px solid var(--el-color-primary); outline-offset: 2px; }
.shot-card :deep(.el-card__body) { padding: 10px; }
.shot-grid {
  display: grid;
  grid-template-columns: minmax(220px, 36%) minmax(0, 1fr);
  gap: 14px;
}
.keyframe {
  position: relative;
  min-width: 0;
  align-self: start;
  overflow: hidden;
  border-radius: 4px;
  background: #121a19;
}
.keyframe img, .placeholder {
  display: flex;
  width: 100%;
  aspect-ratio: 16/9;
  object-fit: cover;
  align-items: center;
  justify-content: center;
  color: rgb(255 255 255 / 62%);
}
.placeholder {
  flex-direction: column;
  gap: 7px;
  background:
    linear-gradient(135deg, transparent 49.7%, rgb(255 255 255 / 7%) 50%, transparent 50.3%),
    #182321;
  font-size: 10px;
}
.placeholder .el-icon { color: #b3c8c1; font-size: 22px; }
.frame-label, .frame-state { position: absolute; top: 8px; display: inline-flex; align-items: center; gap: 5px; border-radius: 3px; padding: 4px 6px; color: #fff; background: rgb(15 25 23 / 78%); font-size: 9px; }
.frame-label { left: 8px; font-weight: 650; letter-spacing: .04em; }
.frame-state { right: 8px; }
.frame-state i, .timeline-state i { width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
.tone-ready { color: #94d1ad; }
.tone-frame { color: #e2ba77; }
.tone-running { color: #91c7c0; }
.tone-waiting { color: #c4cfcc; }
.kf-ops { display: flex; justify-content: center; padding: 8px 0 1px; }
.kf-ops .el-button { margin: 0; }
.kf-ops .el-icon { margin-right: 4px; }
.mini-progress { position: absolute; right: 0; bottom: 0; left: 0; padding: 3px 8px 7px; background: linear-gradient(transparent, rgb(8 13 12 / 76%)); }
.mini-bar { height: 3px; overflow: hidden; border-radius: 2px; margin-top: 3px; background: rgb(255 255 255 / 28%); }
.mini-fill { height: 100%; background: #83c7bb; transition: width 0.5s; }
.info { display: flex; flex-direction: column; }
.tags { display: flex; flex-wrap: wrap; gap: 5px; margin-bottom: 8px; }
.tags .el-tag { max-width: 100%; }
.duration-value { font-variant-numeric: tabular-nums; }
.action-text { margin: 0 0 10px; color: var(--el-text-color-primary); font-size: 13px; line-height: 1.6; }
.detail-label { color: var(--el-text-color-secondary); font-size: 10px; }
.shot-characters { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin: 0 0 8px; }
.character-chip { display: inline-flex; align-items: center; gap: 5px; min-height: 23px; border: 1px solid var(--workspace-line); border-radius: 12px; padding: 2px 7px 2px 3px; color: var(--el-text-color-regular); font-size: 10px; }
.character-chip img, .chip-placeholder { width: 17px; height: 17px; flex: 0 0 17px; border-radius: 50%; object-fit: cover; background: var(--el-fill-color); }
.chip-placeholder { display: grid; place-items: center; color: var(--el-color-primary); font-size: 9px; }
.character-chip small { color: var(--el-text-color-placeholder); font-size: 9px; }
.dialogue-line { display: flex; align-items: baseline; gap: 5px; min-width: 0; border-left: 2px solid #d28b47; margin: 1px 0 5px; padding: 2px 0 2px 8px; color: var(--el-text-color-regular); font-size: 11px; line-height: 1.5; }
.quote-mark { color: #d28b47; font-family: Georgia, serif; font-size: 18px; line-height: 1; }
.char-name { flex: 0 0 auto; color: var(--el-color-primary); font-size: 10px; font-weight: 650; }
.line-text { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ops { display: flex; align-items: center; flex-wrap: wrap; gap: 2px; border-top: 1px solid var(--workspace-line); margin-top: auto; padding-top: 7px; }
.ops .el-button + .el-button { margin-left: 0; }
.ops .el-button { padding-right: 6px; padding-left: 6px; }
.ops .el-icon { margin-right: 3px; }
.ops-spacer { flex: 1; }
.timeline-view { padding: 3px 0; }
.timeline-ruler, .tl-row { display: grid; grid-template-columns: 110px minmax(0, 1fr) 78px; align-items: center; gap: 9px; }
.timeline-ruler { margin: 0 0 8px; color: var(--el-text-color-secondary); font-size: 9px; }
.timeline-ruler > div { display: flex; justify-content: space-between; border-bottom: 1px solid var(--workspace-line); padding-bottom: 5px; }
.tl-row { min-height: 39px; border-bottom: 1px solid var(--workspace-line); }
.tl-label { display: flex; align-items: center; gap: 7px; overflow: hidden; border: 0; padding: 5px 2px; color: var(--el-text-color-regular); background: transparent; font: inherit; font-size: 10px; text-align: left; text-overflow: ellipsis; white-space: nowrap; cursor: pointer; }
.tl-label span { color: #d28b47; font-size: 9px; font-variant-numeric: tabular-nums; }
.tl-track { position: relative; height: 24px; overflow: hidden; border-radius: 3px; background: repeating-linear-gradient(90deg, var(--el-fill-color-light) 0, var(--el-fill-color-light) calc(10% - 1px), var(--workspace-line) calc(10% - 1px), var(--workspace-line) 10%); }
.tl-bar { display: flex; height: 100%; min-width: 42px; align-items: center; justify-content: space-between; gap: 5px; overflow: hidden; border-left: 3px solid #d28b47; border-radius: 3px; padding: 0 7px; color: var(--el-text-color-primary); background: #f1e6d6; font-size: 9px; }
.tl-bar span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tl-bar small { flex: 0 0 auto; color: var(--el-text-color-secondary); font-size: 9px; }
.tl-track.has-video .tl-bar { border-left-color: var(--el-color-primary); background: var(--el-color-primary-light-9); }
.timeline-state { display: inline-flex; align-items: center; gap: 5px; font-size: 9px; white-space: nowrap; }
.timeline-state.tone-ready { color: var(--el-color-success); }
.timeline-state.tone-frame { color: #bb8134; }
.timeline-state.tone-running { color: var(--el-color-primary); }
.timeline-state.tone-waiting { color: var(--el-text-color-secondary); }
.right-panel { padding: 8px 12px 12px; }
.right-panel :deep(.el-tabs__header) { margin-bottom: 10px; }
.right-panel :deep(.el-tabs__item) { height: 40px; padding: 0 10px; font-size: 12px; }
.setting-tab-head { display: flex; align-items: center; justify-content: space-between; gap: 6px; margin: 0 0 7px; color: var(--el-text-color-secondary); font-size: 10px; }
.setting-tab-head b { margin-left: 3px; color: var(--el-text-color-primary); font-variant-numeric: tabular-nums; }
.card-item { border-bottom: 1px solid var(--workspace-line); padding: 9px 0; }
.character-item { display: flex; align-items: flex-start; gap: 8px; }
.character-item img, .character-placeholder { width: 38px; height: 44px; flex: 0 0 38px; border-radius: 3px; object-fit: cover; background: var(--el-fill-color); }
.character-placeholder { display: grid; place-items: center; color: var(--el-text-color-secondary); }
.character-item-copy { min-width: 0; flex: 1; }
.character-item-copy b { font-size: 11px; }
.character-item-copy :deep(.el-tag) { margin-left: 4px; }
.character-description { overflow: hidden; margin-top: 4px; text-overflow: ellipsis; white-space: nowrap; }
.reference-warning { margin-top: 4px; color: var(--el-color-warning); font-size: 9px; }
.ops-mini { display: flex; }
.bottom-bar {
  position: sticky;
  bottom: 8px;
  z-index: 5;
  grid-column: 1 / -1;
  display: flex;
  align-items: center;
  gap: 8px;
  border: 1px solid var(--workspace-line);
  border-radius: 6px;
  padding: 8px 12px;
  background: var(--el-bg-color);
  box-shadow: 0 5px 18px rgb(25 45 41 / 10%);
  flex-wrap: wrap;
}
.duration-summary { display: flex; align-items: baseline; gap: 6px; }
.summary-label, .target-duration { color: var(--el-text-color-secondary); font-size: 10px; }
.duration-summary strong { color: var(--el-text-color-primary); font-size: 17px; font-variant-numeric: tabular-nums; }
.duration-summary strong small { margin-left: 2px; color: var(--el-text-color-secondary); font-size: 10px; font-weight: 500; }
.duration-alert { color: var(--el-color-warning); font-size: 10px; font-weight: 600; }
.duration-summary.warn strong { color: var(--el-color-warning); }
.bottom-bar .el-icon { margin-right: 4px; }
.timeline-state, .warn { font-weight: 600; }
.workbench :deep(.el-empty) { padding: 35px 0; }
.workbench :deep(.el-empty__description p) { font-size: 12px; }
.workbench.compact .left-panel, .workbench.compact .right-panel { max-height: 360px; }
.workbench.compact .center-panel { min-height: 620px; }
@media (max-width: 1280px) {
  .workbench { grid-template-columns: 205px minmax(0, 1fr) 250px; gap: 9px; }
  .shot-grid { grid-template-columns: minmax(190px, 34%) minmax(0, 1fr); gap: 11px; }
}
@media (max-width: 1100px) {
  .workbench.compact { grid-template-columns: minmax(0, 1fr); grid-template-rows: auto minmax(620px, 1fr) auto; }
  .shot-grid { grid-template-columns: minmax(220px, 36%) minmax(0, 1fr); }
}
@media (max-width: 700px) {
  .center-panel { padding: 0 11px 12px; }
  .episode-heading { padding: 16px 2px 12px; }
  .episode-copy h1 { font-size: 19px; }
  .episode-progress { gap: 6px; }
  .progress-ring { width: 36px; height: 36px; }
  .center-head { margin-right: -11px; margin-left: -11px; padding: 0 11px; }
  .shot-grid { grid-template-columns: minmax(0, 1fr); }
  .keyframe { width: 100%; }
  .ops { gap: 2px; }
  .ops .el-button { padding-right: 5px; padding-left: 5px; }
  .timeline-ruler, .tl-row { grid-template-columns: 76px minmax(0, 1fr) 68px; gap: 5px; }
  .timeline-state { font-size: 8px; }
}
@media (max-width: 480px) {
  .workbench.compact { grid-template-rows: auto minmax(540px, 1fr) auto; }
  .workbench-switcher { width: 100%; }
  .workbench-switcher :deep(.el-radio-button) { flex: 1; }
  .workbench-switcher :deep(.el-radio-button__inner) { width: 100%; padding: 8px 5px; }
  .episode-heading { align-items: flex-start; }
  .episode-copy h1 { font-size: 17px; }
  .episode-progress > span { display: none; }
  .total { gap: 3px; }
  .shot-card :deep(.el-card__body) { padding: 8px; }
  .ops-spacer { display: none; }
  .timeline-ruler, .tl-row { grid-template-columns: 63px minmax(0, 1fr) 59px; gap: 4px; }
  .tl-label { gap: 3px; font-size: 9px; }
  .tl-bar { padding: 0 4px; }
  .tl-bar small { display: none; }
  .bottom-bar { bottom: 4px; gap: 5px; padding: 7px; }
  .duration-summary { flex: 1 0 100%; }
  .bottom-bar .el-button { flex: 1; margin-left: 0; padding-right: 8px; padding-left: 8px; }
  .bottom-bar .el-button :deep(span) { font-size: 11px; }
}
html.dark .tl-bar { color: #f0e5d6; background: #54483a; }
html.dark .tl-track.has-video .tl-bar { color: #d3e9e4; background: #29423f; }
html.dark .tl-bar small { color: #d9cbb9; }
@media (prefers-reduced-motion: reduce) {
  .mini-fill { transition: none; }
}
</style>
