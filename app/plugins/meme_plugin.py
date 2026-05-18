from __future__ import annotations

from typing import TYPE_CHECKING

from app.jobs.meme_engine import get_agent_active_slangs, use_slang_in_text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class MemePlugin:
    """梗插件 — 封装梗系统的内容后置处理和上下文注入。"""

    @property
    def enabled(self) -> bool:
        from app.config import config
        try:
            return bool(config.meme.enabled)
        except AttributeError:
            return False

    async def on_content_created(self, agent_id: str, content: str, db: "AsyncSession") -> None:
        """内容创建后扫描梗使用并更新好感度."""
        await use_slang_in_text(agent_id, content, db)

    async def get_context_data(self, agent_id: str, db: "AsyncSession") -> dict | None:
        """收集 Agent 的活跃梗列表，注入内容生成上下文."""
        slangs = await get_agent_active_slangs(agent_id, db)
        if not slangs:
            return None
        personal_slangs = "、".join(s["slug"] for s in slangs)
        return {"personal_slangs": personal_slangs}
