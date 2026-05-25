"""Phase 13.2 — schedule template switching after life events."""
import unittest


class TestPickTemplateId(unittest.TestCase):
    """Verify _pick_template_id returns correct templates for all life stages."""

    def _agent(self, age, occupation, boarding=False):
        class FakeAgent:
            pass
        a = FakeAgent()
        a.age = age
        a.occupation = occupation
        a.boarding = boarding
        a.id = "test-id-12345678901234567890"
        return a

    def _pick(self, agent):
        from app.jobs.daily_schedule import _pick_template_id
        return _pick_template_id(agent)

    def test_student_day_under_18(self):
        """Age < 18, non-boarding student → student_day."""
        agent = self._agent(15, "学生", boarding=False)
        self.assertEqual(self._pick(agent), "student_day")

    def test_student_boarding(self):
        """Age < 18, boarding student → student_boarding."""
        agent = self._agent(16, "学生", boarding=True)
        self.assertEqual(self._pick(agent), "student_boarding")

    def test_student_college(self):
        """Age >= 18, student → student_college."""
        agent = self._agent(19, "学生", boarding=True)
        self.assertEqual(self._pick(agent), "student_college")

    def test_unemployed(self):
        """待业 → unemployed."""
        agent = self._agent(30, "待业")
        self.assertEqual(self._pick(agent), "unemployed")

    def test_worker_regular(self):
        """Employed worker → worker_regular or worker_overtime."""
        agent = self._agent(28, "普工")
        tid = self._pick(agent)
        self.assertIn(tid, ["worker_regular", "worker_overtime"])

    def test_freelancer(self):
        """自由职业 → freelancer."""
        agent = self._agent(30, "自由职业")
        self.assertEqual(self._pick(agent), "freelancer")

    def test_initial_employed(self):
        """初入职场 → worker_regular or worker_overtime."""
        agent = self._agent(23, "初入职场")
        tid = self._pick(agent)
        self.assertIn(tid, ["worker_regular", "worker_overtime"])


