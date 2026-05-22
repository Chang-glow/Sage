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
