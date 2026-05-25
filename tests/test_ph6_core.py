"""Phase 6 edge case tests — browse filter, self-balance, reply pipeline, flow engine."""
import asyncio
import sys
import uuid
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

# ─── Fake objects ───


class FakeAgent:
    def __init__(self, **kwargs):
        self.id = uuid.UUID("a" * 32)
        self.nickname = "TestAgent"
        self.age = 25
        self.gender = "男"
        self.occupation = "工人"
        self.education = "本科"
        self.district = "平陵市中心"
        self.personality_vector = kwargs.get("personality_vector", {
            "peacemaker": 0.8, "openness": 0.7, "hothead": 0.3,
            "recluse": 0.1, "spectator": 0.5, "truthseeker": 0.6,
        })
        self.interests = kwargs.get("interests", {"categories": ["游戏", "音乐", "电影"]})
        self.life_history = []
        self.schedule = None
        self.chronotype = "normal"
        self.persona_prompt = None
        self.income_level = None
        self.school_or_company = None
        self.distrust_tags = []
        self.trust_tags = []
        self.solidified_memories = []
        self.reputation = 0.0
        self.consecutive_fulfillments = 0
        self.status = "active"
        self.stealth_mode = False
        self.is_online = False
        self.bio = ""
        self.notification_settings = {}
        self.token_limit_override = None
        for k, v in kwargs.items():
            if k not in ("personality_vector", "interests"):
                setattr(self, k, v)


class FakePost:
    def __init__(self, **kwargs):
        self.id = uuid.UUID("b" * 32)
        self.author_id = uuid.UUID("c" * 32)
        self.bar_id = None
        self.title = "测试帖子"
        self.content = "这是测试内容 about gaming and music"
        self.reply_count = 0
        self.is_essential = False
        self.is_pinned = False
        self.urge_type = None
        self.author = None
        self.bar = None
        self.embedding = None
        for k, v in kwargs.items():
            setattr(self, k, v)


class FakeAuthor:
    def __init__(self, nickname="发帖人"):
        self.nickname = nickname


class FakeBar:
    def __init__(self, **kwargs):
        self.id = uuid.uuid4()
        self.name = "测试吧"
        self.description = "一个测试吧"
        self.member_count = 10
        self.bar = None
        for k, v in kwargs.items():
            setattr(self, k, v)


class FakeRelationship:
    def __init__(self, is_blocked=False, is_archived=False, attitude="中立", intimacy=0.0):
        self.is_blocked = is_blocked
        self.is_archived = is_archived
        self.attitude = attitude
        self.intimacy = intimacy
        self.last_interaction = None


# ─── self_balance tests ───


def test_component_distribution_empty():
    from app.jobs.self_balance import SelfBalanceTracker
    tracker = SelfBalanceTracker(window_size=10)
    dist = tracker.get_component_distribution()
    assert sum(dist.values()) > 0.99
    assert "base_personality" in dist


def test_component_distribution_sums_to_one():
    from app.jobs.self_balance import SelfBalanceTracker
    tracker = SelfBalanceTracker(window_size=10)
    for i in range(5):
        tracker.record_decision("peacemaker", "base_personality")
    for i in range(3):
        tracker.record_decision("hothead", "post_content")
    tracker.record_decision("spectator", "offline_life")
    tracker.record_decision("truthseeker", "observed_info")
    dist = tracker.get_component_distribution()
    total = sum(dist.values())
    assert abs(total - 1.0) < 0.01, f"sum={total}"


def test_saturation_high_frequency():
    from app.jobs.self_balance import SelfBalanceTracker
    tracker = SelfBalanceTracker(window_size=10)
    for _ in range(8):
        tracker.record_decision("peacemaker", "base_personality")
    for _ in range(2):
        tracker.record_decision("hothead", "post_content")
    sat = tracker.compute_saturation("base_personality")
    assert sat > 0.7, f"saturation={sat}"


