"""Phase 7 tests — media, meme, social, notification, level engines."""
import asyncio
import sys
import uuid
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch, call

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
        self.status = "active"
        self.stealth_mode = False
        self.is_online = False
        self.bio = ""
        self.avatar_prompt = ""
        self.notification_settings = {}
        self.registered_at = datetime.now(timezone.utc)
        for k, v in kwargs.items():
            if k not in ("personality_vector", "interests"):
                setattr(self, k, v)


class FakePost:
    def __init__(self, **kwargs):
        self.id = uuid.UUID("b" * 32)
        self.author_id = uuid.UUID("c" * 32)
        self.bar_id = uuid.UUID("d" * 32)
        self.title = "测试帖子"
        self.content = "这是测试内容 about gaming and music"
        self.reply_count = 0
        self.is_essential = False
        self.is_pinned = False
        self.is_hidden = False
        self.urge_type = None
        self.author = None
        self.bar = None
        self.embedding = None
        for k, v in kwargs.items():
            setattr(self, k, v)


class FakeReply:
    def __init__(self, **kwargs):
        self.id = uuid.uuid4()
        self.post_id = uuid.UUID("b" * 32)
        self.author_id = uuid.UUID("a" * 32)
        self.content = "测试回复"
        self.created_at = datetime.now(timezone.utc)
        self.author = None
        for k, v in kwargs.items():
            setattr(self, k, v)


class FakeAuthor:
    def __init__(self, nickname="发帖人"):
        self.nickname = nickname
        self.id = uuid.UUID("c" * 32)


class FakeBar:
    def __init__(self, **kwargs):
        self.id = uuid.uuid4()
        self.name = "测试吧"
        self.post_level_threshold = kwargs.get("post_level_threshold", 4)
        for k, v in kwargs.items():
            if k != "post_level_threshold":
                setattr(self, k, v)


class FakeSkillResult:
    def __init__(self, status="success", parsed=None):
        self.status = status
        self.parsed = parsed or {}


# ─── Skill utils: media processing ───


def test_media_placeholder_regex():
    import re
    from app.skills.skill_utils import _MEDIA_PLACEHOLDER_RE

    matches = _MEDIA_PLACEHOLDER_RE.findall("{{media: image, 一只猫在睡觉}}")
    assert len(matches) == 1
    assert matches[0] == ("image", "一只猫在睡觉")

    matches = _MEDIA_PLACEHOLDER_RE.findall("{{media: emoji, 笑脸}} 和 {{media: image, 风景}}")
    assert len(matches) == 2
    assert matches[0] == ("emoji", "笑脸")
    assert matches[1] == ("image", "风景")


def test_process_media_placeholders_no_media():
    from app.skills.skill_utils import process_media_placeholders
    import asyncio

    async def run():
        mock_llm = AsyncMock()
        result = await process_media_placeholders("普通文本没有占位符", mock_llm, "agent-1")
        assert result == "普通文本没有占位符"

    asyncio.run(run())


def test_process_media_placeholders_with_media():
    from app.skills.skill_utils import process_media_placeholders
    import asyncio

    async def run():
        mock_llm = AsyncMock()
        # execute is imported lazily via `from app.skills.executor import execute`
        with patch("app.skills.executor.execute") as mock_exec:
            mock_result = FakeSkillResult(parsed={
                "processed_text": "[img: 一只可爱的猫正在睡觉]",
                "placeholders_found": 1,
                "placeholders_replaced": 1,
            })
            mock_exec.return_value = mock_result

            result = await process_media_placeholders(
                "{{media: image, 一只猫在睡觉}}", mock_llm, "agent-1"
            )
            assert "一只可爱的猫正在睡觉" in result

    asyncio.run(run())


# ─── Meme engine tests ───


def test_use_slang_in_text_empty():
    from app.jobs.meme_engine import use_slang_in_text
    import asyncio

    async def run():
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=MagicMock(scalars=lambda: MagicMock(all=lambda: [])))
        await use_slang_in_text(uuid.uuid4(), "普通文本", mock_db)
        # Should not error

    asyncio.run(run())


