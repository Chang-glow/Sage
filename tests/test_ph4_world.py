"""Phase 4 tests — city_data, location_assigner, agent_factory, API validation."""
import random
import sys
from unittest.mock import MagicMock, patch


# ═══════════════════════════════════════════════════
# city_data.py — filtering functions (monkeypatch caches)
# ═══════════════════════════════════════════════════

_TEST_EDUCATION = [
    {"id": "EDU-001", "name": "平陵一中", "type": "省重点高中", "age_range": [15, 18], "boarding": "mixed", "district": "RES-001", "weight": 10, "note": ""},
    {"id": "EDU-002", "name": "平陵二中", "type": "普通高中", "age_range": [15, 18], "boarding": "day_only", "district": "RES-002", "weight": 8, "note": ""},
    {"id": "EDU-003", "name": "平陵职业高中", "type": "职业高中", "age_range": [15, 18], "boarding": "boarding_only", "district": "RES-003", "weight": 5, "note": ""},
    {"id": "EDU-006", "name": "平陵大学", "type": "本科", "age_range": [18, 22], "boarding": "mixed", "district": "RES-001", "weight": 10, "note": ""},
    {"id": "EDU-007", "name": "平陵职业技术学院", "type": "专科", "age_range": [18, 22], "boarding": "day_only", "district": "RES-004", "weight": 7, "note": ""},
    {"id": "EDU-010", "name": "平陵中专", "type": "中专", "age_range": [15, 18], "boarding": "boarding_only", "district": "RES-003", "weight": 4, "note": ""},
]

_TEST_COMPANIES = [
    {"id": "COM-001", "name": "平陵代工厂", "type": "代工厂", "occupation_categories": ["普工", "文员"], "district": "RES-003", "note": ""},
    {"id": "COM-002", "name": "平陵外卖站", "type": "外卖配送", "occupation_categories": ["外卖员"], "district": "RES-001", "note": ""},
    {"id": "COM-003", "name": "平陵快递", "type": "快递物流", "occupation_categories": ["快递员"], "district": "RES-002", "note": ""},
    {"id": "COM-010", "name": "平陵网约车", "type": "网约车", "occupation_categories": ["网约车司机"], "district": "RES-005", "note": ""},
]

_TEST_INTERESTS = [
    {"name": "刷短视频", "category": "娱乐消遣", "min_age": 14, "max_age": 50, "rarity": 1.0},
    {"name": "打游戏", "category": "娱乐消遣", "min_age": 14, "max_age": 35, "rarity": 0.9},
    {"name": "广场舞", "category": "生活日常", "min_age": 36, "max_age": 50, "rarity": 0.5},
    {"name": "养花", "category": "生活日常", "min_age": 20, "max_age": 50, "rarity": 0.4},
    {"name": "追星", "category": "娱乐消遣", "min_age": 14, "max_age": 25, "rarity": 0.6},
]

_TEST_RESIDENTIAL = [
    {"id": "RES-001", "name": "老城区", "description": "", "typical_residents": [], "adjacent_landmarks": []},
    {"id": "RES-002", "name": "新城区", "description": "", "typical_residents": [], "adjacent_landmarks": []},
    {"id": "RES-003", "name": "大学城片区", "description": "", "typical_residents": [], "adjacent_landmarks": []},
    {"id": "RES-004", "name": "厂区宿舍", "description": "", "typical_residents": [], "adjacent_landmarks": []},
    {"id": "RES-005", "name": "开发区", "description": "", "typical_residents": [], "adjacent_landmarks": []},
]


def _setup_city_data():
    """Monkeypatch city_data caches so no filesystem access needed."""
    import app.world.city_data as cd
    cd._education_cache = list(_TEST_EDUCATION)
    cd._companies_cache = list(_TEST_COMPANIES)
    cd._interests_cache = list(_TEST_INTERESTS)
    cd._residential_cache = list(_TEST_RESIDENTIAL)


def _teardown_city_data():
    import app.world.city_data as cd
    cd._education_cache = None
    cd._companies_cache = None
    cd._interests_cache = None
    cd._residential_cache = None


def test_get_institutions_by_age_15():
    _setup_city_data()
    try:
        from app.world.city_data import get_institutions_by_age
        results = get_institutions_by_age(15)
        ids = {r["id"] for r in results}
        assert "EDU-001" in ids
        assert "EDU-006" not in ids  # college
    finally:
        _teardown_city_data()


def test_get_institutions_by_age_19():
    _setup_city_data()
    try:
        from app.world.city_data import get_institutions_by_age
        results = get_institutions_by_age(19)
        ids = {r["id"] for r in results}
        assert "EDU-006" in ids  # college
        assert "EDU-001" not in ids  # high school
    finally:
        _teardown_city_data()


