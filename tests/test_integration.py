"""Integration tests — one core data-flow path per completed Phase.

All tests use a real Docker pgvector database. LLM calls use MockLLM with
custom responses to avoid API costs, but DB reads/writes must be real.

Each test is self-contained: seed → execute → verify → cleanup.

Usage: docker compose exec -T app python tests/test_integration.py
"""
from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.skills.llm_manager import MockLLM
from app.skills.registry import registry
from app.skills.skill_utils import TokenUsage

# Skills must be explicitly loaded outside of main.py
registry.load_all()

_engine = None
_SessionFactory = None
_passed = 0
_failed = 0


def _get_session_factory():
    global _engine, _SessionFactory
    if _SessionFactory is None:
        _engine = create_async_engine(settings.database_url)
        _SessionFactory = async_sessionmaker(_engine)
    return _SessionFactory


def _make_mock_llm(**overrides) -> MockLLM:
    """Create MockLLM with custom responses for skills not in default set."""
    mock = MockLLM()
    for skill_id, response in overrides.items():
        mock.responses[skill_id] = response
    return mock


# ═══════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════

async def _cleanup_agents(db, agent_ids: list[uuid.UUID]) -> None:
    """Delete test agents and their schedules/slangs/notifications/relationships."""
    from app.models.agent import AgentSchedule, AgentDailySchedule
    from app.models.slang import AgentSlang
    from app.models.notification import Notification
    from app.models.relationship import Relationship
    for aid in agent_ids:
        await db.execute(delete(Notification).where(Notification.recipient_id == aid))
        await db.execute(delete(Notification).where(Notification.sender_id == aid))
        await db.execute(delete(Relationship).where(Relationship.agent_id == aid))
        await db.execute(delete(Relationship).where(Relationship.target_id == aid))
        await db.execute(delete(AgentSlang).where(AgentSlang.agent_id == aid))
        await db.execute(delete(AgentDailySchedule).where(AgentDailySchedule.agent_id == aid))
        await db.execute(delete(AgentSchedule).where(AgentSchedule.agent_id == aid))
    from app.models.agent import Agent
    for aid in agent_ids:
        await db.execute(delete(Agent).where(Agent.id == aid))
    await db.commit()


async def _cleanup_posts(db, post_ids: list[uuid.UUID]) -> None:
    from app.models.post import Reply, Post
    for pid in post_ids:
        await db.execute(delete(Reply).where(Reply.post_id == pid))
        await db.execute(delete(Post).where(Post.id == pid))
    await db.commit()


# ═══════════════════════════════════════════════════════════════════
# Phase 4: Agent 创建通路
# ═══════════════════════════════════════════════════════════════════

async def test_integration_agent_creation():
    """create_agent → Agent 入库 → AgentSchedule 入库 → 可查询"""
    from app.engine.agent_factory import create_agent
    from app.models.agent import Agent, AgentSchedule

    sf = _get_session_factory()
    mock = _make_mock_llm(
        slang_learning='{"learned": []}',
        persona_summary='{"persona_prompt": "test persona"}',
    )

    async with sf() as db:
        agent = await create_agent(db, llm_caller=mock.call)
        await db.flush()
        agent_id = agent.id
        await db.commit()

        # verify Agent in DB
        result = await db.execute(select(Agent).where(Agent.id == agent_id))
        found = result.scalar_one_or_none()
        assert found is not None, "Agent not found after create"
        assert found.nickname is not None

        # verify AgentSchedule in DB
        result = await db.execute(
            select(AgentSchedule).where(AgentSchedule.agent_id == agent_id)
        )
        schedule = result.scalar_one_or_none()
        assert schedule is not None, "AgentSchedule not found after create"

        # cleanup
        await _cleanup_agents(db, [agent_id])


# ═══════════════════════════════════════════════════════════════════
# Phase 6: 浏览过滤通路
# ═══════════════════════════════════════════════════════════════════

