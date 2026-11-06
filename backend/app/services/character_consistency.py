"""角色形象提示词与版本化参考图快照。"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.response import BizError, CODE_BIZ_INVALID
from app.models.entities import Character, CharacterAsset, GeneratedAsset, StylePreset


def character_prompt(db: Session, character: Character) -> str:
    """用角色卡和项目画风生成单人设定图提示词。"""
    style_prompt, negative_prompt = image_style(db, character.project_id)
    traits = [
        character.name, character.age_range, character.gender_presentation,
        character.hair, character.face_features, character.body_shape,
        character.clothing, *(character.color_palette or []), *(character.style_tokens or []),
    ]
    return "，".join(filter(None, [
        style_prompt,
        "单人角色设定图，正面半身像，清晰可辨的脸部与服装，纯净背景",
        *traits, "保持脸部、发型和服装的明确特征，无其他人物，无文字和水印",
        f"避免：{negative_prompt}" if negative_prompt else None,
    ]))


def image_style(db: Session, project_id: int) -> tuple[str | None, str | None]:
    """统一选择项目画风与全局画风。"""
    preset = db.query(StylePreset).filter(StylePreset.project_id == project_id).first()
    if preset is None:
        preset = db.query(StylePreset).filter(StylePreset.project_id.is_(None)).first()
    return (preset.style_prompt, preset.negative_prompt) if preset else (None, None)


def shot_character_refs(db: Session, project_id: int, character_ids: list[int], *, require_ready: bool) -> list[dict]:
    """记录当前镜头引用的角色版本和主参考图。"""
    refs = []
    for character_id in character_ids:
        try:
            character = db.get(Character, int(character_id))
        except (TypeError, ValueError):
            raise BizError(CODE_BIZ_INVALID, "分镜角色 ID 无效") from None
        if character is None or character.project_id != project_id:
            raise BizError(CODE_BIZ_INVALID, f"角色 {character_id} 不属于当前项目")
        primary = db.query(CharacterAsset).filter(
            CharacterAsset.character_id == character.id, CharacterAsset.is_primary == 1,
        ).first()
        if require_ready and (not character.confirmed or primary is None):
            raise BizError(CODE_BIZ_INVALID, f"请先为角色「{character.name}」生成或上传主参考图，并确认锁定角色卡")
        if primary is not None and db.get(GeneratedAsset, primary.asset_id) is None:
            raise BizError(CODE_BIZ_INVALID, f"角色「{character.name}」的主参考图已丢失")
        refs.append({
            "id": character.id, "code": character.code, "name": character.name,
            "version": character.version, "primary_asset_id": primary.asset_id if primary else None,
            "description": "，".join(filter(None, [character.name, character.age_range,
                character.gender_presentation, character.hair, character.face_features,
                character.body_shape, character.clothing, *(character.color_palette or []),
                *(character.style_tokens or [])])),
        })
    if require_ready and len(refs) > 3:
        raise BizError(CODE_BIZ_INVALID, "当前图像模型最多支持 3 张角色参考图，请拆分分镜")
    if require_ready:
        for ref in refs:
            asset = db.get(GeneratedAsset, ref["primary_asset_id"])
            if asset is None or not (get_settings().media_root_path / asset.file_path).is_file():
                raise BizError(CODE_BIZ_INVALID, f"角色「{ref['name']}」的主参考图文件已丢失")
    return refs


def validate_character_refs(db: Session, refs: list[dict]) -> None:
    """任务执行时拒绝已变更的角色卡或主参考图。"""
    for ref in refs:
        character = db.get(Character, ref["id"])
        if character is None:
            raise BizError(CODE_BIZ_INVALID, "角色已删除，请重新提交生成任务")
        db.refresh(character)
        primary = db.query(CharacterAsset).filter(
            CharacterAsset.character_id == ref["id"], CharacterAsset.is_primary == 1,
        ).first()
        if (character.version != ref["version"] or not character.confirmed
                or (primary.asset_id if primary else None) != ref["primary_asset_id"]):
            raise BizError(CODE_BIZ_INVALID, "角色版本或主参考图已变化，请重新提交生成任务")