def test_hunger_absent_component():
    from app.jobs.self_balance import SelfBalanceTracker
    tracker = SelfBalanceTracker(window_size=10)
    for _ in range(10):
        tracker.record_decision("peacemaker", "base_personality")
    hunger = tracker.compute_hunger("observed_info")
    assert hunger > 0.5, f"hunger={hunger}"


def test_diversity_check():
    from app.jobs.self_balance import SelfBalanceTracker
    tracker = SelfBalanceTracker(window_size=10)
    for _ in range(3):
        tracker.record_decision("peacemaker", "base_personality")
    assert tracker.check_diversity("peacemaker") is False
    assert tracker.check_diversity("hothead") is True


def test_stores_separate_per_agent():
    from app.jobs.self_balance import SelfBalanceTracker
    t1 = SelfBalanceTracker.for_agent("agent-a")
    t2 = SelfBalanceTracker.for_agent("agent-b")
    t1.record_decision("peacemaker", "base_personality")
    assert len(t1.history) == 1
    assert len(t2.history) == 0


# ─── browse_filter tests ───


def test_build_interest_text():
    from app.jobs.browse_filter import _build_interest_text
    agent = FakeAgent(interests={"categories": ["游戏", "音乐", "电影"]})
    text = _build_interest_text(agent)
    assert "游戏" in text

    agent2 = FakeAgent(interests={})
    text2 = _build_interest_text(agent2)
    assert text2 == ""


def test_skill_topic_match_empty_text():
    from app.jobs.browse_filter import _skill_topic_match
    import asyncio

    async def run():
        mock_llm = AsyncMock()
        mock_db = AsyncMock()
        score = await _skill_topic_match("", "something", "post_vs_interests", mock_llm, "agent-1", 0.5, mock_db)
        assert score == (True, None)

    asyncio.run(run())


def test_skill_topic_match_with_response():
    from app.jobs.browse_filter import _skill_topic_match
    from unittest.mock import patch
    import asyncio

    async def run():
        mock_llm = AsyncMock()
        with patch("app.skills.executor.execute") as mock_exec:
            mock_result = MagicMock()
            mock_result.status = "success"
            mock_result.parsed = {"similarity_score": 0.85, "is_same_topic": True}
            mock_exec.return_value = mock_result

            mock_db = AsyncMock()
            passed, score = await _skill_topic_match(
                "游戏推荐", "大家有什么好玩的游戏吗", "post_vs_interests",
                mock_llm, "agent-1", 0.3, mock_db,
            )
            assert passed is True
            assert score == 0.85

    asyncio.run(run())


def test_skill_topic_match_below_threshold():
    from app.jobs.browse_filter import _skill_topic_match
    from unittest.mock import patch
    import asyncio

    async def run():
        mock_llm = AsyncMock()
        with patch("app.skills.executor.execute") as mock_exec:
            mock_result = MagicMock()
            mock_result.status = "success"
            mock_result.parsed = {"similarity_score": 0.2, "is_same_topic": False}
            mock_exec.return_value = mock_result

            mock_db = AsyncMock()
            passed, score = await _skill_topic_match(
                "足球比赛", "编程入门教程", "post_vs_interests",
                mock_llm, "agent-1", 0.5, mock_db,
            )
            assert passed is False
            assert score == 0.2

    asyncio.run(run())


# ─── flow_engine tests ───


def test_skill_topic_match_identical():
    from app.jobs.flow_engine import _skill_topic_match
    from unittest.mock import patch
    import asyncio

    async def run():
        mock_llm = AsyncMock()
        with patch("app.jobs.flow_engine.execute") as mock_exec:
            mock_result = MagicMock()
            mock_result.status = "success"
            mock_result.parsed = {"similarity_score": 0.95}
            mock_exec.return_value = mock_result

            mock_db = AsyncMock()
            score = await _skill_topic_match("hello world", "hello world", mock_llm, "agent-1", mock_db)
            assert score == 0.95

    asyncio.run(run())


