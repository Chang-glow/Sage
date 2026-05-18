from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, TYPE_CHECKING

import structlog

from app.config import config as yaml_config
from app.skills.llm_manager import call_llm
from app.skills.registry import registry
from app.skills.skill_utils import SkillResult

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()

_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*\n?(.*?)```", re.DOTALL)


def _resolve_model(model_type: str) -> str:
    if "主力" in model_type:
        return yaml_config.llm.default_main_model
    return yaml_config.llm.default_cheap_model


def _parse_response(raw: str, output_format: str, schema: dict | None = None) -> dict | str:
    cleaned = raw.strip()
    if "JSON" in output_format.upper():
        m = _JSON_BLOCK_RE.search(cleaned)
        if m:
            cleaned = m.group(1).strip()
        else:
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start != -1 and end != -1 and end > start:
                cleaned = cleaned[start : end + 1]
        return json.loads(cleaned)
    return cleaned


async def execute(
    skill_id: str,
    context: dict[str, Any],
    *,
    llm_caller=None,
    agent_id: str | None = None,
    db: AsyncSession | None = None,
) -> SkillResult:
    t0 = time.monotonic()

    try:
        skill = registry.get(skill_id)
    except KeyError:
        return SkillResult(
            skill_id=skill_id,
            status="render_failure",
            error=f"Skill not found: {skill_id}",
        )

    try:
        prompt = skill.prompt_template.format(**context)
    except (KeyError, ValueError) as e:
        return SkillResult(
            skill_id=skill_id,
            status="render_failure",
            error=f"Prompt render failed: {e}",
        )

    # ── World book injection ──
    if db is not None:
        try:
            from app.engine.world_book_engine import assemble_prompt
            prompt = await assemble_prompt(prompt, context, db)
        except Exception as e:
            logger.warning("world_book_assemble_failed", skill_id=skill_id, error=str(e))

    model = _resolve_model(skill.model_type)
    caller = llm_caller or call_llm

    try:
        raw_response = await caller(prompt, model, skill_id=skill_id)
    except Exception as e:
        logger.warning("llm_call_failed", skill_id=skill_id, model=model, error=str(e))
        # 主力模型失败 → 用便宜模型重试一次
        if "主力" in skill.model_type:
            cheap_model = _resolve_model("便宜")
            if cheap_model != model:
                try:
                    raw_response = await caller(prompt, cheap_model, skill_id=skill_id)
                    model = cheap_model
                except Exception as e2:
                    logger.error("llm_fallback_failed", skill_id=skill_id, model=cheap_model, error=str(e2))
                    return SkillResult(
                        skill_id=skill_id,
                        model=model,
                        duration_ms=(time.monotonic() - t0) * 1000,
                        status="llm_failure",
                        error=str(e),
                    )
            else:
                return SkillResult(
                    skill_id=skill_id,
                    model=model,
                    duration_ms=(time.monotonic() - t0) * 1000,
                    status="llm_failure",
                    error=str(e),
                )
        else:
            return SkillResult(
                skill_id=skill_id,
                model=model,
                duration_ms=(time.monotonic() - t0) * 1000,
                status="llm_failure",
                error=str(e),
            )

    try:
        parsed = _parse_response(raw_response, skill.output_format, skill.output_schema)

        # Extract world book management fields from parsed response
        wb_entry = None
        wb_remove = None
        if isinstance(parsed, dict):
            wb_entry = parsed.pop("world_book_entry", None)
            wb_remove = parsed.pop("remove_world_book_entry", None)

            # Persist world book mutations if db available
            if db is not None:
                if wb_entry and isinstance(wb_entry, dict):
                    try:
                        from app.engine.world_book_engine import register_entry
                        await register_entry(wb_entry, db)
                        await db.commit()
                        logger.info(
                            "world_book_entry_registered",
                            skill_id=skill_id, title=wb_entry.get("title", ""),
                        )
                    except Exception as e:
                        logger.warning(
                            "world_book_register_failed",
                            skill_id=skill_id, error=str(e),
                        )
                if wb_remove and isinstance(wb_remove, str):
                    try:
                        from app.engine.world_book_engine import remove_entry
                        await remove_entry(wb_remove, db)
                        await db.commit()
                        logger.info("world_book_entry_removed", skill_id=skill_id, entry_id=wb_remove)
                    except Exception as e:
                        logger.warning(
                            "world_book_remove_failed",
                            skill_id=skill_id, error=str(e),
                        )

        return SkillResult(
            skill_id=skill_id,
            raw_response=raw_response,
            parsed=parsed,
            model=model,
            duration_ms=(time.monotonic() - t0) * 1000,
            status="success",
            world_book_entry=wb_entry,
            remove_world_book_entry=wb_remove,
        )
    except Exception as e:
        logger.warning("parse_failed", skill_id=skill_id, raw=raw_response[:200])
        return SkillResult(
            skill_id=skill_id,
            raw_response=raw_response,
            parsed=raw_response,
            model=model,
            duration_ms=(time.monotonic() - t0) * 1000,
            status="parse_failure",
            error=str(e),
        )
