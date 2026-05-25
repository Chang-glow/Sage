"""0.9.0_promise TDD tests — Promise model + detection + expectation engine + FeatureFlag."""

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


# ── 0.9.0a: Promise Model ──

def test_promise_model_creation():
    """Promise model exists with correct fields and constraints."""
    from app.models import Promise

    assert hasattr(Promise, "__tablename__")
    assert Promise.__tablename__ == "promises"

    # Check key columns
    cols = Promise.__table__.columns
    col_names = {c.name for c in cols}
    expected = {"id", "requester_id", "promiser_id", "content", "due_time",
                "float_value", "importance", "status", "created_at",
                "fulfilled_at", "source_reply_id", "expectation"}
    for name in expected:
        assert name in col_names, f"Missing column: {name}"

    # Check unique constraint
    uq_names = set()
    for c in Promise.__table__.constraints:
        if hasattr(c, "columns"):
            uq_names.update(col.name for col in c.columns)
    assert "requester_id" in uq_names or any(
        "requester_id" in str(c) for c in Promise.__table__.constraints
    ), "Expected UniqueConstraint on requester_id"


def test_promise_unique_constraint_fields():
    """UniqueConstraint covers (requester_id, promiser_id, source_reply_id)."""
    from app.models import Promise
    from sqlalchemy import UniqueConstraint

    has_uq = False
    for c in Promise.__table__.constraints:
        if isinstance(c, UniqueConstraint):
            col_names = {col.name for col in c.columns}
            if "requester_id" in col_names and "promiser_id" in col_names and "source_reply_id" in col_names:
                has_uq = True
                break
    assert has_uq, "Missing UniqueConstraint on (requester_id, promiser_id, source_reply_id)"


# ── 0.9.0b: distrust_tags on Agent ──

def test_agent_distrust_tags_column():
    """Agent model has distrust_tags JSON column."""
    from app.models import Agent

    cols = Agent.__table__.columns
    col_names = {c.name for c in cols}
    assert "distrust_tags" in col_names, f"Missing distrust_tags column, got {col_names}"


# ── 0.9.0c: FeatureFlag Registration ──

def test_feature_flag_registered():
    """'promises' FeatureFlag is registered in PluginRegistry."""
    from app.engine.feature_flags import plugin_registry

    features = plugin_registry.list_all()
    names = [f["name"] for f in features]
    assert "promises" in names, f"Expected 'promises' in feature flags, got {names}"

    # Default should be False (disabled)
    assert plugin_registry.is_enabled("promises") is False


# ── 0.9.0d: Promise Detection BrowseHook ──

def test_promise_detection_hook_registered():
    """_promise_detection_hook is registered in BrowseHookRegistry at priority=85."""
    from app.engine.browse_hooks import browse_hook_registry
    import app.jobs.agent_lifecycle  # triggers module-level registration

    names = [name for name, _, _ in browse_hook_registry._hooks]
    assert "promise_detect" in names, f"Expected 'promise_detect' in hooks, got {names}"

    for name, _, priority in browse_hook_registry._hooks:
        if name == "promise_detect":
            assert priority == 85, f"Expected priority=85, got {priority}"


