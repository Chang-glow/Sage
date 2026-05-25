"""Phase 13.3 — away agent return to hometown."""
import unittest
import uuid
from datetime import date
from unittest.mock import MagicMock, patch


class TestReturnToHometown(unittest.TestCase):
    """Verify check_return_to_hometown correctly handles away agents returning."""

    def _make_away_agent(self, age=23, occupation="学生", is_away=True, hometown="平陵"):
        class FakeAgent:
            pass
        a = FakeAgent()
        a.id = uuid.uuid4()
        a.age = age
        a.occupation = occupation
        a.is_away = is_away
        a.hometown = hometown
        a.school_or_company = "外地院校"
        a.district = None
        a.life_history = None
        a.income_level = None
        a.education = None
        return a

    def test_away_student_returns(self):
        """is_away student age 22+ returns to Pingling with employment."""
        from app.engine.world_dynamic import check_return_to_hometown
        import random as _random

        agent = self._make_away_agent(age=23, occupation="学生")
        rng = _random.Random(42)

        with patch.object(rng, "random", return_value=0.0), \
             patch("app.engine.world_dynamic.get_companies_by_occupation", return_value=[
                 {"name": "平陵电子厂", "type": "工厂", "district": "RES-004"},
             ]):
            result = check_return_to_hometown(agent, rng)

        self.assertIsNotNone(result)
        self.assertEqual(result["type"], "return_to_hometown")
        self.assertFalse(agent.is_away)
        self.assertIsNotNone(agent.school_or_company)
        self.assertNotEqual(agent.occupation, "学生")
        self.assertGreater(len(agent.life_history or []), 0)

    def test_not_away_returns_none(self):
        """Agent not is_away → None."""
        from app.engine.world_dynamic import check_return_to_hometown
        import random as _random

        agent = self._make_away_agent(age=23, is_away=False)
        rng = _random.Random(42)
        result = check_return_to_hometown(agent, rng)
        self.assertIsNone(result)

    def test_too_young_returns_none(self):
        """Age < 22 → None even if is_away."""
        from app.engine.world_dynamic import check_return_to_hometown
        import random as _random

        agent = self._make_away_agent(age=20, occupation="学生")
        rng = _random.Random(42)
        result = check_return_to_hometown(agent, rng)
        self.assertIsNone(result)

    def test_wrong_occupation_returns_none(self):
        """Non-student/初入职场 away agents don't trigger."""
        from app.engine.world_dynamic import check_return_to_hometown
        import random as _random

        agent = self._make_away_agent(age=25, occupation="普工")
        rng = _random.Random(42)
        result = check_return_to_hometown(agent, rng)
        self.assertIsNone(result)

    def test_low_probability_returns_none(self):
        """When random exceeds daily_prob, returns None."""
        from app.engine.world_dynamic import check_return_to_hometown
        import random as _random

        agent = self._make_away_agent(age=23, occupation="初入职场")
        rng = _random.Random(42)

        with patch.object(rng, "random", return_value=0.9):
            result = check_return_to_hometown(agent, rng)
        self.assertIsNone(result)


class TestReturnToHometownInCareerTask(unittest.TestCase):
    """Verify check_return_to_hometown is called in career task."""

    def test_career_task_calls_return_to_hometown(self):
        """world_dynamic_career_task calls check_return_to_hometown for each agent."""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch

        async def _run():
            from app.engine.world_dynamic import world_dynamic_career_task

            agent = MagicMock()
            agent.status = "active"
            agent.is_away = True
            agent.age = 23
            agent.occupation = "学生"

            db = MagicMock()
            db.add = MagicMock()
            db.commit = AsyncMock()
            db.execute = AsyncMock()

            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = [agent]
            db.execute.return_value = mock_result

            with patch("app.engine.world_dynamic.check_return_to_hometown",
                       return_value={"type": "return_to_hometown"}) as mock_ret, \
                 patch("app.engine.world_dynamic.check_initial_employment", return_value=None), \
                 patch("app.engine.world_dynamic.check_job_change", return_value=None), \
                 patch("app.engine.world_dynamic.check_unemployment", return_value=None), \
                 patch("app.engine.world_dynamic.check_job_search_for_unemployed", return_value=None), \
                 patch("app.engine.world_dynamic._regenerate_schedule", AsyncMock()):
                await world_dynamic_career_task(db, MagicMock())

            mock_ret.assert_called_once()

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
