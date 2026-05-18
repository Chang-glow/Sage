"""Phase 3 tests — Skill engine: registry, executor, llm_manager, skill_utils."""
import sys
import tempfile
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch


# ═══════════════════════════════════════════════════
# registry.py — _TITLE_RE
# ═══════════════════════════════════════════════════

def test_title_re_valid():
    from app.skills.registry import _TITLE_RE
    m = _TITLE_RE.match("# Skill: 回复决策 (reply_decision)")
    assert m is not None
    assert m.group(1) == "回复决策"
    assert m.group(2) == "reply_decision"


def test_title_re_english_name():
    from app.skills.registry import _TITLE_RE
    m = _TITLE_RE.match("# Skill: Agent Registration (agent_registration)")
    assert m is not None
    assert m.group(1) == "Agent Registration"
    assert m.group(2) == "agent_registration"


def test_title_re_no_match():
    from app.skills.registry import _TITLE_RE
    assert _TITLE_RE.match("Just some text") is None
    assert _TITLE_RE.match("## Skill: foo (bar)") is None


# ═══════════════════════════════════════════════════
# registry.py — _parse_skillmd
# ═══════════════════════════════════════════════════

def _write_skillmd(dir_path: Path, name: str, content: str) -> Path:
    sub = dir_path / name
    sub.mkdir(parents=True, exist_ok=True)
    p = sub / "SKILL.md"
    p.write_text(content, encoding="utf-8")
    return p


def test_parse_skillmd_valid():
    from app.skills.registry import _parse_skillmd
    with tempfile.TemporaryDirectory() as td:
        p = _write_skillmd(Path(td), "test_skill", """# Skill: 测试技能 (test_skill)
## 触发条件
当需要测试时触发
## 模型
- 类型：便宜
## 输入
无
## 输出格式
JSON
## Prompt 模板
请回复 {name} 的测试结果
## 备注
仅用于测试
""")
        skill = _parse_skillmd(p)
        assert skill is not None
        assert skill.skill_id == "test_skill"
        assert skill.name == "测试技能"
        assert skill.model_type == "便宜"
        assert skill.output_format == "JSON"
        assert "{name}" in skill.prompt_template
        assert skill.trigger_condition == "当需要测试时触发"


def test_parse_skillmd_main_model():
    from app.skills.registry import _parse_skillmd
    with tempfile.TemporaryDirectory() as td:
        p = _write_skillmd(Path(td), "main_skill", """# Skill: 主力技能 (main_skill)
## 模型
- 类型：主力
## 输出格式
JSON
## Prompt 模板
hello
""")
        skill = _parse_skillmd(p)
        assert skill is not None
        assert skill.model_type == "主力"


def test_parse_skillmd_text_output():
    from app.skills.registry import _parse_skillmd
    with tempfile.TemporaryDirectory() as td:
        p = _write_skillmd(Path(td), "text_skill", """# Skill: 文本技能 (text_skill)
## 输出格式
text
## Prompt 模板
hello
""")
        skill = _parse_skillmd(p)
        assert skill is not None
        assert skill.output_format == "text"


def test_parse_skillmd_non_matching_first_line():
    """File with a first line that doesn't match the title pattern returns None."""
    from app.skills.registry import _parse_skillmd
    with tempfile.TemporaryDirectory() as td:
        p = _write_skillmd(Path(td), "bad_title", "No title here\n## Prompt 模板\nhello\n")
        assert _parse_skillmd(p) is None


def test_parse_skillmd_missing_sections():
    from app.skills.registry import _parse_skillmd
    with tempfile.TemporaryDirectory() as td:
        p = _write_skillmd(Path(td), "minimal", "# Skill: 最小 (minimal)\n## Prompt 模板\nhello\n")
        skill = _parse_skillmd(p)
        assert skill is not None
        assert skill.trigger_condition == ""
        assert skill.notes == ""


# ═══════════════════════════════════════════════════
# registry.py — SkillRegistry
# ═══════════════════════════════════════════════════

def test_registry_singleton():
    from app.skills.registry import SkillRegistry
    SkillRegistry.reset_instance()
    r1 = SkillRegistry()
    r2 = SkillRegistry()
    assert r1 is r2


