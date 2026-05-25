"""Phase 14.1 tests — mod actions: hide, pin, essential, ban, appoint sub-mod."""
from __future__ import annotations

import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch


class TestCheckModPermission(unittest.TestCase):
    """Tests for check_mod_permission."""

    def test_owner_can_delete(self):
        from app.engine.bar_mod_engine import check_mod_permission

        mock_db = AsyncMock()
        owner_member = MagicMock()
        owner_member.role = "owner"
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = owner_member
        mock_db.execute = AsyncMock(return_value=mock_result)

        async def _run():
            return await check_mod_permission("agent-1", "bar-1", "delete", mock_db)

        import asyncio
        result = asyncio.run(_run())
        self.assertTrue(result["can_act"])
        self.assertEqual(result["role"], "owner")

    def test_sub_mod_can_hide(self):
        from app.engine.bar_mod_engine import check_mod_permission

        mock_db = AsyncMock()
        member = MagicMock()
        member.role = "sub_mod"
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = member
        mock_db.execute = AsyncMock(return_value=mock_result)

        async def _run():
            return await check_mod_permission("agent-2", "bar-1", "hide", mock_db)

        import asyncio
        result = asyncio.run(_run())
        self.assertTrue(result["can_act"])

    def test_sub_mod_cannot_appoint(self):
        from app.engine.bar_mod_engine import check_mod_permission

        mock_db = AsyncMock()
        member = MagicMock()
        member.role = "sub_mod"
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = member
        mock_db.execute = AsyncMock(return_value=mock_result)

        async def _run():
            return await check_mod_permission("agent-2", "bar-1", "appoint_sub_mod", mock_db)

        import asyncio
        result = asyncio.run(_run())
        self.assertFalse(result["can_act"])

    def test_member_cannot_mod(self):
        from app.engine.bar_mod_engine import check_mod_permission

        mock_db = AsyncMock()
        member = MagicMock()
        member.role = "member"
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = member
        mock_db.execute = AsyncMock(return_value=mock_result)

        async def _run():
            return await check_mod_permission("agent-3", "bar-1", "delete", mock_db)

        import asyncio
        result = asyncio.run(_run())
        self.assertFalse(result["can_act"])

    def test_not_member_at_all(self):
        from app.engine.bar_mod_engine import check_mod_permission

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        async def _run():
            return await check_mod_permission("agent-99", "bar-1", "delete", mock_db)

        import asyncio
        result = asyncio.run(_run())
        self.assertFalse(result["can_act"])


class TestHidePost(unittest.TestCase):
    """Tests for hide_post / unhide_post."""

    def test_hide_post(self):
        from app.engine.bar_mod_engine import hide_post, record_mod_action

        mock_db = AsyncMock()
        moderator = MagicMock()
        moderator.id = uuid.uuid4()
        post = MagicMock()
        post.is_hidden = False
        bar = MagicMock()
        bar.id = uuid.uuid4()

        async def _run():
            with patch("app.engine.bar_mod_engine.record_mod_action") as mock_record:
                mock_log = MagicMock()
                mock_record.return_value = mock_log
                return await hide_post(moderator, post, bar, "违反吧规", mock_db)

        import asyncio
        log = asyncio.run(_run())
        self.assertTrue(post.is_hidden)
        self.assertIsNotNone(log)

    def test_unhide_post(self):
        from app.engine.bar_mod_engine import unhide_post

        mock_db = AsyncMock()
        moderator = MagicMock()
        moderator.id = uuid.uuid4()
        post = MagicMock()
        post.is_hidden = True
        bar = MagicMock()
        bar.id = uuid.uuid4()

        async def _run():
            return await unhide_post(moderator, post, bar, mock_db)

        import asyncio
        asyncio.run(_run())
        self.assertFalse(post.is_hidden)


class TestPinPost(unittest.TestCase):
    """Tests for pin_post / unpin_post."""

    def test_pin_post(self):
        from app.engine.bar_mod_engine import pin_post

        mock_db = AsyncMock()
        moderator = MagicMock()
        moderator.id = uuid.uuid4()
        post = MagicMock()
        post.is_pinned = False
        post.pinned_at = None
        bar = MagicMock()
        bar.id = uuid.uuid4()

        async def _run():
            return await pin_post(moderator, post, bar, mock_db)

        import asyncio
        asyncio.run(_run())
        self.assertTrue(post.is_pinned)
        self.assertIsNotNone(post.pinned_at)

    def test_unpin_post(self):
        from app.engine.bar_mod_engine import unpin_post

        mock_db = AsyncMock()
        moderator = MagicMock()
        moderator.id = uuid.uuid4()
        post = MagicMock()
        post.is_pinned = True
        bar = MagicMock()
        bar.id = uuid.uuid4()

        async def _run():
            return await unpin_post(moderator, post, bar, mock_db)

        import asyncio
        asyncio.run(_run())
        self.assertFalse(post.is_pinned)


