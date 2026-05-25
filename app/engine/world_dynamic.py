"""World dynamic engine — education/career mobility, city development, life events.

Drives Agent lifecycle transitions (中考, 高考, 转学, 就业, 调动, 失业)
through scheduled daily tasks registered in the scheduler.
"""
from __future__ import annotations

import random
from datetime import date, datetime, timedelta, timezone
from typing import Callable

import structlog

from app.config import config as yaml_config
from app.models.agent import Agent
from app.world.city_data import (
    get_city_projects_pool,
    get_companies_by_occupation,
    get_infrastructure_events,
    get_institutions_by_age,
)

logger = structlog.get_logger()

# ── Module-level state for city announcements ──
_pending_city_announcements: list[str] = []
_last_city_project_date: date | None = None
_last_infrastructure_date: date | None = None

# Per-agent job search tracking: agent_id_str → last_search_date
_last_job_search_dates: dict[str, date] = {}


# ═══════════════════════════════════════════════════
# Age progression
# ═══════════════════════════════════════════════════

def check_birthday_today(agent: Agent, today: date) -> bool:
    """Check if today is the agent's birthday (month + day match)."""
    if agent.birthday is None:
        return False
    return agent.birthday.month == today.month and agent.birthday.day == today.day


def increment_age_if_birthday(agent: Agent, today: date) -> bool:
    """Increment agent.age by 1 if today is their birthday. Returns True if incremented."""
    if check_birthday_today(agent, today):
        agent.age += 1
        return True
    return False


# ═══════════════════════════════════════════════════
# Education mobility
# ═══════════════════════════════════════════════════

def _is_student(agent: Agent) -> bool:
    return agent.occupation == "学生"


def _school_is_type(agent: Agent, school_types: list[str]) -> bool:
    """Check if agent's current school matches any of the given types."""
    if not agent.school_or_company:
        return False
    institutions = get_institutions_by_age(max(agent.age, 15))
    for inst in institutions:
        if inst["name"] == agent.school_or_company and inst["type"] in school_types:
            return True
    return False


def check_zhongkao_diversion(agent: Agent, today: date) -> dict | None:
    """Check and execute 中考分流 for 15-year-old middle school students in mid-June.

    Returns dict with diversion result or None.
    """
    if agent.age != 15:
        return None
    if not _is_student(agent):
        return None
    if not _school_is_type(agent, ["初中"]):
        return None
    # 中考 window: June 15-17
    if not (today.month == 6 and 15 <= today.day <= 17):
        return None

    # 60% academic → 普通高中, 40% vocational → 职业高中/中专
    academic = random.random() < 0.6
    if academic:
        high_schools = [
            i for i in get_institutions_by_age(15)
            if i["type"] in ("省重点高中", "普通高中")
        ]
        if not high_schools:
            return None
        weights = [h["weight"] for h in high_schools]
        chosen = random.choices(high_schools, weights=weights)[0]
    else:
        vocational = [
            i for i in get_institutions_by_age(15)
            if i["type"] in ("职业高中", "中专")
        ]
        if not vocational:
            return None
        weights = [v["weight"] for v in vocational]
        chosen = random.choices(vocational, weights=weights)[0]

    agent.school_or_company = chosen["name"]
    result = {
        "type": "zhongkao",
        "school_name": chosen["name"],
        "track": "academic" if academic else "vocational",
    }
    inject_life_event(agent, create_life_event(
        agent.age, "教育", f"中考后进入{chosen['name']}", 0.9,
    ))
    return result


