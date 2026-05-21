from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


@runtime_checkable
class ContentHook(Protocol):
    """内容创作后置钩子协议。插件实现此接口，由 PluginManager 统一调度。"""

    @property
    def enabled(self) -> bool: ...

    async def on_content_created(self, agent_id: str, content: str, db: "AsyncSession") -> None: ...

    async def get_context_data(self, agent_id: str, db: "AsyncSession") -> dict | None: ...


class PluginManager:
    """插件管理器单例。插件始终注册，通过 enabled 属性控制是否激活。

    每个插件的 enabled 属性从 FeatureFlag registry 读取，
    支持运行时通过 API 切换（无需重启）。
    """

    def __init__(self) -> None:
        self._plugins: list[ContentHook] = []
        self._initialized: bool = False

    def _init(self) -> None:
        if self._initialized:
            return
        from app.plugins.meme_plugin import MemePlugin

        self._plugins.append(MemePlugin())
        self._initialized = True

    async def post_content(self, agent_id: str, content: str, db: "AsyncSession") -> None:
        """内容创建后置处理 — 遍历已启用插件调用 on_content_created."""
        self._init()
        for plugin in self._plugins:
            if plugin.enabled:
                await plugin.on_content_created(agent_id, content, db)

    async def gather_context(self, agent_id: str, db: "AsyncSession") -> dict:
        """收集已启用插件的上下文数据，合并返回."""
        self._init()
        ctx: dict = {}
        for plugin in self._plugins:
            if plugin.enabled:
                data = await plugin.get_context_data(agent_id, db)
                if data:
                    ctx.update(data)
        return ctx
