from __future__ import annotations

import asyncio
import random
from datetime import date, datetime, timezone
from typing import Callable

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import config as yaml_config
from app.engine.daily_tasks import daily_task_registry
from app.jobs.agent_lifecycle import run_online_flow, should_wake
from app.jobs.daily_schedule import generate_all_daily_schedules
from app.models.agent import Agent, AgentDailySchedule
from app.skills.llm_manager import create_llm_caller

logger = structlog.get_logger()

_SCHEDULES_GENERATED_DAYS: set[str] = set()

async def decay_slangs(db, llm_caller) -> None:
    """Daily task: decay personal_affinity for slangs not used recently."""
    from app.engine.feature_flags import plugin_registry

    if not plugin_registry.is_enabled("slang"):
        return

    from datetime import timedelta

    from app.models.slang import AgentSlang

    result = await db.execute(select(AgentSlang))
    all_records = list(result.scalars().all())
    if not all_records:
        return

    now = datetime.now(timezone.utc)
    threshold = now - timedelta(days=7)
    decayed = 0

    for a in all_records:
        last_use = a.last_used_at or a.learned_at
        if last_use and last_use < threshold and a.personal_affinity > 0.05:
            a.personal_affinity = round(max(0.05, a.personal_affinity - 0.05), 2)
            decayed += 1

    if decayed:
        logger.info("slang_decay_done", decayed=decayed, total=len(all_records))


async def consolidate_memories_task(db, llm_caller: Callable) -> None:
    """Daily task: run memory consolidation for all active agents."""
    from app.engine.memory_engine import consolidate_agent_memories
    from app.models.agent import Agent

    result = await db.execute(select(Agent).where(Agent.status == "active"))
    agents = list(result.scalars().all())

    consolidated = 0
    for agent in agents:
        if not (agent.solidified_memories):
            continue
        try:
            await consolidate_agent_memories(agent, db, llm_caller)
            consolidated += 1
        except Exception:
            logger.warning("consolidate_agent_failed", agent_id=str(agent.id))

    if consolidated:
        logger.info("consolidate_memories_done", agents=consolidated)


async def memory_cleanup_task(db, llm_caller: Callable) -> None:
    """Daily task (midnight): clean expired fragments + evict over-capacity for all active agents."""
    from app.engine.memory_engine import cleanup_agent_memories, evict_over_capacity
    from app.models.agent import Agent

    result = await db.execute(select(Agent).where(Agent.status == "active"))
    agents = list(result.scalars().all())

    total_expired = 0
    total_evicted = 0
    for agent in agents:
        if not agent.solidified_memories:
            continue
        try:
            expired = cleanup_agent_memories(agent)
            total_expired += len(expired)
            evicted = evict_over_capacity(agent)
            total_evicted += len(evicted)
        except Exception:
            logger.warning("memory_cleanup_agent_failed", agent_id=str(agent.id))

    if total_expired or total_evicted:
        logger.info("memory_cleanup_done", expired=total_expired, evicted=total_evicted, agents=len(agents))


async def intimacy_maintenance_task(db, llm_caller: Callable) -> None:
    """Daily task (midnight): decay stale intimacy + archive cold relationships."""
    from app.engine.memory_engine import decay_all_intimacy, archive_cold_relationships

    decayed = await decay_all_intimacy(db)
    archived = await archive_cold_relationships(db)

    if decayed or archived:
        logger.info("intimacy_maintenance_done", decayed=decayed, archived=archived)


async def sage_news_task(db, llm_caller: Callable) -> None:
    """Daily task (10:00): generate Sage daily news post."""
    from app.models.agent import Agent
    from app.models.post import Post
    from app.skills.executor import execute

    sage_result = await db.execute(
        select(Agent).where(Agent.nickname == "Sage", Agent.status == "system")
    )
    sage = sage_result.scalar_one_or_none()
    if sage is None:
        logger.warning("sage_agent_not_found")
        return

    # Gather city events from external topics
    from app.models.external_topic import Topic
    topics_result = await db.execute(select(Topic).limit(10))
    topics = list(topics_result.scalars().all())
    external_text = "\n".join(
        f"- {t.title}: {t.summary or ''}" for t in topics
    ) if topics else "今日无特别外部事件"

    ctx = {
        "city_events_today": external_text,
        "weather_season": "五月 · 初夏，微暖",
        "external_topics": external_text,
        "recent_community_trends": "（社区趋势数据由系统收集）",
    }

    result = await execute("sage_news", ctx, llm_caller=llm_caller, agent_id=str(sage.id), db=db)
    if result.status != "success" or not isinstance(result.parsed, dict):
        logger.warning("sage_news_failed", status=result.status)
        return

    parsed = result.parsed
    title = parsed.get("title", "平陵新闻")
    content = parsed.get("content", "")

    post = Post(
        author_id=sage.id,
        title=title,
        content=content,
        is_hidden=False,
    )
    db.add(post)
    await db.commit()
    logger.info("sage_news_published", post_id=str(post.id))