class TestRegenerateScheduleAfterLifeEvent(unittest.TestCase):
    """Verify _regenerate_schedule is called after key life events in task functions."""

    def test_zhongkao_triggers_regenerate(self):
        """After zhongkao diversion, schedule is regenerated."""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch

        async def _run():
            from app.engine.world_dynamic import world_dynamic_education_task

            agent = MagicMock()
            agent.status = "active"
            agent.birthday = None
            agent.age = 15
            agent.occupation = "学生"
            agent.school_or_company = "平陵实验中学"
            agent.life_history = None
            agent.is_away = False
            agent.district = "RES-001"

            db = MagicMock()
            db.add = MagicMock()
            db.commit = AsyncMock()
            db.execute = AsyncMock()

            # Mock the select result
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = [agent]
            db.execute.return_value = mock_result

            with patch("app.engine.world_dynamic.check_zhongkao_diversion",
                       return_value={"type": "zhongkao", "track": "academic"}), \
                 patch("app.engine.world_dynamic.check_gaokao_outcome", return_value=None), \
                 patch("app.engine.world_dynamic.check_transfer_event", return_value=None), \
                 patch("app.engine.world_dynamic.increment_age_if_birthday", return_value=False), \
                 patch("app.engine.world_dynamic._regenerate_schedule") as mock_regen, \
                 patch("app.engine.world_dynamic.check_incoming_transfer",
                       AsyncMock()), \
                 patch("app.engine.world_dynamic.check_incoming_exam_student",
                       AsyncMock()):
                await world_dynamic_education_task(db, MagicMock())

            mock_regen.assert_called()
            call_args = mock_regen.call_args
            self.assertEqual(call_args[0][0], agent)  # first arg is the agent

        asyncio.run(_run())

    def test_unemployment_triggers_regenerate(self):
        """After unemployment, schedule is regenerated."""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch

        async def _run():
            from app.engine.world_dynamic import world_dynamic_career_task

            agent = MagicMock()
            agent.status = "active"
            agent.occupation = "普工"
            agent.school_or_company = "平陵电子厂"
            agent.is_away = False
            agent.age = 30
            agent.life_history = None
            agent.district = "RES-001"

            db = MagicMock()
            db.add = MagicMock()
            db.commit = AsyncMock()
            db.execute = AsyncMock()

            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = [agent]
            db.execute.return_value = mock_result

            with patch("app.engine.world_dynamic.check_return_to_hometown", return_value=None), \
                 patch("app.engine.world_dynamic.check_initial_employment", return_value=None), \
                 patch("app.engine.world_dynamic.check_job_change", return_value=None), \
                 patch("app.engine.world_dynamic.check_unemployment",
                       return_value={"type": "unemployment", "old_company": "平陵电子厂"}), \
                 patch("app.engine.world_dynamic.check_job_search_for_unemployed", return_value=None), \
                 patch("app.engine.world_dynamic._regenerate_schedule") as mock_regen:
                await world_dynamic_career_task(db, MagicMock())

            mock_regen.assert_called()
            call_args = mock_regen.call_args
            self.assertEqual(call_args[0][0], agent)

        asyncio.run(_run())

    def test_job_search_success_triggers_regenerate(self):
        """After finding a job, schedule is regenerated."""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch

        async def _run():
            from app.engine.world_dynamic import world_dynamic_career_task

            agent = MagicMock()
            agent.status = "active"
            agent.occupation = "待业"
            agent.school_or_company = "待业"
            agent.is_away = False
            agent.age = 30
            agent.life_history = None
            agent.district = "RES-001"

            db = MagicMock()
            db.add = MagicMock()
            db.commit = AsyncMock()
            db.execute = AsyncMock()

            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = [agent]
            db.execute.return_value = mock_result

            with patch("app.engine.world_dynamic.check_return_to_hometown", return_value=None), \
                 patch("app.engine.world_dynamic.check_initial_employment", return_value=None), \
                 patch("app.engine.world_dynamic.check_job_change", return_value=None), \
                 patch("app.engine.world_dynamic.check_unemployment", return_value=None), \
                 patch("app.engine.world_dynamic.check_job_search_for_unemployed",
                       return_value={"type": "job_search", "found": True}), \
                 patch("app.engine.world_dynamic._regenerate_schedule") as mock_regen:
                await world_dynamic_career_task(db, MagicMock())

            mock_regen.assert_called()
            call_args = mock_regen.call_args
            self.assertEqual(call_args[0][0], agent)

        asyncio.run(_run())

    def test_job_search_failure_no_regenerate(self):
        """Failed job search does NOT trigger schedule regeneration."""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch

        async def _run():
            from app.engine.world_dynamic import world_dynamic_career_task

            agent = MagicMock()
            agent.status = "active"
            agent.occupation = "待业"
            agent.school_or_company = "待业"
            agent.is_away = False
            agent.age = 30
            agent.life_history = None
            agent.district = "RES-001"

            db = MagicMock()
            db.add = MagicMock()
            db.commit = AsyncMock()
            db.execute = AsyncMock()

            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = [agent]
            db.execute.return_value = mock_result

            with patch("app.engine.world_dynamic.check_return_to_hometown", return_value=None), \
                 patch("app.engine.world_dynamic.check_initial_employment", return_value=None), \
                 patch("app.engine.world_dynamic.check_job_change", return_value=None), \
                 patch("app.engine.world_dynamic.check_unemployment", return_value=None), \
                 patch("app.engine.world_dynamic.check_job_search_for_unemployed",
                       return_value={"type": "job_search", "found": False}), \
                 patch("app.engine.world_dynamic._regenerate_schedule") as mock_regen:
                await world_dynamic_career_task(db, MagicMock())

            mock_regen.assert_not_called()

        asyncio.run(_run())

    def test_job_hop_triggers_regenerate(self):
        """Job hop (check_job_change with subtype=hop) triggers schedule regeneration."""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch

        async def _run():
            from app.engine.world_dynamic import world_dynamic_career_task

            agent = MagicMock()
            agent.status = "active"
            agent.occupation = "普工"
            agent.school_or_company = "平陵电子厂"
            agent.is_away = False
            agent.age = 30
            agent.life_history = None
            agent.district = "RES-001"

            db = MagicMock()
            db.add = MagicMock()
            db.commit = AsyncMock()
            db.execute = AsyncMock()

            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = [agent]
            db.execute.return_value = mock_result

            with patch("app.engine.world_dynamic.check_return_to_hometown", return_value=None), \
                 patch("app.engine.world_dynamic.check_initial_employment", return_value=None), \
                 patch("app.engine.world_dynamic.check_job_change",
                       return_value={"type": "job_change", "subtype": "hop"}), \
                 patch("app.engine.world_dynamic.check_unemployment", return_value=None), \
                 patch("app.engine.world_dynamic.check_job_search_for_unemployed", return_value=None), \
                 patch("app.engine.world_dynamic._regenerate_schedule") as mock_regen:
                await world_dynamic_career_task(db, MagicMock())

            mock_regen.assert_called()

        asyncio.run(_run())

    def test_internal_transfer_no_regenerate(self):
        """Internal transfer (subtype=internal_transfer) does NOT trigger regenerate."""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch

        async def _run():
            from app.engine.world_dynamic import world_dynamic_career_task

            agent = MagicMock()
            agent.status = "active"
            agent.occupation = "普工"
            agent.school_or_company = "平陵电子厂"
            agent.is_away = False
            agent.age = 30
            agent.life_history = None
            agent.district = "RES-001"

            db = MagicMock()
            db.add = MagicMock()
            db.commit = AsyncMock()
            db.execute = AsyncMock()

            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = [agent]
            db.execute.return_value = mock_result

            with patch("app.engine.world_dynamic.check_return_to_hometown", return_value=None), \
                 patch("app.engine.world_dynamic.check_initial_employment", return_value=None), \
                 patch("app.engine.world_dynamic.check_job_change",
                       return_value={"type": "job_change", "subtype": "internal_transfer"}), \
                 patch("app.engine.world_dynamic.check_unemployment", return_value=None), \
                 patch("app.engine.world_dynamic.check_job_search_for_unemployed", return_value=None), \
                 patch("app.engine.world_dynamic._regenerate_schedule") as mock_regen:
                await world_dynamic_career_task(db, MagicMock())

            mock_regen.assert_not_called()

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
