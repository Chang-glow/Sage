"""Feature flag registry — each plugin registers itself with metadata and an enabled state.

Config provides the default. Runtime toggle via API overrides it.
Reset clears the override, reverting to config default.

Frontend hook: GET /api/features lists all features; POST /api/features/{name}/toggle toggles.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FeatureFlag:
    name: str
    description: str
    category: str
    _default: bool = False
    _override: bool | None = None  # None = use default

    @property
    def enabled(self) -> bool:
        if self._override is not None:
            return self._override
        return self._default

    def enable(self) -> None:
        self._override = True

    def disable(self) -> None:
        self._override = False

    def reset(self) -> None:
        self._override = None


class PluginRegistry:
    """Singleton registry of all togglable features."""

    _features: dict[str, FeatureFlag] = {}

    @classmethod
    def register(
        cls,
        name: str,
        description: str,
        category: str,
        default_enabled: bool = False,
    ) -> FeatureFlag:
        flag = FeatureFlag(name, description, category, _default=default_enabled)
        cls._features[name] = flag
        return flag

    @classmethod
    def is_enabled(cls, name: str) -> bool:
        flag = cls._features.get(name)
        return flag.enabled if flag else False

    @classmethod
    def list_all(cls) -> list[dict]:
        return [
            {
                "name": f.name,
                "description": f.description,
                "category": f.category,
                "enabled": f.enabled,
            }
            for f in cls._features.values()
        ]

    @classmethod
    def toggle(cls, name: str, enabled: bool) -> bool:
        flag = cls._features.get(name)
        if flag is None:
            return False
        if enabled:
            flag.enable()
        else:
            flag.disable()
        return True

    @classmethod
    def reset(cls, name: str) -> bool:
        flag = cls._features.get(name)
        if flag is None:
            return False
        flag.reset()
        return True


plugin_registry = PluginRegistry()


# ── Module-level registration from config defaults ──

def _init_from_config() -> None:
    from app.config import config as _cfg

    # slang
    try:
        slang_default = bool(_cfg.slang.enabled)
    except AttributeError:
        slang_default = False
    PluginRegistry.register(
        "slang", "梗学习与衰减 — 注册时预学梗、浏览时学新梗、每日衰减", "slang",
        default_enabled=slang_default,
    )

    # meme
    try:
        meme_default = bool(_cfg.meme.enabled)
    except AttributeError:
        meme_default = False
    PluginRegistry.register(
        "meme", "梗系统 — 内容后置扫描梗使用 + 上下文注入活跃梗列表", "meme",
        default_enabled=meme_default,
    )

    # promises
    try:
        promises_default = bool(_cfg.promises.enabled)
    except AttributeError:
        promises_default = False
    PluginRegistry.register(
        "promises", "承诺与期待机制 — promise detection and expectation tracking", "promises",
        default_enabled=promises_default,
    )


_init_from_config()
