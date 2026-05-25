"""Phase 14.0 tests — bar creation, bar rules, application evaluation."""
from __future__ import annotations

import unittest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch


class TestBarApplicationEvaluation(unittest.TestCase):
    """Tests for evaluate_bar_application_post."""

    def test_evaluate_bar_application_true(self):
        """When LLM says it IS a bar application, return bar info dict."""
        from app.engine.bar_manager_engine import evaluate_bar_application_post

        mock_db = AsyncMock()
        mock_llm = AsyncMock()
        post = MagicMock()
        post.title = "有没有人一起建个【观鸟吧】？"
        post.content = "最近观鸟的人好像不少，我们一起建个观鸟吧！"

        async def _run():
            with patch("app.skills.executor.execute") as mock_exec:
                mock_result = MagicMock()
                mock_result.status = "success"
                mock_result.parsed = {
                    "is_application": True,
                    "bar_name": "观鸟吧",
                    "bar_topic": "观鸟",
                    "description": "鸟类观察与摄影交流",
                    "proposed_rules": "禁止捕鸟、禁止交易",
                    "confidence": 0.85,
                }
                mock_exec.return_value = mock_result
                return await evaluate_bar_application_post(post, mock_db, mock_llm)

        import asyncio
        result = asyncio.run(_run())
        self.assertIsNotNone(result)
        self.assertTrue(result["is_application"])
        self.assertEqual(result["bar_name"], "观鸟吧")
        self.assertEqual(result["bar_topic"], "观鸟")

    def test_evaluate_not_application(self):
        """When LLM says it's NOT a bar application, return None."""
        from app.engine.bar_manager_engine import evaluate_bar_application_post

        mock_db = AsyncMock()
        mock_llm = AsyncMock()
        post = MagicMock()
        post.title = "今天天气真好"
        post.content = "出去走走心情不错"

        async def _run():
            with patch("app.skills.executor.execute") as mock_exec:
                mock_result = MagicMock()
                mock_result.status = "success"
                mock_result.parsed = {"is_application": False, "confidence": 0.1}
                mock_exec.return_value = mock_result
                return await evaluate_bar_application_post(post, mock_db, mock_llm)

        import asyncio
        result = asyncio.run(_run())
        self.assertIsNone(result)

    def test_evaluate_low_confidence(self):
        """When is_application=True but confidence < 0.6, return None."""
        from app.engine.bar_manager_engine import evaluate_bar_application_post

        mock_db = AsyncMock()
        mock_llm = AsyncMock()
        post = MagicMock()
        post.title = "test"
        post.content = "test"

        async def _run():
            with patch("app.skills.executor.execute") as mock_exec:
                mock_result = MagicMock()
                mock_result.status = "success"
                mock_result.parsed = {
                    "is_application": True,
                    "bar_name": "模糊吧",
                    "bar_topic": "不清楚",
                    "description": "",
                    "proposed_rules": "",
                    "confidence": 0.4,
                }
                mock_exec.return_value = mock_result
                return await evaluate_bar_application_post(post, mock_db, mock_llm)

        import asyncio
        result = asyncio.run(_run())
        self.assertIsNone(result)

    def test_skill_call_failure(self):
        """When skill returns error status, return None."""
        from app.engine.bar_manager_engine import evaluate_bar_application_post

        mock_db = AsyncMock()
        mock_llm = AsyncMock()
        post = MagicMock()
        post.title = "test"

        async def _run():
            with patch("app.skills.executor.execute") as mock_exec:
                mock_result = MagicMock()
                mock_result.status = "error"
                mock_result.parsed = {}
                mock_exec.return_value = mock_result
                return await evaluate_bar_application_post(post, mock_db, mock_llm)

        import asyncio
        result = asyncio.run(_run())
        self.assertIsNone(result)


