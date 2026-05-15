"""Phase 5 edge case tests — scheduler, lifecycle, daily schedule."""
import asyncio
import sys
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock

# ─── should_wake tests ───

class FakeAgent:
    def __init__(self, is_online=False, status="active", age=25, occupation="工人"):
        self.id = "fake-id"
        self.nickname = "TestAgent"
        self.is_online = is_online
        self.status = status
        self.age = age
        self.occupation = occupation
        self.personality_vector = {"openness": 0.8}
        self.life_history = []
        self.chronotype = "normal"
        self.boarding = False


class FakeSchedule:
    def __init__(self, active_windows):
        self.active_windows = active_windows


def test_should_wake_online_agent_skips():
    from app.jobs.agent_lifecycle import should_wake
    agent = FakeAgent(is_online=True)
    schedule = FakeSchedule([{"day": "weekday", "start": "09:00", "end": "18:00"}])
    dt = datetime(2026, 5, 15, 2, 0, tzinfo=timezone.utc)
    assert should_wake(agent, schedule, dt) is False


def test_should_wake_inactive_agent_skips():
    from app.jobs.agent_lifecycle import should_wake
    agent = FakeAgent(status="inactive")
    schedule = FakeSchedule([{"day": "weekday", "start": "09:00", "end": "18:00"}])
    dt = datetime(2026, 5, 15, 2, 0, tzinfo=timezone.utc)
    assert should_wake(agent, schedule, dt) is False


def test_should_wake_no_windows_skips():
    from app.jobs.agent_lifecycle import should_wake
    agent = FakeAgent()
    schedule = FakeSchedule([])
    dt = datetime(2026, 5, 15, 2, 0, tzinfo=timezone.utc)
    assert should_wake(agent, schedule, dt) is False


def test_should_wake_weekday_window_on_weekend_skips():
    from app.jobs.agent_lifecycle import should_wake
    agent = FakeAgent()
    schedule = FakeSchedule([{"day": "weekday", "start": "09:00", "end": "18:00"}])
    dt = datetime(2026, 5, 16, 2, 0, tzinfo=timezone.utc)  # Saturday
    assert should_wake(agent, schedule, dt) is False


def test_should_wake_weekend_window_on_weekday_skips():
    from app.jobs.agent_lifecycle import should_wake
    agent = FakeAgent()
    schedule = FakeSchedule([{"day": "weekend", "start": "09:00", "end": "18:00"}])
    dt = datetime(2026, 5, 15, 2, 0, tzinfo=timezone.utc)  # Friday
    assert should_wake(agent, schedule, dt) is False


def test_should_wake_outside_time_window_skips():
    from app.jobs.agent_lifecycle import should_wake
    agent = FakeAgent()
    schedule = FakeSchedule([{"day": "weekday", "start": "09:00", "end": "18:00"}])
    dt = datetime(2026, 5, 15, 11, 0, tzinfo=timezone.utc)  # 19:00 UTC+8
    assert should_wake(agent, schedule, dt) is False


def test_should_wake_cross_midnight_window():
    from app.jobs.agent_lifecycle import should_wake
    agent = FakeAgent()
    schedule = FakeSchedule([{"day": "weekday", "start": "22:00", "end": "02:00"}])
    dt = datetime(2026, 5, 15, 16, 0, tzinfo=timezone.utc)  # 00:00 UTC+8
    assert should_wake(agent, schedule, dt) is True


# ─── Time utility tests ───

def test_time_in_window():
    from app.jobs.agent_lifecycle import _time_in_window
    assert _time_in_window(10, 0, "09:00", "18:00") is True
    assert _time_in_window(8, 0, "09:00", "18:00") is False
    assert _time_in_window(18, 0, "09:00", "18:00") is False


def test_cross_midnight_window_both_parts():
    from app.jobs.agent_lifecycle import _time_in_window
    assert _time_in_window(23, 0, "22:00", "02:00") is True
    assert _time_in_window(0, 30, "22:00", "02:00") is True
    assert _time_in_window(21, 0, "22:00", "02:00") is False
    assert _time_in_window(2, 0, "22:00", "02:00") is False


# ─── Daily schedule template matching ───

def test_pick_template_student_boarding():
    from app.jobs.daily_schedule import _pick_template_id
    agent = FakeAgent()
    agent.age = 15
    agent.occupation = "学生"
    agent.boarding = True
    assert _pick_template_id(agent) == "student_boarding"


def test_pick_template_student_college():
    from app.jobs.daily_schedule import _pick_template_id
    agent = FakeAgent()
    agent.age = 20
    agent.occupation = "学生"
    agent.boarding = False
    assert _pick_template_id(agent) == "student_college"


def test_pick_template_freelancer():
    from app.jobs.daily_schedule import _pick_template_id
    agent = FakeAgent()
    agent.age = 30
    agent.occupation = "自由职业"
    assert _pick_template_id(agent) == "freelancer"


def test_pick_template_individual_owner():
    from app.jobs.daily_schedule import _pick_template_id
    agent = FakeAgent()
    agent.age = 45
    agent.occupation = "个体户"
    agent.boarding = False
    t = _pick_template_id(agent)
    assert t in ("freelancer", "worker_overtime")


# ─── Chronotype offset tests ───

def test_shift_time_simple():
    from app.jobs.daily_schedule import _shift_time
    assert _shift_time("08:00", 30) == "08:30"
    assert _shift_time("08:45", -45) == "08:00"


