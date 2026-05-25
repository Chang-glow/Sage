from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import select

from app.config import config as yaml_config
from app.models.bar import AgentBarLevel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()

_XP_TABLE = {
    "post": 5,
    "reply": 3,
    "liked": 1,
    "login": 1,
    "followed": 2,
    "post_replied": 3,
    "bookmarked": 5,
    "unbookmarked": -5,
    "post_liked": 1,
    "post_featured": 50,
    "post_unfeatured": -50,
}

_CHECKIN_BONUS_MODERATOR = 10
_CHECKIN_BONUS_OWNER = 23

MAX_LEVEL = yaml_config.level.total_levels

_LEVEL_XP_TABLE: list[int] = [
    0,     # Lv1  — 初始
    5,     # Lv2  — 个位数入门
    12,    # Lv3
    30,    # Lv4  — 签到 1 周 + 2 天
    70,    # Lv5
    125,   # Lv6
    180,   # Lv7  — 约签到 1 个月
    300,   # Lv8
    500,   # Lv9
    1200,  # Lv10 — 约半年
    2500,  # Lv11
    4000,  # Lv12
    7000,  # Lv13
    10000, # Lv14 — 传说
    30000, # Lv15 — 满级（3× Lv14）
]


def xp_for_level(level: int) -> int:
    """Cumulative XP required to reach this level (Lv1 = 0 XP)."""
    if level <= 1:
        return 0
    idx = level - 1
    if idx >= len(_LEVEL_XP_TABLE):
        return _LEVEL_XP_TABLE[-1]  # cap at last defined level
    return _LEVEL_XP_TABLE[idx]


async def add_xp(
    agent_id,
    bar_id,
    action: str,
    db: "AsyncSession",
    reference_id: str | None = None,
    amount_override: int | None = None,
) -> int | None:
    """Add XP for an action and return new level if leveled up, else None."""
    if amount_override is not None:
        amount = amount_override
    else:
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


async def perform_checkin(agent_id, bar_id, db: "AsyncSession") -> int | None:
    """Daily check-in for an agent at a bar. Streak-based XP: day 1 = +1, ..., day 7 = +7 (capped).

    Returns new level if leveled up, else None. No-op if already checked in today.
    """
    today = date.today()

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

    # Already checked in today?
    if record.last_checkin_date and record.last_checkin_date.date() == today:
        return None

    # Compute streak
    if record.last_checkin_date and record.last_checkin_date.date() == today - timedelta(days=1):
        streak = min(record.checkin_streak + 1, 7)
    else:
        streak = 1

    record.checkin_streak = streak
    record.last_checkin_date = datetime.now(timezone.utc)

    # XP = streak day (1-7)
    result = await add_xp(agent_id, bar_id, "login", db, amount_override=streak)

    # Moderator/owner daily bonus
    from app.models.bar import Bar, BarMember
    bar_result = await db.execute(select(Bar).where(Bar.id == bar_id))
    bar = bar_result.scalar_one_or_none()
    bonus = 0
    if bar and str(bar.current_owner_id) == str(agent_id):
        bonus = _CHECKIN_BONUS_OWNER
    else:
        member_result = await db.execute(
            select(BarMember).where(
                BarMember.bar_id == bar_id,
                BarMember.agent_id == agent_id,
            )
        )
        member = member_result.scalar_one_or_none()
        if member and member.role == "moderator":
            bonus = _CHECKIN_BONUS_MODERATOR

    if bonus > 0:
        bonus_result = await add_xp(agent_id, bar_id, "login", db, amount_override=bonus)
        return bonus_result or result

    return result


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
