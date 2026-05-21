from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, TYPE_CHECKING

import structlog
from sqlalchemy import select, update

from app.config import config as yaml_config
from app.models.post import Post, Reply
from app.skills.executor import execute
from app.skills.skill_utils import build_agent_context

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()

_FLOW_CONFIG = yaml_config.flow


async def _skill_topic_match(
    text_a: str,
    text_b: str,
    llm_caller: Callable,
    agent_id: str,
    db,
) -> float:
    """Call topic_similarity skill and return similarity score."""
    if not text_a.strip() or not text_b.strip():
        return 0.0

    ctx = {
        "text_a": text_a[:500],
        "text_b": text_b[:500],
        "comparison_context": "reply_vs_reply",
    }

    try:
        result = await execute("topic_similarity", ctx, llm_caller=llm_caller, agent_id=agent_id, db=db)
    except Exception:
        logger.warning("flow_topic_similarity_failed", agent_id=agent_id)
        return 0.0

    if result.status == "success" and isinstance(result.parsed, dict):
        return float(result.parsed.get("similarity_score", 0.0))
    return 0.0


# ─── Flow session data types ───


@dataclass
class FlowSession:
    session_id: str
    agent_id: str
    flow_type: str  # "interactive" | "spontaneous"
    post_id: str | None = None
    other_agent_id: str | None = None
    urge_type: str | None = None
    round: int = 0
    max_rounds: int = 10
    consecutive_no_desire: int = 0
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    is_active: bool = True


class FlowSessionStore:
    """In-memory store of active flow sessions, keyed by agent_id."""

    _sessions: dict[str, FlowSession] = {}
    _daily_count: dict[str, int] = {}  # agent_id → count today

    @classmethod
    def can_start_session(cls, agent_id: str) -> bool:
        max_per_day = int(_FLOW_CONFIG.max_sessions_per_day)
        return cls._daily_count.get(agent_id, 0) < max_per_day

    @classmethod
    def start_session(cls, session: FlowSession) -> None:
        cls._sessions[session.agent_id] = session
        cls._daily_count[session.agent_id] = cls._daily_count.get(session.agent_id, 0) + 1
        logger.info("flow_session_started", agent_id=session.agent_id,
                    flow_type=session.flow_type, session_id=session.session_id)

    @classmethod
    def get_active(cls, agent_id: str) -> FlowSession | None:
        session = cls._sessions.get(agent_id)
        if session and session.is_active:
            return session
        return None

    @classmethod
    def end_session(cls, agent_id: str) -> None:
        session = cls._sessions.pop(agent_id, None)
        if session:
            session.is_active = False
            logger.info("flow_session_ended", agent_id=agent_id,
                       rounds=session.round, flow_type=session.flow_type)

    @classmethod
    def increment_round(cls, agent_id: str) -> None:
        session = cls._sessions.get(agent_id)
        if session:
            session.round += 1

    @classmethod
    def increment_no_desire(cls, agent_id: str) -> None:
        session = cls._sessions.get(agent_id)
        if session:
            session.consecutive_no_desire += 1

    @classmethod
    def reset_no_desire(cls, agent_id: str) -> None:
        session = cls._sessions.get(agent_id)
        if session:
            session.consecutive_no_desire = 0


# ─── Interactive flow ───


def _get_real_value(val):
    """Unwrap SQLAlchemy instrumented attributes or proxy objects."""
    # Handle InstrumentedAttribute, Column, etc.
    type_name = type(val).__name__
    if type_name.startswith('Instrumented') or type_name == 'Column':
        return None
    return val


async def check_interactive_flow_trigger(
    agent_id: str,
    post: Post,
    last_reply_content: str,
    previous_reply_content: str,
    llm_caller: Callable,
    db,
) -> bool:
    """Detect if interactive flow should start.

    Conditions:
    1. Topic similarity between consecutive replies > threshold (0.8)
    2. Agent hasn't exceeded daily session cap
    3. Agent doesn't have an active flow session
    """
    if FlowSessionStore.get_active(agent_id) is not None:
        return False
    if not FlowSessionStore.can_start_session(agent_id):
        return False
    if not last_reply_content or not previous_reply_content:
        return False

    sim = await _skill_topic_match(last_reply_content, previous_reply_content, llm_caller, agent_id, db)
    threshold = float(_FLOW_CONFIG.interactive_trigger_similarity)
    return sim > threshold


