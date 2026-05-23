"""Phase 2 tests — model import integrity and field existence."""
import sys
import uuid


def test_all_models_importable():
    from app.models import (
        ActivityLog, Agent, AgentDailySchedule, AgentSchedule,
        AgentBarLevel, AgentSlang,
        Bar, BarMember, BarModLog, BarRule,
        Bookmark,
        Election,
        Follow,
        Like,
        Notification,
        Post,
        PrivateMessage,
        Relationship,
        Reply,
        SkillGroup, SkillGroupMember,
        Slang,
        Topic,
    )
    assert Agent is not None
    assert Post is not None


def test_base_metadata_populated():
    from app.models import Base
    tables = Base.metadata.tables
    expected = {
        "agents", "agent_schedules", "agent_daily_schedules", "activity_logs",
        "bars", "bar_members", "bar_mod_log", "bar_rules",
        "agent_bar_level", "elections",
        "topics", "notifications",
        "posts", "replies",
        "relationships",
        "skill_groups", "skill_group_members",
        "slangs", "agent_slangs",
        "likes", "follows", "bookmarks", "private_messages",
    }
    actual = set(tables.keys())
    missing = expected - actual
    assert not missing, f"Tables missing from metadata: {missing}"


# ─── Field existence + explicit value tests ───

def test_agent_field_roundtrip():
    from app.models.agent import Agent
    a = Agent(
        nickname="test", age=25, gender="男",
        occupation="工人", income_level="5k", education="本科",
        district="平陵市", school_or_company="工厂",
        boarding=False, stealth_mode=True, is_online=True,
        status="inactive", chronotype="nightowl",
    )
    assert a.nickname == "test"
    assert a.age == 25
    assert a.boarding is False
    assert a.stealth_mode is True
    assert a.is_online is True
    assert a.status == "inactive"
    assert a.chronotype == "nightowl"


def test_agent_schedule_field_roundtrip():
    from app.models.agent import AgentSchedule
    s = AgentSchedule(
        browse_speed="fast", reply_impulse=0.8,
        max_flow_rounds=10, max_flow_per_day=6,
    )
    assert s.browse_speed == "fast"
    assert s.reply_impulse == 0.8
    assert s.max_flow_rounds == 10
    assert s.max_flow_per_day == 6


def test_bar_field_roundtrip():
    from app.models.bar import Bar
    b = Bar(name="test", creator_id=uuid.uuid4(), current_owner_id=uuid.uuid4(),
            member_count=5, post_count=10, post_level_threshold=3, is_sage_managed=True)
    assert b.name == "test"
    assert b.member_count == 5
    assert b.post_count == 10
    assert b.post_level_threshold == 3
    assert b.is_sage_managed is True


def test_bar_member_field_roundtrip():
    from app.models.bar import BarMember
    m = BarMember(agent_id=uuid.uuid4(), bar_id=uuid.uuid4(),
                  role="moderator", is_muted=True)
    assert m.role == "moderator"
    assert m.is_muted is True


def test_bar_rule_field_roundtrip():
    from app.models.bar import BarRule
    r = BarRule(bar_id=uuid.uuid4(), content="rules", created_by=uuid.uuid4(),
                version=3, is_current=False)
    assert r.version == 3
    assert r.is_current is False


def test_bar_mod_log_field_roundtrip():
    from app.models.bar import BarModLog
    entry = BarModLog(bar_id=uuid.uuid4(), moderator_id=uuid.uuid4(), action="delete",
                      is_appealed=True, appeal_status="pending")
    assert entry.action == "delete"
    assert entry.is_appealed is True
    assert entry.appeal_status == "pending"


def test_agent_bar_level_field_roundtrip():
    from app.models.bar import AgentBarLevel
    lv = AgentBarLevel(agent_id=uuid.uuid4(), bar_id=uuid.uuid4(),
                       exp=50, level=3, checkin_streak=5)
    assert lv.exp == 50
    assert lv.level == 3
    assert lv.checkin_streak == 5


def test_election_field_roundtrip():
    from app.models.bar import Election
    e = Election(bar_id=uuid.uuid4(), type="impeach", target_agent_id=uuid.uuid4(),
                 initiator_id=uuid.uuid4(), declaration_post_id=uuid.uuid4(),
                 status="resolved", votes_for=10, votes_against=3)
    assert e.type == "impeach"
    assert e.status == "resolved"
    assert e.votes_for == 10
    assert e.votes_against == 3


def test_topic_field_roundtrip():
    from app.models.external_topic import Topic
    t = Topic(title="test", injected_count=5)
    assert t.title == "test"
    assert t.injected_count == 5


def test_notification_field_roundtrip():
    from app.models.notification import Notification
    n = Notification(recipient_id=uuid.uuid4(), type="reply",
                     priority="high", is_read=True)
    assert n.type == "reply"
    assert n.priority == "high"
    assert n.is_read is True


