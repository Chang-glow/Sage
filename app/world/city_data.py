from __future__ import annotations

import random
from pathlib import Path

import yaml

_world_dir = Path(__file__).resolve().parent.parent.parent / "world"

_education_cache: list[dict] | None = None
_companies_cache: list[dict] | None = None
_interests_cache: list[dict] | None = None
_residential_cache: list[dict] | None = None
_entertainment_cache: dict | None = None


def _load_yaml(filename: str) -> dict:
    path = _world_dir / filename
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_education() -> list[dict]:
    global _education_cache
    if _education_cache is None:
        _education_cache = _load_yaml("education.yaml")["institutions"]
    return _education_cache


def load_companies() -> list[dict]:
    global _companies_cache
    if _companies_cache is None:
        _companies_cache = _load_yaml("companies.yaml")["companies"]
    return _companies_cache


def load_interests() -> list[dict]:
    global _interests_cache
    if _interests_cache is None:
        _interests_cache = _load_yaml("interests.yaml")["interests"]
    return _interests_cache


def load_residential() -> list[dict]:
    global _residential_cache
    if _residential_cache is None:
        _residential_cache = _load_yaml("residential.yaml")["residential_areas"]
    return _residential_cache


def get_institutions_by_age(age: int) -> list[dict]:
    return [
        inst
        for inst in load_education()
        if inst["age_range"][0] <= age <= inst["age_range"][1]
    ]


def get_companies_by_occupation(category: str) -> list[dict]:
    return [
        comp
        for comp in load_companies()
        if category in comp["occupation_categories"]
    ]


def get_interests_for_age(age: int) -> list[dict]:
    return [
        tag
        for tag in load_interests()
        if tag["min_age"] <= age <= tag["max_age"]
    ]


def sample_interest_candidates(age: int, count: int = 22) -> list[dict]:
    filtered = get_interests_for_age(age)
    if not filtered:
        return []
    weights = [t["rarity"] for t in filtered]
    k = min(count, len(filtered))
    return random.choices(filtered, weights=weights, k=k)


def get_residential_by_id(area_id: str) -> dict | None:
    for area in load_residential():
        if area["id"] == area_id:
            return area
    return None


def load_entertainment() -> dict:
    global _entertainment_cache
    if _entertainment_cache is None:
        _entertainment_cache = _load_yaml("entertainment.yaml")
    return _entertainment_cache


def get_venues() -> list[dict]:
    return load_entertainment().get("venues", [])


def get_restaurants() -> list[dict]:
    return load_entertainment().get("restaurants", [])


def get_city_projects_pool() -> list[dict]:
    return load_entertainment().get("city_projects_pool", [])


def get_infrastructure_events() -> list[str]:
    return load_entertainment().get("infrastructure_events", [])