def test_registry_load_all_and_get():
    from app.skills.registry import SkillRegistry
    SkillRegistry.reset_instance()
    with tempfile.TemporaryDirectory() as td:
        skills_dir = Path(td)
        _write_skillmd(skills_dir, "s1", "# Skill: S1 (s1)\n## Prompt 模板\nhello {x}\n## 输出格式\nJSON\n")
        _write_skillmd(skills_dir, "s2", "# Skill: S2 (s2)\n## Prompt 模板\nworld\n## 输出格式\ntext\n")

        r = SkillRegistry()
        count = r.load_all(skills_dir)
        assert count == 2
        assert r.get("s1").name == "S1"
        assert r.get("s2").output_format == "text"
        assert r.list_ids() == ["s1", "s2"]


def test_registry_get_missing():
    from app.skills.registry import SkillRegistry
    SkillRegistry.reset_instance()
    r = SkillRegistry()
    try:
        r.get("nonexistent")
        assert False, "should raise KeyError"
    except KeyError:
        pass


def test_registry_reload():
    from app.skills.registry import SkillRegistry
    SkillRegistry.reset_instance()
    with tempfile.TemporaryDirectory() as td:
        skills_dir = Path(td)
        _write_skillmd(skills_dir, "a", "# Skill: A (a)\n## Prompt 模板\nhello\n## 输出格式\nJSON\n")

        r = SkillRegistry()
        r.load_all(skills_dir)
        assert len(r.list_ids()) == 1

        r.reload(skills_dir)
        assert len(r.list_ids()) == 1


def test_registry_empty_dir():
    from app.skills.registry import SkillRegistry
    SkillRegistry.reset_instance()
    with tempfile.TemporaryDirectory() as td:
        r = SkillRegistry()
        count = r.load_all(Path(td))
        assert count == 0
        assert r.list_ids() == []


# ═══════════════════════════════════════════════════
# skill_utils.py — dataclasses + context builders
# ═══════════════════════════════════════════════════

def test_skill_definition_defaults():
    from app.skills.skill_utils import SkillDefinition
    sd = SkillDefinition(skill_id="test", name="Test", model_type="便宜", prompt_template="hello")
    assert sd.output_format == "JSON"
    assert sd.output_schema is None
    assert sd.trigger_condition == ""
    assert sd.notes == ""


def test_skill_result_defaults():
    from app.skills.skill_utils import SkillResult
    sr = SkillResult(skill_id="test")
    assert sr.status == "success"
    assert sr.raw_response == ""
    assert sr.tokens_used == 0


def test_build_agent_context_basic():
    from app.skills.skill_utils import build_agent_context

    class FakeAgent:
        id = uuid.UUID("a" * 32)
        nickname = "测试"
        age = 25
        gender = "男"
        occupation = "工人"
        education = "本科"
        district = "平陵市"
        personality_vector = {"peacemaker": 0.8, "openness": 0.7, "hothead": 0.3}
        interests = {"categories": ["游戏", "音乐", "电影"]}

    ctx = build_agent_context(FakeAgent)
    assert ctx["agent_name"] == "测试"
    assert ctx["agent_age"] == 25
    assert "peacemaker" in ctx["agent_personality"]
    assert "游戏" in ctx["agent_interests"]


def test_build_agent_context_none_fields():
    from app.skills.skill_utils import build_agent_context

    class FakeAgent:
        id = uuid.uuid4()
        nickname = "X"
        age = 0
        gender = ""
        occupation = None
        education = None
        district = None
        personality_vector = None
        interests = None

    ctx = build_agent_context(FakeAgent)
    assert ctx["agent_occupation"] == "未知"
    assert ctx["agent_personality"] == "普通"
    assert ctx["agent_interests"] == "广泛"


def test_build_agent_context_empty_personality():
    from app.skills.skill_utils import build_agent_context

    class FakeAgent:
        id = uuid.uuid4()
        nickname = "X"
        age = 20
        gender = "男"
        occupation = ""
        education = ""
        district = ""
        personality_vector = {}
        interests = {"categories": []}

    ctx = build_agent_context(FakeAgent)
    assert ctx["agent_personality"] == "普通"
    assert ctx["agent_interests"] == "广泛"


def test_build_post_context_basic():
    from app.skills.skill_utils import build_post_context

    class FakeAuthor:
        nickname = "作者"
    class FakeBar:
        name = "吧名"
    class FakePost:
        id = uuid.UUID("b" * 32)
        title = "标题"
        content = "内容"
        author = FakeAuthor()
        bar = FakeBar()
        author_id = uuid.uuid4()
        reply_count = 5

    ctx = build_post_context(FakePost)
    assert ctx["post_title"] == "标题"
    assert ctx["post_content"] == "内容"
    assert ctx["post_author"] == "作者"
    assert ctx["post_bar_name"] == "吧名"
    assert ctx["post_reply_count"] == 5


