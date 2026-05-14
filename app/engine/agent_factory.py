from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Callable

import structlog

from app.config import config as yaml_config
from app.models.agent import Agent, AgentSchedule
from app.skills.executor import execute
from app.world.city_data import sample_interest_candidates
from app.world.location_assigner import assign_location

logger = structlog.get_logger()

# ── Step 1 age intervals ──
_AGE_INTERVALS = [
    ((14, 18), 0.35),
    ((19, 25), 0.30),
    ((26, 35), 0.20),
    ((36, 45), 0.10),
    ((46, 50), 0.05),
]

# ── Non-student occupation pool (age > 22) ──
_OCCUPATION_POOL = [
    "普工", "文员", "销售", "会计", "个体户",
    "外卖员", "快递员", "网约车司机", "医护人员", "自由职业",
]

# ── Income / education lookup ──
_INCOME_EDU_TABLE = {
    (14, 18, "学生"): ("无收入", "在读中学"),
    (19, 22, "学生"): ("无收入/兼职", "本科或专科在读"),
    (19, 22, "初入职场"): ("2k-4k", "高中/中专/大专"),
    (23, 25, "初入职场"): ("3k-6k", "大专/本科"),
    (26, 35, "职场中坚"): ("4k-10k", "高中至本科"),
    (36, 50, "中年"): ("3k-8k", "初中至本科"),
}


def _lookup_income_edu(age: int, occupation: str) -> tuple[str, str]:
    if age < 18:
        return "无收入", "在读中学"
    if age <= 22 and occupation == "学生":
        return "无收入/兼职", "本科或专科在读"
    if age <= 22:
        return "2k-4k", "高中/中专/大专"
    if age <= 25:
        return "3k-6k", "大专/本科"
    if age <= 35:
        return "4k-10k", "高中至本科"
    return "3k-8k", "初中至本科"


# ── 8-dim personality ──
PERSONALITY_TRAITS = [
    "peacemaker", "instigator", "spectator", "recluse",
    "truthseeker", "hothead", "people_pleaser", "cute_pet",
]

_TRAIT_MAX = {
    "peacemaker": 0.35, "instigator": 0.25, "spectator": 0.30,
    "recluse": 0.30, "truthseeker": 0.30, "hothead": 0.25,
    "people_pleaser": 0.30, "cute_pet": 0.35,
}

TRAIT_ADJECTIVES = {
    "peacemaker": ["温和", "包容", "好说话", "老好人"],
    "instigator": ["挑事", "看热闹不嫌事大", "毒舌", "拱火"],
    "spectator": ["佛系", "吃瓜", "旁观", "随性"],
    "recluse": ["社恐", "沉默", "内向", "潜水"],
    "truthseeker": ["理性", "较真", "严谨", "客观"],
    "hothead": ["暴躁", "冲动", "急性子", "直率"],
    "people_pleaser": ["讨好", "话痨", "热情", "迎合"],
    "cute_pet": ["可爱", "软萌", "治愈", "呆萌"],
}

CORRELATIONS = [
    ("peacemaker", "instigator", -0.6),
    ("peacemaker", "hothead", -0.4),
    ("peacemaker", "spectator", -0.2),
    ("instigator", "hothead", 0.4),
    ("instigator", "spectator", 0.3),
    ("hothead", "truthseeker", -0.4),
    ("hothead", "cute_pet", -0.5),
    ("recluse", "people_pleaser", -0.4),
    ("cute_pet", "people_pleaser", -0.3),
    ("cute_pet", "peacemaker", 0.2),
    ("truthseeker", "people_pleaser", -0.2),
    ("spectator", "recluse", 0.2),
]

# ── Notification defaults by age bracket ──
_NOTIFICATION_DEFAULTS = {
    (14, 18): {"被@": True, "被回复": True, "被点赞": True, "被关注": True,
                "被收藏": True, "升级通知": True, "吧务通知": True, "私聊消息": True},
    (19, 25): {"被@": True, "被回复": True, "被点赞": True, "被关注": True,
                "被收藏": True, "升级通知": True, "吧务通知": True, "私聊消息": True},
    (26, 35): {"被@": True, "被回复": True, "被点赞": True, "被关注": True,
                "被收藏": True, "升级通知": False, "吧务通知": True, "私聊消息": True},
    (36, 50): {"被@": True, "被回复": True, "被点赞": False, "被关注": False,
                "被收藏": True, "升级通知": False, "吧务通知": True, "私聊消息": True},
}

