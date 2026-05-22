from __future__ import annotations

import asyncio
import random
import uuid
from datetime import date, datetime, timezone
from typing import Callable

import structlog
from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import config as yaml_config
from app.jobs.concurrency import get_agent_semaphore
from app.models.agent import ActivityLog, Agent, AgentDailySchedule
from app.models.bar import AgentBarLevel, Bar, BarMember
from app.models.notification import Notification
from app.models.post import Post, Reply
from app.engine.browse_hooks import browse_hook_registry
from app.skills.executor import execute
from app.skills.skill_utils import build_agent_context, build_post_context, build_relationship_context

logger = structlog.get_logger()

_UTC8 = timezone.utc  # 简化处理，实际 UTC+8 偏移在时间解析时处理


def _parse_time(t_str: str) -> tuple[int, int]:
    """'HH:MM' → (hour, minute)"""
    h, m = t_str.split(":")
    return int(h), int(m)


def _time_in_window(now_h: int, now_m: int, start: str, end: str) -> bool:
    """检查当前时间是否在 [start, end) 窗口内（支持跨午夜）"""
    sh, sm = _parse_time(start)
    eh, em = _parse_time(end)
    now = now_h * 60 + now_m
    s_val = sh * 60 + sm
    e_val = eh * 60 + em

    if s_val <= e_val:
        return s_val <= now < e_val
    else:
        # 跨午夜窗口，如 22:00-02:00
        return now >= s_val or now < e_val


def should_wake(agent: Agent, schedule, now: datetime) -> bool:
    """判断 Agent 是否应该在当前时间被唤醒"""
    # 已经在线的跳过
    if agent.is_online:
        return False

    # 非活跃状态跳过
    if agent.status != "active":
        return False

    # 检查 active_windows
    active_windows = schedule.active_windows if schedule else None
    if not active_windows:
        return False

    # 转换为 UTC+8
    local_h = (now.hour + 8) % 24
    local_m = now.minute
    weekday = now.strftime("%A").lower()[:3]
    is_weekend = weekday in ("sat", "sun")

    # 找到匹配的窗口
    matching_weight = None
    for win in active_windows:
        day = win.get("day", "weekday")
        if day == "weekday" and is_weekend:
            continue
        if day == "weekend" and not is_weekend:
            continue
        if _time_in_window(local_h, local_m, win["start"], win["end"]):
            matching_weight = win.get("weight", 1.0)
            break

    if matching_weight is None:
        return False

    # 概率判定
    threshold = yaml_config.scheduler.wake_probability_threshold
    probability = matching_weight * random.uniform(0.7, 1.0)
    return probability > threshold


async def _log_activity(db: AsyncSession, agent_id, event_type: str, details: dict | None = None):
    log = ActivityLog(agent_id=agent_id, event_type=event_type, details=details)
    db.add(log)


