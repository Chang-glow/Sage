from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import config as yaml_config

logger = structlog.get_logger()


async def consolidate_agent_memories(
    agent: Any, db: AsyncSession, llm_caller: Any
) -> None:
    """Evaluate memory fragments for upgrade or discard via memory_consolidation skill.

    Forwards short/long/core memory snapshots to the LLM, then applies its
    to_consolidate / to_discard decisions.  Upgrades follow the config thresholds:

    * short → long:  retrieval_count >= upgrade_retrieval_min (default 3)
    * long  → core:  retrieval_count >= consolidate_retrieval_min (default 10)
                      AND age >= consolidate_days_min (default 180 days)
                      AND importance >= consolidate_importance_min (default 0.85)
    """
    from app.skills.executor import execute

    fragments: list[dict[str, Any]] = agent.solidified_memories or []
    if not fragments:
        return

    mem_cfg = yaml_config.memory
    now = datetime.now(timezone.utc)

    def _format_list(items: list[dict[str, Any]]) -> str:
        if not items:
            return "（无）"
        lines = []
        for m in items:
            lines.append(
                f"  [{m.get('id','?')[:8]}] type={m.get('type','?')} "
                f"importance={m.get('importance',0):.2f} "
                f"retrievals={m.get('retrieval_count',0)} "
                f"content: {m.get('content','')[:80]}"
            )
        return "\n".join(lines)

    short = [f for f in fragments if f.get("type") == "short"]
    long_ = [f for f in fragments if f.get("type") == "long"]
    core = [f for f in fragments if f.get("type") == "core"]

    ctx = {
        "agent_name": getattr(agent, "nickname", "未知"),
        "short_term_memories": _format_list(short),
        "long_term_memories": _format_list(long_),
        "core_memories": _format_list(core),
        "recent_events": "（近期事件由调度系统提供，此处暂空）",
    }

    try:
        result = await execute(
            "memory_consolidation", ctx,
            llm_caller=llm_caller, agent_id=str(agent.id), db=db,
        )
    except Exception:
        logger.warning("memory_consolidation_failed", agent_id=str(agent.id))
        return

    if result.status != "success" or not isinstance(result.parsed, dict):
        return

    to_consolidate: list[str] = result.parsed.get("to_consolidate", []) or []
    to_discard: list[str] = result.parsed.get("to_discard", []) or []

    # Apply upgrades (short → long, long → core) with config thresholds
    upgrade_retrieval_min = getattr(mem_cfg, "upgrade_retrieval_min", 3)
    consolidate_retrieval_min = getattr(mem_cfg, "consolidate_retrieval_min", 10)
    consolidate_days_min = getattr(mem_cfg, "consolidate_days_min", 180)
    consolidate_importance_min = getattr(mem_cfg, "consolidate_importance_min", 0.85)
    upgrade_importance_boost = getattr(mem_cfg, "upgrade_importance_boost", 0.15)

    for frag in fragments:
        fid = frag.get("id", "")
        if fid not in to_consolidate:
            continue

        created_str = frag.get("created_at", "")
        age_days = 0
        try:
            created = datetime.fromisoformat(created_str)
            age_days = (now - created).days
        except (ValueError, TypeError):
            pass

        retrievals = frag.get("retrieval_count", 0)
        importance = frag.get("importance", 0)

        if frag.get("type") == "short" and retrievals >= upgrade_retrieval_min:
            frag["type"] = "long"
            frag["importance"] = min(importance + upgrade_importance_boost, 1.0)
            logger.info("memory_upgraded_short_to_long", fragment_id=fid[:8])

        elif frag.get("type") == "long":
            if (
                retrievals >= consolidate_retrieval_min
                and age_days >= consolidate_days_min
                and importance >= consolidate_importance_min
            ):
                frag["type"] = "core"
                logger.info("memory_upgraded_long_to_core", fragment_id=fid[:8])

    # Apply discards
    agent.solidified_memories = [f for f in fragments if f.get("id") not in to_discard]

    logger.info(
        "memory_consolidation_complete",
        agent_id=str(agent.id),
        total=len(agent.solidified_memories or []),
        consolidated=len(to_consolidate),
        discarded=len(to_discard),
    )


def cleanup_agent_memories(agent: Any) -> list[str]:
    """Remove expired fragments from agent.solidified_memories.

    Retention rules:
    - short (importance < 0.3): short_retention_days_low (3d)
    - short (0.3 <= importance < 0.7): short_retention_days_mid (14d)
    - short (importance >= 0.7): never expire by time
    - long: long_retention_days (90d)
    - core: never expire

    Mutates agent.solidified_memories in place. Returns list of removed fragment ids.
    """
    fragments: list[dict[str, Any]] = agent.solidified_memories or []
    if not fragments:
        return []

    mem_cfg = yaml_config.memory
    low_days = int(getattr(mem_cfg, "short_retention_days_low", 3))
    mid_days = int(getattr(mem_cfg, "short_retention_days_mid", 14))
    long_days = int(getattr(mem_cfg, "long_retention_days", 90))
    now = datetime.now(timezone.utc)

    removed: list[str] = []
    kept: list[dict[str, Any]] = []

    for frag in fragments:
        fid = frag.get("id", "")
        ftype = frag.get("type", "short")
        importance = frag.get("importance", 0)

        if ftype == "core":
            kept.append(frag)
            continue

        created_str = frag.get("created_at", "")
        age_days = 0
        try:
            created = datetime.fromisoformat(created_str)
            age_days = (now - created).days
        except (ValueError, TypeError):
            kept.append(frag)
            continue

        expired = False

        if ftype == "short":
            if importance >= 0.7:
                expired = False
            elif importance >= 0.3:
                expired = age_days > mid_days
            else:
                expired = age_days > low_days
        elif ftype == "long":
            expired = age_days > long_days

        if expired:
            removed.append(fid)
        else:
            kept.append(frag)

    agent.solidified_memories = kept
    return removed