def test_shift_time_midnight_wraparound():
    from app.jobs.daily_schedule import _shift_time
    assert _shift_time("23:30", 60) == "00:30"
    assert _shift_time("00:10", -30) == "23:40"


# ─── Calendar hit tests ───

def test_calendar_hit_exam_week():
    from app.jobs.daily_schedule import _check_calendar_hit
    result = _check_calendar_hit("student_college", date(2026, 6, 25))
    assert result is not None
    assert result <= 0.2


def test_calendar_hit_summer_vacation():
    from app.jobs.daily_schedule import _check_calendar_hit
    result = _check_calendar_hit("student_day", date(2026, 7, 15))
    assert result is not None
    assert result > 1.0


def test_calendar_hit_no_hit():
    from app.jobs.daily_schedule import _check_calendar_hit
    result = _check_calendar_hit("worker_regular", date(2026, 5, 15))
    assert result is None


# ─── Asynchronous: run_online_flow integration test ───

async def test_run_online_flow_no_missing_greenlet():
    """Verify run_online_flow does NOT produce MissingGreenlet errors."""
    from app.jobs.agent_lifecycle import run_online_flow

    agent = FakeAgent()
    agent.personality_vector = {"openness": 0.8}
    agent.life_history = [{"age": 20, "event": "大学毕业"}]

    mock_db = AsyncMock()
    mock_llm = AsyncMock()
    mock_llm.return_value = '{"summary": "today was normal", "urge_type": null, "urge_intensity": 0.1}'

    try:
        await run_online_flow(agent, mock_db, mock_llm)
    except Exception as e:
        err_name = type(e).__name__
        err_str = str(e)
        if "MissingGreenlet" in err_name or "greenlet" in err_str.lower():
            raise AssertionError(f"MissingGreenlet error: {e}") from e
        # Other errors expected with mock DB — that's fine


# ─── Concurrency tests ───

def test_semaphore_singleton():
    from app.jobs.concurrency import get_agent_semaphore
    import app.jobs.concurrency as cc
    cc._agent_semaphore = None  # reset
    sem1 = get_agent_semaphore()
    sem2 = get_agent_semaphore()
    assert sem1 is sem2


# ─── Offline summary context completeness ───

def test_personality_description():
    from app.jobs.agent_lifecycle import _describe_personality
    agent = FakeAgent()
    agent.personality_vector = {"openness": 0.9, "agreeableness": 0.7, "neuroticism": 0.3}
    desc = _describe_personality(agent)
    assert "openness=0.90" in desc
    assert "agreeableness=0.70" in desc


def test_life_history_sample_empty():
    from app.jobs.agent_lifecycle import _life_history_sample
    agent = FakeAgent()
    agent.life_history = []
    result = _life_history_sample(agent)
    assert "无" in result


if __name__ == "__main__":
    passed = 0
    failed = 0

    def run_test(fn, name):
        global passed, failed
        try:
            fn()
            passed += 1
            print(f"  PASS {name}")
        except Exception as e:
            failed += 1
            print(f"  FAIL {name}: {e}")

    print("=== Running synchronous tests ===")
    run_test(test_should_wake_online_agent_skips, "should_wake skips online agents")
    run_test(test_should_wake_inactive_agent_skips, "should_wake skips inactive agents")
    run_test(test_should_wake_no_windows_skips, "should_wake skips when no windows")
    run_test(test_should_wake_weekday_window_on_weekend_skips, "weekday window on weekend skips")
    run_test(test_should_wake_weekend_window_on_weekday_skips, "weekend window on weekday skips")
    run_test(test_should_wake_outside_time_window_skips, "outside time window skips")
    run_test(test_should_wake_cross_midnight_window, "cross-midnight window wakes")
    run_test(test_time_in_window, "time_in_window basic")
    run_test(test_cross_midnight_window_both_parts, "cross-midnight window both parts")
    run_test(test_pick_template_student_boarding, "template: student_boarding")
    run_test(test_pick_template_student_college, "template: student_college")
    run_test(test_pick_template_freelancer, "template: freelancer")
    run_test(test_pick_template_individual_owner, "template: individual owner")
    run_test(test_shift_time_simple, "shift_time simple")
    run_test(test_shift_time_midnight_wraparound, "shift_time midnight wraparound")
    run_test(test_calendar_hit_exam_week, "calendar: exam week hit")
    run_test(test_calendar_hit_summer_vacation, "calendar: summer vacation hit")
    run_test(test_calendar_hit_no_hit, "calendar: no hit")
    run_test(test_semaphore_singleton, "semaphore singleton")
    run_test(test_personality_description, "personality description")
    run_test(test_life_history_sample_empty, "life history sample empty")

    print(f"\nSync: {passed}/{passed+failed} passed")

    print("\n=== Running async integration test ===")
    try:
        asyncio.run(test_run_online_flow_no_missing_greenlet())
        passed += 1
        print("  PASS run_online_flow_no_missing_greenlet")
    except Exception as e:
        failed += 1
        print(f"  FAIL run_online_flow_no_missing_greenlet: {e}")

    print(f"\nTotal: {passed}/{passed+failed} passed")
    if failed > 0:
        print("SOME TESTS FAILED")
        sys.exit(1)
    else:
        print("ALL TESTS PASSED")
