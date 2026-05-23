"""0.9.1_promise_consequences TDD tests — deadline check + broken promises + wiring."""

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


# ── 0.9.1a: Deadline Check DailyTask ──

def test_deadline_check_task_registered():
    """promise_deadline_check is registered in DailyTaskRegistry at correct time."""
    from app.engine.daily_tasks import daily_task_registry
    import app.jobs.scheduler  # triggers module-level registration

    task_names = [name for name, _, _, _ in daily_task_registry._tasks]
    assert "promise_deadline_check" in task_names, (
        f"Expected 'promise_deadline_check' in daily tasks, got {task_names}"
    )

    # Verify schedule timing
    for name, _, hour, minute in daily_task_registry._tasks:
        if name == "promise_deadline_check":
            assert hour == 8, f"Expected hour=8, got {hour}"
            assert minute == 0, f"Expected minute=0, got {minute}"


def test_deadline_check_marks_broken():
    """Deadline check task marks expired promises as 'broken'."""
    from unittest.mock import AsyncMock, patch

    async def _run():
        mock_db = AsyncMock()
        mock_llm = MagicMock()

        # Enable FeatureFlag
        from app.engine.feature_flags import plugin_registry
        plugin_registry.toggle("promises", True)

        # Mock pending promise with passed due_time
        from app.models.promise import Promise
        promise = Promise(
            requester_id=uuid.uuid4(),
            promiser_id=uuid.uuid4(),
            content="明天发攻略",
            due_time=datetime(2026, 5, 20, 10, 0, 0, tzinfo=timezone.utc),
            float_value=60.0,
            importance=0.7,
            status="pending",
        )

        # Mock db.execute to return the promise
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [promise]
        mock_db.execute = AsyncMock(return_value=mock_result)

        from app.jobs.scheduler import check_promise_deadlines_task
        await check_promise_deadlines_task(mock_db, mock_llm)

        # Promise should be marked broken
        assert promise.status == "broken", f"Expected status='broken', got '{promise.status}'"
        assert promise.fulfilled_at is not None
        assert mock_db.commit.call_count >= 1

        plugin_registry.toggle("promises", False)

    asyncio.run(_run())


def test_deadline_check_skips_when_disabled():
    """Deadline check task skips when FeatureFlag is disabled."""
    from unittest.mock import AsyncMock, patch

    async def _run():
        mock_db = AsyncMock()
        mock_llm = MagicMock()

        from app.engine.feature_flags import plugin_registry
        plugin_registry.toggle("promises", False)

        from app.jobs.scheduler import check_promise_deadlines_task
        await check_promise_deadlines_task(mock_db, mock_llm)

        # Should not query promises at all
        mock_db.execute.assert_not_called()

    asyncio.run(_run())


def test_deadline_check_skips_within_grace():
    """Deadline check skips promises still within float_value grace period."""
    from unittest.mock import AsyncMock, patch

    async def _run():
        mock_db = AsyncMock()
        mock_llm = MagicMock()

        from app.engine.feature_flags import plugin_registry
        plugin_registry.toggle("promises", True)

        from app.models.promise import Promise

        # Not yet past due_time + float_value
        promise = Promise(
            requester_id=uuid.uuid4(),
            promiser_id=uuid.uuid4(),
            content="测试承诺",
            due_time=datetime.now(timezone.utc) - timedelta(minutes=30),
            float_value=120.0,  # 2 hours grace
            importance=0.5,
            status="pending",
        )

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [promise]
        mock_db.execute = AsyncMock(return_value=mock_result)

        from app.jobs.scheduler import check_promise_deadlines_task
        await check_promise_deadlines_task(mock_db, mock_llm)

        # Should still be pending
        assert promise.status == "pending"

        plugin_registry.toggle("promises", False)

    asyncio.run(_run())


def test_deadline_check_exact_no_grace():
    """promise with float_value=None times out exactly at due_time."""
    from unittest.mock import AsyncMock, patch

    async def _run():
        mock_db = AsyncMock()
        mock_llm = MagicMock()

        from app.engine.feature_flags import plugin_registry
        plugin_registry.toggle("promises", True)

        from app.models.promise import Promise
        promise = Promise(
            requester_id=uuid.uuid4(),
            promiser_id=uuid.uuid4(),
            content="精确截止",
            due_time=datetime(2026, 5, 20, 10, 0, 0, tzinfo=timezone.utc),
            float_value=None,
            importance=0.5,
            status="pending",
        )

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [promise]
        mock_db.execute = AsyncMock(return_value=mock_result)

        from app.jobs.scheduler import check_promise_deadlines_task
        await check_promise_deadlines_task(mock_db, mock_llm)

        assert promise.status == "broken"

        plugin_registry.toggle("promises", False)

    asyncio.run(_run())


