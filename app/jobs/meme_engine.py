from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import select, update

from app.models.slang import AgentSlang, Slang

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()


async def use_slang_in_text(agent_id, text: str, db: "AsyncSession") -> int:
    """Scan text for known slang slugs, bump personal affinity. Returns count of slangs used."""
    if not text:
        return 0

    # Get all active slangs
    result = await db.execute(
        select(Slang).where(Slang.status == "active")
    )
    all_slangs = result.scalars().all()

    used_count = 0
    for slang in all_slangs:
        if slang.slug in text:
            # Upsert AgentSlang
            existing = await db.execute(
                select(AgentSlang).where(
                    AgentSlang.agent_id == agent_id,
                    AgentSlang.slang_id == slang.id,
                )
            )
            record = existing.scalar_one_or_none()
            if record is not None:
                new_affinity = min(1.0, record.personal_affinity + 0.05)
                await db.execute(
                    update(AgentSlang)
                    .where(AgentSlang.id == record.id)
                    .values(personal_affinity=new_affinity, last_used_at=datetime.now(timezone.utc))
                )
            else:
                db.add(AgentSlang(
                    agent_id=agent_id,
                    slang_id=slang.id,
                    personal_affinity=0.55,
                    last_used_at=datetime.now(timezone.utc),
                ))
            used_count += 1

    if used_count > 0:
        await db.commit()
        logger.info("slang_used", agent_id=str(agent_id), count=used_count)
    return used_count


async def decay_slangs(db: "AsyncSession") -> None:
    """Periodic: decay affinity for slangs not used in 14+ days. Archive if below threshold."""
    now = datetime.now(timezone.utc)

    # Decay agent slangs not used recently
    result = await db.execute(
        select(AgentSlang).where(
            AgentSlang.last_used_at.isnot(None),
            AgentSlang.last_used_at < now.replace(day=now.day - 14),
        )
    )
    stale = result.scalars().all()

    for record in stale:
        new_affinity = max(0.0, record.personal_affinity - 0.05)
        await db.execute(
            update(AgentSlang)
            .where(AgentSlang.id == record.id)
            .values(personal_affinity=new_affinity)
        )

    # Archive slangs with zero usage across all agents
    result2 = await db.execute(
        select(Slang).where(Slang.status == "active")
    )
    active_slangs = result2.scalars().all()

    for slang in active_slangs:
        usage_result = await db.execute(
            select(AgentSlang).where(
                AgentSlang.slang_id == slang.id,
                AgentSlang.personal_affinity > 0.1,
            )
        )
        active_users = usage_result.scalars().all()
        if len(active_users) == 0:
            await db.execute(
                update(Slang)
                .where(Slang.id == slang.id)
                .values(status="archived")
            )
            logger.info("slang_archived", slug=slang.slug)

    await db.commit()


async def get_agent_active_slangs(agent_id, db: "AsyncSession") -> list[dict]:
    """Get agent's active slangs for context injection in content generation."""
    result = await db.execute(
        select(AgentSlang, Slang)
        .join(Slang, AgentSlang.slang_id == Slang.id)
        .where(
            AgentSlang.agent_id == agent_id,
            AgentSlang.personal_affinity >= 0.3,
            Slang.status == "active",
        )
        .order_by(AgentSlang.personal_affinity.desc())
        .limit(20)
    )
    rows = result.all()
    return [
        {"slug": s.slug, "meaning": s.meaning, "affinity": round(a.personal_affinity, 2)}
        for a, s in rows
    ]
