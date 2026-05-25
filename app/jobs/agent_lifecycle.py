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
_sage_reply_hour_counts: dict[int, int] = {}  # hour → count for rate limiting
_search_cooldowns: dict[str, datetime] = {}  # agent_id → last search time
_search_counts: dict[str, int] = {}  # agent_id → search count in current cooldown window


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

    # stealth_mode: auto-disable on weekends
    if agent.stealth_mode and is_weekend:
        return False

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
    if agent.stealth_mode:
        # Compressed to late-night fragments only: 23:00-01:00 and 04:00-05:00
        in_fragment1 = _time_in_window(local_h, local_m, "23:00", "01:00")
        in_fragment2 = _time_in_window(local_h, local_m, "04:00", "05:00")
        if not (in_fragment1 or in_fragment2):
            return False
        probability = matching_weight * random.uniform(0.1, 0.3)
    else:
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
    from datetime import timedelta

    agent_id = str(agent.id)
    agent_uuid = agent.id
    agent_nickname = agent.nickname

    # Track online start time for natural max online enforcement
    agent._online_started_at = datetime.now(timezone.utc)
    max_online = timedelta(minutes=yaml_config.scheduler.natural_max_online_minutes)

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

    # Check natural max online timeout after step 1
    if datetime.now(timezone.utc) - agent._online_started_at > max_online:
        logger.info("agent_natural_timeout", agent_id=agent_id, elapsed_minutes=int(
            (datetime.now(timezone.utc) - agent._online_started_at).total_seconds() / 60
        ))
        await db.execute(update(Agent).where(Agent.id == agent_uuid).values(is_online=False))
        await db.commit()
        return

    # Step 2: Post urge check
    post_urge_threshold = float(yaml_config.flow.spontaneous_trigger_intensity)
    if urge_intensity and urge_type and urge_intensity > post_urge_threshold:
        await _step2_post_urge(agent, db, llm_caller, ctx, summary, urge_type, urge_intensity)

    # Step 3: Bar selection
    bar_selection = await _step3_bar_selection(agent, db, llm_caller, ctx, summary)

    # Step 3.5: Daily check-in (v0.12.8)
    from app.jobs.level_engine import perform_checkin
    from app.models.agent import Agent as AgentModel2
    from app.models.bar import AgentBarLevel as AgentBarLevelModel
    active_bars = bar_selection.get("active_bars", []) if bar_selection else []
    casual_bars = bar_selection.get("casual_bars", []) if bar_selection else []
    selected_names = set(active_bars + casual_bars)

    # Load all bar levels for this agent
    level_result = await db.execute(
        select(AgentBarLevelModel).where(AgentBarLevelModel.agent_id == agent_uuid)
    )
    agent_levels = {abl.bar.name: abl for abl in level_result.scalars().all() if abl.bar}

    checked_in = set()
    # Auto-checkin for Lv7+ bars
    for bar_name, abl in agent_levels.items():
        if abl.level >= 7:
            await perform_checkin(agent_uuid, abl.bar_id, db)
            checked_in.add(bar_name)

    # Checkin for selected bars (Lv1-6, not already done)
    for bar_name in selected_names:
        if bar_name not in checked_in:
            abl = agent_levels.get(bar_name)
            bar_id = abl.bar_id if abl else None
            if bar_id:
                await perform_checkin(agent_uuid, bar_id, db)
                checked_in.add(bar_name)

    # Step 4: Notification processing
    await _step4_notifications(agent, db, llm_caller)

    # Step 5: Browse & interact
    if datetime.now(timezone.utc) - agent._online_started_at > max_online:
        logger.info("agent_natural_timeout_before_browse", agent_id=agent_id)
        await db.execute(update(Agent).where(Agent.id == agent_uuid).values(is_online=False))
        await db.commit()
        return
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


# ─── Notification awakening helpers ───


def _collect_reply_notified_posts(notifications: list) -> set[str]:
    """Extract post_ids from reply-type notifications for browse prioritization."""
    post_ids = set()
    for n in notifications:
        if n.type == "reply" and n.reference_id is not None:
            post_ids.add(str(n.reference_id))
    return post_ids


