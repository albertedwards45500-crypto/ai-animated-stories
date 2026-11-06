# -*- coding: utf-8 -*-
"""真实 Provider 实现（阶段三）。

- DeepSeekTextProvider：DeepSeek OpenAI 兼容 chat/completions。
- MiniMaxAudioProvider：MiniMax T2A 语音合成。

均为真实 HTTP 调用实现；API Key 只从环境变量读取（不写日志、不返回浏览器）。
record 模式由 task_service 负责落库留档，replay 模式由参数哈希缓存直接复用。
"""
from __future__ import annotations

import json
import time
from typing import Any

import httpx

from app.core.config import get_settings
from app.providers.base import ProviderResult

DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-chat"

MINIMAX_BASE_URL = "https://api.minimax.chat"
MINIMAX_MODEL = "speech-01"


class _HttpProviderBase:
    """HTTP Provider 公共基类：统一超时与错误转换。

    Attributes:
        name: 供应商标识。
        base_url: API 基址。
    """

    name = ""
    base_url = ""

    def _post_json(self, url: str, headers: dict, payload: dict, timeout_s: int) -> tuple[bool, dict, str]:
        """发送 JSON POST 请求并归一化错误。

        Args:
            url: 完整 URL。
            headers: 请求头。
            payload: JSON 请求体。
            timeout_s: 超时秒数。

        Returns:
            tuple[bool, dict, str]: (是否成功, 响应JSON, 错误信息)。
        """
        try:
            with httpx.Client(timeout=timeout_s) as client:
                resp = client.post(url, headers=headers, json=payload)
            if resp.status_code >= 500:
                return False, {}, f"upstream error: HTTP {resp.status_code}"
            if resp.status_code >= 400:
                return False, {}, f"upstream rejected: HTTP {resp.status_code} {resp.text[:200]}"
            return True, resp.json(), ""
        except httpx.TimeoutException:
            return False, {}, "upstream timeout"
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            return False, {}, f"upstream error: {exc}"


class DeepSeekTextProvider(_HttpProviderBase):
    """DeepSeek 文本 Provider：结构化剧本生成。"""

    name = "deepseek"
    base_url = DEEPSEEK_BASE_URL

    def execute(self, request: dict[str, Any], on_progress=None) -> ProviderResult:
        """调用 DeepSeek 生成结构化剧本。

        Args:
            request: 含 system_prompt/user_prompt/temperature 的请求载荷。
            on_progress: 进度回调（HTTP 单次调用，开始时上报 50）。

        Returns:
            ProviderResult: 成功时 output.script 为解析后的 JSON。
        """
        settings = get_settings()
        if not settings.deepseek_api_key:
            return ProviderResult(ok=False, error_message="DEEPSEEK_API_KEY 未配置（请写入 .env）")
        if on_progress is not None:
            on_progress(50, "calling deepseek")
        start = time.time()
        ok, data, err = self._post_json(
            f"{self.base_url}/chat/completions",
            {"Authorization": f"Bearer {settings.deepseek_api_key}"},
            {
                "model": request.get("model") or DEEPSEEK_MODEL,
                "messages": [
                    {"role": "system", "content": request.get("system_prompt", "")},
                    {"role": "user", "content": request.get("user_prompt", "")},
                ],
                "temperature": float(request.get("temperature", 0.7)),
                "response_format": {"type": "json_object"},
            },
            int(request.get("timeout_seconds", 60)),
        )
        result = ProviderResult(ok=True, model=request.get("model") or DEEPSEEK_MODEL, elapsed_ms=int((time.time() - start) * 1000))
        if not ok:
            result.error_message = err
            result.error_kind = "timeout" if "timeout" in err else "failed"
            return result
        try:
            content = data["choices"][0]["message"]["content"]
            result.output = {"script": json.loads(content)}
        except (KeyError, IndexError, json.JSONDecodeError) as exc:
            result.ok = False
            result.error_message = f"invalid upstream response: {exc}"
            return result
        result.ok = True
        return result


class MiniMaxAudioProvider(_HttpProviderBase):
    """MiniMax 语音 Provider：T2A 对白语音合成。"""

    name = "minimax"
    base_url = MINIMAX_BASE_URL

    def execute(self, request: dict[str, Any], on_progress=None) -> ProviderResult:
        """调用 MiniMax 合成语音。

        Args:
            request: 含 text/voice_id/emotion 的请求载荷。
            on_progress: 进度回调。

        Returns:
            ProviderResult: 成功时 output.audio_hex（base64 音频）与 audio_format。
        """
        settings = get_settings()
        if not settings.minimax_api_key:
            return ProviderResult(ok=False, error_message="MINIMAX_API_KEY 未配置（请写入 .env）")
        if on_progress is not None:
            on_progress(50, "calling minimax")
        start = time.time()
        ok, data, err = self._post_json(
            f"{self.base_url}/v1/t2a_v2",
            {"Authorization": f"Bearer {settings.minimax_api_key}"},
            {
                "model": request.get("model") or MINIMAX_MODEL,
                "text": request.get("text", ""),
                "voice_setting": {
                    "voice_id": request.get("voice_id", "male-qn-qingse"),
                    "speed": float(request.get("speed", 1.0)),
                    "emotion": request.get("emotion") or "neutral",
                },
                "audio_setting": {"format": "mp3"},
            },
            int(request.get("timeout_seconds", 60)),
        )
        result = ProviderResult(ok=True, model=request.get("model") or MINIMAX_MODEL, elapsed_ms=int((time.time() - start) * 1000))
        if not ok:
            result.error_message = err
            result.error_kind = "timeout" if "timeout" in err else "failed"
            return result
        audio = (data.get("data") or {}).get("audio")
        if not audio:
            result.ok = False
            result.error_message = "invalid upstream response: missing audio"
            return result
        result.ok = True
        result.output = {"audio_hex": audio, "audio_format": "mp3"}
        return result