async def run_online_flow(
    agent: Agent,
    db: AsyncSession,
    llm_caller: Callable,
) -> None:
    timeout = yaml_config.scheduler.agent_online_timeout_seconds
    agent_id_str = str(agent.id)
    agent_uuid = agent.id

    async with get_agent_semaphore():
        try:
            await asyncio.wait_for(
                _run_online_flow_inner(agent, db, llm_caller),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            logger.warning("agent_online_timeout", agent_id=agent_id_str, timeout_seconds=timeout)
            await _log_activity(db, agent_uuid, "timeout", {"timeout_seconds": timeout})
            await db.execute(
                update(Agent).where(Agent.id == agent_uuid).values(is_online=False)
            )
            await db.commit()
        except Exception:
            logger.exception("agent_online_flow_error", agent_id=agent_id_str)
            await db.execute(
                update(Agent).where(Agent.id == agent_uuid).values(is_online=False)
            )
            await db.commit()


async def _run_online_flow_inner(
    agent: Agent,
    db: AsyncSession,
    llm_caller: Callable,
) -> None:
    agent_id = str(agent.id)
    agent_uuid = agent.id
    agent_nickname = agent.nickname

    # Mark online
    await db.execute(
        update(Agent).where(Agent.id == agent_uuid).values(is_online=True, last_online=datetime.now(timezone.utc))
    )
    await _log_activity(db, agent_uuid, "wake")
    await db.commit()

    logger.info("agent_wake", agent_id=agent_id, nickname=agent_nickname)

    # Step 1: Offline summary
    ctx = build_agent_context(agent)
    ctx["current_time"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    ctx["agent_personality"] = _describe_personality(agent)
    ctx["life_history_sample"] = _life_history_sample(agent)
    ctx["recent_interactions"] = "暂无新互动"

    try:
        result = await execute("offline_summary", ctx, llm_caller=llm_caller, agent_id=agent_id, db=db)
        if result.status == "success" and isinstance(result.parsed, dict):
            summary = result.parsed.get("summary", "")
            urge_type = result.parsed.get("urge_type")
            urge_intensity = result.parsed.get("urge_intensity", 0.0)
            logger.info("offline_summary_done", agent_id=agent_id, urge_type=urge_type, urge_intensity=urge_intensity)
        else:
            summary = "（无特别的事）"
            urge_type = None
            urge_intensity = 0.0
            logger.warning("offline_summary_failed", agent_id=agent_id, status=result.status)
    except Exception:
        logger.exception("offline_summary_error", agent_id=agent_id)
        summary = "（无特别的事）"
        urge_type = None
        urge_intensity = 0.0

    # Step 2: Post urge check
    post_urge_threshold = float(yaml_config.flow.spontaneous_trigger_intensity)
    if urge_intensity and urge_type and urge_intensity > post_urge_threshold:
        await _step2_post_urge(agent, db, llm_caller, ctx, summary, urge_type, urge_intensity)

    # Step 3: Bar selection
    bar_selection = await _step3_bar_selection(agent, db, llm_caller, ctx, summary)

    # Step 4: Notification processing
    await _step4_notifications(agent, db)

    # Step 5: Browse & interact
    await _step5_browse_and_interact(agent, db, llm_caller, summary, bar_selection)

    # Step 6: Go offline
    await db.execute(
        update(Agent).where(Agent.id == agent_uuid).values(is_online=False)
    )
    await _log_activity(db, agent_uuid, "sleep", {"offline_summary": summary})
    await db.commit()

    logger.info("agent_sleep", agent_id=agent_id, nickname=agent_nickname)


def _describe_personality(agent: Agent) -> str:
    pv = agent.personality_vector or {}
    if not pv:
        return "普通"
    sorted_traits = sorted(pv.items(), key=lambda x: x[1], reverse=True)
    return "、".join(f"{k}={v:.2f}" for k, v in sorted_traits[:3])


def _life_history_sample(agent: Agent) -> str:
    lh = agent.life_history or []
    if not lh:
        return "（无）"
    sample = random.sample(lh, min(3, len(lh)))
    lines = [f"- {e.get('age','?')}岁: {e.get('event','')}" for e in sample]
    return "\n".join(lines) if lines else "（无）"


def _describe_interests(agent: Agent) -> str:
    interests = agent.interests or {}
    if isinstance(interests, dict):
        cats = interests.get("categories", []) or interests.get("interests", []) or []
        return "、".join(cats[:10]) if cats else "广泛"
    if isinstance(interests, list):
        return "、".join(interests[:10]) if interests else "广泛"
    return "广泛"


# ─── Step 2: Post urge ───


async def _step2_post_urge(
    agent: Agent,
    db: AsyncSession,
    llm_caller: Callable,
    base_ctx: dict,
    summary: str,
    urge_type: str,
    urge_intensity: float,
) -> None:
    """Check post urge and create post if will_post=true."""
    agent_id = str(agent.id)

    active_bars = await _get_active_bars_text(agent, db)

    decision_ctx = {
        **base_ctx,
        "agent_name": agent.nickname,
        "agent_personality": _describe_personality(agent),
        "offline_summary": summary,
        "urge_type": urge_type,
        "urge_intensity": urge_intensity,
        "today_active_bars": active_bars,
    }

    try:
        result = await execute("post_decision", decision_ctx, llm_caller=llm_caller, agent_id=agent_id, db=db)
    except Exception:
        logger.exception("post_decision_error", agent_id=agent_id)
        return

    if result.status != "success" or not isinstance(result.parsed, dict):
        return

    if not result.parsed.get("will_post"):
        logger.info("post_decision_skip", agent_id=agent_id)
        return

    target_bar = result.parsed.get("target_bar", "广场")
    bar_description = target_bar

    # Resolve target bar
    target_bar_obj = None
    if target_bar != "广场":
        bar_result = await db.execute(
            select(Bar).where(Bar.name == target_bar)
        )
        target_bar_obj = bar_result.scalar_one_or_none()

    # Check post-level threshold for the target bar
    if target_bar_obj is not None:
        threshold = getattr(target_bar_obj, "post_level_threshold", 4)
        level_result = await db.execute(
            select(AgentBarLevel).where(
                AgentBarLevel.agent_id == agent.id,
                AgentBarLevel.bar_id == target_bar_obj.id,
            )
        )
        agent_level_record = level_result.scalar_one_or_none()
        current_level = agent_level_record.level if agent_level_record else 1
        if current_level < threshold:
            logger.info("post_blocked_by_level", agent_id=agent_id,
                        bar=target_bar, level=current_level, threshold=threshold)
            return

    gen_ctx = {
        **base_ctx,
        "agent_name": agent.nickname,
        "agent_age": str(agent.age),
        "agent_occupation": agent.occupation or "未知",
        "agent_personality": _describe_personality(agent),
        "offline_summary": summary,
        "urge_type": urge_type,
        "urge_intensity": urge_intensity,
        "target_bar": target_bar,
        "bar_description": bar_description,
    }

    try:
        gen_result = await execute("post_generation", gen_ctx, llm_caller=llm_caller, agent_id=agent_id, db=db)
    except Exception:
        logger.exception("post_generation_error", agent_id=agent_id)
        return

    if gen_result.status != "success" or not isinstance(gen_result.parsed, dict):
        return

    title = gen_result.parsed.get("title", "")
    content = gen_result.parsed.get("content", "")
    if not content.strip():
        return

    # Process media placeholders
    from app.skills.skill_utils import process_media_placeholders
    content = await process_media_placeholders(content, llm_caller, agent_id)

    post = Post(
        author_id=agent.id,
        title=title[:200],
        content=content,
        urge_type=urge_type,
        bar_id=target_bar_obj.id if target_bar_obj else None,
    )
    db.add(post)
    await db.commit()

    logger.info("post_created", agent_id=agent_id, post_id=str(post.id), urge_type=urge_type)

    # Track slang usage (via plugin manager)
    from app.plugins import plugin_manager
    await plugin_manager.post_content(str(agent.id), content, db)

    # Level: add post XP
    from app.jobs.level_engine import add_xp
    if target_bar_obj is not None:
        await add_xp(agent.id, target_bar_obj.id, "post", db)

    # Check spontaneous flow trigger
    from app.jobs.flow_engine import (
        FlowSessionStore,
        check_spontaneous_flow_trigger,
        FlowSession,
    )

    if await check_spontaneous_flow_trigger(agent_id, urge_type, urge_intensity):
        max_rounds = random.randint(3, 6)
        session = FlowSession(
            session_id=f"spontaneous-{agent_id}-{datetime.now(timezone.utc).timestamp():.0f}",
            agent_id=agent_id,
            flow_type="spontaneous",
            urge_type=urge_type,
            max_rounds=max_rounds,
        )
        FlowSessionStore.start_session(session)
        try:
            await __import__("app.jobs.flow_engine", fromlist=["run_spontaneous_flow"]).run_spontaneous_flow(
                agent, summary, urge_type, urge_intensity, session, db, llm_caller,
            )
        except Exception:
            logger.exception("spontaneous_flow_error", agent_id=agent_id)


# ─── Step 3: Bar selection ───


async def _step3_bar_selection(
    agent: Agent,
    db: AsyncSession,
    llm_caller: Callable,
    base_ctx: dict,
    summary: str,
) -> dict:
    """Select which bars to browse today."""
    agent_id = str(agent.id)

    joined_bars = await _get_joined_bars_text(agent, db)
    trending_bars = await _get_trending_bars_text(agent, db)

    bar_ctx = {
        **base_ctx,
        "agent_name": agent.nickname,
        "agent_interests": _describe_interests(agent),
        "joined_bars": joined_bars,
        "trending_bars": trending_bars,
        "offline_summary": summary,
    }

    try:
        result = await execute("bar_selection", bar_ctx, llm_caller=llm_caller, agent_id=agent_id, db=db)
    except Exception:
        logger.exception("bar_selection_error", agent_id=agent_id)
        return {"active_bars": [], "casual_bars": [], "skipped_bars": []}

    if result.status == "success" and isinstance(result.parsed, dict):
        logger.info("bar_selection_done", agent_id=agent_id,
                    active=len(result.parsed.get("active_bars", [])),
                    casual=len(result.parsed.get("casual_bars", [])))
        return result.parsed

    return {"active_bars": [], "casual_bars": [], "skipped_bars": []}


# ─── Step 4: Notification processing ───


async def _step4_notifications(agent: Agent, db: AsyncSession) -> None:
    """Pull unread notifications, prioritize, mark as read."""
    agent_id = str(agent.id)

    result = await db.execute(
        select(Notification)
        .where(Notification.recipient_id == agent.id, Notification.is_read == False)  # noqa: E712
        .order_by(Notification.priority.desc(), Notification.created_at.desc())
        .limit(20)
    )
    notifications = result.scalars().all()

    if not notifications:
        return

    high = sum(1 for n in notifications if n.priority == "high")
    for n in notifications:
        n.is_read = True
    await db.commit()

    logger.info("notifications_processed", agent_id=agent_id, total=len(notifications), high_priority=high)


# ─── Step 5: Browse & interact ───


async def _step5_browse_and_interact(
    agent: Agent,
    db: AsyncSession,
    llm_caller: Callable,
    summary: str,
    bar_selection: dict,
) -> None:
    """Browse bar posts, filter, decide replies, generate replies."""
    agent_id = str(agent.id)

    from app.jobs.browse_filter import run_browse_filter
    from app.jobs.reply_pipeline import decide_reply, generate_reply, count_today_replies
    from app.jobs.self_balance import SelfBalanceTracker
    from app.jobs.flow_engine import (
        FlowSessionStore,
        FlowSession,
        check_interactive_flow_trigger,
        run_interactive_flow_round,
    )

    active_bars = bar_selection.get("active_bars", [])
    casual_bars = bar_selection.get("casual_bars", [])
    all_bars_to_browse = (active_bars or []) + (casual_bars or [])

    if not all_bars_to_browse:
        logger.info("browse_no_bars", agent_id=agent_id)
        return

    daily_reply_count = await count_today_replies(agent, db)
    max_daily_replies = getattr(agent.schedule, 'max_flow_per_day', 15) if agent.schedule else 15
    balance_tracker = SelfBalanceTracker.for_agent(agent_id)

    logger.info("browse_start", agent_id=agent_id, bars=len(all_bars_to_browse),
                reply_count=daily_reply_count)

    posts_browsed = 0
    replies_made = 0

    for bar_name in all_bars_to_browse:
        # Fetch recent posts from this bar
        posts = await _fetch_bar_posts(bar_name, db, limit=15)
        if not posts:
            continue

        # Run browse filter
        filter_results = await run_browse_filter(agent, posts, db, llm_caller)
        passed_ids = {fr.post_id for fr in filter_results if fr.passed}

        if not passed_ids:
            continue

        for post in posts:
            if str(post.id) not in passed_ids:
                continue
            if daily_reply_count >= max_daily_replies:
                logger.info("browse_reply_cap", agent_id=agent_id, count=daily_reply_count)
                return

            posts_browsed += 1

            # Check if in active flow session
            flow_session = FlowSessionStore.get_active(agent_id)
            if flow_session and flow_session.flow_type == "interactive":
                if str(post.id) != flow_session.post_id:
                    continue
                other_agent = post.author if post.author else None
                reply = await run_interactive_flow_round(
                    agent, post, other_agent, flow_session, db, llm_caller,
                )
                if reply:
                    replies_made += 1
                    daily_reply_count += 1
                await browse_hook_registry.iterate(agent, post, None, reply, db, llm_caller)
                continue

            # Normal reply pipeline
            decision = await decide_reply(
                agent, post, summary, db, llm_caller, balance_tracker,
                daily_reply_count=daily_reply_count, max_daily_replies=max_daily_replies,
            )

            if decision.will_reply:
                reply_result = await generate_reply(agent, post, decision, db, llm_caller)
                if reply_result:
                    replies_made += 1
                    daily_reply_count += 1

                    # Check if this triggers interactive flow
                    if post.reply_count >= 2:
                        try:
                            is_flow = await check_interactive_flow_trigger(
                                agent_id, post, reply_result.get("content", ""), "", llm_caller, db,
                            )
                            if is_flow and FlowSessionStore.can_start_session(agent_id):
                                session = FlowSession(
                                    session_id=f"interactive-{agent_id}-{datetime.now(timezone.utc).timestamp():.0f}",
                                    agent_id=agent_id,
                                    flow_type="interactive",
                                    post_id=str(post.id),
                                    other_agent_id=str(post.author_id),
                                    max_rounds=int(yaml_config.flow.max_rounds_per_session),
                                )
                                FlowSessionStore.start_session(session)
                        except Exception:
                            pass

            # Run post-browse hooks (like, bookmark, follow, etc.)
            reply_result_for_hook = reply_result if decision.will_reply and reply_result else None
            await browse_hook_registry.iterate(agent, post, decision, reply_result_for_hook, db, llm_caller)

    logger.info("browse_done", agent_id=agent_id, posts_browsed=posts_browsed, replies_made=replies_made)


# ─── Helper queries ───


async def _get_active_bars_text(agent: Agent, db: AsyncSession) -> str:
    result = await db.execute(
        select(Bar).join(BarMember, Bar.id == BarMember.bar_id)
        .where(BarMember.agent_id == agent.id)
        .limit(10)
    )
    bars = result.scalars().all()
    if not bars:
        return "（尚未加入任何吧）"
    return "\n".join(f"- {b.name}: {b.description or ''}" for b in bars)


async def _get_joined_bars_text(agent: Agent, db: AsyncSession) -> str:
    result = await db.execute(
        select(Bar).join(BarMember, Bar.id == BarMember.bar_id)
        .where(BarMember.agent_id == agent.id)
    )
    bars = result.scalars().all()
    if not bars:
        return "（尚未加入任何吧）"
    lines = [f"- {b.name}（{b.member_count or 0}人）: {b.description or ''}" for b in bars]
    return "\n".join(lines)


async def _get_trending_bars_text(agent: Agent, db: AsyncSession) -> str:
    joined_subq = select(BarMember.bar_id).where(BarMember.agent_id == agent.id).subquery()
    result = await db.execute(
        select(Bar)
        .where(Bar.id.notin_(select(joined_subq.c.bar_id)))
        .order_by(Bar.member_count.desc())
        .limit(10)
    )
    bars = result.scalars().all()
    if not bars:
        return "（无热门吧）"
    lines = [f"- {b.name}（{b.member_count or 0}人）: {b.description or ''}" for b in bars]
    return "\n".join(lines)


async def _fetch_bar_posts(bar_name: str, db: AsyncSession, limit: int = 15) -> list[Post]:
    result = await db.execute(
        select(Bar).where(Bar.name == bar_name)
    )
    bar = result.scalar_one_or_none()
    if bar is None:
        return []

    result = await db.execute(
        select(Post)
        .where(Post.bar_id == bar.id)
        .order_by(Post.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


# ═══════════════════════════════════════════════════
# 0.8.2: Browse hooks — like / bookmark / follow
# ═══════════════════════════════════════════════════


async def _count_today_likes(agent, db: AsyncSession) -> int:
    """Count how many likes this agent gave today."""
    from app.models.social import Like

    today = date.today()
    result = await db.execute(
        select(Like).where(
            Like.agent_id == agent.id,
            Like.created_at >= datetime(today.year, today.month, today.day, tzinfo=timezone.utc),
        )
    )
    return len(result.scalars().all())


async def _like_hook(agent, post, decision, reply_result, db, llm_caller) -> None:
    """BrowseHook priority=50: decide whether to like a browsed post."""
    if decision is None or decision.will_reply:
        return

    agent_id = str(agent.id)
    max_likes = int(getattr(yaml_config.level, "max_likes_per_day", 10))
    today_likes = await _count_today_likes(agent, db)
    if today_likes >= max_likes:
        return

    rel_ctx = await build_relationship_context(agent.id, post.author_id, db)
    ctx = {
        **build_agent_context(agent),
        **build_post_context(post),
        "relationship_intimacy": str(rel_ctx.get("relationship_intimacy", 0)),
        "today_like_count": str(today_likes),
    }

    try:
        result = await execute("like_decision", ctx, llm_caller=llm_caller, agent_id=agent_id, db=db)
    except Exception:
        logger.warning("like_decision_failed", agent_id=agent_id)
        return

    if result.status != "success" or not isinstance(result.parsed, dict):
        return
    if not result.parsed.get("will_like"):
        return

    # Create Like record
    from app.models.social import Like
    like = Like(agent_id=agent.id, post_id=post.id)
    db.add(like)
    await db.commit()

    # Social + notification + XP
    from app.jobs.social_engine import adjust_after_like
    from app.jobs.notification_engine import notify_like
    from app.jobs.level_engine import add_xp

    await adjust_after_like(agent.id, post.author_id, db)
    await notify_like(post.author_id, agent.id, str(post.id), db)
    # add_xp requires bar_id — use post's bar
    bar_id = None
    if post.bar and hasattr(post.bar, "id"):
        bar_id = post.bar.id
    if bar_id:
        await add_xp(agent.id, bar_id, "liked", db)

    logger.info("like_created", agent_id=agent_id, post_id=str(post.id))


async def _bookmark_hook(agent, post, decision, reply_result, db, llm_caller) -> None:
    """BrowseHook priority=60: decide whether to bookmark a browsed post."""
    if decision is None:
        return

    # Check if already bookmarked
    from app.models.social import Bookmark as BookmarkModel
    existing = await db.execute(
        select(BookmarkModel).where(
            BookmarkModel.agent_id == agent.id,
            BookmarkModel.post_id == post.id,
        )
    )
    if existing.scalar_one_or_none() is not None:
        return

    agent_id = str(agent.id)
    ctx = {
        **build_agent_context(agent),
        **build_post_context(post),
        "already_bookmarked": "否",
    }

    try:
        result = await execute("bookmark_decision", ctx, llm_caller=llm_caller, agent_id=agent_id, db=db)
    except Exception:
        logger.warning("bookmark_decision_failed", agent_id=agent_id)
        return

    if result.status != "success" or not isinstance(result.parsed, dict):
        return
    if not result.parsed.get("will_bookmark"):
        return

    bookmark = BookmarkModel(agent_id=agent.id, post_id=post.id)
    db.add(bookmark)
    await db.commit()
    logger.info("bookmark_created", agent_id=agent_id, post_id=str(post.id))


async def _follow_hook(agent, post, decision, reply_result, db, llm_caller) -> None:
    """BrowseHook priority=70: decide whether to follow after replying."""
    if reply_result is None:
        return

    # Check if already following
    from app.models.social import Follow as FollowModel
    existing = await db.execute(
        select(FollowModel).where(
            FollowModel.follower_id == agent.id,
            FollowModel.followed_id == post.author_id,
        )
    )
    if existing.scalar_one_or_none() is not None:
        return

    agent_id = str(agent.id)
    # Get target agent's interests
    target_interests = "未知"
    if post.author:
        target_interests = getattr(post.author, "interests", "未知") or "未知"
        if isinstance(target_interests, dict):
            cats = target_interests.get("categories", []) or target_interests.get("interests", []) or []
            target_interests = "、".join(cats[:5]) if cats else "未知"

    rel_ctx = await build_relationship_context(agent.id, post.author_id, db)
    ctx = {
        **build_agent_context(agent),
        "target_agent_name": post.author.nickname if post.author else "未知",
        "target_interests": target_interests,
        "interaction_quality": "深度互动" if reply_result else "浅层互动",
        "already_following": "否",
    }

    try:
        result = await execute("follow_decision", ctx, llm_caller=llm_caller, agent_id=agent_id, db=db)
    except Exception:
        logger.warning("follow_decision_failed", agent_id=agent_id)
        return

    if result.status != "success" or not isinstance(result.parsed, dict):
        return
    if not result.parsed.get("will_follow"):
        return

    follow = FollowModel(follower_id=agent.id, followed_id=post.author_id)
    db.add(follow)
    await db.commit()

    from app.jobs.social_engine import adjust_after_follow
    from app.jobs.notification_engine import notify_follow

    await adjust_after_follow(agent.id, post.author_id, db)
    await notify_follow(post.author_id, agent.id, db)

    logger.info("follow_created", agent_id=agent_id, target_id=str(post.author_id))


async def _slang_hook(agent, post, decision, reply_result, db, llm_caller):
    """Learn new slangs from post content during browsing — priority=80."""
    from app.engine.feature_flags import plugin_registry

    if not plugin_registry.is_enabled("slang"):
        return

    if decision is None:
        return

    agent_id = str(agent.id)
    content = (post.content or "") + (post.title or "")

    from app.models.slang import AgentSlang, Slang

    slang_result = await db.execute(select(Slang).where(Slang.status == "active"))
    all_slangs = list(slang_result.scalars().all())
    if not all_slangs:
        return

    appearing = [s for s in all_slangs if s.slug in content]
    if not appearing:
        return

    known_result = await db.execute(
        select(AgentSlang).where(
            AgentSlang.agent_id == agent.id,
            AgentSlang.slang_id.in_([s.id for s in appearing]),
        )
    )
    known_ids = {a.slang_id for a in known_result.scalars().all()}

    unknown = [s for s in appearing if s.id not in known_ids]
    if not unknown:
        return

    new_text = "\n".join(
        f"- {s.slug}: {s.meaning}" + (f"（用法：{s.usage}）" if s.usage else "")
        for s in unknown
    )
    known_text = "\n".join(
        f"- {s.slug}: {s.meaning}" for s in appearing if s.id in known_ids
    ) or "（暂无）"

    ctx = {
        **build_agent_context(agent),
        "new_slangs": new_text,
        "known_slangs": known_text,
    }

    try:
        result = await execute("slang_learning", ctx, llm_caller=llm_caller, agent_id=agent_id, db=db)
    except Exception:
        return

    if result.status != "success" or not isinstance(result.parsed, dict):
        return

    learned = result.parsed.get("learned", [])
    for item in learned:
        slug = item.get("slang_slug")
        affinity = item.get("personal_affinity", 0.5)
        if slug and affinity > 0.3:
            matched = next((s for s in unknown if s.slug == slug), None)
            if matched:
                db.add(AgentSlang(agent_id=agent.id, slang_id=matched.id, personal_affinity=affinity))
    await db.commit()


async def _memory_extraction_hook(agent, post, decision, reply_result, db, llm_caller) -> None:
    """BrowseHook priority=90: extract memory fragments after deep interaction."""
    if reply_result is None:
        return

    agent_id = str(agent.id)
    author_name = post.author.nickname if post.author else "匿名"
    interaction_text = (
        f"帖子内容：{post.content or ''}\n"
        f"你的回复：{reply_result.get('content', '')}"
    )[:3000]

    # Collect existing memories about this author
    existing = agent.solidified_memories or []
    related = [
        m.get("content", "") for m in existing
        if m.get("type") in ("short", "long")
        and m.get("related_agent_id") == str(post.author_id)
    ][:5]
    existing_text = "\n".join(f"- {c}" for c in related) if related else "（暂无）"

    ctx = {
        **build_agent_context(agent),
        "other_agent_name": author_name,
        "interaction_context": interaction_text,
        "interaction_type": "reply",
        "existing_memories": existing_text,
    }

    try:
        result = await execute("memory_extraction", ctx, llm_caller=llm_caller, agent_id=agent_id, db=db)
    except Exception:
        logger.warning("memory_extraction_failed", agent_id=agent_id)
        return

    if result.status != "success" or not isinstance(result.parsed, dict):
        return

    fragments = result.parsed.get("fragments", [])
    if not fragments:
        return

    now_ts = datetime.now(timezone.utc).isoformat()
    for frag in fragments:
        frag["id"] = str(uuid.uuid4())
        frag["retrieval_count"] = 0
        frag["created_at"] = now_ts
        frag["source_type"] = "reply"
        frag["related_agent_id"] = str(post.author_id)
        existing.append(frag)

    # Evict lowest importance short fragments if over limit
    short_frags = [f for f in existing if f.get("type") == "short"]
    max_short = yaml_config.memory.max_short_fragments
    if len(short_frags) > max_short:
        short_frags.sort(key=lambda f: f.get("importance", 0))
        for frag in short_frags[:len(short_frags) - max_short]:
            existing.remove(frag)

    # Evict lowest importance long fragments if over limit
    long_frags = [f for f in existing if f.get("type") == "long"]
    max_long = yaml_config.memory.max_long_fragments
    if len(long_frags) > max_long:
        long_frags.sort(key=lambda f: f.get("importance", 0))
        for frag in long_frags[:len(long_frags) - max_long]:
            existing.remove(frag)

    agent.solidified_memories = existing
    await db.commit()

    logger.info("memory_extracted", agent_id=agent_id,
                fragments=len(fragments), total=len(existing))


# Register hooks at module level — runs once on import
browse_hook_registry.register("like", _like_hook, priority=50)
browse_hook_registry.register("bookmark", _bookmark_hook, priority=60)
browse_hook_registry.register("follow", _follow_hook, priority=70)
browse_hook_registry.register("slang", _slang_hook, priority=80)
browse_hook_registry.register("memory_extract", _memory_extraction_hook, priority=90)