def test_promise_detection_creates_record():
    """Promise detection hook creates Promise record when LLM detects a promise."""
    from unittest.mock import AsyncMock, patch

    agent = _make_mock_agent()
    post = _make_mock_post()
    reply_result = {"content": "我明天一定帮你查一下那个攻略"}

    # Enable the feature flag for this test
    from app.engine.feature_flags import plugin_registry
    plugin_registry.toggle("promises", True)

    async def _run():
        mock_db = AsyncMock()
        mock_llm = MagicMock()

        # Mock active promise count query to return 0
        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 0
        mock_db.execute = AsyncMock()
        mock_db.execute.return_value = mock_count_result

        with patch("app.jobs.agent_lifecycle.execute") as mock_exec:
            mock_exec_result = MagicMock()
            mock_exec_result.status = "success"
            mock_exec_result.parsed = {
                "detected": True,
                "content": "明天帮查攻略",
                "due_time_estimate": "明天",
                "float_minutes": 120,
                "importance": 0.7,
                "reason": "明确时间承诺",
            }
            mock_exec.return_value = mock_exec_result

            with patch("app.jobs.agent_lifecycle.build_agent_context",
                       return_value={"agent_name": "测试Agent"}):
                with patch("app.jobs.agent_lifecycle.build_post_context",
                           return_value={"post_title": "测试帖子", "post_content": "内容",
                                         "post_author_id": str(post.author_id)}):
                    with patch("app.engine.promise_engine._parse_due_time",
                               return_value=datetime(2026, 5, 23, 12, 0, 0, tzinfo=timezone.utc)):
                        with patch("app.jobs.agent_lifecycle._count_active_promises",
                                   return_value=0):
                            with patch("app.jobs.agent_lifecycle.build_relationship_context",
                                       return_value={"relationship_intimacy": 0.3}):
                                from app.jobs.agent_lifecycle import _promise_detection_hook
                                await _promise_detection_hook(agent, post, MagicMock(),
                                                              reply_result, mock_db, mock_llm)

            # execute("promise_detection") was called
            mock_exec.assert_called_once()
            call_args = mock_exec.call_args
            assert call_args[0][0] == "promise_detection"

            # Promise was created
            assert mock_db.add.call_count >= 1
            assert mock_db.commit.call_count >= 1

    asyncio.run(_run())
    plugin_registry.toggle("promises", False)  # reset


def test_promise_detection_skips_when_disabled():
    """Promise detection hook skips when FeatureFlag is disabled."""
    from unittest.mock import AsyncMock, patch

    agent = _make_mock_agent()
    post = _make_mock_post()
    reply_result = {"content": "我答应你"}

    from app.engine.feature_flags import plugin_registry
    # Ensure disabled
    plugin_registry.toggle("promises", False)

    async def _run():
        mock_db = AsyncMock()
        mock_llm = MagicMock()

        with patch("app.jobs.agent_lifecycle.execute") as mock_exec:
            from app.jobs.agent_lifecycle import _promise_detection_hook
            await _promise_detection_hook(agent, post, MagicMock(), reply_result, mock_db, mock_llm)

            mock_exec.assert_not_called()

    asyncio.run(_run())


def test_promise_detection_skips_no_reply():
    """Promise detection hook skips when reply_result is None."""
    from unittest.mock import AsyncMock, patch

    agent = _make_mock_agent()
    post = _make_mock_post()

    from app.engine.feature_flags import plugin_registry
    plugin_registry.toggle("promises", True)

    async def _run():
        mock_db = AsyncMock()
        mock_llm = MagicMock()

        with patch("app.jobs.agent_lifecycle.execute") as mock_exec:
            from app.jobs.agent_lifecycle import _promise_detection_hook
            await _promise_detection_hook(agent, post, MagicMock(), None, mock_db, mock_llm)

            mock_exec.assert_not_called()

    asyncio.run(_run())
    plugin_registry.toggle("promises", False)


def test_promise_detection_respects_max_active():
    """Promise detection hook skips when agent has max_active_promises_per_agent."""
    from unittest.mock import AsyncMock, patch
    from app.config import config as yaml_config

    agent = _make_mock_agent()
    post = _make_mock_post()
    reply_result = {"content": "我再答应你一件事"}

    from app.engine.feature_flags import plugin_registry
    plugin_registry.toggle("promises", True)

    max_active = yaml_config.promises.max_active_promises_per_agent

    async def _run():
        mock_db = AsyncMock()
        mock_llm = MagicMock()

        with patch("app.jobs.agent_lifecycle.execute") as mock_exec:
            with patch("app.jobs.agent_lifecycle._count_active_promises",
                       return_value=max_active):
                from app.jobs.agent_lifecycle import _promise_detection_hook
                await _promise_detection_hook(agent, post, MagicMock(), reply_result, mock_db, mock_llm)

                mock_exec.assert_not_called()

    asyncio.run(_run())
    plugin_registry.toggle("promises", False)