# ── Naming styles (from 02-1-ex_起名规范) ──
NAMING_STYLES = [
    {
        "id": 1, "category": "外号/江湖型",
        "logic": "地名/特征 + 名中一字，或动物/自然物 + 单字",
        "age_min": 36, "age_max": 50,
        "personality_bias": ["hothead", "peacemaker"],
    },
    {
        "id": 2, "category": "古风/诗意型",
        "logic": "两字、三字或四字意境组合，自创或化用诗词",
        "age_min": 31, "age_max": 41,
        "personality_bias": ["truthseeker", "cute_pet"],
    },
    {
        "id": 3, "category": "居士/隐士型",
        "logic": "姓氏 + 居士/散人，或宗教/哲学概念词",
        "age_min": 36, "age_max": 46,
        "personality_bias": ["recluse", "peacemaker"],
    },
    {
        "id": 4, "category": "生活状态型",
        "logic": "描述当前状态、日常习惯或自我评价",
        "age_min": 26, "age_max": 36,
        "personality_bias": ["spectator", "people_pleaser"],
    },
    {
        "id": 5, "category": "废话/无意义型",
        "logic": "平凡的真理、凑字数、无实际信息量的句子",
        "age_min": 26, "age_max": 36,
        "personality_bias": ["spectator", "hothead"],
    },
    {
        "id": 6, "category": "圈内黑话/角色梗型",
        "logic": "特定游戏/动漫/历史事件/主播圈的角色外号、剧情梗、组织名",
        "age_min": 16, "age_max": 26,
        "personality_bias": ["instigator", "cute_pet"],
    },
    {
        "id": 7, "category": "自嘲/匿名型",
        "logic": "调侃社区规则、假装注销、保留默认名或统一马甲",
        "age_min": 14, "age_max": 50,
        "personality_bias": ["recluse", "spectator"],
    },
    {
        "id": 8, "category": "仿名型",
        "logic": "模仿知名博主或游戏角色，谐音或字形改动",
        "age_min": 21, "age_max": 31,
        "personality_bias": ["people_pleaser", "spectator"],
    },
    {
        "id": 9, "category": "诗句/歌词取样型",
        "logic": "直接截取一句诗词或流行歌词",
        "age_min": 31, "age_max": 41,
        "personality_bias": ["truthseeker", "cute_pet"],
    },
    {
        "id": 10, "category": "小说角色/OC型",
        "logic": "使用原创角色名或冷门小说角色名",
        "age_min": 21, "age_max": 36,
        "personality_bias": ["cute_pet", "peacemaker"],
    },
    {
        "id": 11, "category": "意象/隐喻组合型",
        "logic": "将两个或多个具有内在逻辑或情绪关联的具体物象并置，形成新画面或隐喻（含矛盾修辞）",
        "age_min": 26, "age_max": 36,
        "personality_bias": ["truthseeker", "spectator"],
    },
    {
        "id": 12, "category": "典故嵌入型",
        "logic": "将核心字放入经典成语/诗词中，保留原字",
        "age_min": 31, "age_max": 41,
        "personality_bias": ["truthseeker", "recluse"],
    },
    {
        "id": 13, "category": "中二生僻字/特殊符号装饰型",
        "logic": "使用生僻字、罕见字组合，或添加装饰性符号（如灬、丶），追求视觉冲击或酷感",
        "age_min": 16, "age_max": 26,
        "personality_bias": ["instigator", "hothead"],
    },
    {
        "id": 14, "category": "颜文字/表情符号型",
        "logic": "使用颜文字（如 QwQ、TAT、QAQ）作为主体或组成部分",
        "age_min": 26, "age_max": 36,
        "personality_bias": ["cute_pet", "people_pleaser"],
    },
    {
        "id": 15, "category": "英文类（含中英混合）",
        "logic": "以英文单词、字母组合为主体，或中英混合（非拼音）；包含有意义单词、无意义字母组合、中英杂糅、英文拟音等子类型",
        "age_min": 26, "age_max": 41,
        "personality_bias": ["truthseeker", "instigator"],
    },
]


