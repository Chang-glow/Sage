"""0.12.4_memory_boost TDD tests — memory importance boost on conflict/flow/block."""

import asyncio
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch


def _make_mock_agent(name="测试Agent"):
    """Helper to create a minimal mock agent with required attributes."""
    agent = MagicMock()
    agent.id = uuid.uuid4()
    agent.nickname = name
    agent.personality_vector = {"开放": 0.7, "外向": 0.5}
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
    agent.consecutive_fulfillments = 0
    agent.status = "active"
    agent.is_online = False
    return agent


# ── A. _boost_memory_importance helper ──

def test_boost_memory_importance_boosts_related_fragments():
    """_boost_memory_importance boosts importance of fragments with matching related_agent_id."""
    agent = _make_mock_agent()
    target_id = uuid.uuid4()
    agent.solidified_memories = [
        {"type": "short", "content": "聊得很开心",
         "importance": 0.5, "retrieval_count": 0,
         "created_at": datetime.now(timezone.utc).isoformat(),
         "source_type": "reply", "related_agent_id": str(target_id)},
        {"type": "short", "content": "无关记忆",
         "importance": 0.3, "retrieval_count": 0,
         "created_at": datetime.now(timezone.utc).isoformat(),
         "source_type": "reply", "related_agent_id": str(uuid.uuid4())},
    ]

    async def _run():
        mock_db = AsyncMock()
        from app.jobs.social_engine import _boost_memory_importance
        await _boost_memory_importance(agent, target_id, 0.2, mock_db)

        # Related fragment should be boosted
        assert agent.solidified_memories[0]["importance"] == 0.7, \
            f"Expected 0.7, got {agent.solidified_memories[0]['importance']}"
        # Unrelated fragment unchanged
        assert agent.solidified_memories[1]["importance"] == 0.3

    asyncio.run(_run())


def test_boost_memory_importance_upgrades_short_to_long():
    """_boost_memory_importance upgrades 'short' type to 'long'."""
    agent = _make_mock_agent()
    target_id = uuid.uuid4()
    agent.solidified_memories = [
        {"type": "short", "content": "争吵记忆",
         "importance": 0.4, "retrieval_count": 0,
         "created_at": datetime.now(timezone.utc).isoformat(),
         "source_type": "reply", "related_agent_id": str(target_id)},
    ]

    async def _run():
        mock_db = AsyncMock()
        from app.jobs.social_engine import _boost_memory_importance
        await _boost_memory_importance(agent, target_id, 0.2, mock_db)
        assert agent.solidified_memories[0]["type"] == "long", \
            f"Expected 'long', got {agent.solidified_memories[0]['type']}"

    asyncio.run(_run())


def test_boost_memory_importance_clamped_at_1():
    """_boost_memory_importance clamps importance at 1.0."""
    agent = _make_mock_agent()
    target_id = uuid.uuid4()
    agent.solidified_memories = [
        {"type": "long", "content": "重要记忆",
         "importance": 0.95, "retrieval_count": 5,
         "created_at": datetime.now(timezone.utc).isoformat(),
         "source_type": "reply", "related_agent_id": str(target_id)},
    ]

    async def _run():
        mock_db = AsyncMock()
        from app.jobs.social_engine import _boost_memory_importance
        await _boost_memory_importance(agent, target_id, 0.2, mock_db)
        assert agent.solidified_memories[0]["importance"] == 1.0

    asyncio.run(_run())


def test_boost_memory_importance_empty_memories():
    """_boost_memory_importance handles empty solidified_memories gracefully."""
    agent = _make_mock_agent()
    agent.solidified_memories = []

    async def _run():
        mock_db = AsyncMock()
        from app.jobs.social_engine import _boost_memory_importance
        await _boost_memory_importance(agent, uuid.uuid4(), 0.2, mock_db)
        assert agent.solidified_memories == []

    asyncio.run(_run())


# ── B. adjust_after_conflict includes memory boost ──