async def test_integration_browse_pipeline():
    """种子 Agent + Post → run_browse_filter → 返回过滤结果"""
    from app.jobs.browse_filter import run_browse_filter
    from app.models.agent import Agent
    from app.models.post import Post

    sf = _get_session_factory()
    mock = _make_mock_llm(
        topic_similarity='{"similarity_score": 0.8, "is_same_topic": true}',
    )

    async with sf() as db:
        # Seed test agents
        author = Agent(
            nickname="test_author_6", age=30, gender="男",
            chronotype="normal", status="active",
        )
        browser = Agent(
            nickname="test_browser_6", age=25, gender="女",
            chronotype="normal", status="active",
            interests={"categories": ["游戏", "音乐"]},
        )
        db.add_all([author, browser])
        await db.flush()
        author_id = author.id
        browser_id = browser.id

        # Seed test post
        post = Post(
            author_id=author_id, title="测试帖文", content="这是一条测试帖文内容",
            bar_id=None,
        )
        db.add(post)
        await db.flush()
        post_id = post.id

        # Run browse filter (browse_filter does not commit internally)
        results = await run_browse_filter(
            browser, [post], db, mock.call,
        )

        assert len(results) == 1
        assert hasattr(results[0], "passed")
        assert isinstance(results[0].passed, bool)

        # cleanup
        await _cleanup_posts(db, [post_id])
        await _cleanup_agents(db, [author_id, browser_id])


# ═══════════════════════════════════════════════════════════════════
# Phase 7: 回复通路
# ═══════════════════════════════════════════════════════════════════

async def test_integration_reply_pipeline():
    """Agent + Post → generate_reply → Reply 落库 → Post.reply_count 更新"""
    from app.jobs.reply_pipeline import generate_reply, ReplyDecisionResult
    from app.models.agent import Agent
    from app.models.bar import Bar
    from app.models.post import Post, Reply
    from app.models.relationship import Relationship

    sf = _get_session_factory()
    mock = _make_mock_llm(
        reply_generation='{"content": "这是一条集成测试回复，写得很有深度。"}',
    )

    async with sf() as db:
        # Seed test agents
        author = Agent(
            nickname="test_post_author_7", age=28, gender="男",
            chronotype="normal", status="active",
        )
        replier = Agent(
            nickname="test_replier_7", age=25, gender="女",
            chronotype="normal", status="active",
        )
        db.add_all([author, replier])
        await db.flush()
        author_id = author.id
        replier_id = replier.id

        # Seed bar
        bar_name = f"test_bar_7_{uuid.uuid4().hex[:8]}"
        bar = Bar(name=bar_name, description="test", creator_id=author_id, current_owner_id=author_id)
        db.add(bar)
        await db.flush()
        bar_id = bar.id

        # Seed post
        post = Post(
            author_id=author_id, bar_id=bar_id,
            title="测试帖文7", content="有人看吗",
        )
        db.add(post)
        await db.flush()
        post_id = post.id

        # Seed relationship (replier → author)
        rel = Relationship(
            agent_id=replier_id, target_id=author_id,
            intimacy=0.5, attitude="友好",
        )
        db.add(rel)
        await db.flush()

        # Build decision
        decision = ReplyDecisionResult(
            will_reply=True, reason="test", suggested_tone="友好",
            active_persona="default",
        )

        # Preload relationships for reply context
        from app.models.agent import AgentSchedule
        db.add(AgentSchedule(agent_id=replier_id))
        await db.flush()

        # Run reply (generate_reply commits internally)
        result = await generate_reply(replier, post, decision, db, mock.call)
        assert result is not None, "generate_reply returned None"
        assert "content" in result
        assert len(result["content"]) > 0

        # Verify Reply in DB (fresh query after generate_reply's internal commit)
        reply_result = await db.execute(
            select(Reply).where(Reply.post_id == post_id)
        )
        replies = list(reply_result.scalars().all())
        assert len(replies) >= 1, "No Reply found in DB"

        # Verify post.reply_count updated (refresh needed after internal commit)
        await db.refresh(post)
        assert post.reply_count >= 1

        # cleanup (use saved IDs since generate_reply committed internally)
        reply_ids = [r.id for r in replies]
        for rid in reply_ids:
            await db.execute(delete(Reply).where(Reply.id == rid))
        from app.models.bar import AgentBarLevel
        await db.execute(delete(AgentBarLevel).where(AgentBarLevel.bar_id == bar_id))
        await _cleanup_posts(db, [post_id])
        await db.execute(delete(Relationship).where(Relationship.agent_id == replier_id))
        await db.execute(delete(Bar).where(Bar.id == bar_id))
        await _cleanup_agents(db, [author_id, replier_id])


# ═══════════════════════════════════════════════════════════════════
# Phase 8: 世界书通路
# ═══════════════════════════════════════════════════════════════════

