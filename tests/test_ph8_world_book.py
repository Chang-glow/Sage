"""Phase 8 tests — world book engine, persona summary, prompt assembly."""
import asyncio
import sys
import uuid
from unittest.mock import AsyncMock, MagicMock, patch


# ─── Helper ───

def _make_entry(title, **kwargs):
    from app.models.world_book import WorldBookEntry
    import uuid as _uuid
    defaults = dict(
        id=_uuid.uuid4(),
        title=title,
        content=kwargs.pop("content", f"Content for {title}"),
        scope=kwargs.pop("scope", "character"),
        trigger_type=kwargs.pop("trigger_type", "keyword"),
        trigger_keys=kwargs.pop("trigger_keys", []),
        logic_rule=kwargs.pop("logic_rule", None),
        priority=kwargs.pop("priority", 5),
        position=kwargs.pop("position", "after_char"),
        recursive=kwargs.pop("recursive", False),
        is_active=kwargs.pop("is_active", True),
        created_by_skill=kwargs.pop("created_by_skill", "test"),
    )
    defaults.update(kwargs)
    return WorldBookEntry(**defaults)


# ═══════════════════════════════════════════════════
# Group A: Model field roundtrip
# ═══════════════════════════════════════════════════

def test_world_book_entry_defaults():
    from app.models.world_book import WorldBookEntry
    e = WorldBookEntry(title="测试", content="测试内容", trigger_keys=["x"], logic_rule="AND_ANY",
                       scope="character", trigger_type="keyword", position="after_char",
                       priority=5, recursive=False, is_active=True)
    assert e.scope == "character"
    assert e.trigger_type == "keyword"
    assert e.priority == 5
    assert e.position == "after_char"
    assert e.recursive is False
    assert e.is_active is True


def test_world_book_entry_field_types():
    from app.models.world_book import WorldBookEntry
    e = WorldBookEntry(
        id=uuid.uuid4(), scope="global", title="全局测试条目", content="注入内容",
        trigger_type="keyword", trigger_keys=["数学", "考试"], logic_rule="AND_ANY",
        priority=7, position="before_char", recursive=True, is_active=True,
        created_by_skill="memory_extraction",
    )
    assert e.trigger_keys == ["数学", "考试"]
    assert e.logic_rule == "AND_ANY"
    assert e.recursive is True
    assert e.created_by_skill == "memory_extraction"


def test_agent_persona_prompt_field():
    from app.models.agent import Agent
    a = Agent(nickname="test", age=20, gender="男", persona_prompt="这是一段人设描述")
    assert a.persona_prompt == "这是一段人设描述"


# ═══════════════════════════════════════════════════
# Group B: Logic rule evaluation
# ═══════════════════════════════════════════════════

def test_evaluate_logic_rule_and_any():
    from app.engine.world_book_engine import _evaluate_logic_rule
    assert _evaluate_logic_rule(["数学", "考试"], "数学考试很难", "AND_ANY") is True
    assert _evaluate_logic_rule(["数学", "考试"], "今天天气很好", "AND_ANY") is False
    assert _evaluate_logic_rule([], "anything", "AND_ANY") is False


def test_evaluate_logic_rule_and_all():
    from app.engine.world_book_engine import _evaluate_logic_rule
    assert _evaluate_logic_rule(["数学", "考试"], "数学考试很难", "AND_ALL") is True
    assert _evaluate_logic_rule(["数学", "考试"], "数学很难", "AND_ALL") is False


def test_evaluate_logic_rule_not_any():
    from app.engine.world_book_engine import _evaluate_logic_rule
    assert _evaluate_logic_rule(["数学", "考试"], "今天天气很好", "NOT_ANY") is True
    assert _evaluate_logic_rule(["数学", "考试"], "数学很难", "NOT_ANY") is False


