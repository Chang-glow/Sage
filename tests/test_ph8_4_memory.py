"""0.8.4_memory TDD tests."""

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

def _make_mock_agent(name="测试Agent"):
    """Helper to create a minimal mock agent with required attributes."""
    import uuid as _uuid
    agent = MagicMock()
    agent.id = _uuid.uuid4()
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
    agent.status = "active"
    agent.is_online = False
    return agent


def _make_mock_post(title="测试帖", content="这是测试内容", author_name="作者A"):
    """Helper to create a minimal mock post."""
    import uuid as _uuid
    post = MagicMock()
    post.id = _uuid.uuid4()
    post.title = title
    post.content = content
    post.author_id = _uuid.uuid4()
    post.reply_count = 0
    post.is_hidden = False
    author = MagicMock()
    author.nickname = author_name
    post.author = author
    bar = MagicMock()
    bar.name = "测试吧"
    post.bar = bar
    return post


# 0.8.4: Memory System — memory_extraction + memory_consolidation
# ═══════════════════════════════════════════════════

def _make_mock_agent():
    """Helper: create a mock agent with required attributes for memory tests."""
    agent = MagicMock()
    agent.id = uuid.uuid4()
    agent.nickname = "测试Agent"
    agent.age = 25
    agent.gender = "男"
    agent.occupation = "学生"
    agent.income_level = "普通"
    agent.school_or_company = "测试大学"
    agent.chronotype = "normal"
    agent.interests = {"阅读": 0.8, "音乐": 0.6}
    agent.personality_vector = {"openness": 0.7, "extroversion": 0.5}
    agent.persona_prompt = ""
    agent.life_history = []
    agent.solidified_memories = []
    return agent


def _make_mock_post():
    """Helper: create a mock post with author and bar."""
    post = MagicMock()
    post.id = uuid.uuid4()
    post.title = "测试帖子"
    post.content = "这是测试帖子的内容"
    post.reply_count = 3
    post.author_id = uuid.uuid4()

    author = MagicMock()
    author.nickname = "发帖人"
    post.author = author

    bar = MagicMock()
    bar.name = "测试吧"
    post.bar = bar

    return post


# ── 0.8.4a: Memory Extraction Hook ──

def test_memory_extraction_hook_registered():
    """_memory_extraction_hook is registered in BrowseHookRegistry at priority 90."""
    from app.engine.browse_hooks import browse_hook_registry
    import app.jobs.agent_lifecycle  # triggers module-level registration

    names = [name for name, _, _ in browse_hook_registry._hooks]
    assert "memory_extract" in names, f"Expected 'memory_extract' in registered hooks, got {names}"


def test_memory_extraction_after_reply():
    """Memory extraction runs after a reply, stores fragments in solidified_memories."""
    from unittest.mock import AsyncMock, patch

    agent = _make_mock_agent()
    post = _make_mock_post()
    reply_result = {"content": "一条深度回复内容，有很多观点和想法交流"}

    async def _run():
        mock_db = AsyncMock()
        mock_llm = MagicMock()

        with patch("app.jobs.agent_lifecycle.execute") as mock_exec:
            mock_exec_result = MagicMock()
            mock_exec_result.status = "success"
            mock_exec_result.parsed = {
                "fragments": [
                    {"content": "和发帖人讨论了测试帖子的话题", "importance": 0.6, "type": "short"},
                    {"content": "发现和发帖人在音乐上很有共同语言", "importance": 0.8, "type": "long"},
                ]
            }
            mock_exec.return_value = mock_exec_result

            with patch("app.jobs.agent_lifecycle.build_agent_context",
                       return_value={"agent_name": "测试Agent"}):
                with patch("app.jobs.agent_lifecycle.build_post_context",
                           return_value={"post_title": "测试帖子", "post_content": "内容"}):
                    from app.jobs.agent_lifecycle import _memory_extraction_hook
                    await _memory_extraction_hook(agent, post, MagicMock(), reply_result, mock_db, mock_llm)

            # execute("memory_extraction") was called
            mock_exec.assert_called_once()
            call_args = mock_exec.call_args
            assert call_args[0][0] == "memory_extraction"

            # Fragments stored on agent
            assert len(agent.solidified_memories) == 2
            assert agent.solidified_memories[0]["content"] == "和发帖人讨论了测试帖子的话题"
            assert agent.solidified_memories[0]["importance"] == 0.6
            assert agent.solidified_memories[0]["type"] == "short"
            assert agent.solidified_memories[1]["content"] == "发现和发帖人在音乐上很有共同语言"
            assert agent.solidified_memories[1]["importance"] == 0.8
            assert agent.solidified_memories[1]["type"] == "long"
            # Metadata fields present
            for frag in agent.solidified_memories:
                assert "id" in frag
                assert "created_at" in frag
                assert "retrieval_count" in frag
                assert "source_type" in frag

    asyncio.run(_run())


