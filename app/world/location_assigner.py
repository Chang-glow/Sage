from __future__ import annotations

import random

from app.world.city_data import (
    get_companies_by_occupation,
    get_institutions_by_age,
    load_residential,
)


def assign_location(age: int, occupation_category: str) -> dict:
    """为 Agent 分配平陵市具体地点。

    Returns:
        {school_or_company, school_or_company_id, district, district_id, boarding}
    """
    is_student = age < 18 or occupation_category == "学生"

    if is_student:
        return _assign_student(age)
    else:
        return _assign_non_student(occupation_category)


def _assign_student(age: int) -> dict:
    institutions = get_institutions_by_age(age)

    if not institutions:
        return _fallback_location()

    if age <= 18:
        return _assign_high_school(institutions)
    else:
        return _assign_college(institutions)


def _assign_high_school(institutions: list[dict]) -> dict:
    academic = [i for i in institutions if "高中" in i["type"] and "职业" not in i["type"]]
    vocational = [i for i in institutions if i["type"] in ("职业高中", "中专")]

    academic_weight = sum(i["weight"] for i in academic)
    vocational_weight = sum(i["weight"] for i in vocational)

    total_weight = academic_weight + vocational_weight or 1
    track_weights = [academic_weight / total_weight, vocational_weight / total_weight]
    track = random.choices(["academic", "vocational"], weights=track_weights)[0]

    pool = academic if track == "academic" else vocational
    if not pool:
        pool = academic + vocational

    weights = [i["weight"] for i in pool]
    school = random.choices(pool, weights=weights)[0]

    return _derive_boarding_and_district(school)


def _assign_college(institutions: list[dict]) -> dict:
    weights = [i["weight"] for i in institutions]
    school = random.choices(institutions, weights=weights)[0]
    return _derive_boarding_and_district(school)


def _derive_boarding_and_district(school: dict) -> dict:
    boarding_rule = school["boarding"]
    if boarding_rule == "boarding_only":
        boarding = True
    elif boarding_rule == "day_only":
        boarding = False
    else:
        boarding = random.choice([True, False])

    if boarding:
        district = school["district"]
    else:
        district = random.choice(["RES-001", "RES-002"])

    area = _resolve_district(district)

    return {
        "school_or_company": school["name"],
        "school_or_company_id": school["id"],
        "district": area["name"] if area else district,
        "district_id": district,
        "boarding": boarding,
    }


def _assign_non_student(occupation_category: str) -> dict:
    companies = get_companies_by_occupation(occupation_category)

    if not companies:
        district_id = random.choice(["RES-001", "RES-002", "RES-005"])
        area = _resolve_district(district_id)
        return {
            "school_or_company": "无固定单位",
            "school_or_company_id": None,
            "district": area["name"] if area else district_id,
            "district_id": district_id,
            "boarding": None,
        }

    company = random.choice(companies)
    district_id = company["district"]
    area = _resolve_district(district_id)

    return {
        "school_or_company": company["name"],
        "school_or_company_id": company["id"],
        "district": area["name"] if area else district_id,
        "district_id": district_id,
        "boarding": None,
    }


def _resolve_district(district_id: str) -> dict | None:
    for area in load_residential():
        if area["id"] == district_id:
            return area
    return None


def _fallback_location() -> dict:
    district_id = random.choice(["RES-001", "RES-002"])
    area = _resolve_district(district_id)
    return {
        "school_or_company": "平陵市",
        "school_or_company_id": None,
        "district": area["name"] if area else district_id,
        "district_id": district_id,
        "boarding": None,
        "is_temporary": True,
    }
