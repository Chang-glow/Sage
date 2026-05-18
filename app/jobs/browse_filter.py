from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

import structlog
from sqlalchemy import select

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()

_BLOCKED_KEYWORDS: set[str] = set()


@dataclass
class BrowseFilterResult:
    post_id: str
    passed: bool
    reason: str  # "blocked_author" | "keyword_blocked" | "low_similarity" | "llm_filter_failed" | "passed"
    similarity_score: float | None = None


async def check_blocklist(
    agent_id: uuid.UUID,
    post_author_id: uuid.UUID,
    db: "AsyncSession",
) -> bool:
    """Return True if the post should be skipped (author is blocked or archived)."""
    from app.models.relationship import Relationship

    result = await db.execute(
        select(Relationship).where(
            Relationship.agent_id == agent_id,
            Relationship.target_id == post_author_id,
        )
    )
    rel = result.scalar_one_or_none()
    if rel is None:
        return False
    if rel.is_blocked or rel.is_archived:
        return True
    return False


def _build_interest_text(agent) -> str:
    interests = agent.interests or {}
    if isinstance(interests, dict):
        cats = interests.get("categories", []) or interests.get("interests", []) or []
        return " ".join(cats)
    if isinstance(interests, list):
        return " ".join(interests)
    return ""


async def _skill_topic_match(
    text_a: str,
    text_b: str,
    comparison_context: str,
    llm_caller: Callable,
    agent_id: str,
    threshold: float,
    db,
) -> tuple[bool, float | None]:
    """Call topic_similarity skill to judge if two texts are about the same topic."""
    from app.skills.executor import execute

    if not text_a.strip() or not text_b.strip():
        return True, None

    ctx = {
        "text_a": text_a[:500],
        "text_b": text_b[:500],
        "comparison_context": comparison_context,
    }

    try:
        result = await execute("topic_similarity", ctx, llm_caller=llm_caller, agent_id=agent_id, db=db)
    except Exception:
        logger.warning("topic_similarity_call_failed", agent_id=agent_id)
        return True, None  # graceful degradation

    if result.status == "success" and isinstance(result.parsed, dict):
        score = result.parsed.get("similarity_score", 0.5)
        is_same = result.parsed.get("is_same_topic", score > threshold)
        final_score = float(score) if score is not None else None
        return is_same, final_score

    return True, None  # fallback: let it through


async def run_browse_filter(
    agent,
    posts: list,
    db: "AsyncSession",
    llm_caller: Callable,
) -> list[BrowseFilterResult]:
    """Run 3-stage browse filter on a batch of posts.

    1. Blocklist check (blocked/archived authors) — pure code
    2. Keyword filter (blocked keywords) — pure code
    3. Topic similarity — calls topic_similarity skill (cheap LLM)
    """
    from app.config import config as yaml_config

    agent_id = uuid.UUID(str(agent.id))
    agent_id_str = str(agent.id)
    threshold = float(yaml_config.browse.interest_similarity_threshold)
    interest_text = _build_interest_text(agent)
    results: list[BrowseFilterResult] = []

    for post in posts:
        post_id = str(post.id)

        # Stage 1: Blocklist check
        author_id = uuid.UUID(str(post.author_id))
        if await check_blocklist(agent_id, author_id, db):
            results.append(BrowseFilterResult(post_id=post_id, passed=False, reason="blocked_author"))
            continue

        # Stage 1.5: Hidden post check
        if getattr(post, "is_hidden", False):
            results.append(BrowseFilterResult(post_id=post_id, passed=False, reason="hidden"))
            continue

        # Stage 2: Keyword filter
        if _BLOCKED_KEYWORDS:
            text = (post.title or "") + " " + (post.content or "")
            if any(kw.lower() in text.lower() for kw in _BLOCKED_KEYWORDS):
                results.append(BrowseFilterResult(post_id=post_id, passed=False, reason="keyword_blocked"))
                continue

        # Stage 3: Topic similarity via skill
        post_text = (post.title or "") + " " + (post.content or "")
        passed, sim = await _skill_topic_match(
            interest_text, post_text, "post_vs_interests",
            llm_caller, agent_id_str, threshold, db,
        )

        reason = "passed" if passed else "low_similarity"
        results.append(BrowseFilterResult(post_id=post_id, passed=passed, reason=reason, similarity_score=sim))

    return results