async def test_integration_world_book():
    """种子 WorldBookEntry → execute skill → prompt 中包含世界书内容"""
    from app.engine.world_book_engine import assemble_prompt, register_entry
    from app.models.world_book import WorldBookEntry

    sf = _get_session_factory()

    async with sf() as db:
        # Seed a world book entry
        entry_data = {
            "scope": "global",
            "title": "测试世界书条目",
            "content": "平陵市是一个宁静的小城。",
            "trigger_type": "constant",
            "trigger_keys": [],
            "priority": 10,
            "position": "before_char",
            "recursive": False,
        }
        await register_entry(entry_data, db)
        await db.commit()

        # Verify we can query it (fresh query after commit)
        result = await db.execute(
            select(WorldBookEntry).where(WorldBookEntry.title == "测试世界书条目")
        )
        entry = result.scalar_one_or_none()
        assert entry is not None, "WorldBookEntry not found after register"

        # Save entry_id for cleanup
        entry_id = entry.id

        # Test assemble_prompt with matching context
        ctx = {"agent_name": "test", "agent_district": "平陵市"}
        base_prompt = "请介绍一下你自己。"
        assembled = await assemble_prompt(base_prompt, ctx, db)
        assert "平陵市是一个宁静的小城" in assembled

        # cleanup
        await db.execute(
            delete(WorldBookEntry).where(WorldBookEntry.id == entry_id)
        )
        await db.commit()


# ═══════════════════════════════════════════════════════════════════
# Phase 9: 承诺通路
# ═══════════════════════════════════════════════════════════════════

async def test_integration_promise_lifecycle():
    """创建 Promise → check_promise_deadlines → 过期 promise 状态变更"""
    from app.models.agent import Agent
    from app.models.promise import Promise

    sf = _get_session_factory()

    async with sf() as db:
        # Seed agents
        requester = Agent(
            nickname="test_requester_9", age=30, gender="男",
            chronotype="normal", status="active",
        )
        promiser = Agent(
            nickname="test_promiser_9", age=28, gender="女",
            chronotype="normal", status="active",
        )
        db.add_all([requester, promiser])
        await db.flush()
        requester_id = requester.id
        promiser_id = promiser.id

        # Enable promises feature flag
        from app.engine.feature_flags import plugin_registry
        was_enabled = plugin_registry.is_enabled("promises")
        if not was_enabled:
            plugin_registry.toggle("promises", True)

        try:
            # Create a promise that is already overdue
            promise = Promise(
                requester_id=requester_id,
                promiser_id=promiser_id,
                content="我承诺明天回复你的帖子",
                status="pending",
                due_time=datetime.now(timezone.utc) - timedelta(hours=1),
                created_at=datetime.now(timezone.utc) - timedelta(days=1),
            )
            db.add(promise)
            await db.flush()
            promise_id = promise.id
            await db.commit()

            # Run deadline check (check_promise_deadlines_task commits internally)
            from app.jobs.scheduler import check_promise_deadlines_task
            mock = _make_mock_llm()
            await check_promise_deadlines_task(db, mock.call)

            # Re-query promise to get updated status after internal commit
            result = await db.execute(
                select(Promise).where(Promise.id == promise_id)
            )
            updated_promise = result.scalar_one_or_none()
            assert updated_promise is not None, "Promise not found after deadline check"
            assert updated_promise.status == "broken", f"Expected 'broken', got '{updated_promise.status}'"

            # cleanup
            await db.execute(delete(Promise).where(Promise.id == promise_id))
            await _cleanup_agents(db, [requester_id, promiser_id])
        finally:
            if not was_enabled:
                plugin_registry.reset("promises")


# ═══════════════════════════════════════════════════════════════════
# Phase 11: 搜索通路
# ═══════════════════════════════════════════════════════════════════

async def test_integration_search():
    """种子 Topic + Post → execute_external_search + execute_internal_search → 返回结果"""
    from app.engine.search_engine import execute_internal_search, execute_external_search
    from app.models.agent import Agent
    from app.models.external_topic import Topic
    from app.models.post import Post

    sf = _get_session_factory()

    async with sf() as db:
        # Seed external topic
        topic = Topic(
            title="平陵市今日举办文化节",
            summary="平陵市文化节今日开幕，市民踊跃参加。",
            category="当地新闻",
            source="test",
            fetched_at=datetime.now(timezone.utc),
        )
        db.add(topic)
        await db.flush()
        topic_id = topic.id

        # Seed post matching the search
        author = Agent(
            nickname="test_author_11", age=25, gender="男",
            chronotype="normal", status="active",
        )
        db.add(author)
        await db.flush()
        author_id = author.id

        post = Post(
            author_id=author_id,
            title="平陵市文化节体验分享",
            content="今天去了平陵市文化节，感觉很有趣。",
        )
        db.add(post)
        await db.flush()
        post_id = post.id

        # Search (flush only — commit would expire lazy relationships like p.author)
        await db.flush()

        # Search
        ext_results = await execute_external_search("文化节", db)
        int_results = await execute_internal_search("文化节", db)

        assert len(ext_results) >= 1, f"External search returned {len(ext_results)} results, expected >= 1"
        assert ext_results[0]["type"] == "topic"
        assert len(int_results) >= 1, f"Internal search returned {len(int_results)} results, expected >= 1"

        # cleanup
        await _cleanup_posts(db, [post_id])
        await db.execute(delete(Topic).where(Topic.id == topic_id))
        await _cleanup_agents(db, [author_id])