class TestCountApplicationSupporters(unittest.TestCase):
    """Tests for count_application_supporters."""

    def test_enough_supporters(self):
        """5 supporters, 1 opponent → threshold met."""
        from app.engine.bar_manager_engine import count_application_supporters

        mock_db = AsyncMock()
        post = MagicMock()
        post.id = uuid.uuid4()

        mock_replies = []
        for _ in range(5):
            r = MagicMock()
            r.content = "支持建吧！"
            mock_replies.append(r)
        opp = MagicMock()
        opp.content = "反对，没必要"
        mock_replies.append(opp)

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = mock_replies
        mock_db.execute = AsyncMock(return_value=mock_result)

        async def _run():
            return await count_application_supporters(post, mock_db)

        import asyncio
        result = asyncio.run(_run())
        self.assertGreaterEqual(result["supporter_count"], 4)
        self.assertEqual(result["total_replies"], 6)
        self.assertFalse(result["has_serious_opposition"])

    def test_serious_opposition(self):
        """3 strong opponents → has_serious_opposition=True."""
        from app.engine.bar_manager_engine import count_application_supporters

        mock_db = AsyncMock()
        post = MagicMock()
        post.id = uuid.uuid4()

        mock_replies = []
        for _ in range(3):
            r = MagicMock()
            r.content = "支持"
            mock_replies.append(r)
        for _ in range(3):
            r = MagicMock()
            r.content = "坚决反对，这个吧完全没必要存在"
            mock_replies.append(r)

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = mock_replies
        mock_db.execute = AsyncMock(return_value=mock_result)

        async def _run():
            return await count_application_supporters(post, mock_db)

        import asyncio
        result = asyncio.run(_run())
        self.assertEqual(result["supporter_count"], 3)
        self.assertTrue(result["has_serious_opposition"])


class TestCreateBarFromApplication(unittest.TestCase):
    """Tests for create_bar_from_application."""

    def test_create_bar_full_flow(self):
        """Creates Bar, BarMember(owner), BarRule, AgentBarLevel."""
        from app.engine.bar_manager_engine import create_bar_from_application

        mock_db = AsyncMock()
        mock_llm = AsyncMock()
        mock_db.flush = AsyncMock()

        agent = MagicMock()
        agent.id = uuid.uuid4()
        agent.nickname = "观鸟爱好者"

        post = MagicMock()
        post.id = uuid.uuid4()
        post.title = "有没有人一起建个【观鸟吧】？"
        post.bar_id = None

        bar_info = {
            "bar_name": "观鸟吧",
            "bar_topic": "观鸟",
            "description": "鸟类观察与摄影交流",
            "proposed_rules": "禁止捕鸟",
        }

        added_objects = []
        mock_db.add = lambda obj: added_objects.append(obj)

        async def _run():
            with patch("app.skills.executor.execute") as mock_exec:
                mock_result = MagicMock()
                mock_result.status = "success"
                mock_result.parsed = {"rules": "禁止捕鸟、禁止交易"}
                mock_exec.return_value = mock_result
                return await create_bar_from_application(post, agent, bar_info, mock_db, mock_llm)

        import asyncio
        bar = asyncio.run(_run())

        self.assertIsNotNone(bar)
        self.assertEqual(bar.name, "观鸟吧")
        self.assertEqual(bar.creator_id, agent.id)
        self.assertEqual(bar.current_owner_id, agent.id)

        from app.models.bar import Bar, BarMember, BarRule
        from app.models.bar import AgentBarLevel as ABL
        types_found = {type(obj) for obj in added_objects}
        self.assertIn(Bar, types_found)
        self.assertIn(BarMember, types_found)
        self.assertIn(BarRule, types_found)
        self.assertIn(ABL, types_found)

        self.assertIsNotNone(post.bar_id)
        self.assertTrue(post.is_rule_post)
        self.assertTrue(post.is_essential)


