from __future__ import annotations

import math
import random
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Callable

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import config as yaml_config
from app.jobs.self_balance import SelfBalanceTracker
from app.models.post import Post, Reply
from app.skills.executor import execute
from app.skills.skill_utils import build_agent_context, build_post_context, build_relationship_context

logger = structlog.get_logger()

_WEIGHTS = yaml_config.reply_weights


def reply_willingness(reply_count_in_post: int) -> float:
    """Reply willingness multiplier based on round number within a post.

    Models natural conversation curve: moderate start → peak at round 2
    (they replied back!) → gradual decay.

    Formula: w(n) = n * exp(-0.6*n) * 1.6  where n = reply_count + 1
    """
    n = reply_count_in_post + 1
    raw = n * math.exp(-0.6 * n) * 1.6
    return min(1.0, max(0.0, raw))


# ─── Data types ───


@dataclass
class ActivationScore:
    component: str
    score: float  # raw score before weighting
    weighted: float = 0.0


@dataclass
class ReplyDecisionResult:
    will_reply: bool
    reason: str
    suggested_tone: str
    active_persona: str
    activation_components: list[ActivationScore] = field(default_factory=list)
    self_balance_adjustment: str | None = None


# ─── Layer computation helpers ───


def _personality_to_activation(personality_vector: dict[str, float] | None) -> float:
    """Layer 1: Map personality traits to baseline interaction tendency."""
    if not personality_vector:
        return 0.5
    # Higher extraversion-related traits → more likely to engage
    social_traits = {
        "peacemaker": 0.7,       # tends to engage constructively
        "people_pleaser": 0.8,   # wants to interact
        "cute_pet": 0.7,         # playful engagement
        "instigator": 0.8,        # likes stirring discussion
        "hothead": 0.75,          # reactive engagement
    }
    # Lower extraversion traits → less likely
    quiet_traits = {
        "spectator": 0.3,         # mostly watches
        "recluse": 0.2,            # minimal interaction
        "truthseeker": 0.5,       # engages when intellectually interested
    }

    score = 0.0
    count = 0
    for trait, val in personality_vector.items():
        if trait in social_traits:
            score += val * social_traits[trait]
        elif trait in quiet_traits:
            score += val * quiet_traits[trait]
        else:
            score += val * 0.5
        count += 1

    return score / max(count, 1)


def _topic_overlap(text_a: str, text_b: str) -> float:
    """Layer 2/3: Character-bigram overlap score between two texts."""
    if not text_a or not text_b:
        return 0.0

    def bigrams(s: str) -> set[str]:
        s = s.lower().strip()
        if len(s) < 2:
            return {s}
        return {s[i:i+2] for i in range(len(s) - 1)}

    ba = bigrams(text_a)
    bb = bigrams(text_b)
    if not ba or not bb:
        return 0.0
    intersection = ba & bb
    return len(intersection) / min(len(ba), len(bb))


def _post_hotness(post: Post) -> float:
    """Layer 4: Post engagement score based on reply_count and flags."""
    score = 0.3  # baseline
    rc = post.reply_count or 0
    if rc > 20:
        score += 0.3
    elif rc > 10:
        score += 0.2
    elif rc > 5:
        score += 0.1
    if post.is_essential:
        score += 0.2
    if post.is_pinned:
        score += 0.15
    return min(score, 1.0)


def _sample_dominant_persona(
    personality_vector: dict[str, float] | None,
    activation_scores: list[ActivationScore],
    balance_tracker: SelfBalanceTracker,
) -> str:
    """Sample the dominant persona based on activation scores + personality + self-balance."""
    if not personality_vector:
        return "balanced"

    # Weight personality traits by their activation contribution
    # Higher-scoring traits get higher probability of being selected
    candidates: list[tuple[str, float]] = []
    for trait, val in personality_vector.items():
        # Poor activation → lower chance to be dominant
        candidate_score = val
        candidates.append((trait, candidate_score))

    candidates.sort(key=lambda x: x[1], reverse=True)

    if not candidates:
        return "balanced"

    # Check diversity: if top persona saturated, force rotation
    top_persona = candidates[0][0]
    if not balance_tracker.check_diversity(top_persona):
        logger.debug("self_balance_rotation", forced_off=top_persona)
        # Pick next best that passes diversity check
        for persona, _ in candidates[1:]:
            if balance_tracker.check_diversity(persona):
                return persona
        # All fail → still return something
        return candidates[1][0] if len(candidates) > 1 else top_persona

    # Weighted random sample from top 3
    top3 = candidates[:3]
    total = sum(s for _, s in top3)
    if total == 0:
        return top3[0][0]
    r = random.random() * total
    cumulative = 0.0
    for persona, score in top3:
        cumulative += score
        if r <= cumulative:
            return persona
    return top3[0][0]