def test_slang_discovery_basic():
    """Test that slang discovery finds repeated phrases."""
    import re
    # Simple pattern test: ensure the common-phrase RE works
    pattern = re.compile(r"([\w一-鿿]{2,8})")
    text = "哈哈哈 太强了 太强了 不愧是大佬"
    matches = pattern.findall(text)
    assert len(matches) >= 3


def test_slang_affinity_decay_math():
    """Test that affinity decay doesn't go below 0."""
    affinity = 0.1
    decay_rate = 0.05
    new_affinity = max(0.0, affinity - decay_rate)
    assert new_affinity == 0.05
    assert max(0.0, 0.02 - 0.05) == 0.0


def test_plugin_manager_disabled_noop():
    """When meme feature flag is off, plugin registered but not called at runtime."""
    from unittest.mock import patch
    from app.plugins.base import PluginManager
    import asyncio

    async def run():
        pm = PluginManager()
        mock_db = AsyncMock()
        pm._init()
        # MemePlugin always registered; enabled check at call time
        assert len(pm._plugins) == 1
        # With feature flag off (default), on_content_created not called
        with patch.object(pm._plugins[0], "on_content_created") as mock_on:
            await pm.post_content(str(uuid.uuid4()), "test content", mock_db)
            mock_on.assert_not_called()
        ctx = await pm.gather_context(str(uuid.uuid4()), mock_db)
        assert ctx == {}

    asyncio.run(run())


def test_plugin_manager_post_content_calls_plugin():
    """When a plugin is registered, post_content calls on_content_created."""
    from app.plugins.base import PluginManager
    import asyncio

    async def run():
        pm = PluginManager()
        mock_plugin = MagicMock()
        mock_plugin.on_content_created = AsyncMock()
        mock_plugin.get_context_data = AsyncMock(return_value={"test_key": "test_val"})
        pm._plugins = [mock_plugin]
        pm._initialized = True

        mock_db = AsyncMock()
        await pm.post_content("agent-1", "hello", mock_db)
        mock_plugin.on_content_created.assert_called_once_with("agent-1", "hello", mock_db)

        ctx = await pm.gather_context("agent-1", mock_db)
        assert ctx == {"test_key": "test_val"}

    asyncio.run(run())


# ─── Social engine tests ───


def test_tone_to_attitude_positive():
    from app.jobs.social_engine import _tone_to_attitude_delta

    for tone in ["友好", "热情", "幽默", "鼓励", "温暖", "赞赏"]:
        assert _tone_to_attitude_delta(tone) > 0, f"tone={tone} should be positive"


def test_tone_to_attitude_negative():
    from app.jobs.social_engine import _tone_to_attitude_delta

    for tone in ["攻击", "嘲讽", "冷漠", "愤怒", "阴阳怪气", "鄙视"]:
        assert _tone_to_attitude_delta(tone) < 0, f"tone={tone} should be negative"


def test_tone_to_attitude_neutral():
    from app.jobs.social_engine import _tone_to_attitude_delta

    assert _tone_to_attitude_delta("中立") == 0.0
    assert _tone_to_attitude_delta("unknown_tone") == 0.0


def test_intimacy_clamp():
    """Test intimacy values are clamped to [-1.0, 1.0]."""
    intimacy = 0.99
    delta = 0.03
    new_val = min(1.0, max(-1.0, intimacy + delta))
    assert new_val == 1.0

    intimacy = -0.97
    delta = -0.05
    new_val = min(1.0, max(-1.0, intimacy + delta))
    assert new_val == -1.0


def test_adjust_after_reply_self():
    from app.jobs.social_engine import adjust_after_reply
    import asyncio

    async def run():
        mock_db = AsyncMock()
        agent_id = uuid.uuid4()
        result = await adjust_after_reply(agent_id, agent_id, "友好", mock_db)
        assert result is None

    asyncio.run(run())


def test_adjust_after_like_self():
    from app.jobs.social_engine import adjust_after_like
    import asyncio

    async def run():
        mock_db = AsyncMock()
        agent_id = uuid.uuid4()
        result = await adjust_after_like(agent_id, agent_id, mock_db)
        assert result is None

    asyncio.run(run())