# ── 0.9.0e: _parse_due_time ──

def test_parse_due_time_relative():
    """_parse_due_time handles '3天后' correctly."""
    from app.engine.promise_engine import _parse_due_time

    now = datetime(2026, 5, 22, 10, 0, 0, tzinfo=timezone.utc)
    result = _parse_due_time("3天后", now)
    assert result is not None
    assert result.date() == (now + timedelta(days=3)).date()


def test_parse_due_time_tomorrow():
    """_parse_due_time handles '明天' correctly."""
    from app.engine.promise_engine import _parse_due_time

    now = datetime(2026, 5, 22, 10, 0, 0, tzinfo=timezone.utc)
    result = _parse_due_time("明天", now)
    assert result is not None
    assert result.date() == (now + timedelta(days=1)).date()


def test_parse_due_time_next_week():
    """_parse_due_time handles '下周' as +7 days."""
    from app.engine.promise_engine import _parse_due_time

    now = datetime(2026, 5, 22, 10, 0, 0, tzinfo=timezone.utc)
    result = _parse_due_time("下周", now)
    assert result is not None
    assert result.date() == (now + timedelta(days=7)).date()


def test_parse_due_time_vague_fallback():
    """_parse_due_time returns None for unparseable input."""
    from app.engine.promise_engine import _parse_due_time

    now = datetime(2026, 5, 22, 10, 0, 0, tzinfo=timezone.utc)
    result = _parse_due_time("有空就做", now)
    assert result is None

    result2 = _parse_due_time("", now)
    assert result2 is None


# ── 0.9.0f: Expectation Engine ──

def test_expectation_calculation_returns_0_to_100():
    """calculate_expectation returns value in 0-100 range."""
    from unittest.mock import AsyncMock, patch
    from app.engine.promise_engine import calculate_expectation

    async def _run():
        mock_llm = MagicMock()

        # Build a mock promise
        promise = MagicMock()
        promise.due_time = datetime(2026, 5, 23, 10, 0, 0, tzinfo=timezone.utc)
        promise.importance = 0.5
        promise.created_at = datetime(2026, 5, 22, 10, 0, 0, tzinfo=timezone.utc)

        requester = _make_mock_agent()
        promiser = _make_mock_agent("承诺者")

        with patch("app.skills.executor.execute") as mock_exec:
            mock_result = MagicMock()
            mock_result.status = "success"
            mock_result.parsed = {"expectation": 45.0, "reason": "中等重要，截止还有时间"}
            mock_exec.return_value = mock_result

            result = await calculate_expectation(promise, requester, promiser, mock_llm)
            assert 0 <= result <= 100, f"Expected 0-100, got {result}"

    asyncio.run(_run())


def test_expectation_grows_nearer_deadline():
    """calculate_expectation returns higher value when deadline is closer."""
    from unittest.mock import MagicMock, patch
    from app.engine.promise_engine import calculate_expectation

    async def _run():
        mock_llm = MagicMock()

        requester = _make_mock_agent()
        promiser = _make_mock_agent("承诺者")

        # Far deadline
        promise_far = MagicMock()
        promise_far.due_time = datetime(2026, 6, 22, 10, 0, 0, tzinfo=timezone.utc)
        promise_far.importance = 0.7
        promise_far.created_at = datetime(2026, 5, 22, 10, 0, 0, tzinfo=timezone.utc)

        # Near deadline
        promise_near = MagicMock()
        promise_near.due_time = datetime(2026, 5, 23, 10, 0, 0, tzinfo=timezone.utc)
        promise_near.importance = 0.7
        promise_near.created_at = datetime(2026, 5, 22, 10, 0, 0, tzinfo=timezone.utc)

        call_results = iter([85.0, 25.0])

        with patch("app.skills.executor.execute") as mock_exec:
            def side_effect(*args, **kwargs):
                result = MagicMock()
                result.status = "success"
                val = next(call_results)
                result.parsed = {"expectation": val, "reason": "test"}
                return result

            mock_exec.side_effect = side_effect

            near = await calculate_expectation(promise_near, requester, promiser, mock_llm)
            far = await calculate_expectation(promise_far, requester, promiser, mock_llm)

            assert near > far, f"Near ({near}) should be > far ({far})"

    asyncio.run(_run())


