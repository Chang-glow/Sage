"""0.10.1_search TDD tests — search engine + internal/external search + result presentation."""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch


def _make_mock_agent(name="测试Agent", pv=None):
    import uuid as _uuid
    agent = MagicMock()
    agent.id = _uuid.uuid4()
    agent.nickname = name
    agent.personality_vector = pv or {"开放": 0.7, "外向": 0.5}
    agent.interests = {"categories": ["科技", "游戏"]}
    agent.occupation = "学生"
    agent.age = 25
    agent.gender = "男"
    agent.education = "本科"
    agent.district = "平陵市"
    agent.persona_prompt = ""
    agent.income_level = "中等"
    agent.school_or_company = "某大学"
    agent.chronotype = "normal"
    agent.life_history = []
    agent.solidified_memories = []
    agent.distrust_tags = []
    agent.trust_tags = []
    agent.reputation = 0.0
    agent.status = "active"
    agent.is_online = False
    return agent


# ── 0.10.1a: Internal search ──

def test_internal_search_posts():
    """execute_internal_search finds posts matching query."""
    async def _run():
        from app.engine.search_engine import execute_internal_search

        mock_db = AsyncMock()
        mock_posts = MagicMock()
        mock_posts.scalars.return_value.all.return_value = []
        mock_replies = MagicMock()
        mock_replies.scalars.return_value.all.return_value = []
        mock_bars = MagicMock()
        mock_bars.scalars.return_value.all.return_value = []
        mock_agents = MagicMock()
        mock_agents.scalars.return_value.all.return_value = []

        mock_db.execute = AsyncMock(side_effect=[
            mock_posts, mock_replies, mock_bars, mock_agents,
        ])

        results = await execute_internal_search("观鸟攻略", mock_db)
        assert isinstance(results, list)
        # Should have called 4 queries (posts, replies, bars, agents)
        assert mock_db.execute.call_count == 4

    asyncio.run(_run())


def test_internal_search_empty_query():
    """execute_internal_search returns empty on blank query."""
    async def _run():
        from app.engine.search_engine import execute_internal_search

        mock_db = AsyncMock()
        results = await execute_internal_search("", mock_db)
        assert results == []

        results2 = await execute_internal_search("   ", mock_db)
        assert results2 == []

    asyncio.run(_run())


def test_internal_search_result_format():
    """execute_internal_search returns structured results with type field."""
    async def _run():
        from app.engine.search_engine import execute_internal_search

        mock_post = MagicMock()
        mock_post.id = uuid.uuid4()
        mock_post.title = "观鸟攻略分享"
        mock_post.content = "分享一些观鸟技巧"
        mock_post.author_id = uuid.uuid4()
        bar = MagicMock()
        bar.name = "自然观察"
        mock_post.bar = bar
        author = MagicMock()
        author.nickname = "鸟友A"
        mock_post.author = author

        mock_db = AsyncMock()
        mock_posts = MagicMock()
        mock_posts.scalars.return_value.all.return_value = [mock_post]
        mock_empty = MagicMock()
        mock_empty.scalars.return_value.all.return_value = []

        mock_db.execute = AsyncMock(side_effect=[
            mock_posts, mock_empty, mock_empty, mock_empty,
        ])

        results = await execute_internal_search("观鸟", mock_db)
        assert len(results) >= 1
        r = results[0]
        assert r["type"] == "post"
        assert "观鸟攻略" in r["title"]
        assert r["source"] == "自然观察"

    asyncio.run(_run())


# ── 0.10.1b: External search ──

def test_external_search_topics():
    """execute_external_search queries topics table."""
    async def _run():
        from app.engine.search_engine import execute_external_search

        mock_topic = MagicMock()
        mock_topic.id = uuid.uuid4()
        mock_topic.title = "今日观鸟热点"
        mock_topic.summary = "某地发现稀有鸟类"
        mock_topic.source = "新闻"
        mock_topic.category = "自然"

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_topic]
        mock_db.execute = AsyncMock(return_value=mock_result)

        results = await execute_external_search("观鸟", mock_db)
        assert len(results) >= 1
        assert results[0]["title"] == "今日观鸟热点"
        assert results[0]["source"] == "新闻"

    asyncio.run(_run())


def test_external_search_empty():
    """execute_external_search returns empty on blank query."""
    async def _run():
        from app.engine.search_engine import execute_external_search

        mock_db = AsyncMock()
        results = await execute_external_search("", mock_db)
        assert results == []

    asyncio.run(_run())


# ── 0.10.1c: Search result formatting ──

