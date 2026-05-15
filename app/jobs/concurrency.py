from __future__ import annotations

import asyncio

from app.config import config as yaml_config

_agent_semaphore: asyncio.Semaphore | None = None


def get_agent_semaphore() -> asyncio.Semaphore:
    global _agent_semaphore
    if _agent_semaphore is None:
        _agent_semaphore = asyncio.Semaphore(yaml_config.scheduler.max_concurrent_agents)
    return _agent_semaphore
