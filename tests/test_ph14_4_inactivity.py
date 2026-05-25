"""Phase 14.4 tests — owner inactivity check, Sage proxy management."""
from __future__ import annotations

import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch


class TestCheckOwnerInactivity(unittest.TestCase):
    """Tests for check_owner_inactivity."""

    def test_owner_active(self):
        """Owner logged in recently → active."""
        from app.engine.bar_manager_engine import check_owner_inactivity

        mock_db = AsyncMock()
        bar = MagicMock()
        bar.id = uuid.uuid4()
        bar.current_owner_id = uuid.uuid4()

        # Owner was online recently
        owner = MagicMock()
        owner.last_online = datetime.now(timezone.utc) - timedelta(days=1)

        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = owner
        mock_db.execute = AsyncMock(return_value=mock_result)

        async def _run():
            return await check_owner_inactivity(bar, mock_db)

        import asyncio
        result = asyncio.run(_run())
        self.assertEqual(result, "active")

    def test_owner_lost(self):
        """Owner offline 14 days, no mod actions → lost."""
        from app.engine.bar_manager_engine import check_owner_inactivity

        mock_db = AsyncMock()
        bar = MagicMock()
        bar.id = uuid.uuid4()
        bar.current_owner_id = uuid.uuid4()

        # Owner offline for 14 days
        owner = MagicMock()
        owner.last_online = datetime.now(timezone.utc) - timedelta(days=14)

        # First query returns owner, second returns empty mod actions
        mock_result1 = MagicMock()
        mock_result1.scalars.return_value.first.return_value = owner

        mock_result2 = MagicMock()
        mock_result2.scalar.return_value = 0  # no mod actions

        mock_db.execute = AsyncMock()
        mock_db.execute.side_effect = [mock_result1, mock_result2]

        async def _run():
            return await check_owner_inactivity(bar, mock_db)

        import asyncio
        result = asyncio.run(_run())
        self.assertEqual(result, "lost")

    def test_no_owner(self):
        """Bar with no owner → none."""
        from app.engine.bar_manager_engine import check_owner_inactivity

        mock_db = AsyncMock()
        bar = MagicMock()
        bar.id = uuid.uuid4()
        bar.current_owner_id = None

        async def _run():
            return await check_owner_inactivity(bar, mock_db)

        import asyncio
        result = asyncio.run(_run())
        self.assertEqual(result, "none")


class TestSetOwnerLost(unittest.TestCase):
    """Tests for set_owner_lost."""

    def test_set_owner_lost(self):
        from app.engine.bar_manager_engine import set_owner_lost

        mock_db = AsyncMock()
        bar = MagicMock()
        bar.id = uuid.uuid4()
        bar.name = "测试吧"
        bar.current_owner_id = uuid.uuid4()

        owner = MagicMock()
        owner.nickname = "失联吧主"
        mock_scalars = MagicMock()
        mock_scalars.first.return_value = owner
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute = AsyncMock(return_value=mock_result)

        added = []
        mock_db.add = lambda obj: added.append(obj)

        async def _run():
            return await set_owner_lost(bar, mock_db)

        import asyncio
        post = asyncio.run(_run())
        self.assertIsNotNone(post)
        from app.models.post import Post
        self.assertIsInstance(post, Post)
        self.assertIn("失联", post.title)
        self.assertEqual(len(added), 1)


