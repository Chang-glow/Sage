"""Usage tracker — record + query API calls and agent token consumption.

Interface only — not wired into any production code path yet.
Import and call from wherever API calls or LLM invocations happen.

Usage:
    from app.engine.usage_tracker import record_api_call, record_token_usage

    await record_api_call(db, source="bing_search", count=1)
    await record_token_usage(db, agent_id=str(agent.id), source="deepseek_chat", tokens=1420)
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

import structlog
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.usage import UsageRecord

logger = structlog.get_logger()


async def record_api_call(
    db: AsyncSession,
    source: str,
    count: int = 1,
    agent_id: str | None = None,
    cost_estimate: float | None = None,
    metadata: dict[str, Any] | None = None,
) -> UsageRecord:
    """Record an external API call.

    Args:
        db: database session (caller must commit)
        source: "bing_search", "rss_feed", etc.
        count: number of calls (default 1)
        agent_id: optional agent UUID string that triggered the call
        cost_estimate: optional USD cost
        metadata: optional extra context (endpoint, query, ...)

    Returns the created UsageRecord (not yet committed).
    """
    record = UsageRecord(
        record_type="api_call",
        source=source,
        agent_id=uuid.UUID(agent_id) if agent_id else None,
        quantity=count,
        cost_estimate=cost_estimate,
        metadata_json=metadata,
    )
    db.add(record)
    logger.debug("api_call_recorded", source=source, count=count, agent_id=agent_id)
    return record


async def record_token_usage(
    db: AsyncSession,
    agent_id: str,
    source: str,
    tokens: int,
    cost_estimate: float | None = None,
    metadata: dict[str, Any] | None = None,
) -> UsageRecord:
    """Record LLM token consumption for an agent.

    Args:
        db: database session (caller must commit)
        agent_id: agent UUID string
        source: "deepseek_chat", "siliconflow", etc.
        tokens: total tokens used (prompt + completion)
        cost_estimate: optional USD cost
        metadata: optional extra context (model name, prompt/completion split)

    Returns the created UsageRecord (not yet committed).
    """
    record = UsageRecord(
        record_type="token_usage",
        source=source,
        agent_id=uuid.UUID(agent_id),
        quantity=tokens,
        cost_estimate=cost_estimate,
        metadata_json=metadata,
    )
    db.add(record)
    logger.debug("token_usage_recorded", source=source, tokens=tokens, agent_id=agent_id)
    return record


async def get_daily_usage(
    db: AsyncSession,
    target_date: date | None = None,
) -> dict[str, Any]:
    """Get aggregated usage for a given date (default today UTC).

    Returns:
        {date, api_calls: {source: count}, tokens: {source: count}, total_api_calls, total_tokens}
    """
    if target_date is None:
        target_date = date.today()

    start = datetime(target_date.year, target_date.month, target_date.day, tzinfo=timezone.utc)
    end = start + timedelta(days=1)

    # API calls
    api_result = await db.execute(
        select(UsageRecord.source, func.sum(UsageRecord.quantity).label("total"))
        .where(
            UsageRecord.record_type == "api_call",
            UsageRecord.created_at >= start,
            UsageRecord.created_at < end,
        )
        .group_by(UsageRecord.source)
    )
    api_calls: dict[str, int] = {}
    for row in api_result:
        api_calls[str(row[0])] = int(row[1] or 0)

    # Token usage
    token_result = await db.execute(
        select(UsageRecord.source, func.sum(UsageRecord.quantity).label("total"))
        .where(
            UsageRecord.record_type == "token_usage",
            UsageRecord.created_at >= start,
            UsageRecord.created_at < end,
        )
        .group_by(UsageRecord.source)
    )
    tokens: dict[str, int] = {}
    for row in token_result:
        tokens[str(row[0])] = int(row[1] or 0)

    return {
        "date": str(target_date),
        "api_calls": api_calls,
        "tokens": tokens,
        "total_api_calls": sum(api_calls.values()),
        "total_tokens": sum(tokens.values()),
    }


async def get_agent_usage(
    db: AsyncSession,
    agent_id: str,
    days: int = 30,
) -> dict[str, Any]:
    """Get token + API usage for a specific agent over the last N days.

    Returns:
        {agent_id, days, total_tokens, tokens_by_source: {source: count},
         total_api_calls, api_calls_by_source: {source: count}}
    """
    since = datetime.now(timezone.utc) - timedelta(days=days)

    # Token usage
    token_result = await db.execute(
        select(UsageRecord.source, func.sum(UsageRecord.quantity).label("total"))
        .where(
            UsageRecord.record_type == "token_usage",
            UsageRecord.agent_id == uuid.UUID(agent_id),
            UsageRecord.created_at >= since,
        )
        .group_by(UsageRecord.source)
    )
    tokens_by_source: dict[str, int] = {}
    for row in token_result:
        tokens_by_source[str(row[0])] = int(row[1] or 0)

    # API calls (triggered by this agent)
    api_result = await db.execute(
        select(UsageRecord.source, func.sum(UsageRecord.quantity).label("total"))
        .where(
            UsageRecord.record_type == "api_call",
            UsageRecord.agent_id == uuid.UUID(agent_id),
            UsageRecord.created_at >= since,
        )
        .group_by(UsageRecord.source)
    )
    api_by_source: dict[str, int] = {}
    for row in api_result:
        api_by_source[str(row[0])] = int(row[1] or 0)

    return {
        "agent_id": agent_id,
        "days": days,
        "total_tokens": sum(tokens_by_source.values()),
        "tokens_by_source": tokens_by_source,
        "total_api_calls": sum(api_by_source.values()),
        "api_calls_by_source": api_by_source,
    }
