# -*- coding: utf-8 -*-
"""素材 API：上传、元信息、文件流（预览，支持 Range）、列表、删除。"""
from __future__ import annotations

import mimetypes
import os
import re
from pathlib import Path

from fastapi import APIRouter, Depends, Query, Request, UploadFile, File, Form
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.enums import AssetType
from app.core.response import BizError, CODE_NOT_FOUND, ok
from app.models.entities import GeneratedAsset, Project
from app.services.asset_service import media_dir, register_asset, safe_filename
from app.providers.base import new_uuid

router = APIRouter(prefix="/api/assets", tags=["assets"])


def get_asset_or_404(db: Session, asset_id: int) -> GeneratedAsset:
    """按 ID 获取素材。

    Args:
        db: 数据库会话。
        asset_id: 素材 ID。

    Returns:
        GeneratedAsset: 素材行。
    """
    a = db.get(GeneratedAsset, asset_id)
    if a is None:
        raise BizError(CODE_NOT_FOUND, f"素材 {asset_id} 不存在")
    return a


def _asset_dict(a: GeneratedAsset) -> dict:
    """序列化素材行。

    Args:
        a: 素材行。

    Returns:
        dict: 素材数据。
    """
    return {
        "id": a.id, "project_id": a.project_id, "task_id": a.task_id,
        "asset_type": a.asset_type, "file_path": a.file_path, "file_name": a.file_name,
        "mime_type": a.mime_type, "file_size": a.file_size, "meta_json": a.meta_json,
        "created_at": a.created_at.isoformat() if a.created_at else None,
        "raw_url": f"/api/assets/{a.id}/raw",
    }


@router.post("/upload")
async def upload_asset(
    file: UploadFile = File(...),
    project_id: int = Form(...),
    asset_type: str = Form(...),
    db: Session = Depends(get_db),
):
    """上传本地素材（multipart）。

    Args:
        file: 上传的文件。
        project_id: 所属项目。
        asset_type: 素材类型（image/video/audio/subtitle）。
        db: 数据库会话。

    Returns:
        JSONResponse: 素材记录。
    """
    if db.get(Project, project_id) is None:
        raise BizError(CODE_NOT_FOUND, f"项目 {project_id} 不存在")
    if asset_type not in (t.value for t in AssetType):
        raise BizError(40001, f"非法素材类型 {asset_type}")
    name = safe_filename(file.filename or "upload.bin")
    tmp = media_dir("uploads") / f"{new_uuid()}_{name}"
    tmp.write_bytes(await file.read())
    asset = register_asset(db, project_id=project_id, task_id=None,
                           asset_type=asset_type, src_file=tmp)
    tmp.unlink(missing_ok=True)
    db.commit()
    return ok(_asset_dict(asset))


@router.get("/{asset_id}")
def get_asset(asset_id: int, db: Session = Depends(get_db)):
    """素材元信息。

    Args:
        asset_id: 素材 ID。
        db: 数据库会话。

    Returns:
        JSONResponse: 素材数据。
    """
    return ok(_asset_dict(get_asset_or_404(db, asset_id)))


@router.get("/{asset_id}/raw")
def get_asset_raw(asset_id: int, request: Request, db: Session = Depends(get_db)):
    """文件流（预览用，支持 Range 请求）。

    Args:
        asset_id: 素材 ID。
        request: 请求对象。
        db: 数据库会话。

    Returns:
        FileResponse: 文件流响应。

    Raises:
        BizError: 文件缺失（40401）。
    """
    a = get_asset_or_404(db, asset_id)
    path = get_media_root() / a.file_path
    if not path.exists():
        raise BizError(CODE_NOT_FOUND, f"素材文件缺失: {a.file_path}")
    mime = a.mime_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream"

    range_header = request.headers.get("range")
    if range_header:
        m = re.match(r"bytes=(\d*)-(\d*)$", range_header)
        if m:
            size = path.stat().st_size
            start = int(m.group(1)) if m.group(1) else 0
            end = int(m.group(2)) if m.group(2) else size - 1
            end = min(end, size - 1)
            if start > end or start >= size:
                from fastapi.responses import Response as FResponse
                return FResponse(status_code=416, headers={"Content-Range": f"bytes */{size}"})
            def iter_file(p: Path, s: int, e: int):
                """分块读取文件字节。

                Args:
                    p: 文件路径。
                    s: 起始字节。
                    e: 结束字节。

                Yields:
                    bytes: 数据块。
                """
                with open(p, "rb") as f:
                    f.seek(s)
                    remaining = e - s + 1
                    while remaining > 0:
                        chunk = f.read(min(1 << 20, remaining))
                        if not chunk:
                            break
                        remaining -= len(chunk)
                        yield chunk
            from fastapi.responses import StreamingResponse
            return StreamingResponse(
                iter_file(path, start, end), status_code=206, media_type=mime,
                headers={
                    "Content-Range": f"bytes {start}-{end}/{size}",
                    "Accept-Ranges": "bytes",
                    "Content-Length": str(end - start + 1),
                },
            )
    return FileResponse(path, media_type=mime, filename=a.file_name or path.name)


def get_media_root():
    """获取媒体根目录。

    Returns:
        Path: 媒体根目录。
    """
    from app.core.config import get_settings
    return get_settings().media_root_path


@router.get("")
@router.get("/")
def list_assets(
    project_id: int | None = Query(None), asset_type: str | None = Query(None),
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """素材库列表。

    Args:
        project_id: 项目过滤。
        asset_type: 类型过滤（image/video/audio/subtitle）。
        page: 页码。
        page_size: 每页条数。
        db: 数据库会话。

    Returns:
        JSONResponse: ``{total, items}``。
    """
    q = db.query(GeneratedAsset)
    if project_id is not None:
        q = q.filter(GeneratedAsset.project_id == project_id)
    if asset_type:
        q = q.filter(GeneratedAsset.asset_type == asset_type)
    total = q.count()
    items = q.order_by(GeneratedAsset.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return ok({"total": total, "items": [_asset_dict(a) for a in items]})


@router.delete("/{asset_id}")
def delete_asset(asset_id: int, db: Session = Depends(get_db)):
    """删除素材记录（文件保留于媒体目录）。

    Args:
        asset_id: 素材 ID。
        db: 数据库会话。

    Returns:
        JSONResponse: 空数据成功响应。
    """
    a = get_asset_or_404(db, asset_id)
    db.delete(a)
    db.commit()
    return ok(None, "deleted")
