"""Phase 14.3 tests — election, impeachment, voting, resolution."""
from __future__ import annotations

import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch


class TestCreateImpeachment(unittest.TestCase):
    """Tests for create_impeachment."""

    def test_create_impeachment(self):
        from app.engine.election_engine import create_impeachment

        mock_db = AsyncMock()
        bar = MagicMock()
        bar.id = uuid.uuid4()
        initiator = MagicMock()
        initiator.id = uuid.uuid4()
        target = MagicMock()
        target.id = uuid.uuid4()
        post = MagicMock()
        post.id = uuid.uuid4()

        added = []
        mock_db.add = lambda obj: added.append(obj)

        async def _run():
            return await create_impeachment(bar, initiator, target, post, mock_db)

        import asyncio
        election = asyncio.run(_run())

        from app.models.bar import Election
        self.assertIsInstance(election, Election)
        self.assertEqual(election.type, "impeach")
        self.assertEqual(election.status, "active")
        self.assertEqual(election.target_agent_id, target.id)
        self.assertEqual(election.initiator_id, initiator.id)
        self.assertEqual(election.bar_id, bar.id)
        self.assertIsNotNone(election.voting_ends_at)
        self.assertEqual(len(added), 1)


class TestCreateElection(unittest.TestCase):
    """Tests for create_election."""

    def test_create_election(self):
        from app.engine.election_engine import create_election

        mock_db = AsyncMock()
        bar = MagicMock()
        bar.id = uuid.uuid4()

        added = []
        mock_db.add = lambda obj: added.append(obj)

        async def _run():
            return await create_election(bar, mock_db)

        import asyncio
        election = asyncio.run(_run())

        from app.models.bar import Election
        self.assertEqual(election.type, "election")
        self.assertEqual(election.status, "active")
        self.assertIsNotNone(election.voting_ends_at)


class TestCastVote(unittest.TestCase):
    """Tests for cast_vote."""

    def test_cast_vote(self):
        from app.engine.election_engine import cast_vote

        mock_db = AsyncMock()
        voter = MagicMock()
        voter.id = uuid.uuid4()
        voter.nickname = "投票者"

        election = MagicMock()
        election.id = uuid.uuid4()
        election.type = "impeach"
        election.votes_for = 0
        election.votes_against = 0

        async def _run():
            with patch("app.skills.executor.execute") as mock_exec:
                mock_result = MagicMock()
                mock_result.status = "success"
                mock_result.parsed = {"vote": True, "reason": "滥用职权", "confidence": 0.8}
                mock_exec.return_value = mock_result
                return await cast_vote(voter, election, mock_db)

        import asyncio
        result = asyncio.run(_run())
        self.assertTrue(result["voted"])
        self.assertEqual(election.votes_for, 1)