async def run_interactive_flow_round(
    agent,
    post: Post,
    other_agent,
    session: FlowSession,
    db: "AsyncSession",
    llm_caller: Callable,
) -> dict | None:
    """Execute one round of interactive flow."""
    agent_id = str(agent.id)

    # Build conversation history from recent replies
    replies_result = await db.execute(
        select(Reply)
        .where(Reply.post_id == post.id)
        .order_by(Reply.created_at.desc())
        .limit(20)
    )
    all_replies = list(replies_result.scalars().all())
    all_replies.reverse()  # chronological order
    conversation = "\n".join(
        f"{r.author.nickname if r.author else '匿名'}: {r.content}"
        for r in all_replies
    )

    ctx = {
        **build_agent_context(agent),
        "agent_personality": build_agent_context(agent).get("agent_personality", "普通"),
        "other_agent_name": other_agent.nickname if other_agent else "匿名",
        "conversation_history": conversation,
        "flow_round": str(session.round + 1),
        "max_rounds": str(session.max_rounds),
    }

    result = await execute("flow_interaction", ctx, llm_caller=llm_caller, agent_id=agent_id, db=db)

    if result.status != "success" or not isinstance(result.parsed, dict):
        return None

    should_continue = result.parsed.get("should_continue", False)
    reply_content = result.parsed.get("reply_content", "")
    tone = result.parsed.get("tone", "中立")

    if not reply_content.strip():
        should_continue = False

    if should_continue:
        FlowSessionStore.increment_round(agent_id)
        FlowSessionStore.reset_no_desire(agent_id)
    else:
        FlowSessionStore.increment_no_desire(agent_id)

    # Check exit conditions
    flow_ended = False
    exit_no_desire = int(_FLOW_CONFIG.exit_rounds_no_desire)
    if session.consecutive_no_desire >= exit_no_desire:
        logger.info("flow_exit_no_desire", agent_id=agent_id, consecutive=session.consecutive_no_desire)
        FlowSessionStore.end_session(agent_id)
        flow_ended = True
    elif session.round >= session.max_rounds:
        logger.info("flow_exit_max_rounds", agent_id=agent_id, rounds=session.round)
        FlowSessionStore.end_session(agent_id)
        flow_ended = True

    if reply_content.strip():
        reply = Reply(
            post_id=post.id,
            author_id=agent.id,
            content=reply_content,
        )
        db.add(reply)
        await db.execute(
            update(Post).where(Post.id == post.id).values(reply_count=Post.reply_count + 1)
        )
        await db.commit()

        # Track slang usage & adjust social relationship
        from app.plugins import plugin_manager
        from app.jobs.social_engine import adjust_after_reply
        await plugin_manager.post_content(str(agent.id), reply_content, db)
        post_author_id = getattr(post, "author_id", None)
        if post_author_id and str(post_author_id) != agent_id:
            await adjust_after_reply(agent.id, post_author_id, tone, db)

        # Notifications
        from app.jobs.notification_engine import notify_reply, notify_mentions
        if post_author_id and str(post_author_id) != agent_id:
            await notify_reply(post_author_id, agent.id, str(post.id), db)
        await notify_mentions(reply_content, agent.id, str(post.id), db)

        # Level: add reply XP
        from app.jobs.level_engine import add_xp
        bar_id = getattr(post, "bar_id", None)
        if bar_id:
            await add_xp(agent.id, bar_id, "reply", db)

        # Flow ended: call follow_hook directly (doesn't go through BrowseHook loop)
        if flow_ended:
            try:
                from app.jobs.agent_lifecycle import _follow_hook
                await _follow_hook(agent, post, None, {"content": reply_content}, db, llm_caller)
            except Exception:
                pass

        return {"reply_id": str(reply.id), "content": reply_content, "tone": tone}

    return None


# ─── Spontaneous flow ───


async def check_spontaneous_flow_trigger(
    agent_id: str,
    urge_type: str,
    urge_intensity: float,
) -> bool:
    """Check if spontaneous flow should start.

    Conditions:
    1. urge_intensity > threshold (0.7)
    2. urge_type is suitable for long-form creation
    3. Under daily session cap
    4. No active flow session
    """
    if FlowSessionStore.get_active(agent_id) is not None:
        return False
    if not FlowSessionStore.can_start_session(agent_id):
        return False

    threshold = float(_FLOW_CONFIG.spontaneous_trigger_intensity)
    if urge_intensity <= threshold:
        return False

    # Long-form urge types
    long_form_types = {"life_share", "rant", "discussion", "game_log", "reaction", "news_reaction"}
    if urge_type not in long_form_types:
        return False

    return True


async def run_spontaneous_flow(
    agent,
    offline_summary: str,
    urge_type: str,
    urge_intensity: float,
    session: FlowSession,
    db: "AsyncSession",
    llm_caller: Callable,
) -> list[dict]:
    """Execute spontaneous flow: 3-6 rounds of long-form content creation."""
    agent_id = str(agent.id)
    created_posts: list[dict] = []
    previous_rounds_text = ""

    for round_num in range(1, session.max_rounds + 1):
        ctx = {
            **build_agent_context(agent),
            "agent_personality": build_agent_context(agent).get("agent_personality", "普通"),
            "urge_type": urge_type,
            "inspiration": offline_summary,
            "previous_rounds": previous_rounds_text or "（第一轮）",
            "flow_round": str(round_num),
            "max_rounds": str(session.max_rounds),
        }

        result = await execute("flow_creation", ctx, llm_caller=llm_caller, agent_id=agent_id, db=db)

        if result.status != "success" or not isinstance(result.parsed, dict):
            break

        title = result.parsed.get("title", f"无题{round_num}")
        content = result.parsed.get("content", "")
        is_final = result.parsed.get("is_final_round", False)

        if content.strip():
            from app.skills.skill_utils import process_media_placeholders
            content = await process_media_placeholders(content, llm_caller, agent_id)

            post = Post(
                author_id=agent.id,
                title=title[:200],
                content=content,
                urge_type=urge_type,
            )
            db.add(post)
            await db.commit()
            created_posts.append({
                "post_id": str(post.id),
                "title": title,
                "content": content,
            })
            previous_rounds_text += f"\n第{round_num}轮: {title}\n{content[:200]}..."

            from app.plugins import plugin_manager
            await plugin_manager.post_content(str(agent.id), content, db)

            logger.info("spontaneous_flow_post", agent_id=agent_id, round=round_num, post_id=str(post.id))

        if is_final or round_num >= session.max_rounds:
            break

    FlowSessionStore.end_session(agent_id)
    return created_posts
