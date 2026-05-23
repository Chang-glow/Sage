"""0.8.7_config TDD tests."""

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

                            # v0.12.8 checkin query between step3 and step4 needs
                            # explicit return chain: scalars().all() -> []
                            mock_db.execute = AsyncMock()
                            mock_db.execute.return_value = MagicMock()
                            mock_db.execute.return_value.scalars.return_value.all.return_value = []

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
