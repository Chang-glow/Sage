from __future__ import annotations

import asyncio
import random
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
from app.skills.executor import execute
from app.skills.skill_utils import build_agent_context

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
        result = await execute("offline_summary", ctx, llm_caller=llm_caller, agent_id=agent_id)
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
        result = await execute("post_decision", decision_ctx, llm_caller=llm_caller, agent_id=agent_id)
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

    # Check post-level threshold for the target bar
    if target_bar != "广场":
        bar_result = await db.execute(
            select(Bar).where(Bar.name == target_bar)
        )
        bar = bar_result.scalar_one_or_none()
        if bar is not None:
            threshold = getattr(bar, "post_level_threshold", 4)
            level_result = await db.execute(
                select(AgentBarLevel).where(
                    AgentBarLevel.agent_id == agent.id,
                    AgentBarLevel.bar_id == bar.id,
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
        gen_result = await execute("post_generation", gen_ctx, llm_caller=llm_caller, agent_id=agent_id)
    except Exception:
        logger.exception("post_generation_error", agent_id=agent_id)
        return

    if gen_result.status != "success" or not isinstance(gen_result.parsed, dict):
        return

    title = gen_result.parsed.get("title", "")
    content = gen_result.parsed.get("content", "")
    if not content.strip():
        return

    post = Post(
        author_id=agent.id,
        title=title[:200],
        content=content,
        urge_type=urge_type,
    )
    db.add(post)
    await db.commit()

    logger.info("post_created", agent_id=agent_id, post_id=str(post.id), urge_type=urge_type)

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
        result = await execute("bar_selection", bar_ctx, llm_caller=llm_caller, agent_id=agent_id)
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
                                agent_id, post, reply_result.get("content", ""), "", llm_caller,
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