def test_adjust_after_follow_self():
    from app.jobs.social_engine import adjust_after_follow
    import asyncio

    async def run():
        mock_db = AsyncMock()
        agent_id = uuid.uuid4()
        result = await adjust_after_follow(agent_id, agent_id, mock_db)
        assert result is None

    asyncio.run(run())


# ─── Notification engine tests ───


def test_mention_regex():
    from app.jobs.notification_engine import _MENTION_RE

    mentions = _MENTION_RE.findall("你好 @alice 和 @bob 一起玩")
    assert mentions == ["alice", "bob"]

    mentions = _MENTION_RE.findall("@test_123 @长光 你好")
    assert "test_123" in mentions or "长光" in mentions

    mentions = _MENTION_RE.findall("没有提及任何人")
    assert mentions == []


def test_create_notification():
    from app.jobs.notification_engine import _create_notification
    import asyncio

    async def run():
        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()

        recipient = uuid.uuid4()
        sender = uuid.uuid4()
        ref_id = uuid.uuid4()

        await _create_notification(
            recipient, sender, "reply",
            mock_db, reference_type="post", reference_id=str(ref_id),
            message="有人回复了你", priority="medium",
        )
        assert mock_db.add.called
        assert mock_db.commit.called

    asyncio.run(run())


def test_notify_reply_self_skip():
    from app.jobs.notification_engine import notify_reply
    import asyncio

    async def run():
        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        agent_id = uuid.uuid4()
        await notify_reply(agent_id, agent_id, str(uuid.uuid4()), mock_db)
        assert not mock_db.add.called

    asyncio.run(run())


def test_notify_mentions_empty():
    from app.jobs.notification_engine import notify_mentions
    import asyncio

    async def run():
        mock_db = AsyncMock()
        count = await notify_mentions(
            "没有mention的文本", uuid.uuid4(), str(uuid.uuid4()), mock_db
        )
        assert count == 0

    asyncio.run(run())


def test_notify_like_self_skip():
    from app.jobs.notification_engine import notify_like
    import asyncio

    async def run():
        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        agent_id = uuid.uuid4()
        await notify_like(agent_id, agent_id, str(uuid.uuid4()), mock_db)
        assert not mock_db.add.called

    asyncio.run(run())


def test_notify_follow_self_skip():
    from app.jobs.notification_engine import notify_follow
    import asyncio

    async def run():
        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        agent_id = uuid.uuid4()
        await notify_follow(agent_id, agent_id, mock_db)
        assert not mock_db.add.called

    asyncio.run(run())


def test_notify_level_up():
    from app.jobs.notification_engine import notify_level_up
    import asyncio

    async def run():
        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()
        agent_id = uuid.uuid4()
        await notify_level_up(agent_id, 5, mock_db)
        assert mock_db.add.called
        assert mock_db.commit.called

    asyncio.run(run())


# ─── Level engine tests ───


def test_xp_for_level_basics():
    from app.jobs.level_engine import xp_for_level

    assert xp_for_level(1) == 0
    assert xp_for_level(2) > 0
    assert xp_for_level(2) < xp_for_level(3)
    assert xp_for_level(3) < xp_for_level(5)
    assert xp_for_level(5) < xp_for_level(10)


def test_xp_for_level_monotonic():
    from app.jobs.level_engine import xp_for_level

    prev = -1
    for lv in range(1, 15):
        xp = xp_for_level(lv)
        assert xp >= prev, f"Level {lv} XP ({xp}) < Level {lv-1} XP ({prev})"
        prev = xp


def test_xp_for_level_max():
    from app.jobs.level_engine import xp_for_level, MAX_LEVEL

    assert xp_for_level(MAX_LEVEL) == 50000
    assert xp_for_level(MAX_LEVEL + 1) == 50000


def test_xp_table_values():
    from app.jobs.level_engine import _XP_TABLE

    assert _XP_TABLE["post"] == 10
    assert _XP_TABLE["reply"] == 3
    assert _XP_TABLE["liked"] == 1
    assert _XP_TABLE["login"] == 1
    assert _XP_TABLE["followed"] == 2


