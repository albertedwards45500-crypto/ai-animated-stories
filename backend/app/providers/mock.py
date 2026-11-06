# -*- coding: utf-8 -*-
"""Mock Provider 实现（四类能力）。

必须模拟排队、处理中、成功、失败、超时、取消和重试，不能永远成功
（PRD 5.3 / 开发文档 §7.3）。模拟策略：

- request_payload.params.mock_scenario 显式指定 success/fail/timeout；
- 未指定时按参数确定性哈希伪随机：约 10% failed、5% timeout、85% succeeded；
- 处理过程分 5 步推进 progress，每步通过 on_progress 落库并检查取消；
- timeout 场景睡眠超过 provider 超时阈值，由 worker 判定 timeout。
"""
from __future__ import annotations

import hashlib
import time
from typing import Any

from app.core.config import get_settings
from app.providers.base import ProviderResult

# 单步处理间隔（秒），保证 Mock 任务 ≤5 秒完成
STEP_INTERVAL = 0.2
TOTAL_STEPS = 5


def resolve_scenario(request: dict[str, Any]) -> str:
    """解析本次 Mock 任务的模拟场景。

    Args:
        request: 请求载荷。

    Returns:
        str: success / fail / timeout 之一。
    """
    params = (request.get("params") or {}) if isinstance(request.get("params"), dict) else {}
    explicit = params.get("mock_scenario") or get_settings().mock_default_scenario
    if explicit in ("success", "fail", "timeout"):
        if int(request.get("_retry_count") or 0) > 0 and explicit in ("fail", "timeout"):
            return "success"
        return str(explicit)
    # 确定性伪随机：基于请求内容的哈希，同参数同结果，保证重试行为可复现
    payload = repr(sorted(request.items(), key=lambda kv: kv[0])).encode("utf-8")
    digest = int(hashlib.sha256(payload).hexdigest(), 16)
    bucket = digest % 100
    if bucket < 10:
        return "fail"
    if bucket < 15:
        return "timeout"
    return "success"


def simulate_processing(
    request: dict[str, Any],
    on_progress=None,
    scenario: str | None = None,
    timeout_threshold_s: float = 8.0,
) -> ProviderResult:
    """通用 Mock 处理流程：分步推进进度并模拟终态。

    Args:
        request: 请求载荷。
        on_progress: 进度回调（worker 注入，用于落库与取消检查）。
        scenario: 显式场景，缺省按 resolve_scenario 推断。
        timeout_threshold_s: timeout 判定阈值（秒）。

    Returns:
        ProviderResult: 处理结果。
    """
    settings = get_settings()
    sc = scenario or resolve_scenario(request)
    start = time.time()

    for step in range(1, TOTAL_STEPS + 1):
        time.sleep(STEP_INTERVAL)
        if on_progress is not None:
            # 回调抛出 TaskCancelled 由 worker 转换为 cancelled 终态
            on_progress(int(step * 100 / TOTAL_STEPS))

    elapsed = time.time() - start
    base = ProviderResult(ok=True, model="mock-1", elapsed_ms=int(elapsed * 1000))
    if sc == "fail":
        base.ok = False
        base.error_message = "mock provider simulated failure"
        base.error_kind = "failed"
        return base
    if sc == "timeout" or elapsed > timeout_threshold_s:
        # 模拟上游超时：sleep 已超过阈值，标记 timeout
        base.ok = False
        base.error_message = "mock provider simulated timeout"
        base.error_kind = "timeout"
        return base
    base.ok = True
    return base