def evict_over_capacity(agent: Any) -> list[str]:
    """Evict lowest-score fragments when short or long pools exceed capacity.

    Score = importance * time_decay, where time_decay = 1 / (1 + age_days / retention_days).
    Lower score = evicted first.

    Mutates agent.solidified_memories in place. Returns list of evicted fragment ids.
    """
    fragments: list[dict[str, Any]] = agent.solidified_memories or []
    if not fragments:
        return []

    mem_cfg = yaml_config.memory
    max_short = int(getattr(mem_cfg, "max_short_fragments", 150))
    max_long = int(getattr(mem_cfg, "max_long_fragments", 50))
    low_days = int(getattr(mem_cfg, "short_retention_days_low", 3))
    mid_days = int(getattr(mem_cfg, "short_retention_days_mid", 14))
    long_ret = int(getattr(mem_cfg, "long_retention_days", 90))
    now = datetime.now(timezone.utc)

    def _score(frag: dict[str, Any]) -> float:
        importance = frag.get("importance", 0)
        created_str = frag.get("created_at", "")
        ftype = frag.get("type", "short")
        try:
            age_days = (now - datetime.fromisoformat(created_str)).days
        except (ValueError, TypeError):
            age_days = 0
        if ftype == "long":
            ref_days = long_ret
        elif importance >= 0.3:
            ref_days = mid_days
        else:
            ref_days = low_days
        time_decay = 1.0 / (1.0 + max(0, age_days) / max(1, ref_days))
        return importance * time_decay

    short_frags = [(f, _score(f)) for f in fragments if f.get("type") == "short"]
    long_frags = [(f, _score(f)) for f in fragments if f.get("type") == "long"]
    other = [f for f in fragments if f.get("type") not in ("short", "long")]

    removed: list[str] = []

    if len(short_frags) > max_short:
        short_frags.sort(key=lambda x: x[1])
        excess = len(short_frags) - max_short
        for f, _ in short_frags[:excess]:
            removed.append(f.get("id", ""))
        short_frags = short_frags[excess:]

    if len(long_frags) > max_long:
        long_frags.sort(key=lambda x: x[1])
        excess = len(long_frags) - max_long
        for f, _ in long_frags[:excess]:
            removed.append(f.get("id", ""))
        long_frags = long_frags[excess:]

    agent.solidified_memories = [f for f, _ in short_frags] + [f for f, _ in long_frags] + other
    return removed


async def decay_all_intimacy(db: AsyncSession) -> int:
    """Reduce intimacy for relationships with last_interaction > 7 days.

    Decay rate: config.memory.decay_rate per day beyond 7.
    Does NOT drop intimacy below -1.0.
    Returns count of decayed relationships.
    """
    from sqlalchemy import select, update

    now = datetime.now(timezone.utc)
    decay_rate = float(yaml_config.memory.decay_rate)
    stale_days = 7

    from app.models.relationship import Relationship

    result = await db.execute(
        select(Relationship).where(
            Relationship.is_archived == False,
            Relationship.last_interaction.isnot(None),
        )
    )
    relationships = result.scalars().all()

    decayed = 0
    for rel in relationships:
        if rel.last_interaction is None:
            continue
        days_since = (now - rel.last_interaction).days
        if days_since > stale_days:
            decay_amount = (days_since - stale_days) * decay_rate
            rel.intimacy = max(-1.0, rel.intimacy - decay_amount)
            decayed += 1

    if decayed > 0:
        await db.commit()

    return decayed


async def archive_cold_relationships(db: AsyncSession) -> int:
    """Archive relationships: intimacy < archive_threshold AND last_interaction > archive_days ago.

    Returns count of archived relationships.
    """
    from sqlalchemy import select

    now = datetime.now(timezone.utc)
    threshold = float(yaml_config.memory.archive_threshold)
    archive_days = int(yaml_config.memory.archive_days)

    from app.models.relationship import Relationship

    result = await db.execute(
        select(Relationship).where(
            Relationship.is_archived == False,
            Relationship.last_interaction.isnot(None),
        )
    )
    relationships = result.scalars().all()

    archived = 0
    for rel in relationships:
        if rel.last_interaction is None:
            continue
        days_since = (now - rel.last_interaction).days
        if rel.intimacy < threshold and days_since > archive_days:
            rel.is_archived = True
            archived += 1

    if archived > 0:
        await db.commit()

    return archived
