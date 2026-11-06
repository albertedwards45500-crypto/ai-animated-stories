# -*- coding: utf-8 -*-
"""枚举常量定义。

固化《数据库设计.md》与《API接口文档.md》中的状态与类型枚举，
不新增文档之外的取值（见 DECISIONS D-07）。
"""
from enum import Enum


class ProjectStatus(int, Enum):
    """项目状态：1=active 0=archived。"""

    ARCHIVED = 0
    ACTIVE = 1


class EpisodeStatus(int, Enum):
    """剧集状态：0=草稿 1=剧本已生成 2=素材就绪 3=已合成。"""

    DRAFT = 0
    SCRIPT_GENERATED = 1
    ASSETS_READY = 2
    RENDERED = 3


class ShotStatus(int, Enum):
    """分镜状态：0=待生成 1=素材部分就绪 2=素材就绪 3=已入成片。"""

    PENDING = 0
    PARTIAL_READY = 1
    ASSETS_READY = 2
    IN_RENDER = 3


class TaskStatus(str, Enum):
    """生成任务状态机。

    queued → processing → succeeded | failed | timeout | cancelled
    """

    QUEUED = "queued"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"

    @classmethod
    def terminal(cls) -> set["TaskStatus"]:
        """返回全部终态集合。

        Returns:
            set[TaskStatus]: succeeded/failed/timeout/cancelled。
        """
        return {cls.SUCCEEDED, cls.FAILED, cls.TIMEOUT, cls.CANCELLED}

    @classmethod
    def running(cls) -> set["TaskStatus"]:
        """返回全部进行中状态集合。

        Returns:
            set[TaskStatus]: queued/processing。
        """
        return {cls.QUEUED, cls.PROCESSING}


class TaskType(str, Enum):
    """生成任务类型。"""

    TEXT = "text"
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    ASR = "asr"
    RENDER = "render"


class ProviderMode(str, Enum):
    """Provider 运行模式：mock/record/replay。"""

    MOCK = "mock"
    RECORD = "record"
    REPLAY = "replay"


class AssetType(str, Enum):
    """素材类型。"""

    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    SUBTITLE = "subtitle"


class AudioTrackType(str, Enum):
    """音频轨道类型：dialogue/narration/bgm/sfx。"""

    DIALOGUE = "dialogue"
    NARRATION = "narration"
    BGM = "bgm"
    SFX = "sfx"


class ShotTypeEnum(str, Enum):
    """分镜景别枚举。"""

    LONG = "远景"
    FULL = "全景"
    MEDIUM = "中景"
    CLOSE = "近景"
    EXTREME_CLOSE = "特写"


class CameraMovementEnum(str, Enum):
    """运镜枚举。"""

    FIXED = "固定"
    PUSH = "推"
    PULL = "拉"
    PAN = "摇"
    TRACK = "移"


# SHOT_TYPE / CAMERA_MOVEMENT 合法取值列表（用于校验）
SHOT_TYPES = [e.value for e in ShotTypeEnum]
CAMERA_MOVEMENTS = [e.value for e in CameraMovementEnum]

# 时段枚举
TIME_OF_DAY = ["dawn", "day", "dusk", "night"]

# 字幕格式
SUBTITLE_FORMATS = ["srt", "ass", "json"]

# 字幕来源
SUBTITLE_SOURCES = ["whisper", "asr_api", "manual", "upload"]
