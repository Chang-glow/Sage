"""0.8.6_dm_search TDD tests."""

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


# 0.8.6: DM + search 决策
# ═══════════════════════════════════════════════════


# ── 0.8.6a: DM hook ──

def test_dm_hook_registered():
    """_dm_hook is registered in BrowseHookRegistry at priority 100."""
    from app.engine.browse_hooks import browse_hook_registry
    import app.jobs.agent_lifecycle  # triggers module-level registration

    names = [name for name, _, _ in browse_hook_registry._hooks]
    assert "dm" in names, f"Expected 'dm' in registered hooks, got {names}"

    # Verify priority
    for name, _, priority in browse_hook_registry._hooks:
        if name == "dm":
            assert priority == 100, f"Expected priority=100, got {priority}"


def test_dm_decision_called_after_deep_interaction():
    """DM hook calls execute('dm_decision') and creates PrivateMessage after reply."""
    from unittest.mock import AsyncMock, patch

    agent = _make_mock_agent()
    agent.personality_vector = {"extroversion": 0.9, "openness": 0.8}  # 0.72 > 0.25
    post = _make_mock_post()
    reply_result = {"content": "深度互动的回复内容，交流了很多想法"}

    async def _run():
        mock_db = AsyncMock()
        mock_llm = MagicMock()

        # Mock _count_today_dms to return 0
        with patch("app.jobs.agent_lifecycle._count_today_dms", return_value=0):
            with patch("app.jobs.agent_lifecycle.execute") as mock_exec:
                mock_exec_result = MagicMock()
                mock_exec_result.status = "success"
                mock_exec_result.parsed = {
                    "will_dm": True,
                    "content": "你好，刚才聊得很开心，想加个好友私聊？",
                    "tone": "友善",
                }
                mock_exec.return_value = mock_exec_result

                with patch("app.jobs.agent_lifecycle.build_agent_context",
                           return_value={"agent_name": "测试Agent", "agent_personality": "extroversion=0.90"}):
                    from app.jobs.agent_lifecycle import _dm_hook
                    await _dm_hook(agent, post, MagicMock(), reply_result, mock_db, mock_llm)

                # execute("dm_decision") was called
                mock_exec.assert_called_once()
                call_args = mock_exec.call_args
                assert call_args[0][0] == "dm_decision"

                # PrivateMessage created
                assert mock_db.add.call_count >= 1
                assert mock_db.commit.call_count >= 1

    asyncio.run(_run())


def test_dm_threshold_filter():
    """DM hook skips when extroversion × openness <= dm_outgoing_threshold."""
    from unittest.mock import AsyncMock, patch

    agent = _make_mock_agent()
    agent.personality_vector = {"extroversion": 0.3, "openness": 0.3}  # 0.09 <= 0.25
    post = _make_mock_post()
    reply_result = {"content": "回复内容"}

    async def _run():
        mock_db = AsyncMock()
        mock_llm = MagicMock()

        with patch("app.jobs.agent_lifecycle._count_today_dms", return_value=0):
            with patch("app.jobs.agent_lifecycle.execute") as mock_exec:
                from app.jobs.agent_lifecycle import _dm_hook
                await _dm_hook(agent, post, MagicMock(), reply_result, mock_db, mock_llm)

                # execute should NOT be called
                mock_exec.assert_not_called()

    asyncio.run(_run())


def test_dm_daily_cap():
    """DM hook respects dm_max_per_day config limit."""
    from unittest.mock import AsyncMock, patch
    from app.config import config as yaml_config

    agent = _make_mock_agent()
    agent.personality_vector = {"extroversion": 0.9, "openness": 0.9}
    post = _make_mock_post()
    reply_result = {"content": "回复"}

    max_per_day = yaml_config.browse.dm_max_per_day

    async def _run():
        mock_db = AsyncMock()
        mock_llm = MagicMock()

        # Simulate already at daily cap
        with patch("app.jobs.agent_lifecycle._count_today_dms", return_value=max_per_day):
            with patch("app.jobs.agent_lifecycle.execute") as mock_exec:
                from app.jobs.agent_lifecycle import _dm_hook
                await _dm_hook(agent, post, MagicMock(), reply_result, mock_db, mock_llm)

                mock_exec.assert_not_called()

    asyncio.run(_run())


