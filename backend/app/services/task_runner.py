# -*- coding: utf-8 -*-
"""任务执行器：按任务类型分派 Provider 执行并落库产物。

被 Dramatiq worker（app.tasks.worker）调用；也可在测试中同步执行。
"""
from __future__ import annotations

from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.enums import AssetType, EpisodeStatus, ProviderMode, ShotStatus, TaskStatus, TaskType
from app.models.entities import (
    AudioTrack,
    Character,
    CharacterAsset,
    Episode,
    GenerationTask,
    GeneratedAsset,
    Location,
    Prompt,
    RenderJob,
    Shot,
    Subtitle,
)
from app.providers.base import GenerationProvider, ProviderResult
from app.providers.registry import get_provider, pick_image_file
from app.services import asset_service, render_service, subtitle_service, task_service
from app.services.script_service import apply_script_to_episode, validate_script
from app.services.character_consistency import character_prompt, image_style, validate_character_refs
from app.services.task_service import TaskCancelledError

# 剧本生成提示词模板（版本化依据开发文档 10.4.2）
SCRIPT_TEMPLATE_VERSION = "script.v1.0"
_executor: ThreadPoolExecutor | None = None
_executor_lock = Lock()
SCRIPT_SYSTEM_PROMPT = (
    "你是专业的中文短剧编剧和分镜策划。你的任务是把用户提供的故事梗概改写成可执行的 AI 漫剧剧本。\n"
    "创作要求：\n"
    "- 情节必须有明确的目标、冲突、转折和结尾。\n"
    "- 每集只保留必要动作，适合 30～90 秒短视频。\n"
    "- 角色行为必须符合角色设定。\n"
    "- 对白口语化，每句对白标明说话角色。\n"
    "- 所有场景、角色和镜头必须使用稳定编号。\n"
    "输出 JSON 必须严格包含以下结构：episode_title 字符串、logline 字符串、characters 数组、scenes 数组。\n"
    "characters 每项包含 code、name、appearance、voice_id 字符串。\n"
    "scenes 每项包含 scene_id、location_id、time_of_day、purpose 字符串和 shots 数组。\n"
    "shots 每项包含 shot_id 字符串、duration_seconds 数字、characters 字符串数组、action 字符串、dialogue 数组、sound_cue 字符串。\n"
    "dialogue 每项使用 {\"character\":\"角色code\",\"text\":\"对白\"}。所有必需字段都要提供，无对白时 dialogue 返回空数组。"
    "所有字段名必须使用上述英文名，严禁增加 Markdown 代码围栏。只返回 JSON，不要解释。"
)


def _progress_cb(db: Session, task: GenerationTask):
    """构造进度回调：落库进度并检查取消。

    Args:
        db: 数据库会话。
        task: 任务行。

    Returns:
        callable: on_progress(progress:int, stage:str)。
    """

    def cb(progress: int, stage: str = "") -> None:
        """上报进度。

        Args:
            progress: 0~100。
            stage: 阶段描述。
        """
        task_service.mark_progress(db, task, progress)

    return cb


def _record_prompt(db: Session, task: GenerationTask, template_key: str, user_prompt: str, provider_result: ProviderResult) -> None:
    """记录本次生成的提示词快照（prompts 表）。

    Args:
        db: 数据库会话。
        task: 任务行。
        template_key: 模板标识。
        user_prompt: 渲染后的提示词。
        provider_result: 执行结果（含 model）。
    """
    db.add(Prompt(
        project_id=task.project_id,
        template_key=template_key,
        template_version=f"{template_key}.v1.0",
        system_prompt=SCRIPT_SYSTEM_PROMPT if template_key == "script" else None,
        user_prompt=user_prompt[:100000],
        variables_json=task.request_payload or {},
        model=provider_result.model or task.model,
        provider=task.provider,
        task_id=task.id,
    ))