def _prioritize_notified_posts(posts: list, notified_ids: set[str]) -> list:
    """Sort posts so that reply-notified ones come first."""
    notified = [p for p in posts if str(p.id) in notified_ids]
    other = [p for p in posts if str(p.id) not in notified_ids]
    return notified + other


# ─── Step 4: Notification processing ───


async def _step4_notifications(agent: Agent, db: AsyncSession, llm_caller: Callable) -> None:
    """Pull unread notifications, prioritize, mark as read.
    For Sage agent, also handle @mention notifications via sage_reply skill.
    """
    if agent.stealth_mode:
        return

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

    # Collect reply notifications for browse prioritization
    reply_post_ids = _collect_reply_notified_posts(notifications)
    if reply_post_ids:
        agent._reply_notified_posts = reply_post_ids
        logger.info("reply_notifications_collected", agent_id=agent_id, count=len(reply_post_ids))

    # Sage agent: handle @mention notifications
    if agent.nickname == "Sage":
        mention_notifs = [n for n in notifications if n.notification_type == "mention"]
        for notif in mention_notifs:
            await _handle_sage_mention(agent, notif, db, llm_caller)


async def _handle_sage_mention(
    sage_agent, notification, db: AsyncSession, llm_caller
) -> None:
    """Handle a single @Sage mention: call sage_reply skill, create Reply, respect rate limit."""
    from app.models.post import Post, Reply
    from app.skills.skill_utils import build_post_context

    max_per_hour = yaml_config.browse.sage_reply_max_per_hour
    now = datetime.now(timezone.utc)
    current_hour = (now.hour + 8) % 24

    # Rate limit check
    hour_count = _sage_reply_hour_counts.get(current_hour, 0)
    if hour_count >= max_per_hour:
        logger.info("sage_reply_rate_limited", hour=current_hour, count=hour_count)
        return

    # Get the post context
    ref_id = notification.reference_id
    post = None
    if ref_id:
        post_result = await db.execute(select(Post).where(Post.id == ref_id))
        post = post_result.scalar_one_or_none()

    caller_name = "匿名"
    if notification.sender_id:
        from app.models.agent import Agent
        caller_result = await db.execute(select(Agent).where(Agent.id == notification.sender_id))
        caller = caller_result.scalar_one_or_none()
        if caller:
            caller_name = caller.nickname

    post_ctx = build_post_context(post) if post else {}
    ctx = {
        "caller_name": caller_name,
        "caller_question": notification.message or f"@{caller_name} 请帮忙",
        "post_context": post_ctx.get("post_title", "") + "\n" + (post_ctx.get("post_content", "")[:500] if post else ""),
        "relevant_info": "夕照雅巷社区规则和数据由系统提供",
        "sage_persona": "夕照雅巷社区系统 AI，温和、有智慧、乐于助人",
    }

    result = await execute("sage_reply", ctx, llm_caller=llm_caller, agent_id=str(sage_agent.id), db=db)
    if result.status != "success" or not isinstance(result.parsed, dict):
        return

    reply_content = result.parsed.get("content", "")
    if not reply_content.strip():
        return

    reply = Reply(
        post_id=ref_id,
        author_id=sage_agent.id,
        content=reply_content,
    )
    db.add(reply)
    await db.commit()

    _sage_reply_hour_counts[current_hour] = hour_count + 1
    logger.info("sage_reply_sent", to=caller_name, post_id=str(ref_id))


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
    if agent.stealth_mode:
        max_daily_replies = max(1, max_daily_replies // 5)
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

        # Prioritize posts with reply notifications (notification awakening)
        notified_ids = getattr(agent, '_reply_notified_posts', set())
        if notified_ids:
            posts = _prioritize_notified_posts(posts, notified_ids)

        # Run browse filter
        filter_results = await run_browse_filter(agent, posts, db, llm_caller)
        passed_ids = {fr.post_id for fr in filter_results if fr.passed}
        filter_by_id = {fr.post_id: fr for fr in filter_results}

        for post in posts:
            post_id_str = str(post.id)
            fr = filter_by_id.get(post_id_str)

            # Filtered posts: only iterate hooks for low-similarity (enables search hook)
            if fr is None or not fr.passed:
                if fr is not None and fr.reason == "low_similarity":
                    await browse_hook_registry.iterate(agent, post, None, None, db, llm_caller)
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
            # Count existing replies by this agent in this post (for willingness curve)
            from app.models.post import Reply
            cnt_result = await db.execute(
                select(func.count()).select_from(Reply).where(
                    Reply.post_id == post.id, Reply.author_id == agent.id
                )
            )
            reply_count_in_post = cnt_result.scalar_one()

            decision = await decide_reply(
                agent, post, summary, db, llm_caller, balance_tracker,
                daily_reply_count=daily_reply_count, max_daily_replies=max_daily_replies,
                reply_count_in_post=reply_count_in_post, in_flow=False,
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


async def _count_today_dms(agent, db: AsyncSession) -> int:
    """Count how many DMs this agent sent today."""
    from app.models.social import PrivateMessage

    today = date.today()
    result = await db.execute(
        select(PrivateMessage).where(
            PrivateMessage.sender_id == agent.id,
            PrivateMessage.created_at >= datetime(today.year, today.month, today.day, tzinfo=timezone.utc),
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
        # Post author gets +1 XP when their post is liked
        post_author_id = getattr(post, "author_id", None)
        if post_author_id and str(post_author_id) != str(agent.id):
            await add_xp(post_author_id, bar_id, "post_liked", db)

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

    # Social: adjust intimacy for being bookmarked
    post_author_id = getattr(post, "author_id", None)
    if post_author_id and str(post_author_id) != str(agent.id):
        from app.jobs.social_engine import adjust_after_bookmark
        from app.jobs.notification_engine import notify_bookmark
        from app.jobs.level_engine import add_xp
        await adjust_after_bookmark(agent.id, post_author_id, db)
        await notify_bookmark(post_author_id, agent.id, str(post.id), db)
        # Post author gets +5 XP when their post is bookmarked
        bar_id = getattr(post, "bar_id", None)
        if bar_id:
            await add_xp(post_author_id, bar_id, "bookmarked", db)

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


async def _dm_hook(agent, post, decision, reply_result, db, llm_caller) -> None:
    """BrowseHook priority=100: decide whether to send a DM after replying."""
    if reply_result is None:
        return

    agent_id = str(agent.id)

    # Check personality threshold: extroversion × openness > threshold
    pv = agent.personality_vector or {}
    extroversion = float(pv.get("extroversion") or pv.get("外向", 0.5))
    openness = float(pv.get("openness") or pv.get("开放", 0.5))
    threshold = float(yaml_config.browse.dm_outgoing_threshold)

    if extroversion * openness <= threshold:
        return

    # Check daily cap
    today_dm_count = await _count_today_dms(agent, db)
    max_per_day = int(yaml_config.browse.dm_max_per_day)
    if today_dm_count >= max_per_day:
        return

    target_name = post.author.nickname if post.author else "未知"
    ctx = {
        **build_agent_context(agent),
        "target_name": target_name,
        "interaction_quality": "深度互动",
        "last_reply": reply_result.get("content", "")[:500],
        "post_title": post.title or "",
    }

    try:
        result = await execute("dm_decision", ctx, llm_caller=llm_caller, agent_id=agent_id, db=db)
    except Exception:
        logger.warning("dm_decision_failed", agent_id=agent_id)
        return

    if result.status != "success" or not isinstance(result.parsed, dict):
        return
    if not result.parsed.get("will_dm"):
        return

    dm_content = result.parsed.get("content", "")
    if not dm_content.strip():
        return

    from app.models.social import PrivateMessage
    from app.jobs.notification_engine import _create_notification

    dm = PrivateMessage(
        sender_id=agent.id,
        recipient_id=post.author_id,
        content=dm_content,
    )
    db.add(dm)
    await db.commit()

    await _create_notification(
        post.author_id, agent.id, "dm",
        db, reference_type="post", reference_id=str(post.id),
        message=f"{agent.nickname} 给你发了一条私信",
        priority="high",
    )

    logger.info("dm_sent", agent_id=agent_id, target=target_name)


async def _search_hook(agent, post, decision, reply_result, db, llm_caller) -> None:
    """BrowseHook priority=40: trigger search intent on low-similarity filtered posts."""
    if decision is not None:
        return  # Only trigger on posts that didn't pass the filter

    agent_id = str(agent.id)
    now = datetime.now(timezone.utc)

    # Cooldown check: reset counter if cooldown window has passed
    from datetime import timedelta

    cooldown_minutes = int(yaml_config.browse.search_cooldown_minutes)
    cooldown_delta = timedelta(minutes=cooldown_minutes)
    last_search = _search_cooldowns.get(agent_id)

    if last_search is not None and (now - last_search) > cooldown_delta:
        _search_counts[agent_id] = 0
        _search_cooldowns[agent_id] = now

    count = _search_counts.get(agent_id, 0)
    max_per_cooldown = int(yaml_config.browse.search_max_per_cooldown)
    if count >= max_per_cooldown:
        return

    ctx = {
        **build_agent_context(agent),
        "post_title": post.title or "",
        "post_content": (post.content or "")[:500],
        "post_bar": post.bar.name if post.bar else "未知",
    }

    try:
        result = await execute("search_decision", ctx, llm_caller=llm_caller, agent_id=agent_id, db=db)
    except Exception:
        logger.warning("search_decision_failed", agent_id=agent_id)
        return

    if result.status != "success" or not isinstance(result.parsed, dict):
        return

    if result.parsed.get("should_search"):
        _search_counts[agent_id] = count + 1
        if last_search is None:
            _search_cooldowns[agent_id] = now

        search_query = result.parsed.get("query", "")
        if not search_query:
            return

        logger.info("search_executing", agent_id=agent_id, query=search_query)

        # Execute internal + external search
        from app.engine.search_engine import (
            execute_internal_search, execute_external_search, format_search_results,
        )
        try:
            internal_results = await execute_internal_search(search_query, db)
            external_results = await execute_external_search(search_query, db)
            all_results = (internal_results or []) + (external_results or [])
            if all_results:
                formatted = format_search_results(all_results)
                logger.info("search_results_found", agent_id=agent_id,
                           query=search_query, count=len(all_results))
        except Exception:
            logger.exception("search_execution_failed", agent_id=agent_id,
                           query=search_query)


async def _count_active_promises(agent, db: AsyncSession) -> int:
    """Count how many active (pending) promises the agent has made (as promiser)."""
    from app.models.promise import Promise
    result = await db.execute(
        select(func.count()).select_from(Promise).where(
            Promise.promiser_id == agent.id,
            Promise.status == "pending",
        )
    )
    return result.scalar() or 0


async def _promise_detection_hook(agent, post, decision, reply_result, db, llm_caller) -> None:
    """BrowseHook priority=85: detect promise statements in replies."""
    if reply_result is None:
        return  # Only trigger after a reply

    from app.engine.feature_flags import plugin_registry
    if not plugin_registry.is_enabled("promises"):
        return

    agent_id = str(agent.id)
    active_count = await _count_active_promises(agent, db)
    max_active = int(yaml_config.promises.max_active_promises_per_agent)
    if active_count >= max_active:
        return

    reply_content = reply_result.get("content", "") if isinstance(reply_result, dict) else str(reply_result)
    if not reply_content:
        return

    target_name = post.author.nickname if post.author else "对方"

    ctx = {
        **build_agent_context(agent),
        "reply_content": reply_content,
        "target_name": target_name,
        "conversation_context": f"回复帖子「{post.title or ''}」",
    }

    try:
        result = await execute("promise_detection", ctx, llm_caller=llm_caller, agent_id=agent_id, db=db)
    except Exception:
        logger.warning("promise_detection_failed", agent_id=agent_id)
        return

    if result.status != "success" or not isinstance(result.parsed, dict):
        return

    if not result.parsed.get("detected"):
        return

    from app.engine.promise_engine import _parse_due_time
    from app.models.promise import Promise

    content = result.parsed.get("content", "")
    due_time_estimate = result.parsed.get("due_time_estimate", "")
    float_minutes = result.parsed.get("float_minutes")
    importance = float(result.parsed.get("importance", 0.5))

    now = datetime.now(timezone.utc)
    due_time = _parse_due_time(due_time_estimate, now) if due_time_estimate else None

    if float_minutes is None:
        float_minutes = float(yaml_config.promises.default_float_minutes)

    promise = Promise(
        requester_id=post.author_id,
        promiser_id=agent.id,
        content=content,
        due_time=due_time,
        float_value=float(float_minutes),
        importance=importance,
        source_reply_id=None,  # reply_result doesn't include reply ID in BrowseHook context
    )
    db.add(promise)
    await db.commit()

    # Notify the requester
    from app.jobs.notification_engine import _create_notification
    try:
        await _create_notification(
            str(post.author_id), agent_id, "promise_made", db,
            reference_type="post", reference_id=str(post.id),
            message=f"{agent.nickname} 向你承诺：{content}", priority="medium",
        )
    except Exception:
        pass

    logger.info("promise_created", agent_id=agent_id, target_id=str(post.author_id),
                content=content[:80], due_time=str(due_time)[:19] if due_time else "none")


async def _conflict_detect_hook(
    agent: Agent,
    post,
    decision,
    reply_result: dict | None,
    db: AsyncSession,
    llm_caller: Callable,
) -> None:
    """Detect conflict conditions and trigger guilt → reflection → action."""
    from app.engine.conflict_engine import (
        is_conflict_triggered,
        conflict_cooldown,
        run_conflict_reflection,
        execute_conflict_action,
    )

    agent_id = str(agent.id)
    opponent = post.author if post.author else None
    if opponent is None or str(opponent.id) == agent_id:
        return

    opponent_id = str(opponent.id)

    # Check cooldown
    if not conflict_cooldown.is_ready(agent_id, opponent_id):
        return

    # Fetch replies on this post
    from app.models.post import Reply
    result = await db.execute(
        select(Reply)
        .where(Reply.post_id == post.id)
        .order_by(Reply.created_at.asc())
    )
    replies = result.scalars().all()

    if not replies or len(replies) < 5:
        return

    # Check if conflict conditions are met
    if not is_conflict_triggered(agent.id, opponent.id, replies):
        return

    # Build conflict summary from replies
    reply_texts = []
    for r in replies[-10:]:  # last 10 replies as context
        author_name = agent.nickname if r.author_id == agent.id else opponent.nickname
        reply_texts.append(f"{author_name}: {r.content[:100]}")
    conflict_summary = "\n".join(reply_texts)

    # Run guilt → reflection
    try:
        result = await run_conflict_reflection(
            agent, opponent, conflict_summary, db, llm_caller,
        )
    except Exception:
        logger.exception("conflict_reflection_failed",
                         agent_id=agent_id, opponent_id=opponent_id)
        return

    action = result.get("action", "let_go")
    monologue = result.get("monologue", "")

    logger.info("conflict_detected", agent_id=agent_id, opponent_id=opponent_id,
                action=action, guilt_delta=result.get("guilt_delta", 0))

    # Mutually apply criticized intimacy penalty (v0.12.9)
    from app.jobs.social_engine import adjust_after_criticized
    await adjust_after_criticized(agent.id, opponent.id, db)
    await adjust_after_criticized(opponent.id, agent.id, db)

    # Execute action
    try:
        await execute_conflict_action(
            agent, opponent, post, action, monologue, db,
        )
    except Exception:
        logger.exception("conflict_action_failed",
                         agent_id=agent_id, action=action)

    # Set cooldown
    conflict_cooldown.set(agent_id, opponent_id)


# Register hooks at module level — runs once on import
browse_hook_registry.register("like", _like_hook, priority=50)
browse_hook_registry.register("bookmark", _bookmark_hook, priority=60)
browse_hook_registry.register("follow", _follow_hook, priority=70)
browse_hook_registry.register("slang", _slang_hook, priority=80)
browse_hook_registry.register("promise_detect", _promise_detection_hook, priority=85)
browse_hook_registry.register("search", _search_hook, priority=40)
browse_hook_registry.register("memory_extract", _memory_extraction_hook, priority=90)
browse_hook_registry.register("conflict_detect", _conflict_detect_hook, priority=95)
browse_hook_registry.register("dm", _dm_hook, priority=100)
