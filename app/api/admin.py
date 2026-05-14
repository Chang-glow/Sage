from __future__ import annotations

import secrets
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.engine.agent_factory import create_agent
from app.models.agent import Agent

router = APIRouter()
security = HTTPBasic()


class DeployRequest(BaseModel):
    count: int = Field(..., ge=1, le=10)
    constraints: Optional[dict] = None


def verify_admin(credentials: HTTPBasicCredentials = Depends(security)):
    if not secrets.compare_digest(credentials.password, settings.admin_password):
        raise HTTPException(status_code=401, detail="未授权")


async def get_db(request: Request) -> AsyncSession:
    return request.app.state.db_session_factory()


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
