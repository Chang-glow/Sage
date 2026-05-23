"""Phase 12.2 TDD tests — usage tracker: API call + token usage recording + query."""

import asyncio
import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch


# ── 12.2a: UsageRecord model ──

def test_usage_record_creation():
    """UsageRecord can be instantiated with all fields."""
    from app.models.usage import UsageRecord

    agent_id = uuid.uuid4()
    record = UsageRecord(
        record_type="api_call",
        source="bing_search",
        agent_id=agent_id,
        quantity=1,
        cost_estimate=0.0,
        metadata_json={"endpoint": "/v7.0/search", "query": "测试"},
    )
    assert record.record_type == "api_call"
    assert record.source == "bing_search"
    assert record.agent_id == agent_id
    assert record.quantity == 1
    assert record.cost_estimate == 0.0
    assert record.metadata_json["endpoint"] == "/v7.0/search"


def test_usage_record_token_type():
    """UsageRecord with record_type='token_usage' stores token count."""
    from app.models.usage import UsageRecord

    record = UsageRecord(
        record_type="token_usage",
        source="deepseek_chat",
        agent_id=uuid.uuid4(),
        quantity=1420,
        metadata_json={"model": "deepseek-chat", "prompt_tokens": 1000, "completion_tokens": 420},
    )
    assert record.record_type == "token_usage"
    assert record.quantity == 1420


def test_usage_record_nullable_fields():
    """UsageRecord agent_id, cost_estimate, metadata_json can be None."""
    from app.models.usage import UsageRecord

    record = UsageRecord(record_type="api_call", source="bing_search", quantity=5)
    assert record.agent_id is None
    assert record.cost_estimate is None
    assert record.metadata_json is None


# ── 12.2b: record_api_call ──

def test_record_api_call_adds_to_db():
    """record_api_call creates a UsageRecord with record_type='api_call'."""
    async def _run():
        from app.engine.usage_tracker import record_api_call

        mock_db = AsyncMock()
        record = await record_api_call(mock_db, source="bing_search", count=3)

        assert record.record_type == "api_call"
        assert record.source == "bing_search"
        assert record.quantity == 3
        assert record.agent_id is None
        mock_db.add.assert_called_once()

    asyncio.run(_run())


def test_record_api_call_with_agent():
    """record_api_call accepts optional agent_id."""
    async def _run():
        from app.engine.usage_tracker import record_api_call

        mock_db = AsyncMock()
        agent_id = str(uuid.uuid4())
        record = await record_api_call(
            mock_db, source="bing_search", agent_id=agent_id,
            cost_estimate=0.001, metadata={"query": "test"},
        )

        assert str(record.agent_id) == agent_id
        assert record.cost_estimate == 0.001
        assert record.metadata_json == {"query": "test"}

    asyncio.run(_run())


# ── 12.2c: record_token_usage ──

def test_record_token_usage_adds_to_db():
    """record_token_usage creates a UsageRecord with record_type='token_usage'."""
    async def _run():
        from app.engine.usage_tracker import record_token_usage

        mock_db = AsyncMock()
        agent_id = str(uuid.uuid4())
        record = await record_token_usage(
            mock_db, agent_id=agent_id, source="deepseek_chat", tokens=1420,
        )

        assert record.record_type == "token_usage"
        assert str(record.agent_id) == agent_id
        assert record.quantity == 1420
        mock_db.add.assert_called_once()

    asyncio.run(_run())


def test_record_token_usage_with_cost():
    """record_token_usage accepts cost_estimate and metadata."""
    async def _run():
        from app.engine.usage_tracker import record_token_usage

        mock_db = AsyncMock()
        record = await record_token_usage(
            mock_db, agent_id=str(uuid.uuid4()), source="deepseek_chat",
            tokens=8000, cost_estimate=0.002,
            metadata={"model": "deepseek-chat", "prompt_tokens": 6000, "completion_tokens": 2000},
        )

        assert record.cost_estimate == 0.002
        assert record.metadata_json["model"] == "deepseek-chat"

    asyncio.run(_run())


# ── 12.2d: query functions ──

def test_get_daily_usage_aggregates():
    """get_daily_usage returns aggregated counts for today."""
    async def _run():
        from app.engine.usage_tracker import get_daily_usage

        mock_db = AsyncMock()
        # First call: API calls grouped by source
        # Second call: tokens grouped by source
        call_count = 0

        async def _mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                # API calls: 3 bing_search, 1 rss_feed
                result.__iter__.return_value = iter([("bing_search", 3), ("rss_feed", 1)])
            elif call_count == 2:
                # Token usage: 50000 tokens from deepseek_chat
                result.__iter__.return_value = iter([("deepseek_chat", 50000)])
            return result

        mock_db.execute = _mock_execute

        usage = await get_daily_usage(mock_db)

        assert usage["total_api_calls"] == 4
        assert usage["total_tokens"] == 50000
        assert usage["api_calls"]["bing_search"] == 3
        assert usage["tokens"]["deepseek_chat"] == 50000

    asyncio.run(_run())


def test_get_daily_usage_empty():
    """get_daily_usage returns zeros when no records exist."""
    async def _run():
        from app.engine.usage_tracker import get_daily_usage

        mock_db = AsyncMock()
        call_count = 0

        async def _mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            result.__iter__.return_value = iter([])
            return result

        mock_db.execute = _mock_execute

        usage = await get_daily_usage(mock_db)

        assert usage["total_api_calls"] == 0
        assert usage["total_tokens"] == 0
        assert usage["api_calls"] == {}
        assert usage["tokens"] == {}

    asyncio.run(_run())


def test_get_agent_usage_aggregates():
    """get_agent_usage returns per-agent token and API call breakdown."""
    async def _run():
        from app.engine.usage_tracker import get_agent_usage

        agent_id = str(uuid.uuid4())
        mock_db = AsyncMock()
        call_count = 0

        async def _mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.__iter__.return_value = iter([("deepseek_chat", 20000), ("siliconflow", 10000)])
            elif call_count == 2:
                result.__iter__.return_value = iter([("bing_search", 5)])
            return result

        mock_db.execute = _mock_execute

        usage = await get_agent_usage(mock_db, agent_id=agent_id, days=7)

        assert usage["agent_id"] == agent_id
        assert usage["days"] == 7
        assert usage["total_tokens"] == 30000
        assert usage["total_api_calls"] == 5
        assert usage["tokens_by_source"]["deepseek_chat"] == 20000
        assert usage["api_calls_by_source"]["bing_search"] == 5

    asyncio.run(_run())


def test_get_agent_usage_default_30_days():
    """get_agent_usage defaults to 30-day window."""
    async def _run():
        from app.engine.usage_tracker import get_agent_usage

        mock_db = AsyncMock()
        call_count = 0

        async def _mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            result.__iter__.return_value = iter([])
            return result

        mock_db.execute = _mock_execute

        usage = await get_agent_usage(mock_db, agent_id=str(uuid.uuid4()))
        assert usage["days"] == 30

    asyncio.run(_run())


# ── 12.2e: model registration ──

def test_usage_record_importable_from_models():
    """UsageRecord is importable from app.models."""
    from app.models import UsageRecord
    assert UsageRecord.__tablename__ == "usage_records"


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
