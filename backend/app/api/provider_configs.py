# -*- coding: utf-8 -*-
"""Provider 配置 API：读取与更新（不含密钥，API Key 只经环境变量）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.enums import TaskType
from app.core.response import BizError, CODE_NOT_FOUND, ok
from app.models.entities import ProviderConfig
from app.schemas.entities import ProviderConfigUpdate

router = APIRouter(tags=["provider-configs"])

# 能力 → 默认 provider（环境变量兜底）
DEFAULT_PROVIDERS = {
    "text": ("mock", "DEEPSEEK_API_KEY"),
    "image": ("mock", "IMAGE_API_KEY"),
    "video": ("mock", "VIDEO_API_KEY"),
    "audio": ("mock", "MINIMAX_API_KEY"),
    "asr": ("mock", "ASR_API_KEY"),
}


@router.get("/api/provider-configs")
def list_provider_configs(db: Session = Depends(get_db)):
    """各能力当前配置（不含密钥明文）。

    Args:
        db: 数据库会话。

    Returns:
        JSONResponse: 配置数组（缺失能力用默认占位）。
    """
    rows = {r.capability: r for r in db.query(ProviderConfig).all()}
    items = []
    for capability in ("text", "image", "video", "audio", "asr"):
        r = rows.get(capability)
        default_provider, default_key_ref = DEFAULT_PROVIDERS[capability]
        items.append({
            "capability": capability,
            "provider": r.provider if r else default_provider,
            "mode": r.mode if r else "mock",
            "model": r.model if r else None,
            "base_url": r.base_url if r else None,
            "api_key_ref": r.api_key_ref if r else default_key_ref,
            "timeout_seconds": r.timeout_seconds if r else 60,
            "max_retries": r.max_retries if r else 2,
            "daily_quota": r.daily_quota if r else None,
            "enabled": bool(r.enabled) if r else True,
        })
    return ok(items)


@router.put("/api/provider-configs/{capability}")
def update_provider_config(capability: str, body: ProviderConfigUpdate, db: Session = Depends(get_db)):
    """更新 Provider 配置（API Key 通过环境变量注入，接口只写变量名）。

    Args:
        capability: 能力标识（text/image/video/audio/asr）。
        body: 更新请求。
        db: 数据库会话。

    Returns:
        JSONResponse: 更新后的配置。

    Raises:
        BizError: capability 非法（40001）。
    """
    if capability not in DEFAULT_PROVIDERS:
        raise BizError(40001, f"非法能力标识 {capability}，可选: {list(DEFAULT_PROVIDERS)}")
    row = db.query(ProviderConfig).filter(ProviderConfig.capability == capability).first()
    if row is None:
        default_provider, _ = DEFAULT_PROVIDERS[capability]
        row = ProviderConfig(capability=capability, provider=default_provider, mode="mock")
        db.add(row)
    data = body.model_dump(exclude_unset=True)
    if "enabled" in data and data["enabled"] is not None:
        data["enabled"] = 1 if data["enabled"] else 0
    for field, value in data.items():
        setattr(row, field, value)
    if not row.api_key_ref:
        row.api_key_ref = DEFAULT_PROVIDERS[capability][1]
    db.commit()
    db.refresh(row)
    return ok({
        "capability": row.capability, "provider": row.provider, "mode": row.mode,
        "model": row.model, "base_url": row.base_url, "api_key_ref": row.api_key_ref,
        "timeout_seconds": row.timeout_seconds, "max_retries": row.max_retries,
        "daily_quota": row.daily_quota, "enabled": bool(row.enabled),
    })