class TestReviseBarRules(unittest.TestCase):
    """Tests for revise_bar_rules."""

    def test_revise_rules_archives_old(self):
        """Revising archives old BarRule, creates new with version+1, + announcement post + mod log."""
        from app.engine.bar_manager_engine import revise_bar_rules
        from app.models.post import Post

        mock_db = AsyncMock()
        mock_db.add = MagicMock()  # Not async
        bar = MagicMock()
        bar.id = uuid.uuid4()
        bar.name = "测试吧"
        owner = MagicMock()
        owner.id = uuid.uuid4()

        old_rule = MagicMock()
        old_rule.is_current = True
        old_rule.version = 1
        old_rule.content = "旧吧规内容"

        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = old_rule
        mock_db.execute = AsyncMock(return_value=mock_result)

        async def _run():
            with patch("app.engine.bar_manager_engine.record_mod_action") as mock_record:
                mock_record.return_value = MagicMock()
                return await revise_bar_rules(bar, owner, "更新后的吧规内容", mock_db)

        import asyncio
        new_rule = asyncio.run(_run())

        self.assertIsNotNone(new_rule)
        self.assertFalse(old_rule.is_current)
        self.assertEqual(new_rule.version, 2)
        self.assertTrue(new_rule.is_current)
        self.assertEqual(new_rule.content, "更新后的吧规内容")

        # Verify an announcement Post was created
        db_add_calls = mock_db.add.call_args_list
        posts_added = [c[0][0] for c in db_add_calls if isinstance(c[0][0], Post)]
        self.assertEqual(len(posts_added), 1)
        announcement = posts_added[0]
        self.assertTrue(announcement.is_pinned)
        self.assertIn("吧规修订", announcement.title)
        self.assertIn("v2", announcement.title)
        self.assertEqual(announcement.bar_id, bar.id)
        self.assertEqual(announcement.author_id, owner.id)

    def test_revise_rules_writes_mod_log(self):
        """revise_bar_rules calls record_mod_action with correct args."""
        from app.engine.bar_manager_engine import revise_bar_rules

        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        bar = MagicMock()
        bar.id = uuid.uuid4()
        bar.name = "测试吧"
        owner = MagicMock()
        owner.id = uuid.uuid4()

        old_rule = MagicMock()
        old_rule.is_current = True
        old_rule.version = 1
        old_rule.content = "旧吧规"

        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = old_rule
        mock_db.execute = AsyncMock(return_value=mock_result)

        async def _run():
            with patch("app.engine.bar_manager_engine.record_mod_action") as mock_record:
                mock_record.return_value = MagicMock()
                await revise_bar_rules(bar, owner, "新吧规内容", mock_db)
                return mock_record

        import asyncio
        mock_record = asyncio.run(_run())
        mock_record.assert_called_once()
        call_args = mock_record.call_args[0]
        self.assertEqual(call_args[0], owner.id)  # moderator_id
        self.assertEqual(call_args[1], bar.id)    # bar_id
        self.assertEqual(call_args[2], "revise_rules")  # action


class TestCanCreateBar(unittest.TestCase):
    """Tests for can_create_bar."""

    def test_under_limit(self):
        """Agent with fewer bars than max can create more."""
        from app.engine.bar_manager_engine import can_create_bar

        mock_db = AsyncMock()
        agent_id = uuid.uuid4()
        mock_result = MagicMock()
        mock_result.scalar.return_value = 1
        mock_db.execute = AsyncMock(return_value=mock_result)

        async def _run():
            return await can_create_bar(agent_id, mock_db)

        import asyncio
        result = asyncio.run(_run())
        self.assertTrue(result)

    def test_at_limit(self):
        """Agent at max bars cannot create more."""
        from app.engine.bar_manager_engine import can_create_bar

        mock_db = AsyncMock()
        agent_id = uuid.uuid4()
        mock_result = MagicMock()
        mock_result.scalar.return_value = 3
        mock_db.execute = AsyncMock(return_value=mock_result)

        async def _run():
            return await can_create_bar(agent_id, mock_db)

        import asyncio
        result = asyncio.run(_run())
        self.assertFalse(result)


