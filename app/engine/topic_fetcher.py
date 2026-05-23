"""Topic fetcher — web search + RSS → external_topic pool refresh.

Collection strategy (per 04-4-ex 新闻池配置规范):
  - Bing Web Search API v7 → 国际局势, 国内热点 (≤30 calls/day, free tier)
  - RSS / Atom feeds → 娱乐, 二次元, 游戏, 商业, 当地, 文学, 科创, 教育 (zero cost)
  - 官方社媒扫描 (B站/微博) → reserved for future implementation
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
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


async def fetch_rss_feed(url: str, category: str = "综合") -> list[dict[str, Any]]:
    """Fetch and parse an RSS/Atom feed, return structured topic dicts.

    Each result: {title, snippet, url, source: "rss"}
    Returns empty list on fetch failure, parse error, or empty feed.
    """
    if not url or not url.strip():
        return []

    import httpx

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url.strip(), headers={"User-Agent": "Sage/1.0"})
        if resp.status_code != 200:
            logger.warning("rss_feed_http_error", url=url[:80], status=resp.status_code)
            return []
        xml_text = resp.text
    except Exception:
        logger.exception("rss_feed_request_failed", url=url[:80])
        return []

    return _parse_rss_xml(xml_text, category, url)


def _parse_rss_xml(xml_text: str, category: str, feed_url: str) -> list[dict[str, Any]]:
    """Parse RSS 2.0 or Atom XML into topic dicts. Not async — pure CPU."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        logger.warning("rss_feed_parse_error", url=feed_url[:80])
        return []

    results: list[dict[str, Any]] = []
    ns = {"atom": "http://www.w3.org/2005/Atom"}

    # RSS 2.0: <channel> → <item>…
    for item in root.iter("item"):
        title = _text_of(item, "title")
        snippet = _text_of(item, "description")
        link = _text_of(item, "link")
        if title:
            results.append({
                "title": title[:300],
                "snippet": _strip_html(snippet)[:500] if snippet else "",
                "url": link or "",
                "source": "rss",
                "category": category,
            })

    # Atom: <feed> → <entry>…
    for entry in root.findall("atom:entry", ns):
        title = _text_of(entry, "atom:title", ns)
        summary = _text_of(entry, "atom:summary", ns)
        link_el = entry.find("atom:link", ns)
        link = link_el.attrib.get("href", "") if link_el is not None else ""
        if title:
            results.append({
                "title": title[:300],
                "snippet": _strip_html(summary)[:500] if summary else "",
                "url": link,
                "source": "rss",
                "category": category,
            })

    if not results:
        # Also try root-level elements directly (some feeds omit <channel>)
        for item in root.findall(".//item"):
            title = _text_of(item, "title")
            if title:
                results.append({
                    "title": title[:300],
                    "snippet": _strip_html(_text_of(item, "description"))[:500],
                    "url": _text_of(item, "link") or "",
                    "source": "rss",
                    "category": category,
                })

    return results


def _text_of(el: ET.Element, tag: str, ns: dict | None = None) -> str:
    child = el.find(tag, ns) if ns else el.find(tag)
    return (child.text or "").strip() if child is not None and child.text else ""


def _strip_html(text: str) -> str:
    """Crude HTML tag stripper — removes anything between < and >."""
    import re
    return re.sub(r"<[^>]*>", "", text)


async def _upsert_topics(
    db: AsyncSession, items: list[dict[str, Any]]
) -> int:
    """Insert new topics into DB, skipping duplicates by title. Returns count added."""
    if not items:
        return 0

    from app.models.external_topic import Topic

    added = 0
    for r in items:
        title = r.get("title", "")
        if not title:
            continue

        existing = await db.execute(select(Topic).where(Topic.title == title))
        if existing.scalars().first() is not None:
            continue

        topic = Topic(
            title=title,
            summary=r.get("snippet", ""),
            content=r.get("snippet", ""),
            source=r.get("source", "rss"),
            category=r.get("category", "综合"),
            fetched_at=datetime.now(timezone.utc),
        )
        db.add(topic)
        added += 1

    return added


async def refresh_topic_pool_from_rss(
    db: AsyncSession,
    feeds: list[dict[str, str]] | None = None,
) -> int:
    """Fetch topics from RSS feeds and upsert into external_topic table.

    Args:
        db: database session
        feeds: list of {url, category} dicts. If None/empty, returns 0.

    Returns count of newly added topics (duplicates by title are skipped).
    """
    if not feeds:
        return 0

    total = 0
    for f in feeds:
        url = f.get("url", "")
        category = f.get("category", "综合")
        if not url:
            continue

        results = await fetch_rss_feed(url, category)
        if results:
            added = await _upsert_topics(db, results)
            total += added

    if total > 0:
        await db.commit()
        logger.info("rss_topic_pool_refreshed", added=total, feeds=len(feeds))

    return total


async def refresh_topic_pool(
    db: AsyncSession,
    queries: list[dict[str, str]] | None = None,
) -> int:
    """Fetch topics from Bing Web Search API and upsert into external_topic table.

    Args:
        db: database session
        queries: list of {query, category} dicts. If None/empty, returns 0.

    Returns count of newly added topics (duplicates by title are skipped).
    """
    if not queries:
        return 0

    total = 0
    for q in queries:
        query_text = q.get("query", "")
        category = q.get("category", "综合")
        if not query_text:
            continue

        results = await bing_search(query_text)
        if results:
            added = await _upsert_topics(db, results)
            total += added
        try:
            from app.engine.usage_tracker import record_api_call
            await record_api_call(db, source="bing_search", count=1,
                metadata={"query": query_text[:100], "category": category, "results": len(results)})
        except Exception:
            pass

    await db.commit()
    logger.info("bing_topic_pool_refreshed", added=total, queries=len(queries))

    return total