def check_gaokao_outcome(agent: Agent, today: date) -> dict | None:
    """Check and execute 高考升学 for 18-year-old high school students in June.

    Outcome weights influenced by: school quality + truthseeker trait + life_history.
    """
    if agent.age != 18:
        return None
    if not _is_student(agent):
        return None
    if not _school_is_type(agent, ["省重点高中", "普通高中"]):
        return None
    # 高考 is June 7-9; check outcome during June 8-30
    if not (today.month == 6 and 8 <= today.day <= 30):
        return None

    # Base weights
    local_college_w = 0.25
    local_vocational_w = 0.25
    away_w = 0.30
    fail_w = 0.20

    # School quality boost
    if _school_is_type(agent, ["省重点高中"]):
        local_college_w += 0.15
        fail_w -= 0.10
        away_w += 0.05

    # Truthseeker boost (high truthseeker → better exam results)
    pv = agent.personality_vector or {}
    truthseeker = float(pv.get("truthseeker", 0))
    if truthseeker > 0.2:
        boost = min(0.15, truthseeker * 0.3)
        local_college_w += boost
        fail_w -= boost * 0.5

    # Life history academic entries
    if agent.life_history:
        academic_neg = sum(
            1 for e in agent.life_history
            if "不及格" in str(e.get("event", "")) or "退学" in str(e.get("event", ""))
        )
        if academic_neg > 0:
            fail_w += 0.10 * academic_neg
            local_college_w -= 0.05 * academic_neg

    # Normalize
    total = local_college_w + local_vocational_w + away_w + fail_w
    local_college_w /= total
    local_vocational_w /= total
    away_w /= total
    fail_w /= total

    r = random.random()
    cumulative = 0
    outcome = None

    cumulative += local_college_w
    if r < cumulative:
        # 本地本科
        colleges = [
            i for i in get_institutions_by_age(18)
            if i["type"] == "本科"
        ]
        if colleges:
            chosen = random.choices(colleges, weights=[c["weight"] for c in colleges])[0]
            agent.school_or_company = chosen["name"]
            agent.district = chosen.get("district", agent.district)
            outcome = {"type": "gaokao", "outcome": "local_college", "school_name": chosen["name"], "is_away": False}
            inject_life_event(agent, create_life_event(agent.age, "教育", f"高考考入{chosen['name']}", 1.0))

    cumulative += local_vocational_w
    if outcome is None and r < cumulative:
        vocational_colleges = [
            i for i in get_institutions_by_age(18)
            if i["type"] == "专科"
        ]
        if vocational_colleges:
            chosen = vocational_colleges[0]
            agent.school_or_company = chosen["name"]
            agent.district = chosen.get("district", agent.district)
            outcome = {"type": "gaokao", "outcome": "local_vocational", "school_name": chosen["name"], "is_away": False}
            inject_life_event(agent, create_life_event(agent.age, "教育", f"高考进入{chosen['name']}", 0.9))

    cumulative += away_w
    if outcome is None and r < cumulative:
        agent.is_away = True
        agent.school_or_company = "外地院校"
        agent.hometown = agent.hometown or "平陵"
        outcome = {"type": "gaokao", "outcome": "away", "school_name": "外地院校", "is_away": True}
        inject_life_event(agent, create_life_event(agent.age, "教育", "高考考入外地院校，离开平陵", 1.0))

    if outcome is None:
        # 落榜 → enter workforce
        agent.occupation = "初入职场"
        agent.school_or_company = None
        outcome = {"type": "gaokao", "outcome": "fail", "school_name": None, "is_away": False}
        inject_life_event(agent, create_life_event(agent.age, "教育", "高考落榜，进入社会就业", 0.9))

    return outcome


def check_transfer_event(agent: Agent, rng: random.Random) -> dict | None:
    """Check for school transfer event (age 12-18 students).

    Annual probability from config; converted to daily check.
    """
    if not (12 <= agent.age <= 18):
        return None
    if not _is_student(agent):
        return None

    annual_prob = float(getattr(yaml_config.world_dynamic, "education_transfer_probability", 0.04))
    daily_prob = annual_prob / 365.0
    if rng.random() >= daily_prob:
        return None

    cross_city_ratio = float(getattr(yaml_config.world_dynamic, "education_transfer_cross_city_ratio", 0.3))
    is_cross_city = rng.random() < cross_city_ratio

    if is_cross_city:
        agent.is_away = True
        agent.hometown = agent.hometown or "平陵"
        agent.school_or_company = "外地学校"
        result = {"type": "transfer", "subtype": "cross_city", "school_name": "外地学校", "is_away": True}
        inject_life_event(agent, create_life_event(
            agent.age, "教育", "因家庭搬迁转学到外地", 0.7,
        ))
    else:
        # Local transfer: pick a different school of the same level
        institutions = get_institutions_by_age(agent.age)
        same_type = [
            i for i in institutions
            if i["name"] != agent.school_or_company
        ]
        if same_type:
            chosen = rng.choice(same_type)
            agent.school_or_company = chosen["name"]
            agent.district = chosen.get("district", agent.district)
            result = {"type": "transfer", "subtype": "local", "school_name": chosen["name"], "is_away": False}
            inject_life_event(agent, create_life_event(
                agent.age, "教育", f"转学到{chosen['name']}", 0.6,
            ))
        else:
            result = None

    return result


