"""Phase 13 Layer 4 — integration: full lifecycle end-to-end tests."""
import unittest
import uuid
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch


def _make_fake_agent(**kwargs):
    """Build a minimal agent-like object for integration testing."""
    defaults = {
        "id": uuid.uuid4(),
        "nickname": "TestAgent",
        "age": 25,
        "gender": "男",
        "occupation": "普工",
        "education": "高中",
        "district": "RES-001",
        "school_or_company": "平陵电子厂",
        "boarding": False,
        "personality_vector": {
            "peacemaker": 0.1, "instigator": 0.1, "spectator": 0.1,
            "recluse": 0.1, "truthseeker": 0.3, "hothead": 0.1,
            "people_pleaser": 0.1, "cute_pet": 0.15,
        },
        "life_history": [],
        "hometown": None,
        "is_away": False,
        "birthday": None,
        "status": "active",
        "notification_settings": {},
        "stealth_mode": False,
        "interests": [],
    }
    defaults.update(kwargs)

    class FakeAgent:
        pass

    agent = FakeAgent()
    for k, v in defaults.items():
        setattr(agent, k, v)
    return agent


class TestEducationLifecycle(unittest.TestCase):
    """End-to-end education mobility flows."""

    def test_birthday_age_progression_flow(self):
        """Agent birthday=today → education task → age increments."""
        from app.engine.world_dynamic import increment_age_if_birthday, inject_life_event, create_life_event

        agent = _make_fake_agent(age=15, birthday=date(2000, 6, 15), occupation="学生",
                                 school_or_company="平陵实验中学")
        today = date(2026, 6, 15)

        self.assertTrue(increment_age_if_birthday(agent, today))
        self.assertEqual(agent.age, 16)
        inject_life_event(agent, create_life_event(16, "生日", "年满 16 岁", 0.5))
        self.assertTrue(any("16" in str(e.get("event", "")) for e in (agent.life_history or [])))

    def test_zhongkao_diversion_e2e(self):
        """Agent at age 15 in middle school during 中考 window gets assigned a high school."""
        from app.engine.world_dynamic import check_zhongkao_diversion

        institutions = [
            {"name": "平陵实验中学", "type": "初中", "weight": 5},
            {"name": "平陵一中", "type": "省重点高中", "weight": 5},
            {"name": "平陵二中", "type": "普通高中", "weight": 10},
            {"name": "平陵三中", "type": "职业高中", "weight": 8},
        ]
        with patch("app.engine.world_dynamic.get_institutions_by_age", return_value=institutions):
            agent = _make_fake_agent(age=15, occupation="学生", school_or_company="平陵实验中学")
            result = check_zhongkao_diversion(agent, date(2026, 6, 16))
            self.assertIsNotNone(result)
            self.assertEqual(result["type"], "zhongkao")
            self.assertIn(result["track"], ["academic", "vocational"])
            # School should have changed from 初中 to high school
            self.assertNotEqual(agent.school_or_company, "平陵实验中学")

    def test_gaokao_e2e(self):
        """Agent at age 18 graduating high school gets gaokao outcome."""
        from app.engine.world_dynamic import check_gaokao_outcome

        institutions = [
            {"name": "平陵一中", "type": "省重点高中", "weight": 5},
            {"name": "平陵文理学院", "type": "本科", "weight": 15, "district": "RES-003"},
            {"name": "平陵师范学院", "type": "本科", "weight": 10, "district": "RES-003"},
            {"name": "平陵职业技术学院", "type": "专科", "weight": 12, "district": "RES-003"},
        ]
        with patch("app.engine.world_dynamic.get_institutions_by_age", return_value=institutions):
            agent = _make_fake_agent(age=18, occupation="学生", school_or_company="平陵一中")
            result = check_gaokao_outcome(agent, date(2026, 6, 10))
            self.assertIsNotNone(result)
            self.assertEqual(result["type"], "gaokao")
            # Should have a life event recorded
            self.assertGreater(len(agent.life_history or []), 0)
            # Outcome must be valid
            self.assertIn(result["outcome"], ["local_college", "local_vocational", "away", "fail"])


class TestCareerLifecycle(unittest.TestCase):
    """End-to-end career mobility flows."""

    def test_initial_employment_from_student(self):
        """Age 22 student → initial employment assignment."""
        from app.engine.world_dynamic import check_initial_employment
        import random as _random

        with patch("app.engine.world_dynamic.get_institutions_by_age", return_value=[
            {"name": "平陵文理学院", "type": "本科", "weight": 15},
        ]):
            with patch("app.engine.world_dynamic.get_companies_by_occupation", return_value=[
                {"name": "平陵电子厂", "type": "工厂", "district": "RES-004"},
            ]):
                agent = _make_fake_agent(age=22, occupation="学生", school_or_company="平陵文理学院")
                rng = _random.Random(42)
                result = check_initial_employment(agent, rng)
                self.assertIsNotNone(result)
                self.assertEqual(result["type"], "employment")
                self.assertIn(result["status"], ["employed", "unemployed"])

    def test_unemployment_then_job_search(self):
        """Unemployed agent searches and eventually gets a job."""
        from app.engine.world_dynamic import check_job_search_for_unemployed, _last_job_search_dates
        import random as _random

        agent = _make_fake_agent(age=30, occupation="待业", school_or_company="待业")
        # Clear any tracking
        _last_job_search_dates.pop(str(agent.id), None)

        with patch("app.engine.world_dynamic.get_companies_by_occupation", return_value=[
            {"name": "平陵电子厂", "type": "工厂", "district": "RES-004"},
        ]):
            rng = _random.Random(42)
            result = check_job_search_for_unemployed(agent, rng)
            self.assertIsNotNone(result)
            self.assertEqual(result["type"], "job_search")
            if result["found"]:
                self.assertNotEqual(agent.occupation, "待业")
                self.assertIsNotNone(agent.school_or_company)


class TestIntegrationOfflineSummary(unittest.TestCase):
    """Verify offline summary injection pattern."""

    def test_life_events_appear_in_context(self):
        """Verify get_pending_life_events_for_context produces injectable strings."""
        from app.engine.world_dynamic import get_pending_life_events_for_context, inject_life_event, create_life_event

        agent = _make_fake_agent(
            age=25, birthday=date(2000, 6, 15),
            occupation="待业", school_or_company="待业",
        )
        # Inject a recent life event
        inject_life_event(agent, create_life_event(24, "职业", "被裁员", 0.8))

        events = get_pending_life_events_for_context(agent, date(2026, 6, 15))
        self.assertGreater(len(events), 0)
        self.assertTrue(any("生日" in e for e in events))
        self.assertTrue(any("待业" in e for e in events))

    def test_away_agent_context(self):
        """Away agents get hometown context."""
        from app.engine.world_dynamic import get_pending_life_events_for_context

        agent = _make_fake_agent(is_away=True, hometown="省城")
        events = get_pending_life_events_for_context(agent, date(2026, 6, 15))
        self.assertTrue(any("外地" in e for e in events))
        self.assertTrue(any("省城" in e for e in events))


if __name__ == "__main__":
    unittest.main()