def _compute_activation(
    agent,
    post: Post,
    offline_summary: str,
    post_content_str: str,
) -> list[ActivationScore]:
    """Compute 4-layer weighted activation scores for a post."""
    # Layer 1: Base personality (weight 0.4)
    l1_raw = _personality_to_activation(agent.personality_vector)
    l1 = ActivationScore(
        component="base_personality",
        score=l1_raw,
    )

    # Layer 2: Offline life (weight 0.25)
    l2_raw = _topic_overlap(offline_summary, post_content_str)
    l2 = ActivationScore(
        component="offline_life",
        score=l2_raw,
    )

    # Layer 3: Observed info / interests (weight 0.1)
    interests_text = ""
    agent_interests = agent.interests or {}
    if isinstance(agent_interests, dict):
        cats = agent_interests.get("categories", []) or agent_interests.get("interests", []) or []
        interests_text = " ".join(cats)
    elif isinstance(agent_interests, list):
        interests_text = " ".join(agent_interests)
    l3_raw = _topic_overlap(interests_text, post_content_str)
    l3 = ActivationScore(
        component="observed_info",
        score=l3_raw,
    )

    # Layer 4: Post content / hotness (weight 0.25)
    l4_raw = _post_hotness(post)
    l4 = ActivationScore(
        component="post_content",
        score=l4_raw,
    )

    # Apply weights
    l1.weighted = l1.score * _WEIGHTS.base_personality
    l2.weighted = l2.score * _WEIGHTS.offline_life
    l3.weighted = l3.score * _WEIGHTS.observed_info
    l4.weighted = l4.score * _WEIGHTS.post_content

    # Normalize
    total = l1.weighted + l2.weighted + l3.weighted + l4.weighted
    if total > 0:
        l1.weighted /= total
        l2.weighted /= total
        l3.weighted /= total
        l4.weighted /= total

    return [l1, l2, l3, l4]


# ─── Main pipeline functions ───


async def decide_reply(
    agent,
    post: Post,
    offline_summary: str,
    db: AsyncSession,
    llm_caller: Callable,
    balance_tracker: SelfBalanceTracker,
    daily_reply_count: int = 0,
    max_daily_replies: int = 15,
    reply_count_in_post: int = 0,
    in_flow: bool = False,
) -> ReplyDecisionResult:
    """Full reply decision pipeline: activation → self-balance → persona → LLM decision."""
    agent_id = str(agent.id)
    post_content_str = (post.title or "") + " " + (post.content or "")

    # 1. Compute 4-layer activation
    activation = _compute_activation(agent, post, offline_summary, post_content_str)

    # 2. Apply self-balancing
    saturation_check = None
    top_component = max(activation, key=lambda a: a.weighted)
    if balance_tracker.compute_saturation(top_component.component) > 0.7:
        saturation_check = top_component.component
        # Down-weight saturated components
        for a in activation:
            if balance_tracker.compute_saturation(a.component) > 0.7:
                a.weighted *= 0.5

    # 3. Sample dominant persona
    active_persona = _sample_dominant_persona(agent.personality_vector, activation, balance_tracker)

    # 4. Build context for reply_decision skill
    rel_ctx = await build_relationship_context(
        uuid.UUID(agent_id), uuid.UUID(str(post.author_id)), db
    )
    base_ctx = build_agent_context(agent)

    ctx = {
        **base_ctx,
        "agent_personality": base_ctx.get("agent_personality", "普通"),
        "active_persona": active_persona,
        "offline_summary": offline_summary,
        "post_title": post.title or "",
        "post_content": post_content_str,
        "post_author": rel_ctx.get("relationship_attitude", "中立"),
        "relationship_attitude": rel_ctx.get("relationship_attitude", "中立"),
        "relationship_intimacy": rel_ctx.get("relationship_intimacy", 0.0),
        "recent_reply_count": str(daily_reply_count),
        "max_daily_replies": str(max_daily_replies),
    }

    # Fix: post_author should be the author's name, not relationship_attitude
    if hasattr(post, 'author') and post.author:
        ctx["post_author"] = post.author.nickname

    # Compute reply willingness (skip in flow — flow is deep engagement)
    if not in_flow:
        willingness = reply_willingness(reply_count_in_post)
        ctx["reply_willingness"] = round(willingness, 3)
        ctx["reply_round_in_post"] = reply_count_in_post + 1

    # 5. Call reply_decision skill
    result = await execute("reply_decision", ctx, llm_caller=llm_caller, agent_id=agent_id, db=db)

    will_reply = False
    reason = "skill_call_failed"
    suggested_tone = "中立"

    if result.status == "success" and isinstance(result.parsed, dict):
        will_reply = result.parsed.get("will_reply", False)
        reason = result.parsed.get("reason", "")
        suggested_tone = result.parsed.get("suggested_tone", "中立")

    # 6. Record decision
    decision = ReplyDecisionResult(
        will_reply=will_reply,
        reason=reason,
        suggested_tone=suggested_tone,
        active_persona=active_persona,
        activation_components=activation,
        self_balance_adjustment=saturation_check,
    )
    balance_tracker.record_decision(active_persona, top_component.component)

    return decision


