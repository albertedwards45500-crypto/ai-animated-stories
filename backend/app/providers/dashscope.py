# -*- coding: utf-8 -*-
"""阿里云百炼（DashScope）Provider 实现：图片 / 视频 / 语音。

接口协议（DashScope v1，异步任务提交 + 轮询）：
- 图片：POST /api/v1/services/aigc/text2image/image-synthesis（X-DashScope-Async: enable）
- 视频：POST /api/v1/services/aigc/video-generation/video-synthesis（X-DashScope-Async: enable）
- 语音：POST /api/v1/services/audio/tts（同步返回音频二进制）

API Key 只从环境变量读取（.env），不写日志、不返回浏览器。
成功输出统一通过 output["local_file"] 返回已下载的本地文件路径，
由 task_runner 登记为 generated_assets。
"""
from __future__ import annotations

import base64
import mimetypes
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

from app.core.config import get_settings
from app.providers.base import ProviderResult

DASHSCOPE_BASE = "https://dashscope.aliyuncs.com/api/v1"
# 异步任务轮询间隔（秒）与最长等待
POLL_INTERVAL_S = 2.0


def _auth_headers(api_key: str) -> dict:
    """构造 DashScope 认证头。

    Args:
        api_key: API Key（来自环境变量）。

    Returns:
        dict: Authorization 请求头。
    """
    return {"Authorization": f"Bearer {api_key}"}


def _poll_task(api_key: str, task_id: str, timeout_s: int) -> tuple[bool, dict | None, str, bool]:
    """轮询 DashScope 异步任务直到终态。

    Args:
        api_key: API Key。
        task_id: 异步任务 ID。
        timeout_s: 超时秒数。

    Returns:
        tuple: (是否成功, 任务数据, 错误信息, 是否超时)。
    """
    deadline = time.time() + timeout_s
    with httpx.Client(timeout=30) as client:
        while time.time() < deadline:
            resp = client.get(f"{DASHSCOPE_BASE}/tasks/{task_id}", headers=_auth_headers(api_key))
            if resp.status_code != 200:
                return False, None, f"task query failed: HTTP {resp.status_code}", False
            data = resp.json().get("output", {})
            status = data.get("task_status")
            if status == "SUCCEEDED":
                return True, data, "", False
            if status in ("FAILED", "CANCELED", "UNKNOWN"):
                return False, data, f"dashscope task {status}: {data.get('message', '')}", False
            time.sleep(POLL_INTERVAL_S)
    return False, None, "dashscope task polling timeout", True


def _download(url: str, dest: Path) -> bool:
    """下载生成结果文件到本地。

    Args:
        url: 结果文件 URL。
        dest: 目标路径。

    Returns:
        bool: 是否成功。
    """
    try:
        with httpx.Client(timeout=120, follow_redirects=True) as client:
            resp = client.get(url)
        if resp.status_code != 200 or not resp.content:
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(resp.content)
        return True
    except httpx.HTTPError:
        return False


