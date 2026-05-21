"""BrowseHookRegistry — per-post hook system for extensible browse behavior.

Hooks are called after the core reply decision/generation logic in _step5.
New social features (like, bookmark, follow, DM, search, memory, slang)
register as hooks rather than modifying _step5 directly.

Interface: async (agent, post, decision, reply_result, db, llm_caller) → None
- decision: ReplyDecisionResult | None (None if filter didn't pass)
- reply_result: dict | None (None if no reply was generated)
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

BrowseHookFn = Callable[..., Any]  # async (agent, post, decision, reply_result, db, llm_caller)


class BrowseHookRegistry:
    """Priority-sorted registry of post-browse hooks.

    Usage:
        registry = BrowseHookRegistry()

        async def my_hook(agent, post, decision, reply_result, db, llm_caller):
            ...

        registry.register("my_hook", my_hook, priority=50)

        # In _step5, after per-post logic:
        await registry.iterate(agent, post, decision, reply_result, db, llm_caller)
    """

    def __init__(self) -> None:
        self._hooks: list[tuple[str, BrowseHookFn, int]] = []

    def register(self, name: str, hook_fn: BrowseHookFn, priority: int = 50) -> None:
        """Register a hook with a given priority (lower = runs first)."""
        self._hooks.append((name, hook_fn, priority))
        self._hooks.sort(key=lambda x: x[2])

    async def iterate(
        self,
        agent: Any,
        post: Any,
        decision: Any,
        reply_result: dict | None,
        db: AsyncSession,
        llm_caller: Any,
    ) -> None:
        """Call all registered hooks in priority order. Hook errors are logged and swallowed."""
        for name, hook_fn, _priority in self._hooks:
            try:
                await hook_fn(agent, post, decision, reply_result, db, llm_caller)
            except Exception:
                logger.exception("browse_hook_failed", hook_name=name)


# Module-level singleton — import and register hooks on this instance.
browse_hook_registry = BrowseHookRegistry()
