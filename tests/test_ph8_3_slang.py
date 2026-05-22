"""0.8.3_slang TDD tests."""

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
