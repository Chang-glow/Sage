from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class SkillDefinition:
    skill_id: str
    name: str
    model_type: str  # "主力" | "便宜"
    prompt_template: str
    output_format: str = "JSON"
    output_schema: dict[str, Any] | None = None
    trigger_condition: str = ""
    input_description: str = ""
    notes: str = ""
    source_path: Path | None = None


@dataclass
class SkillResult:
    skill_id: str
    raw_response: str = ""
    parsed: dict[str, Any] | str | None = None
    model: str = ""
    tokens_used: int = 0
    duration_ms: float = 0.0
    status: str = "success"  # success | render_failure | llm_failure | parse_failure
    error: str | None = None


def build_agent_context(agent) -> dict[str, Any]:
    return {
        "agent_id": str(agent.id),
        "agent_name": agent.nickname,
        "agent_age": agent.age,
        "agent_gender": agent.gender,
        "agent_occupation": agent.occupation or "未知",
        "agent_education": agent.education or "",
        "agent_district": agent.district or "平陵市",
    }


def build_post_context(post) -> dict[str, Any]:
    return {
        "post_id": str(post.id),
        "post_title": post.title,
        "post_content": post.content,
        "post_author": str(post.author_id),
        "post_bar_name": "",
    }