# ── AgentDraft ──
@dataclass
class AgentDraft:
    # Step 1
    age: int = 0
    gender: str = ""
    occupation: str = ""
    income_level: str = ""
    education: str = ""
    # Step 2
    candidate_interests: list[dict] = field(default_factory=list)
    # Step 3
    school_or_company: str = ""
    district: str = ""
    boarding: bool | None = None
    # Step 5a
    personality_vector: dict[str, float] = field(default_factory=dict)
    personality_adjectives: list[str] = field(default_factory=list)
    naming_style: dict = field(default_factory=dict)
    # Step 4
    interests: list[str] = field(default_factory=list)
    custom_interest: str | None = None
    nickname: str = ""
    bio: str = ""
    schedule_raw: dict = field(default_factory=dict)
    life_history: list[dict] = field(default_factory=list)
    # Step 6
    slang_slugs: list[str] = field(default_factory=list)
    # Step 7
    notification_settings: dict = field(default_factory=dict)
    stealth_mode: bool = False


# ── Step functions ──

def generate_hard_conditions() -> AgentDraft:
    draft = AgentDraft()

    intervals = [r for r, _ in _AGE_INTERVALS]
    weights = [w for _, w in _AGE_INTERVALS]
    age_lo, age_hi = random.choices(intervals, weights=weights)[0]
    draft.age = random.randint(age_lo, age_hi)

    draft.gender = random.choice(["男", "女"])

    if draft.age < 18:
        draft.occupation = "学生"
    elif draft.age <= 22:
        draft.occupation = random.choices(["学生", "初入职场"], weights=[0.6, 0.4])[0]
    else:
        draft.occupation = random.choice(_OCCUPATION_POOL)

    draft.income_level, draft.education = _lookup_income_edu(draft.age, draft.occupation)

    return draft


def screen_interest_pool(draft: AgentDraft) -> AgentDraft:
    draft.candidate_interests = sample_interest_candidates(draft.age)
    return draft


def assign_city_location(draft: AgentDraft) -> AgentDraft:
    loc = assign_location(draft.age, draft.occupation)
    draft.school_or_company = loc["school_or_company"]
    draft.district = loc["district"]
    draft.boarding = loc["boarding"]
    return draft


def gen_personality_initial(draft: AgentDraft) -> AgentDraft:
    vec = {}
    for trait, tmax in _TRAIT_MAX.items():
        vec[trait] = random.uniform(0.02, tmax)

    total = sum(vec.values())
    vec = {k: v / total for k, v in vec.items()}
    draft.personality_vector = vec

    # Map top 3 traits to adjectives
    sorted_traits = sorted(vec.items(), key=lambda x: x[1], reverse=True)
    adjectives = []
    for trait, _ in sorted_traits[:3]:
        adj = random.choice(TRAIT_ADJECTIVES[trait])
        adjectives.append(adj)
    draft.personality_adjectives = adjectives

    return draft


def select_naming_style(draft: AgentDraft) -> AgentDraft:
    # Filter by age range
    age = draft.age
    candidates = [s for s in NAMING_STYLES if s["age_min"] <= age <= s["age_max"]]
    if not candidates:
        # Take closest 4 styles + always include 自嘲/匿名型
        candidates = sorted(NAMING_STYLES, key=lambda s: min(
            abs(s["age_min"] - age), abs(s["age_max"] - age)
        ))[:4]
        anon = next(s for s in NAMING_STYLES if s["id"] == 7)
        if anon not in candidates:
            candidates.append(anon)

    # Boost styles matching top 2 personality traits
    top_traits = sorted(draft.personality_vector.items(), key=lambda x: x[1], reverse=True)
    top2 = {top_traits[0][0], top_traits[1][0]}

    weights = []
    for s in candidates:
        w = 1.0
        for bias in s["personality_bias"]:
            if bias in top2:
                w *= 1.5
        weights.append(w)

    draft.naming_style = random.choices(candidates, weights=weights)[0]
    return draft


