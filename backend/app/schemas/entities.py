# -*- coding: utf-8 -*-
"""Pydantic v2 请求/响应模型集合。

按《API接口文档.md》定义请求体与响应体结构，
字段校验规则与文档保持一致。
"""
from pydantic import BaseModel, ConfigDict, Field


class ORMModel(BaseModel):
    """支持从 ORM 对象序列化的基类。"""

    model_config = ConfigDict(from_attributes=True)


class PageQuery(BaseModel):
    """分页查询参数。

    Attributes:
        page: 页码，从 1 起。
        page_size: 每页条数，默认 20，最大 100。
    """

    page: int = Field(1, ge=1, description="页码，从 1 起")
    page_size: int = Field(20, ge=1, le=100, description="每页条数，最大 100")


# ---------- 项目 ----------
class ProjectCreate(BaseModel):
    """创建项目请求体。"""

    name: str = Field(..., min_length=1, max_length=100, description="项目名，必填")
    genre: str | None = Field(None, max_length=50, description="项目类型")
    audience: str | None = Field(None, max_length=100, description="目标受众")
    style_preset_id: int | None = Field(None, description="默认画风预设")
    default_episode_duration: int = Field(60, ge=10, le=600, description="单集目标时长(秒)")
    world_rules: dict | None = Field(None, description="世界观与禁用内容")
    description: str | None = Field(None, description="备注")


class ProjectUpdate(BaseModel):
    """更新项目请求体（部分更新，均可选）。"""

    name: str | None = Field(None, min_length=1, max_length=100)
    genre: str | None = Field(None, max_length=50)
    audience: str | None = Field(None, max_length=100)
    style_preset_id: int | None = None
    default_episode_duration: int | None = Field(None, ge=10, le=600)
    world_rules: dict | None = None
    description: str | None = None
    status: int | None = Field(None, ge=0, le=1)


# ---------- 剧集 ----------
class EpisodeCreate(BaseModel):
    """创建剧集请求体。"""

    episode_no: int | None = Field(None, ge=1, description="集序号，缺省自动递增")
    title: str = Field(..., min_length=1, max_length=200, description="集标题")
    logline: str | None = Field(None, max_length=500, description="一句话简介")
    story_outline: str = Field(..., min_length=1, max_length=2000, description="故事梗概，2000 字上限")
    target_duration: int | None = Field(None, ge=30, le=90, description="目标时长(秒) 30~90")


class EpisodeUpdate(BaseModel):
    """更新剧集请求体。"""

    title: str | None = Field(None, min_length=1, max_length=200)
    logline: str | None = Field(None, max_length=500)
    story_outline: str | None = Field(None, min_length=1, max_length=2000)
    target_duration: int | None = Field(None, ge=30, le=90)
    status: int | None = Field(None, ge=0, le=3)


class ScriptGenerateRequest(BaseModel):
    """生成剧本请求体（异步任务）。

    Attributes:
        episode: 剧集创建信息（title/story_outline/target_duration）。
        provider: 供应商标识，可选，默认取当前配置。
    """

    episode: EpisodeCreate
    provider: str | None = Field(None, description="provider，缺省取配置")


# ---------- 场景 ----------
class SceneCreate(BaseModel):
    """创建剧本场景请求体。"""

    scene_no: int = Field(..., ge=1, description="场景序号，集内唯一")
    code: str | None = Field(None, max_length=50, description="稳定编号 scene_001")
    location_id: int | None = None
    time_of_day: str | None = Field(None, pattern="^(dawn|day|dusk|night)$")
    purpose: str | None = Field(None, max_length=300)
    summary: str | None = None


class SceneUpdate(BaseModel):
    """更新场景请求体。"""

    location_id: int | None = None
    time_of_day: str | None = Field(None, pattern="^(dawn|day|dusk|night)$")
    purpose: str | None = Field(None, max_length=300)
    summary: str | None = None


# ---------- 分镜 ----------
class DialogueLine(BaseModel):
    """对白行。

    Attributes:
        character_id: 说话角色 ID。
        text: 台词。
        emotion: 情绪标签。
    """

    character_id: int = Field(..., description="说话角色 ID，必选")
    text: str = Field(..., min_length=1, description="台词，非空")
    emotion: str | None = Field(None, max_length=50)


class ShotCreate(BaseModel):
    """创建分镜请求体。"""

    shot_no: int = Field(..., ge=1, description="场内镜头序号")
    code: str | None = Field(None, max_length=50)
    shot_type: str | None = Field(None, description="远景/全景/中景/近景/特写")
    camera_movement: str | None = Field(None, description="固定/推/拉/摇/移")
    character_ids: list[int] | None = None
    location_id: int | None = None
    action_description: str | None = None
    dialogue: list[DialogueLine] | None = None
    visual_prompt: dict | None = None
    duration: float = Field(5.0, gt=0, le=60, description="镜头时长(秒)")


class ShotUpdate(BaseModel):
    """更新分镜请求体（含 visual_prompt）。"""

    shot_type: str | None = None
    camera_movement: str | None = None
    character_ids: list[int] | None = None
    location_id: int | None = None
    action_description: str | None = None
    dialogue: list[DialogueLine] | None = None
    visual_prompt: dict | None = None
    duration: float | None = Field(None, gt=0, le=60)