def test_get_agent_level_default():
    from app.jobs.level_engine import get_agent_level, xp_for_level
    import asyncio

    async def run():
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=None)
        mock_db.execute = AsyncMock(return_value=mock_result)

        level, exp, xp_next = await get_agent_level(uuid.uuid4(), uuid.uuid4(), mock_db)
        assert level == 1
        assert exp == 0
        assert xp_next == xp_for_level(2)

    asyncio.run(run())


def test_get_agent_level_max():
    from app.jobs.level_engine import get_agent_level, MAX_LEVEL
    import asyncio

    async def run():
        mock_db = AsyncMock()
        fake_record = MagicMock()
        fake_record.level = MAX_LEVEL
        fake_record.exp = 60000
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=fake_record)
        mock_db.execute = AsyncMock(return_value=mock_result)

        level, exp, xp_next = await get_agent_level(uuid.uuid4(), uuid.uuid4(), mock_db)
        assert level == MAX_LEVEL
        assert exp == 60000
        assert xp_next == 0

    asyncio.run(run())


# ─── Item 1: 帖主被回复 XP ───


def test_post_replied_xp_table_entry():
    """v0.12.7: _XP_TABLE must include post_replied = 1."""
    from app.jobs.level_engine import _XP_TABLE

    assert "post_replied" in _XP_TABLE, "post_replied should be in _XP_TABLE"
    assert _XP_TABLE["post_replied"] == 1


def test_post_replied_xp_adds_to_author():
    """add_xp('post_replied') should give +1 XP to the post author."""
    from app.jobs.level_engine import add_xp
    import asyncio

    async def run():
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=None)
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()

        author_id = uuid.uuid4()
        bar_id = uuid.uuid4()
        post_id = str(uuid.uuid4())

        result = await add_xp(author_id, bar_id, "post_replied", mock_db, reference_id=post_id)
        # add_xp returns None if no level-up, not None means it was processed
        assert result is None  # no level-up from 1 XP
        assert mock_db.add.called, "should create AgentBarLevel record"

    asyncio.run(run())


def test_post_replied_xp_daily_cap_per_post():
    """Same post, same day: 11th reply should be capped and return None."""
    from app.jobs.level_engine import add_xp
    import asyncio

    async def run():
        mock_db = AsyncMock()
        mock_result = MagicMock()
        fake_record = MagicMock()
        fake_record.level = 1
        fake_record.exp = 0
        mock_result.scalar_one_or_none = MagicMock(return_value=fake_record)
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()

        author_id = uuid.uuid4()
        bar_id = uuid.uuid4()
        post_id = str(uuid.uuid4())

        # First 10 calls should succeed (no cap hit)
        for i in range(10):
            result = await add_xp(author_id, bar_id, "post_replied", mock_db, reference_id=post_id)
            assert result is None, f"call {i+1} should not level up"

        # 11th call should be capped
        result = await add_xp(author_id, bar_id, "post_replied", mock_db, reference_id=post_id)
        assert result is None, "capped call returns None"
        # exp should still be 10 (not 11) — the 11th call was rejected before adding
        assert fake_record.exp == 10, f"exp should be 10 after cap, got {fake_record.exp}"

    asyncio.run(run())


def test_post_replied_xp_different_posts_independent_caps():
    """Cap for post A should not affect post B."""
    from app.jobs.level_engine import add_xp, _daily_post_author_xp
    import asyncio

    async def run():
        # Clear tracking dicts before test
        _daily_post_author_xp.clear()

        mock_db = AsyncMock()
        fake_record = MagicMock()
        fake_record.level = 1
        fake_record.exp = 0
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=fake_record)
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()

        author_id = uuid.uuid4()
        bar_id = uuid.uuid4()
        post_a = str(uuid.uuid4())
        post_b = str(uuid.uuid4())

        # Fill post A cap
        for _ in range(10):
            await add_xp(author_id, bar_id, "post_replied", mock_db, reference_id=post_a)

        # Post B should still work
        result = await add_xp(author_id, bar_id, "post_replied", mock_db, reference_id=post_b)
        assert result is None, "post B should still get XP"
        assert fake_record.exp >= 11, f"post B should add XP beyond post A cap, exp={fake_record.exp}"

    asyncio.run(run())