class TestBarApplicationInterestCheck(unittest.TestCase):
    """P2-2: Interest heat check before bar application LLM evaluation."""

    def setUp(self):
        """Reset cooldowns before each test."""
        from app.jobs import agent_lifecycle
        agent_lifecycle._bar_app_cooldowns.clear()

    def test_bar_application_low_interest_skipped(self):
        """Agent has no recent related posts → LLM not called."""
        from app.jobs.agent_lifecycle import _bar_application_check_hook

        mock_db = AsyncMock()
        mock_llm = AsyncMock()

        agent = MagicMock()
        agent.id = uuid.uuid4()

        post = MagicMock()
        post.title = "有没有人一起建个【观鸟吧】？"
        post.content = "最近观鸟的人好多"
        post.bar_id = None

        async def _run():
            with patch("app.jobs.agent_lifecycle._check_agent_topic_interest", new_callable=AsyncMock) as mock_interest:
                mock_interest.return_value = False
                with patch("app.jobs.agent_lifecycle._extract_topic_keywords", return_value=["观鸟"]):
                    with patch("app.engine.bar_manager_engine.can_create_bar", return_value=True):
                        with patch("app.engine.bar_manager_engine.evaluate_bar_application_post") as mock_eval:
                            with patch("app.engine.feature_flags.plugin_registry.is_enabled", return_value=True):
                                await _bar_application_check_hook(agent, post, None, None, mock_db, mock_llm)
                                mock_eval.assert_not_called()

        import asyncio
        asyncio.run(_run())

    def test_bar_application_high_interest_proceeds(self):
        """Agent has 3+ related recent posts → LLM evaluation proceeds."""
        from app.jobs.agent_lifecycle import _bar_application_check_hook

        mock_db = AsyncMock()
        mock_llm = AsyncMock()

        agent = MagicMock()
        agent.id = uuid.uuid4()

        post = MagicMock()
        post.title = "有没有人一起建个【观鸟吧】？"
        post.content = "最近观鸟的人好多"
        post.bar_id = None

        async def _run():
            with patch("app.jobs.agent_lifecycle._check_agent_topic_interest", new_callable=AsyncMock) as mock_interest:
                mock_interest.return_value = True
                with patch("app.jobs.agent_lifecycle._extract_topic_keywords", return_value=["观鸟"]):
                    with patch("app.engine.bar_manager_engine.can_create_bar", return_value=True):
                        with patch("app.engine.bar_manager_engine.evaluate_bar_application_post") as mock_eval:
                            mock_eval.return_value = None  # Return None to stop after LLM call
                            with patch("app.engine.feature_flags.plugin_registry.is_enabled", return_value=True):
                                await _bar_application_check_hook(agent, post, None, None, mock_db, mock_llm)
                                mock_eval.assert_called_once()

        import asyncio
        asyncio.run(_run())

    def test_bar_application_no_keywords_proceeds(self):
        """When _extract_topic_keywords returns empty list, skip interest check and proceed."""
        from app.jobs.agent_lifecycle import _bar_application_check_hook

        mock_db = AsyncMock()
        mock_llm = AsyncMock()

        agent = MagicMock()
        agent.id = uuid.uuid4()

        post = MagicMock()
        post.title = "hello"
        post.content = "world"
        post.bar_id = None

        async def _run():
            with patch("app.jobs.agent_lifecycle._extract_topic_keywords", return_value=[]):
                with patch("app.engine.bar_manager_engine.can_create_bar", return_value=True):
                    with patch("app.engine.bar_manager_engine.evaluate_bar_application_post") as mock_eval:
                        mock_eval.return_value = None
                        with patch("app.engine.feature_flags.plugin_registry.is_enabled", return_value=True):
                            await _bar_application_check_hook(agent, post, None, None, mock_db, mock_llm)
                            mock_eval.assert_called_once()

        import asyncio
        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
