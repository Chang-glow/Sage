"""Phase 14.2 tests — appeal system: submit, resolve, detection."""
from __future__ import annotations

import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch


class TestSubmitAppeal(unittest.TestCase):
    """Tests for submit_appeal."""

    def test_submit_appeal_within_window(self):
        """Appeal within 7 days of mod action should succeed."""
        from app.engine.bar_mod_engine import submit_appeal

        mock_db = AsyncMock()
        agent = MagicMock()
        agent.id = uuid.uuid4()

        mod_log_id = uuid.uuid4()

        # Mock mod log with recent creation date
        mod_log = MagicMock()
        mod_log.id = mod_log_id
        mod_log.is_appealed = False
        mod_log.created_at = datetime.now(timezone.utc) - timedelta(days=2)
        mod_log.bar_id = uuid.uuid4()
        mod_log.action = "hide"
        mod_log.reason = "违反吧规"
        mod_log.moderator_id = uuid.uuid4()

        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = mod_log
        mock_db.execute = AsyncMock(return_value=mock_result)

        # Track added objects
        added = []
        mock_db.add = lambda obj: added.append(obj)

        async def _run():
            with patch("app.engine.bar_mod_engine.generate_appeal_post") as mock_gen:
                mock_gen.return_value = MagicMock()
                return await submit_appeal(agent, mod_log_id, "我不同意删除", mock_db)

        import asyncio
        result = asyncio.run(_run())
        self.assertIsNotNone(result)
        self.assertTrue(mod_log.is_appealed)
        self.assertEqual(mod_log.appeal_reason, "我不同意删除")
        self.assertEqual(mod_log.appeal_status, "pending")

    def test_submit_appeal_past_window(self):
        """Appeal after 7 days should be rejected."""
        from app.engine.bar_mod_engine import submit_appeal

        mock_db = AsyncMock()
        agent = MagicMock()
        agent.id = uuid.uuid4()

        mod_log = MagicMock()
        mod_log.created_at = datetime.now(timezone.utc) - timedelta(days=10)
        mod_log.is_appealed = False

        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = mod_log
        mock_db.execute = AsyncMock(return_value=mock_result)

        async def _run():
            return await submit_appeal(agent, uuid.uuid4(), "申诉", mock_db)

        import asyncio
        result = asyncio.run(_run())
        self.assertIsNone(result)

    def test_submit_appeal_already_appealed(self):
        """Cannot appeal an already-appealed action."""
        from app.engine.bar_mod_engine import submit_appeal

        mock_db = AsyncMock()
        agent = MagicMock()
        agent.id = uuid.uuid4()

        mod_log = MagicMock()
        mod_log.created_at = datetime.now(timezone.utc) - timedelta(days=1)
        mod_log.is_appealed = True

        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = mod_log
        mock_db.execute = AsyncMock(return_value=mock_result)

        async def _run():
            return await submit_appeal(agent, uuid.uuid4(), "再申诉一次", mock_db)

        import asyncio
        result = asyncio.run(_run())
        self.assertIsNone(result)


class TestResolveAppeal(unittest.TestCase):
    """Tests for resolve_appeal."""

    def test_resolve_appeal_upheld_restores_post(self):
        """When appeal upheld, restore hidden post."""
        from app.engine.bar_mod_engine import resolve_appeal

        mock_db = AsyncMock()
        moderator = MagicMock()
        moderator.id = uuid.uuid4()

        mod_log_id = uuid.uuid4()
        post = MagicMock()
        post.is_hidden = True

        mod_log = MagicMock()
        mod_log.id = mod_log_id
        mod_log.action = "hide"
        mod_log.target_type = "post"
        mod_log.target_id = post.id
        mod_log.appeal_status = "pending"
        mod_log.bar_id = uuid.uuid4()

        mock_result = MagicMock()
        mock_result.scalars.return_value.first.side_effect = [mod_log, post]
        mock_db.execute = AsyncMock(return_value=mock_result)

        async def _run():
            return await resolve_appeal(moderator, mod_log_id, "upheld", mock_db)

        import asyncio
        result = asyncio.run(_run())
        self.assertIsNotNone(result)
        self.assertEqual(mod_log.appeal_status, "upheld")
        self.assertFalse(post.is_hidden)

    def test_resolve_appeal_rejected(self):
        """When appeal rejected, keep everything as-is."""
        from app.engine.bar_mod_engine import resolve_appeal

        mock_db = AsyncMock()
        moderator = MagicMock()
        moderator.id = uuid.uuid4()

        mod_log = MagicMock()
        mod_log.id = uuid.uuid4()
        mod_log.action = "hide"
        mod_log.appeal_status = "pending"

        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = mod_log
        mock_db.execute = AsyncMock(return_value=mock_result)

        async def _run():
            return await resolve_appeal(moderator, mod_log.id, "rejected", mock_db)

        import asyncio
        result = asyncio.run(_run())
        self.assertIsNotNone(result)
        self.assertEqual(mod_log.appeal_status, "rejected")


