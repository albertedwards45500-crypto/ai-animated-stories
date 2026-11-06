# -*- coding: utf-8 -*-
"""成片渲染服务：FFmpeg 合成（拼接 + 混音 + 字幕），输出真实可播放 MP4。

合成前校验（PRD 4.2.6）：每个分镜均有视频素材、音频时长 ≤ 片段时长
（或明确静音）、字幕时间不超出总时长且无不合理重叠。
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.enums import AudioTrackType, ShotStatus
from app.core.response import BizError, CODE_BIZ_INVALID
from app.models.entities import (
    AudioTrack,
    Episode,
    GeneratedAsset,
    RenderJob,
    Scene,
    Shot,
    Subtitle,
)
from app.services.asset_service import probe_duration_ms, media_dir
from app.services.subtitle_service import SubtitleLine, build_srt, validate_subtitles

# 统一输出参数
TARGET_W, TARGET_H, TARGET_FPS = 1280, 720, 30


def _run_ffmpeg(args: list[str], cwd: Path | None = None) -> None:
    """执行 FFmpeg 命令，失败抛出业务错误。

    Args:
        args: 完整命令参数列表（不含可执行文件名）。
        cwd: 工作目录，默认 None。

    Raises:
        BizError: FFmpeg 执行失败（40002），stderr 摘要附在错误中。
    """
    exe = get_settings().ffmpeg_executable
    try:
        proc = subprocess.run(
            [exe, "-hide_banner", "-loglevel", "error", "-y", *args],
            capture_output=True, text=True, timeout=600, cwd=str(cwd) if cwd else None,
        )
    except subprocess.TimeoutExpired as exc:
        raise BizError(CODE_BIZ_INVALID, "FFmpeg 合成超时") from exc
    if proc.returncode != 0:
        tail = (proc.stderr or "")[-500:]
        raise BizError(CODE_BIZ_INVALID, f"FFmpeg 合成失败: {tail}")


def _ordered_shots(db: Session, episode_id: int) -> list[Shot]:
    """按播放顺序获取分镜。

    Args:
        db: 数据库会话。
        episode_id: 剧集 ID。

    Returns:
        list[Shot]: 排序后的分镜列表。
    """
    return (
        db.query(Shot)
        .filter(Shot.episode_id == episode_id)
        .order_by(Shot.scene_no, Shot.shot_no)
        .all()
    )


def validate_episode_for_render(db: Session, episode_id: int) -> dict:
    """合成前校验：素材、音频时长、字幕时间轴。

    Args:
        db: 数据库会话。
        episode_id: 剧集 ID。

    Returns:
        dict: 校验上下文（分镜素材映射、总时长）。

    Raises:
        BizError: 校验失败（40002），data.errors 为问题清单。
    """
    shots = _ordered_shots(db, episode_id)
    if not shots:
        raise BizError(CODE_BIZ_INVALID, "合成失败：该剧集没有分镜", {"errors": ["无分镜"]})
    errors: list[str] = []
    total_ms = 0
    plan: list[dict] = []
    for shot in shots:
        seg_ms = int(float(shot.duration) * 1000)
        total_ms += seg_ms
        if not shot.video_asset_id:
            errors.append(f"{shot.code or f'shot_{shot.id}'} 缺少视频素材")
            plan.append({"shot_id": shot.id, "duration_ms": seg_ms, "video": None})
            continue
        video = db.get(GeneratedAsset, shot.video_asset_id)
        if video is None:
            errors.append(f"{shot.code or f'shot_{shot.id}'} 视频素材记录缺失")
            continue
        vpath = get_settings().media_root_path / video.file_path
        if not vpath.exists():
            errors.append(f"{shot.code or f'shot_{shot.id}'} 视频文件缺失")
        # 音频时长校验：对白音频时长超出片段时长按超长标记（混音时截断为明确行为）
        tracks = db.query(AudioTrack).filter(AudioTrack.shot_id == shot.id, AudioTrack.track_type == AudioTrackType.DIALOGUE.value).all()
        for t in tracks:
            if t.asset_id:
                a = db.get(GeneratedAsset, t.asset_id)
                if a is None:
                    errors.append(f"{shot.code or f'shot_{shot.id}'} 对白音频素材缺失")
                    continue
                dur = probe_duration_ms(get_settings().media_root_path / a.file_path)
                if dur is not None and dur > seg_ms + 500:
                    errors.append(
                        f"{shot.code or f'shot_{shot.id}'} 音频时长({dur}ms)超出片段时长({seg_ms}ms)，将按片段时长截断"
                    )
        plan.append({"shot_id": shot.id, "duration_ms": seg_ms, "video": str(vpath)})

    # 字幕校验
    subs = db.query(Subtitle).filter(Subtitle.episode_id == episode_id).order_by(Subtitle.start_ms).all()
    sub_lines = [SubtitleLine(start_ms=s.start_ms, end_ms=s.end_ms, text=s.text, character_id=s.character_id) for s in subs]
    issues = validate_subtitles(sub_lines, total_ms)
    errors.extend(issues)

    if errors:
        raise BizError(CODE_BIZ_INVALID, "合成前校验失败", {"errors": errors})
    return {"plan": plan, "total_ms": total_ms, "subtitle_lines": sub_lines}


def render_episode(
    db: Session,
    job: RenderJob,
    context: dict,
    on_progress=None,
) -> Path:
    """执行 FFmpeg 合成，输出可播放 MP4。

    流程：片段归一化 → concat 拼接 → 混音 → 字幕烧录/封装 → 输出。

    Args:
        db: 数据库会话。
        job: 渲染任务行。
        context: validate_episode_for_render 返回的校验上下文。
        on_progress: 进度回调（接收 0~100 进度）。

    Returns:
        Path: 成片文件路径。

    Raises:
        BizError: 各阶段 FFmpeg 失败（40002）。
    """
    plan = context["plan"]
    with tempfile.TemporaryDirectory(prefix="render_") as tmp:
        tmp_dir = Path(tmp)
        # 1) 片段归一化
        norm_files: list[Path] = []
        n = len(plan)
        for i, seg in enumerate(plan):
            if on_progress is not None:
                on_progress(int(10 + 30 * i / max(n, 1)), "normalize")
            src = seg["video"]
            out = tmp_dir / f"seg_{i:03d}.mp4"
            _run_ffmpeg([
                "-i", src,
                "-vf", f"scale={TARGET_W}:{TARGET_H}:force_original_aspect_ratio=decrease,pad={TARGET_W}:{TARGET_H}:(ow-iw)/2:(oh-ih)/2,setsar=1,tpad=stop_mode=clone:stop_duration={seg['duration_ms'] / 1000:.3f}",
                "-r", str(TARGET_FPS),
                "-t", f"{seg['duration_ms'] / 1000:.3f}",
                "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
                "-an", str(out),
            ])
            norm_files.append(out)

        # 2) concat 拼接
        if on_progress is not None:
            on_progress(45, "concat")
        concat_list = tmp_dir / "concat.txt"
        concat_list.write_text("".join(f"file '{f.as_posix()}'\n" for f in norm_files), encoding="utf-8")
        base = tmp_dir / "base.mp4"
        _run_ffmpeg(["-f", "concat", "-safe", "0", "-i", str(concat_list), "-c", "copy", str(base)])

        # 3) 混音：逐片段 pad/trim 到片段时长后 concat 为整轨
        if on_progress is not None:
            on_progress(60, "mix audio")
        has_audio = any(
            db.query(AudioTrack).filter(AudioTrack.shot_id == seg["shot_id"]).first() is not None
            for seg in plan
        )
        output = media_dir("generated") / f"render_{job.uuid}.mp4"
        if has_audio:
            seg_audios: list[Path] = []
            for i, seg in enumerate(plan):
                tracks = db.query(AudioTrack).filter(AudioTrack.shot_id == seg["shot_id"]).all()
                inputs: list[str] = []
                filter_parts: list[str] = []
                mix_labels: list[str] = []
                for t in tracks:
                    if not t.asset_id:
                        continue
                    a = db.get(GeneratedAsset, t.asset_id)
                    if a is None:
                        continue
                    apath = get_settings().media_root_path / a.file_path
                    if not apath.exists():
                        continue
                    j = len(inputs)
                    inputs.append(str(apath))
                    # 统一采样率与声道（供应商音频可能为 24kHz 单声道），
                    # 截断到片段时长并 pad 补齐
                    filter_parts.append(
                        f"[{j}:a]aresample=44100,aformat=sample_rates=44100:channel_layouts=stereo,"
                        f"atrim=0:{seg['duration_ms'] / 1000:.3f},"
                        f"apad=whole_dur={seg['duration_ms'] / 1000:.3f}[a{j}]"
                    )
                    mix_labels.append(f"[a{j}]")
                out_a = tmp_dir / f"aud_{i:03d}.wav"
                if mix_labels:
                    fc = ";".join(filter_parts) + f";{''.join(mix_labels)}amix=inputs={len(mix_labels)}:normalize=0[out]"
                    args2: list[str] = []
                    for p in inputs:
                        args2 += ["-i", p]
                    _run_ffmpeg([
                        *args2,
                        "-filter_complex", fc,
                        "-map", "[out]", str(out_a),
                    ])
                else:
                    # 无有效音频片段：静音轨
                    _run_ffmpeg([
                        "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
                        "-t", f"{seg['duration_ms'] / 1000:.3f}", str(out_a),
                    ])
                seg_audios.append(out_a)
            aud_list = tmp_dir / "aud.txt"
            aud_list.write_text("".join(f"file '{f.as_posix()}'\n" for f in seg_audios), encoding="utf-8")
            full_audio = tmp_dir / "audio.wav"
            # 重编码而非 -c copy：各片段来源不一（mono/stereo、采样率差异），
            # copy 遇参数不一致会静默截断输出
            _run_ffmpeg(["-f", "concat", "-safe", "0", "-i", str(aud_list),
                         "-c:a", "pcm_s16le", str(full_audio)])
        else:
            full_audio = None

        # 4) 字幕
        if on_progress is not None:
            on_progress(80, "subtitles")
        sub_lines: list[SubtitleLine] = context.get("subtitle_lines") or []
        srt_path: Path | None = None
        if sub_lines:
            srt_path = media_dir("generated") / f"render_{job.uuid}.srt"
            srt_path.write_text(build_srt(sub_lines), encoding="utf-8")

        # 5) 封装输出
        if on_progress is not None:
            on_progress(90, "mux")
        args = ["-i", str(base)]
        if full_audio is not None:
            args += ["-i", str(full_audio)]
        if srt_path is not None and not job.subtitle_burn_in:
            args += ["-i", str(srt_path)]
        args += ["-map", "0:v:0"]
        if full_audio is not None:
            args += ["-map", "1:a:0"]
        args += ["-c:v", "copy", "-c:a", "aac", "-b:a", "192k"]
        if srt_path is not None and job.subtitle_burn_in:
            rel = srt_path.relative_to(get_settings().media_root_path).as_posix()
            args += [
                "-vf", f"subtitles={rel}:force_style='FontSize=42,Outline=2,Alignment=2'",
                "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
            ]
        elif srt_path is not None:
            subtitle_index = 2 if full_audio is not None else 1
            args += ["-map", f"{subtitle_index}:s:0", "-c:s", "mov_text", "-metadata:s:s:0", "language=chi"]
        args += ["-t", f"{context['total_ms'] / 1000:.3f}", "-movflags", "+faststart", str(output)]
        _run_ffmpeg(args, cwd=get_settings().media_root_path)

    return output


def mark_shots_rendered(db: Session, episode_id: int) -> None:
    """合成成功后将分镜标记为已入成片。

    Args:
        db: 数据库会话（调用方提交）。
        episode_id: 剧集 ID。
    """
    for shot in _ordered_shots(db, episode_id):
        shot.status = ShotStatus.IN_RENDER.value