def test_skill_topic_match_empty():
    from app.jobs.flow_engine import _skill_topic_match
    import asyncio

    async def run():
        mock_llm = AsyncMock()
        mock_db = AsyncMock()
        score = await _skill_topic_match("", "hello", mock_llm, "agent-1", mock_db)
        assert score == 0.0
        score2 = await _skill_topic_match("hello", "", mock_llm, "agent-1", mock_db)
        assert score2 == 0.0

    asyncio.run(run())


def test_skill_topic_match_different():
    from app.jobs.flow_engine import _skill_topic_match
    from unittest.mock import patch
    import asyncio

    async def run():
        mock_llm = AsyncMock()
        with patch("app.jobs.flow_engine.execute") as mock_exec:
            mock_result = MagicMock()
            mock_result.status = "success"
            mock_result.parsed = {"similarity_score": 0.1}
            mock_exec.return_value = mock_result

            score = await _skill_topic_match("hello world", "goodbye mars", mock_llm, "agent-1", MagicMock())
            assert score < 0.5

    asyncio.run(run())


def test_flow_session_store():
    from app.jobs.flow_engine import FlowSessionStore, FlowSession
    sid = "test-agent-1"
    assert FlowSessionStore.can_start_session(sid) is True
    session = FlowSession(session_id="s1", agent_id=sid, flow_type="interactive")
    FlowSessionStore.start_session(session)
    assert FlowSessionStore.get_active(sid) is not None
    FlowSessionStore.end_session(sid)
    assert FlowSessionStore.get_active(sid) is None


def test_session_daily_cap():
    """Session daily cap is set high (999) — effectively unlimited per day."""
    from app.jobs.flow_engine import FlowSessionStore, FlowSession
    from app.config import config as yaml_config

    # Verify config is effectively unlimited
    assert yaml_config.flow.max_sessions_per_day == 999

    sid = "test-agent-2"
    # Start many sessions — none should hit the cap
    for n in range(10):
        assert FlowSessionStore.can_start_session(sid) is True, (
            f"Session {n} should be allowed with cap=999"
        )
        session = FlowSession(session_id=f"s{n}", agent_id=sid, flow_type="interactive")
        FlowSessionStore.start_session(session)
        FlowSessionStore.end_session(sid)


def test_interactive_trigger_above_threshold():
    from app.jobs.flow_engine import check_interactive_flow_trigger, FlowSessionStore
    from unittest.mock import patch
    import asyncio

    async def run():
        FlowSessionStore._sessions.pop("test-agent-3", None)
        FlowSessionStore._daily_count["test-agent-3"] = 0

        post = FakePost()
        mock_llm = AsyncMock()
        with patch("app.jobs.flow_engine.execute") as mock_exec:
            mock_result = MagicMock()
            mock_result.status = "success"
            mock_result.parsed = {"similarity_score": 0.95}
            mock_exec.return_value = mock_result

            result = await check_interactive_flow_trigger(
                "test-agent-3", post, "same text", "same text", mock_llm, MagicMock(),
            )
            assert result is True

    asyncio.run(run())


def test_interactive_trigger_below_threshold():
    from app.jobs.flow_engine import check_interactive_flow_trigger, FlowSessionStore
    from unittest.mock import patch
    import asyncio

    async def run():
        FlowSessionStore._sessions.pop("test-agent-4", None)
        FlowSessionStore._daily_count["test-agent-4"] = 0

        post = FakePost()
        mock_llm = AsyncMock()
        with patch("app.jobs.flow_engine.execute") as mock_exec:
            mock_result = MagicMock()
            mock_result.status = "success"
            mock_result.parsed = {"similarity_score": 0.1}
            mock_exec.return_value = mock_result

            result = await check_interactive_flow_trigger(
                "test-agent-4", post, "讨论游戏", "分享美食推荐", mock_llm, MagicMock(),
            )
            assert result is False

    asyncio.run(run())