async def check_incoming_transfer(db, rng: random.Random, session_factory, llm_caller: Callable) -> Agent | None:
    """Global event: create an agent transferring INTO Pingling from outside.

    Spawned as a student age 12-18 with a Pingling school.
    """
    daily_prob = float(getattr(yaml_config.world_dynamic, "education_incoming_transfer_probability", 0.02))
    if rng.random() >= daily_prob:
        return None

    from app.engine.agent_factory import create_agent

    try:
        agent = await create_agent(
            db, llm_caller=llm_caller,
            manual_input={
                "nickname": "",  # factory will generate via AI
                "age": rng.randint(12, 18),
                "gender": rng.choice(["男", "女"]),
                "interests": [],
                "schedule": {},
            },
        )
        # Post-creation: set world dynamic fields
        agent.hometown = rng.choice(["省城", "隔壁市", "外省某市"])
        agent.is_away = False  # they're coming TO Pingling
        db.add(agent)
        await db.commit()
        logger.info("incoming_transfer_created", agent_id=str(agent.id),
                    age=agent.age, hometown=agent.hometown)
        return agent
    except Exception:
        logger.warning("incoming_transfer_failed")
        return None


async def check_incoming_exam_student(db, rng: random.Random, session_factory, llm_caller: Callable) -> Agent | None:
    """Global event: create an agent who passed gaokao and came TO Pingling for college.

    Only triggered in post-gaokao season (July-September).
    """
    today = date.today()
    if not (7 <= today.month <= 9):
        return None

    daily_prob = 0.01  # lower than transfer — college enrollment is seasonal
    if rng.random() >= daily_prob:
        return None

    from app.engine.agent_factory import create_agent

    try:
        agent = await create_agent(
            db, llm_caller=llm_caller,
            manual_input={
                "nickname": "",
                "age": rng.randint(18, 20),
                "gender": rng.choice(["男", "女"]),
                "interests": [],
                "schedule": {},
            },
        )
        agent.hometown = rng.choice(["省城", "隔壁市某县", "外省"])
        agent.is_away = False
        agent.occupation = "学生"
        # Assign a Pingling college
        colleges = [i for i in get_institutions_by_age(18) if i["type"] in ("本科", "专科")]
        if colleges:
            chosen = rng.choice(colleges)
            agent.school_or_company = chosen["name"]
            agent.district = chosen.get("district", "RES-003")
        db.add(agent)
        await db.commit()
        logger.info("incoming_exam_student_created", agent_id=str(agent.id),
                    age=agent.age, hometown=agent.hometown)
        return agent
    except Exception:
        logger.warning("incoming_exam_student_failed")
        return None


# ═══════════════════════════════════════════════════
# Career mobility
# ═══════════════════════════════════════════════════

def _is_employed(agent: Agent) -> bool:
    return (
        agent.occupation is not None
        and agent.occupation not in ("学生", "待业")
        and agent.school_or_company is not None
        and agent.school_or_company != "待业"
    )


def _is_unemployed(agent: Agent) -> bool:
    return (
        agent.occupation == "待业"
        or agent.school_or_company == "待业"
    )


