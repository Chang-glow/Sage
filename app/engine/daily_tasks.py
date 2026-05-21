"""DailyTaskRegistry — time-scheduled task system for the scheduler loop.

Tasks are registered with an (hour, minute) and called when the scheduler
loop reaches that time. This replaces hardcoded call lists in _maybe_generate_schedules.

Interface: async (db, llm_caller) → None
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

DailyTaskFn = Callable[..., Any]  # async (db, llm_caller)


class DailyTaskRegistry:
    """Time-scheduled task registry.

    Usage:
        registry = DailyTaskRegistry()

        async def reset_tokens(db, llm_caller):
            ...

        registry.register("reset_token_counters", reset_tokens, hour=0, minute=5)

        # In scheduler loop:
        for name, task_fn in registry.get_due(current_hour, current_minute):
            await task_fn(db, llm_caller)
    """

    def __init__(self) -> None:
        self._tasks: list[tuple[str, DailyTaskFn, int, int]] = []

    def register(self, name: str, task_fn: DailyTaskFn, hour: int, minute: int) -> None:
        """Register a task to run at the given (hour, minute)."""
        self._tasks.append((name, task_fn, hour, minute))

    def get_due(self, hour: int, minute: int) -> list[tuple[str, DailyTaskFn]]:
        """Return list of (name, task_fn) due at the given (hour, minute)."""
        return [(name, fn) for name, fn, h, m in self._tasks if h == hour and m == minute]


# Module-level singleton
daily_task_registry = DailyTaskRegistry()
