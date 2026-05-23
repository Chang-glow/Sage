"""Search engine: internal (posts/replies/bars/agents) + external (topic pool)."""

from __future__ import annotations

from typing import Any


async def execute_internal_search(query: str, db) -> list[dict[str, Any]]:
    """Search posts, replies, bars, and agents for the given query.

    Uses PostgreSQL ILIKE for case-insensitive matching.
    """
    if not query or not query.strip():
        return []

    q = query.strip()
    like = f"%{q}%"

    from sqlalchemy import or_, select
    from sqlalchemy.orm import selectinload
    from app.models.post import Post, Reply
    from app.models.bar import Bar
    from app.models.agent import Agent

    results: list[dict[str, Any]] = []

    # Search posts (eager-load relationships for async safety)
    post_result = await db.execute(
        select(Post).options(
            selectinload(Post.author),
            selectinload(Post.bar),
        ).where(
            or_(Post.title.ilike(like), Post.content.ilike(like))
        ).limit(10)
    )
    for p in post_result.scalars().all():
        bar_name = p.bar.name if p.bar else "未知"
        author_name = p.author.nickname if p.author else "未知"
        results.append({
            "type": "post",
            "id": str(p.id),
            "title": p.title or "",
            "snippet": (p.content or "")[:200],
            "source": bar_name,
            "author": author_name,
        })

    # Search replies
    reply_result = await db.execute(
        select(Reply).where(Reply.content.ilike(like)).limit(10)
    )
    for r in reply_result.scalars().all():
        results.append({
            "type": "reply",
            "id": str(r.id),
            "title": "",
            "snippet": (r.content or "")[:200],
            "source": f"回复 (post={r.post_id})",
            "author": str(r.author_id),
        })

    # Search bars
    bar_result = await db.execute(
        select(Bar).where(
            or_(Bar.name.ilike(like), Bar.description.ilike(like))
        ).limit(5)
    )
    for b in bar_result.scalars().all():
        results.append({
            "type": "bar",
            "id": str(b.id),
            "title": b.name or "",
            "snippet": (b.description or "")[:200],
            "source": "吧组",
            "author": "",
        })

    # Search agents by nickname
    agent_result = await db.execute(
        select(Agent).where(Agent.nickname.ilike(like)).limit(5)
    )
    for a in agent_result.scalars().all():
        results.append({
            "type": "agent",
            "id": str(a.id),
            "title": a.nickname or "",
            "snippet": f"{a.occupation or ''} · {a.district or ''}",
            "source": "用户",
            "author": "",
        })

    return results


async def execute_external_search(query: str, db) -> list[dict[str, Any]]:
    """Search the external topic pool (pre-fetched news/headlines).

    Agents think they're searching the internet — actually a curated pool.
    """
    if not query or not query.strip():
        return []

    q = query.strip()
    like = f"%{q}%"

    from sqlalchemy import or_, select
    from app.models.external_topic import Topic

    result = await db.execute(
        select(Topic).where(
            or_(Topic.title.ilike(like), Topic.summary.ilike(like), Topic.content.ilike(like))
        ).limit(10)
    )

    results: list[dict[str, Any]] = []
    for t in result.scalars().all():
        results.append({
            "type": "topic",
            "id": str(t.id),
            "title": t.title or "",
            "snippet": (t.summary or t.content or "")[:200],
            "source": t.source or "网络",
            "category": t.category or "",
        })
    return results


def format_search_results(results: list[dict[str, Any]] | None) -> str:
    """Format search results into text for injection into reply context."""
    if not results:
        return ""

    lines = ["【搜索结果】"]
    for i, r in enumerate(results[:5], 1):
        type_label = _type_label(r.get("type", ""))
        lines.append(
            f"{i}. [{type_label}] {r.get('title', '无标题')} — "
            f"{r.get('snippet', '')[:100]}"
        )
        if r.get("source"):
            lines.append(f"   来源: {r['source']}")

    return "\n".join(lines)


def _type_label(t: str) -> str:
    return {"post": "帖子", "reply": "回复", "bar": "吧组", "agent": "用户", "topic": "资讯"}.get(t, t)