class TestOwnerInactivityGracePeriod(unittest.TestCase):
    """Tests for grace period → auto-election in _check_owner_inactivity_task."""

    def setUp(self):
        from unittest.mock import patch
        self.patch_check = patch(
            "app.engine.bar_manager_engine.check_owner_inactivity"
        )
        self.patch_set_lost = patch(
            "app.engine.bar_manager_engine.set_owner_lost"
        )
        self.patch_create_election = patch(
            "app.engine.election_engine.create_election"
        )
        self.mock_check = self.patch_check.start()
        self.mock_set_lost = self.patch_set_lost.start()
        self.mock_create_election = self.patch_create_election.start()

    def tearDown(self):
        self.patch_check.stop()
        self.patch_set_lost.stop()
        self.patch_create_election.stop()

    def test_grace_not_elapsed_posts_lost(self):
        """Grace period not elapsed → set_owner_lost, not create_election."""
        from app.jobs.scheduler import _check_owner_inactivity_task

        self.mock_check.return_value = "lost"

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock()

        mock_bar = MagicMock()
        mock_bar.id = uuid.uuid4()
        mock_bar.name = "测试吧"
        mock_bar.current_owner_id = uuid.uuid4()

        # Bar query returns one bar
        mock_bar_result = MagicMock()
        mock_bar_result.scalars.return_value.all.return_value = [mock_bar]

        # Lost post query: exists and created recently (grace NOT elapsed)
        recent_post = MagicMock()
        recent_post.created_at = datetime.now(timezone.utc) - timedelta(days=1)

        mock_post_result = MagicMock()
        mock_post_result.scalars.return_value.first.return_value = recent_post

        # Election query: no active election
        mock_election_result = MagicMock()
        mock_election_result.scalars.return_value.first.return_value = None

        mock_db.execute.side_effect = [
            mock_bar_result,
            mock_election_result,
            mock_post_result,
        ]

        async def _run():
            await _check_owner_inactivity_task(mock_db, None)

        import asyncio
        asyncio.run(_run())
        self.mock_set_lost.assert_called_once()
        self.mock_create_election.assert_not_called()

    def test_grace_elapsed_triggers_election(self):
        """Grace period elapsed → create_election, not set_owner_lost."""
        from app.jobs.scheduler import _check_owner_inactivity_task

        self.mock_check.return_value = "lost"

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock()

        mock_bar = MagicMock()
        mock_bar.id = uuid.uuid4()
        mock_bar.name = "测试吧"
        mock_bar.current_owner_id = uuid.uuid4()

        mock_bar_result = MagicMock()
        mock_bar_result.scalars.return_value.all.return_value = [mock_bar]

        # Lost post: created 5 days ago (grace=3, so elapsed)
        old_post = MagicMock()
        old_post.created_at = datetime.now(timezone.utc) - timedelta(days=5)

        mock_post_result = MagicMock()
        mock_post_result.scalars.return_value.first.return_value = old_post

        # No active election
        mock_election_result = MagicMock()
        mock_election_result.scalars.return_value.first.return_value = None

        mock_db.execute.side_effect = [
            mock_bar_result,
            mock_election_result,
            mock_post_result,
        ]

        async def _run():
            await _check_owner_inactivity_task(mock_db, None)

        import asyncio
        asyncio.run(_run())
        self.mock_set_lost.assert_not_called()
        self.mock_create_election.assert_called_once()

    def test_active_election_skips(self):
        """Bar already has active election → skip both lost and election."""
        from app.jobs.scheduler import _check_owner_inactivity_task

        self.mock_check.return_value = "lost"

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock()

        mock_bar = MagicMock()
        mock_bar.id = uuid.uuid4()
        mock_bar.name = "测试吧"
        mock_bar.current_owner_id = uuid.uuid4()

        mock_bar_result = MagicMock()
        mock_bar_result.scalars.return_value.all.return_value = [mock_bar]

        # Active election exists
        active_election = MagicMock()
        mock_election_result = MagicMock()
        mock_election_result.scalars.return_value.first.return_value = active_election

        mock_db.execute.side_effect = [
            mock_bar_result,
            mock_election_result,
        ]

        async def _run():
            await _check_owner_inactivity_task(mock_db, None)

        import asyncio
        asyncio.run(_run())
        self.mock_set_lost.assert_not_called()
        self.mock_create_election.assert_not_called()

    def test_no_lost_post_yet_triggers_lost(self):
        """No prior lost post → create lost announcement (first detection)."""
        from app.jobs.scheduler import _check_owner_inactivity_task

        self.mock_check.return_value = "lost"

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock()

        mock_bar = MagicMock()
        mock_bar.id = uuid.uuid4()
        mock_bar.name = "测试吧"
        mock_bar.current_owner_id = uuid.uuid4()

        mock_bar_result = MagicMock()
        mock_bar_result.scalars.return_value.all.return_value = [mock_bar]

        # No active election
        mock_election_result = MagicMock()
        mock_election_result.scalars.return_value.first.return_value = None

        # No lost post
        mock_post_result = MagicMock()
        mock_post_result.scalars.return_value.first.return_value = None

        mock_db.execute.side_effect = [
            mock_bar_result,
            mock_election_result,
            mock_post_result,
        ]

        async def _run():
            await _check_owner_inactivity_task(mock_db, None)

        import asyncio
        asyncio.run(_run())
        self.mock_set_lost.assert_called_once()
        self.mock_create_election.assert_not_called()