def test_format_search_results():
    """format_search_results produces text for infusion into reply context."""
    from app.engine.search_engine import format_search_results

    results = [
        {"type": "post", "title": "观鸟攻略", "snippet": "分享观鸟技巧", "source": "自然观察"},
        {"type": "topic", "title": "今日观鸟热点", "snippet": "稀有鸟类发现", "source": "新闻"},
    ]
    text = format_search_results(results)
    assert "观鸟攻略" in text
    assert "今日观鸟热点" in text
    assert "post" in text.lower() or "帖" in text


def test_format_search_results_empty():
    """format_search_results returns empty string on empty results."""
    from app.engine.search_engine import format_search_results

    assert format_search_results([]) == ""
    assert format_search_results(None) == ""


# ── 0.10.1d: Search hook execution (no longer just intent recording) ──

def test_search_hook_calls_engine():
    """_search_hook executes search when should_search is True."""
    from unittest.mock import AsyncMock, patch

    agent = _make_mock_agent("搜索者")
    post = MagicMock()
    post.id = uuid.uuid4()
    post.title = "Python教程"
    post.content = "如何写好Python代码"
    post.author_id = uuid.uuid4()
    post.reply_count = 0
    bar = MagicMock()
    bar.name = "编程吧"
    post.bar = bar
    author = MagicMock()
    author.nickname = "作者A"
    author.id = post.author_id
    post.author = author

    async def _run():
        mock_db = AsyncMock()
        # execute_internal_search calls db.execute 4 times; each needs .scalars().all() → []
        _empty_result = MagicMock()
        _empty_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=_empty_result)
        mock_llm = MagicMock()

        import app.jobs.agent_lifecycle as lc
        agent_id = str(agent.id)
        lc._search_counts[agent_id] = 0
        lc._search_cooldowns[agent_id] = datetime.now(timezone.utc)

        with patch("app.jobs.agent_lifecycle.execute") as mock_exec:
            mock_exec_result = MagicMock()
            mock_exec_result.status = "success"
            mock_exec_result.parsed = {
                "should_search": True,
                "query": "Python最佳实践",
                "reason": "了解编程知识",
            }
            mock_exec.return_value = mock_exec_result

            from app.jobs.agent_lifecycle import _search_hook
            await _search_hook(agent, post, None, None, mock_db, mock_llm)

            # db.execute called 4 times (posts, replies, bars, agents)
            assert mock_db.execute.call_count == 4, (
                f"Expected 4 db.execute calls, got {mock_db.execute.call_count}"
            )
            mock_exec.assert_called_once()
            assert mock_exec.call_args[0][0] == "search_decision"

        lc._search_counts.pop(agent_id, None)
        lc._search_cooldowns.pop(agent_id, None)

    asyncio.run(_run())


def test_search_hook_no_search_when_false():
    """_search_hook does NOT call engine when should_search is False."""
    from unittest.mock import AsyncMock, patch

    agent = _make_mock_agent("搜索者")

    async def _run():
        mock_db = AsyncMock()
        mock_llm = MagicMock()

        import app.jobs.agent_lifecycle as lc
        agent_id = str(agent.id)
        lc._search_counts[agent_id] = 0
        lc._search_cooldowns[agent_id] = datetime.now(timezone.utc)

        with patch("app.skills.executor.execute") as mock_exec:
            mock_exec_result = MagicMock()
            mock_exec_result.status = "success"
            mock_exec_result.parsed = {
                "should_search": False,
                "query": "",
                "reason": "不感兴趣",
            }
            mock_exec.return_value = mock_exec_result

            with patch("app.engine.search_engine.execute_internal_search") as mock_internal:
                from app.jobs.agent_lifecycle import _search_hook
                await _search_hook(agent, MagicMock(), None, None, mock_db, mock_llm)

                mock_internal.assert_not_called()

        lc._search_counts.pop(agent_id, None)
        lc._search_cooldowns.pop(agent_id, None)

    asyncio.run(_run())


# ═══════════════════════════════════════════════════

if __name__ == "__main__":
    import traceback

    tests = [
        (name, obj) for name, obj in list(globals().items())
        if name.startswith("test_") and callable(obj)
    ]
    passed = 0
    failed = 0
    for name, fn in tests:
        try:
            fn()
            passed += 1
            print(f"  PASS {name}")
        except Exception as e:
            failed += 1
            print(f"  FAIL {name}: {e}")
            traceback.print_exc()

    print(f"\n{passed} passed, {failed} failed, {len(tests)} total")
    if failed:
        import sys
        sys.exit(1)
