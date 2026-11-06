# AI 漫剧项目初版开发文档

## 1. 文档信息

- 版本：v0.1
- 状态：初版方案
- 目标：先完成本地 Mock 闭环，再逐步接入国产 AI API
- 运行环境：个人笔记本电脑，RTX 4060，8GB 显存
- 当前工作区：项目尚未初始化，以下方案作为开发基线

## 2. 项目目标

构建一个面向个人创作的小型 AI 漫剧生产系统，支持：

1. 创建项目和剧集。
2. 输入故事梗概并生成结构化剧本。
3. 管理角色、场景和画风设定。
4. 将剧本拆分为场景和分镜。
5. 生成或上传分镜关键帧。
6. 生成角色对白和旁白语音。
7. 自动生成字幕和时间轴。
8. 合成短视频并预览、下载。
9. 记录每次 AI 任务的状态、输入、输出和错误。

首版不追求完整的自动化长片生产，优先验证一条可重复的短视频闭环。

## 3. 非目标

首版暂不包含：

- 多用户权限和复杂团队协作。
- 移动端原生应用。
- 本地运行大型视频生成模型。
- 高并发生产和分布式 GPU 调度。
- 自动发布到短视频平台。

## 4. 硬件与运行策略

RTX 4060 8GB 不适合作为大型视频模型的唯一运行环境。采用以下策略：

### 本地执行

- Mock 服务和任务调度。
- ComfyUI 图片实验、角色参考图和关键帧生成。
- Whisper 字幕识别。
- FFmpeg 音视频合成。
- 文件预览和项目管理。

### 云端或第三方 API 执行

- 高质量图片批量生成。
- 视频生成。
- 高质量或声音克隆语音。
- 大模型剧本生成。

AI 服务必须通过 Provider 适配层接入，业务代码不能直接依赖某一家供应商。

## 5. 技术栈

### 前端

- Vue 3
- TypeScript
- Vite
- Vue Router
- Pinia
- Element Plus
- Axios
- VueUse
- Vue Flow：分镜或工作流视图
- SSE 或 WebSocket：任务进度

### 后端

- Python 3.11+
- FastAPI
- Pydantic v2
- SQLAlchemy 2.x
- Alembic
- MySQL 8.x
- Redis
- Dramatiq 或 Celery：异步任务
- MinIO 或本地素材目录：对象存储
- FFmpeg：音视频处理
- pytest：测试

首版建议使用 Dramatiq；当任务规模和部署复杂度增加后再评估 Celery。

### AI 与媒体组件

- ComfyUI：本地图片工作流
- ControlNet：姿态和构图控制
- InstantID 或 IP-Adapter：角色一致性
- Whisper：字幕和语音时间轴
- FFmpeg：转码、混音、字幕烧录和封装
- Remotion：后续需要复杂动态字幕和程序化片头时引入

## 6. 系统架构

```text
Vue 3 创作端
    │ REST + SSE/WebSocket
    ▼
FastAPI API
    ├── 项目/剧集服务
    ├── 剧本服务
    ├── 角色和场景服务
    ├── 分镜服务
    ├── AI Provider 适配层
    ├── 任务调度服务
    ├── 素材服务
    └── 渲染服务
          ├── MySQL
          ├── Redis
          ├── MinIO/本地素材目录
          ├── Mock/国产 AI API
          └── FFmpeg/Whisper
```

## 7. Provider 设计

### 7.1 支持模式

每类 AI 能力支持三种运行模式：

- `mock`：不调用外部服务，使用固定或随机测试素材。
- `record`：调用真实 API，并保存请求和响应。
- `replay`：使用已保存的真实响应，避免重复消费 API。

### 7.2 统一接口

建议为文本、图片、视频和语音分别定义接口：

```python
class VideoProvider(Protocol):
    async def submit(self, request: VideoRequest) -> TaskResult: ...
    async def get_status(self, task_id: str) -> TaskStatus: ...
    async def cancel(self, task_id: str) -> None: ...
```

实现类示例：

```text
MockTextProvider
MockImageProvider
MockVideoProvider
MockAudioProvider
AliyunProvider
VolcengineProvider
TencentProvider
MinimaxProvider
```

### 7.3 统一任务状态

```text
queued → processing → succeeded
                    ├→ failed
                    ├→ timeout
                    └→ cancelled
```

Mock 服务也必须模拟排队、处理中、失败、超时、取消和重试，不能永远成功。

## 8. 国产 AI 服务调研方向

实际接入前需核实 API、模型、价格、商用许可和地域可用性。

### 文本

- DeepSeek
- 阿里通义千问/百炼
- 智谱 GLM
- 百度文心/千帆
- Kimi
- MiniMax

### 图片

- 阿里通义万相/百炼
- 火山引擎或即梦相关能力
- 腾讯混元
- 百度相关图像生成能力

