"""Topic fetcher — web search → external_topic pool refresh.

Search provider: Bing Web Search API v7.
Content scheme (query/category list) configured externally — this module
provides the search interface and pool refresh pipeline.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings

logger = structlog.get_logger()

BING_ENDPOINT = "https://api.bing.microsoft.com/v7.0/search"


async def bing_search(query: str, limit: int = 5) -> list[dict[str, Any]]:
    """Search Bing Web Search API, return structured topic dicts.

    Each result: {title, snippet, url, source: "web"}
    Returns empty list on failure, rate limit, or missing API key.
    """
    if not query or not query.strip():
        return []

    api_key = settings.bing_search_api_key
    if not api_key:
        logger.warning("bing_search_no_api_key")
        return []

    import httpx

    headers = {"Ocp-Apim-Subscription-Key": api_key}
    params: dict[str, Any] = {
        "q": query.strip(),
        "count": limit,
        "mkt": "zh-CN",
        "safeSearch": "Moderate",
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(BING_ENDPOINT, headers=headers, params=params)

        if resp.status_code == 429:
            logger.warning("bing_search_rate_limited")
            return []
        if resp.status_code != 200:
            logger.warning("bing_search_http_error", status=resp.status_code)
            return []

        data = resp.json()
        pages = data.get("webPages", {}).get("value", [])
    except Exception:
        logger.exception("bing_search_request_failed", query=query[:100])
        return []

    results: list[dict[str, Any]] = []
    for p in pages:
        results.append({
            "title": p.get("name", "")[:300],
            "snippet": p.get("snippet", "")[:500],
            "url": p.get("url", ""),
            "source": "web",
        })
    return results


async def refresh_topic_pool(
    db: AsyncSession,
    queries: list[dict[str, str]] | None = None,
) -> int:
    """Fetch topics from web search and upsert into external_topic table.

    Args:
        db: database session
        queries: list of {query, category} dicts. If None/empty, returns 0.

    Returns count of newly added topics (duplicates by title are skipped).
    """
    if not queries:
        return 0

    from app.models.external_topic import Topic

    total = 0
    for q in queries:
        query_text = q.get("query", "")
        category = q.get("category", "综合")
        if not query_text:
            continue

        results = await bing_search(query_text)
        for r in results:
            title = r.get("title", "")
            if not title:
                continue

            # Deduplicate by title
            existing = await db.execute(
                select(Topic).where(Topic.title == title)
            )
            if existing.scalars().first() is not None:
                continue

            topic = Topic(
                title=title,
                summary=r.get("snippet", ""),
                content=r.get("snippet", ""),
                source=r.get("source", "web"),
                category=category,
                fetched_at=datetime.now(timezone.utc),
            )
            db.add(topic)
            total += 1

    if total > 0:
        await db.commit()
        logger.info("topic_pool_refreshed", added=total, queries=len(queries))

    return total
