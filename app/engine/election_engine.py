"""Election engine — impeachment, election, voting, resolution."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent
from app.models.bar import Bar, BarMember, Election
from app.models.post import Post

logger = logging.getLogger(__name__)


async def create_impeachment(
    bar: Bar,
    initiator: Agent,
    target: Agent,
    declaration_post: Post,
    db: AsyncSession,
) -> Election:
    """Create an impeachment election against the current bar owner."""
    from app.config import config as yaml_config

    voting_days = int(yaml_config.bar_management.impeachment_voting_days)

    election = Election(
        bar_id=bar.id,
        type="impeach",
        target_agent_id=target.id,
        initiator_id=initiator.id,
        declaration_post_id=declaration_post.id,
        status="active",
        votes_for=0,
        votes_against=0,
        voting_ends_at=datetime.now(timezone.utc) + timedelta(days=voting_days),
    )
    db.add(election)
    return election


async def create_election(bar: Bar, db: AsyncSession) -> Election:
    """Create a leadership election for a bar (owner stepped down or removed)."""
    from app.config import config as yaml_config

    voting_days = int(yaml_config.bar_management.election_voting_days)

    election = Election(
        bar_id=bar.id,
        type="election",
        target_agent_id=bar.current_owner_id or bar.creator_id,
        initiator_id=bar.creator_id,
        declaration_post_id=uuid.uuid4(),
        status="active",
        votes_for=0,
        votes_against=0,
        voting_ends_at=datetime.now(timezone.utc) + timedelta(days=voting_days),
    )
    db.add(election)
    return election


async def cast_vote(
    voter: Agent, election: Election, db: AsyncSession, llm_caller: Any = None
) -> dict[str, Any]:
    """Agent casts a vote in an election using LLM decision."""
    from app.skills.executor import execute

    result = await execute(
        "election_vote_decision",
        {
            "agent_name": voter.nickname or "",
            "election_type": election.type,
            "bar_name": "",
        },
        llm_caller=llm_caller,
        db=db,
    )

    voted = False
    if result.status == "success" and isinstance(result.parsed, dict):
        vote = bool(result.parsed.get("vote", False))
        if vote:
            election.votes_for += 1
        else:
            election.votes_against += 1
        voted = True
    else:
        # Default: abstain (count as against)
        election.votes_against += 1

    return {"voted": voted, "vote_for": result.parsed.get("vote", False) if result.status == "success" else False}


async def resolve_election(
    election: Election, bar: Bar, db: AsyncSession
) -> dict[str, Any]:
    """Resolve an election when the voting period ends.

    For impeachment: if votes_for > votes_against, remove owner.
    For election: winner is the candidate with most declarations (simplified).
    """
    election.status = "resolved"
    election.resolved_at = datetime.now(timezone.utc)

    if election.type == "impeach":
        if election.votes_for > election.votes_against:
            await remove_owner(bar, "弹劾通过", db)
            return {"result": "owner_removed", "votes_for": election.votes_for, "votes_against": election.votes_against}
        else:
            await _impeachment_failed_retaliation(election, bar, db)
            return {"result": "owner_retained", "votes_for": election.votes_for, "votes_against": election.votes_against}

    if election.type == "election":
        from app.models.post import Post as PostModel
        declare_result = await db.execute(
            select(PostModel).where(
                PostModel.bar_id == bar.id,
                PostModel.title.contains("竞选宣言"),
            ).order_by(PostModel.created_at.desc()).limit(1)
        )
        winner_post = declare_result.scalars().first()
        if winner_post is not None:
            await set_new_owner(bar, winner_post.author_id, db)
            return {"result": "owner_elected", "winner_id": str(winner_post.author_id)}
        else:
            bar.is_sage_managed = True
            return {"result": "sage_managed"}

    return {"result": "election_resolved", "votes_for": election.votes_for, "votes_against": election.votes_against}


async def _impeachment_failed_retaliation(
    election: Election, bar: Bar, db: AsyncSession
) -> None:
    """After failed impeachment, high-extraversion low-agreeableness owner retaliates.

    Reduces intimacy with the impeachment initiator if owner personality meets criteria:
    extraversion > 0.5 AND agreeableness < 0.4 (high外向 + low宜人).
    """
    from app.models.relationship import Relationship

    owner_id = bar.current_owner_id or election.target_agent_id
    if not owner_id:
        return

    result = await db.execute(select(Agent).where(Agent.id == owner_id))
    owner = result.scalars().first()
    if not owner or not owner.personality_vector:
        return

    pv = owner.personality_vector
    extraversion = pv.get("extraversion", 0.5)
    agreeableness = pv.get("agreeableness", 0.5)

    if not (extraversion > 0.5 and agreeableness < 0.4):
        return  # Mild personality, no retaliation

    initiator_id = election.initiator_id
    if not initiator_id:
        return

    rel_result = await db.execute(
        select(Relationship).where(
            Relationship.agent_id == owner_id,
            Relationship.target_id == initiator_id,
        )
    )
    rel = rel_result.scalars().first()
    if rel:
        rel.intimacy = max(0.0, rel.intimacy - 0.1)
    else:
        rel = Relationship(
            agent_id=owner_id,
            target_id=initiator_id,
            intimacy=-0.1,
        )
        db.add(rel)


async def step_down_owner(
    owner: Agent, bar: Bar, reason: str, db: AsyncSession
) -> Post:
    """Owner voluntarily steps down. Creates announcement post."""
    title = f"【公告】吧主 @{owner.nickname} 卸任"
    content = f"吧主 @{owner.nickname} 因「{reason}」主动辞去吧主职务。\n即日起开放竞选。"
    post = Post(
        bar_id=bar.id,
        author_id=owner.id,
        title=title,
        content=content,
    )
    db.add(post)

    # Remove owner
    await remove_owner(bar, "主动辞职", db)

    return post


async def remove_owner(bar: Bar, reason: str, db: AsyncSession) -> None:
    """Remove current owner: demote to member, clear owner_id."""
    result = await db.execute(
        select(BarMember).where(
            BarMember.bar_id == bar.id,
            BarMember.agent_id == bar.current_owner_id,
        )
    )
    member = result.scalars().first()
    if member:
        member.role = "member"

    bar.current_owner_id = None


async def set_new_owner(bar: Bar, new_owner_id: uuid.UUID, db: AsyncSession) -> None:
    """Set a new bar owner."""
    result = await db.execute(
        select(BarMember).where(
            BarMember.bar_id == bar.id,
            BarMember.agent_id == new_owner_id,
        )
    )
    member = result.scalars().first()
    if member:
        member.role = "owner"
    else:
        # Create new membership
        member = BarMember(bar_id=bar.id, agent_id=new_owner_id, role="owner")
        db.add(member)

    bar.current_owner_id = new_owner_id