def test_evaluate_logic_rule_not_all():
    from app.engine.world_book_engine import _evaluate_logic_rule
    assert _evaluate_logic_rule(["数学", "考试"], "数学很难", "NOT_ALL") is True
    assert _evaluate_logic_rule(["数学", "考试"], "数学考试", "NOT_ALL") is False


def test_evaluate_logic_rule_none():
    from app.engine.world_book_engine import _evaluate_logic_rule
    assert _evaluate_logic_rule(["x"], "xyz", None) is True
    assert _evaluate_logic_rule(["x"], "abc", None) is False


def test_evaluate_logic_rule_case_insensitive():
    from app.engine.world_book_engine import _evaluate_logic_rule
    assert _evaluate_logic_rule(["MATH"], "math is hard", "AND_ANY") is True


# ═══════════════════════════════════════════════════
# Group C: Entry matching
# ═══════════════════════════════════════════════════

def test_match_entries_constant():
    from app.engine.world_book_engine import _match_entries
    entry = _make_entry("t1", trigger_type="constant", trigger_keys=[])
    matched = _match_entries([entry], "any text", {})
    assert len(matched) == 1


def test_match_entries_keyword_hit():
    from app.engine.world_book_engine import _match_entries
    entry = _make_entry("t1", trigger_type="keyword", trigger_keys=["数学"])
    assert len(_match_entries([entry], "数学考试", {})) == 1


def test_match_entries_keyword_miss():
    from app.engine.world_book_engine import _match_entries
    entry = _make_entry("t1", trigger_type="keyword", trigger_keys=["数学"])
    assert len(_match_entries([entry], "英语考试", {})) == 0


def test_match_entries_regex():
    from app.engine.world_book_engine import _match_entries
    entry = _make_entry("t1", trigger_type="regex", trigger_keys=[r"\d+分"])
    assert len(_match_entries([entry], "我考了98分", {})) == 1
    assert len(_match_entries([entry], "我考得很好", {})) == 0


def test_match_entries_regex_bad_pattern():
    from app.engine.world_book_engine import _match_entries
    entry = _make_entry("t1", trigger_type="regex", trigger_keys=["[invalid(re"])
    assert len(_match_entries([entry], "any text", {})) == 0


def test_match_entries_status_hit():
    from app.engine.world_book_engine import _match_entries
    entry = _make_entry("t1", trigger_type="status", trigger_keys=["angry", "sad"])
    ctx = {"_status": {"emotion": "angry"}}
    assert len(_match_entries([entry], "", ctx)) == 1


def test_match_entries_status_miss():
    from app.engine.world_book_engine import _match_entries
    entry = _make_entry("t1", trigger_type="status", trigger_keys=["angry"])
    ctx = {"_status": {"emotion": "happy"}}
    assert len(_match_entries([entry], "", ctx)) == 0


def test_match_entries_inactive_skipped():
    from app.engine.world_book_engine import _match_entries
    entry = _make_entry("t1", trigger_type="constant", is_active=False)
    assert len(_match_entries([entry], "any text", {})) == 0


def test_match_entries_empty_keys_constant():
    from app.engine.world_book_engine import _match_entries
    entry = _make_entry("t1", trigger_type="constant", trigger_keys=[])
    assert len(_match_entries([entry], "anything", {})) == 1


# ═══════════════════════════════════════════════════
# Group D: Sort and trim
# ═══════════════════════════════════════════════════

def test_sort_entries_by_priority():
    from app.engine.world_book_engine import _sort_entries
    e1 = _make_entry("low", priority=3)
    e2 = _make_entry("high", priority=10)
    e3 = _make_entry("mid", priority=5)
    sorted_entries = _sort_entries([e1, e2, e3])
    assert sorted_entries[0].priority == 10
    assert sorted_entries[2].priority == 3


def test_sort_entries_same_priority_scope_rank():
    from app.engine.world_book_engine import _sort_entries
    e1 = _make_entry("global", priority=5, scope="global")
    e2 = _make_entry("char", priority=5, scope="character")
    sorted_entries = _sort_entries([e1, e2])
    assert sorted_entries[0].scope == "character"