async def sage_summary_task(db, llm_caller: Callable) -> None:
    """Daily task (23:30): generate Sage community daily summary."""
    from app.models.agent import Agent
    from app.models.post import Post
    from app.skills.executor import execute

    sage_result = await db.execute(
        select(Agent).where(Agent.nickname == "Sage", Agent.status == "system")
    )
    sage = sage_result.scalar_one_or_none()
    if sage is None:
        logger.warning("sage_agent_not_found")
        return

    # Gather today's stats
    from app.models.bar import Bar
    from datetime import date

    today = date.today()

    bars_result = await db.execute(select(Bar).limit(10))
    bars = list(bars_result.scalars().all())
    active_bars_text = "\n".join(f"- {b.name}" for b in bars) if bars else "暂无活跃吧"

    # Hot posts
    from app.models.post import Post as PostModel
    hot_result = await db.execute(
        select(PostModel).order_by(PostModel.reply_count.desc()).limit(5)
    )
    hot_posts = list(hot_result.scalars().all())
    hot_text = "\n".join(
        f"- 《{p.title}》(作者: {p.author.nickname if p.author else '未知'}, 回复: {p.reply_count})"
        for p in hot_posts
    ) if hot_posts else "今日暂无热门帖子"

    ctx = {
        "hot_posts": hot_text,
        "active_bars": active_bars_text,
        "active_agents": "（统计中）",
        "total_posts": "（统计中）",
        "total_replies": "（统计中）",
        "key_events": "今日暂无特别关键事件",
    }

    result = await execute("sage_summary", ctx, llm_caller=llm_caller, agent_id=str(sage.id), db=db)
    if result.status != "success" or not isinstance(result.parsed, dict):
        logger.warning("sage_summary_failed", status=result.status)
        return

    parsed = result.parsed
    title = parsed.get("title", "夕照雅巷 · 社区总结")
    content = parsed.get("content", "")

    post = Post(
        author_id=sage.id,
        title=title,
        content=content,
        is_hidden=False,
    )
    db.add(post)
    await db.commit()
    logger.info("sage_summary_published", post_id=str(post.id))


async def check_promise_deadlines_task(db, llm_caller: Callable) -> None:
    """Daily task: update expectation values + mark broken promises past deadline."""
    from app.engine.feature_flags import plugin_registry
    if not plugin_registry.is_enabled("promises"):
        return

    from app.models.promise import Promise
    from app.models.agent import Agent
    from app.engine.promise_engine import check_promise_status, calculate_expectation
    from app.jobs.social_engine import adjust_after_promise_broken
    from app.jobs.notification_engine import _create_notification

    result = await db.execute(
        select(Promise).where(Promise.status == "pending")
    )
    pending_promises = result.scalars().all()

    broken_count = 0
    expectation_updated = 0
    for promise in pending_promises:
        # Update expectation for every pending promise
        try:
            requester_result = await db.execute(select(Agent).where(Agent.id == promise.requester_id))
            requester = requester_result.scalar_one_or_none()
            promiser_result = await db.execute(select(Agent).where(Agent.id == promise.promiser_id))
            promiser = promiser_result.scalar_one_or_none()
            if requester is not None and promiser is not None:
                promise.expectation = await calculate_expectation(
                    promise, requester, promiser, llm_caller,
                )
                expectation_updated += 1
        except Exception:
            logger.warning("expectation_calc_failed", promise_id=str(promise.id))

        # Check broken status (only for promises with deadline)
        if promise.due_time is None:
            continue
        status = check_promise_status(promise)
        if status == "broken":
            promise.status = "broken"
            promise.fulfilled_at = datetime.now(timezone.utc)
            db.add(promise)

            try:
                await adjust_after_promise_broken(
                    promise.requester_id, promise.promiser_id,
                    promise.content, db,
                )
            except Exception:
                logger.warning("promise_broken_penalty_failed", promise_id=str(promise.id))

            # Notify both parties
            try:
                await _create_notification(
                    str(promise.promiser_id), str(promise.requester_id),
                    "promise_broken", db,
                    message=f"你未能履行承诺：「{promise.content}」",
                    priority="high",
                )
                await _create_notification(
                    str(promise.requester_id), str(promise.promiser_id),
                    "promise_broken", db,
                    message=f"对方未履行承诺：「{promise.content}」",
                    priority="medium",
                )
            except Exception:
                pass

            broken_count += 1

    if broken_count > 0 or expectation_updated > 0:
        await db.commit()
        logger.info("promise_deadline_check_done", broken=broken_count,
                    expectation_updated=expectation_updated, total=len(pending_promises))