class TestSageProxyManage(unittest.TestCase):
    """Tests for sage_proxy_manage_bar."""

    def test_sage_proxy_manages_bar(self):
        from app.engine.bar_manager_engine import sage_proxy_manage_bar

        mock_db = AsyncMock()
        bar = MagicMock()
        bar.id = uuid.uuid4()
        bar.is_sage_managed = False

        async def _run():
            await sage_proxy_manage_bar(bar, mock_db)
            return bar

        import asyncio
        bar = asyncio.run(_run())
        self.assertTrue(bar.is_sage_managed)


class TestSageProxyModScan(unittest.TestCase):
    """Tests for _sage_proxy_mod_scan daily task."""

    def setUp(self):
        self.patch_hide = patch("app.engine.bar_mod_engine.hide_post")
        self.mock_hide = self.patch_hide.start()

    def tearDown(self):
        self.patch_hide.stop()

    def test_spam_post_gets_hidden(self):
        """Spam post in sage-managed bar → hide_post called."""
        from app.jobs.scheduler import _sage_proxy_mod_scan

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock()

        sage_agent = MagicMock()
        sage_result = MagicMock()
        sage_result.scalars.return_value.first.return_value = sage_agent

        bar = MagicMock()
        bar.id = uuid.uuid4()
        bar.is_sage_managed = True

        spam_post = MagicMock()
        spam_post.title = "免费送钱"
        spam_post.content = "加微信 http://spam.example.com 领取大奖"

        bar_result = MagicMock()
        bar_result.scalars.return_value.all.return_value = [bar]

        post_result = MagicMock()
        post_result.scalars.return_value.all.return_value = [spam_post]

        mock_db.execute.side_effect = [sage_result, bar_result, post_result]

        async def _run():
            await _sage_proxy_mod_scan(mock_db, None)

        import asyncio
        asyncio.run(_run())
        self.mock_hide.assert_called_once()

    def test_clean_post_not_hidden(self):
        """Clean post in sage-managed bar → no action."""
        from app.jobs.scheduler import _sage_proxy_mod_scan

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock()

        sage_agent = MagicMock()
        sage_result = MagicMock()
        sage_result.scalars.return_value.first.return_value = sage_agent

        bar = MagicMock()
        bar.id = uuid.uuid4()
        bar.is_sage_managed = True

        clean_post = MagicMock()
        clean_post.title = "今天天气真好"
        clean_post.content = "大家来讨论一下春天的花吧"

        bar_result = MagicMock()
        bar_result.scalars.return_value.all.return_value = [bar]

        post_result = MagicMock()
        post_result.scalars.return_value.all.return_value = [clean_post]

        mock_db.execute.side_effect = [sage_result, bar_result, post_result]

        async def _run():
            await _sage_proxy_mod_scan(mock_db, None)

        import asyncio
        asyncio.run(_run())
        self.mock_hide.assert_not_called()

    def test_non_sage_managed_skipped(self):
        """Non sage-managed bars → skipped entirely."""
        from app.jobs.scheduler import _sage_proxy_mod_scan

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock()

        sage_agent = MagicMock()
        sage_result = MagicMock()
        sage_result.scalars.return_value.first.return_value = sage_agent

        bar_result = MagicMock()
        bar_result.scalars.return_value.all.return_value = []

        mock_db.execute.side_effect = [sage_result, bar_result]

        async def _run():
            await _sage_proxy_mod_scan(mock_db, None)

        import asyncio
        asyncio.run(_run())
        self.mock_hide.assert_not_called()


if __name__ == "__main__":
    unittest.main()