def test_memory_extraction_skips_when_no_reply():
    """Memory extraction skips when reply_result is None (no reply generated)."""
    from unittest.mock import AsyncMock, patch

    agent = _make_mock_agent()
    post = _make_mock_post()

    async def _run():
        mock_db = AsyncMock()
        mock_llm = MagicMock()

        with patch("app.jobs.agent_lifecycle.execute") as mock_exec:
            from app.jobs.agent_lifecycle import _memory_extraction_hook
            await _memory_extraction_hook(agent, post, MagicMock(), None, mock_db, mock_llm)

            # execute should NOT be called since there's no reply
            mock_exec.assert_not_called()

    asyncio.run(_run())


def test_memory_extraction_skips_empty_fragments():
    """Memory extraction handles empty fragments list from LLM gracefully."""
    from unittest.mock import AsyncMock, patch

    agent = _make_mock_agent()
    post = _make_mock_post()
    reply_result = {"content": "简短回复"}

    async def _run():
        mock_db = AsyncMock()
        mock_llm = MagicMock()

        with patch("app.jobs.agent_lifecycle.execute") as mock_exec:
            mock_exec_result = MagicMock()
            mock_exec_result.status = "success"
            mock_exec_result.parsed = {"fragments": []}
            mock_exec.return_value = mock_exec_result

            with patch("app.jobs.agent_lifecycle.build_agent_context",
                       return_value={"agent_name": "测试Agent"}):
                with patch("app.jobs.agent_lifecycle.build_post_context",
                           return_value={"post_title": "测试帖子"}):
                    from app.jobs.agent_lifecycle import _memory_extraction_hook
                    await _memory_extraction_hook(agent, post, MagicMock(), reply_result, mock_db, mock_llm)

            # No fragments stored
            assert agent.solidified_memories == []

    asyncio.run(_run())


def test_memory_fragment_storage_limit():
    """When short fragments exceed max_short_fragments, evict lowest importance."""
    from unittest.mock import AsyncMock, patch
    from app.config import config as yaml_config

    agent = _make_mock_agent()
    max_short = yaml_config.memory.max_short_fragments  # 150

    # Pre-fill with max_short fragments, each with UNIQUE importance
    agent.solidified_memories = [
        {
            "id": str(uuid.uuid4()),
            "content": f"已有记忆 {i}",
            "importance": round(0.1 + i * 0.003, 3),  # 0.100 ~ 0.547, all unique
            "type": "short",
            "retrieval_count": 0,
            "created_at": "2026-01-15T10:00:00",
            "source_type": "reply",
        }
        for i in range(max_short)
    ]
    min_importance = min(f["importance"] for f in agent.solidified_memories)

    post = _make_mock_post()
    reply_result = {"content": "新回复"}

    async def _run():
        mock_db = AsyncMock()
        mock_llm = MagicMock()

        with patch("app.jobs.agent_lifecycle.execute") as mock_exec:
            mock_exec_result = MagicMock()
            mock_exec_result.status = "success"
            mock_exec_result.parsed = {
                "fragments": [
                    {"content": "新记忆片段——高重要度", "importance": 0.9, "type": "short"},
                ]
            }
            mock_exec.return_value = mock_exec_result

            with patch("app.jobs.agent_lifecycle.build_agent_context",
                       return_value={"agent_name": "测试Agent"}):
                with patch("app.jobs.agent_lifecycle.build_post_context",
                           return_value={"post_title": "测试帖子"}):
                    from app.jobs.agent_lifecycle import _memory_extraction_hook
                    await _memory_extraction_hook(agent, post, MagicMock(), reply_result, mock_db, mock_llm)

            # Should still have max_short fragments (one evicted, one added)
            short_frags = [f for f in agent.solidified_memories if f["type"] == "short"]
            assert len(short_frags) == max_short

            # The evicted one should be the lowest importance
            current_min = min(f["importance"] for f in short_frags)
            assert current_min > min_importance, "Lowest importance fragment should have been evicted"

            # The new fragment should be present
            contents = [f["content"] for f in short_frags]
            assert "新记忆片段——高重要度" in contents

    asyncio.run(_run())


# ── 0.8.4b: Memory Consolidation Task ──