def test_get_institutions_by_age_out_of_range():
    _setup_city_data()
    try:
        from app.world.city_data import get_institutions_by_age
        assert get_institutions_by_age(5) == []
        assert get_institutions_by_age(60) == []
    finally:
        _teardown_city_data()


def test_get_companies_by_occupation_match():
    _setup_city_data()
    try:
        from app.world.city_data import get_companies_by_occupation
        results = get_companies_by_occupation("普工")
        assert len(results) >= 1
        assert results[0]["name"] == "平陵代工厂"
    finally:
        _teardown_city_data()


def test_get_companies_by_occupation_no_match():
    _setup_city_data()
    try:
        from app.world.city_data import get_companies_by_occupation
        results = get_companies_by_occupation("宇航员")
        assert results == []
    finally:
        _teardown_city_data()


def test_get_interests_for_age_15():
    _setup_city_data()
    try:
        from app.world.city_data import get_interests_for_age
        results = get_interests_for_age(15)
        names = {r["name"] for r in results}
        assert "刷短视频" in names
        assert "广场舞" not in names  # age 36+
    finally:
        _teardown_city_data()


def test_get_interests_for_age_40():
    _setup_city_data()
    try:
        from app.world.city_data import get_interests_for_age
        results = get_interests_for_age(40)
        names = {r["name"] for r in results}
        assert "广场舞" in names
        assert "追星" not in names  # max 25
    finally:
        _teardown_city_data()


def test_get_residential_by_id_found():
    _setup_city_data()
    try:
        from app.world.city_data import get_residential_by_id
        result = get_residential_by_id("RES-001")
        assert result is not None
        assert result["name"] == "老城区"
    finally:
        _teardown_city_data()


def test_get_residential_by_id_not_found():
    _setup_city_data()
    try:
        from app.world.city_data import get_residential_by_id
        assert get_residential_by_id("NOSUCH") is None
    finally:
        _teardown_city_data()


def test_sample_interest_candidates():
    _setup_city_data()
    random.seed(42)
    try:
        from app.world.city_data import sample_interest_candidates
        results = sample_interest_candidates(20, count=3)
        assert len(results) >= 1
        for r in results:
            assert "name" in r
    finally:
        _teardown_city_data()


def test_sample_interest_candidates_empty():
    _setup_city_data()
    try:
        from app.world.city_data import sample_interest_candidates
        results = sample_interest_candidates(5, count=5)
        assert results == []
    finally:
        _teardown_city_data()


# ═══════════════════════════════════════════════════
# location_assigner.py — deterministic branches
# ═══════════════════════════════════════════════════

def test_assign_location_student_path():
    _setup_city_data()
    random.seed(42)
    try:
        from app.world.location_assigner import assign_location
        result = assign_location(16, "学生")
        assert "school_or_company" in result
        assert "district" in result
        assert "boarding" in result
    finally:
        _teardown_city_data()


def test_assign_location_non_student_path():
    _setup_city_data()
    random.seed(42)
    try:
        from app.world.location_assigner import assign_location
        result = assign_location(30, "普工")
        assert result["school_or_company"] == "平陵代工厂"
        assert "district" in result
    finally:
        _teardown_city_data()


def test_assign_location_no_matching_company():
    _setup_city_data()
    random.seed(42)
    try:
        from app.world.location_assigner import assign_location
        result = assign_location(30, "宇航员")
        assert result["school_or_company"] == "无固定单位"
        assert result["school_or_company_id"] is None
    finally:
        _teardown_city_data()


def test_derive_boarding_only():
    _setup_city_data()
    try:
        from app.world.location_assigner import _derive_boarding_and_district
        # EDU-003 has boarding_only
        school = next(s for s in _TEST_EDUCATION if s["id"] == "EDU-003")
        result = _derive_boarding_and_district(school)
        assert result["boarding"] is True
        assert result["district_id"] == "RES-003"
    finally:
        _teardown_city_data()


def test_derive_day_only():
    _setup_city_data()
    try:
        from app.world.location_assigner import _derive_boarding_and_district
        # EDU-002 has day_only
        school = next(s for s in _TEST_EDUCATION if s["id"] == "EDU-002")
        result = _derive_boarding_and_district(school)
        assert result["boarding"] is False
    finally:
        _teardown_city_data()


def test_resolve_district_found():
    _setup_city_data()
    try:
        from app.world.location_assigner import _resolve_district
        result = _resolve_district("RES-001")
        assert result is not None
        assert result["name"] == "老城区"
    finally:
        _teardown_city_data()


