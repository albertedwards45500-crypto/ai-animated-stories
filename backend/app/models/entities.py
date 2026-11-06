# -*- coding: utf-8 -*-
"""全部核心数据表模型（16 张，依据《数据库设计.md》）。

projects / episodes / locations / characters / character_assets /
style_presets / scenes / shots / prompts / generation_tasks /
generated_assets / audio_tracks / video_clips / subtitles / render_jobs /
provider_configs。
"""
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    BigInteger,
    CHAR,
    DateTime,
    DECIMAL,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Project(Base, TimestampMixin):
    """项目表。"""

    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, comment="项目名")
    genre: Mapped[str | None] = mapped_column(String(50), comment="项目类型")
    audience: Mapped[str | None] = mapped_column(String(100), comment="目标受众")
    style_preset_id: Mapped[int | None] = mapped_column(BigInteger, comment="默认画风预设")
    world_rules: Mapped[dict | None] = mapped_column(JSON, comment="世界观与禁用内容")
    default_episode_duration: Mapped[int] = mapped_column(Integer, default=60, server_default=text("60"), comment="单集目标时长(秒)")
    description: Mapped[str | None] = mapped_column(Text, comment="备注")
    status: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"), comment="1=active 0=archived")

    __table_args__ = ({"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},)


class Episode(Base, TimestampMixin):
    """剧集表。"""

    __tablename__ = "episodes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True, comment="所属项目")
    episode_no: Mapped[int] = mapped_column(Integer, nullable=False, comment="集序号")
    title: Mapped[str | None] = mapped_column(String(200), comment="集标题")
    logline: Mapped[str | None] = mapped_column(String(500), comment="一句话简介")
    story_outline: Mapped[str | None] = mapped_column(Text, comment="故事梗概")
    script_json: Mapped[dict | None] = mapped_column(JSON, comment="最近一次生成的结构化剧本")
    target_duration: Mapped[int | None] = mapped_column(Integer, comment="目标时长(秒)")
    status: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"), comment="0=草稿 1=剧本已生成 2=素材就绪 3=已合成")

    __table_args__ = (
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )


class Location(Base, TimestampMixin):
    """场景/地点卡表（locations）。"""

    __tablename__ = "locations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True, comment="所属项目")
    code: Mapped[str] = mapped_column(String(50), nullable=False, comment="稳定编号 location_001")
    name: Mapped[str] = mapped_column(String(100), nullable=False, comment="地点名")
    description: Mapped[str | None] = mapped_column(Text, comment="环境描述固定词")
    time_of_day: Mapped[str | None] = mapped_column(String(20), comment="dawn/day/dusk/night")
    lighting: Mapped[str | None] = mapped_column(String(200), comment="光线固定词")
    scene_prompt: Mapped[str | None] = mapped_column(Text, comment="场景卡固定提示词片段")


class Character(Base, TimestampMixin):
    """角色卡表。"""

    __tablename__ = "characters"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True, comment="所属项目")
    code: Mapped[str] = mapped_column(String(50), nullable=False, comment="稳定编号 char_001")
    name: Mapped[str] = mapped_column(String(100), nullable=False, comment="角色名")
    age_range: Mapped[str | None] = mapped_column(String(20), comment="年龄段")
    gender_presentation: Mapped[str | None] = mapped_column(String(20), comment="性别呈现")
    hair: Mapped[str | None] = mapped_column(String(300), comment="发型发色固定词")
    face_features: Mapped[str | None] = mapped_column(String(300), comment="五官特征")
    body_shape: Mapped[str | None] = mapped_column(String(200), comment="体型")
    clothing: Mapped[str | None] = mapped_column(String(300), comment="服装固定词")
    color_palette: Mapped[list | None] = mapped_column(JSON, comment="主色板")
    style_tokens: Mapped[list | None] = mapped_column(JSON, comment="风格 token 列表")
    voice_id: Mapped[str | None] = mapped_column(String(100), comment="供应商音色 ID")
    voice_emotions: Mapped[list | None] = mapped_column(JSON, comment="可选情绪枚举")
    version: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"), comment="角色卡版本")
    confirmed: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"), comment="1=已锁定")


class CharacterAsset(Base, TimestampMixin):
    """角色参考图/素材关联表。"""

    __tablename__ = "character_assets"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    character_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True, comment="角色 ID")
    asset_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="generated_assets.id")
    asset_type: Mapped[str] = mapped_column(String(20), default="reference", server_default="reference", comment="reference/turnaround/expression")
    is_primary: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"), comment="主参考图")


