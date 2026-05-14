from __future__ import annotations

import asyncio
import logging
import re
import threading
from pathlib import Path

from app.skills.skill_utils import SkillDefinition

logger = logging.getLogger(__name__)

_TITLE_RE = re.compile(r"^#\s+Skill:\s*(.+?)\s*\((\w+)\)\s*$")


def _parse_skillmd(path: Path) -> SkillDefinition | None:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        logger.warning("skill_parse_read_failed", path=str(path))
        return None

    lines = text.split("\n")
    if not lines:
        return None

    m = _TITLE_RE.match(lines[0].strip())
    if not m:
        logger.warning("skill_parse_bad_title", path=str(path), first_line=lines[0])
        return None

    name, skill_id = m.group(1).strip(), m.group(2).strip()

    sections: dict[str, str] = {}
    current_heading: str | None = None
    current_lines: list[str] = []

    for line in lines[1:]:
        if line.startswith("## "):
            if current_heading is not None:
                sections[current_heading] = "\n".join(current_lines).strip()
            current_heading = line[3:].strip()
            current_lines = []
        else:
            current_lines.append(line)

    if current_heading is not None:
        sections[current_heading] = "\n".join(current_lines).strip()

    model_type = "便宜"
    for key, body in sections.items():
        if "模型" in key:
            if "主力" in body:
                model_type = "主力"
            break

    prompt_template = sections.get("Prompt 模板", "")

    output_format = "JSON"
    output_schema: dict | None = None
    output_body = sections.get("输出格式", "")
    if output_body:
        if output_body.upper().startswith("JSON"):
            output_format = "JSON"
        else:
            output_format = "text"

    return SkillDefinition(
        skill_id=skill_id,
        name=name,
        model_type=model_type,
        prompt_template=prompt_template,
        output_format=output_format,
        output_schema=output_schema,
        trigger_condition=sections.get("触发条件", ""),
        input_description=sections.get("输入", ""),
        notes=sections.get("备注", ""),
        source_path=path,
    )


class SkillRegistry:
    _instance: SkillRegistry | None = None
    _lock = threading.Lock()

    def __new__(cls) -> SkillRegistry:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    obj = super().__new__(cls)
                    obj._skills: dict[str, SkillDefinition] = {}
                    obj._loaded = False
                    cls._instance = obj
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        with cls._lock:
            cls._instance = None

    @property
    def skills(self) -> dict[str, SkillDefinition]:
        return dict(self._skills)

    def load_all(self, skills_dir: Path | None = None) -> int:
        if skills_dir is None:
            skills_dir = Path(__file__).resolve().parent.parent.parent / "skills"
        count = 0
        for md_path in sorted(skills_dir.rglob("SKILL.md")):
            skill = _parse_skillmd(md_path)
            if skill is not None:
                self._skills[skill.skill_id] = skill
                count += 1
                logger.info(
                    "skill_loaded",
                    skill_id=skill.skill_id,
                    name=skill.name,
                    model_type=skill.model_type,
                )
        self._loaded = True
        logger.info("skills_load_complete", count=count, total=len(self._skills))
        return count

    def get(self, skill_id: str) -> SkillDefinition:
        if skill_id not in self._skills:
            raise KeyError(f"Skill not found: {skill_id}")
        return self._skills[skill_id]

    def list_ids(self) -> list[str]:
        return sorted(self._skills.keys())

    def reload(self, skills_dir: Path | None = None) -> int:
        self._skills.clear()
        return self.load_all(skills_dir)


registry = SkillRegistry()


async def watch_skills_dir(skills_dir: Path, interval: float = 30.0):
    last_mtimes: dict[str, float] = {}
    while True:
        current_mtimes: dict[str, float] = {}
        changed = False
        for md_path in skills_dir.rglob("SKILL.md"):
            try:
                mtime = md_path.stat().st_mtime
            except OSError:
                continue
            key = str(md_path)
            current_mtimes[key] = mtime
            if key in last_mtimes and last_mtimes[key] != mtime:
                changed = True
        if changed or len(current_mtimes) != len(last_mtimes):
            logger.info("skill_file_changed", triggering_reload=True)
            registry.reload(skills_dir)
        last_mtimes = current_mtimes
        await asyncio.sleep(interval)