def _run_script(db: Session, task: GenerationTask, provider: GenerationProvider) -> dict:
    """执行剧本生成：Provider 输出 → Schema 校验 → 自动建档落库。

    Args:
        db: 数据库会话。
        task: 任务行。
        provider: Provider 实例。

    Returns:
        dict: 响应快照。

    Raises:
        BizError: Schema 校验失败（40002）。
    """
    req = task.request_payload or {}
    episode = db.get(Episode, task.episode_id) if task.episode_id else None
    user_prompt = f"故事梗概：{req.get('story_outline', '')}\n目标时长：{req.get('target_duration', 60)} 秒"
    provider_request = {
        **req,
        "system_prompt": SCRIPT_SYSTEM_PROMPT,
        "user_prompt": user_prompt,
    }
    result = provider.execute(provider_request, _progress_cb(db, task))
    _record_prompt(db, task, "script", user_prompt, result)
    if not result.ok:
        return {"ok": False, "error_message": result.error_message, "error_kind": result.error_kind}
    script = validate_script(result.output.get("script"))
    if episode is not None:
        apply_script_to_episode(db, episode, script)
        db.commit()
    return {"ok": True, "script": script}


def _mock_asset_file(kind: str, index_key: str) -> Path:
    """从 mock 素材目录确定性选取文件。

    Args:
        kind: images/video/audio。
        index_key: 索引键。

    Returns:
        Path: 素材文件。

    Raises:
        FileNotFoundError: Mock 素材缺失。
    """
    directory = get_settings().media_root_path / "mock" / kind
    f = pick_image_file(directory, index_key)
    if f is None:
        raise FileNotFoundError(f"Mock 素材缺失: media/mock/{kind}（请运行 seed_mock_assets 初始化）")
    return f


def _build_image_prompt(db: Session, shot: Shot | None) -> str:
    """按「画风+角色卡+场景卡+动作+景别+质量」拼装图片提示词（开发文档 10.4.4）。

    Args:
        db: 数据库会话。
        shot: 目标分镜。

    Returns:
        str: 拼装后的提示词。
    """
    parts: list[str] = []
    if shot is None:
        return "高质量插画"
    episode = db.get(Episode, shot.episode_id)
    if episode is not None:
        style_prompt, negative_prompt = image_style(db, episode.project_id)
        if style_prompt:
            parts.append(style_prompt)
    for cid in (shot.character_ids or []):
        ch = db.get(Character, int(cid))
        if ch is not None:
            parts.append(", ".join(x for x in [ch.name, ch.hair, ch.face_features, ch.clothing] if x))
    if shot.location_id:
        loc = db.get(Location, shot.location_id)
        if loc is not None:
            parts.append(", ".join(x for x in [loc.name, loc.description, loc.lighting] if x))
    if shot.action_description:
        parts.append(shot.action_description)
    if shot.shot_type:
        parts.append(shot.shot_type)
    parts.append("高质量，细节丰富，动漫风格")
    if episode is not None and negative_prompt:
        parts.append(f"避免：{negative_prompt}")
    return "，".join(p for p in parts if p)


def _reference_files(db: Session, refs: list[dict]) -> list[str]:
    """把角色快照中的主参考图解析为本地文件。"""
    paths = []
    for ref in refs:
        asset = db.get(GeneratedAsset, ref["primary_asset_id"])
        if asset is None:
            raise FileNotFoundError("角色主参考图已丢失")
        path = get_settings().media_root_path / asset.file_path
        if not path.is_file():
            raise FileNotFoundError(f"角色主参考图文件已丢失: {asset.id}")
        paths.append(str(path))
    return paths


def _frame_prompt(shot: Shot | None) -> str:
    """只包含镜头运动；静态人物由首帧与角色卡约束。"""
    return "。".join(filter(None, [
        shot.action_description if shot else None,
        f"镜头{shot.camera_movement}" if shot and shot.camera_movement and shot.camera_movement != "固定" else None,
        "主体自然运动，表情与动作连贯，保持角色脸部、发型、服装与场景布局不变，不新增人物，无文字和水印",
    ]))