def test_dm_hook_skips_no_reply():
    """DM hook returns early when reply_result is None."""
    from unittest.mock import AsyncMock, patch

    agent = _make_mock_agent()
    post = _make_mock_post()

    async def _run():
        mock_db = AsyncMock()
        mock_llm = MagicMock()

        with patch("app.jobs.agent_lifecycle.execute") as mock_exec:
            from app.jobs.agent_lifecycle import _dm_hook
            await _dm_hook(agent, post, MagicMock(), None, mock_db, mock_llm)

            mock_exec.assert_not_called()

    asyncio.run(_run())


# ── 0.8.6b: Search hook ──

def test_search_hook_registered():
    """_search_hook is registered in BrowseHookRegistry at priority 40."""
    from app.engine.browse_hooks import browse_hook_registry
    import app.jobs.agent_lifecycle  # triggers module-level registration

    names = [name for name, _, _ in browse_hook_registry._hooks]
    assert "search" in names, f"Expected 'search' in registered hooks, got {names}"

    for name, _, priority in browse_hook_registry._hooks:
        if name == "search":
            assert priority == 40, f"Expected priority=40, got {priority}"


def test_search_decision_triggered_low_similarity():
    """Search hook calls execute('search_decision') when decision is None (filtered post)."""
    from unittest.mock import AsyncMock, patch

    agent = _make_mock_agent()
    post = _make_mock_post()

    # Reset cooldown tracking
    import app.jobs.agent_lifecycle as al_mod
    al_mod._search_cooldowns.clear()
    al_mod._search_counts.clear()

    async def _run():
        mock_db = AsyncMock()
        mock_llm = MagicMock()

        with patch("app.jobs.agent_lifecycle.execute") as mock_exec:
            mock_exec_result = MagicMock()
            mock_exec_result.status = "success"
            mock_exec_result.parsed = {
                "should_search": True,
                "search_query": "平陵市 游戏开发",
                "reason": "对新话题感兴趣",
            }
            mock_exec.return_value = mock_exec_result

            with patch("app.jobs.agent_lifecycle.build_agent_context",
                       return_value={"agent_name": "测试Agent"}):
                from app.jobs.agent_lifecycle import _search_hook
                await _search_hook(agent, post, None, None, mock_db, mock_llm)

            # execute("search_decision") was called
            mock_exec.assert_called_once()
            call_args = mock_exec.call_args
            assert call_args[0][0] == "search_decision"

    asyncio.run(_run())


def test_search_decision_skips_when_decision_present():
    """Search hook returns early when decision is not None (post passed filter)."""
    from unittest.mock import AsyncMock, patch

    agent = _make_mock_agent()
    post = _make_mock_post()
    decision = MagicMock()

    async def _run():
        mock_db = AsyncMock()
        mock_llm = MagicMock()

        with patch("app.jobs.agent_lifecycle.execute") as mock_exec:
            from app.jobs.agent_lifecycle import _search_hook
            await _search_hook(agent, post, decision, None, mock_db, mock_llm)

            mock_exec.assert_not_called()

    asyncio.run(_run())


def test_search_decision_cooldown():
    """Search hook respects search_max_per_cooldown config limit."""
    from unittest.mock import AsyncMock, patch
    from app.config import config as yaml_config

    agent = _make_mock_agent()
    post = _make_mock_post()

    # Reset cooldown tracking
    import app.jobs.agent_lifecycle as al_mod
    al_mod._search_cooldowns.clear()
    al_mod._search_counts.clear()

    max_per_cooldown = yaml_config.browse.search_max_per_cooldown

    async def _run():
        mock_db = AsyncMock()
        mock_llm = MagicMock()

        call_count = 0

        with patch("app.jobs.agent_lifecycle.execute") as mock_exec:
            mock_exec_result = MagicMock()
            mock_exec_result.status = "success"
            mock_exec_result.parsed = {
                "should_search": True,
                "search_query": "搜索关键词",
            }
            mock_exec.return_value = mock_exec_result

            with patch("app.jobs.agent_lifecycle.build_agent_context",
                       return_value={"agent_name": "测试Agent"}):
                from app.jobs.agent_lifecycle import _search_hook

                # Call more times than max_per_cooldown
                for _ in range(max_per_cooldown + 3):
                    await _search_hook(agent, post, None, None, mock_db, mock_llm)
                    call_count += 1

            # execute should be called at most max_per_cooldown times
            assert mock_exec.call_count <= max_per_cooldown, (
                f"Called {mock_exec.call_count} times, max is {max_per_cooldown}"
            )
            assert mock_exec.call_count == max_per_cooldown

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
