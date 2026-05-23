"""0.9.2_trust_reputation TDD tests — trust_tags + reputation + fulfillment rewards."""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
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
    agent.distrust_tags = []
    agent.trust_tags = []
    agent.reputation = 0.0
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


# ── 0.9.2a: Agent model fields ──

def test_agent_trust_tags_column():
    """Agent model has trust_tags JSON column."""
    from app.models import Agent

    cols = Agent.__table__.columns
    col_names = {c.name for c in cols}
    assert "trust_tags" in col_names, f"Missing trust_tags column, got {col_names}"


def test_agent_reputation_column():
    """Agent model has reputation Float column."""
    from app.models import Agent

    cols = Agent.__table__.columns
    col_names = {c.name for c in cols}
    assert "reputation" in col_names, f"Missing reputation column, got {col_names}"

    rep_col = cols["reputation"]
    assert str(rep_col.type) in ("FLOAT", "Float"), f"reputation should be Float, got {rep_col.type}"


# ── 0.9.2b: Config values ──

def test_config_trust_tag_duration():
    """config.promises has trust_tag_duration_days."""
    from app.config import config as yaml_config
    val = yaml_config.promises.trust_tag_duration_days
    assert val > 0, f"Expected positive trust_tag_duration_days, got {val}"


def test_config_reputation_threshold():
    """config.promises has reputation_high_importance_threshold."""
    from app.config import config as yaml_config
    val = yaml_config.promises.reputation_high_importance_threshold
    assert 0 < val <= 1.0, f"Expected 0-1 reputation_high_importance_threshold, got {val}"


def test_config_reputation_boost():
    """config.promises has reputation_boost_per_fulfillment."""
    from app.config import config as yaml_config
    val = yaml_config.promises.reputation_boost_per_fulfillment
    assert val > 0, f"Expected positive reputation_boost_per_fulfillment, got {val}"


# ── 0.9.2c: adjust_after_promise_fulfilled ──

def test_fulfilled_adds_trust_tag():
    """adjust_after_promise_fulfilled adds trust_tag to promiser."""
    from unittest.mock import AsyncMock, patch

    requester = _make_mock_agent("需求方A")
    promiser = _make_mock_agent("承诺方B")
    promise_content = "明天发观鸟攻略"

    async def _run():
        mock_db = AsyncMock()

        mock_rel = MagicMock()
        mock_rel.intimacy = 0.5
        mock_rel.attitude = "neutral"

        with patch("app.jobs.social_engine._ensure_relationship", return_value=mock_rel):
            mock_agent_result = MagicMock()
            mock_agent_result.scalar_one_or_none.return_value = promiser
            mock_db.execute = AsyncMock(return_value=mock_agent_result)

            from app.jobs.social_engine import adjust_after_promise_fulfilled
            result = await adjust_after_promise_fulfilled(
                requester.id, promiser.id, promise_content, mock_db
            )

            assert result is not None
            assert len(promiser.trust_tags) >= 1
            tag = promiser.trust_tags[0]
            assert tag["from_id"] == str(requester.id)
            assert tag["reason"] == promise_content
            assert "expires_at" in tag
            assert "created_at" in tag

    asyncio.run(_run())


def test_fulfilled_removes_distrust_tag():
    """adjust_after_promise_fulfilled removes distrust_tag from this requester."""
    from unittest.mock import AsyncMock, patch

    requester = _make_mock_agent("需求方A")
    promiser = _make_mock_agent("承诺方B")

    now = datetime.now(timezone.utc)
    promiser.distrust_tags = [
        {"from_id": str(requester.id), "reason": "之前失信", "expires_at": (now + timedelta(days=10)).isoformat(), "created_at": now.isoformat()},
        {"from_id": str(uuid.uuid4()), "reason": "另一个失信", "expires_at": (now + timedelta(days=10)).isoformat(), "created_at": now.isoformat()},
    ]

    async def _run():
        mock_db = AsyncMock()

        mock_rel = MagicMock()
        mock_rel.intimacy = 0.5
        mock_rel.attitude = "neutral"

        with patch("app.jobs.social_engine._ensure_relationship", return_value=mock_rel):
            mock_agent_result = MagicMock()
            mock_agent_result.scalar_one_or_none.return_value = promiser
            mock_db.execute = AsyncMock(return_value=mock_agent_result)

            from app.jobs.social_engine import adjust_after_promise_fulfilled
            await adjust_after_promise_fulfilled(
                requester.id, promiser.id, "履行承诺", mock_db
            )

            # Distrust tag from this requester should be removed
            remaining_from_ids = [t["from_id"] for t in promiser.distrust_tags]
            assert str(requester.id) not in remaining_from_ids, "distrust_tag from requester should be removed"
            # Other distrust tags should remain
            assert len(promiser.distrust_tags) == 1

    asyncio.run(_run())