def _register_provider_file(db: Session, task: GenerationTask, local_file: str | None, asset_type: str, fallback_key: str, index_key: str) -> tuple[Any, bool]:
    """登记 Provider 产物：真实 provider 用下载文件，Mock 用本地素材轮转。

    Args:
        db: 数据库会话。
        task: 任务行。
        local_file: Provider 输出的本地文件路径（Mock 场景为 None）。
        asset_type: 素材类型。
        fallback_key: Mock 素材目录名（images/video/audio）。
        index_key: Mock 轮转索引键。

    Returns:
        tuple: (素材行, 是否成功)。失败时第一个元素为错误 dict。
    """
    if local_file:
        src = Path(local_file)
        if not src.exists():
            return {"ok": False, "error_message": "provider 输出文件缺失", "error_kind": "failed"}, False
    else:
        try:
            src = _mock_asset_file(fallback_key, index_key)
        except FileNotFoundError as exc:
            return {"ok": False, "error_message": str(exc), "error_kind": "failed"}, False
    asset = asset_service.register_asset(
        db, project_id=task.project_id, task_id=task.id,
        asset_type=asset_type, src_file=src,
        meta={"provider": task.provider, "mode": task.mode},
    )
    return asset, True


def _run_image(db: Session, task: GenerationTask, provider: GenerationProvider) -> dict:
    """执行关键帧生成：真实 provider 拼装提示词，Mock 轮转测试图。

    Args:
        db: 数据库会话。
        task: 任务行。
        provider: Provider 实例。

    Returns:
        dict: 响应快照。
    """
    req = dict(task.request_payload or {})
    if req.get("character_id"):
        character = db.get(Character, req["character_id"])
        if character is None or character.confirmed or character.version != req.get("character_version"):
            return {"ok": False, "error_kind": "failed", "error_message": "角色卡已变化或锁定，请重新生成"}
        req["prompt"] = character_prompt(db, character)
        result = provider.execute(req, _progress_cb(db, task))
        if not result.ok:
            return {"ok": False, "error_message": result.error_message, "error_kind": result.error_kind}
        character = db.get(Character, req["character_id"])
        db.refresh(character)
        if character.confirmed or character.version != req["character_version"]:
            return {"ok": False, "error_kind": "failed", "error_message": "生成期间角色卡已变化或锁定，请重新生成"}
        asset_or_err, ok = _register_provider_file(
            db, task, result.output.get("local_file"), AssetType.IMAGE.value,
            "images", f"character-{character.id}-v{character.version}",
        )
        if not ok:
            return asset_or_err
        asset = asset_or_err
        asset.meta_json = {**(asset.meta_json or {}), "character_id": character.id,
                           "character_version": character.version, "kind": "character_reference"}
        has_primary = db.query(CharacterAsset).filter(
            CharacterAsset.character_id == character.id, CharacterAsset.is_primary == 1,
        ).first() is not None
        db.add(CharacterAsset(character_id=character.id, asset_id=asset.id,
                              asset_type="reference", is_primary=0 if has_primary else 1))
        db.commit()
        task.output_asset_ids = [asset.id]
        return {"ok": True, "asset_id": asset.id, "character_id": character.id,
                "character_version": character.version, "file_path": asset.file_path}
    shot = db.get(Shot, task.shot_id) if task.shot_id else None
    refs = req.get("character_refs") or []
    if provider.name != "mock":
        validate_character_refs(db, refs)
    if provider.name != "mock" and shot is not None and [int(x) for x in (shot.character_ids or [])] != [r["id"] for r in refs]:
        return {"ok": False, "error_kind": "failed", "error_message": "分镜角色已变化，请重新生成关键帧"}
    if provider.name != "mock" and shot is not None and req.get("prompt") != _build_image_prompt(db, shot):
        return {"ok": False, "error_kind": "failed", "error_message": "分镜设定已变化，请重新提交关键帧任务"}
    if refs and provider.name != "mock":
        req["reference_images"] = _reference_files(db, refs)
        req["prompt"] = "。".join([
            req.get("prompt") or _build_image_prompt(db, shot),
            "；".join(f"图{index}是角色「{ref['name']}」的唯一外观依据，保持其脸部、发型和服装" for index, ref in enumerate(refs, 1)),
            "根据参考图绘制本分镜，不要交换人物身份，不要新增人物",
        ])
    # 真实 provider 需要 prompt：按固定词拼装
    if provider.name != "mock" and not req.get("prompt"):
        req["prompt"] = _build_image_prompt(db, shot)
    result = provider.execute(req, _progress_cb(db, task))
    if not result.ok:
        return {"ok": False, "error_message": result.error_message, "error_kind": result.error_kind}
    asset_or_err, ok = _register_provider_file(db, task, result.output.get("local_file"), AssetType.IMAGE.value, "images", f"shot-{task.shot_id}-{'-'.join(r['code'] for r in refs)}")
    if not ok:
        return asset_or_err
    asset = asset_or_err
    asset.meta_json = {**(asset.meta_json or {}), "character_refs": refs, "shot_id": task.shot_id}
    if shot is not None and provider.name != "mock":
        db.refresh(shot)
        validate_character_refs(db, refs)
        if ([int(x) for x in (shot.character_ids or [])] != [r["id"] for r in refs]
                or (task.request_payload or {}).get("prompt") != _build_image_prompt(db, shot)):
            return {"ok": False, "error_kind": "failed", "error_message": "分镜角色已变化，请重新生成关键帧"}
    if shot is not None:
        shot.keyframe_asset_id = asset.id
        shot.status = ShotStatus.PARTIAL_READY.value if not shot.video_asset_id else ShotStatus.ASSETS_READY.value
        db.commit()
    task.output_asset_ids = [asset.id]
    return {"ok": True, "asset_id": asset.id, "file_path": asset.file_path}