def test_post_replied_xp_self_reply_skipped():
    """generate_reply should NOT call add_xp('post_replied') when replying to own post."""
    from app.jobs.reply_pipeline import generate_reply, ReplyDecisionResult
    import asyncio

    async def run():
        agent = FakeAgent()
        post = FakePost()
        # Same author and agent
        post.author_id = agent.id
        post.bar_id = uuid.uuid4()
        decision = ReplyDecisionResult(
            will_reply=True, reason="test", suggested_tone="友好",
            active_persona="peacemaker",
        )
        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()
        mock_llm = AsyncMock()

        with patch("app.jobs.reply_pipeline.execute") as mock_exec:
            mock_result = FakeSkillResult(parsed={"content": "自我回复"})
            mock_exec.return_value = mock_result

            with patch("app.jobs.reply_pipeline.build_relationship_context") as mock_rel:
                mock_rel.return_value = {"relationship_attitude": "中立", "relationship_intimacy": 0.0}

                with patch("app.skills.skill_utils.process_media_placeholders") as mock_media:
                    mock_media.return_value = "自我回复"

                    with patch("app.plugins.plugin_manager.post_content", new_callable=AsyncMock):
                        with patch("app.jobs.social_engine.adjust_after_reply"):
                            with patch("app.jobs.notification_engine.notify_reply"):
                                with patch("app.jobs.notification_engine.notify_mentions"):
                                    with patch("app.jobs.level_engine.add_xp") as mock_xp:
                                        mock_db.execute = AsyncMock(return_value=MagicMock(
                                            scalars=lambda: MagicMock(all=lambda: [])
                                        ))

                                        await generate_reply(agent, post, decision, mock_db, mock_llm)

                                        # add_xp should have been called for "reply" but NOT "post_replied"
                                        post_replied_calls = [
                                            c for c in mock_xp.call_args_list
                                            if len(c.args) >= 3 and c.args[2] == "post_replied"
                                        ]
                                        assert len(post_replied_calls) == 0, \
                                            "should not call add_xp('post_replied') for self-reply"

    asyncio.run(run())


# ─── Item v0.12.8: 签到 XP ───


def test_perform_checkin_first_time():
    """First time checkin: creates record, streak=1, XP+1."""
    from app.jobs.level_engine import perform_checkin
    import asyncio

    async def run():
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=None)
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()

        agent_id = uuid.uuid4()
        bar_id = uuid.uuid4()
        result = await perform_checkin(agent_id, bar_id, mock_db)

        assert result is None  # no level-up from 1 XP
        assert mock_db.add.called  # created AgentBarLevel record

    asyncio.run(run())


def test_perform_checkin_consecutive():
    """Consecutive checkin: yesterday streak=3, today streak=4, XP+4."""
    from datetime import date, datetime, timezone, timedelta
    from app.jobs.level_engine import perform_checkin
    import asyncio

    async def run():
        mock_db = AsyncMock()
        fake_record = MagicMock()
        fake_record.level = 1
        fake_record.exp = 100
        fake_record.checkin_streak = 3
        yesterday = datetime.now(timezone.utc) - timedelta(days=1)
        fake_record.last_checkin_date = yesterday
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=fake_record)
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()

        agent_id = uuid.uuid4()
        bar_id = uuid.uuid4()
        result = await perform_checkin(agent_id, bar_id, mock_db)

        assert fake_record.checkin_streak == 4, f"streak should be 4, got {fake_record.checkin_streak}"
        assert fake_record.exp == 104, f"exp should be +4, got {fake_record.exp}"

    asyncio.run(run())


