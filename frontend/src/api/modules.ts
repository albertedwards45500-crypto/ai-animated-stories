/**
 * 各资源 API 模块：与《API接口文档.md》一一对应。
 */
import { http } from './client'
import axios from 'axios'
import type { ApiResponse } from './client'

// ---- 类型 ----
export interface Project {
  id: number
  name: string
  genre: string | null
  audience: string | null
  style_preset_id: number | null
  world_rules: Record<string, unknown> | null
  default_episode_duration: number
  description: string | null
  status: number
  episode_count?: number
  created_at: string | null
  updated_at: string | null
}

export interface Shot {
  id: number
  episode_id: number
  scene_id: number
  scene_no: number
  shot_no: number
  code: string | null
  shot_type: string | null
  camera_movement: string | null
  character_ids: number[] | null
  action_description: string | null
  dialogue: { character_id: number; text: string; emotion?: string }[] | null
  visual_prompt: Record<string, unknown> | null
  duration: number | null
  keyframe_asset_id: number | null
  video_asset_id: number | null
  status: number
}

export interface Scene {
  id: number
  episode_id: number
  scene_no: number
  code: string | null
  location_id: number | null
  time_of_day: string | null
  purpose: string | null
  summary: string | null
  shot_count?: number
  shots?: Shot[]
}

export interface Episode {
  id: number
  project_id: number
  episode_no: number
  title: string | null
  logline: string | null
  story_outline: string | null
  script_json: Record<string, unknown> | null
  target_duration: number | null
  status: number
  scene_count?: number
  shot_count?: number
  scenes?: Scene[]
}

export interface GenTask {
  task_id: string
  type: string
  provider: string | null
  mode: string | null
  status: string
  progress: number
  error_message: string | null
  retry_count: number
  cost: number
  shot_id: number | null
  episode_id: number | null
  project_id: number | null
  output_asset_ids: number[]
  request_payload?: Record<string, unknown> | null
  response_payload?: Record<string, unknown> | null
}

export interface Asset {
  id: number
  project_id: number | null
  asset_type: string
  file_path: string
  file_name: string | null
  mime_type: string | null
  file_size: number | null
  meta_json: Record<string, unknown> | null
  raw_url: string
}

export interface Character {
  id: number
  code: string
  name: string
  age_range?: string | null
  gender_presentation?: string | null
  hair: string | null
  face_features?: string | null
  body_shape?: string | null
  clothing: string | null
  color_palette?: string[] | null
  style_tokens?: string[] | null
  voice_id: string | null
  voice_emotions: string[] | null
  version: number
  confirmed: number
  reference_assets: CharacterAsset[]
}

export interface CharacterAsset {
  id: number
  asset_id: number
  asset_type: string
  is_primary: boolean
  file_name: string | null
  raw_url: string
}

export interface LocationCard {
  id: number
  code: string
  name: string
  description: string | null
  time_of_day: string | null
  lighting: string | null
}

export interface StylePreset {
  id: number
  project_id: number | null
  name: string
  style_prompt: string | null
  negative_prompt: string | null
}

export interface ProviderConfig {
  capability: string
  provider: string
  mode: string
  model: string | null
  base_url: string | null
  api_key_ref: string | null
  timeout_seconds: number
  max_retries: number
  daily_quota: number | null
  enabled: boolean
}

export interface RenderJob {
  job_id: string
  episode_id: number
  task_id: string | null
  status: string
  progress: number
  output_asset_id: number | null
  error_message: string | null
  preview_url: string
  download_url: string
}

// ---- 项目 ----
export const listProjects = (params: { page?: number; page_size?: number; keyword?: string }) =>
  http.get<never, { total: number; items: Project[] }>('/api/projects', { params })

export const createProject = (body: Partial<Project>) => http.post<never, Project>('/api/projects', body)

export const getProject = (id: number) => http.get<never, Project>(`/api/projects/${id}`)

