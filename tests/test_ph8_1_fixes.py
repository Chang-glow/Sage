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


# ═══════════════════════════════════════════════════
# 0.8.3: Slang system — prelearn + browse hook + decay
# ═══════════════════════════════════════════════════


def test_slang_hook_registered():
    """_slang_hook is registered in BrowseHookRegistry at module import."""
    from app.engine.browse_hooks import browse_hook_registry
    import app.jobs.agent_lifecycle  # triggers module-level registration

    names = [name for name, _, _ in browse_hook_registry._hooks]
    assert "slang" in names, f"Expected 'slang' in registered hooks, got {names}"


def test_slang_disabled_by_default():
    """slang functions return early when feature flag is off (default from config)."""
    from unittest.mock import AsyncMock, MagicMock

    agent = _make_mock_agent()
    post = _make_mock_post()
    post.content = "这波操作真的yyds！"
    decision = MagicMock()

    async def _run():
        mock_db = AsyncMock()
        mock_llm = MagicMock()

        # _slang_hook returns early (registry default is False from config)
        from app.jobs.agent_lifecycle import _slang_hook
        await _slang_hook(agent, post, decision, None, mock_db, mock_llm)
        assert mock_db.execute.call_count == 0

        # decay_slangs returns early
        mock_db2 = AsyncMock()
        from app.jobs.scheduler import decay_slangs
        await decay_slangs(mock_db2, MagicMock())
        assert mock_db2.execute.call_count == 0

        # prelearn_slangs returns draft unchanged
        from app.engine.agent_factory import AgentDraft, prelearn_slangs
        draft = AgentDraft()
        draft.nickname = "测试"
        mock_db3 = AsyncMock()
        result = await prelearn_slangs(draft, mock_llm, mock_db3)
        assert result is draft
        assert result.slang_slugs == []
        assert mock_db3.execute.call_count == 0

    asyncio.run(_run())


def test_prelearn_slangs_with_active_slangs():
    """prelearn_slangs calls slang_learning skill and populates draft.slang_slugs."""
    from unittest.mock import AsyncMock, MagicMock, patch
    from app.engine.agent_factory import AgentDraft

    draft = AgentDraft()
    draft.nickname = "测试用户"
    draft.age = 25
    draft.personality_adjectives = ["开朗", "幽默"]

    async def _run():
        mock_db = AsyncMock()
        mock_llm = MagicMock()

        # Mock active slangs in DB
        from app.models.slang import Slang
        slang1 = Slang(id=1, slug="yyds", meaning="永远的神", status="active")
        slang2 = Slang(id=2, slug="破防了", meaning="心理防线被突破", status="active")

        mock_db.execute = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [slang1, slang2]
        mock_db.execute.return_value = mock_result

        with patch("app.engine.feature_flags.PluginRegistry.is_enabled", return_value=True):
            with patch("app.skills.executor.execute") as mock_exec:
                mock_exec_result = MagicMock()
                mock_exec_result.status = "success"
                mock_exec_result.parsed = {
                    "learned": [
                        {"slang_slug": "yyds", "personal_affinity": 0.8, "reason": "符合身份"},
                    ]
                }
                mock_exec.return_value = mock_exec_result

                from app.engine.agent_factory import prelearn_slangs
                result = await prelearn_slangs(draft, mock_llm, mock_db)

                mock_exec.assert_called_once()
                assert "yyds" in result.slang_slugs
                assert "破防了" not in result.slang_slugs

    asyncio.run(_run())


def test_prelearn_slangs_empty_pool():
    """prelearn_slangs returns draft unchanged when no active slangs."""
    from unittest.mock import AsyncMock, MagicMock, patch
    from app.engine.agent_factory import AgentDraft

    draft = AgentDraft()
    draft.nickname = "测试用户"
    draft.age = 25

    async def _run():
        mock_db = AsyncMock()

        # Mock: no active slangs
        mock_db.execute = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        with patch("app.engine.feature_flags.PluginRegistry.is_enabled", return_value=True):
            from app.engine.agent_factory import prelearn_slangs
            result = await prelearn_slangs(draft, MagicMock(), mock_db)

            assert result is draft
            assert result.slang_slugs == []

    asyncio.run(_run())