async def refresh_topics_task(db, llm_caller: Callable) -> None:
    """Daily task: refresh external topic pool via Bing API (时政) + RSS feeds (其他).

    Config structure in config.yaml → topics:
      - bing_queries: [{query, category}]  — 国际局势, 国内热点
      - rss_feeds:    [{url, category}]    — 娱乐, 二次元, 游戏, 商业, 当地, 文学, 科创, 教育
    """
    from app.engine.topic_fetcher import refresh_topic_pool, refresh_topic_pool_from_rss

    topics_cfg = getattr(yaml_config, "topics", None)
    bing_list: list[dict[str, str]] = []
    rss_list: list[dict[str, str]] = []
    if topics_cfg is not None:
        try:
            bing_list = getattr(topics_cfg, "bing_queries", [])
        except AttributeError:
            pass
        try:
            rss_list = getattr(topics_cfg, "rss_feeds", [])
        except AttributeError:
            pass

    if not bing_list and not rss_list:
        logger.info("refresh_topics_skipped", reason="no bing_queries or rss_feeds configured")
        return

    bing_added = 0
    rss_added = 0

    if bing_list:
        bing_added = await refresh_topic_pool(db, bing_list)

    if rss_list:
        rss_added = await refresh_topic_pool_from_rss(db, rss_list)

    if bing_added or rss_added:
        logger.info("refresh_topics_done", bing_added=bing_added, rss_added=rss_added)


# Register daily tasks
daily_task_registry.register(
    "generate_daily_schedules",
    generate_all_daily_schedules,
    hour=yaml_config.scheduler.daily_schedule_generation_hour,
    minute=0,
)
daily_task_registry.register("slang_decay", decay_slangs, hour=0, minute=7)
daily_task_registry.register("memory_consolidate", consolidate_memories_task, hour=0, minute=13)
daily_task_registry.register("memory_cleanup", memory_cleanup_task, hour=0, minute=15)
daily_task_registry.register("intimacy_maintenance", intimacy_maintenance_task, hour=0, minute=17)
daily_task_registry.register("refresh_topics", refresh_topics_task, hour=6, minute=0)
daily_task_registry.register("sage_news", sage_news_task, hour=10, minute=0)
daily_task_registry.register("sage_summary", sage_summary_task, hour=23, minute=30)
daily_task_registry.register(
    "promise_deadline_check",
    check_promise_deadlines_task,
    hour=yaml_config.promises.deadline_check_hour,
    minute=yaml_config.promises.deadline_check_minute,
)


async def run_scheduler_loop(
    session_factory: async_sessionmaker,
    stop_event: asyncio.Event,
) -> None:
    logger.info("scheduler_started", scan_interval_min=yaml_config.scheduler.scan_interval_minutes)

    llm_caller = create_llm_caller()

    while not stop_event.is_set():
        try:
            async with session_factory() as db:
                # 午夜生成结构化日程
                await _maybe_generate_schedules(db, llm_caller)

                # 扫描可唤醒 Agent
                agents = await _scan_wakeable_agents(db)

                if agents:
                    logger.info("scheduler_wake_scan", candidates=len(agents))

                # 分批启动上线流程
                tasks = []
                for agent in agents:
                    t = asyncio.create_task(_wake_agent_with_db(agent, session_factory, llm_caller))
                    tasks.append(t)

                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)

        except Exception:
            logger.exception("scheduler_cycle_error")

        # 等待下一次扫描
        try:
            await asyncio.wait_for(
                stop_event.wait(),
                timeout=yaml_config.scheduler.scan_interval_minutes * 60,
            )
        except asyncio.TimeoutError:
            pass


async def _maybe_generate_schedules(db, llm_caller: Callable) -> None:
    """Run daily tasks due at the current hour:minute via DailyTaskRegistry."""
    now = datetime.now(timezone.utc)
    local_hour = (now.hour + 8) % 24
    local_minute = now.minute

    due_tasks = daily_task_registry.get_due(local_hour, local_minute)
    if not due_tasks:
        return

    for task_name, task_fn in due_tasks:
        today_str = str(date.today())
        dedup_key = f"{today_str}:{task_name}"
        if dedup_key in _SCHEDULES_GENERATED_DAYS:
            continue

        try:
            logger.info("daily_task_start", task_name=task_name, hour=local_hour, minute=local_minute)
            await task_fn(db, llm_caller)
            await db.commit()
            logger.info("daily_task_done", task_name=task_name)
        except Exception:
            logger.exception("daily_task_failed", task_name=task_name)
        _SCHEDULES_GENERATED_DAYS.add(dedup_key)


async def _scan_wakeable_agents(db) -> list[Agent]:
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(Agent).where(
            Agent.status == "active",
            Agent.is_online == False,  # noqa: E712
        )
    )
    candidates = []

    for agent in result.scalars().all():
        schedule = agent.schedule
        if schedule is None:
            continue
        if should_wake(agent, schedule, now):
            candidates.append(agent)

    # Shuffle to avoid deterministic order
    random.shuffle(candidates)
    return candidates


async def _wake_agent_with_db(agent: Agent, session_factory: async_sessionmaker, llm_caller: Callable) -> None:
    # Random delay (0-15 min) for natural distribution
    delay = random.randint(0, yaml_config.scheduler.wake_random_delay_max_minutes * 60)
    if delay > 0:
        await asyncio.sleep(delay)

    async with session_factory() as db:
        # Re-fetch agent within the new session
        result = await db.execute(select(Agent).where(Agent.id == agent.id))
        fresh_agent = result.scalar_one_or_none()
        if fresh_agent is None or fresh_agent.is_online:
            return

        await run_online_flow(fresh_agent, db, llm_caller)