### 视频

- 阿里通义万相
- 火山引擎视频生成
- 腾讯混元视频
- MiniMax
- 可灵开发者 API（需确认正式开放范围）

### 语音

- MiniMax Voice
- 火山引擎豆包语音
- 阿里云 CosyVoice/百炼语音
- 腾讯云语音合成
- 百度智能云语音
- 科大讯飞开放平台

### 字幕

- 首版优先使用本地 Whisper，避免重复 API 成本。
- 后续可接入阿里云、火山引擎、腾讯云、百度或科大讯飞 ASR。

## 9. 核心业务流程

```text
创建项目
  ↓
输入故事梗概
  ↓
生成结构化剧本
  ↓
拆分场景和分镜
  ↓
维护角色、场景和画风
  ↓
生成/上传关键帧
  ↓
生成对白语音
  ↓
生成字幕时间轴
  ↓
生成或上传视频片段
  ↓
FFmpeg 合成成片
  ↓
预览和下载
```

## 10. 数据库设计

### 10.1 核心表

```text
projects              项目
episodes              剧集
scenes                场景
shots                 分镜
characters            角色
character_assets      角色参考图和素材
locations             场景/地点
style_presets         画风配置
prompts               提示词记录
generation_tasks      AI 生成任务
generated_assets      生成素材
audio_tracks          音频轨道
video_clips           视频片段
subtitles             字幕
render_jobs           成片渲染任务
provider_configs      Provider 配置
```

### 10.2 generation_tasks 关键字段

```text
id
project_id
type                  text/image/video/audio/asr/render
provider              mock/aliyun/volcengine/tencent/minimax
model
status
progress
request_payload
response_payload
input_asset_ids
output_asset_ids
retry_count
error_message
cost
started_at
finished_at
created_at
```

### 10.3 分镜关键字段

```text
episode_id
scene_no
shot_no
location_id
character_ids
shot_type             远景/全景/中景/近景/特写
camera_movement       固定/推/拉/摇/移
action_description
dialogue
visual_prompt
duration
keyframe_asset_id
video_asset_id
```

## 10.4 提示词工程规范

提示词不能散落在前端按钮或业务代码中，应作为可版本化的模板和数据保存。每次生成都必须记录：

```text
template_id
template_version
system_prompt
user_prompt
variables_json
model
provider
temperature
seed
input_asset_ids
output_asset_ids
```

### 10.4.1 通用规则

所有生成提示词遵循以下规则：

1. 先说明任务和输出目标，再提供项目上下文。
2. 使用明确的字段和枚举，不使用“自由发挥”这类不受控表述。
3. 要求模型只返回约定格式，不返回 Markdown、解释文字或额外字段。
4. 角色、场景、画风和时间信息使用稳定 ID 引用，避免每次重新描述导致漂移。
5. 生成前校验输入长度、必填字段和枚举值；生成后校验 JSON Schema。
6. 解析失败时只允许有限次数的“修复 JSON”重试，不重复调用昂贵的视频 API。
7. 中文内容用于剧情和对白，图片/视频模型提示词可根据供应商要求转换为中文或英文。
8. 禁止在提示词中放入 API Key、数据库密码、用户隐私和未授权的真人身份信息。

### 10.4.2 剧本生成提示词

系统提示词模板：

```text
你是专业的中文短剧编剧和分镜策划。你的任务是把用户提供的故事梗概改写成可执行的 AI 漫剧剧本。

创作要求：
- 情节必须有明确的目标、冲突、转折和结尾。
- 每集只保留必要动作，适合 30～90 秒短视频。
- 角色行为必须符合角色设定，不能无原因改变性格或立场。
- 对白口语化，避免长段独白；每句对白标明说话角色。
- 不编造用户未提供的现实人物、品牌、版权角色或敏感事实。
- 所有场景、角色和镜头必须使用稳定编号。

输出要求：只返回符合指定 JSON Schema 的 JSON，不要 Markdown，不要解释。
```

用户提示词变量：

```text
项目类型：{genre}
目标受众：{audience}
画风：{style}
单集目标时长：{episode_duration_seconds} 秒
本集标题：{episode_title}
故事梗概：{story_outline}
角色设定：{characters_json}
世界观和禁用内容：{world_rules_json}
```

输出最少包含：

```json
{
  "episode_title": "",
  "logline": "",
  "characters": [],
  "scenes": [
    {
      "scene_id": "scene_001",
      "location_id": "location_001",
      "time_of_day": "night",
      "purpose": "",
      "shots": [
        {
          "shot_id": "shot_001",
          "duration_seconds": 5,
          "characters": ["char_001"],
          "action": "",
          "dialogue": [],
          "sound_cue": ""
        }
      ]
    }
  ]
}
```

### 10.4.3 分镜提示词

