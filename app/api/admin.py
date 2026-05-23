from __future__ import annotations

import secrets
from collections.abc import AsyncGenerator
from datetime import date
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.engine.agent_factory import create_agent
from app.engine.usage_tracker import get_agent_usage, get_daily_usage
from app.models.agent import Agent

router = APIRouter()
security = HTTPBasic()


class DeployRequest(BaseModel):
    count: int = Field(..., ge=1, le=10)
    constraints: Optional[dict] = None


def verify_admin(credentials: HTTPBasicCredentials = Depends(security)):
    if not secrets.compare_digest(credentials.password, settings.admin_password):
        raise HTTPException(status_code=401, detail="未授权")


async def get_db(request: Request) -> AsyncGenerator[AsyncSession, None]:
    async with request.app.state.db_session_factory() as session:
        yield session


@router.post("/deploy")
async def deploy_agents(
    body: DeployRequest,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_admin),
):
    agents = []
    for _ in range(body.count):
        agent = await create_agent(db)
        agents.append({"agent_id": str(agent.id), "nickname": agent.nickname})
    await db.commit()
    return {"deployed": len(agents), "agents": agents}


@router.get("/stats")
async def get_stats(
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_admin),
):
    total = await db.execute(select(func.count()).select_from(Agent))
    total_count = total.scalar()

    online = await db.execute(
        select(func.count()).select_from(Agent).where(Agent.is_online == True)
    )
    online_count = online.scalar()

    return {
        "total_agents": total_count,
        "online_agents": online_count,
    }


@router.get("/stats/usage/daily")
async def get_usage_daily(
    target_date: str | None = Query(None, description="日期 YYYY-MM-DD，默认今天"),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_admin),
):
    """获取指定日期的 API 调用和 Token 用量汇总。"""
    parsed_date = None
    if target_date:
        try:
            parsed_date = date.fromisoformat(target_date)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"invalid date format: {target_date}")
    return await get_daily_usage(db, target_date=parsed_date)


@router.get("/stats/usage/agent/{agent_id}")
async def get_usage_by_agent(
    agent_id: UUID,
    days: int = Query(30, ge=1, le=365, description="查询天数范围，默认 30"),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_admin),
):
    """获取指定 Agent 在最近 N 天的用量统计。"""
    return await get_agent_usage(db, agent_id=str(agent_id), days=days)
