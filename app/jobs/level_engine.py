from __future__ import annotations

import math
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import select

from app.models.bar import AgentBarLevel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()

_XP_TABLE = {
    "post": 10,
    "reply": 3,
    "liked": 1,
    "login": 1,
    "followed": 2,
}

MAX_LEVEL = 15


def xp_for_level(level: int) -> int:
    """Cumulative XP required to reach this level (starting from Lv1 at 0 XP)."""
    if level <= 1:
        return 0
    if level >= MAX_LEVEL:
        return 50000
    return int(100 * ((level - 1) ** 1.6))


async def add_xp(
    agent_id,
    bar_id,
    action: str,
    db: "AsyncSession",
) -> int | None:
    """Add XP for an action and return new level if leveled up, else None."""
    amount = _XP_TABLE.get(action)
    if amount is None:
        logger.warning("unknown_xp_action", action=action)
        return None

    result = await db.execute(
        select(AgentBarLevel).where(
            AgentBarLevel.agent_id == agent_id,
            AgentBarLevel.bar_id == bar_id,
        )
    )
    record = result.scalar_one_or_none()
    if record is None:
        record = AgentBarLevel(agent_id=agent_id, bar_id=bar_id, exp=0, level=1)
        db.add(record)
        await db.flush()

    old_level = record.level
    record.exp += amount

    # Check level up
    new_level = old_level
    while new_level < MAX_LEVEL and record.exp >= xp_for_level(new_level + 1):
        new_level += 1

    if new_level > old_level:
        record.level = new_level
        await db.commit()
        logger.info("level_up", agent_id=str(agent_id), bar_id=str(bar_id),
                    old_level=old_level, new_level=new_level, total_xp=record.exp)

        from app.jobs.notification_engine import notify_level_up
        await notify_level_up(agent_id, new_level, db)
        return new_level

    await db.commit()
    return None


async def get_agent_level(agent_id, bar_id, db: "AsyncSession") -> tuple[int, int, int]:
    """Return (level, exp, xp_to_next_level)."""
    result = await db.execute(
        select(AgentBarLevel).where(
            AgentBarLevel.agent_id == agent_id,
            AgentBarLevel.bar_id == bar_id,
        )
    )
    record = result.scalar_one_or_none()
    if record is None:
        return 1, 0, xp_for_level(2)
    current = record.level
    if current >= MAX_LEVEL:
        return current, record.exp, 0
    xp_next = xp_for_level(current + 1) - record.exp
    return record.level, record.exp, max(xp_next, 1)