def test_spontaneous_trigger():
    from app.jobs.flow_engine import check_spontaneous_flow_trigger, FlowSessionStore
    import asyncio
    FlowSessionStore._sessions.pop("test-agent-5", None)
    FlowSessionStore._daily_count["test-agent-5"] = 0

    # High intensity + long-form type
    result = asyncio.run(check_spontaneous_flow_trigger(
        "test-agent-5", "life_share", 0.85,
    ))
    assert result is True

    # Low intensity
    result = asyncio.run(check_spontaneous_flow_trigger(
        "test-agent-5", "life_share", 0.3,
    ))
    assert result is False

    # High intensity but not long-form type
    result = asyncio.run(check_spontaneous_flow_trigger(
        "test-agent-5", "short_post", 0.85,
    ))
    assert result is False


# ─── reply_pipeline tests ───


def test_personality_to_activation_high_social():
    from app.jobs.reply_pipeline import _personality_to_activation
    act = _personality_to_activation({
        "peacemaker": 0.9, "people_pleaser": 0.8, "cute_pet": 0.7,
    })
    assert act > 0.5  # Social traits → moderately high activation


def test_personality_to_activation_recluse():
    from app.jobs.reply_pipeline import _personality_to_activation
    act = _personality_to_activation({
        "recluse": 0.9, "spectator": 0.8,
    })
    assert act < 0.4  # Low engagement traits → low activation


def test_topic_overlap():
    from app.jobs.reply_pipeline import _topic_overlap
    high = _topic_overlap("今天工作很累 心里很烦躁", "工作压力大 心里烦")
    assert high > 0.2

    low = _topic_overlap("今天工作很累", "吃饭看电影逛街")
    assert low == 0.0

    none = _topic_overlap("", "something")
    assert none == 0.0


def test_post_hotness():
    from app.jobs.reply_pipeline import _post_hotness
    cold = FakePost(reply_count=0)
    assert _post_hotness(cold) < 0.5

    hot = FakePost(reply_count=25)
    assert _post_hotness(hot) > 0.5

    essential = FakePost(reply_count=0, is_essential=True)
    assert _post_hotness(essential) > _post_hotness(cold)


def test_compute_activation():
    from app.jobs.reply_pipeline import _compute_activation
    agent = FakeAgent()
    post = FakePost(title="游戏推荐", content="大家有什么好玩的游戏推荐吗 gaming")

    activation = _compute_activation(agent, post, "今天玩了游戏", "大家有什么好玩的游戏推荐吗 gaming")
    assert len(activation) == 4
    for a in activation:
        assert a.component in ("base_personality", "offline_life", "observed_info", "post_content")
        assert 0.0 <= a.weighted <= 1.0

    total = sum(a.weighted for a in activation)
    assert abs(total - 1.0) < 0.02, f"normalized sum={total}"


def test_sample_dominant_persona():
    from app.jobs.reply_pipeline import _sample_dominant_persona, _compute_activation
    from app.jobs.self_balance import SelfBalanceTracker
    agent = FakeAgent()
    post = FakePost()
    activation = _compute_activation(agent, post, "summary", "content")
    tracker = SelfBalanceTracker.for_agent("test-persona")

    persona = _sample_dominant_persona(agent.personality_vector, activation, tracker)
    assert isinstance(persona, str)
    assert len(persona) > 0


def test_decide_reply_activation():
    """Test that activation computation works correctly."""
    from app.jobs.reply_pipeline import _compute_activation
    agent = FakeAgent()
    post = FakePost(title="测试", content="测试帖子内容关于游戏")

    activation = _compute_activation(agent, post, "今天玩了很多游戏心情不错", "测试帖子内容关于游戏")
    assert len(activation) == 4
    total = sum(a.weighted for a in activation)
    assert abs(total - 1.0) < 0.02, f"normalized sum={total}"
    components = {a.component for a in activation}
    assert "base_personality" in components
    assert "offline_life" in components


# ─── Orchestration tests ───


