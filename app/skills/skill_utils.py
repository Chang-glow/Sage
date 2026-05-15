from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TYPE_CHECKING

from sqlalchemy import select

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class SkillDefinition:
    skill_id: str
    name: str
    model_type: str  # "主力" | "便宜"
    prompt_template: str
    output_format: str = "JSON"
    output_schema: dict[str, Any] | None = None
    trigger_condition: str = ""
    input_description: str = ""
    notes: str = ""
    source_path: Path | None = None


@dataclass
class SkillResult:
    skill_id: str
    raw_response: str = ""
    parsed: dict[str, Any] | str | None = None
    model: str = ""
    tokens_used: int = 0
    duration_ms: float = 0.0
    status: str = "success"  # success | render_failure | llm_failure | parse_failure
    error: str | None = None


def build_agent_context(agent) -> dict[str, Any]:
    pv = agent.personality_vector or {}
    sorted_traits = sorted(pv.items(), key=lambda x: x[1], reverse=True) if pv else []
    personality_str = "、".join(f"{k}={v:.2f}" for k, v in sorted_traits[:5])

    interests = agent.interests or {}
    if isinstance(interests, dict):
        cats = interests.get("categories", []) or interests.get("interests", []) or []
        interest_str = "、".join(cats[:10]) if cats else "广泛"
    elif isinstance(interests, list):
        interest_str = "、".join(interests[:10]) if interests else "广泛"
    else:
        interest_str = "广泛"

    return {
        "agent_id": str(agent.id),
        "agent_name": agent.nickname,
        "agent_age": agent.age,
        "agent_gender": agent.gender,
        "agent_occupation": agent.occupation or "未知",
        "agent_education": agent.education or "",
        "agent_district": agent.district or "平陵市",
        "agent_personality": personality_str or "普通",
        "agent_interests": interest_str,
    }


def build_post_context(post) -> dict[str, Any]:
    bar_name = ""
    if post.bar and post.bar.name:
        bar_name = post.bar.name
    author_name = ""
    if post.author and post.author.nickname:
        author_name = post.author.nickname

    return {
        "post_id": str(post.id),
        "post_title": post.title,
        "post_content": post.content,
        "post_author": author_name or str(post.author_id),
        "post_bar_name": bar_name,
        "post_author_id": str(post.author_id),
        "post_reply_count": post.reply_count or 0,
    }


import re
from typing import Callable

_MEDIA_PLACEHOLDER_RE = re.compile(r"\{\{media:\s*(image|emoji),\s*([^}]+)\}\}")


async def process_media_placeholders(
    text: str,
    llm_caller: Callable,
    agent_id: str,
) -> str:
    """If text contains {{media:...}} placeholders, call media_generation skill to convert them."""
    if not _MEDIA_PLACEHOLDER_RE.search(text):
        return text

    from app.skills.executor import execute

    try:
        result = await execute("media_generation", {"raw_text": text}, llm_caller=llm_caller, agent_id=agent_id)
    except Exception:
        return text

    if result.status == "success" and isinstance(result.parsed, dict):
        processed = result.parsed.get("processed_text", text)
        return processed if processed else text
    return text


async def build_relationship_context(
    agent_id: uuid.UUID,
    target_id: uuid.UUID,
    db: "AsyncSession",
) -> dict[str, Any]:
    """Query Relationship table for agent→target, return attitude/intimacy/etc."""
    from app.models.relationship import Relationship

    result = await db.execute(
        select(Relationship).where(
            Relationship.agent_id == agent_id,
            Relationship.target_id == target_id,
        )
    )
    rel = result.scalar_one_or_none()
    if rel is None:
        return {
            "relationship_attitude": "中立",
            "relationship_intimacy": 0.0,
            "is_blocked": False,
            "is_archived": False,
            "last_interaction": "从未",
        }
    return {
        "relationship_attitude": rel.attitude or "中立",
        "relationship_intimacy": rel.intimacy or 0.0,
        "is_blocked": rel.is_blocked or False,
        "is_archived": rel.is_archived or False,
        "last_interaction": str(rel.last_interaction) if rel.last_interaction else "从未",
    }
