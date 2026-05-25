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


if __name__ == "__main__":
    unittest.main()
