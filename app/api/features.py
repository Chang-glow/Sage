"""Feature flag API — frontend can list and toggle plugin states at runtime."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.engine.feature_flags import plugin_registry

router = APIRouter()


class ToggleRequest(BaseModel):
    enabled: bool


@router.get("/features")
async def list_features():
    return {"features": plugin_registry.list_all()}


@router.post("/features/{name}/toggle")
async def toggle_feature(name: str, body: ToggleRequest):
    ok = plugin_registry.toggle(name, body.enabled)
    if not ok:
        raise HTTPException(404, f"未找到功能: {name}")
    return {"ok": True, "name": name, "enabled": plugin_registry.is_enabled(name)}