class TestResolveElection(unittest.TestCase):
    """Tests for resolve_election."""

    def test_resolve_impeachment_owner_removed(self):
        from app.engine.election_engine import resolve_election

        mock_db = AsyncMock()
        bar = MagicMock()
        bar.id = uuid.uuid4()
        bar.current_owner_id = uuid.uuid4()

        election = MagicMock()
        election.id = uuid.uuid4()
        election.type = "impeach"
        election.status = "active"
        election.votes_for = 6
        election.votes_against = 3
        election.bar_id = bar.id
        election.target_agent_id = bar.current_owner_id

        call_log = []

        async def mock_remove(owner_id, bar_arg, db_arg):
            call_log.append(("remove", owner_id))

        async def _run():
            with patch("app.engine.election_engine.remove_owner", side_effect=mock_remove):
                return await resolve_election(election, bar, mock_db)

        import asyncio
        result = asyncio.run(_run())
        self.assertEqual(result["result"], "owner_removed")
        self.assertEqual(election.status, "resolved")
        self.assertEqual(len(call_log), 1)

    def test_resolve_impeachment_owner_stays(self):
        from app.engine.election_engine import resolve_election

        mock_db = AsyncMock()
        bar = MagicMock()
        bar.id = uuid.uuid4()

        election = MagicMock()
        election.type = "impeach"
        election.status = "active"
        election.votes_for = 3
        election.votes_against = 5
        election.bar_id = bar.id

        async def _run():
            with patch("app.engine.election_engine.remove_owner") as mock_remove:
                return await resolve_election(election, bar, mock_db)

        import asyncio
        result = asyncio.run(_run())
        self.assertEqual(result["result"], "owner_retained")
        self.assertEqual(election.status, "resolved")

    def test_resolve_election_with_winner(self):
        """Election type: declaration post author becomes new owner."""
        from app.engine.election_engine import resolve_election

        mock_db = AsyncMock()
        bar = MagicMock()
        bar.id = uuid.uuid4()
        bar.current_owner_id = None

        election = MagicMock()
        election.id = uuid.uuid4()
        election.type = "election"
        election.status = "active"
        election.votes_for = 5
        election.votes_against = 1
        election.bar_id = bar.id

        winner_id = uuid.uuid4()
        winner_post = MagicMock()
        winner_post.author_id = winner_id

        mock_post_result = MagicMock()
        mock_post_result.scalars.return_value.first.return_value = winner_post

        mock_db.execute = AsyncMock(return_value=mock_post_result)

        call_log = []

        async def mock_set_new_owner(b, new_id, db_arg):
            call_log.append(("set_new_owner", new_id))

        async def _run():
            with patch("app.engine.election_engine.set_new_owner", side_effect=mock_set_new_owner):
                return await resolve_election(election, bar, mock_db)

        import asyncio
        result = asyncio.run(_run())
        self.assertEqual(result["result"], "owner_elected")
        self.assertEqual(election.status, "resolved")
        self.assertEqual(len(call_log), 1)
        self.assertEqual(call_log[0][1], winner_id)

    def test_resolve_election_no_candidates(self):
        """Election type: no declaration posts → sage managed."""
        from app.engine.election_engine import resolve_election

        mock_db = AsyncMock()
        bar = MagicMock()
        bar.id = uuid.uuid4()
        bar.is_sage_managed = False

        election = MagicMock()
        election.type = "election"
        election.status = "active"
        election.votes_for = 0
        election.votes_against = 0
        election.bar_id = bar.id

        mock_post_result = MagicMock()
        mock_post_result.scalars.return_value.first.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_post_result)

        async def _run():
            return await resolve_election(election, bar, mock_db)

        import asyncio
        result = asyncio.run(_run())
        self.assertEqual(result["result"], "sage_managed")
        self.assertTrue(bar.is_sage_managed)
        self.assertEqual(election.status, "resolved")


class TestStepDownOwner(unittest.TestCase):
    """Tests for step_down_owner."""

    def test_step_down(self):
        from app.engine.election_engine import step_down_owner

        mock_db = AsyncMock()
        owner = MagicMock()
        owner.id = uuid.uuid4()
        owner.nickname = "老吧主"
        bar = MagicMock()
        bar.id = uuid.uuid4()
        bar.current_owner_id = owner.id

        # Mock remove_owner's db.execute query
        owner_member = MagicMock()
        owner_member.role = "owner"
        mock_scalars = MagicMock()
        mock_scalars.first.return_value = owner_member
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute = AsyncMock(return_value=mock_result)

        added = []
        mock_db.add = lambda obj: added.append(obj)

        async def _run():
            with patch("app.engine.election_engine.create_election") as mock_create:
                mock_create.return_value = MagicMock()
                return await step_down_owner(owner, bar, "太累了", mock_db)

        import asyncio
        result = asyncio.run(_run())
        self.assertIsNotNone(result)  # announcement post


class TestRemoveOwner(unittest.TestCase):
    """Tests for remove_owner."""

    def test_remove_owner(self):
        from app.engine.election_engine import remove_owner

        mock_db = AsyncMock()
        bar = MagicMock()
        bar.id = uuid.uuid4()
        bar.current_owner_id = uuid.uuid4()

        owner_member = MagicMock()
        owner_member.role = "owner"
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = owner_member
        mock_db.execute = AsyncMock(return_value=mock_result)

        async def _run():
            return await remove_owner(bar, "违规", mock_db)

        import asyncio
        asyncio.run(_run())
        self.assertEqual(owner_member.role, "member")
        self.assertIsNone(bar.current_owner_id)


class TestSetNewOwner(unittest.TestCase):
    """Tests for set_new_owner."""

    def test_set_new_owner(self):
        from app.engine.election_engine import set_new_owner

        mock_db = AsyncMock()
        bar = MagicMock()
        bar.id = uuid.uuid4()
        bar.current_owner_id = None
        new_owner_id = uuid.uuid4()

        # Existing member
        existing = MagicMock()
        existing.role = "member"
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = existing
        mock_db.execute = AsyncMock(return_value=mock_result)

        async def _run():
            return await set_new_owner(bar, new_owner_id, mock_db)

        import asyncio
        asyncio.run(_run())
        self.assertEqual(existing.role, "owner")
        self.assertEqual(bar.current_owner_id, new_owner_id)


if __name__ == "__main__":
    unittest.main()