class StylePreset(Base, TimestampMixin):
    """画风预设表。"""

    __tablename__ = "style_presets"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[int | None] = mapped_column(BigInteger, comment="NULL 表示全局预设")
    name: Mapped[str] = mapped_column(String(100), nullable=False, comment="画风名")
    style_prompt: Mapped[str | None] = mapped_column(Text, comment="画风固定正向词")
    negative_prompt: Mapped[str | None] = mapped_column(Text, comment="统一负面提示词")
    params: Mapped[dict | None] = mapped_column(JSON, comment="采样器/步数/比例等默认参数")


class Scene(Base, TimestampMixin):
    """剧本场景表（episodes 拆分，区别于 locations 场景卡）。"""

    __tablename__ = "scenes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    episode_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True, comment="所属剧集")
    scene_no: Mapped[int] = mapped_column(Integer, nullable=False, comment="场景序号")
    code: Mapped[str | None] = mapped_column(String(50), comment="稳定编号 scene_001")
    location_id: Mapped[int | None] = mapped_column(BigInteger, comment="关联 locations")
    time_of_day: Mapped[str | None] = mapped_column(String(20), comment="可覆盖场景卡默认值")
    purpose: Mapped[str | None] = mapped_column(String(300), comment="该场戏目的")
    summary: Mapped[str | None] = mapped_column(Text, comment="场景剧情摘要")


class Shot(Base, TimestampMixin):
    """分镜表。"""

    __tablename__ = "shots"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    episode_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True, comment="所属剧集")
    scene_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True, comment="所属场景")
    scene_no: Mapped[int] = mapped_column(Integer, nullable=False, comment="冗余排序")
    shot_no: Mapped[int] = mapped_column(Integer, nullable=False, comment="场内镜头序号")
    code: Mapped[str | None] = mapped_column(String(50), comment="稳定编号 shot_001")
    location_id: Mapped[int | None] = mapped_column(BigInteger, comment="场景/地点")
    character_ids: Mapped[list | None] = mapped_column(JSON, comment="出场角色 ID 列表")
    shot_type: Mapped[str | None] = mapped_column(String(20), comment="景别")
    camera_movement: Mapped[str | None] = mapped_column(String(20), comment="运镜")
    action_description: Mapped[str | None] = mapped_column(Text, comment="动作描述")
    dialogue: Mapped[list | None] = mapped_column(JSON, comment="[{character_id,text,emotion}]")
    visual_prompt: Mapped[dict | None] = mapped_column(JSON, comment="image_prompt/video_prompt/negative/continuity_notes")
    duration: Mapped[Decimal] = mapped_column(DECIMAL(5, 2), default=Decimal("5.00"), server_default=text("5.00"), comment="镜头时长(秒)")
    keyframe_asset_id: Mapped[int | None] = mapped_column(BigInteger, comment="关键帧素材")
    video_asset_id: Mapped[int | None] = mapped_column(BigInteger, comment="视频片段素材")
    status: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"), comment="0=待生成 1=部分就绪 2=就绪 3=已入成片")


class Prompt(Base, TimestampMixin):
    """提示词记录表（模板版本化）。"""

    __tablename__ = "prompts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[int | None] = mapped_column(BigInteger, index=True, comment="所属项目")
    template_key: Mapped[str | None] = mapped_column(String(100), comment="script/storyboard/image")
    template_version: Mapped[str | None] = mapped_column(String(20), comment="如 script.v1.1")
    system_prompt: Mapped[str | None] = mapped_column(Text, comment="系统提示词")
    user_prompt: Mapped[str | None] = mapped_column(Text, comment="渲染后的最终提示词")
    variables_json: Mapped[dict | None] = mapped_column(JSON, comment="变量快照")
    model: Mapped[str | None] = mapped_column(String(100), comment="模型名")
    provider: Mapped[str | None] = mapped_column(String(50), comment="供应商标识")
    temperature: Mapped[Decimal | None] = mapped_column(DECIMAL(3, 2), comment="温度")
    seed: Mapped[int | None] = mapped_column(BigInteger, comment="随机种子")
    input_asset_ids: Mapped[list | None] = mapped_column(JSON, comment="输入素材")
    output_asset_ids: Mapped[list | None] = mapped_column(JSON, comment="输出素材")
    task_id: Mapped[int | None] = mapped_column(BigInteger, index=True, comment="关联 generation_tasks")