def test_resolve_district_not_found():
    _setup_city_data()
    try:
        from app.world.location_assigner import _resolve_district
        assert _resolve_district("NO-EXIST") is None
    finally:
        _teardown_city_data()


# ═══════════════════════════════════════════════════
# agent_factory.py — deterministic functions
# ═══════════════════════════════════════════════════

def test_lookup_income_edu_under_18():
    from app.engine.agent_factory import _lookup_income_edu
    income, edu = _lookup_income_edu(15, "学生")
    assert income == "无收入"
    assert edu == "在读中学"


def test_lookup_income_edu_student_20():
    from app.engine.agent_factory import _lookup_income_edu
    income, edu = _lookup_income_edu(20, "学生")
    assert "兼职" in income
    assert "在读" in edu


def test_lookup_income_edu_young_worker():
    from app.engine.agent_factory import _lookup_income_edu
    income, edu = _lookup_income_edu(21, "普工")
    assert income == "2k-4k"


def test_lookup_income_edu_mid_career():
    from app.engine.agent_factory import _lookup_income_edu
    income, edu = _lookup_income_edu(22, "普工")
    assert income == "2k-4k"


def test_lookup_income_edu_25():
    from app.engine.agent_factory import _lookup_income_edu
    income, edu = _lookup_income_edu(25, "文员")
    assert income == "3k-6k"
    assert "本科" in edu


def test_lookup_income_edu_30():
    from app.engine.agent_factory import _lookup_income_edu
    income, edu = _lookup_income_edu(30, "销售")
    assert income == "4k-10k"


def test_lookup_income_edu_40():
    from app.engine.agent_factory import _lookup_income_edu
    income, edu = _lookup_income_edu(45, "个体户")
    assert income == "3k-8k"


def test_generate_hard_conditions():
    from app.engine.agent_factory import generate_hard_conditions
    random.seed(42)
    draft = generate_hard_conditions()
    assert 14 <= draft.age <= 50
    assert draft.gender in ("男", "女")
    assert draft.occupation != ""
    assert draft.income_level != ""
    assert draft.education != ""
    assert draft.chronotype in ("early", "normal", "nightowl", "chaotic")


def test_gen_personality_initial():
    from app.engine.agent_factory import gen_personality_initial, AgentDraft, PERSONALITY_TRAITS
    random.seed(42)
    draft = AgentDraft()
    draft = gen_personality_initial(draft)
    assert len(draft.personality_vector) == 8
    for trait in PERSONALITY_TRAITS:
        assert trait in draft.personality_vector
    total = sum(draft.personality_vector.values())
    assert abs(total - 1.0) < 0.001
    assert len(draft.personality_adjectives) == 3


def test_gen_personality_adjust():
    from app.engine.agent_factory import gen_personality_adjust, AgentDraft, PERSONALITY_TRAITS
    random.seed(42)
    draft = AgentDraft()
    # Manually set a vector
    draft.personality_vector = {t: 0.125 for t in PERSONALITY_TRAITS}
    draft = gen_personality_adjust(draft)
    total = sum(draft.personality_vector.values())
    assert abs(total - 1.0) < 0.001
    for val in draft.personality_vector.values():
        assert val >= 0.02


def test_select_naming_style_normal():
    from app.engine.agent_factory import select_naming_style, AgentDraft, PERSONALITY_TRAITS
    random.seed(42)
    draft = AgentDraft(age=30)
    draft.personality_vector = {t: 0.125 for t in PERSONALITY_TRAITS}
    draft = select_naming_style(draft)
    assert "id" in draft.naming_style
    assert "category" in draft.naming_style


def test_select_naming_style_age_14():
    from app.engine.agent_factory import select_naming_style, AgentDraft, PERSONALITY_TRAITS
    random.seed(42)
    draft = AgentDraft(age=14)
    draft.personality_vector = {t: 0.125 for t in PERSONALITY_TRAITS}
    draft = select_naming_style(draft)
    assert "id" in draft.naming_style


def test_set_notification_defaults_teen():
    from app.engine.agent_factory import set_notification_defaults, AgentDraft
    random.seed(0)
    draft = AgentDraft(age=15, occupation="学生", boarding=False)
    draft = set_notification_defaults(draft)
    assert len(draft.notification_settings) > 0


def test_set_notification_defaults_adult():
    from app.engine.agent_factory import set_notification_defaults, AgentDraft
    random.seed(0)
    draft = AgentDraft(age=30, occupation="文员")
    draft = set_notification_defaults(draft)
    assert len(draft.notification_settings) > 0


def test_prelearn_slangs_noop():
    from app.engine.agent_factory import prelearn_slangs, AgentDraft
    import asyncio

    async def run():
        draft = AgentDraft()
        result = await prelearn_slangs(draft, MagicMock())
        assert result is draft

    asyncio.run(run())