def check_initial_employment(agent: Agent, rng: random.Random) -> dict | None:
    """Assign initial employment to agents aging into the workforce (22-25)."""
    if not (22 <= agent.age <= 25):
        return None
    # Only for students graduating or "初入职场" without a company
    if agent.occupation not in ("学生", "初入职场"):
        return None
    if agent.school_or_company and agent.school_or_company != "待业":
        # Check if their school is still a school (not a company)
        insts = get_institutions_by_age(agent.age)
        if any(i["name"] == agent.school_or_company for i in insts):
            pass  # still in school — proceed
        else:
            return None  # already has a company

    unemployed_ratio = float(getattr(yaml_config.world_dynamic, "career_unemployed_at_start_ratio", 0.15))
    if rng.random() < unemployed_ratio:
        agent.occupation = "待业"
        agent.school_or_company = "待业"
        agent.income_level = "无收入"
        result = {"type": "employment", "status": "unemployed"}
        inject_life_event(agent, create_life_event(
            agent.age, "职业", "毕业后暂时待业", 0.7,
        ))
    else:
        # Assign occupation from pool
        from app.engine.agent_factory import _OCCUPATION_POOL
        agent.occupation = rng.choice(_OCCUPATION_POOL)
        companies = get_companies_by_occupation(agent.occupation)
        if companies:
            chosen = rng.choice(companies)
            agent.school_or_company = chosen["name"]
            agent.district = chosen.get("district", agent.district)
        else:
            agent.school_or_company = "平陵某单位"
        # Update income/education
        from app.engine.agent_factory import _lookup_income_edu
        agent.income_level, agent.education = _lookup_income_edu(agent.age, agent.occupation)
        result = {"type": "employment", "status": "employed", "occupation": agent.occupation,
                  "company": agent.school_or_company}
        inject_life_event(agent, create_life_event(
            agent.age, "职业", f"入职{agent.school_or_company}，成为{agent.occupation}", 0.8,
        ))

    return result


def check_job_change(agent: Agent, rng: random.Random) -> dict | None:
    """Check for job transfer/change event for employed adults."""
    if not _is_employed(agent):
        return None
    if agent.age < 22:
        return None

    annual_prob = float(getattr(yaml_config.world_dynamic, "career_job_change_probability", 0.07))
    daily_prob = annual_prob / 365.0
    if rng.random() >= daily_prob:
        return None

    # Internal transfer vs. job hop
    if rng.random() < 0.4:
        # Internal transfer — same company
        result = {"type": "job_change", "subtype": "internal_transfer"}
        inject_life_event(agent, create_life_event(
            agent.age, "职业", f"在{agent.school_or_company}内部调动岗位", 0.5,
        ))
    else:
        # Job hop — new company
        companies = get_companies_by_occupation(agent.occupation)
        if companies and agent.school_or_company:
            others = [c for c in companies if c["name"] != agent.school_or_company]
            if others:
                chosen = rng.choice(others)
                old_company = agent.school_or_company
                agent.school_or_company = chosen["name"]
                agent.district = chosen.get("district", agent.district)
                result = {"type": "job_change", "subtype": "hop", "new_company": chosen["name"]}
                inject_life_event(agent, create_life_event(
                    agent.age, "职业", f"从{old_company}跳槽到{chosen['name']}", 0.7,
                ))
            else:
                result = None
        else:
            result = None

    return result


def check_unemployment(agent: Agent, rng: random.Random) -> dict | None:
    """Check for layoff/quitting event for employed adults."""
    if not _is_employed(agent):
        return None

    annual_prob = float(getattr(yaml_config.world_dynamic, "career_unemployment_probability", 0.03))
    daily_prob = annual_prob / 365.0
    if rng.random() >= daily_prob:
        return None

    old_company = agent.school_or_company
    agent.occupation = "待业"
    agent.school_or_company = "待业"
    agent.income_level = "无收入"
    result = {"type": "unemployment", "old_company": old_company}
    inject_life_event(agent, create_life_event(
        agent.age, "职业", f"从{old_company}离职/被裁，目前待业", 0.8,
    ))
    return result


def check_job_search_for_unemployed(agent: Agent, rng: random.Random) -> dict | None:
    """Periodic job search for unemployed agents."""
    if not _is_unemployed(agent):
        return None

    agent_id_str = str(agent.id)
    search_interval = int(getattr(yaml_config.world_dynamic, "career_job_search_interval_days", 30))
    today = date.today()

    last_search = _last_job_search_dates.get(agent_id_str)
    if last_search is not None:
        days_since = (today - last_search).days
        if days_since < search_interval:
            return None

    _last_job_search_dates[agent_id_str] = today

    # 50% chance of finding a job per attempt
    if rng.random() < 0.5:
        from app.engine.agent_factory import _OCCUPATION_POOL
        agent.occupation = rng.choice(_OCCUPATION_POOL)
        companies = get_companies_by_occupation(agent.occupation)
        if companies:
            chosen = rng.choice(companies)
            agent.school_or_company = chosen["name"]
            agent.district = chosen.get("district", agent.district)
        else:
            agent.school_or_company = "平陵某单位"
        from app.engine.agent_factory import _lookup_income_edu
        agent.income_level, agent.education = _lookup_income_edu(agent.age, agent.occupation)
        result = {"type": "job_search", "found": True, "occupation": agent.occupation}
        inject_life_event(agent, create_life_event(
            agent.age, "职业", f"找到新工作：{agent.school_or_company}的{agent.occupation}", 0.8,
        ))
    else:
        result = {"type": "job_search", "found": False}
        inject_life_event(agent, create_life_event(
            agent.age, "职业", "求职未果，继续待业", 0.4,
        ))

    return result


