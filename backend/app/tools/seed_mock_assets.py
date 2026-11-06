# -*- coding: utf-8 -*-
"""Mock 测试素材初始化脚本。

用 FFmpeg 生成《本地开发环境.md》§4 要求的素材：
    media/mock/images/   ≥3 张测试图
    media/mock/audio/    ≥2 个对白音频（WAV，便于 python 读取时长）
    media/mock/video/    1 个 5 秒视频片段
    media/mock/subtitles/ 1 个 SRT 字幕样例

运行（backend 目录）：
    python -m app.tools.seed_mock_assets
"""
from __future__ import annotations

import subprocess

from app.core.config import get_settings
from app.services.asset_service import media_dir


def _ffmpeg(args: list[str]) -> None:
    """执行 FFmpeg 命令。

    Args:
        args: 参数列表。

    Raises:
        SystemExit: FFmpeg 失败时终止脚本。
    """
    exe = get_settings().ffmpeg_executable
    proc = subprocess.run([exe, "-hide_banner", "-loglevel", "error", "-y", *args], capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit(f"FFmpeg 失败: {proc.stderr[-500:]}")


def seed() -> None:
    """生成全部 Mock 测试素材。"""
    images = media_dir("mock", "images")
    audio = media_dir("mock", "audio")
    video = media_dir("mock", "video")
    subs = media_dir("mock", "subtitles")

    # 3 张测试图（测试卡 + 纯色，768x1344 竖版）
    patterns = ["testsrc2", "smptebars", "rgbtestsrc"]
    for i, pat in enumerate(patterns):
        _ffmpeg([
            "-f", "lavfi", "-i", f"{pat}=size=768x1344:rate=1",
            "-frames:v", "1", str(images / f"mock_img_{i + 1}.png"),
        ])

    # 2 个对白音频（不同音高的正弦波，时长约 1.5s / 2.5s）
    for i, freq in enumerate([440, 660]):
        _ffmpeg([
            "-f", "lavfi", "-i", f"sine=frequency={freq}:duration={1.5 + i}",
            "-c:a", "pcm_s16le", "-ar", "44100", "-ac", "1",
            str(audio / f"mock_voice_{i + 1}.wav"),
        ])

    # 1 个 5 秒视频（测试卡 + 正弦音）
    _ffmpeg([
        "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30:duration=5",
        "-f", "lavfi", "-i", "sine=frequency=330:duration=5",
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest", str(video / "mock_clip_5s.mp4"),
    ])

    # 1 个 SRT 字幕样例
    (subs / "mock_sample.srt").write_text(
        "1\n00:00:00,000 --> 00:00:02,000\n第一集：雨夜来电\n\n"
        "2\n00:00:02,000 --> 00:00:04,500\n你终于来了。\n",
        encoding="utf-8",
    )
    print("Mock 素材初始化完成：media/mock/{images,audio,video,subtitles}")


if __name__ == "__main__":
    seed()