class MockTextProvider:
    """Mock 文本 Provider：生成符合剧本 Schema 的结构化 JSON。"""

    name = "mock"

    def execute(self, request: dict[str, Any], on_progress=None) -> ProviderResult:
        """执行文本生成。

        Args:
            request: 含 episode/project 上下文的请求载荷。
            on_progress: 进度回调。

        Returns:
            ProviderResult: 成功时 output.script 为结构化剧本 dict。
        """
        result = simulate_processing(request, on_progress)
        if not result.ok:
            return result
        outline = (request.get("story_outline") or "")[:50]
        shot_duration = max(1, min(float(request.get("target_duration") or 60) / 3, 60))
        result.output = {
            "script": {
                "episode_title": request.get("episode_title") or "第一集",
                "logline": outline,
                "characters": [
                    {"code": "char_001", "name": "小林", "appearance": "黑色短发，浅色外套"},
                    {"code": "char_002", "name": "阿晴", "appearance": "棕色长发，蓝色衬衫"},
                ],
                "scenes": [{
                    "scene_id": "scene_001", "location_id": "旧书店", "time_of_day": "傍晚",
                    "purpose": "发现线索、产生分歧并决定出发",
                    "shots": [
                        {"shot_id": "shot_001", "duration_seconds": shot_duration, "characters": ["char_001"],
                         "action": "小林翻开旧书，发现一张手绘地图。",
                         "dialogue": [{"character_id": "char_001", "text": "你看，这里藏着一张地图。"}]},
                        {"shot_id": "shot_002", "duration_seconds": shot_duration, "characters": ["char_002"],
                         "action": "阿晴靠近桌面，指向地图上的红色标记。",
                         "dialogue": [{"character_id": "char_002", "text": "这个地方，我好像见过。"}]},
                        {"shot_id": "shot_003", "duration_seconds": shot_duration, "characters": ["char_001", "char_002"],
                         "action": "两人收起地图，推开书店的门，走向暮色。",
                         "dialogue": [{"character_id": "char_001", "text": "走吧，一起去找答案。"}]},
                    ],
                }],
            }
        }
        return result


class MockImageProvider:
    """Mock 图片 Provider：从 media/mock/images 轮转选取测试图作为关键帧。"""

    name = "mock"

    def execute(self, request: dict[str, Any], on_progress=None) -> ProviderResult:
        """执行图片生成。

        Args:
            request: 含 shot_id/prompt 的请求载荷。
            on_progress: 进度回调。

        Returns:
            ProviderResult: 成功时 output.file_name 指向 mock 图。
        """
        result = simulate_processing(request, on_progress)
        if not result.ok:
            return result
        result.output = {"kind": "image", "source_dir": "mock/images"}
        return result


class MockVideoProvider:
    """Mock 视频 Provider：从 media/mock/video 选取 5 秒测试片段。"""

    name = "mock"

    def execute(self, request: dict[str, Any], on_progress=None) -> ProviderResult:
        """执行视频生成。

        Args:
            request: 含 shot_id/duration 的请求载荷。
            on_progress: 进度回调。

        Returns:
            ProviderResult: 成功时 output 标记视频片段来源。
        """
        result = simulate_processing(request, on_progress)
        if not result.ok:
            return result
        result.output = {"kind": "video", "source_dir": "mock/video"}
        return result


class MockAudioProvider:
    """Mock 音频 Provider：从 media/mock/audio 选取测试音频。"""

    name = "mock"

    def execute(self, request: dict[str, Any], on_progress=None) -> ProviderResult:
        """执行语音生成。

        Args:
            request: 含 text/voice_id 的请求载荷。
            on_progress: 进度回调。

        Returns:
            ProviderResult: 成功时 output 标记音频来源。
        """
        result = simulate_processing(request, on_progress)
        if not result.ok:
            return result
        result.output = {"kind": "audio", "source_dir": "mock/audio"}
        return result


class MockAsrProvider:
    """Mock ASR Provider：基于对白文本生成字幕行（不依赖真实识别）。"""

    name = "mock"

    def execute(self, request: dict[str, Any], on_progress=None) -> ProviderResult:
        """执行字幕识别。

        Args:
            request: 含 audio_tracks（文本与时长）的请求载荷。
            on_progress: 进度回调。

        Returns:
            ProviderResult: 成功时 output.subtitles 为字幕行列表。
        """
        result = simulate_processing(request, on_progress)
        if not result.ok:
            return result
        result.output = {"kind": "subtitle", "source": "mock"}
        return result