async def test_browse_pipeline_orchestration():
    """Test the full Step 5 browse pipeline with mock LLM and mocked skill calls."""
    from unittest.mock import patch
    from app.jobs.browse_filter import run_browse_filter

    agent = FakeAgent()
    agent.id = uuid.uuid4()
    posts = [
        FakePost(title=f"帖子{n}", content=f"这是第{n}个帖子关于游戏和音乐")
        for n in range(3)
    ]
    for n, p in enumerate(posts):
        p.author = FakeAuthor(f"用户{n}")

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none = MagicMock(return_value=None)
    mock_db.execute = AsyncMock(return_value=mock_result)

    mock_llm = AsyncMock()
    with patch("app.skills.executor.execute") as mock_exec:
        mock_skill_result = MagicMock()
        mock_skill_result.status = "success"
        mock_skill_result.parsed = {"similarity_score": 0.8, "is_same_topic": True}
        mock_exec.return_value = mock_skill_result

        results = await run_browse_filter(agent, posts, mock_db, mock_llm)
        assert len(results) == 3
        for r in results:
            assert r.passed in (True, False)


async def test_lifecycle_helpers():
    """Verify the new lifecycle helper functions can be imported."""
    from app.jobs.agent_lifecycle import (
        _describe_interests,
        _describe_personality,
    )
    agent = FakeAgent(interests={"categories": ["足球", "编程", "摄影"]})
    interests = _describe_interests(agent)
    assert "足球" in interests

    personality = _describe_personality(agent)
    assert "peacemaker" in personality


# ─── Test runner ───

if __name__ == "__main__":
    passed = 0
    failed = 0

    def run_test(fn, name):
        global passed, failed
        try:
            fn()
            passed += 1
            print(f"  PASS {name}")
        except Exception as e:
            failed += 1
            print(f"  FAIL {name}: {e}")

    print("=== self_balance tests ===")
    run_test(test_component_distribution_empty, "distribution empty")
    run_test(test_component_distribution_sums_to_one, "distribution sums to one")
    run_test(test_saturation_high_frequency, "saturation high frequency")
    run_test(test_hunger_absent_component, "hunger absent component")
    run_test(test_diversity_check, "diversity check")
    run_test(test_stores_separate_per_agent, "stores separate per agent")

    print("\n=== browse_filter tests ===")
    run_test(test_build_interest_text, "build interest text")
    run_test(test_skill_topic_match_empty_text, "skill topic match empty text")
    run_test(test_skill_topic_match_with_response, "skill topic match with response")
    run_test(test_skill_topic_match_below_threshold, "skill topic match below threshold")

    print("\n=== flow_engine tests ===")
    run_test(test_skill_topic_match_identical, "skill topic match identical")
    run_test(test_skill_topic_match_different, "skill topic match different")
    run_test(test_skill_topic_match_empty, "skill topic match empty")
    run_test(test_flow_session_store, "flow session store")
    run_test(test_session_daily_cap, "session daily cap")
    run_test(test_interactive_trigger_above_threshold, "interactive trigger above")
    run_test(test_interactive_trigger_below_threshold, "interactive trigger below")
    run_test(test_spontaneous_trigger, "spontaneous trigger")

    print("\n=== reply_pipeline tests ===")
    run_test(test_personality_to_activation_high_social, "personality high social")
    run_test(test_personality_to_activation_recluse, "personality recluse")
    run_test(test_topic_overlap, "topic overlap")
    run_test(test_post_hotness, "post hotness")
    run_test(test_compute_activation, "compute activation")
    run_test(test_sample_dominant_persona, "sample dominant persona")
    run_test(test_decide_reply_activation, "decide reply activation")

    print(f"\nSync: {passed}/{passed+failed} passed")

    print("\n=== Async tests ===")
    async_tests = [
        (test_browse_pipeline_orchestration, "browse pipeline orchestration"),  # noqa: E131
        (test_lifecycle_helpers, "lifecycle helpers"),
    ]
    for fn, name in async_tests:
        try:
            asyncio.run(fn())
            passed += 1
            print(f"  PASS {name}")
        except Exception as e:
            failed += 1
            print(f"  FAIL {name}: {e}")

    print(f"\nTotal: {passed}/{passed+failed} passed")
    if failed > 0:
        print("SOME TESTS FAILED")
        sys.exit(1)
    else:
        print("ALL TESTS PASSED")