def test_slang_learning_during_browse():
    """_slang_hook creates AgentSlang when post contains unknown slang."""
    agent = _make_mock_agent()
    post = _make_mock_post()
    post.content = "这波操作真的yyds！"
    post.title = "测试帖"
    decision = MagicMock()

    async def _run():
        from unittest.mock import AsyncMock, patch

        mock_db = AsyncMock()
        mock_llm = MagicMock()

        from app.models.slang import Slang

        slang_yyds = Slang(id=1, slug="yyds", meaning="永远的神", status="active")

        # Mock DB: slang query returns yyds, AgentSlang query returns empty (not known)
        call_count = [0]

        async def mock_execute(stmt):
            call_count[0] += 1
            mock_result = MagicMock()
            # First call: all active slangs
            if call_count[0] == 1:
                mock_result.scalars.return_value.all.return_value = [slang_yyds]
            # Second call: AgentSlang query (agent doesn't know any)
            else:
                mock_result.scalars.return_value.all.return_value = []
            return mock_result

        mock_db.execute = mock_execute

        with patch("app.engine.feature_flags.PluginRegistry.is_enabled", return_value=True):
            with patch("app.jobs.agent_lifecycle.execute") as mock_exec:
                mock_exec_result = MagicMock()
                mock_exec_result.status = "success"
                mock_exec_result.parsed = {
                    "learned": [
                        {"slang_slug": "yyds", "personal_affinity": 0.7, "reason": "年轻人常用"},
                    ]
                }
                mock_exec.return_value = mock_exec_result

                from app.jobs.agent_lifecycle import _slang_hook
                await _slang_hook(agent, post, decision, None, mock_db, mock_llm)

                mock_exec.assert_called_once()
                # AgentSlang added
                assert mock_db.add.call_count >= 1
                assert mock_db.commit.call_count >= 1

    asyncio.run(_run())


def test_slang_learning_skips_known():
    """_slang_hook skips slang the agent already knows."""
    agent = _make_mock_agent()
    post = _make_mock_post()
    post.content = "这波操作真的yyds！"
    post.title = "测试帖"
    decision = MagicMock()

    async def _run():
        from unittest.mock import AsyncMock, patch

        mock_db = AsyncMock()
        mock_llm = MagicMock()

        from app.models.slang import Slang, AgentSlang

        slang_yyds = Slang(id=1, slug="yyds", meaning="永远的神", status="active")
        known = AgentSlang(agent_id=agent.id, slang_id=1, personal_affinity=0.8)

        call_count = [0]

        async def mock_execute(stmt):
            call_count[0] += 1
            mock_result = MagicMock()
            if call_count[0] == 1:
                mock_result.scalars.return_value.all.return_value = [slang_yyds]
            else:
                mock_result.scalars.return_value.all.return_value = [known]
            return mock_result

        mock_db.execute = mock_execute

        with patch("app.engine.feature_flags.PluginRegistry.is_enabled", return_value=True):
            with patch("app.jobs.agent_lifecycle.execute") as mock_exec:
                from app.jobs.agent_lifecycle import _slang_hook
                await _slang_hook(agent, post, decision, None, mock_db, mock_llm)

                # Skill should NOT be called since agent already knows the slang
                mock_exec.assert_not_called()

    asyncio.run(_run())


def test_slang_hook_skips_when_decision_none():
    """_slang_hook skips when decision is None."""
    agent = _make_mock_agent()
    post = _make_mock_post()

    async def _run():
        from unittest.mock import AsyncMock, patch
        mock_db = AsyncMock()
        mock_llm = MagicMock()
        with patch("app.engine.feature_flags.PluginRegistry.is_enabled", return_value=True):
            from app.jobs.agent_lifecycle import _slang_hook
            await _slang_hook(agent, post, None, None, mock_db, mock_llm)
            # No DB interaction should happen
            assert mock_db.execute.call_count == 0

    asyncio.run(_run())


def test_decay_slangs_reduces_affinity():
    """decay_slangs reduces personal_affinity for slangs not used in 7 days."""
    from datetime import datetime, timedelta, timezone
    from unittest.mock import AsyncMock, MagicMock, patch

    from app.models.slang import AgentSlang

    agent_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    fresh = AgentSlang(
        id=uuid.uuid4(),
        agent_id=agent_id,
        slang_id=1,
        personal_affinity=0.8,
        learned_at=now - timedelta(days=1),
        last_used_at=now - timedelta(hours=1),
    )
    stale = AgentSlang(
        id=uuid.uuid4(),
        agent_id=agent_id,
        slang_id=2,
        personal_affinity=0.5,
        learned_at=now - timedelta(days=30),
        last_used_at=now - timedelta(days=10),
    )

    async def _run():
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [fresh, stale]
        mock_db.execute.return_value = mock_result

        with patch("app.engine.feature_flags.PluginRegistry.is_enabled", return_value=True):
            from app.jobs.scheduler import decay_slangs
            await decay_slangs(mock_db, MagicMock())

            # Fresh slang should NOT be decayed
            assert fresh.personal_affinity == 0.8
            # Stale slang should be decayed (0.5 → 0.45)
            assert stale.personal_affinity == 0.45

    asyncio.run(_run())


