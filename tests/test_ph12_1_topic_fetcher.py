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
            # db.add called 3 times: 2 topics + 1 api_call record
            assert mock_db.add.call_count == 3
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
            # db.add still called once for the api_call record
            assert mock_db.add.call_count == 1
            assert mock_db.commit.called

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

            # Duplicate should be skipped (topic not added, but api_call record is)
            assert count == 0
            # db.add still called once for the api_call record
            assert mock_db.add.call_count == 1
            assert mock_db.commit.called

    asyncio.run(_run())


# ── 12.1c: RSS feed fetching ──

RSS_XML_SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test Feed</title>
    <item>
      <title>游戏新闻: 原神 4.0 版本发布</title>
      <description>&lt;p&gt;米哈游正式发布原神 4.0 版本，新增枫丹地图&lt;/p&gt;</description>
      <link>https://example.com/game1</link>
    </item>
    <item>
      <title>电竞: LPL 夏季赛决赛</title>
      <description>LPL 夏季赛决赛将在上海举行</description>
      <link>https://example.com/game2</link>
    </item>
  </channel>
</rss>"""

ATOM_XML_SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Test Atom Feed</title>
  <entry>
    <title>科技前沿: 量子计算突破</title>
    <summary>中国科学家在量子计算领域取得重大突破</summary>
    <link href="https://example.com/tech1"/>
  </entry>
  <entry>
    <title>科普: 黑洞新发现</title>
    <summary>天文学家发现最近的黑洞</summary>
    <link href="https://example.com/tech2"/>
  </entry>
</feed>"""


def test_fetch_rss_feed_returns_structured_results():
    """fetch_rss_feed parses RSS XML and returns topic dicts."""
    async def _run():
        from app.engine.topic_fetcher import fetch_rss_feed

        with patch("httpx.AsyncClient.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.text = RSS_XML_SAMPLE
            mock_get.return_value = mock_resp

            results = await fetch_rss_feed("https://example.com/feed.xml", category="游戏版")

            assert len(results) == 2, f"Expected 2 results, got {len(results)}"
            assert results[0]["title"] == "游戏新闻: 原神 4.0 版本发布"
            assert "米哈游" in results[0]["snippet"]
            assert results[0]["source"] == "rss"
            assert results[0]["category"] == "游戏版"
            assert results[0]["url"] == "https://example.com/game1"

    asyncio.run(_run())


def test_fetch_rss_feed_atom_format():
    """fetch_rss_feed parses Atom XML correctly."""
    async def _run():
        from app.engine.topic_fetcher import fetch_rss_feed

        with patch("httpx.AsyncClient.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.text = ATOM_XML_SAMPLE
            mock_get.return_value = mock_resp

            results = await fetch_rss_feed("https://example.com/atom.xml", category="科创科普版")

            assert len(results) == 2
            assert results[0]["title"] == "科技前沿: 量子计算突破"
            assert results[0]["source"] == "rss"

    asyncio.run(_run())


def test_fetch_rss_feed_empty_url():
    """fetch_rss_feed returns empty list on blank URL."""
    async def _run():
        from app.engine.topic_fetcher import fetch_rss_feed

        assert await fetch_rss_feed("") == []
        assert await fetch_rss_feed("   ") == []

    asyncio.run(_run())


def test_fetch_rss_feed_http_failure():
    """fetch_rss_feed returns empty on HTTP error."""
    async def _run():
        from app.engine.topic_fetcher import fetch_rss_feed

        with patch("httpx.AsyncClient.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 500
            mock_get.return_value = mock_resp

            results = await fetch_rss_feed("https://example.com/broken.xml", category="游戏版")
            assert results == []

    asyncio.run(_run())


def test_fetch_rss_feed_parse_error():
    """fetch_rss_feed returns empty on invalid XML."""
    async def _run():
        from app.engine.topic_fetcher import fetch_rss_feed

        with patch("httpx.AsyncClient.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.text = "not valid xml >>>"
            mock_get.return_value = mock_resp

            results = await fetch_rss_feed("https://example.com/bad.xml", category="综合")
            assert results == []

    asyncio.run(_run())


def test_strip_html_removes_tags():
    """_strip_html removes HTML tags from text."""
    from app.engine.topic_fetcher import _strip_html

    assert _strip_html("<p>Hello</p>") == "Hello"
    assert _strip_html("<a href='x'>link</a> text") == "link text"
    assert _strip_html("plain text") == "plain text"
    assert _strip_html("") == ""


# ── 12.1d: RSS pool refresh ──

def test_refresh_topic_pool_from_rss_stores_topics():
    """refresh_topic_pool_from_rss fetches RSS feeds and upserts into DB."""
    async def _run():
        from app.engine.topic_fetcher import refresh_topic_pool_from_rss

        mock_db = AsyncMock()
        mock_existing = MagicMock()
        mock_existing.scalars.return_value.first.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_existing)

        with patch("app.engine.topic_fetcher.fetch_rss_feed") as mock_fetch:
            mock_fetch.return_value = [
                {"title": "热点 C", "snippet": "摘要 C", "url": "http://x", "source": "rss", "category": "游戏版"},
                {"title": "热点 D", "snippet": "摘要 D", "url": "http://y", "source": "rss", "category": "游戏版"},
            ]

            count = await refresh_topic_pool_from_rss(mock_db, feeds=[
                {"url": "https://example.com/feed.xml", "category": "游戏版"},
            ])

            assert count == 2, f"Expected 2 topics, got {count}"
            assert mock_db.add.call_count == 2
            assert mock_db.commit.called
            mock_fetch.assert_called_once()

    asyncio.run(_run())


def test_refresh_topic_pool_from_rss_empty_feeds():
    """refresh_topic_pool_from_rss with None or empty feeds returns 0."""
    async def _run():
        from app.engine.topic_fetcher import refresh_topic_pool_from_rss

        mock_db = AsyncMock()
        assert await refresh_topic_pool_from_rss(mock_db, feeds=None) == 0
        assert await refresh_topic_pool_from_rss(mock_db, feeds=[]) == 0

    asyncio.run(_run())


def test_refresh_topic_pool_from_rss_skip_empty_url():
    """refresh_topic_pool_from_rss skips feeds with empty url."""
    async def _run():
        from app.engine.topic_fetcher import refresh_topic_pool_from_rss

        mock_db = AsyncMock()
        count = await refresh_topic_pool_from_rss(mock_db, feeds=[
            {"url": "", "category": "游戏版"},
            {"url": "  ", "category": "科技"},
        ])
        assert count == 0

    asyncio.run(_run())


# ── 12.1e: DailyTask registration ──

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