class GenerationTask(Base, TimestampMixin):
    """AI 生成任务表（核心）。"""

    __tablename__ = "generation_tasks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    uuid: Mapped[str] = mapped_column(CHAR(36), nullable=False, unique=True, index=True, comment="对外任务 ID")
    project_id: Mapped[int | None] = mapped_column(BigInteger, index=True, comment="所属项目")
    episode_id: Mapped[int | None] = mapped_column(BigInteger, comment="关联剧集")
    shot_id: Mapped[int | None] = mapped_column(BigInteger, comment="关联分镜")
    type: Mapped[str] = mapped_column(String(20), nullable=False, comment="text/image/video/audio/asr/render")
    provider: Mapped[str | None] = mapped_column(String(50), comment="供应商标识")
    model: Mapped[str | None] = mapped_column(String(100), comment="模型名")
    mode: Mapped[str | None] = mapped_column(String(10), comment="mock/record/replay")
    status: Mapped[str] = mapped_column(String(20), default="queued", server_default="queued", index=True, comment="任务状态")
    progress: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"), comment="0~100")
    request_payload: Mapped[dict | None] = mapped_column(JSON, comment="请求快照（脱敏后）")
    response_payload: Mapped[dict | None] = mapped_column(JSON, comment="响应快照（脱敏后）")
    input_asset_ids: Mapped[list | None] = mapped_column(JSON, comment="输入素材")
    output_asset_ids: Mapped[list | None] = mapped_column(JSON, comment="输出素材")
    retry_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"), comment="重试次数")
    error_message: Mapped[str | None] = mapped_column(Text, comment="错误信息")
    cost: Mapped[Decimal] = mapped_column(DECIMAL(10, 4), default=Decimal("0"), server_default=text("0"), comment="费用(元)")
    idempotency_key: Mapped[str | None] = mapped_column(CHAR(64), index=True, comment="参数哈希")
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="开始时间")
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="结束时间")


class GeneratedAsset(Base, TimestampMixin):
    """生成素材表。"""

    __tablename__ = "generated_assets"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[int | None] = mapped_column(BigInteger, index=True, comment="所属项目")
    task_id: Mapped[int | None] = mapped_column(BigInteger, index=True, comment="来源任务")
    asset_type: Mapped[str] = mapped_column(String(20), nullable=False, comment="image/video/audio/subtitle")
    storage_kind: Mapped[str] = mapped_column(String(20), default="local", server_default="local", comment="local/minio")
    file_path: Mapped[str] = mapped_column(String(500), nullable=False, comment="相对 MEDIA_ROOT 路径")
    file_name: Mapped[str | None] = mapped_column(String(255), comment="展示名")
    mime_type: Mapped[str | None] = mapped_column(String(100), comment="MIME 类型")
    file_size: Mapped[int | None] = mapped_column(BigInteger, comment="字节")
    meta_json: Mapped[dict | None] = mapped_column(JSON, comment="分辨率/时长等元数据")
    checksum: Mapped[str | None] = mapped_column(CHAR(64), comment="SHA-256")


class AudioTrack(Base, TimestampMixin):
    """音频轨道表。"""

    __tablename__ = "audio_tracks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    shot_id: Mapped[int | None] = mapped_column(BigInteger, index=True, comment="分镜对白音频")
    episode_id: Mapped[int | None] = mapped_column(BigInteger, index=True, comment="旁白/BGM 挂到集")
    track_type: Mapped[str] = mapped_column(String(20), default="dialogue", server_default="dialogue", comment="dialogue/narration/bgm/sfx")
    character_id: Mapped[int | None] = mapped_column(BigInteger, comment="说话角色")
    text_raw: Mapped[str | None] = mapped_column(Text, comment="原文")
    text_normalized: Mapped[str | None] = mapped_column(Text, comment="规范化文本")
    asset_id: Mapped[int | None] = mapped_column(BigInteger, comment="音频素材")
    voice_id: Mapped[str | None] = mapped_column(String(100), comment="音色 ID")
    emotion: Mapped[str | None] = mapped_column(String(50), comment="情绪")
    speed: Mapped[Decimal] = mapped_column(DECIMAL(4, 2), default=Decimal("1.00"), server_default=text("1.00"), comment="语速")
    pitch: Mapped[Decimal] = mapped_column(DECIMAL(5, 2), default=Decimal("0"), server_default=text("0"), comment="音高")
    pause_after_ms: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"), comment="停顿(ms)")
    duration_ms: Mapped[int | None] = mapped_column(Integer, comment="实际时长(ms)")


