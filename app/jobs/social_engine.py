from __future__ import annotations

from datetime import datetime, timedelta, timezone
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
_PROMISE_BROKEN = -0.05
_PROMISE_FULFILLED = 0.03


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


async def adjust_after_promise_broken(
    requester_id,
    promiser_id,
    promise_content: str,
    db: "AsyncSession",
) -> Relationship | None:
    """Promise broken: reduce intimacy + add distrust_tag to promiser."""
    if requester_id == promiser_id:
        return None

    from app.config import config as yaml_config
    from app.models.agent import Agent

    rel = await _ensure_relationship(requester_id, promiser_id, db)
    rel.intimacy = max(-1.0, min(1.0, rel.intimacy + _PROMISE_BROKEN))
    rel.last_interaction = datetime.now(timezone.utc)
    if rel.intimacy < -0.2:
        rel.attitude = "negative"

    # Add distrust_tag to promiser
    now = datetime.now(timezone.utc)
    duration_days = int(yaml_config.promises.distrust_tag_duration_days)
    expires_at = now + timedelta(days=duration_days)

    result = await db.execute(
        select(Agent).where(Agent.id == promiser_id)
    )
    promiser = result.scalar_one_or_none()
    if promiser is not None:
        tags = list(promiser.distrust_tags or [])
        tags.append({
            "from_id": str(requester_id),
            "reason": promise_content,
            "expires_at": expires_at.isoformat(),
            "created_at": now.isoformat(),
        })
        promiser.distrust_tags = tags

    await db.commit()
    logger.info("promise_broken", requester=str(requester_id), promiser=str(promiser_id),
                intimacy=round(rel.intimacy, 3))
    return rel


async def adjust_after_promise_fulfilled(
    requester_id,
    promiser_id,
    promise_content: str,
    db: "AsyncSession",
    importance: float = 0.5,
) -> Relationship | None:
    """Promise fulfilled: boost intimacy, add trust_tag, remove distrust_tag, boost reputation."""
    if requester_id == promiser_id:
        return None

    from app.config import config as yaml_config
    from app.models.agent import Agent

    # Intimacy boost proportional to importance
    base_boost = float(yaml_config.promises.fulfilled_intimacy_boost)
    boost = base_boost * importance

    rel = await _ensure_relationship(requester_id, promiser_id, db)
    rel.intimacy = min(1.0, max(-1.0, rel.intimacy + boost))
    rel.last_interaction = datetime.now(timezone.utc)

    # Fetch promiser for tag/reputation updates
    result = await db.execute(
        select(Agent).where(Agent.id == promiser_id)
    )
    promiser = result.scalar_one_or_none()
    if promiser is not None:
        now = datetime.now(timezone.utc)

        # Remove distrust_tag from this requester
        tags = list(promiser.distrust_tags or [])
        promiser.distrust_tags = [
            t for t in tags
            if isinstance(t, dict) and t.get("from_id") != str(requester_id)
        ]

        # Add trust_tag
        duration_days = int(yaml_config.promises.trust_tag_duration_days)
        effective_duration = max(1, int(duration_days * importance))
        expires_at = now + timedelta(days=effective_duration)
        trust_tags = list(promiser.trust_tags or [])
        trust_tags.append({
            "from_id": str(requester_id),
            "reason": promise_content,
            "expires_at": expires_at.isoformat(),
            "created_at": now.isoformat(),
        })
        promiser.trust_tags = trust_tags

        # Reputation boost for high importance
        threshold = float(yaml_config.promises.reputation_high_importance_threshold)
        if importance > threshold:
            boost_amount = float(yaml_config.promises.reputation_boost_per_fulfillment)
            promiser.reputation = min(1.0, promiser.reputation + boost_amount)

    await db.commit()
    logger.info("promise_fulfilled", requester=str(requester_id), promiser=str(promiser_id),
                intimacy=round(rel.intimacy, 3), importance=importance)
    return rel