def test_post_field_roundtrip():
    from app.models.post import Post
    p = Post(author_id=uuid.uuid4(), title="t", content="c",
             is_hidden=True, is_essential=True, is_pinned=True,
             is_rule_post=True, reply_count=10, like_count=5)
    assert p.is_hidden is True
    assert p.is_essential is True
    assert p.is_pinned is True
    assert p.is_rule_post is True
    assert p.reply_count == 10
    assert p.like_count == 5


def test_reply_field_roundtrip():
    from app.models.post import Reply
    r = Reply(post_id=uuid.uuid4(), author_id=uuid.uuid4(), content="reply")
    assert r.content == "reply"


def test_relationship_field_roundtrip():
    from app.models.relationship import Relationship
    r = Relationship(agent_id=uuid.uuid4(), target_id=uuid.uuid4(),
                     attitude="friendly", intimacy=0.8, is_blocked=True, is_archived=True)
    assert r.attitude == "friendly"
    assert r.intimacy == 0.8
    assert r.is_blocked is True
    assert r.is_archived is True


def test_private_message_field_roundtrip():
    from app.models.social import PrivateMessage
    pm = PrivateMessage(sender_id=uuid.uuid4(), recipient_id=uuid.uuid4(), content="hi",
                        is_read=True)
    assert pm.is_read is True


def test_like_field_roundtrip():
    from app.models.social import Like
    l = Like(agent_id=uuid.uuid4(), post_id=uuid.uuid4())
    assert l.agent_id is not None


def test_follow_field_roundtrip():
    from app.models.social import Follow
    f = Follow(follower_id=uuid.uuid4(), followed_id=uuid.uuid4())
    assert f.follower_id is not None


def test_bookmark_field_roundtrip():
    from app.models.social import Bookmark
    b = Bookmark(agent_id=uuid.uuid4(), post_id=uuid.uuid4())
    assert b.agent_id is not None


def test_slang_field_roundtrip():
    from app.models.slang import Slang
    s = Slang(slug="test", meaning="test_meaning", status="archived")
    assert s.slug == "test"
    assert s.status == "archived"


def test_agent_slang_field_roundtrip():
    from app.models.slang import AgentSlang
    a = AgentSlang(agent_id=uuid.uuid4(), slang_id=1, personal_affinity=0.8)
    assert a.personal_affinity == 0.8


def test_skill_group_field_roundtrip():
    from app.models.skill_group import SkillGroup, SkillGroupMember
    sg = SkillGroup(agent_id=uuid.uuid4(), name="test_group")
    assert sg.name == "test_group"
    sgm = SkillGroupMember(group_id=uuid.uuid4(), skill_id="test_skill")
    assert sgm.skill_id == "test_skill"


# ─── Agent model fields existence ───

def test_agent_model_has_expected_fields():
    from app.models.agent import Agent
    a = Agent(
        nickname="test", age=25, gender="男",
        occupation="工人", income_level="5k-8k", education="本科",
        district="平陵市中心", school_or_company="平陵工厂",
        personality_vector={"peacemaker": 0.8},
        interests={"categories": ["游戏"]},
        life_history=[{"event": "test"}],
        notification_settings={"reply": True},
    )
    assert a.nickname == "test"
    assert a.occupation == "工人"
    assert a.personality_vector == {"peacemaker": 0.8}


def test_seed_topics_structure():
    """SEED_TOPICS 列表中每条数据都有 title 和 category。"""
    from scripts.seed_topics import SEED_TOPICS
    assert isinstance(SEED_TOPICS, list)
    assert len(SEED_TOPICS) > 0
    for item in SEED_TOPICS:
        assert isinstance(item, dict), f"每条应为 dict，实际 {type(item)}"
        assert "title" in item, f"缺少 title: {item}"
        assert "category" in item, f"缺少 category: {item}"
        assert isinstance(item["title"], str) and len(item["title"]) > 0
        assert isinstance(item["category"], str) and len(item["category"]) > 0


def test_seed_topics_covers_all_categories():
    """10 个分类全部覆盖。"""
    from scripts.seed_topics import SEED_TOPICS
    expected = {
        "国际局势", "国内热点", "娱乐新闻", "二次元版", "游戏版",
        "商业版", "当地新闻", "文学版", "科创科普版", "教育版",
    }
    actual = {item["category"] for item in SEED_TOPICS}
    missing = expected - actual
    assert not missing, f"缺少分类: {missing}"
    extra = actual - expected
    assert not extra, f"未知分类: {extra}"


def test_seed_topics_count():
    """种子话题在 20-30 条之间。"""
    from scripts.seed_topics import SEED_TOPICS
    assert 20 <= len(SEED_TOPICS) <= 30, f"应有 20-30 条，实际 {len(SEED_TOPICS)}"


def test_agent_token_limit_override_field():
    """Agent 模型有 token_limit_override 字段，可为 None 或整数值。"""
    from app.models.agent import Agent
    a1 = Agent(nickname="test", age=25, gender="男", token_limit_override=5000)
    assert a1.token_limit_override == 5000
    a2 = Agent(nickname="test2", age=30, gender="女")
    assert a2.token_limit_override is None


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
