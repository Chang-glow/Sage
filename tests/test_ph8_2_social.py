"""0.8.2_social TDD tests."""

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


# 0.8.2: Social actions — like / bookmark / follow hooks
# ═══════════════════════════════════════════════════

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
    author.id = post.author_id
    post.author = author
    bar = MagicMock()
    bar.name = "测试吧"
    post.bar = bar
    return post


# ── Like hook ──

def test_like_hook_registered_in_browse_hooks():
    """_like_hook is registered in BrowseHookRegistry at module import."""
    from app.engine.browse_hooks import browse_hook_registry
    import app.jobs.agent_lifecycle  # triggers module-level registration

    names = [name for name, _, _ in browse_hook_registry._hooks]
    assert "like" in names, f"Expected 'like' in registered hooks, got {names}"


def test_like_hook_creates_like_when_no_reply():
    """like hook creates Like record when decision exists and will_reply=False."""
    from unittest.mock import AsyncMock, patch

    agent = _make_mock_agent()
    post = _make_mock_post()
    decision = MagicMock()
    decision.will_reply = False

    async def _run():
        mock_db = AsyncMock()
        mock_llm = MagicMock()

        with patch("app.jobs.agent_lifecycle.execute") as mock_exec:
            mock_result = MagicMock()
            mock_result.status = "success"
            mock_result.parsed = {"will_like": True, "reason": "感兴趣"}
            mock_exec.return_value = mock_result

            with patch("app.jobs.agent_lifecycle._count_today_likes", return_value=0):
                with patch("app.jobs.agent_lifecycle.build_relationship_context",
                           return_value={"relationship_intimacy": 0.3}):
                    with patch("app.jobs.social_engine.adjust_after_like"):
                        with patch("app.jobs.notification_engine.notify_like"):
                            with patch("app.jobs.level_engine.add_xp"):
                                from app.jobs.agent_lifecycle import _like_hook
                                await _like_hook(agent, post, decision, None, mock_db, mock_llm)

            assert mock_db.add.call_count >= 1
            assert mock_db.commit.call_count >= 1

    asyncio.run(_run())


def test_like_hook_skips_when_replied():
    """like hook should skip when decision.will_reply=True (already replied)."""
    agent = _make_mock_agent()
    post = _make_mock_post()
    decision = MagicMock()
    decision.will_reply = True

    async def _run():
        from unittest.mock import AsyncMock
        mock_db = AsyncMock()
        mock_llm = MagicMock()
        from app.jobs.agent_lifecycle import _like_hook
        await _like_hook(agent, post, decision, None, mock_db, mock_llm)
        # Should not add anything
        assert mock_db.add.call_count == 0

    asyncio.run(_run())


def test_like_hook_skips_when_decision_none():
    """like hook should skip when decision is None (filter didn't pass)."""
    agent = _make_mock_agent()
    post = _make_mock_post()

    async def _run():
        from unittest.mock import AsyncMock
        mock_db = AsyncMock()
        mock_llm = MagicMock()
        from app.jobs.agent_lifecycle import _like_hook
        await _like_hook(agent, post, None, None, mock_db, mock_llm)
        assert mock_db.add.call_count == 0

    asyncio.run(_run())


# ── Bookmark hook ──

def test_bookmark_hook_registered_in_browse_hooks():
    """_bookmark_hook is registered in BrowseHookRegistry at module import."""
    from app.engine.browse_hooks import browse_hook_registry
    import app.jobs.agent_lifecycle

    names = [name for name, _, _ in browse_hook_registry._hooks]
    assert "bookmark" in names, f"Expected 'bookmark' in registered hooks, got {names}"


def test_bookmark_hook_creates_bookmark():
    """bookmark hook creates Bookmark record when decision exists."""
    agent = _make_mock_agent()
    post = _make_mock_post()
    decision = MagicMock()

    async def _run():
        from unittest.mock import AsyncMock, patch
        mock_db = AsyncMock()
        mock_llm = MagicMock()

        # Mock: no existing bookmark
        mock_db.execute = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        with patch("app.jobs.agent_lifecycle.execute") as mock_exec:
            mock_exec_result = MagicMock()
            mock_exec_result.status = "success"
            mock_exec_result.parsed = {"will_bookmark": True, "reason": "有用"}
            mock_exec.return_value = mock_exec_result

            from app.jobs.agent_lifecycle import _bookmark_hook
            await _bookmark_hook(agent, post, decision, None, mock_db, mock_llm)

            # Bookmark should be created
            assert mock_db.add.call_count >= 1
            assert mock_db.commit.call_count >= 1

    asyncio.run(_run())


