# -*- coding: utf-8 -*-
"""剧本服务：JSON Schema 校验、结构化剧本落库（自动建档）。"""
from __future__ import annotations

from typing import Any

from jsonschema import Draft202012Validator
from sqlalchemy.orm import Session

from app.core.response import BizError, CODE_BIZ_INVALID
from app.models.entities import (
    Character,
    Episode,
    Location,
    Scene,
    Shot,
)
from app.core.enums import EpisodeStatus

# 剧本 JSON Schema（PRD 4.2.2 / 开发文档 10.4.2 输出最少结构）
SCRIPT_SCHEMA: dict = {
    "type": "object",
    "required": ["episode_title", "logline", "characters", "scenes"],
    "properties": {
        "episode_title": {"type": "string", "minLength": 1},
        "logline": {"type": "string"},
        "characters": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["code", "name"],
                "properties": {
                    "code": {"type": "string"},
                    "name": {"type": "string"},
                    "appearance": {"type": "string"},
                    "voice_id": {"type": "string"},
                },
            },
        },
        "scenes": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["scene_id", "shots"],
                "properties": {
                    "scene_id": {"type": "string"},
                    "location_id": {"type": "string"},
                    "time_of_day": {"type": "string"},
                    "purpose": {"type": "string"},
                    "shots": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["shot_id", "duration_seconds"],
                            "properties": {
                                "shot_id": {"type": "string"},
                                "duration_seconds": {"type": "number", "minimum": 1, "maximum": 60},
                                "characters": {"type": "array", "items": {"type": "string"}},
                                "action": {"type": "string"},
                                "dialogue": {"type": "array"},
                                "sound_cue": {"type": "string"},
                            },
                        },
                    },
                },
            },
        },
    },
}

# 剧本解析失败允许的最大「修复 JSON」重试次数
MAX_JSON_FIX_RETRIES = 2

_validator = Draft202012Validator(SCRIPT_SCHEMA)


def validate_script(script: Any) -> dict:
    """校验剧本符合 JSON Schema。

    Args:
        script: 待校验的剧本对象。

    Returns:
        dict: 校验通过的剧本。

    Raises:
        BizError: Schema 校验失败（40002），errors 附带详情。
    """
    errors = sorted(_validator.iter_errors(script), key=lambda e: e.path)
    if errors:
        details = [
            {"field": "/".join(str(p) for p in e.path) or "$", "reason": e.message}
            for e in errors[:10]
        ]
        raise BizError(CODE_BIZ_INVALID, "剧本 JSON Schema 校验失败", {"errors": details})
    return script


def apply_script_to_episode(db: Session, episode: Episode, script: dict) -> None:
    """将结构化剧本落库：更新剧集并自动建档角色/地点/场景/分镜。

    剧本引用的 character/location 不存在时自动建档（PRD 4.2.2 校验规则）。

    Args:
        db: 数据库会话（调用方提交）。
        episode: 目标剧集。
        script: 已通过 Schema 校验的剧本。
    """
    project_id = episode.project_id
    episode.script_json = script
    episode.title = script.get("episode_title") or episode.title
    episode.logline = (script.get("logline") or episode.logline or "")[:500]
    episode.status = EpisodeStatus.SCRIPT_GENERATED.value

    # 清空旧的场景与分镜（重新生成即重建）
    for sc in db.query(Scene).filter(Scene.episode_id == episode.id).all():
        db.query(Shot).filter(Shot.scene_id == sc.id).delete()
        db.delete(sc)

    # 角色建档（按 code 幂等）
    char_map: dict[str, int] = {}
    for ch in script.get("characters") or []:
        code = ch.get("code") or f"char_{len(char_map) + 1:03d}"
        existing = db.query(Character).filter(Character.project_id == project_id, Character.code == code).first()
        if existing:
            char_map[code] = existing.id
        else:
            obj = Character(
                project_id=project_id, code=code, name=ch.get("name") or code,
                hair=(ch.get("appearance") or "")[:300] or None,
                voice_id=ch.get("voice_id"),
            )
            db.add(obj)
            db.flush()
            char_map[code] = obj.id

    # 地点建档
    loc_map: dict[str, int] = {}
    for sc in script.get("scenes") or []:
        loc_code = sc.get("location_id") or "location_001"
        if loc_code not in loc_map:
            existing = db.query(Location).filter(Location.project_id == project_id, Location.code == loc_code).first()
            if existing:
                loc_map[loc_code] = existing.id
            else:
                obj = Location(project_id=project_id, code=loc_code, name=loc_code)
                db.add(obj)
                db.flush()
                loc_map[loc_code] = obj.id

    # 场景与分镜
    for scene_no, sc in enumerate(script.get("scenes") or [], start=1):
        scene = Scene(
            episode_id=episode.id,
            scene_no=scene_no,
            code=sc.get("scene_id") or f"scene_{scene_no:03d}",
            location_id=loc_map.get(sc.get("location_id") or "location_001"),
            time_of_day=sc.get("time_of_day"),
            purpose=(sc.get("purpose") or "")[:300] or None,
            summary="",
        )
        db.add(scene)
        db.flush()
        for shot_no, sh in enumerate(sc.get("shots") or [], start=1):
            char_ids = [char_map[c] for c in (sh.get("characters") or []) if c in char_map]
            dialogue = []
            for line in sh.get("dialogue") or []:
                if not isinstance(line, dict):
                    continue
                line = dict(line)
                reference = line.get("character_id") or line.get("character") or line.get("character_code")
                if reference in char_map:
                    line["character_id"] = char_map[reference]
                elif reference not in char_map.values():
                    line.pop("character_id", None)
                dialogue.append(line)
            db.add(Shot(
                episode_id=episode.id,
                scene_id=scene.id,
                scene_no=scene_no,
                shot_no=shot_no,
                code=sh.get("shot_id") or f"shot_{shot_no:03d}",
                location_id=scene.location_id,
                character_ids=char_ids,
                action_description=sh.get("action"),
                dialogue=dialogue,
                duration=float(sh.get("duration_seconds") or 5.0),
            ))
