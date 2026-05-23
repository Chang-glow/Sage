"""Phase 12.1 TDD tests — topic fetcher: web search + pool refresh + DailyTask."""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch


# ── 12.1a: Bing search interface ──

def test_bing_search_returns_structured_results():
    """bing_search returns list of dicts with title, summary, url, source."""
    async def _run():
        from app.engine.topic_fetcher import bing_search

        mock_response = {
            "webPages": {
                "value": [
                    {
                        "name": "Python 3.13 发布",
                        "snippet": "Python 3.13 正式发布，带来多项性能改进",
                        "url": "https://example.com/python313",
                    },
                    {
                        "name": "AI 编程工具对比",
                        "snippet": "2026 年主流 AI 编程工具横向评测",
                        "url": "https://example.com/ai-tools",
                    },
                ]
            }
        }

        with patch("app.engine.topic_fetcher.settings") as mock_settings:
            mock_settings.bing_search_api_key = "test-api-key"
            with patch("httpx.AsyncClient.get") as mock_get:
                mock_resp = MagicMock()
                mock_resp.status_code = 200
                mock_resp.json.return_value = mock_response
                mock_get.return_value = mock_resp

                results = await bing_search("Python 新闻", limit=5)

                assert len(results) == 2
                assert results[0]["title"] == "Python 3.13 发布"
                assert results[0]["snippet"] == "Python 3.13 正式发布，带来多项性能改进"
                assert results[0]["source"] == "web"
                assert "url" in results[0]

    asyncio.run(_run())


def test_bing_search_empty_query():
    """bing_search returns empty list on blank query."""
    async def _run():
        from app.engine.topic_fetcher import bing_search

        assert await bing_search("") == []
        assert await bing_search("   ") == []

    asyncio.run(_run())


def test_bing_search_no_api_key():
    """bing_search returns empty when BING_SEARCH_API_KEY is not configured."""
    async def _run():
        from app.engine.topic_fetcher import bing_search

        # Mock settings to have empty API key
        with patch("app.engine.topic_fetcher.settings") as mock_settings:
            mock_settings.bing_search_api_key = ""
            results = await bing_search("测试")
            assert results == []

    asyncio.run(_run())


def test_bing_search_http_failure():
    """bing_search returns empty on HTTP error."""
    async def _run():
        from app.engine.topic_fetcher import bing_search

        with patch("app.engine.topic_fetcher.settings") as mock_settings:
            mock_settings.bing_search_api_key = "test-api-key"
            with patch("httpx.AsyncClient.get") as mock_get:
                mock_resp = MagicMock()
                mock_resp.status_code = 500
                mock_get.return_value = mock_resp

                results = await bing_search("测试")
                assert results == []

    asyncio.run(_run())


def test_bing_search_rate_limited():
    """bing_search returns empty on 429 rate limit."""
    async def _run():
        from app.engine.topic_fetcher import bing_search

        with patch("app.engine.topic_fetcher.settings") as mock_settings:
            mock_settings.bing_search_api_key = "test-api-key"
            with patch("httpx.AsyncClient.get") as mock_get:
                mock_resp = MagicMock()
                mock_resp.status_code = 429
                mock_get.return_value = mock_resp

                results = await bing_search("测试")
                assert results == []

    asyncio.run(_run())


# ── 12.1b: Topic pool refresh ──

def test_refresh_topic_pool_stores_topics():
    """refresh_topic_pool fetches topics and upserts into DB."""
    async def _run():
        from app.engine.topic_fetcher import refresh_topic_pool

        mock_db = AsyncMock()
        # No existing topics with same title
        mock_existing = MagicMock()
        mock_existing.scalars.return_value.first.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_existing)

        mock_topics = [
            {"title": "热点 A", "snippet": "摘要 A", "source": "web", "category": "科技"},
            {"title": "热点 B", "snippet": "摘要 B", "source": "web", "category": "科技"},
        ]

        with patch("app.engine.topic_fetcher.bing_search") as mock_search:
            mock_search.return_value = mock_topics

            count = await refresh_topic_pool(mock_db, queries=[
                {"query": "科技新闻", "category": "科技"},
            ])

            assert count == 2, f"Expected 2 topics, got {count}"
            # db.add called twice (once per topic)
            assert mock_db.add.call_count == 2
            assert mock_db.commit.called
            mock_search.assert_called_once()

    asyncio.run(_run())


def test_refresh_topic_pool_empty_result():
    """refresh_topic_pool handles empty search results gracefully."""
    async def _run():
        from app.engine.topic_fetcher import refresh_topic_pool

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock()

        with patch("app.engine.topic_fetcher.bing_search") as mock_search:
            mock_search.return_value = []
            count = await refresh_topic_pool(mock_db, queries=[
                {"query": "nothing", "category": "科技"},
            ])

            assert count == 0
            mock_db.add.assert_not_called()

    asyncio.run(_run())


def test_refresh_topic_pool_no_queries():
    """refresh_topic_pool with None or empty queries returns 0."""
    async def _run():
        from app.engine.topic_fetcher import refresh_topic_pool

        mock_db = AsyncMock()
        assert await refresh_topic_pool(mock_db, queries=None) == 0
        assert await refresh_topic_pool(mock_db, queries=[]) == 0

    asyncio.run(_run())


def test_refresh_topic_pool_deduplicate():
    """refresh_topic_pool skips topics with duplicate titles in DB."""
    async def _run():
        from app.engine.topic_fetcher import refresh_topic_pool

        mock_db = AsyncMock()
        # Mock existing topic found
        mock_existing = MagicMock()
        mock_existing.scalars.return_value.first.return_value = MagicMock()  # not None
        mock_db.execute = AsyncMock(return_value=mock_existing)

        mock_topics = [
            {"title": "已存在的话题", "snippet": "X", "source": "web", "category": "科技"},
        ]

        with patch("app.engine.topic_fetcher.bing_search") as mock_search:
            mock_search.return_value = mock_topics

            count = await refresh_topic_pool(mock_db, queries=[
                {"query": "科技", "category": "科技"},
            ])

            # Duplicate should be skipped
            assert count == 0
            mock_db.add.assert_not_called()

    asyncio.run(_run())


# ── 12.1c: DailyTask registration ──

def test_topic_fetcher_task_registered():
    """refresh_topics task is registered as DailyTask."""
    import app.jobs.scheduler
    from app.engine.daily_tasks import daily_task_registry

    names = [name for name, _, _, _ in daily_task_registry._tasks]
    assert "refresh_topics" in names, (
        f"refresh_topics not in registered tasks: {names}"
    )


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
