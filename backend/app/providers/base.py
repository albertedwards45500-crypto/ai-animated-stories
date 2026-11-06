# -*- coding: utf-8 -*-
"""Provider 适配层基类协议。

所有 AI 能力（text/image/video/audio/asr）通过统一协议接入，
业务代码不依赖任何一家供应商。
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ProviderResult:
    """Provider 执行结果。

    Attributes:
        ok: 是否成功。
        output: 成功时的输出数据（如素材描述、文本内容）。
        error_message: 失败时的错误信息。
        error_kind: 失败类型（failed/timeout），用于状态机落库。
        cost: 本次调用费用（元），Mock 为 0。
        model: 实际使用的模型名。
        elapsed_ms: 耗时（毫秒）。
    """

    ok: bool
    output: dict[str, Any] = field(default_factory=dict)
    error_message: str | None = None
    error_kind: str = "failed"
    cost: float = 0.0
    model: str = ""
    elapsed_ms: int = 0


class ProgressCallback(Protocol):
    """进度回调协议：worker 每步调用以持久化进度并检查取消。"""

    def __call__(self, progress: int, stage: str = "") -> None:
        """上报进度。

        Args:
            progress: 0~100 进度值。
            stage: 阶段描述文案。
        """
        ...


class GenerationProvider(Protocol):
    """AI 能力 Provider 统一协议。

    实现类：MockTextProvider / MockImageProvider / MockVideoProvider /
    MockAudioProvider / DeepSeekTextProvider / MiniMaxAudioProvider 等。
    """

    name: str

    def execute(
        self,
        request: dict[str, Any],
        on_progress: ProgressCallback | None = None,
    ) -> ProviderResult:
        """同步执行一次生成。

        Args:
            request: 请求载荷（已脱敏）。
            on_progress: 进度回调，可为 None。

        Returns:
            ProviderResult: 执行结果，不抛出业务异常（失败通过返回值表达）。
        """
        ...


def new_uuid() -> str:
    """生成对外暴露的 UUID 字符串。

    Returns:
        str: 36 位 UUID。
    """
    return str(uuid.uuid4())


def now_ms() -> int:
    """当前毫秒时间戳。

    Returns:
        int: epoch 毫秒。
    """
    return int(time.time() * 1000)