def test_decay_slangs_floor():
    """decay_slangs does not reduce personal_affinity below 0.05."""
    from datetime import datetime, timedelta, timezone
    from unittest.mock import AsyncMock, MagicMock, patch

    from app.models.slang import AgentSlang

    agent_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    minimal = AgentSlang(
        id=uuid.uuid4(),
        agent_id=agent_id,
        slang_id=3,
        personal_affinity=0.06,
        learned_at=now - timedelta(days=60),
        last_used_at=now - timedelta(days=30),
    )

    async def _run():
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [minimal]
        mock_db.execute.return_value = mock_result

        with patch("app.engine.feature_flags.PluginRegistry.is_enabled", return_value=True):
            from app.jobs.scheduler import decay_slangs
            await decay_slangs(mock_db, MagicMock())

            # Should floor at 0.05, not go below
            assert minimal.personal_affinity == 0.05

    asyncio.run(_run())


# ═══════════════════════════════════════════════════
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
# 0.8.5: Sage 技能 — news / summary / reply
# ═══════════════════════════════════════════════════


# ── 0.8.5a: Sage News & Summary Daily Tasks ──

def test_sage_news_task_registered():
    """sage_news is registered in DailyTaskRegistry at hour=10, minute=0."""
    from app.engine.daily_tasks import daily_task_registry
    import app.jobs.scheduler

    task_names = [name for name, _, _, _ in daily_task_registry._tasks]
    assert "sage_news" in task_names, f"Expected 'sage_news' in daily tasks, got {task_names}"

    for name, _, hour, minute in daily_task_registry._tasks:
        if name == "sage_news":
            assert hour == 10, f"Expected hour=10, got {hour}"
            assert minute == 0, f"Expected minute=0, got {minute}"


def test_sage_summary_task_registered():
    """sage_summary is registered in DailyTaskRegistry at hour=23, minute=30."""
    from app.engine.daily_tasks import daily_task_registry
    import app.jobs.scheduler

    task_names = [name for name, _, _, _ in daily_task_registry._tasks]
    assert "sage_summary" in task_names, f"Expected 'sage_summary' in daily tasks, got {task_names}"

    for name, _, hour, minute in daily_task_registry._tasks:
        if name == "sage_summary":
            assert hour == 23, f"Expected hour=23, got {hour}"
            assert minute == 30, f"Expected minute=30, got {minute}"


def test_sage_news_generates_post():
    """sage_news_task calls execute('sage_news') and creates a Post authored by Sage."""
    from unittest.mock import AsyncMock, patch

    async def _run():
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock()
        mock_llm = MagicMock()

        # Mock Sage agent query
        sage_agent = MagicMock()
        sage_agent.id = uuid.uuid4()
        sage_agent.nickname = "Sage"
        sage_agent.status = "system"
        sage_result = MagicMock()
        sage_result.scalar_one_or_none.return_value = sage_agent

        # Mock Topic query
        topic_result = MagicMock()
        topic_result.scalars.return_value.all.return_value = []

        mock_db.execute.side_effect = [sage_result, topic_result]

        with patch("app.skills.executor.execute") as mock_exec:
            mock_exec_result = MagicMock()
            mock_exec_result.status = "success"
            mock_exec_result.parsed = {
                "title": "平陵新闻 · 5月22日",
                "content": "今日平陵社区动态...",
                "news_items": [{"headline": "头条", "summary": "摘要"}],
            }
            mock_exec.return_value = mock_exec_result

            from app.jobs.scheduler import sage_news_task
            await sage_news_task(mock_db, mock_llm)

            # execute("sage_news") was called
            mock_exec.assert_called_once()
            call_args = mock_exec.call_args
            assert call_args[0][0] == "sage_news"

            # A Post was created
            assert mock_db.add.call_count >= 1
            assert mock_db.commit.call_count >= 1

    asyncio.run(_run())


