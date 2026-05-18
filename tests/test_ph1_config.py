"""Phase 1 tests — config system, Settings, validate, health endpoint."""
import os
import sys
import asyncio
from copy import deepcopy


# ─── _Config.__getattr__ ───

def test_config_getattr_shallow():
    from app.config import _Config
    c = _Config({"key": "value"})
    assert c.key == "value"


def test_config_getattr_nested():
    from app.config import _Config
    c = _Config({"a": {"b": 42}})
    assert c.a.b == 42


def test_config_getattr_returns_sub_config():
    from app.config import _Config
    c = _Config({"a": {"b": 1, "c": 2}})
    sub = c.a
    assert isinstance(sub, type(c))
    assert sub.b == 1
    assert sub.c == 2


def test_config_getattr_missing_key():
    from app.config import _Config
    c = _Config({"a": 1})
    try:
        _ = c.b
        assert False, "should raise AttributeError"
    except AttributeError:
        pass


def test_config_getattr_deeply_nested():
    from app.config import _Config
    c = _Config({"x": {"y": {"z": "deep"}}})
    assert c.x.y.z == "deep"


def test_config_getattr_empty_prefix():
    from app.config import _Config
    c = _Config({"key": 1, "other": 2}, prefix="")
    assert c.key == 1


def test_config_repr():
    from app.config import _Config
    c = _Config({"a": 1, "b": 2, "ax": 3}, prefix="a")
    r = repr(c)
    assert isinstance(r, str)


# ─── Settings ───

def test_settings_defaults():
    from app.config import Settings
    s = Settings(database_url="db://test", deepseek_api_key="placeholder-key",
                 siliconflow_api_key="placeholder-key", admin_password="placeholder-password")
    assert s.database_url == "db://test"
    assert s.deepseek_base_url == "https://api.deepseek.com"
    assert s.siliconflow_base_url == "https://api.siliconflow.cn"


def test_settings_invite_codes_single():
    from app.config import Settings
    s = Settings(database_url="db://test", deepseek_api_key="placeholder-key",
                 siliconflow_api_key="placeholder-key", admin_password="placeholder-password",
                 invite_codes=["code1"])
    assert s.invite_codes == ["code1"]


def test_settings_invite_codes_multiple():
    from app.config import Settings
    s = Settings(database_url="db://test", deepseek_api_key="placeholder-key",
                 siliconflow_api_key="placeholder-key", admin_password="placeholder-password",
                 invite_codes=["a", "b", "c"])
    assert len(s.invite_codes) == 3


def test_settings_invite_codes_default():
    from app.config import Settings
    s = Settings(database_url="db://test", deepseek_api_key="placeholder-key",
                 siliconflow_api_key="placeholder-key", admin_password="placeholder-password")
    assert "sga-2026-invite" in s.invite_codes


# ─── validate() ───

def test_validate_all_present():
    from app.config import Settings, validate
    import app.config as mod
    orig = mod.settings
    try:
        mod.settings = Settings(database_url="db://t", deepseek_api_key="placeholder-key-1",
                                siliconflow_api_key="placeholder-key-2", admin_password="placeholder-pw")
        missing = validate()
        assert missing == []
    finally:
        mod.settings = orig


def test_validate_missing_keys():
    from app.config import Settings, validate
    import app.config as mod
    orig = mod.settings
    try:
        mod.settings = Settings(database_url="db://t", deepseek_api_key="",
                                siliconflow_api_key="", admin_password="")
        missing = validate()
        assert "DEEPSEEK_API_KEY" in missing
        assert "SILICONFLOW_API_KEY" in missing
        assert "ADMIN_PASSWORD" in missing
    finally:
        mod.settings = orig


def test_validate_partial():
    from app.config import Settings, validate
    import app.config as mod
    orig = mod.settings
    try:
        mod.settings = Settings(database_url="db://t", deepseek_api_key="ok",
                                siliconflow_api_key="", admin_password="placeholder-ok")
        missing = validate()
        assert missing == ["SILICONFLOW_API_KEY"]
    finally:
        mod.settings = orig


# ─── health() ───

def test_health_endpoint():
    from app.main import health
    async def run():
        result = await health()
        assert result == {"status": "ok"}
    asyncio.run(run())


# ─── Run all ───

if __name__ == "__main__":
    import traceback

    tests = [
        (name, obj) for name, obj in globals().items()
        if name.startswith("test_") and callable(obj)
    ]
    passed = 0
    failed = 0
    for name, fn in tests:
        try:
            fn()
            passed += 1
            print(f"  PASS {name}")
        except Exception:
            failed += 1
            print(f"  FAIL {name}")
            traceback.print_exc()

    print(f"\n{passed} passed, {failed} failed, {len(tests)} total")
    if failed:
        sys.exit(1)