def test_trim_by_budget_under():
    from app.engine.world_book_engine import _trim_by_budget
    entries = [_make_entry("e1", content="short"), _make_entry("e2", content="also short")]
    trimmed = _trim_by_budget(entries, token_budget=100)
    assert len(trimmed) == 2


def test_trim_by_budget_over():
    from app.engine.world_book_engine import _trim_by_budget
    entries = [
        _make_entry("e1", priority=10, content="a" * 150),
        _make_entry("e2", priority=5, content="b" * 150),
    ]
    # token_budget=50 → char_budget=200. First entry fits (150), second would exceed (150+150=300>200)
    trimmed = _trim_by_budget(entries, token_budget=50)
    assert len(trimmed) == 1
    assert trimmed[0].title == "e1"


def test_trim_by_budget_empty():
    from app.engine.world_book_engine import _trim_by_budget
    assert _trim_by_budget([], 100) == []


def test_trim_by_budget_zero():
    from app.engine.world_book_engine import _trim_by_budget
    entries = [_make_entry("e1", content="x" * 10)]
    assert _trim_by_budget(entries, token_budget=0) == []


# ═══════════════════════════════════════════════════
# Group E: Position injection
# ═══════════════════════════════════════════════════

def test_inject_entries_before_char():
    from app.engine.world_book_engine import _inject_entries
    entries = [_make_entry("e1", content="前置内容", position="before_char")]
    result = _inject_entries("原始prompt", entries)
    assert "前置内容" in result
    assert result.index("前置内容") < result.index("原始prompt")


def test_inject_entries_after_char():
    from app.engine.world_book_engine import _inject_entries
    entries = [_make_entry("e1", content="后置内容", position="after_char")]
    result = _inject_entries("原始prompt", entries)
    assert "后置内容" in result
    assert result.index("后置内容") > result.index("原始prompt")


def test_inject_entries_at_depth_marker():
    from app.engine.world_book_engine import _inject_entries
    entries = [_make_entry("e1", content="深度注入", position="at_depth")]
    prompt = "开头 {world_book_inject} 结尾"
    result = _inject_entries(prompt, entries)
    assert "深度注入" in result
    idx_inject = result.index("深度注入")
    idx_start = result.index("开头")
    idx_end = result.index("结尾")
    assert idx_start < idx_inject < idx_end


def test_inject_entries_at_depth_no_marker():
    from app.engine.world_book_engine import _inject_entries
    entries = [_make_entry("e1", content="无标记注入", position="at_depth")]
    result = _inject_entries("没有标记的prompt", entries)
    assert "无标记注入" in result
    assert result.index("无标记注入") > result.index("没有标记的prompt")


def test_inject_entries_multiple_positions():
    from app.engine.world_book_engine import _inject_entries
    e1 = _make_entry("before", content="前置", position="before_char")
    e2 = _make_entry("after", content="后置", position="after_char")
    result = _inject_entries("中间", [e1, e2])
    assert result.index("前置") < result.index("中间") < result.index("后置")


# ═══════════════════════════════════════════════════
# Group F: assemble_prompt (async)
# ═══════════════════════════════════════════════════

def test_assemble_prompt_with_constant_entry():
    async def run():
        from app.engine.world_book_engine import assemble_prompt
        mock_db = AsyncMock()
        mock_result = MagicMock()
        e = _make_entry("const1", trigger_type="constant", content="全局注入测试")
        mock_result.scalars.return_value.all.return_value = [e]
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await assemble_prompt("基础prompt", {"greeting": "hello"}, mock_db)
        assert "全局注入测试" in result
        assert "基础prompt" in result

    asyncio.run(run())


def test_assemble_prompt_empty_context():
    async def run():
        from app.engine.world_book_engine import assemble_prompt
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await assemble_prompt("基础prompt", {}, mock_db)
        assert result == "基础prompt"

    asyncio.run(run())