def gen_personality_adjust(draft: AgentDraft) -> AgentDraft:
    vec = dict(draft.personality_vector)
    mean_val = 1.0 / 8

    for a, b, coef in CORRELATIONS:
        drift_a = vec[a] - mean_val
        vec[b] += coef * 0.1 * drift_a

    # Clamp and normalize
    for k in vec:
        vec[k] = max(0.02, vec[k])

    total = sum(vec.values())
    vec = {k: v / total for k, v in vec.items()}
    draft.personality_vector = vec
    return draft


async def ai_autonomous_selection(draft: AgentDraft, llm_caller: Callable) -> AgentDraft:
    hard = (
        f"年龄：{draft.age}岁，性别：{draft.gender}，"
        f"职业：{draft.occupation}，收入：{draft.income_level}，"
        f"学历：{draft.education}，居住地：{draft.district}，"
        f"学校/单位：{draft.school_or_company}"
    )

    interests_text = "\n".join(
        f"- {t['name']}（{t['category']}）"
        for t in draft.candidate_interests
    )

    naming_style_text = (
        f"{draft.naming_style['category']}：{draft.naming_style['logic']}。"
        f"适用年龄段：{draft.naming_style['age_min']}-{draft.naming_style['age_max']}岁"
    )

    life_count = round(10 * math.log(draft.age / 18 + 1) + 10)
    allow_custom = "true" if random.random() < 0.05 else "false"

    adjectives = "、".join(draft.personality_adjectives)

    custom_instruction = (
        "你可以自定义一个兴趣标签（需符合你的年龄和身份），"
        "5% 概率触发，当前已触发，请设置 custom_interest 字段"
        if allow_custom == "true"
        else "本轮无需自定义兴趣，custom_interest 设为 null"
    )

    ctx = {
        "hard_conditions": hard,
        "candidate_interests": interests_text,
        "personality_adjectives": adjectives,
        "naming_style": naming_style_text,
        "custom_interest_instruction": custom_instruction,
        "life_events_count": str(life_count),
    }

    result = await execute("agent_registration", ctx, llm_caller=llm_caller)

    if result.status == "success" and isinstance(result.parsed, dict):
        parsed = result.parsed
        draft.interests = parsed.get("interests", [])
        draft.custom_interest = parsed.get("custom_interest")
        draft.nickname = parsed.get("nickname", "")
        draft.bio = parsed.get("bio", "")
        draft.schedule_raw = parsed.get("schedule", {})
        draft.life_history = parsed.get("life_history", [])
    else:
        logger.warning("ai_autonomous_selection_failed", status=result.status, error=result.error)
        # fallback defaults
        draft.interests = [t["name"] for t in draft.candidate_interests[:5]]
        draft.nickname = f"用户{draft.age}"
        draft.bio = "一个普通的平陵市民"
        draft.schedule_raw = {
            "active_windows": [{"day": "weekday", "start": "18:00", "end": "22:00", "weight": 1.0}],
            "browse_speed": "normal", "reply_impulse": 0.5,
            "max_flow_rounds": 5, "max_flow_per_day": 3,
        }
        draft.life_history = []

    return draft


async def prelearn_slangs(draft: AgentDraft, llm_caller: Callable) -> AgentDraft:
    # Slang pre-learning is deferred until slangs table has data
    return draft


def set_notification_defaults(draft: AgentDraft) -> AgentDraft:
    for (lo, hi), defaults in _NOTIFICATION_DEFAULTS.items():
        if lo <= draft.age <= hi:
            draft.notification_settings = dict(defaults)
            break
    else:
        draft.notification_settings = dict(list(_NOTIFICATION_DEFAULTS.values())[0])

    # 中学生防发现模式 (50% for 14-18 boarding day students)
    if draft.age <= 18 and draft.occupation == "学生" and draft.boarding is False:
        if random.random() < 0.5:
            draft.stealth_mode = True
            for k in draft.notification_settings:
                draft.notification_settings[k] = False

    return draft