# ═══════════════════════════════════════════════════
# API validation — Pydantic models + verify_admin
# ═══════════════════════════════════════════════════

def test_agent_register_request_valid():
    from app.api.agents import AgentRegisterRequest
    req = AgentRegisterRequest(
        nickname="测试用户",
        age=25,
        gender="男",
        interests=["游戏", "音乐"],
        invite_code="test-code",
    )
    assert req.nickname == "测试用户"
    assert req.age == 25


def test_agent_register_request_age_13_invalid():
    from app.api.agents import AgentRegisterRequest
    from pydantic import ValidationError
    try:
        AgentRegisterRequest(nickname="test", age=13, gender="男", interests=["a"], invite_code="x")
        assert False, "should raise ValidationError"
    except ValidationError:
        pass


def test_agent_register_request_age_51_invalid():
    from app.api.agents import AgentRegisterRequest
    from pydantic import ValidationError
    try:
        AgentRegisterRequest(nickname="test", age=51, gender="男", interests=["a"], invite_code="x")
        assert False, "should raise ValidationError"
    except ValidationError:
        pass


def test_agent_register_request_nickname_too_short():
    from app.api.agents import AgentRegisterRequest
    from pydantic import ValidationError
    try:
        AgentRegisterRequest(nickname="a", age=20, gender="男", interests=["a"], invite_code="x")
        assert False, "should raise ValidationError"
    except ValidationError:
        pass


def test_agent_register_request_nickname_too_long():
    from app.api.agents import AgentRegisterRequest
    from pydantic import ValidationError
    try:
        AgentRegisterRequest(nickname="a" * 21, age=20, gender="男", interests=["a"], invite_code="x")
        assert False, "should raise ValidationError"
    except ValidationError:
        pass


def test_agent_register_request_empty_interests():
    from app.api.agents import AgentRegisterRequest
    from pydantic import ValidationError
    try:
        AgentRegisterRequest(nickname="test", age=20, gender="男", interests=[], invite_code="x")
        assert False, "should raise ValidationError"
    except ValidationError:
        pass


def test_agent_register_request_bad_gender():
    from app.api.agents import AgentRegisterRequest
    from pydantic import ValidationError
    try:
        AgentRegisterRequest(nickname="test", age=20, gender="未知", interests=["a"], invite_code="x")
        assert False, "should raise ValidationError"
    except ValidationError:
        pass


def test_verify_admin_correct():
    from app.api.admin import verify_admin
    from fastapi.security import HTTPBasicCredentials
    import app.api.admin as admin_mod
    orig_settings = admin_mod.settings
    try:
        m = MagicMock()
        m.admin_password = "correct-pw"
        admin_mod.settings = m
        verify_admin(HTTPBasicCredentials(username="admin", password="correct-pw"))
    finally:
        admin_mod.settings = orig_settings


def test_verify_admin_wrong():
    from app.api.admin import verify_admin
    from fastapi.security import HTTPBasicCredentials
    from fastapi import HTTPException
    import app.api.admin as admin_mod
    orig_settings = admin_mod.settings
    try:
        m = MagicMock()
        m.admin_password = "correct-pw"
        admin_mod.settings = m
        try:
            verify_admin(HTTPBasicCredentials(username="admin", password="wrong-pw"))
            assert False, "should raise HTTPException"
        except HTTPException as e:
            assert e.status_code == 401
    finally:
        admin_mod.settings = orig_settings


def test_deploy_request_valid():
    from app.api.admin import DeployRequest
    req = DeployRequest(count=5)
    assert req.count == 5


def test_deploy_request_count_zero_invalid():
    from app.api.admin import DeployRequest
    from pydantic import ValidationError
    try:
        DeployRequest(count=0)
        assert False, "should raise"
    except ValidationError:
        pass


def test_deploy_request_count_11_invalid():
    from app.api.admin import DeployRequest
    from pydantic import ValidationError
    try:
        DeployRequest(count=11)
        assert False, "should raise"
    except ValidationError:
        pass


# ─── Run all ───

if __name__ == "__main__":
    import traceback

    tests = [
        (name, obj) for name, obj in globals().items()
        if name.startswith("test_") and callable(obj)
    ]
    passed = 0
    failed = 0
    for name, fn in tests:
        try:
            fn()
            passed += 1
            print(f"  PASS {name}")
        except Exception:
            failed += 1
            print(f"  FAIL {name}")
            traceback.print_exc()

    print(f"\n{passed} passed, {failed} failed, {len(tests)} total")
    if failed:
        sys.exit(1)
