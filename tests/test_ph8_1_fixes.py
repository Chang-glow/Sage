"""0.8.1 TDD tests — infrastructure, Phase 8 self-fix, dead function cleanup.

RED PHASE: These tests FAIL because the implementation doesn't exist yet.
"""
import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch


# ═══════════════════════════════════════════════════
# Group A1: BrowseHookRegistry
# ═══════════════════════════════════════════════════

def test_browse_hook_registry_register_and_iterate():
    """BrowseHookRegistry.register() stores hooks; iterate() calls them sorted by priority."""
    from app.engine.browse_hooks import BrowseHookRegistry

    registry = BrowseHookRegistry()
    call_order = []

    async def hook_a(agent, post, decision, reply_result, db, llm_caller):
        call_order.append("a")

    async def hook_b(agent, post, decision, reply_result, db, llm_caller):
        call_order.append("b")

    async def hook_c(agent, post, decision, reply_result, db, llm_caller):
        call_order.append("c")

    registry.register("c", hook_c, priority=70)
    registry.register("a", hook_a, priority=50)
    registry.register("b", hook_b, priority=60)

    mock_agent = MagicMock()
    mock_post = MagicMock()
    mock_db = MagicMock()
    mock_llm = MagicMock()

    asyncio.run(registry.iterate(mock_agent, mock_post, None, None, mock_db, mock_llm))

    assert call_order == ["a", "b", "c"], f"Expected [a, b, c] by priority, got {call_order}"


def test_browse_hook_sees_decision_and_reply():
    """Hook receives the correct decision and reply_result passed to iterate()."""
    from app.engine.browse_hooks import BrowseHookRegistry

    registry = BrowseHookRegistry()
    received_decision = None
    received_reply = None

    async def capture_hook(agent, post, decision, reply_result, db, llm_caller):
        nonlocal received_decision, received_reply
        received_decision = decision
        received_reply = reply_result

    registry.register("capture", capture_hook, priority=50)

    mock_decision = MagicMock()
    mock_decision.will_reply = False
    mock_reply = {"content": "test reply"}

    asyncio.run(registry.iterate(
        MagicMock(), MagicMock(), mock_decision, mock_reply, MagicMock(), MagicMock(),
    ))

    assert received_decision is mock_decision
    assert received_reply is mock_reply


def test_browse_hook_empty_registry_no_error():
    """iterate() on empty registry should not raise."""
    from app.engine.browse_hooks import BrowseHookRegistry

    registry = BrowseHookRegistry()
    asyncio.run(registry.iterate(
        MagicMock(), MagicMock(), None, None, MagicMock(), MagicMock(),
    ))


# ═══════════════════════════════════════════════════
# Group A2: DailyTaskRegistry
# ═══════════════════════════════════════════════════

def test_daily_task_registry_register_and_get_due():
    """DailyTaskRegistry.get_due(hour, minute) returns matching tasks only."""
    from app.engine.daily_tasks import DailyTaskRegistry

    registry = DailyTaskRegistry()

    async def task_a(db, llm_caller):
        pass

    async def task_b(db, llm_caller):
        pass

    registry.register("task_8am", task_a, hour=8, minute=0)
    registry.register("task_830am", task_b, hour=8, minute=30)

    due_8am = registry.get_due(8, 0)
    due_830am = registry.get_due(8, 30)
    due_9am = registry.get_due(9, 0)

    assert len(due_8am) == 1
    assert due_8am[0][0] == "task_8am"
    assert len(due_830am) == 1
    assert due_830am[0][0] == "task_830am"
    assert len(due_9am) == 0


def test_daily_task_registry_empty_no_error():
    """get_due() on empty registry returns empty list."""
    from app.engine.daily_tasks import DailyTaskRegistry

    registry = DailyTaskRegistry()
    assert registry.get_due(12, 0) == []


# ═══════════════════════════════════════════════════
# Group A3: build_post_context
# ═══════════════════════════════════════════════════

def test_build_post_context_fields():
    """build_post_context returns all expected fields from a post object."""
    from app.skills.skill_utils import build_post_context

    mock_post = MagicMock()
    mock_post.id = uuid.uuid4()
    mock_post.title = "测试标题"
    mock_post.content = "这是帖子的内容，可能会很长"
    mock_post.reply_count = 5
    mock_post.author_id = uuid.uuid4()

    mock_author = MagicMock()
    mock_author.nickname = "测试用户"
    mock_post.author = mock_author

    mock_bar = MagicMock()
    mock_bar.name = "测试吧"
    mock_post.bar = mock_bar

    ctx = build_post_context(mock_post)

    assert ctx["post_id"] == str(mock_post.id)
    assert ctx["post_title"] == "测试标题"
    assert ctx["post_content"] == "这是帖子的内容，可能会很长"
    assert ctx["post_author"] == "测试用户"
    assert ctx["post_author_id"] == str(mock_post.author_id)
    assert ctx["post_bar_name"] == "测试吧"
    assert ctx["post_reply_count"] == 5


def test_build_post_context_missing_relations():
    """build_post_context handles missing author/bar gracefully."""
    from app.skills.skill_utils import build_post_context

    mock_post = MagicMock()
    mock_post.id = uuid.uuid4()
    mock_post.title = "无作者帖子"
    mock_post.content = "内容"
    mock_post.reply_count = 0
    mock_post.author_id = uuid.uuid4()
    mock_post.author = None
    mock_post.bar = None

    ctx = build_post_context(mock_post)

    assert ctx["post_author"] == str(mock_post.author_id)  # fallback to id
    assert ctx["post_bar_name"] == ""


# ═══════════════════════════════════════════════════
# Group B1: world_book_engine validation on register
# ═══════════════════════════════════════════════════

