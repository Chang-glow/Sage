from __future__ import annotations

import random
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import structlog
import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import config as yaml_config
from app.models.agent import Agent, AgentDailySchedule
from app.skills.executor import execute

logger = structlog.get_logger()

_TEMPLATES: dict | None = None
_CALENDAR: dict | None = None
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _load_templates() -> dict:
    global _TEMPLATES
    if _TEMPLATES is None:
        path = _PROJECT_ROOT / "world" / "schedule_templates.yaml"
        with open(path, encoding="utf-8") as f:
            _TEMPLATES = yaml.safe_load(f)
    return _TEMPLATES


def _load_calendar() -> dict:
    global _CALENDAR
    if _CALENDAR is None:
        path = _PROJECT_ROOT / "world" / "calendar.yaml"
        with open(path, encoding="utf-8") as f:
            _CALENDAR = yaml.safe_load(f)
    return _CALENDAR


def _pick_template_id(agent: Agent) -> str:
    age = agent.age
    occupation = (agent.occupation or "").strip()
    boarding = agent.boarding

    if occupation == "学生":
        if age >= 18:
            return "student_college"
        if boarding:
            return "student_boarding"
        return "student_day"

    if occupation in ("初入职场", "普工", "文员", "销售", "会计", "医护人员", "外卖员", "快递员", "网约车司机"):
        agent_id = str(agent.id)
        if random.Random(agent_id).random() < 0.25:
            return "worker_overtime"
        return "worker_regular"

    if occupation == "自由职业":
        return "freelancer"

    if occupation == "个体户":
        if random.Random(str(agent.id)).random() < 0.3:
            return "worker_overtime"
        return "freelancer"

    if age >= 36:
        return "middle_age"

    return "worker_regular"


def _apply_chronotype_offset(block: dict, chronotype: str) -> dict:
    data = _load_templates()
    offsets = data.get("chronotype_offsets", {})
    block = dict(block)

    if chronotype == "early":
        offset_min = offsets.get("early", -45)
        block["time_start"] = _shift_time(block["time_start"], offset_min)
        block["time_end"] = _shift_time(block["time_end"], offset_min)
    elif chronotype == "nightowl":
        offset_min = offsets.get("nightowl", 90)
        block["time_start"] = _shift_time(block["time_start"], offset_min)
        block["time_end"] = _shift_time(block["time_end"], offset_min)
    elif chronotype == "chaotic":
        lo, hi = offsets.get("chaotic_range", [-60, 60])
        offset_min = random.randint(lo, hi)
        block["time_start"] = _shift_time(block["time_start"], offset_min)
        block["time_end"] = _shift_time(block["time_end"], offset_min)
    else:  # normal
        jitter = random.randint(-30, 30)
        block["time_start"] = _shift_time(block["time_start"], jitter)
        block["time_end"] = _shift_time(block["time_end"], jitter)

    return block


def _shift_time(t_str: str, minutes: int) -> str:
    parts = t_str.split(":")
    h = int(parts[0])
    m = int(parts[1]) if len(parts) > 1 else 0
    total = h * 60 + m + minutes
    total = total % (24 * 60)
    return f"{total // 60:02d}:{total % 60:02d}"


def _check_calendar_hit(template_id: str, today: date) -> float | None:
    """返回命中的 activity_multiplier，未命中返回 None"""
    calendar = _load_calendar()
    for evt in calendar.get("events", []):
        start = date.fromisoformat(evt["date_start"])
        end = date.fromisoformat(evt["date_end"])
        if start <= today <= end:
            affects = evt.get("affects", [])
            if "all" in affects:
                return evt["activity_multiplier"]
            for aff in affects:
                if aff == template_id:
                    return evt["activity_multiplier"]
                if aff.endswith("_*"):
                    prefix = aff[:-2]
                    if template_id.startswith(prefix):
                        return evt["activity_multiplier"]
    return None