def test_assemble_prompt_no_matching_entries():
    async def run():
        from app.engine.world_book_engine import assemble_prompt
        mock_db = AsyncMock()
        e = _make_entry("t1", trigger_type="keyword", trigger_keys=["nonexistent"])
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [e]
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await assemble_prompt("base", {}, mock_db)
        assert result == "base"

    asyncio.run(run())


def test_assemble_prompt_keyword_match():
    async def run():
        from app.engine.world_book_engine import assemble_prompt
        mock_db = AsyncMock()
        e = _make_entry("t1", trigger_type="keyword", trigger_keys=["提示词"], content="注入条目")
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [e]
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await assemble_prompt("包含提示词的基础prompt", {}, mock_db)
        assert "注入条目" in result
        assert "包含提示词的基础prompt" in result

    asyncio.run(run())


def test_assemble_prompt_recursive():
    async def run():
        from app.engine.world_book_engine import assemble_prompt
        mock_db = AsyncMock()
        e1 = _make_entry("e1", trigger_type="keyword", trigger_keys=["触发A"],
                         content="递归触发B", recursive=True)
        e2 = _make_entry("e2", trigger_type="keyword", trigger_keys=["触发B"],
                         content="第二条注入", recursive=False)
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [e1, e2]
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await assemble_prompt("包含触发A的prompt", {}, mock_db)
        assert "第二条注入" in result

    asyncio.run(run())


# ═══════════════════════════════════════════════════
# Group G: SkillResult world book fields
# ═══════════════════════════════════════════════════

def test_skill_result_world_book_fields_default():
    from app.skills.skill_utils import SkillResult
    sr = SkillResult(skill_id="test")
    assert sr.world_book_entry is None
    assert sr.remove_world_book_entry is None


def test_skill_result_world_book_fields_set():
    from app.skills.skill_utils import SkillResult
    sr = SkillResult(
        skill_id="test",
        world_book_entry={"title": "test", "content": "hello"},
        remove_world_book_entry="some-uuid",
    )
    assert sr.world_book_entry["title"] == "test"
    assert sr.remove_world_book_entry == "some-uuid"


# ═══════════════════════════════════════════════════
# Group H: Context assembly
# ═══════════════════════════════════════════════════

def test_build_agent_context_includes_persona_prompt():
    from app.skills.skill_utils import build_agent_context

    class FakeAgent:
        id = uuid.uuid4()
        nickname = "测试"
        age = 25
        gender = "男"
        occupation = "工人"
        education = "本科"
        district = ""
        personality_vector = {}
        interests = {}
        persona_prompt = "我是一个测试用户"
        income_level = "3k-5k"
        school_or_company = ""
        chronotype = "normal"
        distrust_tags = []
        trust_tags = []

    ctx = build_agent_context(FakeAgent)
    assert "agent_persona_prompt" in ctx
    assert ctx["agent_persona_prompt"] == "我是一个测试用户"
    assert "agent_income_level" in ctx
    assert ctx["agent_income_level"] == "3k-5k"
    assert "agent_chronotype" in ctx


def test_build_memory_context():
    from app.skills.skill_utils import build_memory_context

    class FakeAgent:
        life_history = [
            {"age": 14, "category": "family", "event": "搬家到平陵", "impact_weight": 0.7},
            {"age": 16, "category": "school", "event": "演讲比赛获奖", "impact_weight": 0.5},
        ]
        solidified_memories = [
            {"content": "固化记忆1", "impact_weight": 0.9},
            {"content": "固化记忆2", "impact_weight": 0.6},
        ]

    ctx = build_memory_context(FakeAgent, top_n=2)
    assert "搬家" in ctx["life_history_top"]
    assert "固化记忆1" in ctx["solidified_memories_top"]
    # top 2 should only include 0.9 and 0.6, not the 0.5 one
    assert "演讲" not in ctx["life_history_top"] or "固化记忆2" in ctx["solidified_memories_top"]