async def generate_reply(
    agent,
    post: Post,
    decision: ReplyDecisionResult,
    db: AsyncSession,
    llm_caller: Callable,
) -> dict | None:
    """Generate reply content using the main model and persist to DB."""
    agent_id = str(agent.id)

    # 1. Fetch top 10 existing replies
    replies_result = await db.execute(
        select(Reply)
        .where(Reply.post_id == post.id)
        .order_by(Reply.created_at.desc())
        .limit(10)
    )
    recent_replies = replies_result.scalars().all()
    recent_replies_str = "\n".join(
        f"- {r.author.nickname if r.author else '匿名'}: {r.content[:100]}"
        for r in recent_replies
    ) if recent_replies else "（暂无回复）"

    # 2. Fetch agent's personal slangs (via plugin manager)
    from app.plugins import plugin_manager
    plugin_ctx = await plugin_manager.gather_context(str(agent.id), db)
    personal_slangs = plugin_ctx.get("personal_slangs", "")

    # 3. Build relationship context
    rel_ctx = await build_relationship_context(
        uuid.UUID(agent_id), uuid.UUID(str(post.author_id)), db
    )
    base_ctx = build_agent_context(agent)

    ctx = {
        **base_ctx,
        "agent_personality": base_ctx.get("agent_personality", "普通"),
        "active_persona": decision.active_persona,
        "suggested_tone": decision.suggested_tone,
        "post_title": post.title or "",
        "post_content": (post.title or "") + " " + (post.content or ""),
        "post_author": "",
        "recent_replies": recent_replies_str,
        "relationship_attitude": rel_ctx.get("relationship_attitude", "中立"),
        "relationship_intimacy": rel_ctx.get("relationship_intimacy", 0.0),
        "personal_slangs": personal_slangs,
    }

    if hasattr(post, 'author') and post.author:
        ctx["post_author"] = post.author.nickname

    # 4. Call reply_generation skill
    result = await execute("reply_generation", ctx, llm_caller=llm_caller, agent_id=agent_id, db=db)

    if result.status != "success" or not isinstance(result.parsed, dict):
        logger.warning("reply_generation_failed", agent_id=agent_id, status=result.status)
        return None

    content = result.parsed.get("content", "")
    if not content.strip():
        logger.warning("reply_generation_empty", agent_id=agent_id)
        return None

    # Process media placeholders
    from app.skills.skill_utils import process_media_placeholders
    content = await process_media_placeholders(content, llm_caller, agent_id)

    # stealth_mode: no image posting — strip [img: ...] placeholders
    if agent.stealth_mode:
        import re
        content = re.sub(r'\[img:\s*[^\]]*\]', '', content).strip()

    # 5. Insert Reply record
    reply = Reply(
        post_id=post.id,
        author_id=agent.id,
        content=content,
    )
    db.add(reply)
    await db.flush()
    reply_id = reply.id
    post_id = str(post.id)
    post_id_uuid = post.id
    agent_id_uuid = agent.id
    bar_id = getattr(post, "bar_id", None)
    post_author_id_val = getattr(post, "author_id", None)

    # 6. Update post.reply_count
    await db.execute(
        update(Post).where(Post.id == post.id).values(reply_count=Post.reply_count + 1)
    )

    await db.commit()

    from app.engine.data_integrity import verify_insert
    from app.models.post import Reply as ReplyModel
    await verify_insert(db, ReplyModel, reply_id)

    logger.info("reply_generated", agent_id=agent_id, post_id=post_id,
                reply_id=str(reply_id), tone=decision.suggested_tone)

    # Track slang usage (via plugin manager)
    from app.plugins import plugin_manager
    await plugin_manager.post_content(agent_id, content, db)

    # Adjust social relationship
    from app.jobs.social_engine import adjust_after_reply
    if post_author_id_val and str(post_author_id_val) != agent_id:
        await adjust_after_reply(agent_id_uuid, post_author_id_val, decision.suggested_tone, db)

    # Notifications
    from app.jobs.notification_engine import notify_reply, notify_mentions
    if post_author_id_val and str(post_author_id_val) != agent_id:
        await notify_reply(post_author_id_val, agent_id_uuid, post_id, db)
    await notify_mentions(content, agent_id_uuid, post_id, db)

    # Level: add reply XP
    from app.jobs.level_engine import add_xp
    if bar_id:
        await add_xp(agent_id_uuid, bar_id, "reply", db)

    # Level: post author gets XP for being replied to
    if post_author_id_val and str(post_author_id_val) != agent_id and bar_id:
        await add_xp(post_author_id_val, bar_id, "post_replied", db, reference_id=post_id)

    return {
        "reply_id": str(reply_id),
        "content": content,
        "tone": decision.suggested_tone,
    }


async def count_today_replies(agent, db: AsyncSession) -> int:
    """Count how many replies this agent made today."""
    today = date.today()
    result = await db.execute(
        select(Reply).where(
            Reply.author_id == agent.id,
            Reply.created_at >= datetime(today.year, today.month, today.day, tzinfo=timezone.utc),
        )
    )
    return len(result.scalars().all())