class VideoClip(Base, TimestampMixin):
    """视频片段表。"""

    __tablename__ = "video_clips"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    shot_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True, comment="分镜")
    asset_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="视频素材")
    clip_type: Mapped[str | None] = mapped_column(String(20), comment="generated/uploaded")
    duration_ms: Mapped[int | None] = mapped_column(Integer, comment="时长(ms)")
    width: Mapped[int | None] = mapped_column(Integer, comment="宽")
    height: Mapped[int | None] = mapped_column(Integer, comment="高")
    fps: Mapped[Decimal | None] = mapped_column(DECIMAL(5, 2), comment="帧率")
    source: Mapped[str | None] = mapped_column(String(50), comment="provider 或 tool 标识")


class Subtitle(Base, TimestampMixin):
    """字幕表。"""

    __tablename__ = "subtitles"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    episode_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True, comment="所属剧集")
    shot_id: Mapped[int | None] = mapped_column(BigInteger, comment="关联分镜")
    audio_track_id: Mapped[int | None] = mapped_column(BigInteger, comment="关联音频轨")
    character_id: Mapped[int | None] = mapped_column(BigInteger, comment="说话人")
    text: Mapped[str] = mapped_column(String(500), nullable=False, comment="字幕文本")
    start_ms: Mapped[int] = mapped_column(Integer, nullable=False, comment="开始(ms)")
    end_ms: Mapped[int] = mapped_column(Integer, nullable=False, comment="结束(ms)")
    format: Mapped[str | None] = mapped_column(String(10), comment="srt/ass/json")
    file_asset_id: Mapped[int | None] = mapped_column(BigInteger, comment="整份字幕文件素材")
    source: Mapped[str | None] = mapped_column(String(20), comment="whisper/asr_api/manual/upload")


class RenderJob(Base, TimestampMixin):
    """成片渲染任务表。"""

    __tablename__ = "render_jobs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    uuid: Mapped[str] = mapped_column(CHAR(36), nullable=False, unique=True, index=True, comment="对外 ID")
    episode_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True, comment="剧集")
    task_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="generation_tasks(type=render)")
    plan_json: Mapped[dict | None] = mapped_column(JSON, comment="合成计划")
    status: Mapped[str] = mapped_column(String(20), default="queued", server_default="queued", comment="同任务状态机")
    output_asset_id: Mapped[int | None] = mapped_column(BigInteger, comment="成片素材")
    subtitle_burn_in: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"), comment="是否烧录字幕")
    error_message: Mapped[str | None] = mapped_column(Text, comment="错误信息")


class ProviderConfig(Base, TimestampMixin):
    """Provider 配置表（api_key_ref 只存环境变量名，不存明文密钥）。"""

    __tablename__ = "provider_configs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    capability: Mapped[str] = mapped_column(String(20), nullable=False, comment="text/image/video/audio/asr")
    provider: Mapped[str] = mapped_column(String(50), nullable=False, comment="供应商标识")
    mode: Mapped[str] = mapped_column(String(10), default="mock", server_default="mock", comment="mock/record/replay")
    model: Mapped[str | None] = mapped_column(String(100), comment="默认模型")
    base_url: Mapped[str | None] = mapped_column(String(255), comment="API 基址")
    api_key_ref: Mapped[str | None] = mapped_column(String(100), comment="环境变量名")
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=60, server_default=text("60"), comment="超时(秒)")
    max_retries: Mapped[int] = mapped_column(Integer, default=2, server_default=text("2"), comment="重试上限")
    daily_quota: Mapped[int | None] = mapped_column(Integer, comment="每日调用上限")
    enabled: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"), comment="启用开关")
