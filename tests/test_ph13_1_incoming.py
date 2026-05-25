"""Phase 13.1 — incoming transfer agent school assignment."""
import unittest
import uuid
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch


class TestIncomingTransfer(unittest.TestCase):
    """Verify check_incoming_transfer assigns school/district/boarding."""

    def test_transfer_assigns_location(self):
        """Incoming transfer agent gets school + district + boarding via assign_location."""
        import asyncio

        async def _run():
            from app.engine.world_dynamic import check_incoming_transfer

            fake_agent = MagicMock()
            fake_agent.id = uuid.uuid4()
            fake_agent.age = 14
            fake_agent.school_or_company = None
            fake_agent.district = None
            fake_agent.boarding = None

            async def _fake_create(db, llm_caller=None, manual_input=None):
                return fake_agent

            mock_location = {
                "school_or_company": "平陵实验中学",
                "school_or_company_id": "MID-001",
                "district": "老城区",
                "district_id": "RES-001",
                "boarding": False,
            }

            with patch("app.engine.agent_factory.create_agent", _fake_create), \
                 patch("app.world.location_assigner.assign_location", return_value=mock_location):
                import random as _random
                rng = _random.Random(42)
                db = MagicMock()
                db.commit = AsyncMock()
                # Force probability to trigger
                with patch.object(rng, "random", return_value=0.0):
                    result = await check_incoming_transfer(
                        db, rng, None, MagicMock(),
                    )

            self.assertIsNotNone(result)
            self.assertEqual(fake_agent.school_or_company, "平陵实验中学")
            self.assertEqual(fake_agent.district, "老城区")
            self.assertEqual(fake_agent.boarding, False)
            self.assertIsNotNone(fake_agent.hometown)

        asyncio.run(_run())

    def test_transfer_does_not_trigger_when_probability_not_met(self):
        """When random > daily_prob, returns None without creating agent."""
        import asyncio

        async def _run():
            from app.engine.world_dynamic import check_incoming_transfer
            import random as _random
            rng = _random.Random(42)
            # Force probability to NOT trigger
            with patch.object(rng, "random", return_value=0.5):
                result = await check_incoming_transfer(
                    MagicMock(), rng, None, MagicMock(),
                )
            self.assertIsNone(result)

        asyncio.run(_run())


class TestIncomingExamStudent(unittest.TestCase):
    """Verify check_incoming_exam_student assigns school/district/boarding."""

    def test_exam_student_assigns_location(self):
        """Incoming exam student gets college + district + boarding via assign_location."""
        import asyncio

        async def _run():
            from app.engine.world_dynamic import check_incoming_exam_student

            fake_agent = MagicMock()
            fake_agent.id = uuid.uuid4()
            fake_agent.age = 18
            fake_agent.school_or_company = None
            fake_agent.district = None
            fake_agent.boarding = None

            async def _fake_create(db, llm_caller=None, manual_input=None):
                return fake_agent

            mock_location = {
                "school_or_company": "平陵文理学院",
                "school_or_company_id": "COL-001",
                "district": "大学城区",
                "district_id": "RES-003",
                "boarding": True,
            }

            with patch("app.engine.agent_factory.create_agent", _fake_create), \
                 patch("app.world.location_assigner.assign_location", return_value=mock_location), \
                 patch("app.engine.world_dynamic.date") as mock_date:
                mock_date.today.return_value = date(2026, 7, 15)
                import random as _random
                rng = _random.Random(42)
                db = MagicMock()
                db.commit = AsyncMock()
                with patch.object(rng, "random", return_value=0.0):
                    result = await check_incoming_exam_student(
                        db, rng, None, MagicMock(),
                    )

            self.assertIsNotNone(result)
            self.assertEqual(fake_agent.school_or_company, "平陵文理学院")
            self.assertEqual(fake_agent.district, "大学城区")
            self.assertEqual(fake_agent.boarding, True)
            self.assertEqual(fake_agent.occupation, "学生")
            self.assertFalse(fake_agent.is_away)

        asyncio.run(_run())

    def test_exam_student_outside_season_returns_none(self):
        """Outside July-September, returns None."""
        import asyncio

        async def _run():
            from app.engine.world_dynamic import check_incoming_exam_student
            with patch("app.engine.world_dynamic.date") as mock_date:
                mock_date.today.return_value = date(2026, 3, 1)
                result = await check_incoming_exam_student(
                    MagicMock(), MagicMock(), None, MagicMock(),
                )
            self.assertIsNone(result)

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
