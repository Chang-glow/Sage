"""Bar management REST API — bar CRUD, mod actions, elections, appeals."""
from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.engine.bar_manager_engine import (
    can_create_bar,
    check_owner_inactivity,
    create_bar_from_application,
    revise_bar_rules,
)
from app.engine.bar_mod_engine import (
    appoint_sub_mod,
    ban_member,
    essential_post,
    hide_post,
    pin_post,
    record_mod_action,
    remove_sub_mod,
    resolve_appeal,
    submit_appeal,
    unban_member,
    unhide_post,
    unpin_post,
    unessential_post,
)
from app.engine.election_engine import (
    cast_vote,
    create_election,
    resolve_election,
    set_new_owner,
    step_down_owner,
)
from app.models.agent import Agent
from app.models.bar import Bar, BarMember, BarModLog, BarRule, Election

router = APIRouter()


async def get_db(request: Request) -> AsyncGenerator[AsyncSession, None]:
    async with request.app.state.db_session_factory() as session:
        yield session


# ── Request/Response models ──


class ModActionRequest(BaseModel):
    moderator_id: str
    reason: str | None = None


class BanRequest(BaseModel):
    moderator_id: str
    days: int = Field(..., ge=1, le=7)
    reason: str


class AppealRequest(BaseModel):
    agent_id: str
    appeal_reason: str


class ResolveAppealRequest(BaseModel):
    moderator_id: str
    resolution: str  # "upheld" or "rejected"


class AppointModRequest(BaseModel):
    owner_id: str


class VoteRequest(BaseModel):
    voter_id: str


class ReviseRulesRequest(BaseModel):
    owner_id: str
    content: str


class StepDownRequest(BaseModel):
    owner_id: str
    reason: str = "主动辞职"


# ── Query endpoints ──


@router.get("/bars")
async def list_bars(db: AsyncSession = Depends(get_db)):
    """List all bars."""
    result = await db.execute(select(Bar).order_by(Bar.member_count.desc()))
    bars = result.scalars().all()
    return {
        "bars": [
            {
                "id": str(b.id),
                "name": b.name,
                "description": b.description,
                "member_count": b.member_count,
                "current_owner_id": str(b.current_owner_id) if b.current_owner_id else None,
                "is_sage_managed": b.is_sage_managed,
                "post_level_threshold": b.post_level_threshold,
                "created_at": b.created_at.isoformat() if b.created_at else None,
            }
            for b in bars
        ]
    }


@router.get("/bars/{bar_id}")
async def get_bar(bar_id: UUID, db: AsyncSession = Depends(get_db)):
    """Bar detail."""
    result = await db.execute(select(Bar).where(Bar.id == bar_id))
    bar = result.scalars().first()
    if bar is None:
        raise HTTPException(status_code=404, detail="Bar not found")
    return {
        "id": str(bar.id),
        "name": bar.name,
        "description": bar.description,
        "creator_id": str(bar.creator_id),
        "current_owner_id": str(bar.current_owner_id) if bar.current_owner_id else None,
        "member_count": bar.member_count,
        "post_count": bar.post_count,
        "post_level_threshold": bar.post_level_threshold,
        "is_sage_managed": bar.is_sage_managed,
        "created_at": bar.created_at.isoformat() if bar.created_at else None,
    }


@router.get("/bars/{bar_id}/members")
async def list_bar_members(bar_id: UUID, db: AsyncSession = Depends(get_db)):
    """List bar members with roles."""
    result = await db.execute(
        select(BarMember).where(BarMember.bar_id == bar_id)
    )
    members = result.scalars().all()
    return {
        "members": [
            {
                "id": str(m.id),
                "agent_id": str(m.agent_id),
                "role": m.role,
                "is_muted": m.is_muted,
                "muted_until": m.muted_until.isoformat() if m.muted_until else None,
                "joined_at": m.joined_at.isoformat() if m.joined_at else None,
            }
            for m in members
        ]
    }


