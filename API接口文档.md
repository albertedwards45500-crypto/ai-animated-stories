# API 接口文档：AI 漫剧生产系统 v0.1

- 基础地址：`http://127.0.0.1:8000`
- 风格：REST + JSON；任务进度用 SSE
- 认证：首版单用户本地部署，暂不做鉴权；接口预留 `Authorization` 头
- Content-Type：`application/json; charset=utf-8`（文件上传用 `multipart/form-data`）

## 1. 统一响应格式

```json
// 成功
{ "code": 0, "message": "ok", "data": { } }
// 失败
{ "code": 40001, "message": "参数校验失败", "data": { "errors": [ { "field": "story_outline", "reason": "required" } ] } }
```

### 错误码

| code | HTTP | 含义 |
|------|------|------|
| 0 | 200 | 成功 |
| 40001 | 400 | 参数校验失败 |
| 40002 | 400 | 业务校验失败（如字幕时间非法） |
| 40401 | 404 | 资源不存在 |
| 40901 | 409 | 状态冲突（如删除项目时存在进行中任务） |
| 42901 | 429 | 超出 Provider 每日额度 |
| 50001 | 500 | 服务器内部错误 |
| 50201 | 502 | 上游 AI 供应商错误 |
| 50401 | 504 | 上游超时 |

### 任务状态枚举

`queued` / `processing` / `succeeded` / `failed` / `timeout` / `cancelled`

---

## 2. 项目管理

### 2.1 创建项目

`POST /api/projects`

```json
// 请求
{
  "name": "都市夜行",
  "genre": "悬疑",
  "audience": "18-30 城市青年",
  "style_preset_id": 1,
  "default_episode_duration": 60,
  "world_rules": { "banned": ["真实品牌", "真人肖像"] }
}
// 响应 data
{ "id": 1, "name": "都市夜行", "status": 1, "created_at": "2026-10-13T10:00:00+08:00" }
```

### 2.2 项目列表

`GET /api/projects?page=1&page_size=20&keyword=`

响应 data：`{ "total": 12, "items": [ ... ] }`

### 2.3 项目详情 / 更新 / 删除

- `GET /api/projects/{id}` — 返回项目全量字段及剧集数统计
- `PUT /api/projects/{id}` — 部分更新，body 同创建（均可选）
- `DELETE /api/projects/{id}` — 若存在进行中任务返回 `40901`

---

## 3. 剧本、场景与分镜

### 3.1 生成剧本（异步任务）

`POST /api/projects/{id}/script/generate`

```json
// 请求
{
  "episode": {
    "title": "第一集：雨夜来电",
    "story_outline": "深夜，林夏接到一通不该存在的电话……",
    "target_duration": 60
  },
  "provider": "mock"          // 可选，默认取当前配置
}
// 响应 data：返回任务，进度走 SSE
{ "task_id": "b7c1...", "status": "queued", "poll": "/api/generation/tasks/b7c1..." }
```

生成完成后，通过 `GET /api/projects/{id}/episodes` 读取落库结果（script_json）。

### 3.2 剧集

- `GET /api/projects/{id}/episodes` — 列表
- `GET /api/episodes/{id}` — 详情，含 scenes/shots 概要
- `PUT /api/episodes/{id}` — 更新标题/梗概/状态

### 3.3 场景

`POST /api/episodes/{id}/scenes`

```json
// 请求
{ "scene_no": 1, "code": "scene_001", "location_id": 3, "time_of_day": "night", "purpose": "铺垫悬念", "summary": "雨夜，主角接到电话" }
// 响应 data
{ "id": 11, "episode_id": 2, "scene_no": 1, "code": "scene_001" }
```

- `GET /api/episodes/{id}/scenes` — 场景列表（含 shots 数）
- `PUT /api/scenes/{id}` / `DELETE /api/scenes/{id}`

### 3.4 分镜

`POST /api/scenes/{id}/shots`

```json
// 请求
{
  "shot_no": 1, "code": "shot_001",
  "shot_type": "近景", "camera_movement": "推",
  "character_ids": [1],
  "action_description": "林夏盯着屏幕，手指悬在接听键上",
  "dialogue": [ { "character_id": 1, "text": "你终于来了。", "emotion": "紧张但克制" } ],
  "duration": 5.0
}
// 响应 data
{ "id": 21, "scene_id": 11, "code": "shot_001", "status": 0 }
```

- `PUT /api/shots/{id}` — 更新全部可编辑字段（含 visual_prompt）
- `DELETE /api/shots/{id}`
- `GET /api/episodes/{id}/shots` — 跨场景按播放顺序返回分镜（时间轴数据源）

### 3.5 生成/更新分镜提示词（异步任务）

`POST /api/shots/{id}/storyboard` — 以已确认剧本、角色卡、场景卡为输入，生成 `visual_prompt`（image_prompt / video_prompt / negative_prompt / continuity_notes），Mock 可用。

---

## 4. 设定：角色 / 场景卡 / 画风