def _run_video(db: Session, task: GenerationTask, provider: GenerationProvider) -> dict:
    """执行视频片段生成：图生视频需要关键帧公网 URL 或 Mock 片段。

    Args:
        db: 数据库会话。
        task: 任务行。
        provider: Provider 实例。

    Returns:
        dict: 响应快照。
    """
    req = dict(task.request_payload or {})
    shot = db.get(Shot, task.shot_id) if task.shot_id else None
    refs = req.get("character_refs") or []
    if provider.name != "mock":
        validate_character_refs(db, refs)
    if provider.name != "mock" and shot is not None and [int(x) for x in (shot.character_ids or [])] != [r["id"] for r in refs]:
        return {"ok": False, "error_kind": "failed", "error_message": "分镜角色已变化，请重新生成视频"}
    if provider.name != "mock" and (shot is None or not shot.keyframe_asset_id):
        return {"ok": False, "error_kind": "failed", "error_message": "请先用已锁定角色生成关键帧，再生成视频"}
    if shot is not None and provider.name != "mock":
        keyframe = db.get(GeneratedAsset, shot.keyframe_asset_id)
        if keyframe is None or (keyframe.meta_json or {}).get("character_refs") != refs:
            return {"ok": False, "error_kind": "failed", "error_message": "关键帧使用的角色版本与当前角色卡不一致，请重新生成关键帧"}
        if req.get("keyframe_asset_id") != shot.keyframe_asset_id:
            return {"ok": False, "error_kind": "failed", "error_message": "关键帧已变化，请重新提交视频生成任务"}
        movement = _frame_prompt(shot)
        if req.get("prompt") != movement or req.get("duration") != int(float(shot.duration or 5)):
            return {"ok": False, "error_kind": "failed", "error_message": "分镜动作或时长已变化，请重新提交视频任务"}
    if provider.name != "mock":
        # 图生视频只能引用提交时已校验的关键帧，避免外部 URL 绕过角色一致性约束。
        if shot is not None and shot.keyframe_asset_id:
            asset = db.get(GeneratedAsset, shot.keyframe_asset_id)
            if asset is not None:
                kf_path = get_settings().media_root_path / asset.file_path
                if kf_path.exists():
                    # 本地关键帧路径由 Provider 层转 Base64 data URL（百炼支持）
                    req["img_url"] = str(kf_path)
        if not req.get("img_url"):
            return {"ok": False, "error_kind": "failed",
                    "error_message": "图生视频缺少 img_url：请先生成关键帧"}
    result = provider.execute(req, _progress_cb(db, task))
    if not result.ok:
        return {"ok": False, "error_message": result.error_message, "error_kind": result.error_kind}
    asset_or_err, ok = _register_provider_file(db, task, result.output.get("local_file"), AssetType.VIDEO.value, "video", f"{task.uuid}-video")
    if not ok:
        return asset_or_err
    asset = asset_or_err
    asset.meta_json = {**(asset.meta_json or {}), "character_refs": refs,
                       "keyframe_asset_id": shot.keyframe_asset_id if shot else None}
    if shot is not None and provider.name != "mock":
        db.refresh(shot)
        validate_character_refs(db, refs)
        if shot.keyframe_asset_id != req.get("keyframe_asset_id") or [int(x) for x in (shot.character_ids or [])] != [r["id"] for r in refs]:
            return {"ok": False, "error_kind": "failed", "error_message": "关键帧已变化，请重新提交视频生成任务"}
    if shot is not None:
        w, h, fps = asset_service.probe_video_size(get_settings().media_root_path / asset.file_path)
        asset.meta_json = {**(asset.meta_json or {}), "width": w, "height": h, "fps": fps}
        shot.video_asset_id = asset.id
        shot.status = ShotStatus.ASSETS_READY.value if shot.keyframe_asset_id else ShotStatus.PARTIAL_READY.value
        db.commit()
    task.output_asset_ids = [asset.id]
    return {"ok": True, "asset_id": asset.id, "file_path": asset.file_path}