def test_expectation_null_due_time():
    """calculate_expectation handles NULL due_time gracefully."""
    from unittest.mock import MagicMock, patch
    from app.engine.promise_engine import calculate_expectation

    async def _run():
        mock_llm = MagicMock()

        promise = MagicMock()
        promise.due_time = None
        promise.importance = 0.3
        promise.created_at = datetime(2026, 5, 22, 10, 0, 0, tzinfo=timezone.utc)

        requester = _make_mock_agent()
        promiser = _make_mock_agent("承诺者")

        with patch("app.skills.executor.execute") as mock_exec:
            mock_result = MagicMock()
            mock_result.status = "success"
            mock_result.parsed = {"expectation": 10.0, "reason": "无截止时间，基础期待"}
            mock_exec.return_value = mock_result

            result = await calculate_expectation(promise, requester, promiser, mock_llm)
            assert 0 <= result <= 100

    asyncio.run(_run())


def test_check_promise_status_timeout():
    """check_promise_status returns 'broken' when past due_time + float_value."""
    from app.engine.promise_engine import check_promise_status

    promise = MagicMock()
    promise.due_time = datetime(2026, 5, 20, 10, 0, 0, tzinfo=timezone.utc)
    promise.float_value = 60.0  # 60 minutes grace
    promise.status = "pending"

    result = check_promise_status(promise)
    assert result == "broken", f"Expected 'broken', got {result}"


def test_check_promise_status_within_grace():
    """check_promise_status returns None when within float_value grace period."""
    from app.engine.promise_engine import check_promise_status

    promise = MagicMock()
    # Due 30 minutes ago but 120 min grace
    promise.due_time = datetime.now(timezone.utc) - timedelta(minutes=30)
    promise.float_value = 120.0
    promise.status = "pending"

    result = check_promise_status(promise)
    assert result is None, f"Expected None (within grace), got {result}"


def test_check_promise_status_no_grace_expired():
    """check_promise_status returns 'broken' when past due_time with no float_value."""
    from app.engine.promise_engine import check_promise_status

    promise = MagicMock()
    promise.due_time = datetime(2026, 5, 20, 10, 0, 0, tzinfo=timezone.utc)
    promise.float_value = None
    promise.status = "pending"

    result = check_promise_status(promise)
    assert result == "broken"


def test_check_promise_status_null_due():
    """check_promise_status returns None for NULL due_time (never times out)."""
    from app.engine.promise_engine import check_promise_status

    promise = MagicMock()
    promise.due_time = None
    promise.float_value = None
    promise.status = "pending"

    result = check_promise_status(promise)
    assert result is None, f"NULL due_time should never time out, got {result}"


# ── 0.9.0g: distrust_tags in build_agent_context ──

def test_build_agent_context_includes_distrust_tags():
    """build_agent_context includes active distrust_tags."""
    from app.skills.skill_utils import build_agent_context

    agent = _make_mock_agent()
    now = datetime.now(timezone.utc)
    future = (now + timedelta(days=30)).isoformat()
    agent.distrust_tags = [
        {"from_id": str(uuid.uuid4()), "reason": "失信测试", "expires_at": future, "created_at": now.isoformat()},
    ]

    ctx = build_agent_context(agent)
    assert "distrust_tags" in ctx, f"Missing distrust_tags in context, got keys: {list(ctx.keys())}"
    assert len(ctx["distrust_tags"]) == 1
    assert ctx["distrust_tags"][0]["reason"] == "失信测试"


def test_expired_distrust_tag_filtered_out():
    """build_agent_context filters out expired distrust_tags."""
    from app.skills.skill_utils import build_agent_context

    agent = _make_mock_agent()
    now = datetime.now(timezone.utc)
    past = (now - timedelta(days=1)).isoformat()
    agent.distrust_tags = [
        {"from_id": str(uuid.uuid4()), "reason": "过期标签", "expires_at": past, "created_at": past},
    ]

    ctx = build_agent_context(agent)
    assert len(ctx.get("distrust_tags", [])) == 0, "Expired tags should be filtered out"