def test_deadline_check_updates_expectation():
    """Deadline check calls calculate_expectation and stores value on promise."""
    from unittest.mock import AsyncMock, patch

    async def _run():
        mock_db = AsyncMock()
        mock_llm = MagicMock()

        from app.engine.feature_flags import plugin_registry
        plugin_registry.toggle("promises", True)

        from app.models.promise import Promise
        promise = Promise(
            requester_id=uuid.uuid4(),
            promiser_id=uuid.uuid4(),
            content="测试期待值",
            due_time=datetime(2026, 6, 1, 10, 0, 0, tzinfo=timezone.utc),
            importance=0.8,
            status="pending",
        )
        requester = _make_mock_agent("需求方")
        promiser = _make_mock_agent("承诺方")

        # side_effect: 1st call → [promise], 2nd → requester, 3rd → promiser
        call_count = 0

        async def _mock_execute(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalars.return_value.all.return_value = [promise]
            elif call_count == 2:
                result.scalar_one_or_none.return_value = requester
            elif call_count == 3:
                result.scalar_one_or_none.return_value = promiser
            return result

        mock_db.execute = _mock_execute

        with patch("app.engine.promise_engine.calculate_expectation", new_callable=AsyncMock) as mock_calc:
            mock_calc.return_value = 75.5

            from app.jobs.scheduler import check_promise_deadlines_task
            await check_promise_deadlines_task(mock_db, mock_llm)

            # Expectation should be set
            assert promise.expectation == 75.5, (
                f"Expected expectation=75.5, got {promise.expectation}"
            )
            # Still pending (not broken — due_time is in the future)
            assert promise.status == "pending"
            mock_calc.assert_called_once()

        plugin_registry.toggle("promises", False)

    asyncio.run(_run())


# ── 0.9.1b: Broken Promise Penalty ──

def test_adjust_after_promise_broken_exists():
    """adjust_after_promise_broken function exists in social_engine."""
    from app.jobs.social_engine import adjust_after_promise_broken
    assert callable(adjust_after_promise_broken)


def test_adjust_after_promise_broken_adds_distrust_tag():
    """adjust_after_promise_broken appends distrust_tag to promiser."""
    from unittest.mock import AsyncMock, patch

    requester = _make_mock_agent("需求方A")
    promiser = _make_mock_agent("承诺方B")
    promise_content = "明天发观鸟攻略"

    async def _run():
        mock_db = AsyncMock()

        # Mock _ensure_relationship
        mock_rel = MagicMock()
        mock_rel.intimacy = 0.5
        mock_rel.attitude = "neutral"

        with patch("app.jobs.social_engine._ensure_relationship", return_value=mock_rel):
            # Mock agent query for distrust_tags update
            mock_agent_result = MagicMock()
            mock_agent_result.scalar_one_or_none.return_value = promiser
            mock_db.execute = AsyncMock(return_value=mock_agent_result)

            from app.jobs.social_engine import adjust_after_promise_broken
            result = await adjust_after_promise_broken(
                requester.id, promiser.id, promise_content, mock_db
            )

            assert result is not None
            # Intimacy should be reduced
            assert mock_rel.intimacy < 0.5, f"Expected intimacy reduction, got {mock_rel.intimacy}"
            # distrust_tag should be added
            assert len(promiser.distrust_tags) == 1
            assert promiser.distrust_tags[0]["reason"] == promise_content
            assert "expires_at" in promiser.distrust_tags[0]
            assert "created_at" in promiser.distrust_tags[0]

    asyncio.run(_run())


def test_adjust_after_promise_broken_self_guard():
    """adjust_after_promise_broken returns None when requester == promiser."""
    from unittest.mock import AsyncMock

    agent = _make_mock_agent()

    async def _run():
        mock_db = AsyncMock()
        from app.jobs.social_engine import adjust_after_promise_broken
        result = await adjust_after_promise_broken(agent.id, agent.id, "测试", mock_db)
        assert result is None

    asyncio.run(_run())


def test_adjust_after_promise_fulfilled_exists():
    """adjust_after_promise_fulfilled function exists."""
    from app.jobs.social_engine import adjust_after_promise_fulfilled
    assert callable(adjust_after_promise_fulfilled)


def test_broken_promise_notification_created():
    """Notification is created when promise is broken."""
    from unittest.mock import AsyncMock, patch

    async def _run():
        mock_db = AsyncMock()
        mock_llm = MagicMock()

        from app.engine.feature_flags import plugin_registry
        plugin_registry.toggle("promises", True)

        from app.models.promise import Promise
        promise = Promise(
            requester_id=uuid.uuid4(),
            promiser_id=uuid.uuid4(),
            content="过期承诺",
            due_time=datetime(2026, 5, 20, 10, 0, 0, tzinfo=timezone.utc),
            float_value=None,
            importance=0.5,
            status="pending",
        )

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [promise]
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch("app.jobs.social_engine.adjust_after_promise_broken"):
            from app.jobs.scheduler import check_promise_deadlines_task
            await check_promise_deadlines_task(mock_db, mock_llm)

        # Check that notification was created (db.add called with Notification)
        assert mock_db.add.call_count >= 1

        plugin_registry.toggle("promises", False)

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