class TestGenerateAppealPost(unittest.TestCase):
    """Tests for generate_appeal_post."""

    def test_generate_appeal_post(self):
        """Auto-generate a public appeal announcement post."""
        from app.engine.bar_mod_engine import generate_appeal_post

        mock_db = AsyncMock()
        added = []
        mock_db.add = lambda obj: added.append(obj)

        mod_log = MagicMock()
        mod_log.id = uuid.uuid4()
        mod_log.action = "hide"
        mod_log.reason = "违反吧规"
        mod_log.moderator_id = uuid.uuid4()
        mod_log.bar_id = uuid.uuid4()

        agent = MagicMock()
        agent.id = uuid.uuid4()
        agent.nickname = "申诉者"

        moderator = MagicMock()
        moderator.nickname = "吧主"
        moderator.id = mod_log.moderator_id

        async def _run():
            with patch("app.engine.bar_mod_engine.select") as mock_select:
                mock_agent_result = MagicMock()
                mock_agent_result.scalars.return_value.first.return_value = moderator
                mock_db.execute = AsyncMock(return_value=mock_agent_result)
                return await generate_appeal_post(mod_log, agent, "我不服", mock_db)

        import asyncio
        post = asyncio.run(_run())
        self.assertIsNotNone(post)
        from app.models.post import Post
        self.assertIsInstance(post, Post)
        self.assertEqual(post.bar_id, mod_log.bar_id)
        self.assertIn("申诉", post.title)
        self.assertIn("我不服", post.content)
        self.assertEqual(len(added), 1)


class TestAppealPostProtection(unittest.TestCase):
    """Tests that appeal posts cannot be deleted by moderators."""

    def test_cannot_hide_appeal_post(self):
        """hide_post on a post with is_rule_post=True should return None."""
        import asyncio
        from app.engine.bar_mod_engine import hide_post

        mock_db = AsyncMock()
        mock_db.add = MagicMock()

        moderator = MagicMock()
        moderator.id = uuid.uuid4()
        post = MagicMock()
        post.is_rule_post = True
        bar = MagicMock()
        bar.id = uuid.uuid4()

        async def _run():
            return await hide_post(moderator, post, bar, "测试删除", mock_db)

        result = asyncio.run(_run())
        self.assertIsNone(result)

    def test_can_hide_normal_post(self):
        """hide_post on a normal post (is_rule_post=False) should succeed."""
        import asyncio
        from app.engine.bar_mod_engine import hide_post

        mock_db = AsyncMock()
        mock_db.add = MagicMock()

        moderator = MagicMock()
        moderator.id = uuid.uuid4()
        post = MagicMock()
        post.is_rule_post = False
        bar = MagicMock()
        bar.id = uuid.uuid4()

        async def _run():
            return await hide_post(moderator, post, bar, "测试删除", mock_db)

        result = asyncio.run(_run())
        self.assertIsNotNone(result)
        self.assertTrue(post.is_hidden)

    def test_generate_appeal_post_sets_rule_post(self):
        """generate_appeal_post should set is_rule_post=True on the post."""
        import asyncio
        from unittest.mock import patch
        from app.engine.bar_mod_engine import generate_appeal_post
        from app.models.post import Post

        mock_db = AsyncMock()
        added = []
        mock_db.add = lambda obj: added.append(obj)

        mod_log = MagicMock()
        mod_log.id = uuid.uuid4()
        mod_log.action = "hide"
        mod_log.reason = "违反吧规"
        mod_log.moderator_id = uuid.uuid4()
        mod_log.bar_id = uuid.uuid4()

        agent = MagicMock()
        agent.id = uuid.uuid4()
        agent.nickname = "申诉者"

        moderator = MagicMock()
        moderator.nickname = "吧主"
        moderator.id = mod_log.moderator_id

        mock_agent_result = MagicMock()
        mock_agent_result.scalars.return_value.first.return_value = moderator

        async def _run():
            mock_db.execute = AsyncMock(return_value=mock_agent_result)
            return await generate_appeal_post(mod_log, agent, "我不服", mock_db)

        post = asyncio.run(_run())
        self.assertIsInstance(post, Post)
        self.assertTrue(post.is_rule_post, "Appeal post should have is_rule_post=True")


if __name__ == "__main__":
    unittest.main()
