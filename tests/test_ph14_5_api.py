"""Phase 14.5 tests — bar management REST API endpoints."""
from __future__ import annotations

import unittest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException


class TestBarQueryEndpoints(unittest.TestCase):
    """Tests for GET bar endpoints."""

    def test_list_bars_empty(self):
        from app.api.bars import list_bars

        mock_db = AsyncMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute = AsyncMock(return_value=mock_result)

        async def _run():
            return await list_bars(db=mock_db)

        import asyncio
        result = asyncio.run(_run())
        self.assertEqual(result, {"bars": []})

    def test_get_bar_not_found(self):
        from app.api.bars import get_bar

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        async def _run():
            return await get_bar(bar_id=uuid.uuid4(), db=mock_db)

        import asyncio
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(_run())
        self.assertEqual(ctx.exception.status_code, 404)

    def test_list_bar_members(self):
        from app.api.bars import list_bar_members

        mock_db = AsyncMock()
        member = MagicMock()
        member.id = uuid.uuid4()
        member.agent_id = uuid.uuid4()
        member.role = "owner"
        member.is_muted = False
        member.muted_until = None
        member.joined_at = None

        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [member]
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute = AsyncMock(return_value=mock_result)

        async def _run():
            return await list_bar_members(bar_id=uuid.uuid4(), db=mock_db)

        import asyncio
        result = asyncio.run(_run())
        self.assertEqual(len(result["members"]), 1)
        self.assertEqual(result["members"][0]["role"], "owner")


class TestModActionEndpoints(unittest.TestCase):
    """Tests for POST mod action endpoints."""

    def test_hide_post_moderator_not_found(self):
        from app.api.bars import api_hide_post, ModActionRequest

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        req = ModActionRequest(moderator_id=str(uuid.uuid4()), reason="test")

        async def _run():
            return await api_hide_post(
                bar_id=uuid.uuid4(), post_id=uuid.uuid4(), req=req, db=mock_db
            )

        import asyncio
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(_run())
        self.assertEqual(ctx.exception.status_code, 404)
        self.assertIn("Moderator", ctx.exception.detail)

    def test_hide_post_invalid_moderator_id(self):
        from app.api.bars import api_hide_post, ModActionRequest

        mock_db = AsyncMock()
        req = ModActionRequest(moderator_id="not-a-uuid", reason="test")

        async def _run():
            return await api_hide_post(
                bar_id=uuid.uuid4(), post_id=uuid.uuid4(), req=req, db=mock_db
            )

        import asyncio
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(_run())
        self.assertEqual(ctx.exception.status_code, 422)


class TestBanEndpoint(unittest.TestCase):
    """Tests for ban/unban endpoints."""

    def test_ban_moderator_not_found(self):
        from app.api.bars import api_ban_member, BanRequest

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        req = BanRequest(moderator_id=str(uuid.uuid4()), days=3, reason="spam")

        async def _run():
            return await api_ban_member(
                bar_id=uuid.uuid4(), agent_id=uuid.uuid4(), req=req, db=mock_db
            )

        import asyncio
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(_run())
        self.assertEqual(ctx.exception.status_code, 404)

    def test_ban_bar_not_found(self):
        from app.api.bars import api_ban_member, BanRequest

        mock_db = AsyncMock()
        moderator = MagicMock()
        mock_result1 = MagicMock()
        mock_result1.scalars.return_value.first.return_value = moderator

        mock_result2 = MagicMock()
        mock_result2.scalars.return_value.first.return_value = None

        mock_db.execute = AsyncMock()
        mock_db.execute.side_effect = [mock_result1, mock_result2]

        req = BanRequest(moderator_id=str(uuid.uuid4()), days=3, reason="spam")

        async def _run():
            return await api_ban_member(
                bar_id=uuid.uuid4(), agent_id=uuid.uuid4(), req=req, db=mock_db
            )

        import asyncio
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(_run())
        self.assertEqual(ctx.exception.status_code, 404)
        self.assertIn("Bar", ctx.exception.detail)


