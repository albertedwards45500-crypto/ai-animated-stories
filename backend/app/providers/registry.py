# -*- coding: utf-8 -*-
"""Provider 注册表：按能力与供应商标识获取 Provider 实例。

支持 mock 与真实供应商；record/replay 模式由 task_service 层处理
（record=调用后留档，replay=参数哈希命中直接复用）。
"""
from __future__ import annotations

import hashlib
from typing import Any

from app.core.config import get_settings
from app.core.enums import ProviderMode, TaskType
from app.models.entities import ProviderConfig
from app.providers.base import GenerationProvider
from app.providers.mock import (
    MockAsrProvider,
    MockAudioProvider,
    MockImageProvider,
    MockTextProvider,
    MockVideoProvider,
)
from app.providers.dashscope import (
    DashScopeAudioProvider,
    DashScopeImageProvider,
    DashScopeVideoProvider,
)
from app.providers.real import DeepSeekTextProvider, MiniMaxAudioProvider

# 能力 → mock/真实 provider 实例表
_MOCK_PROVIDERS: dict[str, Any] = {
    TaskType.TEXT: MockTextProvider,
    TaskType.IMAGE: MockImageProvider,
    TaskType.VIDEO: MockVideoProvider,
    TaskType.AUDIO: MockAudioProvider,
    TaskType.ASR: MockAsrProvider,
}

_REAL_PROVIDERS: dict[tuple[str, str], Any] = {
    (TaskType.TEXT, "deepseek"): DeepSeekTextProvider,
    (TaskType.AUDIO, "minimax"): MiniMaxAudioProvider,
    (TaskType.IMAGE, "dashscope"): DashScopeImageProvider,
    (TaskType.VIDEO, "dashscope"): DashScopeVideoProvider,
    (TaskType.AUDIO, "dashscope"): DashScopeAudioProvider,
}


def resolve_provider_config(db, capability: str) -> ProviderConfig | None:
    """查询某能力的启用配置。

    Args:
        db: SQLAlchemy 会话。
        capability: 能力标识（text/image/video/audio/asr）。

    Returns:
        ProviderConfig | None: 启用中的配置，未配置返回 None。
    """
    return (
        db.query(ProviderConfig)
        .filter(ProviderConfig.capability == capability, ProviderConfig.enabled == 1)
        .first()
    )


def get_provider(capability: str, provider_name: str | None, mode: str | None) -> tuple[GenerationProvider | None, str, str]:
    """解析最终使用的 Provider 实例。

    解析顺序：请求显式指定 provider > provider_configs 表 > 环境变量默认值。

    Args:
        capability: 能力标识。
        provider_name: 请求指定的供应商标识。
        mode: 请求指定的模式，缺省取配置或环境变量。

    Returns:
        tuple: (Provider 实例, 实际 provider 名, 实际 mode)。
    """
    settings = get_settings()
    final_mode = mode or getattr(settings, "ai_mode", "mock")
    final_provider = provider_name or getattr(settings, f"{capability}_provider", "mock")

    if final_mode == ProviderMode.MOCK.value or final_provider == "mock":
        cls = _MOCK_PROVIDERS.get(capability)
        return (cls() if cls else None), "mock", ProviderMode.MOCK.value

    real_cls = _REAL_PROVIDERS.get((capability, final_provider))
    if real_cls is None:
        # 真实 provider 未注册：回退为显式失败，避免静默用 Mock 冒充真实调用
        return None, final_provider, final_mode
    return real_cls(), final_provider, final_mode


def pick_image_file(directory, index_key: str):
    """从目录按确定性顺序选取一个文件（Mock 素材轮转）。

    Args:
        directory: 素材目录 Path。
        index_key: 确定性索引来源字符串（如 shot uuid）。

    Returns:
        Path | None: 选中的文件路径，目录为空返回 None。
    """
    if not directory.exists():
        return None
    files = sorted(
        f for f in directory.iterdir() if f.is_file() and f.suffix.lower() in (".png", ".jpg", ".jpeg", ".mp4", ".wav", ".mp3", ".srt")
    )
    if not files:
        return None
    idx = int(hashlib.sha256(index_key.encode("utf-8")).hexdigest(), 16) % len(files)
    return files[idx]