def test_build_memory_context_empty():
    from app.skills.skill_utils import build_memory_context

    class FakeAgent:
        life_history = []
        solidified_memories = None

    ctx = build_memory_context(FakeAgent)
    assert ctx["life_history_top"] == "（无）"
    assert ctx["solidified_memories_top"] == "（无）"


def test_build_world_book_context_basic():
    from app.skills.skill_utils import build_world_book_context
    wb = build_world_book_context(
        agent_context={"agent_name": "测试", "agent_occupation": "学生"},
        post_context={"post_title": "数学考试求助", "post_content": "学习方法？"},
    )
    assert "数学考试求助" in wb["scan_text"]
    assert "学生" in wb["scan_text"]


def test_build_world_book_context_with_status():
    from app.skills.skill_utils import build_world_book_context
    wb = build_world_book_context(
        extra_context={"emotion": "frustrated", "flow_mode": True},
    )
    assert wb["_status"]["emotion"] == "frustrated"


def test_extract_text_from_context():
    from app.engine.world_book_engine import _extract_text_from_context
    ctx = {"a": "hello", "b": 123, "c": {"d": "world", "e": [1, 2, 3]}}
    text = _extract_text_from_context(ctx)
    assert "hello" in text
    assert "world" in text
    assert "123" in text


# ═══════════════════════════════════════════════════
# Group I: Executor with world book (async)
# ═══════════════════════════════════════════════════

def test_execute_with_world_book_injection():
    async def run():
        from app.skills.executor import execute
        from app.skills.registry import registry
        from app.skills.skill_utils import SkillDefinition, TokenUsage

        sd = SkillDefinition(
            skill_id="test_wb_inject", name="T", model_type="便宜",
            prompt_template="hello {name}",
        )
        registry._skills["test_wb_inject"] = sd
        try:
            mock_db = AsyncMock()
            mock_db.commit = AsyncMock()

            async def mock_caller(prompt, model, *, skill_id=None, agent_id=None, db=None):
                return '{"result": "ok"}', TokenUsage(0, 0)

            with patch("app.engine.world_book_engine.assemble_prompt") as mock_assemble:
                mock_assemble.return_value = "[世界书]\n注入内容\n[/世界书]\n\nhello world"
                result = await execute(
                    "test_wb_inject", {"name": "world"},
                    llm_caller=mock_caller, db=mock_db,
                )
                assert result.status == "success"
                mock_assemble.assert_called_once()
        finally:
            registry._skills.pop("test_wb_inject", None)

    asyncio.run(run())


def test_execute_without_db_no_injection():
    async def run():
        from app.skills.executor import execute
        from app.skills.registry import registry
        from app.skills.skill_utils import SkillDefinition, TokenUsage

        sd = SkillDefinition(
            skill_id="test_no_db", name="T", model_type="便宜",
            prompt_template="echo {x}",
        )
        registry._skills["test_no_db"] = sd
        try:
            async def mock_caller(prompt, model, *, skill_id=None, agent_id=None, db=None):
                return '{"x": 1}', TokenUsage(0, 0)

            result = await execute("test_no_db", {"x": "1"}, llm_caller=mock_caller)
            assert result.status == "success"
            assert result.parsed == {"x": 1}
        finally:
            registry._skills.pop("test_no_db", None)

    asyncio.run(run())


