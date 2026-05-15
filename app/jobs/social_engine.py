from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import select

from app.models.relationship import Relationship

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()

_INTIMACY_REPLY = 0.03
_INTIMACY_LIKE = 0.01
_INTIMACY_FOLLOW = 0.02
_INTIMACY_CONFLICT = -0.05
_INTIMACY_BLOCK = -0.10


async def _ensure_relationship(agent_id, target_id, db: "AsyncSession") -> Relationship:
    """Get or create a Relationship record."""
    result = await db.execute(
        select(Relationship).where(
            Relationship.agent_id == agent_id,
            Relationship.target_id == target_id,
        )
    )
    rel = result.scalar_one_or_none()
    if rel is None:
        rel = Relationship(agent_id=agent_id, target_id=target_id)
        db.add(rel)
        await db.flush()
    return rel


def _tone_to_attitude_delta(tone: str) -> float:
    """Map reply tone to attitude shift."""
    positive_tones = {"友好", "热情", "幽默", "鼓励", "温暖", "赞赏", "共鸣", "关切"}
    negative_tones = {"攻击", "嘲讽", "冷漠", "愤怒", "阴阳怪气", "鄙视", "敌对"}
    if tone in positive_tones:
        return 0.02
    if tone in negative_tones:
        return -0.03
    return 0.0


async def adjust_after_reply(
    agent_id,
    target_id,
    tone: str,
    db: "AsyncSession",
) -> Relationship:
    """Adjust relationship after agent replies to target."""
    if agent_id == target_id:
        return None

    rel = await _ensure_relationship(agent_id, target_id, db)

    # Intimacy
    rel.intimacy = min(1.0, max(-1.0, rel.intimacy + _INTIMACY_REPLY))

    # Attitude
    delta = _tone_to_attitude_delta(tone)
    current = rel.intimacy or 0.0
    if delta > 0 and current > 0.6:
        rel.attitude = "positive"
    elif delta < 0 and current < -0.2:
        rel.attitude = "negative"
    elif delta == 0:
        pass  # keep current
    else:
        if current > 0.3:
            rel.attitude = "positive"
        elif current < -0.1:
            rel.attitude = "negative"
        else:
            rel.attitude = "neutral"

    rel.last_interaction = datetime.now(timezone.utc)
    await db.commit()
    logger.info("relationship_adjusted", agent_id=str(agent_id), target_id=str(target_id),
                intimacy=round(rel.intimacy, 3), attitude=rel.attitude, trigger="reply")
    return rel


async def adjust_after_like(
    agent_id,
    target_id,
    db: "AsyncSession",
) -> Relationship | None:
    """Adjust relationship after agent likes target's post."""
    if agent_id == target_id:
        return None

    rel = await _ensure_relationship(agent_id, target_id, db)
    rel.intimacy = min(1.0, rel.intimacy + _INTIMACY_LIKE)
    rel.last_interaction = datetime.now(timezone.utc)
    await db.commit()
    return rel


async def adjust_after_follow(
    agent_id,
    target_id,
    db: "AsyncSession",
) -> Relationship | None:
    """Adjust relationship after agent follows target."""
    if agent_id == target_id:
        return None

    rel = await _ensure_relationship(agent_id, target_id, db)
    rel.intimacy = min(1.0, rel.intimacy + _INTIMACY_FOLLOW)
    rel.last_interaction = datetime.now(timezone.utc)
    await db.commit()
    return rel


async def adjust_after_conflict(
    agent_id,
    target_id,
    db: "AsyncSession",
) -> Relationship | None:
    """Adjust relationship after conflict (deleted post, mod action)."""
    if agent_id == target_id:
        return None

    rel = await _ensure_relationship(agent_id, target_id, db)
    rel.intimacy = max(-1.0, rel.intimacy + _INTIMACY_CONFLICT)
    if rel.intimacy < -0.2:
        rel.attitude = "negative"
    rel.last_interaction = datetime.now(timezone.utc)
    await db.commit()
    return rel