class TestEssentialPost(unittest.TestCase):
    """Tests for essential_post / unessential_post."""

    def test_essential_post(self):
        from app.engine.bar_mod_engine import essential_post

        mock_db = AsyncMock()
        moderator = MagicMock()
        moderator.id = uuid.uuid4()
        post = MagicMock()
        post.is_essential = False
        post.essential_at = None
        bar = MagicMock()
        bar.id = uuid.uuid4()

        async def _run():
            return await essential_post(moderator, post, bar, mock_db)

        import asyncio
        asyncio.run(_run())
        self.assertTrue(post.is_essential)
        self.assertIsNotNone(post.essential_at)

    def test_unessential_post(self):
        from app.engine.bar_mod_engine import unessential_post

        mock_db = AsyncMock()
        moderator = MagicMock()
        moderator.id = uuid.uuid4()
        post = MagicMock()
        post.is_essential = True
        bar = MagicMock()
        bar.id = uuid.uuid4()

        async def _run():
            return await unessential_post(moderator, post, bar, mock_db)

        import asyncio
        asyncio.run(_run())
        self.assertFalse(post.is_essential)


class TestBanMember(unittest.TestCase):
    """Tests for ban_member / unban_member."""

    def test_owner_ban_7_days(self):
        from app.engine.bar_mod_engine import ban_member

        mock_db = AsyncMock()
        moderator = MagicMock()
        moderator.id = uuid.uuid4()
        target_id = str(uuid.uuid4())
        bar = MagicMock()
        bar.id = uuid.uuid4()

        target_member = MagicMock()
        target_member.is_muted = False
        target_member.muted_until = None

        mock_scalars = MagicMock()
        mock_scalars.first.return_value = target_member
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute = AsyncMock(return_value=mock_result)

        async def _run():
            with patch("app.engine.bar_mod_engine.check_mod_permission") as mock_perm:
                mock_perm.return_value = {"can_act": True, "role": "owner", "reason": ""}
                with patch("app.engine.bar_mod_engine.record_mod_action") as mock_record:
                    mock_record.return_value = MagicMock()
                    return await ban_member(moderator, target_id, bar, 7, "违规发言", mock_db)

        import asyncio
        result = asyncio.run(_run())
        self.assertIsNotNone(result)

    def test_sub_mod_ban_over_limit_denied(self):
        from app.engine.bar_mod_engine import ban_member

        mock_db = AsyncMock()
        moderator = MagicMock()
        moderator.id = uuid.uuid4()
        target_id = str(uuid.uuid4())
        bar = MagicMock()
        bar.id = uuid.uuid4()

        async def _run():
            with patch("app.engine.bar_mod_engine.check_mod_permission") as mock_perm:
                mock_perm.return_value = {"can_act": True, "role": "sub_mod", "reason": ""}
                return await ban_member(moderator, target_id, bar, 5, "违规", mock_db)

        import asyncio
        result = asyncio.run(_run())
        self.assertIsNone(result)  # denied because > 3 days for sub_mod


class TestAppointSubMod(unittest.TestCase):
    """Tests for appoint_sub_mod / remove_sub_mod."""

    def test_appoint_sub_mod(self):
        from app.engine.bar_mod_engine import appoint_sub_mod

        mock_db = AsyncMock()
        owner = MagicMock()
        owner.id = uuid.uuid4()
        target_id = str(uuid.uuid4())
        bar = MagicMock()
        bar.id = uuid.uuid4()

        target_member = MagicMock()
        target_member.role = "member"
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = target_member
        mock_db.execute = AsyncMock(return_value=mock_result)

        async def _run():
            return await appoint_sub_mod(owner, target_id, bar, mock_db)

        import asyncio
        asyncio.run(_run())
        self.assertEqual(target_member.role, "sub_mod")

    def test_remove_sub_mod(self):
        from app.engine.bar_mod_engine import remove_sub_mod

        mock_db = AsyncMock()
        owner = MagicMock()
        owner.id = uuid.uuid4()
        target_id = str(uuid.uuid4())
        bar = MagicMock()
        bar.id = uuid.uuid4()

        target_member = MagicMock()
        target_member.role = "sub_mod"
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = target_member
        mock_db.execute = AsyncMock(return_value=mock_result)

        async def _run():
            return await remove_sub_mod(owner, target_id, bar, mock_db)

        import asyncio
        asyncio.run(_run())
        self.assertEqual(target_member.role, "member")


class TestRecordModAction(unittest.TestCase):
    """Tests for record_mod_action."""

    def test_record_mod_action_creates_log(self):
        from app.engine.bar_mod_engine import record_mod_action

        mock_db = AsyncMock()
        moderator_id = uuid.uuid4()
        bar_id = uuid.uuid4()
        target_id = uuid.uuid4()

        added = []
        mock_db.add = lambda obj: added.append(obj)

        async def _run():
            return await record_mod_action(
                moderator_id, bar_id, "delete", "post", target_id, "违反吧规", mock_db
            )

        import asyncio
        log = asyncio.run(_run())
        from app.models.bar import BarModLog
        self.assertIsInstance(log, BarModLog)
        self.assertEqual(log.action, "delete")
        self.assertEqual(log.reason, "违反吧规")
        self.assertEqual(log.moderator_id, moderator_id)
        self.assertEqual(log.bar_id, bar_id)
        self.assertEqual(len(added), 1)


if __name__ == "__main__":
    unittest.main()
