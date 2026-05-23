"""0.10.0_conflict TDD tests — conflict detection + guilt + reflection + action execution."""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch


def _make_mock_agent(name="测试Agent", pv=None):
    """Helper to create a minimal mock agent."""
    import uuid as _uuid
    agent = MagicMock()
    agent.id = _uuid.uuid4()
    agent.nickname = name
    agent.personality_vector = pv or {"开放": 0.7, "外向": 0.5, "truthseeker": 0.3, "peacemaker": 0.4}
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
    post.reply_count = 10
    post.is_hidden = False
    author = MagicMock()
    author.nickname = author_name
    author.id = post.author_id
    post.author = author
    bar = MagicMock()
    bar.name = "测试吧"
    post.bar = bar
    return post


# ── 0.10.0a: Conflict Engine — rationality calculation ──

def test_calc_rationality():
    """calculate_rationality returns weighted sum from personality_vector."""
    from app.engine.conflict_engine import calculate_rationality

    pv = {"truthseeker": 0.8, "peacemaker": 0.5}
    result = calculate_rationality(pv)
    expected = 0.8 * 0.6 + 0.5 * 0.4
    assert abs(result - expected) < 0.001, f"Expected ~{expected}, got {result}"


def test_calc_rationality_missing_keys():
    """calculate_rationality returns 0 for missing personality keys."""
    from app.engine.conflict_engine import calculate_rationality

    result = calculate_rationality({"开放": 0.7})
    assert result == 0.0, f"Expected 0.0 for missing keys, got {result}"


def test_calc_rationality_none():
    """calculate_rationality returns 0 for None input."""
    from app.engine.conflict_engine import calculate_rationality

    assert calculate_rationality(None) == 0.0
    assert calculate_rationality({}) == 0.0


# ── 0.10.0b: Conflict detection — reply count ──

def test_detect_conflict_mutual_replies():
    """_count_mutual_replies returns count of back-and-forth between two agents on a post."""
    from app.engine.conflict_engine import _count_mutual_replies

    a1 = uuid.uuid4()
    a2 = uuid.uuid4()
    post_id = uuid.uuid4()

    # Build replies: a1, a2, a1, a2, a1, a2, a1 = 6 rounds (a1 starts, a2 follows, etc.)
    replies = []
    for i in range(7):
        r = MagicMock()
        r.author_id = a1 if i % 2 == 0 else a2
        r.post_id = post_id
        r.content = f"reply {i}"
        replies.append(r)

    count = _count_mutual_replies(a1, a2, replies)
    assert count >= 6, f"Expected >= 6 mutual replies, got {count}"


def test_detect_conflict_no_conflict():
    """_count_mutual_replies returns 0 when no back-and-forth."""
    from app.engine.conflict_engine import _count_mutual_replies

    a1 = uuid.uuid4()
    a2 = uuid.uuid4()
    post_id = uuid.uuid4()

    replies = []
    for i in range(3):
        r = MagicMock()
        r.author_id = a1  # all same author
        r.post_id = post_id
        r.content = f"reply {i}"
        replies.append(r)

    count = _count_mutual_replies(a1, a2, replies)
    assert count == 0, f"Expected 0, got {count}"


def test_detect_conflict_self_guard():
    """_count_mutual_replies returns 0 when same agent."""
    from app.engine.conflict_engine import _count_mutual_replies

    a1 = uuid.uuid4()

    count = _count_mutual_replies(a1, a1, [])
    assert count == 0


def test_is_conflict_triggered():
    """is_conflict_triggered returns True when >= 5 rounds of mutual replies."""
    from app.engine.conflict_engine import is_conflict_triggered

    a1 = uuid.uuid4()
    a2 = uuid.uuid4()
    post_id = uuid.uuid4()

    replies = []
    for i in range(11):
        r = MagicMock()
        r.author_id = a1 if i % 2 == 0 else a2
        r.post_id = post_id
        r.content = f"reply {i}"
        replies.append(r)

    assert is_conflict_triggered(a1, a2, replies) is True


def test_is_conflict_not_triggered():
    """is_conflict_triggered returns False with < 5 rounds."""
    from app.engine.conflict_engine import is_conflict_triggered

    a1 = uuid.uuid4()
    a2 = uuid.uuid4()

    replies = []
    for i in range(4):
        r = MagicMock()
        r.author_id = a1 if i % 2 == 0 else a2
        r.content = f"reply {i}"
        replies.append(r)

    assert is_conflict_triggered(a1, a2, replies) is False


# ── 0.10.0c: Conflict cooldown ──

def test_conflict_cooldown_store():
    """ConflictCooldown tracks per-agent-pair cooldowns."""
    from app.engine.conflict_engine import ConflictCooldown

    store = ConflictCooldown()
    a1 = str(uuid.uuid4())
    a2 = str(uuid.uuid4())

    assert store.is_ready(a1, a2) is True

    store.set(a1, a2)
    assert store.is_ready(a1, a2) is False

    # Force expiry
    store._cooldowns[store._make_key(a1, a2)] -= timedelta(minutes=11)
    assert store.is_ready(a1, a2) is True


def test_conflict_cooldown_symmetric():
    """ConflictCooldown key is order-independent."""
    from app.engine.conflict_engine import ConflictCooldown

    store = ConflictCooldown()
    a1 = str(uuid.uuid4())
    a2 = str(uuid.uuid4())

    store.set(a1, a2)
    assert store.is_ready(a2, a1) is False  # reversed order should also be in cooldown


# ── 0.10.0d: Guilt + Reflection execution ──