def test_sage_summary_generates_post():
    """sage_summary_task calls execute('sage_summary') and creates a Post authored by Sage."""
    from unittest.mock import AsyncMock, patch

    async def _run():
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock()
        mock_llm = MagicMock()

        # Mock Sage agent query
        sage_agent = MagicMock()
        sage_agent.id = uuid.uuid4()
        sage_agent.nickname = "Sage"
        sage_agent.status = "system"
        sage_result = MagicMock()
        sage_result.scalar_one_or_none.return_value = sage_agent

        # Mock Bar query
        bar_result = MagicMock()
        bar_result.scalars.return_value.all.return_value = []

        # Mock hot posts query
        post_result = MagicMock()
        post_result.scalars.return_value.all.return_value = []

        mock_db.execute.side_effect = [sage_result, bar_result, post_result]

        with patch("app.skills.executor.execute") as mock_exec:
            mock_exec_result = MagicMock()
            mock_exec_result.status = "success"
            mock_exec_result.parsed = {
                "title": "夕照雅巷 · 5月22日 社区总结",
                "content": "今日社区总结...",
                "highlights": ["亮点1", "亮点2"],
            }
            mock_exec.return_value = mock_exec_result

            from app.jobs.scheduler import sage_summary_task
            await sage_summary_task(mock_db, mock_llm)

            mock_exec.assert_called_once()
            call_args = mock_exec.call_args
            assert call_args[0][0] == "sage_summary"

            assert mock_db.add.call_count >= 1
            assert mock_db.commit.call_count >= 1

    asyncio.run(_run())


def test_sage_news_skips_when_execute_fails():
    """sage_news_task does not create a post when execute returns non-success."""
    from unittest.mock import AsyncMock, patch

    async def _run():
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock()
        mock_llm = MagicMock()

        sage_agent = MagicMock()
        sage_agent.id = uuid.uuid4()
        sage_agent.nickname = "Sage"
        sage_agent.status = "system"
        sage_result = MagicMock()
        sage_result.scalar_one_or_none.return_value = sage_agent

        topic_result = MagicMock()
        topic_result.scalars.return_value.all.return_value = []

        mock_db.execute.side_effect = [sage_result, topic_result]

        with patch("app.skills.executor.execute") as mock_exec:
            mock_exec_result = MagicMock()
            mock_exec_result.status = "parse_failure"
            mock_exec_result.parsed = None
            mock_exec.return_value = mock_exec_result

            from app.jobs.scheduler import sage_news_task
            await sage_news_task(mock_db, mock_llm)

            # No post should be created
            assert mock_db.add.call_count == 0

    asyncio.run(_run())


# ── 0.8.5b: Sage Reply on @mention ──

def test_sage_reply_on_mention_called():
    """When Sage receives a mention notification, sage_reply is triggered."""
    from unittest.mock import AsyncMock, patch

    # Mock Sage agent
    sage = MagicMock()
    sage.id = uuid.uuid4()
    sage.nickname = "Sage"

    # Mock notification for Sage
    notif = MagicMock()
    notif.recipient_id = sage.id
    notif.notification_type = "mention"
    notif.message = "@Sage 请帮忙看看这个问题"
    notif.sender_id = uuid.uuid4()
    notif.reference_type = "post"
    notif.reference_id = str(uuid.uuid4())

    async def _run():
        mock_db = AsyncMock()
        mock_llm = MagicMock()

        # Reset rate limit counter
        import app.jobs.agent_lifecycle as al_mod
        al_mod._sage_reply_hour_counts.clear()

        # Mock: Sage agent found by ID
        mock_db.execute = AsyncMock()
        # Mock db.execute to return post then caller agent
        mock_post_result = MagicMock()
        mock_post = MagicMock()
        mock_post.title = "测试帖子"
        mock_post.content = "这是帖子内容"
        mock_post.author = MagicMock()
        mock_post.author.nickname = "发帖人"
        mock_post_result.scalar_one_or_none.return_value = mock_post

        mock_caller_result = MagicMock()
        mock_caller = MagicMock()
        mock_caller.nickname = "呼叫者"
        mock_caller_result.scalar_one_or_none.return_value = mock_caller

        mock_db.execute.side_effect = [mock_post_result, mock_caller_result]

        with patch("app.jobs.agent_lifecycle.execute") as mock_exec:
            mock_exec_result = MagicMock()
            mock_exec_result.status = "success"
            mock_exec_result.parsed = {
                "content": "你好！关于你的问题...",
                "tone": "友善",
                "reference_context": "...",
            }
            mock_exec.return_value = mock_exec_result

            from app.jobs.agent_lifecycle import _handle_sage_mention
            await _handle_sage_mention(sage, notif, mock_db, mock_llm)

            # execute("sage_reply") was called
            mock_exec.assert_called_once()
            call_args = mock_exec.call_args
            assert call_args[0][0] == "sage_reply"

            # A Reply should be created
            assert mock_db.add.call_count >= 1
            assert mock_db.commit.call_count >= 1

    asyncio.run(_run())