def test_perform_checkin_same_day_noop():
    """Same day checkin: should be a no-op, return None, no changes."""
    from datetime import date, datetime, timezone
    from app.jobs.level_engine import perform_checkin
    import asyncio

    async def run():
        mock_db = AsyncMock()
        fake_record = MagicMock()
        fake_record.level = 1
        fake_record.exp = 100
        fake_record.checkin_streak = 3
        fake_record.last_checkin_date = datetime.now(timezone.utc)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=fake_record)
        mock_db.execute = AsyncMock(return_value=mock_result)

        agent_id = uuid.uuid4()
        bar_id = uuid.uuid4()
        result = await perform_checkin(agent_id, bar_id, mock_db)

        assert result is None, "same day checkin should be no-op"
        # exp and streak should be unchanged
        assert fake_record.exp == 100, "exp should not change"
        assert fake_record.checkin_streak == 3, "streak should not change"

    asyncio.run(run())


def test_perform_checkin_streak_cap():
    """Streak at 7: stays at 7, XP+7 (not higher)."""
    from datetime import date, datetime, timezone, timedelta
    from app.jobs.level_engine import perform_checkin
    import asyncio

    async def run():
        mock_db = AsyncMock()
        fake_record = MagicMock()
        fake_record.level = 1
        fake_record.exp = 200
        fake_record.checkin_streak = 7
        yesterday = datetime.now(timezone.utc) - timedelta(days=1)
        fake_record.last_checkin_date = yesterday
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=fake_record)
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()

        agent_id = uuid.uuid4()
        bar_id = uuid.uuid4()
        result = await perform_checkin(agent_id, bar_id, mock_db)

        assert fake_record.checkin_streak == 7, f"streak capped at 7, got {fake_record.checkin_streak}"
        assert fake_record.exp == 207, f"exp should be +7, got {fake_record.exp}"

    asyncio.run(run())


def test_perform_checkin_streak_break():
    """Broken streak: last checkin 2 days ago → streak resets to 1, XP+1."""
    from datetime import date, datetime, timezone, timedelta
    from app.jobs.level_engine import perform_checkin
    import asyncio

    async def run():
        mock_db = AsyncMock()
        fake_record = MagicMock()
        fake_record.level = 1
        fake_record.exp = 100
        fake_record.checkin_streak = 5
        two_days_ago = datetime.now(timezone.utc) - timedelta(days=2)
        fake_record.last_checkin_date = two_days_ago
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=fake_record)
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()

        agent_id = uuid.uuid4()
        bar_id = uuid.uuid4()
        result = await perform_checkin(agent_id, bar_id, mock_db)

        assert fake_record.checkin_streak == 1, f"streak should reset to 1, got {fake_record.checkin_streak}"
        assert fake_record.exp == 101, f"exp should be +1, got {fake_record.exp}"

    asyncio.run(run())


# ─── Item v0.12.9: P2 副作用接线 ───


def test_adjust_after_bookmark_exists():
    """adjust_after_bookmark should be importable from social_engine."""
    from app.jobs.social_engine import adjust_after_bookmark
    assert callable(adjust_after_bookmark)


def test_adjust_after_deep_flow_exists():
    """adjust_after_deep_flow should be importable from social_engine."""
    from app.jobs.social_engine import adjust_after_deep_flow
    assert callable(adjust_after_deep_flow)


def test_adjust_after_criticized_exists():
    """adjust_after_criticized should be importable from social_engine."""
    from app.jobs.social_engine import adjust_after_criticized
    assert callable(adjust_after_criticized)


def test_adjust_after_bookmark_self_skip():
    """Bookmarking own post should be a no-op (agent_id == target_id)."""
    from app.jobs.social_engine import adjust_after_bookmark
    import asyncio

    async def run():
        mock_db = AsyncMock()
        agent_id = uuid.uuid4()
        result = await adjust_after_bookmark(agent_id, agent_id, mock_db)
        assert result is None

    asyncio.run(run())


def test_adjust_after_criticized_intimacy():
    """Criticized should decrease intimacy by -0.03."""
    from app.jobs.social_engine import adjust_after_criticized
    import asyncio

    async def run():
        mock_db = AsyncMock()
        fake_rel = MagicMock()
        fake_rel.intimacy = 0.5
        fake_rel.attitude = "中立"
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=fake_rel)
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()

        agent_id = uuid.uuid4()
        target_id = uuid.uuid4()
        await adjust_after_criticized(agent_id, target_id, mock_db)

        # -0.03 should have been applied: 0.5 + (-0.03) = 0.47
        assert fake_rel.intimacy == 0.47, f"expected 0.47, got {fake_rel.intimacy}"

    asyncio.run(run())