class TestAppealEndpoints(unittest.TestCase):
    """Tests for appeal endpoints."""

    def test_submit_appeal_agent_not_found(self):
        from app.api.bars import api_submit_appeal, AppealRequest

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        req = AppealRequest(agent_id=str(uuid.uuid4()), appeal_reason="unfair")

        async def _run():
            return await api_submit_appeal(log_id=uuid.uuid4(), req=req, db=mock_db)

        import asyncio
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(_run())
        self.assertEqual(ctx.exception.status_code, 404)

    def test_resolve_appeal_invalid_resolution(self):
        from app.api.bars import api_resolve_appeal, ResolveAppealRequest

        mock_db = AsyncMock()
        req = ResolveAppealRequest(
            moderator_id=str(uuid.uuid4()), resolution="invalid_value"
        )

        async def _run():
            return await api_resolve_appeal(log_id=uuid.uuid4(), req=req, db=mock_db)

        import asyncio
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(_run())
        self.assertEqual(ctx.exception.status_code, 422)

    def test_resolve_appeal_moderator_not_found(self):
        from app.api.bars import api_resolve_appeal, ResolveAppealRequest

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        req = ResolveAppealRequest(moderator_id=str(uuid.uuid4()), resolution="upheld")

        async def _run():
            return await api_resolve_appeal(log_id=uuid.uuid4(), req=req, db=mock_db)

        import asyncio
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(_run())
        self.assertEqual(ctx.exception.status_code, 404)


class TestElectionEndpoints(unittest.TestCase):
    """Tests for election endpoints."""

    def test_cast_vote_voter_not_found(self):
        from app.api.bars import api_cast_vote, VoteRequest

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        req = VoteRequest(voter_id=str(uuid.uuid4()))

        async def _run():
            return await api_cast_vote(
                bar_id=uuid.uuid4(), election_id=uuid.uuid4(), req=req, db=mock_db
            )

        import asyncio
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(_run())
        self.assertEqual(ctx.exception.status_code, 404)

    def test_step_down_not_owner(self):
        from app.api.bars import api_step_down, StepDownRequest

        bar = MagicMock()
        bar.current_owner_id = uuid.uuid4()

        owner = MagicMock()
        owner.id = uuid.uuid4()  # different from bar.current_owner_id

        mock_db = AsyncMock()
        mock_result1 = MagicMock()
        mock_result1.scalars.return_value.first.return_value = owner
        mock_result2 = MagicMock()
        mock_result2.scalars.return_value.first.return_value = bar
        mock_db.execute = AsyncMock()
        mock_db.execute.side_effect = [mock_result1, mock_result2]

        req = StepDownRequest(owner_id=str(owner.id), reason="tired")

        async def _run():
            return await api_step_down(bar_id=uuid.uuid4(), req=req, db=mock_db)

        import asyncio
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(_run())
        self.assertEqual(ctx.exception.status_code, 403)


class TestReviseRulesEndpoint(unittest.TestCase):
    """Tests for bar rules revision."""

    def test_revise_rules_owner_not_found(self):
        from app.api.bars import api_revise_rules, ReviseRulesRequest

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        req = ReviseRulesRequest(owner_id=str(uuid.uuid4()), content="new rules")

        async def _run():
            return await api_revise_rules(bar_id=uuid.uuid4(), req=req, db=mock_db)

        import asyncio
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(_run())
        self.assertEqual(ctx.exception.status_code, 404)


class TestRequestModels(unittest.TestCase):
    """Tests for Pydantic request model validation."""

    def test_ban_request_valid(self):
        from app.api.bars import BanRequest
        req = BanRequest(moderator_id=str(uuid.uuid4()), days=3, reason="spam")
        self.assertEqual(req.days, 3)

    def test_ban_request_days_too_low(self):
        from app.api.bars import BanRequest
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            BanRequest(moderator_id=str(uuid.uuid4()), days=0, reason="spam")

    def test_ban_request_days_too_high(self):
        from app.api.bars import BanRequest
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            BanRequest(moderator_id=str(uuid.uuid4()), days=8, reason="spam")

    def test_appeal_request(self):
        from app.api.bars import AppealRequest
        req = AppealRequest(agent_id=str(uuid.uuid4()), appeal_reason="unfair ban")
        self.assertEqual(req.appeal_reason, "unfair ban")

    def test_resolve_appeal_request(self):
        from app.api.bars import ResolveAppealRequest
        req = ResolveAppealRequest(moderator_id=str(uuid.uuid4()), resolution="upheld")
        self.assertEqual(req.resolution, "upheld")


if __name__ == "__main__":
    unittest.main()