def test_memory_consolidation_task_registered():
    """memory_consolidate is registered in DailyTaskRegistry at hour=0, minute=13."""
    from app.engine.daily_tasks import daily_task_registry
    import app.jobs.scheduler  # triggers module-level registration

    task_names = [name for name, _, _, _ in daily_task_registry._tasks]
    assert "memory_consolidate" in task_names, (
        f"Expected 'memory_consolidate' in daily tasks, got {task_names}"
    )

    # Verify schedule timing
    for name, _, hour, minute in daily_task_registry._tasks:
        if name == "memory_consolidate":
            assert hour == 0, f"Expected hour=0, got {hour}"
            assert minute == 13, f"Expected minute=13, got {minute}"


def test_memory_consolidation_upgrade():
    """memory_consolidation upgrades short→long and long→core based on criteria."""
    from unittest.mock import AsyncMock, patch
    from datetime import datetime, timedelta, timezone

    agent = _make_mock_agent()
    now = datetime.now(timezone.utc)

    short_id = str(uuid.uuid4())
    long_id = str(uuid.uuid4())

    agent.solidified_memories = [
        {
            "id": short_id,
            "content": "一条经常被回忆的短期记忆",
            "importance": 0.5,
            "type": "short",
            "retrieval_count": 5,  # >= config.upgrade_retrieval_min (3)
            "created_at": (now - timedelta(days=60)).isoformat(),
            "source_type": "reply",
        },
        {
            "id": long_id,
            "content": "一条长期记忆中非常重要的片段",
            "importance": 0.9,  # >= config.consolidate_importance_min (0.85)
            "type": "long",
            "retrieval_count": 12,  # >= config.consolidate_retrieval_min (10)
            "created_at": (now - timedelta(days=200)).isoformat(),  # >= config.consolidate_days_min (180)
            "source_type": "flow",
        },
    ]

    async def _run():
        mock_db = AsyncMock()
        mock_llm = MagicMock()

        from app.engine.memory_engine import consolidate_agent_memories
        with patch("app.skills.executor.execute") as mock_exec:
            mock_exec_result = MagicMock()
            mock_exec_result.status = "success"
            mock_exec_result.parsed = {
                "to_consolidate": [short_id, long_id],
                "to_discard": [],
                "notes": "两条都符合升级条件",
            }
            mock_exec.return_value = mock_exec_result

            await consolidate_agent_memories(agent, mock_db, mock_llm)

        # Verify the short memory was upgraded to long
        short_frag = next(f for f in agent.solidified_memories if f["id"] == short_id)
        assert short_frag["type"] == "long", f"Expected type='long', got {short_frag['type']}"

        # Verify the long memory was upgraded to core
        long_frag = next(f for f in agent.solidified_memories if f["id"] == long_id)
        assert long_frag["type"] == "core", f"Expected type='core', got {long_frag['type']}"

    asyncio.run(_run())


def test_memory_consolidation_discard():
    """memory_consolidation removes fragments listed in to_discard."""
    from unittest.mock import AsyncMock, patch

    agent = _make_mock_agent()

    keep_id = str(uuid.uuid4())
    discard_id = str(uuid.uuid4())

    agent.solidified_memories = [
        {
            "id": keep_id,
            "content": "值得保留的记忆",
            "importance": 0.7,
            "type": "long",
            "retrieval_count": 8,
            "created_at": "2026-03-01T10:00:00",
            "source_type": "reply",
        },
        {
            "id": discard_id,
            "content": "不再重要的记忆",
            "importance": 0.1,
            "type": "short",
            "retrieval_count": 0,
            "created_at": "2026-01-01T10:00:00",
            "source_type": "reply",
        },
    ]

    async def _run():
        mock_db = AsyncMock()
        mock_llm = MagicMock()

        from app.engine.memory_engine import consolidate_agent_memories
        with patch("app.skills.executor.execute") as mock_exec:
            mock_exec_result = MagicMock()
            mock_exec_result.status = "success"
            mock_exec_result.parsed = {
                "to_consolidate": [],
                "to_discard": [discard_id],
                "notes": "importance过低且从未检索",
            }
            mock_exec.return_value = mock_exec_result

            await consolidate_agent_memories(agent, mock_db, mock_llm)

        # Discarded fragment removed
        remaining_ids = [f["id"] for f in agent.solidified_memories]
        assert discard_id not in remaining_ids
        assert keep_id in remaining_ids
        assert len(agent.solidified_memories) == 1

    asyncio.run(_run())


def test_memory_consolidation_noop_empty_memories():
    """consolidate_agent_memories skips execution when agent has no memories."""
    from unittest.mock import AsyncMock, patch

    agent = _make_mock_agent()
    agent.solidified_memories = []

    async def _run():
        mock_db = AsyncMock()
        mock_llm = MagicMock()

        from app.engine.memory_engine import consolidate_agent_memories
        with patch("app.skills.executor.execute") as mock_exec:
            await consolidate_agent_memories(agent, mock_db, mock_llm)
            mock_exec.assert_not_called()

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