分镜生成必须以已确认的剧本、角色卡和场景卡为输入，不允许模型重新发明角色外观。

```text
你是 AI 漫剧分镜导演。请将输入镜头改写为可供图像/视频模型执行的单镜头描述。

必须保留：
- character_id 对应的外观和服装。
- location_id 对应的场景、时间和光线。
- 镜头中的人物数量、动作方向和情绪。
- 用户指定的景别、机位和镜头运动。

必须输出：
- 中文画面描述。
- image_prompt：静态关键帧提示词。
- video_prompt：动态镜头提示词。
- negative_prompt：统一负面提示词。
- continuity_notes：与上一镜头的连续性要求。

禁止：新增角色、改变服装颜色、改变季节、添加未授权文字和水印。
只返回 JSON。
```

推荐结构：

```json
{
  "shot_id": "shot_001",
  "image_prompt": {
    "subject": "",
    "appearance": "",
    "action": "",
    "environment": "",
    "composition": "",
    "lighting": "",
    "style": ""
  },
  "video_prompt": {
    "motion": "",
    "camera": "",
    "duration_seconds": 5,
    "motion_strength": "low"
  },
  "negative_prompt": "low quality, distorted anatomy, extra fingers, inconsistent character, text, watermark",
  "continuity_notes": ""
}
```

### 10.4.4 图片生成提示词拼装

图片提示词由固定片段和镜头变量拼装，不建议完全依赖大模型一次性生成：

```text
[画风固定词]
+ [角色卡固定词]
+ [场景卡固定词]
+ [动作和表情]
+ [构图和景别]
+ [光线和色彩]
+ [质量约束]
+ [负面提示词]
```

角色卡至少保存：

```text
character_id
name
age_range
gender_presentation
hair
face_features
body_shape
clothing
color_palette
style_tokens
reference_asset_ids
```

角色卡一旦确认，除非用户主动修改，否则生成任务只能引用版本号，不允许自动覆盖。

### 10.4.5 视频生成提示词

视频提示词只描述镜头内的运动，不重复大段静态外观：

```text
静态外观：引用关键帧 shot_001_keyframe
主体动作：{action}
表情变化：{emotion_change}
镜头运动：{camera_movement}
环境运动：{environment_motion}
节奏：{pace}
时长：{duration_seconds} 秒
限制：保持角色脸部、服装、发型和场景布局不变，不新增人物，不出现文字和水印
```

在 RTX 4060 本地或云端 API 初期，建议把单镜头控制在 3～8 秒，并优先使用“关键帧到视频”而不是完全文本生成视频。

### 10.4.6 语音生成提示词

语音请求和文本提示词分离保存：

```json
{
  "character_id": "char_001",
  "voice_id": "provider_voice_001",
  "text": "你终于来了。",
  "emotion": "紧张但克制",
  "speed": 1.0,
  "pitch": 0,
  "pause_after_ms": 300,
  "pronunciation_notes": []
}
```

原则：同一角色固定 `voice_id`；情绪只能从项目配置的枚举中选择；对白生成后保留原文、规范化文本和最终音频三个版本。

### 10.4.7 字幕提示词和校验

字幕优先由 Whisper 或供应商 ASR 生成，语言模型只负责断句、标点和角色标注，不负责擅自改写对白。

校验规则：

- 字幕开始时间小于结束时间。
- 时间不能超出视频时长。
- 相邻字幕不能发生不合理重叠。
- 字幕文本必须能在原始对白或识别结果中找到依据。
- 角色名和对白分开保存，支持后续样式渲染。

### 10.4.8 提示词版本和评估

每个模板修改都递增版本号，例如 `script.v1.1`、`storyboard.v1.0`。建立小型回归数据集，至少包含：

- 3 个普通剧情样例。
- 1 个多角色对话样例。
- 1 个连续动作样例。
- 1 个失败或输入不完整样例。

每次修改模板后检查：JSON 合法率、必填字段完整率、角色一致性、镜头时长误差和重复调用率。没有通过校验的结果不能直接进入图片、视频或语音生成。

## 11. API 初版规划

### 项目

```text
POST   /api/projects
GET    /api/projects
GET    /api/projects/{id}
PUT    /api/projects/{id}
DELETE /api/projects/{id}
```

### 剧本和分镜

```text
POST /api/projects/{id}/script/generate
GET  /api/projects/{id}/episodes
POST /api/episodes/{id}/scenes
POST /api/scenes/{id}/shots
PUT  /api/shots/{id}
```

### AI 任务

```text
POST /api/generation/text
POST /api/generation/image
POST /api/generation/video
POST /api/generation/audio
GET  /api/generation/tasks/{id}
POST /api/generation/tasks/{id}/cancel
GET  /api/generation/tasks/{id}/events
```

`/events` 使用 SSE 推送进度；如果以后需要双向控制，再改用 WebSocket。

### 成片

