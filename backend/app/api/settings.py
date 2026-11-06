# -*- coding: utf-8 -*-
"""设定管理 API：角色卡 / 场景卡(locations) / 画风预设。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, UploadFile, File
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.response import BizError, CODE_NOT_FOUND, CODE_STATE_CONFLICT, ok
from app.models.entities import Character, CharacterAsset, GeneratedAsset, Location, StylePreset, Project
from app.schemas.entities import (
    CharacterCreate, CharacterUpdate, LocationCreate, LocationUpdate,
    StylePresetCreate, StylePresetUpdate,
)
from app.services.asset_service import safe_filename
from app.services.asset_service import register_asset, media_dir
from app.core.enums import AssetType
from app.providers.base import new_uuid

router = APIRouter(tags=["settings"])


def _character_asset_dict(link: CharacterAsset, asset: GeneratedAsset) -> dict:
    """序列化角色参考图关联，供角色库和分镜快捷引用使用。"""
    return {
        "id": link.id,
        "asset_id": asset.id,
        "asset_type": link.asset_type,
        "is_primary": bool(link.is_primary),
        "file_name": asset.file_name,
        "raw_url": f"/api/assets/{asset.id}/raw",
    }


def _character_assets(db: Session, character_id: int) -> list[dict]:
    """按主参考图优先返回角色参考素材。"""
    rows = (
        db.query(CharacterAsset, GeneratedAsset)
        .join(GeneratedAsset, GeneratedAsset.id == CharacterAsset.asset_id)
        .filter(CharacterAsset.character_id == character_id)
        .order_by(CharacterAsset.is_primary.desc(), CharacterAsset.id.asc())
        .all()
    )
    return [_character_asset_dict(link, asset) for link, asset in rows]


# ---------- 角色卡 ----------
@router.post("/api/projects/{project_id}/characters")
def create_character(project_id: int, body: CharacterCreate, db: Session = Depends(get_db)):
    """创建角色卡。

    Args:
        project_id: 项目 ID。
        body: 角色卡创建请求。
        db: 数据库会话。

    Returns:
        JSONResponse: 新角色卡。
    """
    if db.get(Project, project_id) is None:
        raise BizError(CODE_NOT_FOUND, f"项目 {project_id} 不存在")
    code = body.code
    if not code:
        count = db.query(Character).filter(Character.project_id == project_id).count()
        code = f"char_{count + 1:03d}"
    c = Character(project_id=project_id, code=code, version=1, confirmed=0, **body.model_dump(exclude={"code"}))
    db.add(c)
    db.commit()
    db.refresh(c)
    return ok({"id": c.id, "code": c.code, "name": c.name, "version": c.version, "confirmed": c.confirmed})


@router.get("/api/projects/{project_id}/characters")
def list_characters(project_id: int, db: Session = Depends(get_db)):
    """角色卡列表。

    Args:
        project_id: 项目 ID。
        db: 数据库会话。

    Returns:
        JSONResponse: 角色卡数组。
    """
    chars = db.query(Character).filter(Character.project_id == project_id).order_by(Character.id).all()
    return ok([
        {
            "id": c.id, "code": c.code, "name": c.name, "age_range": c.age_range,
            "gender_presentation": c.gender_presentation, "hair": c.hair,
            "face_features": c.face_features, "body_shape": c.body_shape, "clothing": c.clothing,
            "color_palette": c.color_palette, "style_tokens": c.style_tokens,
            "voice_id": c.voice_id, "voice_emotions": c.voice_emotions,
            "version": c.version, "confirmed": c.confirmed,
            "reference_assets": _character_assets(db, c.id),
        }
        for c in chars
    ])


@router.put("/api/characters/{character_id}")
def update_character(character_id: int, body: CharacterUpdate, db: Session = Depends(get_db)):
    """更新角色卡（已锁定角色卡禁止修改，需先解锁——本版不提供解锁，按文档语义拒绝）。

    Args:
        character_id: 角色 ID。
        body: 更新请求。
        db: 数据库会话。

    Returns:
        JSONResponse: 更新后的角色卡。
    """
    c = _get_char_or_404(db, character_id)
    if c.confirmed:
        raise BizError(CODE_STATE_CONFLICT, "角色卡已锁定（confirmed），不可修改")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(c, field, value)
    c.version = c.version + 1
    db.commit()
    db.refresh(c)
    return ok({"id": c.id, "name": c.name, "version": c.version, "confirmed": c.confirmed})


@router.delete("/api/characters/{character_id}")
def delete_character(character_id: int, db: Session = Depends(get_db)):
    """删除角色卡。

    Args:
        character_id: 角色 ID。
        db: 数据库会话。

    Returns:
        JSONResponse: 空数据成功响应。
    """
    c = _get_char_or_404(db, character_id)
    db.query(CharacterAsset).filter(CharacterAsset.character_id == character_id).delete()
    db.delete(c)
    db.commit()
    return ok(None, "deleted")


@router.post("/api/characters/{character_id}/confirm")
def confirm_character(character_id: int, db: Session = Depends(get_db)):
    """锁定角色卡：version+1，此后生成任务只能按版本引用。

    Args:
        character_id: 角色 ID。
        db: 数据库会话。

    Returns:
        JSONResponse: 锁定后的角色卡。
    """
    c = _get_char_or_404(db, character_id)
    if not c.confirmed:
        c.version = c.version + 1
    c.confirmed = 1
    db.commit()
    db.refresh(c)
    return ok({"id": c.id, "name": c.name, "version": c.version, "confirmed": c.confirmed})


@router.post("/api/characters/{character_id}/assets")
async def upload_character_asset(character_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    """上传角色参考图（multipart）。

    Args:
        character_id: 角色 ID。
        file: 上传的图片文件。
        db: 数据库会话。

    Returns:
        JSONResponse: 素材关联记录。
    """
    c = _get_char_or_404(db, character_id)
    if c.confirmed:
        raise BizError(CODE_STATE_CONFLICT, "角色卡已锁定（confirmed），不能新增参考图")
    name = safe_filename(file.filename or "ref.png")
    tmp = media_dir("uploads") / f"{new_uuid()}_{name}"
    tmp.write_bytes(await file.read())
    asset = register_asset(db, project_id=c.project_id, task_id=None,
                           asset_type=AssetType.IMAGE.value, src_file=tmp, subdir="characters")
    tmp.unlink(missing_ok=True)
    has_primary = db.query(CharacterAsset).filter(
        CharacterAsset.character_id == c.id, CharacterAsset.is_primary == 1,
    ).first() is not None
    ca = CharacterAsset(character_id=c.id, asset_id=asset.id, asset_type="reference", is_primary=0 if has_primary else 1)
    db.add(ca)
    db.commit()
    db.refresh(ca)
    return ok(_character_asset_dict(ca, asset))


@router.get("/api/characters/{character_id}/assets")
def list_character_assets(character_id: int, db: Session = Depends(get_db)):
    """列出角色卡的参考图及主图状态。"""
    _get_char_or_404(db, character_id)
    return ok(_character_assets(db, character_id))


@router.post("/api/characters/{character_id}/assets/{asset_id}/primary")
def set_primary_character_asset(character_id: int, asset_id: int, db: Session = Depends(get_db)):
    """将角色卡的一张参考图设为主参考图。"""
    character = _get_char_or_404(db, character_id)
    if character.confirmed:
        raise BizError(CODE_STATE_CONFLICT, "角色卡已锁定（confirmed），不能更换主参考图")
    link = db.query(CharacterAsset).filter(
        CharacterAsset.character_id == character_id, CharacterAsset.asset_id == asset_id,
    ).first()
    if link is None:
        raise BizError(CODE_NOT_FOUND, "该素材不是此角色的参考图")
    db.query(CharacterAsset).filter(CharacterAsset.character_id == character_id).update(
        {CharacterAsset.is_primary: 0}, synchronize_session=False,
    )
    link.is_primary = 1
    db.commit()
    return ok(_character_assets(db, character_id))


def _get_char_or_404(db: Session, character_id: int) -> Character:
    """按 ID 获取角色卡。

    Args:
        db: 数据库会话。
        character_id: 角色 ID。

    Returns:
        Character: 角色行。
    """
    c = db.get(Character, character_id)
    if c is None:
        raise BizError(CODE_NOT_FOUND, f"角色 {character_id} 不存在")
    return c


# ---------- 场景卡（locations） ----------
@router.post("/api/projects/{project_id}/locations")
def create_location(project_id: int, body: LocationCreate, db: Session = Depends(get_db)):
    """创建场景卡（地点）。

    Args:
        project_id: 项目 ID。
        body: 场景卡创建请求。
        db: 数据库会话。

    Returns:
        JSONResponse: 新场景卡。
    """
    code = body.code
    if not code:
        count = db.query(Location).filter(Location.project_id == project_id).count()
        code = f"location_{count + 1:03d}"
    loc = Location(project_id=project_id, code=code, **body.model_dump(exclude={"code"}))
    db.add(loc)
    db.commit()
    db.refresh(loc)
    return ok({"id": loc.id, "code": loc.code, "name": loc.name})


@router.get("/api/projects/{project_id}/locations")
def list_locations(project_id: int, db: Session = Depends(get_db)):
    """场景卡列表。

    Args:
        project_id: 项目 ID。
        db: 数据库会话。

    Returns:
        JSONResponse: 场景卡数组。
    """
    locs = db.query(Location).filter(Location.project_id == project_id).order_by(Location.id).all()
    return ok([
        {"id": l.id, "code": l.code, "name": l.name, "description": l.description,
         "time_of_day": l.time_of_day, "lighting": l.lighting, "scene_prompt": l.scene_prompt}
        for l in locs
    ])


@router.put("/api/locations/{location_id}")
def update_location(location_id: int, body: LocationUpdate, db: Session = Depends(get_db)):
    """更新场景卡。

    Args:
        location_id: 场景卡 ID。
        body: 更新请求。
        db: 数据库会话。

    Returns:
        JSONResponse: 更新后的场景卡。
    """
    loc = db.get(Location, location_id)
    if loc is None:
        raise BizError(CODE_NOT_FOUND, f"场景卡 {location_id} 不存在")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(loc, field, value)
    db.commit()
    db.refresh(loc)
    return ok({"id": loc.id, "code": loc.code, "name": loc.name})


@router.delete("/api/locations/{location_id}")
def delete_location(location_id: int, db: Session = Depends(get_db)):
    """删除场景卡。

    Args:
        location_id: 场景卡 ID。
        db: 数据库会话。

    Returns:
        JSONResponse: 空数据成功响应。
    """
    loc = db.get(Location, location_id)
    if loc is None:
        raise BizError(CODE_NOT_FOUND, f"场景卡 {location_id} 不存在")
    db.delete(loc)
    db.commit()
    return ok(None, "deleted")


# ---------- 画风预设 ----------
@router.post("/api/style-presets")
def create_style_preset(body: StylePresetCreate, db: Session = Depends(get_db)):
    """创建画风预设。

    Args:
        body: 画风创建请求。
        db: 数据库会话。

    Returns:
        JSONResponse: 新画风预设。
    """
    sp = StylePreset(**body.model_dump())
    db.add(sp)
    db.commit()
    db.refresh(sp)
    return ok({"id": sp.id, "name": sp.name, "project_id": sp.project_id})


@router.get("/api/style-presets")
def list_style_presets(project_id: int | None = None, db: Session = Depends(get_db)):
    """画风预设列表（可按项目过滤，含全局预设）。

    Args:
        project_id: 项目 ID 过滤。
        db: 数据库会话。

    Returns:
        JSONResponse: 画风预设数组。
    """
    q = db.query(StylePreset)
    if project_id is not None:
        q = q.filter((StylePreset.project_id == project_id) | (StylePreset.project_id.is_(None)))
    return ok([
        {"id": s.id, "project_id": s.project_id, "name": s.name,
         "style_prompt": s.style_prompt, "negative_prompt": s.negative_prompt, "params": s.params}
        for s in q.order_by(StylePreset.id).all()
    ])


@router.put("/api/style-presets/{preset_id}")
def update_style_preset(preset_id: int, body: StylePresetUpdate, db: Session = Depends(get_db)):
    """更新画风预设。

    Args:
        preset_id: 预设 ID。
        body: 更新请求。
        db: 数据库会话。

    Returns:
        JSONResponse: 更新后的画风预设。
    """
    sp = db.get(StylePreset, preset_id)
    if sp is None:
        raise BizError(CODE_NOT_FOUND, f"画风预设 {preset_id} 不存在")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(sp, field, value)
    db.commit()
    db.refresh(sp)
    return ok({"id": sp.id, "name": sp.name})


@router.delete("/api/style-presets/{preset_id}")
def delete_style_preset(preset_id: int, db: Session = Depends(get_db)):
    """删除画风预设。

    Args:
        preset_id: 预设 ID。
        db: 数据库会话。

    Returns:
        JSONResponse: 空数据成功响应。
    """
    sp = db.get(StylePreset, preset_id)
    if sp is None:
        raise BizError(CODE_NOT_FOUND, f"画风预设 {preset_id} 不存在")
    db.delete(sp)
    db.commit()
    return ok(None, "deleted")
