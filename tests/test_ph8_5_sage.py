"""0.8.5_sage TDD tests."""

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