```text
POST /api/render/jobs
GET  /api/render/jobs/{id}
GET  /api/render/jobs/{id}/preview
```

## 12. Mock 阶段方案

Mock 素材目录建议：

```text
media/mock/images/
media/mock/audio/
media/mock/video/
media/mock/subtitles/
```

首版准备：

- 3 张角色/场景测试图。
- 2 个对白音频。
- 1 个 5 秒视频片段。
- 1 个 ASS 或 SRT 字幕文件。
- 1 个合成后的测试视频。

验收要求：

- 前端能看到任务排队、处理中、成功和失败。
- 刷新页面后任务状态不丢失。
- 任务失败后可以重试或取消。
- 可以预览图片、音频、视频和字幕。
- 能把素材合成一个可播放的视频。

## 13. 配置与安全

所有密码和 API Key 使用环境变量，不写入代码和 Git：

```env
APP_ENV=development
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_DATABASE=ai_drama
MYSQL_USER=root
MYSQL_PASSWORD=change_me_dev
REDIS_URL=redis://127.0.0.1:6379/0
AI_MODE=mock
TEXT_PROVIDER=mock
IMAGE_PROVIDER=mock
VIDEO_PROVIDER=mock
AUDIO_PROVIDER=mock
MEDIA_ROOT=./media
```

此前对话中出现过数据库密码，不应继续使用或提交到仓库，建议立即更换。

API Key 管理要求：

- 不放在 Vue 前端。
- 不写入日志。
- 不返回给浏览器。
- 供应商请求和响应中的敏感字段需要脱敏。
- 每个 Provider 设置超时、重试次数和每日额度。

## 14. 开发阶段

### 阶段一：基础工程

- 初始化 Vue 3、FastAPI、MySQL、Redis。
- 建立数据库迁移。
- 建立统一响应格式和错误码。
- 完成项目、剧集、场景、分镜 CRUD。

### 阶段二：Mock 闭环

- 完成 Mock Provider。
- 完成任务队列和进度推送。
- 完成素材预览。
- 完成 FFmpeg 合成。
- 完成最小端到端测试。

### 阶段三：文本和语音

- 接入一个文本供应商。
- 接入一个语音供应商。
- 保存请求、响应和费用。
- 接入本地 Whisper 生成字幕。

### 阶段四：图片和视频

- 接入图片供应商。
- 增加角色参考图和风格配置。
- 接入视频供应商。
- 增加超时、取消和失败重试。

### 阶段五：体验优化

- 增加分镜时间轴。
- 增加角色一致性工作流。
- 增加成本统计和缓存。
- 增加素材版本管理。

## 15. 成本控制

- 默认 `AI_MODE=mock`。
- 对相同请求做参数哈希缓存。
- 真实 API 调用前显示确认信息。
- 限制每日调用量和单任务最大时长。
- 视频生成最后接入。
- 使用 `record/replay` 反复调试，避免重复消费。
- 记录供应商、模型、耗时、成本和失败原因。

## 16. 初版验收标准

完成以下流程即视为 v0.1 可用：

1. 创建一个项目和一集内容。
2. 输入梗概并生成一份结构化 Mock 剧本。
3. 剧本包含场景、角色、对白和分镜。
4. 为分镜关联图片和视频素材。
5. 为对白关联音频。
6. 生成或加载字幕文件。
7. 通过 FFmpeg 合成一个可播放视频。
8. 前端实时显示任务进度。
9. 失败任务可以重试，用户可以取消任务。
10. 刷新页面后项目和任务数据仍然存在。

## 17. GitHub 参考项目

- [ComfyUI](https://github.com/Comfy-Org/ComfyUI)：节点式图像/视频工作流。
- [ControlNet](https://github.com/lllyasviel/ControlNet)：姿态和构图控制。
- [InstantID](https://github.com/InstantID/InstantID)：身份特征保持。
- [IP-Adapter](https://github.com/tencent-ailab/IP-Adapter)：参考图控制。
- [Whisper](https://github.com/openai/whisper)：语音识别和字幕时间轴。
- [Remotion](https://github.com/remotion-dev/remotion)：程序化视频合成。
- [FFmpeg](https://github.com/FFmpeg/FFmpeg)：媒体处理底层能力。
- [LTX-Video](https://github.com/Lightricks/LTX-Video)：视频生成研究和本地实验。
- [Wan2.1](https://github.com/Wan-Video/Wan2.1)：视频生成研究参考。

## 18. 关键决策总结

1. 先 Mock，再接 API。
2. 所有 AI 能力通过 Provider 抽象。
3. 本地 RTX 4060 主要负责轻量推理和后处理。
4. 视频生成最后接入。
5. Whisper 和 FFmpeg 优先本地运行。
6. 任务状态、请求响应和素材版本必须持久化。
7. API Key 和数据库密码只放环境变量。