def test_build_post_context_none_relations():
    from app.skills.skill_utils import build_post_context

    class FakePost:
        id = uuid.uuid4()
        title = "t"
        content = "c"
        author = None
        bar = None
        author_id = uuid.uuid4()
        reply_count = 0

    ctx = build_post_context(FakePost)
    assert ctx["post_bar_name"] == ""


# ═══════════════════════════════════════════════════
# executor.py — _JSON_BLOCK_RE, _parse_response, _resolve_model
# ═══════════════════════════════════════════════════

def test_json_block_re_fenced():
    from app.skills.executor import _JSON_BLOCK_RE
    m = _JSON_BLOCK_RE.search('```json\n{"a": 1}\n```')
    assert m is not None
    assert '"a": 1' in m.group(1)


def test_json_block_re_no_lang():
    from app.skills.executor import _JSON_BLOCK_RE
    m = _JSON_BLOCK_RE.search('```\n{"b": 2}\n```')
    assert m is not None
    assert '"b": 2' in m.group(1)


def test_parse_response_json_fence():
    from app.skills.executor import _parse_response
    result = _parse_response('```json\n{"key": "val"}\n```', "JSON")
    assert result == {"key": "val"}


def test_parse_response_raw_json():
    from app.skills.executor import _parse_response
    result = _parse_response('some text {"x": 1, "y": 2} more text', "JSON")
    assert result == {"x": 1, "y": 2}


def test_parse_response_text():
    from app.skills.executor import _parse_response
    result = _parse_response("just plain text", "text")
    assert result == "just plain text"


def test_parse_response_invalid_json():
    from app.skills.executor import _parse_response
    import json
    try:
        _parse_response("not json at all", "JSON")
        assert False, "should raise"
    except json.JSONDecodeError:
        pass


def test_resolve_model_main():
    # _resolve_model depends on yaml_config; monkeypatch it
    import app.skills.executor as ex_mod
    orig = ex_mod.yaml_config
    try:
        fake_cfg = MagicMock()
        fake_cfg.llm.default_main_model = "deepseek-chat"
        fake_cfg.llm.default_cheap_model = "cheap-model"
        ex_mod.yaml_config = fake_cfg
        assert ex_mod._resolve_model("主力") == "deepseek-chat"
    finally:
        ex_mod.yaml_config = orig


def test_resolve_model_cheap():
    import app.skills.executor as ex_mod
    orig = ex_mod.yaml_config
    try:
        fake_cfg = MagicMock()
        fake_cfg.llm.default_main_model = "deepseek-chat"
        fake_cfg.llm.default_cheap_model = "cheap-model"
        ex_mod.yaml_config = fake_cfg
        assert ex_mod._resolve_model("便宜") == "cheap-model"
    finally:
        ex_mod.yaml_config = orig


# ═══════════════════════════════════════════════════
# llm_manager.py — _is_retryable, tokens, MockLLM, create_llm_caller
# ═══════════════════════════════════════════════════

def test_is_retryable_timeout():
    from app.skills.llm_manager import _is_retryable
    import httpx
    assert _is_retryable(httpx.TimeoutException("timeout")) is True


def test_is_retryable_429():
    from app.skills.llm_manager import _is_retryable
    import httpx
    resp = MagicMock()
    resp.status_code = 429
    exc = httpx.HTTPStatusError("too many", request=MagicMock(), response=resp)
    assert _is_retryable(exc) is True


def test_is_retryable_500():
    from app.skills.llm_manager import _is_retryable
    import httpx
    resp = MagicMock()
    resp.status_code = 500
    exc = httpx.HTTPStatusError("error", request=MagicMock(), response=resp)
    assert _is_retryable(exc) is True


def test_is_retryable_400_not():
    from app.skills.llm_manager import _is_retryable
    import httpx
    resp = MagicMock()
    resp.status_code = 400
    exc = httpx.HTTPStatusError("bad request", request=MagicMock(), response=resp)
    assert _is_retryable(exc) is False


def test_is_retryable_value_error_not():
    from app.skills.llm_manager import _is_retryable
    assert _is_retryable(ValueError("not retryable")) is False


def test_track_tokens():
    from app.skills.llm_manager import _track_tokens, reset_token_counters, _token_usage
    reset_token_counters()
    _track_tokens("agent-1", 100, 50)
    assert _token_usage["_global"] == 150
    assert _token_usage["agent-1"] == 150


def test_track_tokens_multiple_agents():
    from app.skills.llm_manager import _track_tokens, reset_token_counters, _token_usage
    reset_token_counters()
    _track_tokens("a", 10, 5)
    _track_tokens("b", 20, 10)
    assert _token_usage["_global"] == 45
    assert _token_usage["a"] == 15
    assert _token_usage["b"] == 30