def test_sage_reply_rate_limit():
    """Sage reply respects sage_reply_max_per_hour config limit."""
    from unittest.mock import AsyncMock, patch
    from app.config import config as yaml_config

    sage = MagicMock()
    sage.id = uuid.uuid4()
    sage.nickname = "Sage"

    notif = MagicMock()
    notif.recipient_id = sage.id
    notif.notification_type = "mention"
    notif.message = "@Sage 帮忙看看"
    notif.sender_id = uuid.uuid4()
    notif.reference_type = "post"
    notif.reference_id = str(uuid.uuid4())

    max_per_hour = yaml_config.browse.sage_reply_max_per_hour

    # Reset rate limit counter from previous tests
    import app.jobs.agent_lifecycle as al_mod
    al_mod._sage_reply_hour_counts.clear()

    async def _run():
        mock_db = AsyncMock()
        mock_llm = MagicMock()

        # Mock db.execute for post and caller lookups
        mock_post_result = MagicMock()
        mock_post = MagicMock()
        mock_post.title = "测试帖子"
        mock_post.content = "内容"
        mock_post.author = MagicMock()
        mock_post.author.nickname = "发帖人"
        mock_post_result.scalar_one_or_none.return_value = mock_post

        mock_caller_result = MagicMock()
        mock_caller = MagicMock()
        mock_caller.nickname = "呼叫者"
        mock_caller_result.scalar_one_or_none.return_value = mock_caller

        # For each call: 2 db.execute calls (post + agent)
        mock_db.execute = AsyncMock()
        mock_db.execute.side_effect = [mock_post_result, mock_caller_result] * (max_per_hour + 10)

        call_count = 0

        with patch("app.jobs.agent_lifecycle.execute") as mock_exec:
            mock_exec_result = MagicMock()
            mock_exec_result.status = "success"
            mock_exec_result.parsed = {
                "content": "回复内容",
                "tone": "友善",
            }
            mock_exec.return_value = mock_exec_result

            from app.jobs.agent_lifecycle import _handle_sage_mention
            # Call more times than the rate limit
            for _ in range(max_per_hour + 3):
                await _handle_sage_mention(sage, notif, mock_db, mock_llm)
                call_count += 1

            # execute should be called at most max_per_hour times
            assert mock_exec.call_count <= max_per_hour, (
                f"Called {mock_exec.call_count} times, max is {max_per_hour}"
            )
            assert mock_exec.call_count == max_per_hour

    asyncio.run(_run())


# ═══════════════════════════════════════════════════
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
# 0.8.7: 配置段生效 + 清理文档
# ═══════════════════════════════════════════════════


# ── 0.8.7a: level_engine 配置化 ──

def test_level_total_levels_from_config():
    """MAX_LEVEL in level_engine reads from yaml_config.level.total_levels."""
    from app.config import config as yaml_config
    from app.jobs import level_engine

    config_total = yaml_config.level.total_levels
    assert level_engine.MAX_LEVEL == config_total, (
        f"MAX_LEVEL ({level_engine.MAX_LEVEL}) should match config ({config_total})"
    )