# ── 0.12.11b: Expectation auto-reset ──

def test_expectation_reset_2x_overdue():
    """check_promise_deadlines_task sets expectation=0 when > 2x due_time overdue."""
    from unittest.mock import AsyncMock, MagicMock, patch
    import uuid as _uuid

    now = datetime.now(timezone.utc)
    # Promise was for 3 days, created 10 days ago, due 7 days ago = 3 days past 2x window
    created = now - timedelta(days=10)
    deadline = now - timedelta(days=7)

    mock_promise = MagicMock()
    mock_promise.id = _uuid.uuid4()
    mock_promise.requester_id = _uuid.uuid4()
    mock_promise.promiser_id = _uuid.uuid4()
    mock_promise.content = "test"
    mock_promise.status = "pending"
    mock_promise.due_time = deadline
    mock_promise.created_at = created
    mock_promise.float_value = 10080.0  # 7 days grace — not broken
    mock_promise.expectation = 50.0
    mock_promise.importance = 0.5

    async def _run():
        mock_db = AsyncMock()
        mock_llm = AsyncMock()

        mock_agent = _make_mock_agent()
        mock_agent_result = MagicMock()
        mock_agent_result.scalar_one_or_none.return_value = mock_agent

        mock_promise_result = MagicMock()
        mock_promise_result.scalars.return_value.all.return_value = [mock_promise]

        mock_db.execute = AsyncMock(side_effect=[mock_promise_result, mock_agent_result, mock_agent_result])

        with patch("app.engine.feature_flags.plugin_registry") as mock_registry, \
             patch("app.engine.promise_engine.calculate_expectation", return_value=60.0):
            mock_registry.is_enabled.return_value = True
            from app.jobs.scheduler import check_promise_deadlines_task
            await check_promise_deadlines_task(mock_db, mock_llm)

        assert mock_promise.expectation == 0.0, \
            f"Expected 0.0, got {mock_promise.expectation}"

    asyncio.run(_run())


def test_expectation_not_reset_within_2x_window():
    """check_promise_deadlines_task does NOT reset expectation when within 2x window."""
    from unittest.mock import AsyncMock, MagicMock, patch
    import uuid as _uuid

    now = datetime.now(timezone.utc)
    # Promise for 2 days, created 3 days ago, due 1 day ago = still within 2x
    created = now - timedelta(days=3)
    deadline = now - timedelta(days=1)

    mock_promise = MagicMock()
    mock_promise.id = _uuid.uuid4()
    mock_promise.requester_id = _uuid.uuid4()
    mock_promise.promiser_id = _uuid.uuid4()
    mock_promise.content = "test"
    mock_promise.status = "pending"
    mock_promise.due_time = deadline
    mock_promise.created_at = created
    mock_promise.float_value = 2880.0  # 2 days grace
    mock_promise.expectation = 50.0
    mock_promise.importance = 0.5

    async def _run():
        mock_db = AsyncMock()
        mock_llm = AsyncMock()

        mock_agent = _make_mock_agent()
        mock_agent_result = MagicMock()
        mock_agent_result.scalar_one_or_none.return_value = mock_agent

        mock_promise_result = MagicMock()
        mock_promise_result.scalars.return_value.all.return_value = [mock_promise]

        mock_db.execute = AsyncMock(side_effect=[mock_promise_result, mock_agent_result, mock_agent_result])

        with patch("app.engine.feature_flags.plugin_registry") as mock_registry, \
             patch("app.engine.promise_engine.calculate_expectation", return_value=50.0):
            mock_registry.is_enabled.return_value = True
            from app.jobs.scheduler import check_promise_deadlines_task
            await check_promise_deadlines_task(mock_db, mock_llm)

        # Recalculated to 50.0, reset check doesn't trigger (within 2x window)
        assert mock_promise.expectation == 50.0, \
            f"Expected 50.0, got {mock_promise.expectation}"

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
