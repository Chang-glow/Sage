from __future__ import annotations

import asyncio
import random
from datetime import date, datetime, timezone
from typing import Callable

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import config as yaml_config
from app.jobs.agent_lifecycle import run_online_flow, should_wake
from app.jobs.daily_schedule import generate_all_daily_schedules
from app.models.agent import Agent, AgentDailySchedule
from app.skills.llm_manager import create_llm_caller

logger = structlog.get_logger()

_SCHEDULES_GENERATED_DAYS: set[str] = set()


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
    today_str = str(date.today())
    if today_str in _SCHEDULES_GENERATED_DAYS:
        return

    # Check if it's the right hour (midnight UTC+8 = 16:00 UTC)
    now = datetime.now(timezone.utc)
    local_hour = (now.hour + 8) % 24
    target_hour = yaml_config.scheduler.daily_schedule_generation_hour
    if local_hour != target_hour:
        return

    # Check if any agent needs a schedule
    existing = await db.execute(select(AgentDailySchedule).where(AgentDailySchedule.date == date.today()).limit(1))
    if existing.scalar_one_or_none() is not None:
        # At least one agent has today's schedule; assume all done
        _SCHEDULES_GENERATED_DAYS.add(today_str)
        return

    logger.info("scheduler_generating_daily_schedules", date=today_str)
    count = await generate_all_daily_schedules(db, llm_caller)
    if count > 0:
        await db.commit()
        logger.info("scheduler_daily_schedules_done", count=count, date=today_str)
    _SCHEDULES_GENERATED_DAYS.add(today_str)


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