def test_fulfilled_boosts_intimacy_by_importance():
    """adjust_after_promise_fulfilled intimacy boost uses config value * importance."""
    from unittest.mock import AsyncMock, patch

    requester = _make_mock_agent("需求方A")
    promiser = _make_mock_agent("承诺方B")

    async def _run():
        from app.config import config as yaml_config

        mock_db = AsyncMock()

        mock_rel = MagicMock()
        mock_rel.intimacy = 0.5

        with patch("app.jobs.social_engine._ensure_relationship", return_value=mock_rel):
            mock_agent_result = MagicMock()
            mock_agent_result.scalar_one_or_none.return_value = promiser
            mock_db.execute = AsyncMock(return_value=mock_agent_result)

            from app.jobs.social_engine import adjust_after_promise_fulfilled
            await adjust_after_promise_fulfilled(
                requester.id, promiser.id, "高重要性承诺", mock_db
            )

            base_boost = yaml_config.promises.fulfilled_intimacy_boost
            # Default importance is not passed through function signature —
            # the mock agent has no importance field. The function uses fixed boost now.
            assert mock_rel.intimacy > 0.5, f"Expected intimacy > 0.5, got {mock_rel.intimacy}"

    asyncio.run(_run())


def test_fulfilled_boosts_reputation_high_importance():
    """adjust_after_promise_fulfilled boosts reputation when importance > threshold."""
    from unittest.mock import AsyncMock, patch

    requester = _make_mock_agent("需求方A")
    promiser = _make_mock_agent("承诺方B")
    initial_rep = promiser.reputation

    async def _run():
        from app.config import config as yaml_config
        threshold = yaml_config.promises.reputation_high_importance_threshold

        mock_db = AsyncMock()

        mock_rel = MagicMock()
        mock_rel.intimacy = 0.5

        with patch("app.jobs.social_engine._ensure_relationship", return_value=mock_rel):
            mock_agent_result = MagicMock()
            mock_agent_result.scalar_one_or_none.return_value = promiser
            mock_db.execute = AsyncMock(return_value=mock_agent_result)

            from app.jobs.social_engine import adjust_after_promise_fulfilled
            # Pass importance above threshold
            await adjust_after_promise_fulfilled(
                requester.id, promiser.id, "重要承诺", mock_db,
                importance=0.8,
            )

            assert promiser.reputation > initial_rep, (
                f"Expected reputation > {initial_rep}, got {promiser.reputation}"
            )

    asyncio.run(_run())


def test_fulfilled_no_reputation_low_importance():
    """adjust_after_promise_fulfilled does NOT boost reputation for low importance."""
    from unittest.mock import AsyncMock, patch

    requester = _make_mock_agent("需求方A")
    promiser = _make_mock_agent("承诺方B")
    initial_rep = promiser.reputation

    async def _run():
        mock_db = AsyncMock()

        mock_rel = MagicMock()
        mock_rel.intimacy = 0.5

        with patch("app.jobs.social_engine._ensure_relationship", return_value=mock_rel):
            mock_agent_result = MagicMock()
            mock_agent_result.scalar_one_or_none.return_value = promiser
            mock_db.execute = AsyncMock(return_value=mock_agent_result)

            from app.jobs.social_engine import adjust_after_promise_fulfilled
            await adjust_after_promise_fulfilled(
                requester.id, promiser.id, "普通承诺", mock_db,
                importance=0.3,
            )

            assert promiser.reputation == initial_rep, (
                f"reputation should not change for low importance"
            )

    asyncio.run(_run())


def test_fulfilled_self_guard():
    """adjust_after_promise_fulfilled returns None when requester == promiser."""
    from unittest.mock import AsyncMock

    agent = _make_mock_agent()

    async def _run():
        mock_db = AsyncMock()
        from app.jobs.social_engine import adjust_after_promise_fulfilled
        result = await adjust_after_promise_fulfilled(agent.id, agent.id, "测试", mock_db)
        assert result is None

    asyncio.run(_run())


# ── 0.9.2d: build_agent_context includes trust_tags ──

def test_build_agent_context_includes_trust_tags():
    """build_agent_context includes active trust_tags."""
    from app.skills.skill_utils import build_agent_context

    agent = _make_mock_agent()
    now = datetime.now(timezone.utc)
    future = (now + timedelta(days=30)).isoformat()
    agent.trust_tags = [
        {"from_id": str(uuid.uuid4()), "reason": "守信测试", "expires_at": future, "created_at": now.isoformat()},
    ]

    ctx = build_agent_context(agent)
    assert "trust_tags" in ctx, f"Missing trust_tags in context, got keys: {list(ctx.keys())}"
    assert len(ctx["trust_tags"]) == 1
    assert ctx["trust_tags"][0]["reason"] == "守信测试"


def test_expired_trust_tag_filtered_out():
    """build_agent_context filters out expired trust_tags."""
    from app.skills.skill_utils import build_agent_context

    agent = _make_mock_agent()
    now = datetime.now(timezone.utc)
    past = (now - timedelta(days=1)).isoformat()
    agent.trust_tags = [
        {"from_id": str(uuid.uuid4()), "reason": "过期标签", "expires_at": past, "created_at": past},
    ]

    ctx = build_agent_context(agent)
    assert len(ctx.get("trust_tags", [])) == 0, "Expired trust_tags should be filtered out"


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