def test_bookmark_hook_skips_already_bookmarked():
    """bookmark hook skips when the post is already bookmarked."""
    agent = _make_mock_agent()
    post = _make_mock_post()
    decision = MagicMock()

    async def _run():
        from unittest.mock import AsyncMock, patch
        from app.models.social import Bookmark

        mock_db = AsyncMock()
        mock_llm = MagicMock()

        # Mock: existing bookmark found
        mock_db.execute = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = Bookmark()
        mock_db.execute.return_value = mock_result

        with patch("app.jobs.agent_lifecycle.execute") as mock_exec:
            from app.jobs.agent_lifecycle import _bookmark_hook
            await _bookmark_hook(agent, post, decision, None, mock_db, mock_llm)
            # Execute should NOT be called since already bookmarked
            mock_exec.assert_not_called()

    asyncio.run(_run())


def test_bookmark_hook_skips_when_decision_none():
    """bookmark hook should skip when decision is None."""
    agent = _make_mock_agent()
    post = _make_mock_post()

    async def _run():
        from unittest.mock import AsyncMock
        mock_db = AsyncMock()
        mock_llm = MagicMock()
        from app.jobs.agent_lifecycle import _like_hook  # just to trigger import
        from app.jobs.agent_lifecycle import _bookmark_hook
        await _bookmark_hook(agent, post, None, None, mock_db, mock_llm)
        assert mock_db.add.call_count == 0

    asyncio.run(_run())


# ── Follow hook ──

def test_follow_hook_registered_in_browse_hooks():
    """_follow_hook is registered in BrowseHookRegistry at module import."""
    from app.engine.browse_hooks import browse_hook_registry
    import app.jobs.agent_lifecycle

    names = [name for name, _, _ in browse_hook_registry._hooks]
    assert "follow" in names, f"Expected 'follow' in registered hooks, got {names}"


def test_follow_hook_creates_follow_after_reply():
    """follow hook creates Follow record when reply_result exists."""
    agent = _make_mock_agent()
    post = _make_mock_post()
    reply_result = {"content": "你好，我也喜欢这个"}

    async def _run():
        from unittest.mock import AsyncMock, patch

        mock_db = AsyncMock()
        mock_llm = MagicMock()

        # Mock: no existing follow
        mock_db.execute = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        with patch("app.jobs.agent_lifecycle.execute") as mock_exec:
            mock_exec_result = MagicMock()
            mock_exec_result.status = "success"
            mock_exec_result.parsed = {"will_follow": True, "reason": "志趣相投"}
            mock_exec.return_value = mock_exec_result

            with patch("app.jobs.agent_lifecycle.build_relationship_context",
                       return_value={"relationship_intimacy": 0.3}):
                with patch("app.jobs.social_engine.adjust_after_follow"):
                    with patch("app.jobs.notification_engine.notify_follow"):
                        from app.jobs.agent_lifecycle import _follow_hook
                        await _follow_hook(agent, post, None, reply_result, mock_db, mock_llm)

                        assert mock_db.add.call_count >= 1
                        assert mock_db.commit.call_count >= 1

    asyncio.run(_run())


def test_follow_hook_skips_when_no_reply():
    """follow hook skips when reply_result is None."""
    agent = _make_mock_agent()
    post = _make_mock_post()

    async def _run():
        from unittest.mock import AsyncMock
        mock_db = AsyncMock()
        mock_llm = MagicMock()
        from app.jobs.agent_lifecycle import _follow_hook
        await _follow_hook(agent, post, None, None, mock_db, mock_llm)
        assert mock_db.add.call_count == 0

    asyncio.run(_run())


def test_follow_hook_skips_already_following():
    """follow hook skips when already following."""
    agent = _make_mock_agent()
    post = _make_mock_post()
    reply_result = {"content": "回复内容"}

    async def _run():
        from unittest.mock import AsyncMock, patch
        from app.models.social import Follow

        mock_db = AsyncMock()
        mock_llm = MagicMock()

        # Mock: existing follow found
        mock_db.execute = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = Follow()
        mock_db.execute.return_value = mock_result

        with patch("app.jobs.agent_lifecycle.execute") as mock_exec:
            from app.jobs.agent_lifecycle import _follow_hook
            await _follow_hook(agent, post, None, reply_result, mock_db, mock_llm)
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
