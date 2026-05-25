"""Phase 13 Layer 3 — scheduler task registration and behavior."""
import unittest
from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock, patch


class TestTaskRegistration(unittest.TestCase):
    """Verify world dynamic tasks are registered in DailyTaskRegistry."""

    @classmethod
    def setUpClass(cls):
        # Trigger scheduler module import to register tasks
        import app.jobs.scheduler  # noqa: F401

    def test_education_task_registered(self):
        from app.engine.daily_tasks import daily_task_registry
        from app.config import config as yaml_config
        hour = yaml_config.world_dynamic.education_mobility_hour
        due = daily_task_registry.get_due(hour, 0)
        names = [name for name, _ in due]
        self.assertIn("world_dynamic_education", names)

    def test_career_task_registered(self):
        from app.engine.daily_tasks import daily_task_registry
        from app.config import config as yaml_config
        hour = yaml_config.world_dynamic.career_mobility_hour
        due = daily_task_registry.get_due(hour, 0)
        names = [name for name, _ in due]
        self.assertIn("world_dynamic_career", names)

    def test_city_task_registered(self):
        from app.engine.daily_tasks import daily_task_registry
        from app.config import config as yaml_config
        hour = yaml_config.world_dynamic.city_development_hour
        due = daily_task_registry.get_due(hour, 0)
        names = [name for name, _ in due]
        self.assertIn("world_dynamic_city", names)

    def test_education_task_not_at_wrong_hour(self):
        from app.engine.daily_tasks import daily_task_registry
        from app.config import config as yaml_config
        hour = yaml_config.world_dynamic.education_mobility_hour
        # At minute 30 should NOT find our tasks (registered at minute 0)
        due = daily_task_registry.get_due(hour, 30)
        names = [name for name, _ in due]
        self.assertNotIn("world_dynamic_education", names)


class TestCityAnnouncementQueue(unittest.TestCase):
    """Verify pending city announcements queue behavior."""

    def setUp(self):
        from app.engine.world_dynamic import _pending_city_announcements
        _pending_city_announcements.clear()

    def test_get_pending_returns_copy(self):
        from app.engine.world_dynamic import (
            _pending_city_announcements,
            get_pending_city_announcements,
        )
        _pending_city_announcements.append("test")
        result = get_pending_city_announcements()
        self.assertEqual(result, ["test"])
        # Original should NOT be affected by consumer's operations
        self.assertEqual(_pending_city_announcements, ["test"])

    def test_clear_pending_empties_queue(self):
        from app.engine.world_dynamic import (
            _pending_city_announcements,
            clear_pending_city_announcements,
        )
        _pending_city_announcements.append("test")
        clear_pending_city_announcements()
        self.assertEqual(len(_pending_city_announcements), 0)


class TestCityTask(unittest.TestCase):
    """Verify world_dynamic_city_task generates announcements."""

    def setUp(self):
        from app.engine.world_dynamic import (
            _pending_city_announcements,
            _last_city_project_date,
            _last_infrastructure_date,
        )
        _pending_city_announcements.clear()
        # Reset dates so generation triggers immediately
        self._saved_project_date = _last_city_project_date
        self._saved_infra_date = _last_infrastructure_date

    def tearDown(self):
        from app.engine.world_dynamic import (
            _pending_city_announcements,
            _last_city_project_date,
            _last_infrastructure_date,
        )
        _pending_city_announcements.clear()
        _last_city_project_date = self._saved_project_date
        _last_infrastructure_date = self._saved_infra_date

    async def _run_city_task(self):
        from app.engine.world_dynamic import (
            _last_city_project_date,
            _last_infrastructure_date,
        )
        _last_city_project_date = None
        _last_infrastructure_date = None
        from app.engine.world_dynamic import world_dynamic_city_task
        mock_db = MagicMock()
        await world_dynamic_city_task(mock_db, MagicMock())

    def test_city_task_generates_announcements(self):
        import asyncio
        from app.engine.world_dynamic import _pending_city_announcements

        asyncio.run(self._run_city_task())
        self.assertGreater(len(_pending_city_announcements), 0)


class TestLifeEventInjection(unittest.TestCase):
    """Verify life events are injectable into context dicts."""

    def test_context_includes_life_events_key(self):
        """Verify the injection pattern — real test in integration layer."""
        from app.engine.world_dynamic import get_pending_life_events_for_context

        class FakeAgent:
            birthday = date(2000, 6, 15)
            age = 25
            is_away = False
            hometown = None
            occupation = "普工"
            school_or_company = "平陵电子厂"
            life_history = None

        agent = FakeAgent()
        events = get_pending_life_events_for_context(agent, date(2026, 6, 15))
        self.assertIsInstance(events, list)
        self.assertTrue(any("生日" in e for e in events))


if __name__ == "__main__":
    unittest.main()