async def generate_daily_schedule(agent: Agent, today: date, db: AsyncSession, llm_caller=None) -> AgentDailySchedule:
    templates = _load_templates()
    template_id = _pick_template_id(agent)
    template = templates["templates"].get(template_id)
    if template is None:
        template = templates["templates"]["worker_regular"]

    chronotype = getattr(agent, "chronotype", "normal") or "normal"
    calendar_mult = _check_calendar_hit(template_id, today)

    timeline = []
    events = []

    for block in template["blocks"]:
        b = _apply_chronotype_offset(block, chronotype)

        # Calendar override: 考试周等将 is_free_time 设为 false
        if calendar_mult is not None and calendar_mult <= 0.2:
            b["is_free_time"] = False
            if "学习" not in b.get("direction", "") and "考试" not in b.get("direction", ""):
                b["direction"] = "复习备考"

        timeline.append({
            "label": b["label"],
            "time_start": b["time_start"],
            "time_end": b["time_end"],
            "is_free_time": b["is_free_time"],
        })

        # 仅为 is_free_time 块生成事件
        if b["is_free_time"] and llm_caller is not None:
            if random.random() < 0.4:
                ctx = {
                    "agent_name": agent.nickname,
                    "agent_age": str(agent.age),
                    "agent_occupation": agent.occupation or "未知",
                    "agent_personality": _describe_personality(agent),
                    "time_block_label": b["label"],
                    "time_block_time": f"{b['time_start']}-{b['time_end']}",
                    "time_block_direction": b.get("direction", ""),
                    "today_events_so_far": _format_events(events),
                    "life_history_sample": _format_life_history(agent),
                }
                try:
                    result = await execute(
                        "daily_event_generation",
                        ctx,
                        llm_caller=llm_caller,
                        agent_id=str(agent.id),
                        db=db,
                    )
                    if result.status == "success" and isinstance(result.parsed, dict):
                        evt = result.parsed
                        if evt.get("event") is not None:
                            events.append({
                                "time_block": b["label"],
                                "event": evt.get("event", ""),
                                "valence": evt.get("valence", "neutral"),
                                "impact": evt.get("impact", 0.5),
                            })
                except Exception:
                    logger.warning(
                        "daily_event_generation_failed",
                        agent_id=str(agent.id),
                        time_block=b["label"],
                    )

    schedule = AgentDailySchedule(
        agent_id=agent.id,
        date=today,
        timeline=timeline,
        events=events,
    )
    db.add(schedule)
    logger.info(
        "daily_schedule_generated",
        agent_id=str(agent.id),
        date=str(today),
        blocks=len(timeline),
        events=len(events),
    )
    return schedule


def _describe_personality(agent: Agent) -> str:
    pv = agent.personality_vector or {}
    if not pv:
        return "普通"
    sorted_traits = sorted(pv.items(), key=lambda x: x[1], reverse=True)
    return "、".join(f"{k}={v:.2f}" for k, v in sorted_traits[:3])


def _format_events(events: list[dict]) -> str:
    if not events:
        return "（暂无）"
    lines = []
    for e in events:
        lines.append(f"- [{e['time_block']}] {e['event']}（{e['valence']}）")
    return "\n".join(lines)


def _format_life_history(agent: Agent) -> str:
    lh = agent.life_history or []
    if not lh:
        return "（无）"
    sample = random.sample(lh, min(3, len(lh)))
    lines = []
    for entry in sample:
        lines.append(f"- {entry.get('age', '?')}岁: {entry.get('event', '')}")
    return "\n".join(lines) if lines else "（无）"


async def generate_all_daily_schedules(db: AsyncSession, llm_caller) -> int:
    today = date.today()
    result = await db.execute(
        select(Agent).where(
            Agent.status == "active",
        )
    )
    agents = result.scalars().all()

    count = 0
    for agent in agents:
        # Skip if already generated today
        existing = await db.execute(
            select(AgentDailySchedule).where(
                AgentDailySchedule.agent_id == agent.id,
                AgentDailySchedule.date == today,
            )
        )
        if existing.scalar_one_or_none() is not None:
            continue

        try:
            await generate_daily_schedule(agent, today, db, llm_caller)
            count += 1
        except Exception:
            logger.exception("daily_schedule_generation_failed", agent_id=str(agent.id))

    if count > 0:
        await db.commit()
    return count
