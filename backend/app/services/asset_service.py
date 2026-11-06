# -*- coding: utf-8 -*-
"""素材服务：generated_assets 登记、文件复制、媒体元数据探测。"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.entities import GeneratedAsset


def media_dir(*parts: str) -> Path:
    """构造媒体目录路径并确保存在。

    Args:
        parts: 相对 MEDIA_ROOT 的路径片段。

    Returns:
        Path: 绝对目录路径（自动创建）。
    """
    p = get_settings().media_root_path.joinpath(*parts)
    p.mkdir(parents=True, exist_ok=True)
    return p


def sha256_file(path: Path) -> str:
    """计算文件 SHA-256 校验和。

    Args:
        path: 文件路径。

    Returns:
        str: 64 位十六进制哈希。
    """
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def probe_duration_ms(path: Path) -> int | None:
    """用 ffprobe 探测媒体时长（毫秒）。

    Args:
        path: 音视频文件路径。

    Returns:
        int | None: 时长毫秒，探测失败返回 None。
    """
    import subprocess

    ffprobe = get_settings().ffmpeg_executable.replace("ffmpeg", "ffprobe")
    try:
        out = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "json", str(path)],
            capture_output=True, text=True, timeout=30, check=True,
        )
        data = json.loads(out.stdout)
        return int(float(data["format"]["duration"]) * 1000)
    except (subprocess.SubprocessError, KeyError, ValueError, json.JSONDecodeError, FileNotFoundError):
        return None


def register_asset(
    db: Session,
    *,
    project_id: int | None,
    task_id: int | None,
    asset_type: str,
    src_file: Path,
    subdir: str = "generated",
    file_name: str | None = None,
    meta: dict | None = None,
) -> GeneratedAsset:
    """将文件登记为 generated_assets（复制到 generated 目录并落库）。

    Args:
        db: 数据库会话（调用方提交）。
        project_id: 所属项目。
        task_id: 来源任务。
        asset_type: image/video/audio/subtitle。
        src_file: 源文件路径。
        subdir: 目标子目录，默认 generated。
        file_name: 展示名，缺省用源文件名。
        meta: 附加元数据（分辨率/时长等）。

    Returns:
        GeneratedAsset: 已落库的素材行。
    """
    dest_dir = media_dir(subdir)
    dest = dest_dir / f"{task_id or 'manual'}_{src_file.name}"
    if src_file != dest:
        shutil.copy2(src_file, dest)
    asset = GeneratedAsset(
        project_id=project_id,
        task_id=task_id,
        asset_type=asset_type,
        storage_kind="local",
        file_path=str(dest.relative_to(get_settings().media_root_path)).replace("\\", "/"),
        file_name=file_name or src_file.name,
        mime_type=MIME_MAP.get(src_file.suffix.lower(), "application/octet-stream"),
        file_size=dest.stat().st_size,
        meta_json=meta or {},
        checksum=sha256_file(dest),
    )
    db.add(asset)
    db.flush()
    return asset


MIME_MAP = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".mp4": "video/mp4",
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".srt": "application/x-subrip",
    ".ass": "text/x-ssa",
}


def probe_video_size(path: Path) -> tuple[int | None, int | None, float | None]:
    """用 ffprobe 探测视频宽高与帧率。

    Args:
        path: 视频文件路径。

    Returns:
        tuple: (width, height, fps)，探测失败返回 (None, None, None)。
    """
    import subprocess

    ffprobe = get_settings().ffmpeg_executable.replace("ffmpeg", "ffprobe")
    try:
        out = subprocess.run(
            [ffprobe, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height,avg_frame_rate",
             "-of", "json", str(path)],
            capture_output=True, text=True, timeout=30, check=True,
        )
        stream = json.loads(out.stdout)["streams"][0]
        num, _, den = stream.get("avg_frame_rate", "0/1").partition("/")
        fps = float(num) / float(den or 1)
        return int(stream["width"]), int(stream["height"]), round(fps, 2)
    except (subprocess.SubprocessError, KeyError, IndexError, ValueError, ZeroDivisionError, json.JSONDecodeError, FileNotFoundError):
        return None, None, None


def safe_filename(name: str) -> str:
    """清洗文件名（防路径穿越）。

    Args:
        name: 原始文件名。

    Returns:
        str: 仅保留字母数字下划线连字符点的安全文件名。

    Raises:
        ValueError: 清洗后为空。
    """
    cleaned = re.sub(r"[^A-Za-z0-9_.\-\u4e00-\u9fff]", "_", name)
    if not cleaned or cleaned.startswith("."):
        raise ValueError("非法文件名")
    return cleaned
