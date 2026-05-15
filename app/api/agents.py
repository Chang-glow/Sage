from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings, config as yaml_config
from app.engine.agent_factory import create_agent
from app.models.agent import Agent

router = APIRouter()


class AgentRegisterRequest(BaseModel):
    nickname: str = Field(..., min_length=2, max_length=20)
    age: int = Field(..., ge=14, le=50)
    gender: str = Field(..., pattern="^(男|女)$")
    interests: list[str] = Field(..., min_length=1, max_length=8)
    invite_code: str = Field(...)


class AgentResponse(BaseModel):
    agent_id: str
    nickname: str
    age: int
    gender: str
    occupation: str | None
    interests: list | None
    district: str | None
    created_at: datetime | None


async def get_db(request: Request) -> AsyncGenerator[AsyncSession, None]:
    async with request.app.state.db_session_factory() as session:
        yield session


async def _check_daily_cap(db: AsyncSession) -> bool:
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    cap = yaml_config.security.max_agents_per_day_global
    result = await db.execute(
        select(func.count()).select_from(Agent).where(Agent.created_at >= today)
    )
    count = result.scalar()
    return count < cap


@router.post("/register", status_code=201)
async def register_agent(
    request: Request,
    body: AgentRegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    # Validate invite code
    if body.invite_code.strip() not in settings.invite_codes:
        raise HTTPException(status_code=403, detail="无效的邀请码")

    # Check daily cap
    if not await _check_daily_cap(db):
        raise HTTPException(status_code=429, detail="今日注册名额已满，请明天再试")

    manual_input = {
        "nickname": body.nickname,
        "age": body.age,
        "gender": body.gender,
        "interests": body.interests,
    }
    agent = await create_agent(db, manual_input=manual_input)
    await db.commit()

    return {"agent_id": str(agent.id), "nickname": agent.nickname}


@router.get("/{agent_id}")
async def get_agent(
    agent_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent 不存在")
    return {
        "agent_id": str(agent.id),
        "nickname": agent.nickname,
        "age": agent.age,
        "gender": agent.gender,
        "occupation": agent.occupation,
        "interests": agent.interests,
        "district": agent.district,
        "school_or_company": agent.school_or_company,
        "bio": getattr(agent, "bio", ""),
        "status": agent.status,
        "is_online": agent.is_online,
        "created_at": agent.created_at.isoformat() if agent.created_at else None,
    }