@router.get("/bars/{bar_id}/mod-log")
async def list_bar_mod_log(
    bar_id: UUID,
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """Bar mod log (paginated)."""
    result = await db.execute(
        select(BarModLog)
        .where(BarModLog.bar_id == bar_id)
        .order_by(BarModLog.created_at.desc())
        .limit(limit)
    )
    logs = result.scalars().all()
    return {
        "mod_logs": [
            {
                "id": str(log.id),
                "action": log.action,
                "moderator_id": str(log.moderator_id),
                "target_type": log.target_type,
                "target_id": str(log.target_id) if log.target_id else None,
                "reason": log.reason,
                "is_appealed": log.is_appealed,
                "appeal_status": log.appeal_status,
                "created_at": log.created_at.isoformat() if log.created_at else None,
            }
            for log in logs
        ]
    }


@router.get("/bars/{bar_id}/rules")
async def list_bar_rules(bar_id: UUID, db: AsyncSession = Depends(get_db)):
    """Current + historical bar rules."""
    result = await db.execute(
        select(BarRule)
        .where(BarRule.bar_id == bar_id)
        .order_by(BarRule.version.desc())
    )
    rules = result.scalars().all()
    return {
        "rules": [
            {
                "id": str(r.id),
                "version": r.version,
                "is_current": r.is_current,
                "content": r.content,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rules
        ]
    }


@router.get("/bars/{bar_id}/elections")
async def list_bar_elections(bar_id: UUID, db: AsyncSession = Depends(get_db)):
    """Active and past elections for a bar."""
    result = await db.execute(
        select(Election)
        .where(Election.bar_id == bar_id)
        .order_by(Election.started_at.desc())
    )
    elections = result.scalars().all()
    return {
        "elections": [
            {
                "id": str(e.id),
                "type": e.type,
                "status": e.status,
                "votes_for": e.votes_for,
                "votes_against": e.votes_against,
                "voting_ends_at": e.voting_ends_at.isoformat() if e.voting_ends_at else None,
                "resolved_at": e.resolved_at.isoformat() if e.resolved_at else None,
            }
            for e in elections
        ]
    }


# ── Mod action endpoints ──


@router.post("/bars/{bar_id}/posts/{post_id}/hide")
async def api_hide_post(
    bar_id: UUID, post_id: UUID, req: ModActionRequest, db: AsyncSession = Depends(get_db)
):
    """Hide a post (mod action)."""
    try:
        mod_id = uuid.UUID(req.moderator_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid moderator_id")
    mod_result = await db.execute(select(Agent).where(Agent.id == mod_id))
    moderator = mod_result.scalars().first()
    if moderator is None:
        raise HTTPException(status_code=404, detail="Moderator not found")
    # Simplified: get post and bar
    from app.models.post import Post as PostModel
    post_result = await db.execute(select(PostModel).where(PostModel.id == post_id))
    post = post_result.scalars().first()
    if post is None:
        raise HTTPException(status_code=404, detail="Post not found")
    bar_result = await db.execute(select(Bar).where(Bar.id == bar_id))
    bar = bar_result.scalars().first()
    if bar is None:
        raise HTTPException(status_code=404, detail="Bar not found")
    log = await hide_post(moderator, post, bar, req.reason or "未提供", db)
    await db.commit()
    return {"status": "ok", "mod_log_id": str(log.id)}


@router.post("/bars/{bar_id}/posts/{post_id}/unhide")
async def api_unhide_post(
    bar_id: UUID, post_id: UUID, req: ModActionRequest, db: AsyncSession = Depends(get_db)
):
    """Unhide a post."""
    mod_id = uuid.UUID(req.moderator_id)
    mod_result = await db.execute(select(Agent).where(Agent.id == mod_id))
    moderator = mod_result.scalars().first()
    if moderator is None:
        raise HTTPException(status_code=404, detail="Moderator not found")
    from app.models.post import Post as PostModel
    post_result = await db.execute(select(PostModel).where(PostModel.id == post_id))
    post = post_result.scalars().first()
    if post is None:
        raise HTTPException(status_code=404, detail="Post not found")
    bar_result = await db.execute(select(Bar).where(Bar.id == bar_id))
    bar = bar_result.scalars().first()
    if bar is None:
        raise HTTPException(status_code=404, detail="Bar not found")
    log = await unhide_post(moderator, post, bar, db)
    await db.commit()
    return {"status": "ok", "mod_log_id": str(log.id)}


@router.post("/bars/{bar_id}/posts/{post_id}/pin")
async def api_pin_post(
    bar_id: UUID, post_id: UUID, req: ModActionRequest, db: AsyncSession = Depends(get_db)
):
    """Pin a post."""
    mod_id = uuid.UUID(req.moderator_id)
    mod_result = await db.execute(select(Agent).where(Agent.id == mod_id))
    moderator = mod_result.scalars().first()
    if moderator is None:
        raise HTTPException(status_code=404, detail="Moderator not found")
    from app.models.post import Post as PostModel
    post_result = await db.execute(select(PostModel).where(PostModel.id == post_id))
    post = post_result.scalars().first()
    if post is None:
        raise HTTPException(status_code=404, detail="Post not found")
    bar_result = await db.execute(select(Bar).where(Bar.id == bar_id))
    bar = bar_result.scalars().first()
    if bar is None:
        raise HTTPException(status_code=404, detail="Bar not found")
    log = await pin_post(moderator, post, bar, db)
    await db.commit()
    return {"status": "ok", "mod_log_id": str(log.id)}


@router.post("/bars/{bar_id}/posts/{post_id}/unpin")
async def api_unpin_post(
    bar_id: UUID, post_id: UUID, req: ModActionRequest, db: AsyncSession = Depends(get_db)
):
    """Unpin a post."""
    mod_id = uuid.UUID(req.moderator_id)
    mod_result = await db.execute(select(Agent).where(Agent.id == mod_id))
    moderator = mod_result.scalars().first()
    if moderator is None:
        raise HTTPException(status_code=404, detail="Moderator not found")
    from app.models.post import Post as PostModel
    post_result = await db.execute(select(PostModel).where(PostModel.id == post_id))
    post = post_result.scalars().first()
    if post is None:
        raise HTTPException(status_code=404, detail="Post not found")
    bar_result = await db.execute(select(Bar).where(Bar.id == bar_id))
    bar = bar_result.scalars().first()
    if bar is None:
        raise HTTPException(status_code=404, detail="Bar not found")
    log = await unpin_post(moderator, post, bar, db)
    await db.commit()
    return {"status": "ok", "mod_log_id": str(log.id)}


@router.post("/bars/{bar_id}/posts/{post_id}/essential")
async def api_essential_post(
    bar_id: UUID, post_id: UUID, req: ModActionRequest, db: AsyncSession = Depends(get_db)
):
    """Mark a post as essential."""
    mod_id = uuid.UUID(req.moderator_id)
    mod_result = await db.execute(select(Agent).where(Agent.id == mod_id))
    moderator = mod_result.scalars().first()
    if moderator is None:
        raise HTTPException(status_code=404, detail="Moderator not found")
    from app.models.post import Post as PostModel
    post_result = await db.execute(select(PostModel).where(PostModel.id == post_id))
    post = post_result.scalars().first()
    if post is None:
        raise HTTPException(status_code=404, detail="Post not found")
    bar_result = await db.execute(select(Bar).where(Bar.id == bar_id))
    bar = bar_result.scalars().first()
    if bar is None:
        raise HTTPException(status_code=404, detail="Bar not found")
    log = await essential_post(moderator, post, bar, db)
    await db.commit()
    return {"status": "ok", "mod_log_id": str(log.id)}


@router.post("/bars/{bar_id}/posts/{post_id}/unessential")
async def api_unessential_post(
    bar_id: UUID, post_id: UUID, req: ModActionRequest, db: AsyncSession = Depends(get_db)
):
    """Remove essential mark."""
    mod_id = uuid.UUID(req.moderator_id)
    mod_result = await db.execute(select(Agent).where(Agent.id == mod_id))
    moderator = mod_result.scalars().first()
    if moderator is None:
        raise HTTPException(status_code=404, detail="Moderator not found")
    from app.models.post import Post as PostModel
    post_result = await db.execute(select(PostModel).where(PostModel.id == post_id))
    post = post_result.scalars().first()
    if post is None:
        raise HTTPException(status_code=404, detail="Post not found")
    bar_result = await db.execute(select(Bar).where(Bar.id == bar_id))
    bar = bar_result.scalars().first()
    if bar is None:
        raise HTTPException(status_code=404, detail="Bar not found")
    log = await unessential_post(moderator, post, bar, db)
    await db.commit()
    return {"status": "ok", "mod_log_id": str(log.id)}


# ── User management endpoints ──


@router.post("/bars/{bar_id}/members/{agent_id}/ban")
async def api_ban_member(
    bar_id: UUID, agent_id: UUID, req: BanRequest, db: AsyncSession = Depends(get_db)
):
    """Ban a member from the bar."""
    mod_id = uuid.UUID(req.moderator_id)
    mod_result = await db.execute(select(Agent).where(Agent.id == mod_id))
    moderator = mod_result.scalars().first()
    if moderator is None:
        raise HTTPException(status_code=404, detail="Moderator not found")
    bar_result = await db.execute(select(Bar).where(Bar.id == bar_id))
    bar = bar_result.scalars().first()
    if bar is None:
        raise HTTPException(status_code=404, detail="Bar not found")
    log = await ban_member(moderator, str(agent_id), bar, req.days, req.reason, db)
    if log is None:
        raise HTTPException(status_code=400, detail="Ban failed — check permission or limits")
    await db.commit()
    return {"status": "ok", "mod_log_id": str(log.id)}


@router.post("/bars/{bar_id}/members/{agent_id}/unban")
async def api_unban_member(
    bar_id: UUID, agent_id: UUID, req: ModActionRequest, db: AsyncSession = Depends(get_db)
):
    """Unban a member."""
    mod_id = uuid.UUID(req.moderator_id)
    mod_result = await db.execute(select(Agent).where(Agent.id == mod_id))
    moderator = mod_result.scalars().first()
    if moderator is None:
        raise HTTPException(status_code=404, detail="Moderator not found")
    bar_result = await db.execute(select(Bar).where(Bar.id == bar_id))
    bar = bar_result.scalars().first()
    if bar is None:
        raise HTTPException(status_code=404, detail="Bar not found")
    log = await unban_member(moderator, str(agent_id), bar, db)
    if log is None:
        raise HTTPException(status_code=404, detail="Member not found")
    await db.commit()
    return {"status": "ok", "mod_log_id": str(log.id)}


@router.post("/bars/{bar_id}/mods/{agent_id}/appoint")
async def api_appoint_sub_mod(
    bar_id: UUID, agent_id: UUID, req: AppointModRequest, db: AsyncSession = Depends(get_db)
):
    """Appoint a sub-moderator."""
    owner_id = uuid.UUID(req.owner_id)
    owner_result = await db.execute(select(Agent).where(Agent.id == owner_id))
    owner = owner_result.scalars().first()
    if owner is None:
        raise HTTPException(status_code=404, detail="Owner not found")
    bar_result = await db.execute(select(Bar).where(Bar.id == bar_id))
    bar = bar_result.scalars().first()
    if bar is None:
        raise HTTPException(status_code=404, detail="Bar not found")
    log = await appoint_sub_mod(owner, str(agent_id), bar, db)
    if log is None:
        raise HTTPException(status_code=404, detail="Member not found")
    await db.commit()
    return {"status": "ok", "mod_log_id": str(log.id)}


@router.post("/bars/{bar_id}/mods/{agent_id}/remove")
async def api_remove_sub_mod(
    bar_id: UUID, agent_id: UUID, req: AppointModRequest, db: AsyncSession = Depends(get_db)
):
    """Remove a sub-moderator."""
    owner_id = uuid.UUID(req.owner_id)
    owner_result = await db.execute(select(Agent).where(Agent.id == owner_id))
    owner = owner_result.scalars().first()
    if owner is None:
        raise HTTPException(status_code=404, detail="Owner not found")
    bar_result = await db.execute(select(Bar).where(Bar.id == bar_id))
    bar = bar_result.scalars().first()
    if bar is None:
        raise HTTPException(status_code=404, detail="Bar not found")
    log = await remove_sub_mod(owner, str(agent_id), bar, db)
    if log is None:
        raise HTTPException(status_code=404, detail="Member not found")
    await db.commit()
    return {"status": "ok", "mod_log_id": str(log.id)}


# ── Appeals ──


@router.post("/mod-log/{log_id}/appeal")
async def api_submit_appeal(
    log_id: UUID, req: AppealRequest, db: AsyncSession = Depends(get_db)
):
    """Submit an appeal for a mod action."""
    agent_id = uuid.UUID(req.agent_id)
    agent_result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = agent_result.scalars().first()
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    result = await submit_appeal(agent, log_id, req.appeal_reason, db)
    if result is None:
        raise HTTPException(status_code=400, detail="Appeal failed — check window or already appealed")
    await db.commit()
    return {"status": "ok"}


@router.post("/mod-log/{log_id}/resolve-appeal")
async def api_resolve_appeal(
    log_id: UUID, req: ResolveAppealRequest, db: AsyncSession = Depends(get_db)
):
    """Resolve an appeal (mod action)."""
    if req.resolution not in ("upheld", "rejected"):
        raise HTTPException(status_code=422, detail="Resolution must be 'upheld' or 'rejected'")
    mod_id = uuid.UUID(req.moderator_id)
    mod_result = await db.execute(select(Agent).where(Agent.id == mod_id))
    moderator = mod_result.scalars().first()
    if moderator is None:
        raise HTTPException(status_code=404, detail="Moderator not found")
    result = await resolve_appeal(moderator, log_id, req.resolution, db)
    if result is None:
        raise HTTPException(status_code=404, detail="Mod log entry not found")
    await db.commit()
    return {"status": "ok", "resolution": req.resolution}


# ── Elections ──


@router.post("/bars/{bar_id}/elections/{election_id}/vote")
async def api_cast_vote(
    bar_id: UUID, election_id: UUID, req: VoteRequest, db: AsyncSession = Depends(get_db)
):
    """Cast a vote in an election."""
    voter_id = uuid.UUID(req.voter_id)
    voter_result = await db.execute(select(Agent).where(Agent.id == voter_id))
    voter = voter_result.scalars().first()
    if voter is None:
        raise HTTPException(status_code=404, detail="Voter not found")
    election_result = await db.execute(
        select(Election).where(Election.id == election_id, Election.bar_id == bar_id)
    )
    election = election_result.scalars().first()
    if election is None:
        raise HTTPException(status_code=404, detail="Election not found")
    if election.status != "active":
        raise HTTPException(status_code=400, detail="Election is not active")
    outcome = await cast_vote(voter, election, db)
    await db.commit()
    return {"status": "ok", "voted": outcome["voted"]}


@router.post("/bars/{bar_id}/step-down")
async def api_step_down(
    bar_id: UUID, req: StepDownRequest, db: AsyncSession = Depends(get_db)
):
    """Owner steps down, triggering election."""
    owner_id = uuid.UUID(req.owner_id)
    owner_result = await db.execute(select(Agent).where(Agent.id == owner_id))
    owner = owner_result.scalars().first()
    if owner is None:
        raise HTTPException(status_code=404, detail="Owner not found")
    bar_result = await db.execute(select(Bar).where(Bar.id == bar_id))
    bar = bar_result.scalars().first()
    if bar is None:
        raise HTTPException(status_code=404, detail="Bar not found")
    if bar.current_owner_id != owner.id:
        raise HTTPException(status_code=403, detail="You are not the owner")
    post = await step_down_owner(owner, bar, req.reason, db)
    await db.commit()
    return {"status": "ok", "post_id": str(post.id)}


# ── Bar rules ──


@router.post("/bars/{bar_id}/rules")
async def api_revise_rules(
    bar_id: UUID, req: ReviseRulesRequest, db: AsyncSession = Depends(get_db)
):
    """Revise bar rules."""
    owner_id = uuid.UUID(req.owner_id)
    owner_result = await db.execute(select(Agent).where(Agent.id == owner_id))
    owner = owner_result.scalars().first()
    if owner is None:
        raise HTTPException(status_code=404, detail="Owner not found")
    bar_result = await db.execute(select(Bar).where(Bar.id == bar_id))
    bar = bar_result.scalars().first()
    if bar is None:
        raise HTTPException(status_code=404, detail="Bar not found")
    new_rule = await revise_bar_rules(bar, owner, req.content, db)
    await db.commit()
    return {"status": "ok", "rule_id": str(new_rule.id), "version": new_rule.version}