def _run_audio(db: Session, task: GenerationTask, provider: GenerationProvider) -> dict:
    """执行对白语音生成：真实 provider 传文本/音色/情绪，产物登记并绑定音频轨。

    Args:
        db: 数据库会话。
        task: 任务行。
        provider: Provider 实例。

    Returns:
        dict: 响应快照。
    """
    req = dict(task.request_payload or {})
    audio_track = dict(req.get("audio_track") or {})
    req["text"] = audio_track.get("text", "")
    req["voice_id"] = audio_track.get("voice_id") or req.get("voice_id")
    req["emotion"] = audio_track.get("emotion") or req.get("emotion")
    req["speed"] = audio_track.get("speed", 1.0)
    result = provider.execute(req, _progress_cb(db, task))
    if not result.ok:
        return {"ok": False, "error_message": result.error_message, "error_kind": result.error_kind}
    asset_or_err, ok = _register_provider_file(db, task, result.output.get("local_file"), AssetType.AUDIO.value, "audio", f"{task.uuid}-audio")
    if not ok:
        return asset_or_err
    asset = asset_or_err
    duration_ms = asset_service.probe_duration_ms(get_settings().media_root_path / asset.file_path)
    # 成功后才创建轨道，确认与缓存命中均不产生空轨或覆盖另一句对白。
    track = None
    if req.get("audio_track_id"):
        track = db.get(AudioTrack, int(req["audio_track_id"]))
    if track is None and task.shot_id:
        track = AudioTrack(
            shot_id=task.shot_id, episode_id=task.episode_id,
            track_type=audio_track.get("track_type") or "dialogue",
            character_id=audio_track.get("character_id"),
            text_raw=audio_track.get("text", ""),
            text_normalized=audio_track.get("text", "").strip(),
            voice_id=audio_track.get("voice_id"), emotion=audio_track.get("emotion"),
            speed=audio_track.get("speed", 1), pitch=audio_track.get("pitch", 0),
            pause_after_ms=audio_track.get("pause_after_ms", 0),
        )
        db.add(track)
    if track is not None:
        track.asset_id = asset.id
        track.duration_ms = duration_ms
        db.commit()
    task.output_asset_ids = [asset.id]
    return {"ok": True, "asset_id": asset.id, "duration_ms": duration_ms}