# ═══════════════════════════════════════════════════
# City development
# ═══════════════════════════════════════════════════

def generate_city_project(rng: random.Random) -> str:
    """Generate a single city development announcement from the template pool."""
    pool = get_city_projects_pool()
    if not pool:
        return ""

    template_item = rng.choice(pool)
    template = template_item["template"]

    # Fill template placeholders
    if "{industry}" in template:
        industries = template_item.get("industries", ["制造业"])
        template = template.replace("{industry}", rng.choice(industries))
    if "{number}" in template:
        lo, hi = template_item.get("employee_range", [100, 500])
        template = template.replace("{number}", str(rng.randint(lo, hi)))
    if "{location}" in template:
        locations = template_item.get("locations", ["老城区"])
        template = template.replace("{location}", rng.choice(locations))
    if "{street}" in template:
        streets = template_item.get("streets", ["人民路"])
        template = template.replace("{street}", rng.choice(streets))
    if "{shop_type}" in template:
        shop_types = template_item.get("shop_types", ["小超市"])
        template = template.replace("{shop_type}", rng.choice(shop_types))
    if "{name}" in template:
        names = ["好运来", "万家乐", "聚香阁", "百味轩", "如意坊"]
        template = template.replace("{name}", rng.choice(names))
    if "{origin}" in template:
        origins = template_item.get("origins", ["本地"])
        template = template.replace("{origin}", rng.choice(origins))
    if "{route}" in template and "{new_stop}" in template:
        routes = template_item.get("route_numbers", ["1"])
        template = template.replace("{route}", rng.choice(routes))
        stops = ["火车站", "人民医院", "大学城", "开发区管委会", "平陵广场"]
        template = template.replace("{new_stop}", rng.choice(stops))
        old_stops = ["老汽车站", "文化宫", "农贸市场"]
        template = template.replace("{old_stop}", rng.choice(old_stops))

    return template


def generate_infrastructure_event(rng: random.Random) -> str:
    """Pick a random infrastructure change event."""
    events = get_infrastructure_events()
    return rng.choice(events) if events else ""


def get_pending_city_announcements() -> list[str]:
    """Return and clear pending city announcements (consumer: sage_news_task)."""
    return list(_pending_city_announcements)


def clear_pending_city_announcements() -> None:
    _pending_city_announcements.clear()


# ═══════════════════════════════════════════════════
# Life event helpers
# ═══════════════════════════════════════════════════

def create_life_event(age: int, category: str, event_text: str, impact_weight: float) -> dict:
    """Create a life_history entry dict."""
    return {
        "age": age,
        "category": category,
        "event": event_text,
        "impact_weight": impact_weight,
    }


def inject_life_event(agent: Agent, event: dict) -> None:
    """Append a life event to agent's life_history."""
    if agent.life_history is None:
        agent.life_history = []
    agent.life_history.append(event)


def get_pending_life_events_for_context(agent: Agent, today: date) -> list[str]:
    """Build human-readable life event strings for offline_summary context.

    Checks: birthday, recent life events (within 3 days), away status.
    """
    events: list[str] = []

    # Birthday today
    if check_birthday_today(agent, today):
        events.append(f"今天是你 {agent.age} 岁生日")

    # Recent life history events (last 3 entries within 30 days are likely recent)
    if agent.life_history:
        recent = agent.life_history[-3:]
        for e in recent:
            evt_age = e.get("age", 0)
            evt_text = e.get("event", "")
            if evt_age == agent.age and evt_text:
                events.append(evt_text)

    # Away status
    if agent.is_away:
        hometown = agent.hometown or "平陵"
        events.append(f"你目前人在外地（家乡: {hometown}），但对平陵的社区仍然保持关注")

    # Unemployed status
    if _is_unemployed(agent):
        events.append("你目前待业中，正在寻找新的工作机会")

    return events


