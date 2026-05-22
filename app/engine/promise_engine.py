"""Promise & expectation engine.

_parse_due_time: convert natural-language time estimates to datetimes.
calculate_expectation: cheap-model call to estimate 0-100 expectation value.
check_promise_status: determine whether a promise has timed out.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Callable


def _parse_due_time(estimate: str, created_at: datetime) -> datetime | None:
    """Convert LLM natural-language time estimate to a concrete datetime.

    Supported patterns:
    - "Nd天后" / "N天后" / "in N days" → created_at + N days
    - "明天" / "tomorrow" → created_at + 1 day
    - "后天" → created_at + 2 days
    - "下周" / "next week" → created_at + 7 days
    - "下周五" / "next Friday" → next occurrence of that weekday
    - Unparseable / empty → None
    """
    if not estimate or not isinstance(estimate, str):
        return None

    text = estimate.strip()

    # "N天后" / "N 天后" / "in N days"
    m = re.search(r"(\d+)\s*天[后内]|in\s+(\d+)\s+days?", text)
    if m:
        days = int(m.group(1) or m.group(2))
        return created_at + timedelta(days=days)

    # "N小时后" / "in N hours"
    m = re.search(r"(\d+)\s*小时[后内]|in\s+(\d+)\s+hours?", text)
    if m:
        hours = int(m.group(1) or m.group(2))
        return created_at + timedelta(hours=hours)

    # "明天" / "tomorrow"
    if "明天" in text or "tomorrow" in text.lower():
        return created_at + timedelta(days=1)

    # "后天"
    if "后天" in text:
        return created_at + timedelta(days=2)

    # "下周" / "next week"
    if "下周" in text or "next week" in text.lower():
        return created_at + timedelta(days=7)

    # "下个月" / "next month"
    if "下个?月" in text or "next month" in text.lower():
        return created_at + timedelta(days=30)

    # Weekday parsing: "下周X", "下周五", "next Friday"
    weekday_map = {
        "一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6,
        "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
        "friday": 4, "saturday": 5, "sunday": 6,
    }
    for key, target_wd in weekday_map.items():
        if key in text.lower():
            current_wd = created_at.weekday()
            days_until = (target_wd - current_wd) % 7
            if days_until == 0:
                days_until = 7  # "下周五" means next week, not today
            return created_at + timedelta(days=days_until)

    # Unparseable — return None for no deadline
    return None


async def calculate_expectation(
    promise,  # Promise
    requester,  # Agent
    promiser,  # Agent
    llm_caller: Callable,
) -> float:
    """Estimate the requester's current expectation for this promise (0-100).

    Delegates to a cheap model. Inputs: time until due, importance,
    requester personality — the model decides the expectation curve shape.
    """
    from app.skills.executor import execute

    now = datetime.now(timezone.utc)

    if promise.due_time is not None:
        time_remaining = promise.due_time - now
        hours_remaining = max(0, time_remaining.total_seconds() / 3600)
        is_overdue = time_remaining.total_seconds() < 0
    else:
        hours_remaining = 999999  # no deadline
        is_overdue = False

    days_since_created = max(0, (now - promise.created_at).total_seconds() / 86400)

    pv = requester.personality_vector or {}
    personality_str = ", ".join(f"{k}={v:.2f}" for k, v in sorted(pv.items(), key=lambda x: x[1], reverse=True)[:5])

    ctx = {
        "promise_content": promise.content,
        "importance": promise.importance,
        "hours_remaining": round(hours_remaining, 1),
        "is_overdue": is_overdue,
        "days_since_created": round(days_since_created, 1),
        "has_deadline": promise.due_time is not None,
        "requester_name": requester.nickname,
        "requester_personality": personality_str or "普通",
    }

    result = await execute("expectation_calculation", ctx, llm_caller=llm_caller)
    if result.status == "success" and isinstance(result.parsed, dict):
        val = float(result.parsed.get("expectation", 50))
        return max(0.0, min(100.0, val))
    return 50.0


def check_promise_status(promise) -> str | None:
    """Check whether a pending promise has timed out.

    Returns 'broken' if now > due_time + (float_value minutes).
    Returns None if still within the grace period or due_time is NULL.
    """
    if promise.due_time is None:
        return None

    now = datetime.now(timezone.utc)
    cutoff = promise.due_time

    if promise.float_value is not None and promise.float_value > 0:
        cutoff = cutoff + timedelta(minutes=float(promise.float_value))

    if now > cutoff:
        return "broken"
    return None
