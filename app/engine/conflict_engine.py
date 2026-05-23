"""Conflict detection, guilt calculation, reflection, and action execution engine."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable


def calculate_rationality(personality_vector: dict[str, float] | None) -> float:
    """Rationality = truthseeker * 0.6 + peacemaker * 0.4."""
    if not personality_vector:
        return 0.0
    ts = float(personality_vector.get("truthseeker", 0) or 0)
    pm = float(personality_vector.get("peacemaker", 0) or 0)
    return ts * 0.6 + pm * 0.4


def _count_mutual_replies(agent1_id, agent2_id, replies: list) -> int:
    """Count back-and-forth rounds between two agents in a reply list."""
    if agent1_id == agent2_id:
        return 0
    if not replies:
        return 0

    rounds = 0
    prev = None
    for r in replies:
        if r.author_id == agent1_id or r.author_id == agent2_id:
            if prev is not None and r.author_id != prev:
                rounds += 1
            prev = r.author_id
    return rounds


def is_conflict_triggered(agent_id, opponent_id, replies: list) -> bool:
    """True when >= N rounds of mutual replies between agent and opponent."""
    from app.config import config as yaml_config

    threshold = int(yaml_config.conflict.conflict_mutual_reply_threshold)
    count = _count_mutual_replies(agent_id, opponent_id, replies)
    return count >= threshold


class ConflictCooldown:
    """Per-agent-pair cooldown to prevent spamming conflict reflection."""

    def __init__(self) -> None:
        self._cooldowns: dict[str, datetime] = {}

    @staticmethod
    def _make_key(a1: str, a2: str) -> str:
        return "\x00".join(sorted([a1, a2]))

    def set(self, a1: str, a2: str) -> None:
        self._cooldowns[self._make_key(a1, a2)] = datetime.now(timezone.utc)

    def is_ready(self, a1: str, a2: str) -> bool:
        from app.config import config as yaml_config

        key = self._make_key(a1, a2)
        last = self._cooldowns.get(key)
        if last is None:
            return True
        cooldown = timedelta(minutes=int(yaml_config.conflict.reflection_cooldown_minutes))
        return datetime.now(timezone.utc) - last >= cooldown


# Global cooldown store
conflict_cooldown = ConflictCooldown()


async def run_conflict_reflection(
    agent,
    opponent,
    conflict_summary: str,
    db,
    llm_caller: Callable,
) -> dict[str, Any]:
    """Run guilt_calculation then reflection skills. Returns combined result."""
    from app.skills.executor import execute

    pv = agent.personality_vector or {}

    # Step 1: guilt calculation
    guilt_ctx = {
        "agent_name": agent.nickname,
        "agent_personality": ", ".join(
            f"{k}={v:.2f}"
            for k, v in sorted(pv.items(), key=lambda x: x[1], reverse=True)[:5]
        ) or "普通",
        "conflict_exchange": conflict_summary,
        "aggression_score": pv.get("instigator", 0.5),
        "other_perceived_hurt": "中等",
        "relationship_loss": "轻微",
    }

    guilt_result = await execute("guilt_calculation", guilt_ctx, llm_caller=llm_caller)
    if guilt_result.status == "success" and isinstance(guilt_result.parsed, dict):
        guilt_delta = float(guilt_result.parsed.get("guilt_delta", 0))
    else:
        guilt_delta = 0.0

    # Step 2: reflection
    rationality = calculate_rationality(pv)

    reflection_ctx = {
        "agent_name": agent.nickname,
        "agent_personality": guilt_ctx["agent_personality"],
        "conflict_summary": conflict_summary,
        "guilt_score": round(guilt_delta, 2),
        "rationality_score": round(rationality, 2),
        "relationship_before": "普通",
    }

    reflection_result = await execute("reflection", reflection_ctx, llm_caller=llm_caller)
    if reflection_result.status == "success" and isinstance(reflection_result.parsed, dict):
        return {
            "action": reflection_result.parsed.get("action", "let_go"),
            "monologue": reflection_result.parsed.get("monologue", ""),
            "guilt_delta": guilt_delta,
            "rationality": rationality,
        }

    return {
        "action": "let_go",
        "monologue": "",
        "guilt_delta": guilt_delta,
        "rationality": rationality,
    }


async def execute_conflict_action(
    agent,
    opponent,
    post,
    action: str,
    monologue: str,
    db,
) -> dict[str, Any] | None:
    """Execute the action tendency from reflection result."""
    if action == "apologize":
        # Public reply or DM apology — tone shaped by personality
        return {
            "type": "apology",
            "apology_text": f"@{opponent.nickname} {monologue}",
            "target_id": str(opponent.id),
        }

    if action == "hold_grudge":
        from app.jobs.social_engine import adjust_after_conflict
        await adjust_after_conflict(agent.id, opponent.id, db)

        # Add conflict memory as reinforced memory
        memory_entry = {
            "type": "long",
            "content": f"与{opponent.nickname}发生冲突，记恨在心: {monologue}",
            "importance": 0.85,
            "retrieval_count": 0,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        memories = list(agent.solidified_memories or [])
        memories.append(memory_entry)
        agent.solidified_memories = memories

        return {"type": "hold_grudge", "monologue": monologue}

    if action == "let_go":
        return {"type": "let_go", "monologue": monologue}

    if action == "whatever":
        return {"type": "whatever", "monologue": monologue}

    if action == "wait":
        return {"type": "wait", "monologue": monologue}

    return {"type": "unknown", "action": action}