# ═══════════════════════════════════════════════════
# Daily task functions (registered in scheduler)
# ═══════════════════════════════════════════════════

async def world_dynamic_education_task(db, llm_caller: Callable) -> None:
    """Daily task: age progression + education mobility checks."""
    from sqlalchemy import select

    result = await db.execute(select(Agent).where(Agent.status == "active"))
    agents = list(result.scalars().all())

    today = date.today()
    rng = random.Random()
    aged = 0
    zhongkao = 0
    gaokao = 0
    transfers = 0

    for agent in agents:
        changed = False

        if increment_age_if_birthday(agent, today):
            inject_life_event(agent, create_life_event(
                agent.age, "生日", f"年满 {agent.age} 岁", 0.5,
            ))
            aged += 1
            changed = True

        zhk = check_zhongkao_diversion(agent, today)
        if zhk:
            zhongkao += 1
            changed = True

        gk = check_gaokao_outcome(agent, today)
        if gk:
            gaokao += 1
            changed = True

        tf = check_transfer_event(agent, rng)
        if tf:
            transfers += 1
            changed = True

        if changed:
            db.add(agent)

    if aged or zhongkao or gaokao or transfers:
        await db.commit()
        logger.info("education_mobility_done", aged=aged, zhongkao=zhongkao,
                    gaokao=gaokao, transfers=transfers, agents=len(agents))

    # Global incoming events (create new agents)
    from app.skills.llm_manager import create_llm_caller as _create_llm
    caller = _create_llm()
    session_factory = None  # The scheduler provides the session; use create_agent differently
    # For incoming transfers, we use the existing db session
    try:
        await check_incoming_transfer(db, rng, session_factory, caller)
    except Exception:
        logger.warning("incoming_transfer_check_failed")
    try:
        await check_incoming_exam_student(db, rng, session_factory, caller)
    except Exception:
        logger.warning("incoming_exam_student_check_failed")


async def world_dynamic_career_task(db, llm_caller: Callable) -> None:
    """Daily task: career mobility checks (employment, job change, unemployment, job search)."""
    from sqlalchemy import select

    result = await db.execute(select(Agent).where(Agent.status == "active"))
    agents = list(result.scalars().all())

    rng = random.Random()
    employed = 0
    job_changes = 0
    unemployed = 0
    job_searches = 0

    for agent in agents:
        changed = False

        emp = check_initial_employment(agent, rng)
        if emp:
            employed += 1
            changed = True

        jc = check_job_change(agent, rng)
        if jc:
            job_changes += 1
            changed = True

        ue = check_unemployment(agent, rng)
        if ue:
            unemployed += 1
            changed = True

        js = check_job_search_for_unemployed(agent, rng)
        if js:
            job_searches += 1
            changed = True

        if changed:
            db.add(agent)

    if employed or job_changes or unemployed or job_searches:
        await db.commit()
        logger.info("career_mobility_done", employed=employed, job_changes=job_changes,
                    unemployed=unemployed, job_searches=job_searches, agents=len(agents))


async def world_dynamic_city_task(db, llm_caller: Callable) -> None:
    """Daily task: generate city development announcements and append to pending queue."""
    global _last_city_project_date, _last_infrastructure_date

    today = date.today()
    rng = random.Random()
    project_interval = int(getattr(yaml_config.world_dynamic, "city_project_interval_days", 20))

    # City project
    if _last_city_project_date is None or (today - _last_city_project_date).days >= project_interval:
        announcement = generate_city_project(rng)
        if announcement:
            _pending_city_announcements.append(announcement)
            _last_city_project_date = today
            logger.info("city_project_generated", announcement=announcement)

    # Infrastructure event (less frequent, ~twice the interval)
    if _last_infrastructure_date is None or (today - _last_infrastructure_date).days >= project_interval * 2:
        event = generate_infrastructure_event(rng)
        if event:
            _pending_city_announcements.append(event)
            _last_infrastructure_date = today
            logger.info("infrastructure_event_generated", event_text=event)