- `POST /api/projects/{id}/characters` — 创建角色卡（外观固定词、voice_id、emotions）
- `GET /api/projects/{id}/characters` / `PUT /api/characters/{id}` / `DELETE /api/characters/{id}`
- `POST /api/characters/{id}/confirm` — 锁定角色卡，`version+1`，此后生成任务只能按版本引用
- `POST /api/characters/{id}/assets` — 上传参考图（multipart）
- `POST /api/projects/{id}/locations`、`GET/PUT/DELETE /api/locations/{id}` — 场景卡
- `POST /api/style-presets`、`GET/PUT/DELETE /api/style-presets/{id}` — 画风预设

---

## 5. AI 生成任务

### 5.1 发起生成（统一入口）

`POST /api/generation/{type}`，`type ∈ text | image | video | audio`

```json
// POST /api/generation/image —— 生成关键帧
{
  "shot_id": 21,
  "provider": "mock",                  // mock/aliyun/volcengine/tencent/minimax
  "params": {
    "style_preset_id": 1,
    "size": "768x1344",
    "seed": null
  }
}
// 响应 data
{ "task_id": "e1f2...", "status": "queued", "estimated_wait_s": 3 }
```

```json
// POST /api/generation/audio —— 对白语音
{
  "shot_id": 21,
  "audio_track": {
    "track_type": "dialogue", "character_id": 1,
    "text": "你终于来了。", "emotion": "紧张但克制",
    "speed": 1.0, "pitch": 0, "pause_after_ms": 300
  }
}
```

**成本控制行为**：
- 相同参数（参数哈希命中缓存）直接返回已有素材，`task_id` 指向缓存命中的历史任务。
- `provider != mock` 时，若开启调用确认，接口返回 `{ "require_confirm": true, "estimate": {...} }`，需携带 `confirm: true` 重发。
- 超出每日额度返回 `42901`。

### 5.2 字幕（ASR）

`POST /api/generation/asr` — body：`{ "episode_id": 2, "audio_track_ids": [31, 32] }`；本地 Whisper 优先。

### 5.3 任务查询与控制

- `GET /api/generation/tasks/{id}` — 状态、进度、错误、输出素材
- `POST /api/generation/tasks/{id}/cancel` — queued/processing 可取消；终态返回 `40901`
- `POST /api/generation/tasks/{id}/retry` — failed/timeout/cancelled 可重试，`retry_count+1`
- `GET /api/projects/{id}/generation/tasks?status=&type=&page=` — 任务中心列表

### 5.4 任务进度 SSE

`GET /api/generation/tasks/{id}/events`

```text
HTTP/1.1 200 OK
Content-Type: text/event-stream

event: progress
data: {"task_id":"e1f2...","status":"processing","progress":40}

event: status
data: {"task_id":"e1f2...","status":"succeeded","progress":100,"output_asset_ids":[55]}

event: error
data: {"task_id":"e1f2...","status":"failed","error_message":"provider timeout"}
```

- 心跳：每 15 秒发送 `: ping`。
- 断线重连后从 `Last-Event-ID` 续传；前端降级方案为轮询 5.3 查询接口。
- 后续若需双向控制再改 WebSocket。

---

## 6. 素材

- `POST /api/assets/upload`（multipart：file、project_id、asset_type）— 上传本地素材
- `GET /api/assets/{id}` — 素材元信息
- `GET /api/assets/{id}/raw` — 文件流（预览用，支持 Range）
- `GET /api/projects/{id}/assets?asset_type=image&page=` — 素材库列表
- `DELETE /api/assets/{id}`

---

## 7. 成片渲染

### 7.1 发起合成

`POST /api/render/jobs`

```json
// 请求
{
  "episode_id": 2,
  "subtitle_burn_in": true,
  "subtitle_style": { "font_size": 42, "outline": 2, "position": "bottom" },
  "audio": { "bgm_asset_id": 60, "bgm_volume": 0.2 }
}
// 响应 data
{ "job_id": "r9a8...", "task_id": "t7f6...", "status": "queued" }
```

合成前校验失败返回 `40002`（如某分镜缺视频素材、字幕时间越界）。

### 7.2 查询与预览

- `GET /api/render/jobs/{job_id}` — 状态与输出
- `GET /api/render/jobs/{job_id}/preview` — 302 跳转到成片文件流
- `GET /api/render/jobs/{job_id}/download` — 附件下载（`Content-Disposition`）

---

## 8. Provider 配置

- `GET /api/provider-configs` — 各能力当前配置（**不含密钥**）
- `PUT /api/provider-configs/{capability}` — 更新 provider/mode/model/超时/额度；API Key 通过环境变量注入，接口只写变量名

---

## 9. 通用约定

1. 分页参数统一 `page`（从 1 起）、`page_size`（默认 20，最大 100）。
2. 时间统一 ISO 8601 带时区。
3. ID 类外露标识：任务/渲染用 uuid，其余资源用自增 id。
4. 所有生成类接口均为异步：先落库 queued，再投递 Dramatiq 队列；同步只返回任务受理结果。