async def validate_agent(draft: AgentDraft, llm_caller: Callable) -> bool:
    prompt = (
        f"检查以下 Agent 配置是否合理：\n"
        f"年龄：{draft.age}，职业：{draft.occupation}，兴趣：{draft.interests}\n"
        f"性格：{draft.personality_adjectives}，简介：{draft.bio}\n"
        f"是否有明显矛盾？仅回复 YES 或 NO。"
    )
    try:
        resp = await llm_caller(prompt, "inclusionAI/Ling-mini-2.0")
        return "NO" in resp.upper()
    except Exception as e:
        logger.warning("validate_agent_error", error=str(e))
        return True  # pass-through on error


# ── Orchestrator ──

async def create_agent(
    db_session,
    *,
    llm_caller: Callable | None = None,
    manual_input: dict | None = None,
) -> Agent:
    from app.skills.llm_manager import create_llm_caller as _create_llm_caller

    if llm_caller is None:
        llm_caller = _create_llm_caller()

    if manual_input:
        return await _create_manual_agent(db_session, manual_input)

    # Full 8-step pipeline
    draft = generate_hard_conditions()
    draft = screen_interest_pool(draft)
    draft = assign_city_location(draft)
    draft = gen_personality_initial(draft)
    draft = select_naming_style(draft)
    draft = await ai_autonomous_selection(draft, llm_caller)
    draft = gen_personality_adjust(draft)
    draft = await prelearn_slangs(draft, llm_caller)
    draft = set_notification_defaults(draft)

    # Validate with retry
    if not await validate_agent(draft, llm_caller):
        logger.warning("agent_validation_failed", retrying=True, age=draft.age)
        draft = await ai_autonomous_selection(draft, llm_caller)
        draft = gen_personality_adjust(draft)
        draft = set_notification_defaults(draft)
        if not await validate_agent(draft, llm_caller):
            logger.warning("agent_validation_failed_retry", pass_through=True)

    return await _persist_agent(draft, db_session)


async def _create_manual_agent(db_session, manual_input: dict) -> Agent:
    draft = AgentDraft()
    draft.nickname = manual_input.get("nickname", "")
    draft.age = manual_input.get("age", 0)
    draft.gender = manual_input.get("gender", "")
    draft.interests = manual_input.get("interests", [])
    draft.schedule_raw = manual_input.get("schedule", {})
    draft = set_notification_defaults(draft)

    agent = await _persist_agent(draft, db_session)
    return agent


async def _persist_agent(draft: AgentDraft, db_session) -> Agent:
    agent = Agent(
        nickname=draft.nickname,
        age=draft.age,
        gender=draft.gender,
        occupation=draft.occupation,
        income_level=draft.income_level,
        education=draft.education,
        district=draft.district,
        school_or_company=draft.school_or_company,
        boarding=draft.boarding or False,
        interests=draft.interests,
        personality_vector=draft.personality_vector,
        life_history=draft.life_history,
        notification_settings=draft.notification_settings,
        stealth_mode=draft.stealth_mode,
        status="active",
    )
    db_session.add(agent)
    await db_session.flush()

    windows = draft.schedule_raw.get("active_windows", [
        {"day": "weekday", "start": "18:00", "end": "22:00", "weight": 1.0},
    ])
    schedule = AgentSchedule(
        agent_id=agent.id,
        active_windows=windows,
        browse_speed=draft.schedule_raw.get("browse_speed", "normal"),
        reply_impulse=draft.schedule_raw.get("reply_impulse", 0.5),
        max_flow_rounds=draft.schedule_raw.get("max_flow_rounds", 5),
        max_flow_per_day=draft.schedule_raw.get("max_flow_per_day", 3),
    )
    db_session.add(schedule)
    await db_session.flush()

    logger.info(
        "agent_created",
        agent_id=str(agent.id),
        nickname=agent.nickname,
        age=agent.age,
        occupation=agent.occupation,
    )
    return agent