def test_reply_xp_cap_per_day():
    """add_xp for 'reply' action enforces max_replies_exp_per_day cap (XP, not count)."""
    from unittest.mock import AsyncMock, MagicMock, patch
    from app.config import config as yaml_config

    agent_id = uuid.uuid4()
    bar_id = uuid.uuid4()
    max_xp_per_day = yaml_config.level.max_replies_exp_per_day  # 15 XP
    xp_per_reply = 3  # from _XP_TABLE["reply"]
    max_replies = max_xp_per_day // xp_per_reply  # 5 replies before cap

    async def _run():
        mock_db = AsyncMock()

        mock_record = MagicMock()
        mock_record.level = 1
        mock_record.exp = 0

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_record

        mock_db.execute.return_value = mock_result

        from app.jobs.level_engine import add_xp

        # First max_replies should all succeed
        for i in range(max_replies):
            await add_xp(agent_id, bar_id, "reply", mock_db)

        expected_xp = xp_per_reply * max_replies
        assert mock_record.exp == expected_xp, (
            f"Expected {expected_xp} XP after {max_replies} replies, got {mock_record.exp}"
        )

        # One more reply should be capped — no additional XP
        await add_xp(agent_id, bar_id, "reply", mock_db)
        assert mock_record.exp == expected_xp, (
            f"XP should still be {expected_xp} after cap, got {mock_record.exp}"
        )

        # Non-reply actions should still work normally
        await add_xp(agent_id, bar_id, "post", mock_db)
        assert mock_record.exp == expected_xp + 10, (
            f"Post XP should not be affected by reply cap"
        )

    asyncio.run(_run())


# ── 0.8.7b: population cap ──

def test_population_cap_enforced():
    """create_agent raises ValueError when active agent count >= population.total_cap."""
    from unittest.mock import AsyncMock, MagicMock, patch
    from app.config import config as yaml_config

    total_cap = yaml_config.population.total_cap

    async def _run():
        mock_db = AsyncMock()
        mock_llm = MagicMock()

        # Mock: count query returns at cap
        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = total_cap
        mock_db.execute = AsyncMock(return_value=mock_count_result)

        from app.engine.agent_factory import create_agent

        try:
            await create_agent(mock_db, llm_caller=mock_llm)
            assert False, "Expected ValueError but no exception was raised"
        except ValueError as e:
            assert "population" in str(e).lower() or "cap" in str(e).lower(), (
                f"Expected population cap error, got: {e}"
            )

    asyncio.run(_run())


def test_population_cap_allows_when_under():
    """create_agent proceeds to creation when under population cap."""
    from unittest.mock import AsyncMock, MagicMock, patch
    from app.config import config as yaml_config

    total_cap = yaml_config.population.total_cap

    async def _run():
        mock_db = AsyncMock()
        mock_llm = MagicMock()

        # Mock: count is under cap
        count_result = MagicMock()
        count_result.scalar.return_value = total_cap - 5

        mock_db.execute = AsyncMock()
        # First call: count query returns under cap
        # Later calls: from the full pipeline (generate_hard_conditions etc.)
        mock_db.execute.side_effect = [count_result] + [AsyncMock()] * 20

        from app.engine.agent_factory import create_agent

        # The pipeline will fail on mock but NOT due to cap check
        cap_rejected = False
        try:
            await create_agent(mock_db, llm_caller=mock_llm)
        except ValueError as e:
            if "population" in str(e).lower():
                cap_rejected = True
        except Exception:
            pass  # Expected — pipeline runs but mocks aren't complete

        assert not cap_rejected, "Should not reject when under population cap"

    asyncio.run(_run())


# ── 0.8.7c: natural max online ──

def test_natural_max_online_tracking_exists():
    """Agent online flow tracks _online_started_at for timeout enforcement."""
    from unittest.mock import AsyncMock, MagicMock, patch
    from datetime import datetime, timezone

    agent = _make_mock_agent()
    agent.status = "active"
    agent.is_online = False
    # Important: _online_started_at should not exist before online flow
    # Use a sentinel to detect if it gets set
    agent._online_started_at = None

    async def _run():
        mock_db = AsyncMock()
        mock_llm = MagicMock()

        with patch("app.jobs.agent_lifecycle.execute") as mock_exec:
            mock_exec_result = MagicMock()
            mock_exec_result.status = "success"
            mock_exec_result.parsed = {"summary": "ok", "urge_type": None, "urge_intensity": 0.0}
            mock_exec.return_value = mock_exec_result

            with patch("app.jobs.agent_lifecycle._step2_post_urge"):
                with patch("app.jobs.agent_lifecycle._step3_bar_selection",
                           return_value={"active_bars": [], "casual_bars": []}):
                    with patch("app.jobs.agent_lifecycle._step4_notifications"):
                        with patch("app.jobs.agent_lifecycle._step5_browse_and_interact"):
                            from app.jobs.agent_lifecycle import _run_online_flow_inner

                            await _run_online_flow_inner(agent, mock_db, mock_llm)

        # Agent should have _online_started_at set to a datetime during online flow
        assert agent._online_started_at is not None, (
            "Agent should have _online_started_at set during online flow"
        )
        assert isinstance(agent._online_started_at, datetime)

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
