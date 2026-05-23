"""v0.12.6 TDD: reply willingness curve + notification awakening."""

import math
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import asyncio


# ═══════════════════════════════════════════════════════════════════
# Part A: reply_willingness() pure function
# ═══════════════════════════════════════════════════════════════════

def test_reply_willingness_curve_values():
    """w(n) = n * exp(-0.6*n) * 1.6 produces expected peak-at-round-2 shape."""
    from app.jobs.reply_pipeline import reply_willingness

    vals = [reply_willingness(i) for i in range(5)]  # i = reply_count_in_post

    # Round 1 (n=1): first reply, moderate
    assert 0.7 < vals[0] < 0.95, f"Round 1 should be ~0.88, got {vals[0]}"
    # Round 2 (n=2): peak — "they replied back!"
    assert vals[1] > vals[0], f"Round 2 should exceed Round 1, got {vals[0]} → {vals[1]}"
    assert 0.85 < vals[1] <= 1.0, f"Round 2 should be ~0.96, got {vals[1]}"
    # Round 3 (n=3): declining
    assert vals[2] < vals[1], f"Round 3 should decline from peak, got {vals[1]} → {vals[2]}"
    assert 0.6 < vals[2] < 0.9, f"Round 3 should be ~0.79, got {vals[2]}"
    # Round 4+ (n=4,5): continued decay
    assert vals[3] < vals[2], f"Round 4 should continue decaying, got {vals[2]} → {vals[3]}"
    assert vals[4] < vals[3], f"Round 5 should continue decaying, got {vals[3]} → {vals[4]}"
    # Round 5 is below 0.5
    assert vals[4] < 0.5, f"Round 5 should be < 0.5, got {vals[4]}"

    # Verify exact formula
    for i in range(10):
        n = i + 1
        expected = n * math.exp(-0.6 * n) * 1.6
        assert abs(reply_willingness(i) - expected) < 0.0001


def test_reply_willingness_clamped_to_one():
    """willingness never exceeds 1.0."""
    from app.jobs.reply_pipeline import reply_willingness

    for i in range(20):
        w = reply_willingness(i)
        assert 0.0 <= w <= 1.0, f"w({i}) = {w} out of [0, 1]"


# ═══════════════════════════════════════════════════════════════════
# Part A integration: willingness injected into decide_reply
# ═══════════════════════════════════════════════════════════════════

def test_decide_reply_passes_reply_count_in_post():
    """decide_reply accepts reply_count_in_post and passes it to willingness."""
    from app.jobs.reply_pipeline import decide_reply

    agent = _make_mock_agent()
    post = _make_mock_post()
    db = AsyncMock()
    llm_caller = AsyncMock()
    tracker = MagicMock()
    tracker.compute_saturation.return_value = 0.3

    # Mock skill execution and relationship context
    with patch("app.jobs.reply_pipeline.execute") as mock_exec:
        mock_exec.return_value = MagicMock(
            status="success",
            parsed={"will_reply": True, "reason": "test", "suggested_tone": "友好"},
        )
        with patch("app.jobs.reply_pipeline.build_relationship_context") as mock_rel:
            mock_rel.return_value = {"relationship_attitude": "中立", "relationship_intimacy": 0.3}
            with patch("app.jobs.reply_pipeline.reply_willingness") as mock_w:
                mock_w.return_value = 0.88

                result = asyncio.get_event_loop().run_until_complete(
                    decide_reply(agent, post, "offline", db, llm_caller, tracker,
                                 reply_count_in_post=0)
                )

                # reply_willingness was called with correct round
                mock_w.assert_called_once_with(0)
                assert result.will_reply is True


def test_decide_reply_third_round_lower_willingness():
    """Round 3 willingness is lower than round 1, affecting LLM context."""
    from app.jobs.reply_pipeline import decide_reply, reply_willingness

    # Verify the curve itself: round 3 < round 1
    w1 = reply_willingness(0)  # first reply
    w3 = reply_willingness(2)  # third reply
    assert w3 < w1, f"Round 3 willingness ({w3}) should be < Round 1 ({w1})"


# ═══════════════════════════════════════════════════════════════════
# Part B: notification awakening
# ═══════════════════════════════════════════════════════════════════

def test_collect_reply_notification_post_ids():
    """_step4_notifications collects reply-type notification post_ids."""
    from app.models.notification import Notification
    from app.jobs.agent_lifecycle import _collect_reply_notified_posts

    agent_id = uuid.uuid4()

    notifs = [
        _make_notif("reply", str(uuid.uuid4()), agent_id),
        _make_notif("like", str(uuid.uuid4()), agent_id),
        _make_notif("reply", str(uuid.uuid4()), agent_id),
        _make_notif("mention", str(uuid.uuid4()), agent_id),
    ]

    post_ids = _collect_reply_notified_posts(notifs)
    assert len(post_ids) == 2, f"Expected 2 reply post_ids, got {len(post_ids)}"
    assert all(isinstance(pid, str) for pid in post_ids)


def test_prioritize_notified_posts():
    """Posts with reply notifications are sorted to front of browse queue."""
    from app.jobs.agent_lifecycle import _prioritize_notified_posts

    notified_ids = {str(uuid.uuid4()), str(uuid.uuid4())}

    # Create mock posts — 2 are notified, 2 are not
    posts = []
    for i in range(4):
        p = MagicMock()
        p.id = uuid.uuid4()
        posts.append(p)

    # First 2 should be in notified set
    notified_ids.add(str(posts[0].id))
    notified_ids.add(str(posts[1].id))

    sorted_posts = _prioritize_notified_posts(posts, notified_ids)

    # Notified posts come first
    assert str(sorted_posts[0].id) in notified_ids
    assert str(sorted_posts[1].id) in notified_ids


# ═══════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════

def _make_mock_agent(name="测试Agent"):
    agent = MagicMock()
    agent.id = uuid.uuid4()
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


def _make_mock_post(title="测试帖", content="这是测试内容"):
    post = MagicMock()
    post.id = uuid.uuid4()
    post.title = title
    post.content = content
    post.author_id = uuid.uuid4()
    post.reply_count = 0
    post.is_hidden = False
    author = MagicMock()
    author.nickname = "作者A"
    post.author = author
    bar = MagicMock()
    bar.name = "测试吧"
    post.bar = bar
    return post


def _make_notif(ntype, ref_id, recipient_id):
    n = MagicMock()
    n.type = ntype
    n.reference_id = uuid.UUID(ref_id) if ref_id else None
    n.recipient_id = recipient_id
    n.priority = "medium"
    n.is_read = False
    return n


# ═══════════════════════════════════════════════════════════════════
# Runner
# ═══════════════════════════════════════════════════════════════════

_TESTS = [
    ("reply_willingness curve values", test_reply_willingness_curve_values),
    ("reply_willingness clamped <= 1.0", test_reply_willingness_clamped_to_one),
    ("decide_reply passes reply_count_in_post", test_decide_reply_passes_reply_count_in_post),
    ("decide_reply round 3 < round 1", test_decide_reply_third_round_lower_willingness),
    ("collect reply notification post_ids", test_collect_reply_notification_post_ids),
    ("prioritize notified posts", test_prioritize_notified_posts),
]

if __name__ == "__main__":
    passed = 0
    failed = 0
    for label, fn in _TESTS:
        try:
            fn()
            passed += 1
            print(f"  PASS {label}")
        except Exception:
            failed += 1
            print(f"  FAIL {label}")
            import traceback
            traceback.print_exc()
    print(f"\n{passed} passed, {failed} failed, {len(_TESTS)} total")
    if failed:
        exit(1)