def test_check_token_limit_under():
    from app.skills.llm_manager import _track_tokens, check_token_limit, reset_token_counters
    import app.skills.llm_manager as llm_mod
    reset_token_counters()
    orig = llm_mod.yaml_config
    try:
        fake = MagicMock()
        fake.security.global_token_limit = 10000
        fake.security.default_agent_token_limit = 1000
        llm_mod.yaml_config = fake
        assert check_token_limit() is True
        assert check_token_limit("agent-x") is True
    finally:
        llm_mod.yaml_config = orig


def test_check_token_limit_exceeded_global():
    from app.skills.llm_manager import _track_tokens, check_token_limit, reset_token_counters
    import app.skills.llm_manager as llm_mod
    reset_token_counters()
    _track_tokens(None, 10000, 0)
    orig = llm_mod.yaml_config
    try:
        fake = MagicMock()
        fake.security.global_token_limit = 10000
        fake.security.default_agent_token_limit = 1000
        llm_mod.yaml_config = fake
        assert check_token_limit() is False
    finally:
        llm_mod.yaml_config = orig


def test_reset_token_counters():
    from app.skills.llm_manager import _track_tokens, reset_token_counters, _token_usage
    _track_tokens("x", 100, 100)
    reset_token_counters()
    assert _token_usage == {"_global": 0}


def test_default_mock_responses():
    from app.skills.llm_manager import _default_mock_responses
    responses = _default_mock_responses()
    assert "reply_decision" in responses
    assert "offline_summary" in responses
    assert "post_decision" in responses
    assert "agent_registration" in responses


def test_mock_llm_call_known_skill():
    from app.skills.llm_manager import MockLLM
    import asyncio

    async def run():
        mock = MockLLM()
        resp = await mock.call("prompt", "model", skill_id="reply_decision")
        assert "will_reply" in resp

    asyncio.run(run())


def test_mock_llm_call_unknown_skill():
    from app.skills.llm_manager import MockLLM
    import asyncio

    async def run():
        mock = MockLLM()
        resp = await mock.call("prompt", "model", skill_id="unknown")
        assert "mock_response" in resp

    asyncio.run(run())


# ═══════════════════════════════════════════════════
# executor.py — execute() happy path and error paths
# ═══════════════════════════════════════════════════

def test_execute_skill_not_found():
    from app.skills.executor import execute
    import asyncio

    async def run():
        result = await execute("nonexistent_skill_xyz", {})
        assert result.status == "render_failure"
        assert "not found" in (result.error or "")

    asyncio.run(run())


def test_execute_render_failure():
    from app.skills.executor import execute
    from app.skills.registry import registry
    from app.skills.skill_utils import SkillDefinition
    import asyncio

    async def run():
        sd = SkillDefinition(skill_id="test_render", name="T", model_type="便宜",
                             prompt_template="hello {missing_key}")
        registry._skills["test_render"] = sd
        try:
            result = await execute("test_render", {})
            assert result.status == "render_failure"
        finally:
            registry._skills.pop("test_render", None)

    asyncio.run(run())


def test_execute_success_with_mock_llm():
    from app.skills.executor import execute
    from app.skills.registry import registry
    from app.skills.skill_utils import SkillDefinition
    import asyncio

    async def run():
        sd = SkillDefinition(skill_id="test_success", name="T", model_type="便宜",
                             prompt_template="hello {name}", output_format="JSON")
        registry._skills["test_success"] = sd
        try:
            async def mock_caller(prompt, model, *, skill_id=None):
                return '{"result": "ok"}'

            result = await execute("test_success", {"name": "world"}, llm_caller=mock_caller)
            assert result.status == "success"
            assert result.parsed == {"result": "ok"}
        finally:
            registry._skills.pop("test_success", None)

    asyncio.run(run())


def test_execute_parse_failure():
    from app.skills.executor import execute
    from app.skills.registry import registry
    from app.skills.skill_utils import SkillDefinition
    import asyncio

    async def run():
        sd = SkillDefinition(skill_id="test_parse", name="T", model_type="便宜",
                             prompt_template="say {word}", output_format="JSON")
        registry._skills["test_parse"] = sd
        try:
            async def mock_caller(prompt, model, *, skill_id=None):
                return "not json at all"

            result = await execute("test_parse", {"word": "hi"}, llm_caller=mock_caller)
            assert result.status == "parse_failure"
        finally:
            registry._skills.pop("test_parse", None)

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