def test_conflict_boosts_memory_importance():
    """adjust_after_conflict boosts memory importance for both agents."""
    agent_a = _make_mock_agent("Alice")
    agent_b = _make_mock_agent("Bob")

    async def _run():
        mock_db = AsyncMock()
        mock_rel = MagicMock()
        mock_rel.intimacy = 0.5

        # Mock Agent query to return agent_a then agent_b
        result_a = MagicMock()
        result_a.scalar_one_or_none.return_value = agent_a
        result_b = MagicMock()
        result_b.scalar_one_or_none.return_value = agent_b
        # First call returns rel (_ensure_relationship), then agent_a, then agent_b
        mock_db.execute = AsyncMock(side_effect=[result_a, result_b])

        with patch("app.jobs.social_engine._ensure_relationship", return_value=mock_rel), \
             patch("app.jobs.social_engine._boost_memory_importance") as mock_boost:
            from app.jobs.social_engine import adjust_after_conflict
            await adjust_after_conflict(agent_a.id, agent_b.id, mock_db)

        assert mock_boost.call_count == 2
        # First call: agent_a, opponent=agent_b, boost=0.2
        assert mock_boost.call_args_list[0][0][1] == agent_b.id
        assert mock_boost.call_args_list[0][0][2] == 0.2
        # Second call: agent_b, opponent=agent_a, boost=0.2
        assert mock_boost.call_args_list[1][0][1] == agent_a.id

    asyncio.run(_run())


# ── C. adjust_after_deep_flow includes memory boost ──

def test_deep_flow_boosts_memory_importance():
    """adjust_after_deep_flow boosts memory importance for both agents."""
    agent_a = _make_mock_agent("Alice")
    agent_b = _make_mock_agent("Bob")

    async def _run():
        mock_db = AsyncMock()
        mock_rel = MagicMock()
        mock_rel.intimacy = 0.5

        result_a = MagicMock()
        result_a.scalar_one_or_none.return_value = agent_a
        result_b = MagicMock()
        result_b.scalar_one_or_none.return_value = agent_b
        mock_db.execute = AsyncMock(side_effect=[result_a, result_b])

        with patch("app.jobs.social_engine._ensure_relationship", return_value=mock_rel), \
             patch("app.jobs.social_engine._boost_memory_importance") as mock_boost:
            from app.jobs.social_engine import adjust_after_deep_flow
            await adjust_after_deep_flow(agent_a.id, agent_b.id, mock_db)

        assert mock_boost.call_count == 2
        assert mock_boost.call_args_list[0][0][2] == 0.2
        assert mock_boost.call_args_list[1][0][2] == 0.2

    asyncio.run(_run())


# ── D. adjust_after_block ──

def test_block_adjusts_intimacy():
    """adjust_after_block reduces intimacy by _INTIMACY_BLOCK (-0.10)."""
    agent_a = _make_mock_agent("Alice")
    agent_b = _make_mock_agent("Bob")

    async def _run():
        mock_db = AsyncMock()

        # Explicit mock: db.execute returns a result whose scalar_one_or_none is sync
        agent_result = MagicMock()
        agent_result.scalar_one_or_none = MagicMock(return_value=agent_a)
        mock_db.execute = AsyncMock(return_value=agent_result)

        mock_rel = MagicMock()
        mock_rel.intimacy = 0.5

        with patch("app.jobs.social_engine._ensure_relationship", return_value=mock_rel):
            from app.jobs.social_engine import adjust_after_block
            await adjust_after_block(agent_a.id, agent_b.id, mock_db)

        assert mock_rel.intimacy == 0.4, \
            f"Expected 0.4 (-0.10), got {mock_rel.intimacy}"

    asyncio.run(_run())


def test_block_boosts_memory_importance():
    """adjust_after_block boosts memory importance by 0.3."""
    agent = _make_mock_agent("Alice")
    blocker_id = uuid.uuid4()
    agent.solidified_memories = [
        {"type": "short", "content": "被拉黑",
         "importance": 0.3, "retrieval_count": 0,
         "created_at": datetime.now(timezone.utc).isoformat(),
         "source_type": "reply", "related_agent_id": str(blocker_id)},
    ]

    async def _run():
        mock_db = AsyncMock()
        mock_rel = MagicMock()
        mock_rel.intimacy = 0.0

        with patch("app.jobs.social_engine._ensure_relationship", return_value=mock_rel):
            result = MagicMock()
            result.scalar_one_or_none.return_value = agent
            mock_db.execute = AsyncMock(return_value=result)

            from app.jobs.social_engine import adjust_after_block
            await adjust_after_block(agent.id, blocker_id, mock_db)

        # +0.3 boost
        assert agent.solidified_memories[0]["importance"] == 0.6, \
            f"Expected 0.6, got {agent.solidified_memories[0]['importance']}"
        # Short → long
        assert agent.solidified_memories[0]["type"] == "long"

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