def _run_asr(db: Session, task: GenerationTask, provider: GenerationProvider) -> dict:
    """执行字幕生成：由对白文本构造字幕行，写 subtitles 表并生成 SRT 文件。

    Args:
        db: 数据库会话。
        task: 任务行。
        provider: Provider 实例。

    Returns:
        dict: 响应快照。
    """
    result = provider.execute(task.request_payload or {}, _progress_cb(db, task))
    if not result.ok:
        return {"ok": False, "error_message": result.error_message, "error_kind": result.error_kind}
    episode = db.get(Episode, task.episode_id) if task.episode_id else None
    if episode is None:
        return {"ok": False, "error_message": "ASR 任务缺少剧集上下文", "error_kind": "failed"}

    # 按分镜顺序计算成片时间轴偏移：字幕必须对齐各分镜在成片中的实际位置，
    # 而不是按音频轨顺序简单累计（否则烧录字幕与画面/声音错位）
    shots = (
        db.query(Shot)
        .filter(Shot.episode_id == episode.id)
        .order_by(Shot.scene_no, Shot.shot_no)
        .all()
    )
    shot_offset: dict[int, int] = {}
    shot_end: dict[int, int] = {}
    total_ms = 0
    for sh in shots:
        dur = int(float(sh.duration or 5.0) * 1000)
        shot_offset[sh.id] = total_ms
        shot_end[sh.id] = total_ms + dur
        total_ms += dur

    segments: list[tuple[int, int, str, int | None]] = []
    for sh in shots:
        tracks = (
            db.query(AudioTrack)
            .filter(AudioTrack.shot_id == sh.id,
                    AudioTrack.id.in_((task.request_payload or {}).get("audio_track_ids") or []))
            .order_by(AudioTrack.id)
            .all()
        )
        inner = shot_offset[sh.id]
        for t in tracks:
            text = (t.text_raw or "").strip()
            if not text:
                continue
            dur_t = t.duration_ms or max(1200, min(len(text) * 150, 4000))
            start = inner
            # 字幕不得越过所属分镜的结束时间
            end = min(start + dur_t, shot_end[sh.id])
            if end - start < 500:
                continue
            segments.append((start, end, text, t.character_id))
            inner = end
    lines = subtitle_service.build_mock_subtitles(episode.title or "第一集", segments)
    issues = subtitle_service.validate_subtitles(lines, None)
    if issues:
        return {"ok": False, "error_message": "字幕校验失败: " + ";".join(issues), "error_kind": "failed"}

    # 落库字幕行（重建）
    db.query(Subtitle).filter(Subtitle.episode_id == episode.id, Subtitle.source == "mock").delete()
    srt_path = asset_service.media_dir("generated") / f"asr_{task.uuid}.srt"
    srt_path.write_text(subtitle_service.build_srt(lines), encoding="utf-8")
    asset = asset_service.register_asset(
        db, project_id=task.project_id, task_id=task.id,
        asset_type=AssetType.SUBTITLE.value, src_file=srt_path,
    )
    for line in lines:
        db.add(Subtitle(
            episode_id=episode.id, text=line.text,
            start_ms=line.start_ms, end_ms=line.end_ms,
            format="srt", source="mock", file_asset_id=asset.id,
            character_id=line.character_id,
        ))
    db.commit()
    task.output_asset_ids = [asset.id]
    return {"ok": True, "asset_id": asset.id, "subtitle_count": len(lines)}


def _run_render(db: Session, task: GenerationTask, provider: GenerationProvider) -> dict:
    """执行成片渲染：前置校验 → FFmpeg 合成 → 登记成片素材。

    Args:
        db: 数据库会话。
        task: 任务行。
        provider: Provider 实例（渲染任务不调用外部 Provider）。

    Returns:
        dict: 响应快照。
    """
    job = db.query(RenderJob).filter(RenderJob.task_id == task.id).first()
    if job is None:
        return {"ok": False, "error_message": "渲染任务缺少 render_jobs 记录", "error_kind": "failed"}
    context = render_service.validate_episode_for_render(db, task.episode_id)
    output = render_service.render_episode(
        db, job, context,
        on_progress=lambda p, stage="": task_service.mark_progress(db, task, p),
    )
    task_service.mark_progress(db, task, 99)
    asset = asset_service.register_asset(
        db, project_id=task.project_id, task_id=task.id,
        asset_type=AssetType.VIDEO.value, src_file=output, subdir="generated",
        file_name=output.name, meta={"kind": "render"},
    )
    job.status = TaskStatus.SUCCEEDED.value
    job.output_asset_id = asset.id
    render_service.mark_shots_rendered(db, task.episode_id)
    episode = db.get(Episode, task.episode_id)
    if episode is not None:
        episode.status = EpisodeStatus.RENDERED.value
    db.commit()
    task.output_asset_ids = [asset.id]
    return {"ok": True, "asset_id": asset.id, "file_path": asset.file_path}


_RUNNERS = {
    "text": _run_script,
    "image": _run_image,
    "video": _run_video,
    "audio": _run_audio,
    "asr": _run_asr,
    "render": _run_render,
}


