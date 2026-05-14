import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent

_config_cache: dict[str, Any] | None = None


def _load_yaml_config() -> dict[str, Any]:
    global _config_cache
    if _config_cache is not None:
        return _config_cache
    path = PROJECT_ROOT / "config.yaml"
    if not path.exists():
        raise FileNotFoundError(f"config.yaml not found at {path}")
    with open(path, encoding="utf-8") as f:
        _config_cache = yaml.safe_load(f)
    return _config_cache


class _Config:
    """Lazy-loading 配置访问器，支持点号路径。"""

    def __init__(self, data: dict[str, Any], prefix: str = "") -> None:
        self._data = data
        self._prefix = prefix

    def __getattr__(self, name: str) -> Any:
        key = f"{self._prefix}{name}"
        value = self._data
        for part in key.split("."):
            if isinstance(value, dict) and part in value:
                value = value[part]
            else:
                raise AttributeError(f"config key not found: {key}")
        if isinstance(value, dict):
            return _Config(self._data, prefix=f"{key}.")
        return value

    def __repr__(self) -> str:
        keys = [k for k in self._data if k.startswith(self._prefix)]
        return f"Config({keys})"


_yaml_data: dict[str, Any] | None = None


def _get_data() -> dict[str, Any]:
    global _yaml_data
    if _yaml_data is None:
        _yaml_data = _load_yaml_config()
    return _yaml_data


config = _Config(_get_data())


# ── 环境变量 (敏感信息) ──

class Settings(BaseModel):
    database_url: str = os.getenv(
        "DATABASE_URL", "postgresql+asyncpg://user:password@localhost:5432/sga"
    )
    deepseek_api_key: str = os.getenv("DEEPSEEK_API_KEY", "")
    deepseek_base_url: str = os.getenv(
        "DEEPSEEK_BASE_URL", "https://api.deepseek.com"
    )
    siliconflow_api_key: str = os.getenv("SILICONFLOW_API_KEY", "")
    siliconflow_base_url: str = os.getenv(
        "SILICONFLOW_BASE_URL", "https://api.siliconflow.cn"
    )
    admin_password: str = os.getenv("ADMIN_PASSWORD", "")
    bing_search_api_key: str = os.getenv("BING_SEARCH_API_KEY", "")
    invite_codes: list[str] = [
        c.strip()
        for c in os.getenv("INVITE_CODES", "sga-2026-invite").split(",")
        if c.strip()
    ]


settings = Settings()


def validate() -> list[str]:
    """启动时校验必填配置项，返回缺失列表."""
    missing: list[str] = []
    if not settings.deepseek_api_key:
        missing.append("DEEPSEEK_API_KEY")
    if not settings.siliconflow_api_key:
        missing.append("SILICONFLOW_API_KEY")
    if not settings.admin_password:
        missing.append("ADMIN_PASSWORD")
    return missing
