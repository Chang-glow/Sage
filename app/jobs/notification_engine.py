from __future__ import annotations

import re
import uuid
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import select

from app.models.notification import Notification

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()

_MENTION_RE = re.compile(r"@(\S{2,20})")


async def _create_notification(
    recipient_id,
    sender_id,
    ntype: str,
    db: "AsyncSession",
    *,
    reference_type: str | None = None,
    reference_id: str | None = None,
    message: str | None = None,
    priority: str = "medium",
) -> None:
    notification = Notification(
        recipient_id=recipient_id,
        sender_id=sender_id,
        type=ntype,
        priority=priority,
        reference_type=reference_type,
        reference_id=uuid.UUID(reference_id) if reference_id else None,
        message=message,
    )
    db.add(notification)
    await db.commit()
    logger.info("notification_created", recipient=str(recipient_id), type=ntype, priority=priority)


async def notify_reply(recipient_id, sender_id, post_id: str, db: "AsyncSession") -> None:
    """Notify post author that someone replied."""
    if str(recipient_id) == str(sender_id):
        return
    await _create_notification(
        recipient_id, sender_id, "reply",
        db, reference_type="post", reference_id=post_id,
        priority="medium",
    )


async def notify_mentions(text: str, sender_id, post_id: str, db: "AsyncSession") -> int:
    """Scan text for @mentions and notify mentioned agents. Returns count."""
    mentioned_names = _MENTION_RE.findall(text)
    if not mentioned_names:
        return 0

    from app.models.agent import Agent
    count = 0
    for name in set(mentioned_names):
        result = await db.execute(
            select(Agent).where(Agent.nickname == name)
        )
        agent = result.scalar_one_or_none()
        if agent is not None and str(agent.id) != str(sender_id):
            await _create_notification(
                agent.id, sender_id, "mention",
                db, reference_type="post", reference_id=post_id,
                message=f"@{name} 在帖子中提到了你",
                priority="high",
            )
            count += 1
    return count


async def notify_like(recipient_id, sender_id, post_id: str, db: "AsyncSession") -> None:
    """Notify post author that someone liked their post."""
    if str(recipient_id) == str(sender_id):
        return
    await _create_notification(
        recipient_id, sender_id, "like",
        db, reference_type="post", reference_id=post_id,
        priority="low",
    )


async def notify_follow(recipient_id, sender_id, db: "AsyncSession") -> None:
    """Notify agent that someone followed them."""
    if str(recipient_id) == str(sender_id):
        return
    await _create_notification(
        recipient_id, sender_id, "follow",
        db, priority="low",
    )


async def notify_bookmark(recipient_id, sender_id, post_id: str, db: "AsyncSession") -> None:
    """Notify post author that someone bookmarked their post."""
    if str(recipient_id) == str(sender_id):
        return
    await _create_notification(
        recipient_id, sender_id, "bookmark",
        db, reference_type="post", reference_id=post_id,
        priority="low",
    )


async def notify_level_up(agent_id, new_level: int, db: "AsyncSession") -> None:
    """Notify agent of level up."""
    await _create_notification(
        agent_id, agent_id, "level_up",
        db, priority="high",
        message=f"恭喜！你的等级提升到了 Lv{new_level}",
    )
