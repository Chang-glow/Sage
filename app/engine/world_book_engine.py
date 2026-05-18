"""World Book engine — dynamic prompt injection system.

Inspired by SillyTavern World Info / Lorebook mechanism.
Entries are created/updated/removed by Skills.  The engine matches, sorts,
trims and injects active entries into skill prompts before LLM calls.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import config
from app.models.world_book import WorldBookEntry

logger = logging.getLogger(__name__)

# ── Allowed enum values ──
VALID_SCOPES = {"global", "character", "chat"}
VALID_TRIGGER_TYPES = {"constant", "keyword", "regex", "status"}
VALID_LOGIC_RULES = {"AND_ANY", "AND_ALL", "NOT_ANY", "NOT_ALL"}
VALID_POSITIONS = {"before_char", "after_char", "at_depth"}

# Scope sort rank: character first, then chat, then global
_SCOPE_RANK = {"character": 0, "chat": 1, "global": 2}


# ═══════════════════════════════════════════════════════════════════
# Pure functions (no DB, no side effects)
# ═══════════════════════════════════════════════════════════════════

def _extract_text_from_context(ctx: dict[str, Any]) -> str:
    """Recursively collect all string and numeric values into a single
    lowercased text blob for trigger-key scanning."""
    parts: list[str] = []

    def _walk(obj: Any) -> None:
        if isinstance(obj, str):
            parts.append(obj)
        elif isinstance(obj, (int, float)):
            parts.append(str(obj))
        elif isinstance(obj, dict):
            for v in obj.values():
                _walk(v)
        elif isinstance(obj, (list, tuple)):
            for item in obj:
                _walk(item)

    _walk(ctx)
    return " ".join(parts)


def _evaluate_logic_rule(keys: list[str], text: str, rule: str | None) -> bool:
    """Evaluate whether trigger keys match text under the given logic rule."""
    if not keys:
        return False
    matches = [k.lower() in text.lower() for k in keys]
    if rule == "AND_ANY" or rule is None:
        return any(matches)
    elif rule == "AND_ALL":
        return all(matches)
    elif rule == "NOT_ANY":
        return not any(matches)
    elif rule == "NOT_ALL":
        return not all(matches)
    return any(matches)


def _match_entries(
    entries: list[WorldBookEntry],
    context_text: str,
    context: dict[str, Any],
) -> list[WorldBookEntry]:
    """Return entries whose trigger conditions are satisfied."""
    matched: list[WorldBookEntry] = []
    text_lower = context_text.lower()

    for entry in entries:
        if not entry.is_active:
            continue

        tt = entry.trigger_type
        keys: list[str] = entry.trigger_keys or []

        if tt == "constant":
            matched.append(entry)
        elif tt == "keyword":
            if keys and _evaluate_logic_rule(keys, text_lower, entry.logic_rule):
                matched.append(entry)
        elif tt == "regex":
            if keys:
                try:
                    pattern_matches = [
                        bool(re.search(k, context_text, re.IGNORECASE)) for k in keys
                    ]
                    rule = entry.logic_rule or "AND_ANY"
                    if rule == "AND_ANY":
                        ok = any(pattern_matches)
                    elif rule == "AND_ALL":
                        ok = all(pattern_matches)
                    elif rule == "NOT_ANY":
                        ok = not any(pattern_matches)
                    elif rule == "NOT_ALL":
                        ok = not all(pattern_matches)
                    else:
                        ok = any(pattern_matches)
                except re.error:
                    ok = False
                if ok:
                    matched.append(entry)
        elif tt == "status":
            status_values = context.get("_status", {})
            if isinstance(status_values, dict) and keys:
                status_text = " ".join(
                    str(v).lower() for v in status_values.values()
                )
                if _evaluate_logic_rule(keys, status_text, entry.logic_rule):
                    matched.append(entry)

    return matched


def _sort_entries(entries: list[WorldBookEntry]) -> list[WorldBookEntry]:
    """Sort matched entries: priority desc → scope rank → created_at desc."""
    return sorted(
        entries,
        key=lambda e: (
            -e.priority,
            _SCOPE_RANK.get(e.scope, 2),
            -(e.created_at.timestamp() if e.created_at else 0),
        ),
    )


def _trim_by_budget(
    entries: list[WorldBookEntry], token_budget: int
) -> list[WorldBookEntry]:
    """Keep highest-priority entries that fit within token_budget.
    Approximate: 1 token ≈ 4 characters (mixed Chinese / English)."""
    if token_budget <= 0:
        return []
    char_budget = token_budget * 4
    kept: list[WorldBookEntry] = []
    total = 0
    for e in entries:
        cost = len(e.content)
        if total + cost <= char_budget:
            kept.append(e)
            total += cost
        # else: skip this entry, try next (may be smaller)
    return kept


def _inject_entries(prompt: str, entries: list[WorldBookEntry]) -> str:
    """Inject matched entries into the prompt at their designated positions."""
    before: list[str] = []
    after: list[str] = []
    at_depth: list[str] = []

    for e in entries:
        block = f"【{e.title}】{e.content}"
        pos = e.position
        if pos == "before_char":
            before.append(block)
        elif pos == "at_depth":
            at_depth.append(block)
        else:
            after.append(block)

    result = prompt

    if before:
        prefix = "[世界书]\n" + "\n---\n".join(before) + "\n[/世界书]\n\n"
        result = prefix + result

    if after:
        suffix = "\n\n[世界书]\n" + "\n---\n".join(after) + "\n[/世界书]"
        result = result + suffix

    if at_depth:
        depth_block = "[世界书]\n" + "\n---\n".join(at_depth) + "\n[/世界书]"
        marker = "{world_book_inject}"
        if marker in result:
            result = result.replace(marker, depth_block)
        else:
            result = result + "\n\n" + depth_block

    return result


# ═══════════════════════════════════════════════════════════════════
# Async functions (require DB session)
# ═══════════════════════════════════════════════════════════════════

async def assemble_prompt(
    skill_prompt: str,
    context: dict[str, Any],
    db: AsyncSession,
) -> str:
    """Main orchestration: scan → match → recursive → sort → trim → inject."""
    cfg = _get_world_book_config()
    max_depth = cfg.get("max_recursive_depth", 3)

    # Gather all active, non-expired entries
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(WorldBookEntry).where(
            WorldBookEntry.is_active == True,  # noqa: E712
            (WorldBookEntry.expires_at == None) | (WorldBookEntry.expires_at > now),  # noqa: E711
        )
    )
    all_entries: list[WorldBookEntry] = list(result.scalars().all())

    if not all_entries:
        return skill_prompt

    # First-pass scan and match — scan both prompt text and context
    context_text = skill_prompt + " " + _extract_text_from_context(context)
    matched = _match_entries(all_entries, context_text, context)
    visited: set[UUID] = {e.id for e in matched}

    # Recursive pass: entries marked recursive may trigger additional entries
    for _ in range(max_depth):
        if not matched:
            break
        # Collect content from recursive entries as new scan text
        recursive_texts: list[str] = []
        for e in matched:
            if e.recursive and e.content:
                recursive_texts.append(e.content)
        if not recursive_texts:
            break

        extra_text = " ".join(recursive_texts)
        extra_matched = _match_entries(all_entries, extra_text, context)
        new_entries = [e for e in extra_matched if e.id not in visited]
        if not new_entries:
            break
        for e in new_entries:
            visited.add(e.id)
        matched.extend(new_entries)

    # Sort, trim, inject
    sorted_entries = _sort_entries(matched)
    budget = cfg.get("token_budget", 2000)
    trimmed = _trim_by_budget(sorted_entries, budget)

    return _inject_entries(skill_prompt, trimmed)


async def register_entry(data: dict[str, Any], db: AsyncSession) -> WorldBookEntry:
    """Create or update a world book entry from skill-provided data."""
    entry_id = data.get("id")
    if entry_id:
        try:
            uid = UUID(entry_id) if isinstance(entry_id, str) else entry_id
        except (ValueError, TypeError):
            uid = None
        if uid:
            result = await db.execute(
                select(WorldBookEntry).where(WorldBookEntry.id == uid)
            )
            existing = result.scalar_one_or_none()
            if existing:
                _apply_entry_fields(existing, data)
                return existing

    entry = WorldBookEntry()
    _apply_entry_fields(entry, data)
    db.add(entry)
    return entry


async def remove_entry(entry_id: str, db: AsyncSession) -> bool:
    """Soft-delete a world book entry (set is_active=False)."""
    try:
        uid = UUID(entry_id)
    except (ValueError, TypeError):
        return False
    result = await db.execute(
        select(WorldBookEntry).where(WorldBookEntry.id == uid)
    )
    entry = result.scalar_one_or_none()
    if entry is None:
        return False
    entry.is_active = False
    return True


def validate_entry_data(data: dict[str, Any]) -> list[str]:
    """Return list of validation errors; empty means valid."""
    errors: list[str] = []

    title = data.get("title")
    content = data.get("content")
    if not title or not isinstance(title, str) or not title.strip():
        errors.append("title is required and must be a non-empty string")
    if not content or not isinstance(content, str) or not content.strip():
        errors.append("content is required and must be a non-empty string")

    scope = data.get("scope", "character")
    if scope not in VALID_SCOPES:
        errors.append(f"scope must be one of {VALID_SCOPES}, got {scope!r}")

    tt = data.get("trigger_type", "keyword")
    if tt not in VALID_TRIGGER_TYPES:
        errors.append(f"trigger_type must be one of {VALID_TRIGGER_TYPES}, got {tt!r}")

    lr = data.get("logic_rule")
    if lr is not None and lr not in VALID_LOGIC_RULES:
        errors.append(f"logic_rule must be one of {VALID_LOGIC_RULES}, got {lr!r}")

    pos = data.get("position", "after_char")
    if pos not in VALID_POSITIONS:
        errors.append(f"position must be one of {VALID_POSITIONS}, got {pos!r}")

    trigger_keys = data.get("trigger_keys")
    if trigger_keys is not None and not isinstance(trigger_keys, list):
        errors.append("trigger_keys must be a list or null")

    return errors


# ═══════════════════════════════════════════════════════════════════
# Internal helpers
# ═══════════════════════════════════════════════════════════════════

def _get_world_book_config() -> dict[str, Any]:
    """Read world_book section from config, with defaults."""
    try:
        return {
            "token_budget": int(getattr(config.world_book, "token_budget", 2000)),
            "scan_depth": int(getattr(config.world_book, "scan_depth", 10)),
            "max_recursive_depth": int(getattr(config.world_book, "max_recursive_depth", 3)),
            "default_position": str(getattr(config.world_book, "default_position", "after_char")),
        }
    except Exception:
        return {"token_budget": 2000, "scan_depth": 10, "max_recursive_depth": 3, "default_position": "after_char"}


def _apply_entry_fields(entry: WorldBookEntry, data: dict[str, Any]) -> None:
    """Apply dict fields to a WorldBookEntry instance (used for both create & update)."""
    for field in (
        "scope", "title", "content", "trigger_type", "logic_rule",
        "priority", "position", "depth", "recursive", "is_active",
        "created_by_skill",
    ):
        if field in data:
            setattr(entry, field, data[field])

    if "trigger_keys" in data:
        entry.trigger_keys = data["trigger_keys"]

    expires_at = data.get("expires_at")
    if expires_at is not None and isinstance(expires_at, str):
        try:
            entry.expires_at = datetime.fromisoformat(expires_at)
        except (ValueError, TypeError):
            entry.expires_at = None
    elif expires_at is None and "expires_at" in data:
        entry.expires_at = None