def run_task(task_uuid: str) -> None:
    """执行单个生成任务（状态机完整流转）。

    Args:
        task_uuid: 任务 UUID。
    """
    from app.core.db import SessionLocal

    db = SessionLocal()
    try:
        task = db.query(GenerationTask).filter(GenerationTask.uuid == task_uuid).first()
        if task is None:
            return
        if task.status != TaskStatus.QUEUED.value:
            # 已被取消或处理过，直接返回
            return
        task._attempt_retry_count = task.retry_count or 0
        if not task_service.mark_processing(db, task):
            return

        # 注入 retry_count：使确定性哈希的 Mock 场景随重试变化（同参数失败后重试有机会成功）
        run_req = dict(task.request_payload or {})
        run_req["_retry_count"] = task.retry_count

        if task.type == TaskType.RENDER.value:
            # 渲染任务不经过外部 Provider，直接执行本地 FFmpeg 合成
            try:
                snapshot = _run_render(db, task, None)
                if snapshot.get("ok"):
                    task_service.finish_task(db, task, status=TaskStatus.SUCCEEDED.value,
                                             response_payload=snapshot)
                else:
                    status = TaskStatus.TIMEOUT if snapshot.get("error_kind") == "timeout" else TaskStatus.FAILED
                    task_service.finish_task(db, task, status=status.value,
                                             error_message=snapshot.get("error_message"))
            except TaskCancelledError:
                task_service.finish_task(db, task, status=TaskStatus.CANCELLED.value,
                                         error_message="cancelled by user")
            except Exception as exc:  # noqa: BLE001 - 任务失败必须落终态而非静默
                db.rollback()
                task = db.query(GenerationTask).filter(GenerationTask.uuid == task_uuid).first()
                task_service.finish_task(db, task, status=TaskStatus.FAILED.value,
                                         error_message=f"{type(exc).__name__}: {exc}")
            return

        provider, provider_name, mode = get_provider(task.type, task.provider, task.mode)
        if get_settings().app_env == "mock" and task.type in ("image", "video") and provider_name != "mock":
            task_service.finish_task(db, task, status=TaskStatus.FAILED.value,
                                     error_message="模拟环境禁止调用真实 AI Provider")
            return
        task.provider = provider_name
        task.mode = mode
        if provider is None:
            task_service.finish_task(
                db, task, status=TaskStatus.FAILED.value,
                error_message=f"供应商 {provider_name} 未注册或 API Key 未配置（mode={mode}）",
            )
            return

        try:
            runner = _RUNNERS.get(task.type)
            if runner is None:
                task_service.finish_task(db, task, status=TaskStatus.FAILED.value,
                                         error_message=f"未知任务类型 {task.type}")
                return
            task.request_payload = run_req
            db.commit()
            snapshot = runner(db, task, provider)
            if snapshot.get("ok"):
                task_service.finish_task(db, task, status=TaskStatus.SUCCEEDED.value,
                                         response_payload=snapshot)
            else:
                status = TaskStatus.TIMEOUT if snapshot.get("error_kind") == "timeout" else TaskStatus.FAILED
                task_service.finish_task(db, task, status=status.value,
                                         error_message=snapshot.get("error_message"))
        except TaskCancelledError:
            task_service.finish_task(db, task, status=TaskStatus.CANCELLED.value,
                                     error_message="cancelled by user")
        except Exception as exc:  # noqa: BLE001 - 任务失败必须落终态而非静默
            db.rollback()
            task = db.query(GenerationTask).filter(GenerationTask.uuid == task_uuid).first()
            task_service.finish_task(db, task, status=TaskStatus.FAILED.value,
                                     error_message=f"{type(exc).__name__}: {exc}")
    finally:
        db.close()


def dispatch_task(task_uuid: str) -> None:
    """投递任务到 Dramatiq 队列（stub broker 时同步执行）。

    Args:
        task_uuid: 任务 UUID。
    """
    from app.core.config import get_settings

    if get_settings().broker_kind == "stub":
        run_task(task_uuid)
        return
    if get_settings().broker_kind == "thread":
        global _executor
        with _executor_lock:
            if _executor is None:
                _executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="mock-task")
            _executor.submit(run_task, task_uuid)
        return
    from app.tasks.worker import process_generation_task

    process_generation_task.send(task_uuid)


def shutdown_local_tasks() -> None:
    """关闭开发模式的本地任务池；正式环境仍由 Dramatiq 执行任务。"""
    global _executor
    with _executor_lock:
        executor, _executor = _executor, None
    if executor is not None:
        executor.shutdown(wait=True)