export const updateProject = (id: number, body: Partial<Project>) => http.put<never, Project>(`/api/projects/${id}`, body)

export const deleteProject = (id: number) => http.delete(`/api/projects/${id}`)

// ---- 剧本 / 剧集 ----
export const generateScript = (projectId: number, body: { episode: { title: string; story_outline: string; target_duration?: number }; provider?: string }) =>
  http.post<never, { task_id: string; status: string; episode_id: number }>(`/api/projects/${projectId}/script/generate`, body)

export const listEpisodes = (projectId: number) => http.get<never, Episode[]>(`/api/projects/${projectId}/episodes`)

export const getEpisode = (id: number) => http.get<never, Episode>(`/api/episodes/${id}`)

export const updateEpisode = (id: number, body: Partial<Episode>) => http.put<never, Episode>(`/api/episodes/${id}`, body)

// ---- 场景 / 分镜 ----
export const createScene = (episodeId: number, body: Record<string, unknown>) =>
  http.post<never, { id: number }>(`/api/episodes/${episodeId}/scenes`, body)

export const listScenes = (episodeId: number) => http.get<never, Scene[]>(`/api/episodes/${episodeId}/scenes`)

export const createShot = (sceneId: number, body: Record<string, unknown>) =>
  http.post<never, { id: number }>(`/api/scenes/${sceneId}/shots`, body)

export const listEpisodeShots = (episodeId: number) => http.get<never, Shot[]>(`/api/episodes/${episodeId}/shots`)

export const updateShot = (id: number, body: Record<string, unknown>) => http.put<never, Shot>(`/api/shots/${id}`, body)

export const deleteShot = (id: number) => http.delete(`/api/shots/${id}`)

// ---- 设定 ----
export const listCharacters = (projectId: number) => http.get<never, Character[]>(`/api/projects/${projectId}/characters`)

export const createCharacter = (projectId: number, body: Record<string, unknown>) =>
  http.post<never, Character>(`/api/projects/${projectId}/characters`, body)

export const updateCharacter = (id: number, body: Record<string, unknown>) => http.put<never, Character>(`/api/characters/${id}`, body)

export const confirmCharacter = (id: number) => http.post<never, Character>(`/api/characters/${id}/confirm`)

export const generateCharacterImage = (id: number, confirm = false, variantId?: string) =>
  http.post<never, TaskAccept>(`/api/generation/characters/${id}/image`, {
    confirm, variant_id: variantId, params: { mock_scenario: 'success' },
  })

export const uploadCharacterAsset = (id: number, file: File) => {
  const form = new FormData()
  form.append('file', file)
  return http.post<never, CharacterAsset>(`/api/characters/${id}/assets`, form)
}

export const listCharacterAssets = (id: number) =>
  http.get<never, CharacterAsset[]>(`/api/characters/${id}/assets`)

export const setPrimaryCharacterAsset = (characterId: number, assetId: number) =>
  http.post<never, CharacterAsset[]>(`/api/characters/${characterId}/assets/${assetId}/primary`)

export const listLocations = (projectId: number) => http.get<never, LocationCard[]>(`/api/projects/${projectId}/locations`)

export const createLocation = (projectId: number, body: Record<string, unknown>) =>
  http.post<never, LocationCard>(`/api/projects/${projectId}/locations`, body)

export const listStylePresets = (projectId?: number) =>
  http.get<never, StylePreset[]>('/api/style-presets', { params: { project_id: projectId } })

export const createStylePreset = (body: Record<string, unknown>) => http.post<never, StylePreset>('/api/style-presets', body)

// ---- 生成任务 ----
export const generateImage = (shotId: number, params: Record<string, unknown> = {}, confirm = false) =>
  http.post<never, TaskAccept>('/api/generation/image', { shot_id: shotId, params, confirm })

export const generateVideo = (shotId: number, params: Record<string, unknown> = {}, confirm = false) =>
  http.post<never, TaskAccept>('/api/generation/video', { shot_id: shotId, params, confirm })