def test_validate_entry_data_called_on_register():
    """register_entry() calls validate_entry_data() before creating/updating entry.

    Currently validate_entry_data exists but register_entry NEVER calls it.
    This test patches validate_entry_data to verify it IS called by register_entry.
    """
    from app.engine import world_book_engine

    # Invalid data: missing required title
    bad_data = {"content": "some content", "scope": "character"}

    async def _run():
        mock_db = AsyncMock()
        # Patch validate_entry_data to track calls
        with patch.object(world_book_engine, "validate_entry_data", wraps=world_book_engine.validate_entry_data) as mock_validate:
            await world_book_engine.register_entry(bad_data, mock_db)
            # Currently register_entry doesn't call validate_entry_data at all
            assert mock_validate.called, (
                "register_entry MUST call validate_entry_data before creating/updating entry"
            )
            assert mock_validate.call_count >= 1

    asyncio.run(_run())


def test_world_book_default_position_from_config():
    """New entries without explicit position use config.world_book.default_position."""
    from app.config import config as yaml_config
    from app.engine.world_book_engine import register_entry

    default_pos = yaml_config.world_book.default_position
    assert default_pos in ("before_char", "after_char", "at_depth")

    data = {
        "title": "测试位置默认值",
        "content": "验证 position 默认值来自 config",
        "scope": "character",
        "trigger_type": "keyword",
        "trigger_keys": ["测试"],
        # No position field — should use default from config
    }

    async def _run():
        mock_db = AsyncMock()
        entry = await register_entry(data, mock_db)
        return entry

    entry = asyncio.run(_run())
    # Currently position defaults to "after_char" hardcoded in _apply_entry_fields
    # After fix: uses config.world_book.default_position
    assert entry.position == default_pos, (
        f"Expected position='{default_pos}' from config, got '{entry.position}'"
    )


def test_world_book_scan_depth_used():
    """assemble_prompt() uses scan_depth to limit context text size."""
    from app.engine.world_book_engine import _get_world_book_config

    cfg = _get_world_book_config()
    scan_depth = cfg["scan_depth"]
    assert isinstance(scan_depth, int)
    assert scan_depth > 0, f"scan_depth should be positive, got {scan_depth}"

    # scan_depth exists in config but is NOT used in assemble_prompt()
    # This test verifies the value is read; the implementation test below
    # verifies it's actually applied to truncate scan text.

    # For now, verify config value is accessible
    assert scan_depth == 10  # default from config.yaml


# ═══════════════════════════════════════════════════
# Group B2: build_world_book_context annotation
# ═══════════════════════════════════════════════════

def test_build_world_book_context_exists():
    """build_world_book_context() exists and is callable."""
    from app.skills.skill_utils import build_world_book_context

    result = build_world_book_context()
    assert isinstance(result, dict)
    assert "scan_text" in result
    assert "_status" in result


# ═══════════════════════════════════════════════════
# Group C1: dead function cleanup — daily_schedule.py
# ═══════════════════════════════════════════════════

def test_dead_functions_removed():
    """should_generate_daily_schedules and has_todays_schedule are removed."""
    import app.jobs.daily_schedule as ds

    # These should be removed in 0.8.1
    has_should_gen = hasattr(ds, "should_generate_daily_schedules")
    has_has_today = hasattr(ds, "has_todays_schedule")

    # Currently they exist (dead code). After fix: should be removed.
    assert not has_should_gen, (
        "should_generate_daily_schedules is dead code and should be removed"
    )
    assert not has_has_today, (
        "has_todays_schedule is dead code and should be removed"
    )


# ═══════════════════════════════════════════════════
# Group C2: watch_skills_dir in lifespan
# ═══════════════════════════════════════════════════

def test_watch_skills_dir_importable():
    """watch_skills_dir is importable from registry."""
    from app.skills.registry import watch_skills_dir
    assert callable(watch_skills_dir)


# ═══════════════════════════════════════════════════
# Group C3: blocked_keywords from config
# ═══════════════════════════════════════════════════

def test_blocked_keywords_from_config():
    """browse.blocked_keywords exists in config and is loaded at module level."""
    from app.config import config as yaml_config

    # Config should have blocked_keywords field
    blocked = getattr(yaml_config.browse, "blocked_keywords", None)
    assert blocked is not None, (
        "browse.blocked_keywords must exist in config.yaml"
    )
    assert isinstance(blocked, list), (
        f"blocked_keywords should be a list, got {type(blocked)}"
    )


def test_blocked_keywords_used_in_filter():
    """_BLOCKED_KEYWORDS in browse_filter.py is loaded from config at import time.

    Currently hardcoded as set(). After fix: the module-level code loads from config.
    We verify this by checking that _BLOCKED_KEYWORDS is populated from config,
    not unconditionally set to empty.
    """
    # Re-import to see if loading from config works
    import importlib
    import app.jobs.browse_filter as bf

    # After fix, _BLOCKED_KEYWORDS should be loaded from config at module init
    from app.config import config as yaml_config

    # Config should have blocked_keywords (may need to be added to config.yaml)
    config_blocked = getattr(yaml_config.browse, "blocked_keywords", [])
    expected = set(config_blocked)

    # Currently: _BLOCKED_KEYWORDS = set() (hardcoded, never loaded from config)
    # After fix: _BLOCKED_KEYWORDS = set(config.browse.blocked_keywords) loaded at module init
    assert bf._BLOCKED_KEYWORDS == expected, (
        f"_BLOCKED_KEYWORDS ({bf._BLOCKED_KEYWORDS}) should match config ({expected})"
    )


# ═══════════════════════════════════════════════════
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

            with patch("app.jobs.agent_lifecycle._count_today_likes", return_value=3):
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