class DashScopeImageProvider:
    """百炼图片 Provider（qwen-image-3.0，multimodal-generation 同步接口）。

    实测确认：qwen-image 系列走 /services/aigc/multimodal-generation/generation
    同步生成（约 30~120s），响应 output.choices[0].message.content[].image 为图片 URL。
    """

    name = "dashscope"

    def execute(self, request: dict[str, Any], on_progress=None) -> ProviderResult:
        """同步调用文生图并下载结果。

        Args:
            request: 含 prompt/params（size/seed）的请求载荷。
            on_progress: 进度回调。

        Returns:
            ProviderResult: 成功时 output.local_file 为下载的图片路径。
        """
        settings = get_settings()
        api_key = settings.dashscope_api_key_image
        if not api_key:
            return ProviderResult(ok=False, error_message="DASHSCOPE_API_KEY_IMAGE 未配置（请写入 .env）")
        model = request.get("model") or settings.image_model
        prompt = request.get("prompt") or ""
        if not prompt:
            return ProviderResult(ok=False, error_message="图片生成缺少 prompt", model=model)
        params = request.get("params") or {}
        references = request.get("reference_images") or []
        if len(references) > 3:
            return ProviderResult(ok=False, error_message="qwen-image-3.0 最多接受 3 张参考图", model=model)
        content = []
        for reference in references:
            path = Path(reference)
            if not path.is_file() or path.stat().st_size > 10 * 1024 * 1024:
                return ProviderResult(ok=False, error_message="角色参考图不存在或超过 10 MB", model=model)
            mime = mimetypes.guess_type(path.name)[0]
            if mime not in ("image/png", "image/jpeg", "image/webp", "image/gif", "image/bmp", "image/tiff"):
                return ProviderResult(ok=False, error_message="角色参考图格式不受支持", model=model)
            content.append({"image": f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"})
        content.append({"text": prompt})
        start = time.time()
        if on_progress is not None:
            on_progress(30, "generating")
        try:
            with httpx.Client(timeout=int(request.get("timeout_seconds", 300))) as client:
                resp = client.post(
                    f"{DASHSCOPE_BASE}/services/aigc/multimodal-generation/generation",
                    headers={**_auth_headers(api_key), "Content-Type": "application/json"},
                    json={
                        "model": model,
                        "input": {"messages": [{"role": "user", "content": content}]},
                        **({"parameters": {"size": params["size"], **({"seed": int(params["seed"])} if params.get("seed") is not None else {})}}
                            if params.get("size") else {}),
                    },
                )
        except httpx.TimeoutException:
            return ProviderResult(ok=False, error_message="dashscope image timeout", error_kind="timeout", model=model)
        except httpx.HTTPError as exc:
            return ProviderResult(ok=False, error_message=f"dashscope image error: {exc}", model=model)
        if resp.status_code != 200:
            return ProviderResult(ok=False, error_message=f"dashscope rejected: HTTP {resp.status_code} {resp.text[:200]}", model=model)
        try:
            content = resp.json()["output"]["choices"][0]["message"]["content"]
            url = next(c["image"] for c in content if "image" in c)
        except (KeyError, IndexError, StopIteration, ValueError) as exc:
            return ProviderResult(ok=False, error_message=f"dashscope image parse error: {exc}", model=model)
        dest = get_settings().media_root_path / "tmp" / f"dashscope_img_{uuid.uuid4().hex}.png"
        if not _download(url, dest):
            return ProviderResult(ok=False, error_message="result download failed", model=model)
        if on_progress is not None:
            on_progress(95, "downloading")
        return ProviderResult(ok=True, model=model, elapsed_ms=int((time.time() - start) * 1000),
                              output={"local_file": str(dest), "remote_url": url})


class DashScopeVideoProvider:
    """百炼视频 Provider（wan3.0-video，图生视频，异步任务）。"""

    name = "dashscope"

    def execute(self, request: dict[str, Any], on_progress=None) -> ProviderResult:
        """提交图生视频任务并下载结果。

        Args:
            request: 含 img_url（关键帧 URL，可本地文件路径）/prompt/duration 的载荷。
            on_progress: 进度回调。

        Returns:
            ProviderResult: 成功时 output.local_file 为下载的视频路径。
        """
        settings = get_settings()
        api_key = settings.dashscope_api_key_video
        if not api_key:
            return ProviderResult(ok=False, error_message="DASHSCOPE_API_KEY_VIDEO 未配置（请写入 .env）")
        model = request.get("model") or settings.video_model
        img_url = request.get("img_url")
        if not img_url:
            return ProviderResult(ok=False, error_message="图生视频缺少 img_url（请先生成或上传关键帧）", model=model)
        # 本地文件 → Base64 data URL（百炼支持，免去公网 OSS 依赖，实测 wan3.0-video 接受）
        img_path = Path(img_url) if not img_url.startswith(("data:", "http://", "https://")) else None
        if img_path is not None and not img_path.is_file():
            return ProviderResult(ok=False, error_message="关键帧图片文件不存在", model=model)
        if img_path is not None:
            if img_path.stat().st_size > 20 * 1024 * 1024:
                return ProviderResult(ok=False, error_message="关键帧图片超过 20 MB", model=model)
            mime = mimetypes.guess_type(img_path.name)[0]
            if mime not in ("image/png", "image/jpeg", "image/bmp", "image/webp"):
                return ProviderResult(ok=False, error_message="关键帧图片格式不受万相3.0支持", model=model)
            b64 = base64.b64encode(img_path.read_bytes()).decode()
            img_url = f"data:{mime};base64,{b64}"
        duration = int(request.get("duration") or 5)
        if duration < 2 or duration > 30:
            return ProviderResult(ok=False, error_message="万相3.0视频时长需在 2 到 30 秒之间", model=model)
        start = time.time()
        if on_progress is not None:
            on_progress(10, "submitting")
        try:
            with httpx.Client(timeout=60) as client:
                resp = client.post(
                    f"{DASHSCOPE_BASE}/services/aigc/video-generation/video-synthesis",
                    headers={**_auth_headers(api_key), "X-DashScope-Async": "enable", "Content-Type": "application/json"},
                    json={
                        "model": model,
                        "input": {"prompt": request.get("prompt") or "",
                                  "media": [{"type": "first_frame", "url": img_url}]},
                        "parameters": {"duration": duration,
                                       "ratio": "adaptive", "prompt_extend": False},
                    },
                )
        except httpx.TimeoutException:
            return ProviderResult(ok=False, error_message="dashscope submit timeout", error_kind="timeout", model=model)
        except httpx.HTTPError as exc:
            return ProviderResult(ok=False, error_message=f"dashscope submit error: {exc}", model=model)
        if resp.status_code != 200:
            return ProviderResult(ok=False, error_message=f"dashscope rejected: HTTP {resp.status_code} {resp.text[:200]}", model=model)
        task_id = resp.json().get("output", {}).get("task_id")
        if not task_id:
            return ProviderResult(ok=False, error_message="dashscope: missing task_id", model=model)
        if on_progress is not None:
            on_progress(30, "generating")
        ok, data, err, timeout = _poll_task(api_key, task_id, int(request.get("timeout_seconds", 600)))
        if not ok:
            return ProviderResult(ok=False, error_message=err, error_kind="timeout" if timeout else "failed",
                                  model=model, elapsed_ms=int((time.time() - start) * 1000))
        url = (data or {}).get("video_url")
        if not url:
            return ProviderResult(ok=False, error_message="dashscope: missing video_url", model=model)
        dest = get_settings().media_root_path / "tmp" / f"dashscope_video_{task_id}.mp4"
        if not _download(url, dest):
            return ProviderResult(ok=False, error_message="result download failed", model=model)
        return ProviderResult(ok=True, model=model, elapsed_ms=int((time.time() - start) * 1000),
                              output={"local_file": str(dest), "remote_url": url, "task_id": task_id})


class DashScopeAudioProvider:
    """百炼语音 Provider（cosyvoice-v3.5-plus，SpeechSynthesizer 同步接口）。

    实测确认请求格式：POST /api/v1/services/audio/tts/SpeechSynthesizer，
    body 为 {"model", "input": {"text", "voice", "format", "sample_rate"}}。
    引擎返回 418 表示音色不可用或该 Key 未开通语音合成服务。
    """

    name = "dashscope"

    def execute(self, request: dict[str, Any], on_progress=None) -> ProviderResult:
        """调用 CosyVoice 合成语音并保存 WAV。

        Args:
            request: 含 text/voice_id/emotion/speed 的载荷。
            on_progress: 进度回调。

        Returns:
            ProviderResult: 成功时 output.local_file 为音频文件路径。
        """
        settings = get_settings()
        api_key = settings.dashscope_api_key_audio
        if not api_key:
            return ProviderResult(ok=False, error_message="DASHSCOPE_API_KEY_AUDIO 未配置（请写入 .env）")
        model = request.get("model") or settings.audio_model
        text = request.get("text") or ""
        if not text:
            return ProviderResult(ok=False, error_message="语音合成缺少文本", model=model)
        start = time.time()
        if on_progress is not None:
            on_progress(40, "synthesizing")
        try:
            with httpx.Client(timeout=int(request.get("timeout_seconds", 120))) as client:
                resp = client.post(
                    f"{DASHSCOPE_BASE}/services/audio/tts/SpeechSynthesizer",
                    headers={**_auth_headers(api_key), "Content-Type": "application/json"},
                    json={
                        "model": model,
                        "input": {
                            "text": text,
                            # v3 系列系统音色；v3.5-plus 需使用其兼容音色或复刻/设计音色（角色卡 voice_id）
                            "voice": request.get("voice_id") or "longanyang",
                            "format": "wav",
                            "sample_rate": 24000,
                            **({"rate": float(request["speed"])} if request.get("speed") else {}),
                        },
                    },
                )
        except httpx.TimeoutException:
            return ProviderResult(ok=False, error_message="dashscope tts timeout", error_kind="timeout", model=model)
        except httpx.HTTPError as exc:
            return ProviderResult(ok=False, error_message=f"dashscope tts error: {exc}", model=model)
        if resp.status_code != 200:
            return ProviderResult(ok=False, error_message=f"dashscope rejected: HTTP {resp.status_code} {resp.text[:200]}", model=model)
        content_type = resp.headers.get("content-type", "")
        dest = get_settings().media_root_path / "tmp" / f"dashscope_tts_{int(time.time())}.wav"
        dest.parent.mkdir(parents=True, exist_ok=True)
        if "audio" in content_type:
            dest.write_bytes(resp.content)
        else:
            try:
                data = resp.json()
                audio_obj = (data.get("output") or {}).get("audio") or {}
                # 实测：cosyvoice-v3 系列返回 output.audio.url（OSS 结果链接）
                audio_url = audio_obj.get("url") if isinstance(audio_obj, dict) else None
                audio_b64 = audio_obj.get("data") if isinstance(audio_obj, dict) else None
                if not audio_url and not audio_b64:
                    return ProviderResult(ok=False, error_message=f"dashscope tts failed: {str(data)[:200]}", model=model)
                if audio_url:
                    if not _download(audio_url, dest):
                        return ProviderResult(ok=False, error_message="tts result download failed", model=model)
                else:
                    dest.write_bytes(base64.b64decode(audio_b64))
            except Exception as exc:  # noqa: BLE001 - 供应商响应形态不可控
                return ProviderResult(ok=False, error_message=f"dashscope tts parse error: {exc}", model=model)
        return ProviderResult(ok=True, model=model, elapsed_ms=int((time.time() - start) * 1000),
                              output={"local_file": str(dest)})


def _ensure_tmp_dir() -> Path:
    """确保临时目录存在。

    Returns:
        Path: media/tmp 目录。
    """
    p = get_settings().media_root_path / "tmp"
    p.mkdir(parents=True, exist_ok=True)
    return p
