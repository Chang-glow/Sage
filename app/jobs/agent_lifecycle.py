from __future__ import annotations

import asyncio
import random
from datetime import date, datetime, timezone
from typing import Callable

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import config as yaml_config
from app.jobs.concurrency import get_agent_semaphore
from app.models.agent import ActivityLog, Agent, AgentDailySchedule
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

    # Step 2: Post urge check (placeholder — Phase 3 接管)
    if urge_intensity > 0.6:
        logger.info("post_urge_triggered", agent_id=agent_id, urge_type=urge_type, intensity=urge_intensity)
        # TODO Phase 3: execute("post_decision", ...) → execute("post_generation", ...)

    # Step 3: Bar selection (placeholder — Phase 3 接管)
    # TODO Phase 3: execute("bar_selection", ...)
    logger.info("bar_selection_placeholder", agent_id=agent_id)

    # Step 4: Notification processing (placeholder — Phase 3 接管)
    # TODO Phase 3: pull unread notifications, prioritize

    # Step 5: Browse & interact (placeholder — Phase 3 接管)
    # TODO Phase 3: browse feed, reply decisions

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
