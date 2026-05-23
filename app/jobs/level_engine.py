from __future__ import annotations

import math
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
    "post": 10,
    "reply": 3,
    "liked": 1,
    "login": 1,
    "followed": 2,
    "post_replied": 1,
}

MAX_LEVEL = yaml_config.level.total_levels

# Daily reply XP tracking: agent_id → {date_str: total_xp}
_daily_reply_xp: dict[str, dict[str, int]] = {}

# Post-author reply XP tracking: post_id → {date_str: total_xp}
_daily_post_author_xp: dict[str, dict[str, int]] = {}


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

    # Enforce daily reply XP cap
    if action == "reply":
        today_str = str(date.today())
        aid = str(agent_id)
        day_counts = _daily_reply_xp.setdefault(aid, {})
        today_xp = day_counts.get(today_str, 0)
        max_per_day = yaml_config.level.max_replies_exp_per_day
        if today_xp >= max_per_day:
            return None
        day_counts[today_str] = today_xp + amount

    # Enforce daily post-author reply XP cap (per post, per day)
    if action == "post_replied" and reference_id:
        today_str = str(date.today())
        pid = str(reference_id)
        day_counts = _daily_post_author_xp.setdefault(pid, {})
        today_xp = day_counts.get(today_str, 0)
        max_per_day = yaml_config.level.post_reply_exp_cap_per_day
        if today_xp >= max_per_day:
            return None
        day_counts[today_str] = today_xp + amount

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
    return await add_xp(agent_id, bar_id, "login", db, amount_override=streak)


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