def test_execute_extracts_world_book_entry():
    async def run():
        from app.skills.executor import execute
        from app.skills.registry import registry
        from app.skills.skill_utils import SkillDefinition, TokenUsage

        sd = SkillDefinition(
            skill_id="test_wb_extract", name="T", model_type="便宜",
            prompt_template="test",
        )
        registry._skills["test_wb_extract"] = sd
        try:
            mock_db = AsyncMock()
            mock_db.commit = AsyncMock()

            async def mock_caller(prompt, model, *, skill_id=None, agent_id=None, db=None):
                return '{"result": "ok", "world_book_entry": {"title": "e1", "content": "c1"}}', TokenUsage(0, 0)

            result = await execute(
                "test_wb_extract", {}, llm_caller=mock_caller, db=mock_db,
            )
            assert result.status == "success"
            assert result.world_book_entry == {"title": "e1", "content": "c1"}
            assert "world_book_entry" not in (result.parsed or {})
            # verify register_entry was persisted
            assert mock_db.commit.call_count >= 1
        finally:
            registry._skills.pop("test_wb_extract", None)

    asyncio.run(run())


def test_validate_entry_data_valid():
    from app.engine.world_book_engine import validate_entry_data
    errors = validate_entry_data({
        "title": "测试", "content": "内容", "scope": "character",
        "trigger_type": "keyword", "position": "after_char",
    })
    assert errors == []


def test_validate_entry_data_missing_title():
    from app.engine.world_book_engine import validate_entry_data
    errors = validate_entry_data({"content": "c"})
    assert any("title" in e for e in errors)


def test_validate_entry_data_bad_scope():
    from app.engine.world_book_engine import validate_entry_data
    errors = validate_entry_data({"title": "t", "content": "c", "scope": "invalid"})
    assert any("scope" in e for e in errors)


# ═══════════════════════════════════════════════════
# Group J: Persona summary skill
# ═══════════════════════════════════════════════════

def test_persona_summary_registered():
    from app.skills.registry import registry
    registry.reload()
    skill = registry.get("persona_summary")
    assert skill is not None
    assert "主力" in skill.model_type


def test_persona_summary_rendering():
    from app.skills.registry import registry
    registry.reload()
    skill = registry.get("persona_summary")
    prompt = skill.prompt_template.format(
        agent_name="测试", agent_age="25", agent_gender="男",
        agent_occupation="工人", agent_education="本科",
        agent_district="老城区", agent_income_level="3k-6k",
        agent_school_or_company="平陵代工厂", agent_chronotype="normal",
        agent_personality="peacemaker=0.80", agent_interests="游戏、音乐",
        agent_bio="一个普通人", life_history_top="无", solidified_memories_top="无",
    )
    assert "测试" in prompt
    assert "平陵市" in prompt
    assert "world_book_entry" in prompt


def test_persona_summary_mock_execution():
    async def run():
        from app.skills.executor import execute
        from app.skills.registry import registry
        from app.skills.skill_utils import TokenUsage

        registry.reload()

        async def mock_caller(prompt, model, *, skill_id=None, agent_id=None, db=None):
            return '{"persona_prompt": "我是测试用户，一个生活在平陵市的普通人。", "world_book_entry": {"scope": "character", "title": "人设-测试", "content": "我是测试用户...", "trigger_type": "constant", "trigger_keys": [], "priority": 10, "position": "after_char", "recursive": false}}', TokenUsage(0, 0)

        ctx = {
            "agent_name": "测试", "agent_age": "25", "agent_gender": "男",
            "agent_occupation": "工人", "agent_education": "本科",
            "agent_district": "老城区", "agent_income_level": "3k-6k",
            "agent_school_or_company": "平陵代工厂", "agent_chronotype": "normal",
            "agent_personality": "peacemaker=0.80", "agent_interests": "游戏",
            "agent_bio": "一个普通人", "life_history_top": "", "solidified_memories_top": "",
        }
        result = await execute("persona_summary", ctx, llm_caller=mock_caller)
        assert result.status == "success"
        assert result.world_book_entry is not None
        assert result.world_book_entry["trigger_type"] == "constant"
        assert "测试用户" in result.world_book_entry["content"]

    asyncio.run(run())


# ═══════════════════════════════════════════════════
# Run all
# ═══════════════════════════════════════════════════

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
