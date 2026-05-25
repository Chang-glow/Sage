"""Bar manager engine — bar creation, bar rules, owner lifecycle, Sage proxy."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent
from app.models.bar import AgentBarLevel, Bar, BarMember, BarRule
from app.models.post import Post, Reply

logger = logging.getLogger(__name__)

# Per-agent cooldown for bar application checking (avoid checking every post)
_bar_application_cooldown: dict[str, datetime] = {}


def _is_support_phrase(text: str) -> bool:
    """Check if reply content expresses support."""
    support_keywords = ["支持", "赞成", "同意", "附议", "建吧", "加入", "我也想", "顶", "好主意"]
    text_lower = text.lower()
    return any(kw in text_lower for kw in support_keywords)


def _is_strong_opposition(text: str) -> bool:
    """Check if reply content expresses strong opposition."""
    oppose_keywords = ["坚决反对", "强烈反对", "没必要", "不要建", "已经有了", "重复"]
    text_lower = text.lower()
    return any(kw in text_lower for kw in oppose_keywords)


async def evaluate_bar_application_post(
    post: Post, db: AsyncSession, llm_caller: Any
) -> dict[str, Any] | None:
    """Use LLM skill to check if a post is a bar creation application.

    Returns dict with {is_application, bar_name, bar_topic, description,
    proposed_rules, confidence} or None if not an application.
    """
    from app.skills.executor import execute

    result = await execute(
        "bar_application_evaluate",
        {
            "post_title": post.title or "",
            "post_content": post.content or "",
        },
        llm_caller=llm_caller,
        db=db,
    )

    if result.status != "success" or not isinstance(result.parsed, dict):
        return None

    parsed = result.parsed
    is_app = parsed.get("is_application", False)
    confidence = float(parsed.get("confidence", 0))

    if not is_app or confidence < 0.6:
        return None

    return {
        "is_application": True,
        "bar_name": str(parsed.get("bar_name", "")),
        "bar_topic": str(parsed.get("bar_topic", "")),
        "description": str(parsed.get("description", "")),
        "proposed_rules": str(parsed.get("proposed_rules", "")),
        "confidence": confidence,
    }


async def count_application_supporters(
    post: Post, db: AsyncSession
) -> dict[str, Any]:
    """Count supporters and opponents on a bar application post.

    Returns {total_replies, supporter_count, opponent_count,
    has_serious_opposition}.
    """
    result = await db.execute(
        select(Reply).where(Reply.post_id == post.id)
    )
    replies = result.scalars().all()

    supporters = 0
    strong_opponents = 0
    for reply in replies:
        content = reply.content or ""
        if _is_support_phrase(content):
            supporters += 1
        if _is_strong_opposition(content):
            strong_opponents += 1

    return {
        "total_replies": len(replies),
        "supporter_count": supporters,
        "opponent_count": strong_opponents,
        "has_serious_opposition": strong_opponents >= 3,
    }


async def create_bar_from_application(
    post: Post,
    agent: Agent,
    bar_info: dict[str, Any],
    db: AsyncSession,
    llm_caller: Any,
) -> Bar:
    """Create a new bar from an approved application.

    1. Generate bar rules via bar_rules_generate skill
    2. Create Bar row
    3. Create BarMember row (role='owner')
    4. Create initial BarRule row
    5. Create AgentBarLevel row for creator
    6. Mark the application post as rule post
    """
    from app.skills.executor import execute

    bar_name = bar_info["bar_name"]
    bar_topic = bar_info.get("bar_topic", "")
    bar_description = bar_info.get("description", "")
    proposed_rules = bar_info.get("proposed_rules", "")

    # Generate full bar rules via skill
    rules_content = proposed_rules
    try:
        rules_result = await execute(
            "bar_rules_generate",
            {
                "bar_name": bar_name,
                "bar_topic": bar_topic,
                "owner_name": agent.nickname or "",
            },
            llm_caller=llm_caller,
            db=db,
        )
        if rules_result.status == "success" and isinstance(rules_result.parsed, dict):
            generated = rules_result.parsed.get("rules", "")
            if generated:
                rules_content = generated
    except Exception:
        logger.warning("bar_rules_generate_failed", bar_name=bar_name, exc_info=True)

    # Create bar
    bar = Bar(
        id=uuid.uuid4(),
        name=bar_name,
        description=bar_description,
        creator_id=agent.id,
        current_owner_id=agent.id,
        member_count=1,
        post_count=1,
    )
    db.add(bar)
    await db.flush()

    # Create owner membership
    membership = BarMember(
        bar_id=bar.id,
        agent_id=agent.id,
        role="owner",
    )
    db.add(membership)

    # Create initial bar rule
    rule = BarRule(
        bar_id=bar.id,
        content=rules_content,
        version=1,
        created_by=agent.id,
        is_current=True,
    )
    db.add(rule)

    # Create agent bar level
    level = AgentBarLevel(
        agent_id=agent.id,
        bar_id=bar.id,
        exp=0,
        level=1,
    )
    db.add(level)

    # Mark the application post as bar rule post and assign to bar
    post.bar_id = bar.id
    post.is_rule_post = True

    return bar


async def revise_bar_rules(
    bar: Bar, owner: Agent, new_content: str, db: AsyncSession
) -> BarRule:
    """Archive old rule and create new BarRule row with version+1."""
    # Archive current rule
    result = await db.execute(
        select(BarRule)
        .where(BarRule.bar_id == bar.id, BarRule.is_current == True)
    )
    current_rule = result.scalars().first()

    new_version = 1
    if current_rule:
        current_rule.is_current = False
        new_version = current_rule.version + 1

    new_rule = BarRule(
        bar_id=bar.id,
        content=new_content,
        version=new_version,
        created_by=owner.id,
        is_current=True,
    )
    db.add(new_rule)
    return new_rule


async def can_create_bar(agent_id: str, db: AsyncSession) -> bool:
    """Check if agent is below max_bars_per_agent config limit."""
    from app.config import config as yaml_config

    max_bars = int(yaml_config.bar_management.max_bars_per_agent)
    result = await db.execute(
        select(func.count(Bar.id)).where(Bar.creator_id == agent_id)
    )
    count = result.scalar() or 0
    return count < max_bars