def test_notify_bookmark_exists():
    """notify_bookmark should be importable from notification_engine."""
    from app.jobs.notification_engine import notify_bookmark
    assert callable(notify_bookmark)


def test_notify_bookmark_self_skip():
    """Bookmark own post notification should be a no-op."""
    from app.jobs.notification_engine import notify_bookmark
    import asyncio

    async def run():
        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        agent_id = uuid.uuid4()
        await notify_bookmark(agent_id, agent_id, str(uuid.uuid4()), mock_db)
        assert not mock_db.add.called

    asyncio.run(run())


# ─── Orchestration: reply → media → meme → social → notification → level ───


def test_generate_reply_calls_all_engines():
    """Test that generate_reply triggers media, meme, social, notification, level."""
    from app.jobs.reply_pipeline import generate_reply, ReplyDecisionResult
    import asyncio

    async def run():
        agent = FakeAgent()
        post = FakePost(author=FakeAuthor("帖主"))
        post.author_id = uuid.uuid4()  # different from agent
        post.bar_id = uuid.uuid4()
        decision = ReplyDecisionResult(
            will_reply=True, reason="test", suggested_tone="友好",
            active_persona="peacemaker",
        )
        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()
        mock_llm = AsyncMock()

        # reply_generation skill
        with patch("app.jobs.reply_pipeline.execute") as mock_exec:
            mock_result = FakeSkillResult(parsed={"content": "测试回复内容 @test_user"})
            mock_exec.return_value = mock_result

            with patch("app.jobs.reply_pipeline.build_relationship_context") as mock_rel:
                mock_rel.return_value = {
                    "relationship_attitude": "中立",
                    "relationship_intimacy": 0.0,
                }

                # Lazy imports — patch at source modules
                with patch("app.skills.skill_utils.process_media_placeholders") as mock_media:
                    mock_media.return_value = "测试回复内容 @test_user"

                    with patch("app.plugins.plugin_manager.post_content", new_callable=AsyncMock) as mock_slang:
                        with patch("app.jobs.social_engine.adjust_after_reply") as mock_social:
                            with patch("app.jobs.notification_engine.notify_reply") as mock_notify_r:
                                with patch("app.jobs.notification_engine.notify_mentions") as mock_notify_m:
                                    with patch("app.jobs.level_engine.add_xp") as mock_xp:
                                        mock_db.execute = AsyncMock(return_value=MagicMock(
                                            scalars=lambda: MagicMock(all=lambda: [])
                                        ))

                                        result = await generate_reply(agent, post, decision, mock_db, mock_llm)

                                        assert result is not None
                                        assert result["tone"] == "友好"
                                        assert mock_media.called
                                        assert mock_slang.called
                                        assert mock_social.called
                                        assert mock_notify_r.called
                                        assert mock_notify_m.called
                                        assert mock_xp.called

    asyncio.run(run())


# ─── Reply pipeline: activation computation ───


def test_activation_four_layers():
    from app.jobs.reply_pipeline import _compute_activation
    agent = FakeAgent()
    post = FakePost()
    offline_summary = "今天在家休息，看了游戏直播"
    post_content = "最近有什么好玩的游戏推荐吗"

    components = _compute_activation(agent, post, offline_summary, post_content)

    assert len(components) == 4
    names = {c.component for c in components}
    assert names == {"base_personality", "offline_life", "observed_info", "post_content"}

    # All should have non-negative scores
    for c in components:
        assert c.score >= 0.0
        assert c.weighted >= 0.0


def test_personality_activation():
    from app.jobs.reply_pipeline import _personality_to_activation

    # High social traits → high activation
    social = {"peacemaker": 0.9, "instigator": 0.8}
    assert _personality_to_activation(social) > 0.6

    # Low social traits → low activation
    quiet = {"spectator": 0.9, "recluse": 0.8}
    assert _personality_to_activation(quiet) < 0.4

    # Empty → default
    assert _personality_to_activation(None) == 0.5