export const generateAudio = (shotId: number, audioTrack: Record<string, unknown>, confirm = false) =>
  http.post<never, TaskAccept>('/api/generation/audio', { shot_id: shotId, audio_track: audioTrack, confirm })

export const generateAsr = (episodeId: number, audioTrackIds: number[], confirm = false) =>
  http.post<never, TaskAccept>('/api/generation/asr', { episode_id: episodeId, audio_track_ids: audioTrackIds, confirm })

export interface TaskAccept {
  task_id: string
  status: string
  cached?: boolean
  require_confirm?: boolean
  estimate?: Record<string, unknown>
}

export const getTask = (taskId: string) => http.get<never, GenTask>(`/api/generation/tasks/${taskId}`)

export const cancelTask = (taskId: string) => http.post<never, GenTask>(`/api/generation/tasks/${taskId}/cancel`)

export const retryTask = (taskId: string) => http.post<never, GenTask>(`/api/generation/tasks/${taskId}/retry`)

export const listProjectTasks = (
  projectId: number,
  params: { status?: string; type?: string; page?: number; page_size?: number },
) => http.get<never, { total: number; items: GenTask[] }>(`/api/projects/${projectId}/generation/tasks`, { params })

/** 任务事件 SSE 地址（EventSource 使用）。 */
export const taskEventsUrl = (taskId: string) => `/api/generation/tasks/${taskId}/events`

// ---- 素材 ----
export const uploadAsset = (file: File, projectId: number, assetType: string) => {
  const form = new FormData()
  form.append('file', file)
  form.append('project_id', String(projectId))
  form.append('asset_type', assetType)
  return http.post<never, Asset>('/api/assets/upload', form)
}

export const listAssets = (params: { project_id?: number; asset_type?: string; page?: number; page_size?: number }) =>
  http.get<never, { total: number; items: Asset[] }>('/api/assets', { params })

export const deleteAsset = (id: number) => http.delete(`/api/assets/${id}`)

// ---- 渲染 ----
export const createRenderJob = (body: { episode_id: number; subtitle_burn_in: boolean }) =>
  http.post<never, RenderJob>('/api/render/jobs', body)

export const getRenderJob = (jobId: string) => http.get<never, RenderJob>(`/api/render/jobs/${jobId}`)

export const listEpisodeJobs = (episodeId: number) => http.get<never, RenderJob[]>(`/api/render/episodes/${episodeId}/jobs`)

// ---- Provider 配置 ----
export const listProviderConfigs = () => http.get<never, ProviderConfig[]>('/api/provider-configs')

export const updateProviderConfig = (capability: string, body: Record<string, unknown>) =>
  http.put<never, ProviderConfig>(`/api/provider-configs/${capability}`, body)

// ---- 成本统计（阶段五） ----
export interface CostStat {
  provider: string
  model: string
  total_calls: number
  succeeded: number
  failed: number
  success_rate: number
  total_cost: number
  avg_elapsed_ms: number | null
}

export const getCostStats = (projectId?: number) =>
  http.get<never, CostStat[]>('/api/stats/cost', { params: projectId ? { project_id: projectId } : {} })

export interface HealthCheck {
  status: 'up' | 'down'
  message?: string
}

export interface Readiness {
  service: string
  status: 'up' | 'down'
  profile: string
  checks: Record<string, HealthCheck & Record<string, unknown>>
}

/** 健康轮询静默执行，保留 503 依赖诊断，不重复弹出错误消息。 */
export async function getReadiness(): Promise<Readiness> {
  const response = await axios.get<ApiResponse<Readiness>>('/api/health', {
    timeout: 5000, validateStatus: (status) => status === 200 || status === 503,
  })
  const body = response.data
  if (!body?.data?.checks || body.data.service !== 'ai-drama') throw new Error('后端服务不可达')
  return body.data
}