# ═══════════════════════════════════════════════════════════════════
# Phase 12: 用量追踪通路
# ═══════════════════════════════════════════════════════════════════

async def test_integration_usage_tracking():
    """record_token_usage → UsageRecord 落库 → 可查询"""
    from app.engine.usage_tracker import record_token_usage, record_api_call
    from app.models.usage import UsageRecord
    from app.models.agent import Agent

    sf = _get_session_factory()

    async with sf() as db:
        # Seed agent for FK
        agent = Agent(
            nickname="test_agent_12", age=25, gender="男",
            chronotype="normal", status="active",
        )
        db.add(agent)
        await db.flush()
        agent_id = agent.id
        await db.commit()

        # Record token usage
        rec = await record_token_usage(
            db, str(agent_id), "siliconflow", 1500,
            metadata={"model": "test-model", "skill_id": "test_skill"},
        )
        await db.flush()
        rec_id = rec.id

        # Record API call
        rec2 = await record_api_call(db, "bing_search", count=3)
        await db.flush()
        rec2_id = rec2.id
        await db.commit()

        # Verify records in DB (fresh query after commit)
        result = await db.execute(
            select(UsageRecord).where(UsageRecord.id == rec_id)
        )
        found = result.scalar_one_or_none()
        assert found is not None, "UsageRecord not found after write"
        assert found.record_type == "token_usage"
        assert found.quantity == 1500
        assert found.source == "siliconflow"

        result = await db.execute(
            select(UsageRecord).where(UsageRecord.id == rec2_id)
        )
        found2 = result.scalar_one_or_none()
        assert found2 is not None, "API call UsageRecord not found"
        assert found2.record_type == "api_call"
        assert found2.quantity == 3

        # cleanup
        await db.execute(delete(UsageRecord).where(UsageRecord.id.in_([rec_id, rec2_id])))
        await _cleanup_agents(db, [agent_id])
        await db.commit()


# ═══════════════════════════════════════════════════════════════════
# Phase 13-16: 占位 (通路未完成，skip)
# ═══════════════════════════════════════════════════════════════════

# TODO(Phase 13): 论坛管理通路 — 吧务操作 + 封禁 + 申诉流程
# TODO(Phase 14): API + 前端通路 — REST endpoint → DB 读写 → JSON 响应
# TODO(Phase 15): 安全加固通路 — 认证 → 鉴权 → 操作审计
# TODO(Phase 16): 投放与调优通路 — 人类帖子投放 → 参数调优记录


# ═══════════════════════════════════════════════════════════════════
# Runner
# ═══════════════════════════════════════════════════════════════════

_INTEGRATION_TESTS = [
    ("Phase 4: Agent 创建通路", test_integration_agent_creation),
    ("Phase 6: 浏览过滤通路", test_integration_browse_pipeline),
    ("Phase 7: 回复通路", test_integration_reply_pipeline),
    ("Phase 8: 世界书通路", test_integration_world_book),
    ("Phase 9: 承诺通路", test_integration_promise_lifecycle),
    ("Phase 11: 搜索通路", test_integration_search),
    ("Phase 12: 用量追踪通路", test_integration_usage_tracking),
]

if __name__ == "__main__":
    async def _run_all():
        global _passed, _failed
        for label, fn in _INTEGRATION_TESTS:
            try:
                await fn()
                _passed += 1
                print(f"  PASS {label}")
            except Exception:
                _failed += 1
                print(f"  FAIL {label}")
                import traceback
                traceback.print_exc()

        print(f"\n{_passed} passed, {_failed} failed, {len(_INTEGRATION_TESTS)} total")
        if _failed:
            sys.exit(1)

    asyncio.run(_run_all())