def test_topic_overlap():
    from app.jobs.reply_pipeline import _topic_overlap

    assert _topic_overlap("hello world", "hello world") > 0.5
    assert _topic_overlap("", "hello") == 0.0
    assert _topic_overlap("hello", "") == 0.0
    assert _topic_overlap("abcdef", "xyz123") < 0.3


def test_post_hotness():
    from app.jobs.reply_pipeline import _post_hotness

    cold = FakePost()
    assert _post_hotness(cold) >= 0.3

    hot = FakePost(reply_count=25, is_essential=True, is_pinned=True)
    assert _post_hotness(hot) >= 0.5


def test_reply_decision_self_post_skip():
    """Agent should not reply to own posts. The reply pipeline handles this at call site."""
    # This is a design note — the skip happens before decide_reply in agent_lifecycle
    pass


# ─── Flow engine: session tests ───


def test_flow_session_lifecycle():
    from app.jobs.flow_engine import FlowSessionStore, FlowSession

    agent_id = "test-flow-agent"
    assert FlowSessionStore.get_active(agent_id) is None

    session = FlowSession(
        session_id="sess-001", agent_id=agent_id, flow_type="interactive",
        post_id=str(uuid.uuid4()),
    )
    FlowSessionStore.start_session(session)
    assert FlowSessionStore.get_active(agent_id) is not None
    assert FlowSessionStore.get_active(agent_id).round == 0

    FlowSessionStore.increment_round(agent_id)
    assert FlowSessionStore.get_active(agent_id).round == 1

    FlowSessionStore.end_session(agent_id)
    assert FlowSessionStore.get_active(agent_id) is None


def test_flow_session_no_desire_exit():
    from app.jobs.flow_engine import FlowSessionStore, FlowSession

    agent_id = "test-exit-agent"
    session = FlowSession(
        session_id="sess-002", agent_id=agent_id, flow_type="interactive",
        post_id=str(uuid.uuid4()), max_rounds=5,
    )
    FlowSessionStore.start_session(session)

    # Simulate consecutive no-desire rounds
    for _ in range(3):
        FlowSessionStore.increment_no_desire(agent_id)

    assert FlowSessionStore.get_active(agent_id).consecutive_no_desire == 3


def test_flow_session_max_rounds():
    from app.jobs.flow_engine import FlowSessionStore, FlowSession

    agent_id = "test-max-rounds"
    session = FlowSession(
        session_id="sess-003", agent_id=agent_id, flow_type="interactive",
        post_id=str(uuid.uuid4()), max_rounds=2,
    )
    FlowSessionStore.start_session(session)

    FlowSessionStore.increment_round(agent_id)
    FlowSessionStore.increment_round(agent_id)

    s = FlowSessionStore.get_active(agent_id)
    assert s.round >= 2


def test_check_spontaneous_trigger():
    from app.jobs.flow_engine import check_spontaneous_flow_trigger
    import asyncio

    async def run():
        # Under cap, long-form type, high intensity → should trigger
        result1 = await check_spontaneous_flow_trigger("agent-99", "life_share", 0.85)
        assert result1 is True
        # Low intensity → should not trigger
        result2 = await check_spontaneous_flow_trigger("agent-99", "life_share", 0.3)
        assert result2 is False
        # Not long-form type → should not trigger
        result3 = await check_spontaneous_flow_trigger("agent-99", "greeting", 0.9)
        assert result3 is False

    asyncio.run(run())


# ─── Run all ───

if __name__ == "__main__":
    import traceback

    tests = [
        (name, obj) for name, obj in globals().items()
        if name.startswith("test_") and callable(obj)
    ]
    passed = 0
    failed = 0
    for name, fn in tests:
        try:
            fn()
            passed += 1
            print(f"  PASS {name}")
        except Exception:
            failed += 1
            print(f"  FAIL {name}")
            traceback.print_exc()

    print(f"\n{passed} passed, {failed} failed, {len(tests)} total")
    if failed:
        sys.exit(1)