# ---------- 角色 / 场景卡 / 画风 ----------
class CharacterCreate(BaseModel):
    """创建角色卡请求体。"""

    code: str | None = Field(None, max_length=50, description="稳定编号，缺省自动生成")
    name: str = Field(..., min_length=1, max_length=100)
    age_range: str | None = Field(None, max_length=20)
    gender_presentation: str | None = Field(None, max_length=20)
    hair: str | None = Field(None, max_length=300)
    face_features: str | None = Field(None, max_length=300)
    body_shape: str | None = Field(None, max_length=200)
    clothing: str | None = Field(None, max_length=300)
    color_palette: list[str] | None = None
    style_tokens: list[str] | None = None
    voice_id: str | None = Field(None, max_length=100)
    voice_emotions: list[str] | None = None


class CharacterUpdate(BaseModel):
    """更新角色卡请求体（未锁定前可改）。"""

    name: str | None = Field(None, min_length=1, max_length=100)
    age_range: str | None = None
    gender_presentation: str | None = None
    hair: str | None = None
    face_features: str | None = None
    body_shape: str | None = None
    clothing: str | None = None
    color_palette: list[str] | None = None
    style_tokens: list[str] | None = None
    voice_id: str | None = None
    voice_emotions: list[str] | None = None


class LocationCreate(BaseModel):
    """创建场景卡（地点）请求体。"""

    code: str | None = Field(None, max_length=50)
    name: str = Field(..., min_length=1, max_length=100)
    description: str | None = None
    time_of_day: str | None = Field(None, pattern="^(dawn|day|dusk|night)$")
    lighting: str | None = Field(None, max_length=200)
    scene_prompt: str | None = None


class LocationUpdate(BaseModel):
    """更新场景卡请求体。"""

    name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = None
    time_of_day: str | None = Field(None, pattern="^(dawn|day|dusk|night)$")
    lighting: str | None = None
    scene_prompt: str | None = None


class StylePresetCreate(BaseModel):
    """创建画风预设请求体。"""

    project_id: int | None = Field(None, description="缺省为全局预设")
    name: str = Field(..., min_length=1, max_length=100)
    style_prompt: str | None = None
    negative_prompt: str | None = None
    params: dict | None = None


class StylePresetUpdate(BaseModel):
    """更新画风预设请求体。"""

    name: str | None = Field(None, min_length=1, max_length=100)
    style_prompt: str | None = None
    negative_prompt: str | None = None
    params: dict | None = None


# ---------- 生成任务 ----------
class GenerationImageRequest(BaseModel):
    """生成关键帧请求体。"""

    shot_id: int = Field(..., description="目标分镜")
    provider: str | None = Field(None, description="mock/aliyun/...，缺省取配置")
    params: dict | None = Field(None, description="style_preset_id/size/seed 等")
    confirm: bool = Field(False, description="真实 API 调用确认标记")


class GenerationVideoRequest(BaseModel):
    """生成视频片段请求体。"""

    shot_id: int = Field(..., description="目标分镜")
    provider: str | None = None
    params: dict | None = None
    confirm: bool = Field(False, description="真实 API 调用确认标记")


class GenerationAudioRequest(BaseModel):
    """生成对白语音请求体。"""

    shot_id: int = Field(..., description="目标分镜")
    provider: str | None = None
    audio_track: dict = Field(..., description="track_type/character_id/text/emotion/speed/pitch/pause_after_ms")
    confirm: bool = Field(False, description="真实 API 调用确认标记")


class AsrRequest(BaseModel):
    """字幕识别（ASR）请求体。"""

    episode_id: int = Field(..., description="目标剧集")
    audio_track_ids: list[int] = Field(default_factory=list, description="音频轨 ID 列表，省略或为空时使用本集已生成的对白/旁白轨")
    provider: str | None = None
    confirm: bool = Field(False, description="真实 API 调用确认标记")


class StoryboardRequest(BaseModel):
    """分镜提示词生成请求体。"""

    provider: str | None = None
    confirm: bool = Field(False, description="真实 API 调用确认标记")


# ---------- 素材 ----------
class AssetUploadMeta(BaseModel):
    """上传素材元信息（multipart 伴随表单字段）。"""

    project_id: int = Field(..., description="所属项目")
    asset_type: str = Field(..., pattern="^(image|video|audio|subtitle)$", description="素材类型")
    episode_id: int | None = Field(None, description="字幕关联剧集（可选）")


# ---------- 渲染 ----------
class RenderJobCreate(BaseModel):
    """发起合成请求体。"""

    episode_id: int = Field(..., description="目标剧集")
    subtitle_burn_in: bool = Field(True, description="是否烧录字幕")
    subtitle_style: dict | None = Field(None, description="字体/描边/位置")
    audio: dict | None = Field(None, description="bgm_asset_id/bgm_volume")


# ---------- Provider 配置 ----------
class ProviderConfigUpdate(BaseModel):
    """更新 Provider 配置请求体（API Key 经环境变量注入，只写变量名）。"""

    provider: str | None = Field(None, max_length=50)
    mode: str | None = Field(None, pattern="^(mock|record|replay)$")
    model: str | None = Field(None, max_length=100)
    base_url: str | None = Field(None, max_length=255)
    api_key_ref: str | None = Field(None, max_length=100, description="环境变量名，不存明文")
    timeout_seconds: int | None = Field(None, ge=1, le=3600)
    max_retries: int | None = Field(None, ge=0, le=10)
    daily_quota: int | None = Field(None, ge=1)
    enabled: bool | None = None