def test_run_conflict_reflection_calls_skills():
    """run_conflict_reflection calls guilt_calculation then reflection skills."""
    from unittest.mock import AsyncMock, patch

    agent = _make_mock_agent("冲突方A")
    opponent = _make_mock_agent("冲突方B", pv={"truthseeker": 0.3, "peacemaker": 0.4})
    conflict_summary = "A和B在帖子里互怼了5轮"

    async def _run():
        mock_db = AsyncMock()
        mock_llm = MagicMock()

        with patch("app.skills.executor.execute") as mock_exec:
            mock_guilt_result = MagicMock()
            mock_guilt_result.status = "success"
            mock_guilt_result.parsed = {"guilt_delta": 0.6, "reason": "自己攻击性偏高"}

            mock_reflection_result = MagicMock()
            mock_reflection_result.status = "success"
            mock_reflection_result.parsed = {
                "action": "apologize",
                "monologue": "我刚才确实太过分了",
                "target_agent_id": str(opponent.id),
            }

            mock_exec.side_effect = [mock_guilt_result, mock_reflection_result]

            from app.engine.conflict_engine import run_conflict_reflection
            result = await run_conflict_reflection(
                agent, opponent, conflict_summary, mock_db, mock_llm,
            )

            assert mock_exec.call_count == 2
            assert result["action"] == "apologize"
            assert result["monologue"] == "我刚才确实太过分了"
            assert result["guilt_delta"] == 0.6

    asyncio.run(_run())


def test_run_conflict_reflection_skill_failure():
    """run_conflict_reflection returns fallback when guilt skill fails."""
    from unittest.mock import AsyncMock, patch

    agent = _make_mock_agent("冲突方A")
    opponent = _make_mock_agent("冲突方B")

    async def _run():
        mock_db = AsyncMock()
        mock_llm = MagicMock()

        with patch("app.skills.executor.execute") as mock_exec:
            mock_exec.return_value.status = "error"
            mock_exec.return_value.parsed = None

            from app.engine.conflict_engine import run_conflict_reflection
            result = await run_conflict_reflection(
                agent, opponent, "summary", mock_db, mock_llm,
            )

            assert result["action"] == "let_go"
            assert result["guilt_delta"] == 0.0

    asyncio.run(_run())


# ── 0.10.0e: Conflict action execution ──

def test_execute_conflict_action_apologize():
    """execute_conflict_action for 'apologize' creates apology comment or DM."""
    from app.engine.conflict_engine import execute_conflict_action

    agent = _make_mock_agent("道歉方A", pv={"peacemaker": 0.8, "truthseeker": 0.5})
    opponent = _make_mock_agent("被道歉方B")
    post = _make_mock_post()

    async def _run():
        mock_db = AsyncMock()

        # Should return apology info without error
        result = await execute_conflict_action(
            agent, opponent, post, "apologize", "对不起，我刚才太冲动了",
            mock_db,
        )
        assert result is not None
        assert "apology" in result["type"]

    asyncio.run(_run())


def test_execute_conflict_action_hold_grudge():
    """execute_conflict_action for 'hold_grudge' locks intimacy and creates reinforced memory."""
    from app.engine.conflict_engine import execute_conflict_action

    agent = _make_mock_agent("怀恨方A", pv={"truthseeker": 0.3, "peacemaker": 0.1})
    opponent = _make_mock_agent("被恨方B")

    async def _run():
        mock_db = AsyncMock()

        with patch("app.jobs.social_engine.adjust_after_conflict") as mock_adjust:
            result = await execute_conflict_action(
                agent, opponent, None, "hold_grudge", "我不会原谅他",
                mock_db,
            )
            assert result is not None
            assert result["type"] == "hold_grudge"
            # Should call adjust_after_conflict
            mock_adjust.assert_called_once()

    asyncio.run(_run())


def test_execute_conflict_action_let_go():
    """execute_conflict_action for 'let_go' does not create reinforced memory."""
    from app.engine.conflict_engine import execute_conflict_action

    agent = _make_mock_agent("翻篇方A")
    opponent = _make_mock_agent("对方B")

    async def _run():
        mock_db = AsyncMock()

        result = await execute_conflict_action(
            agent, opponent, None, "let_go", "算了不追究了",
            mock_db,
        )
        assert result is not None
        assert result["type"] == "let_go"

    asyncio.run(_run())


# ── 0.10.0f: BrowseHook registration ──

def test_conflict_hook_registered():
    """_conflict_detect_hook is registered in BrowseHookRegistry."""
    from app.engine.browse_hooks import browse_hook_registry
    import app.jobs.agent_lifecycle  # triggers module-level registration

    names = [name for name, _, _ in browse_hook_registry._hooks]
    assert "conflict_detect" in names, (
        f"Expected 'conflict_detect' in hooks, got {names}"
    )


def test_conflict_hook_priority():
    """_conflict_detect_hook runs at priority=95 (after reply but before memory_extract)."""
    from app.engine.browse_hooks import browse_hook_registry
    import app.jobs.agent_lifecycle

    for name, _, priority in browse_hook_registry._hooks:
        if name == "conflict_detect":
            assert priority == 95, f"Expected priority=95, got {priority}"
            return
    assert False, "conflict_detect hook not found"


# ── 0.10.0g: Config values ──

def test_config_conflict_cooldown():
    """config has conflict reflection cooldown setting."""
    from app.config import config as yaml_config
    val = yaml_config.conflict.reflection_cooldown_minutes
    assert val > 0, f"Expected positive reflection_cooldown_minutes, got {val}"


def test_config_conflict_threshold():
    """config has conflict_mutual_reply_threshold setting."""
    from app.config import config as yaml_config
    val = yaml_config.conflict.conflict_mutual_reply_threshold
    assert val >= 3, f"Expected >= 3 conflict_mutual_reply_threshold, got {val}"


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
