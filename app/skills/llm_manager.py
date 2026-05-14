from __future__ import annotations

import asyncio
import logging
from typing import Callable

import httpx
import structlog
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from app.config import config as yaml_config, settings

logger = structlog.get_logger()

_llm_semaphore = None
_token_usage: dict[str, int] = {"_global": 0}


def _get_semaphore() -> asyncio.Semaphore:
    global _llm_semaphore
    if _llm_semaphore is None:
        limit = yaml_config.scheduler.max_llm_requests_per_second
        _llm_semaphore = asyncio.Semaphore(limit)
    return _llm_semaphore


def _is_retryable(exception: BaseException) -> bool:
    if isinstance(exception, httpx.TimeoutException):
        return True
    if isinstance(exception, httpx.HTTPStatusError):
        status = exception.response.status_code
        return status == 429 or status >= 500
    return False


def _track_tokens(agent_id: str | None, prompt_tokens: int, completion_tokens: int) -> None:
    total = prompt_tokens + completion_tokens
    _token_usage["_global"] += total
    if agent_id:
        _token_usage[agent_id] = _token_usage.get(agent_id, 0) + total


def check_token_limit(agent_id: str | None = None) -> bool:
    global_limit = yaml_config.security.global_token_limit
    if _token_usage["_global"] >= global_limit:
        return False
    if agent_id:
        agent_limit = yaml_config.security.default_agent_token_limit
        if _token_usage.get(agent_id, 0) >= agent_limit:
            return False
    return True


def reset_token_counters() -> None:
    _token_usage.clear()
    _token_usage["_global"] = 0


@retry(
    retry=retry_if_exception(_is_retryable),
    stop=stop_after_attempt(3),
    wait=wait_exponential(min=1, max=10, multiplier=2),
    reraise=True,
)
async def _call_provider(
    prompt: str,
    model: str,
    base_url: str,
    api_key: str,
    timeout: float = 60.0,
) -> tuple[str, int, int]:
    logger.info("llm_call_start", model=model, prompt_len=len(prompt))
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout)) as client:
        resp = await client.post(
            f"{base_url}/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.7,
            },
        )
        resp.raise_for_status()
        data = resp.json()
    content = data["choices"][0]["message"]["content"]
    usage = data.get("usage", {})
    prompt_tokens = usage.get("prompt_tokens", 0)
    completion_tokens = usage.get("completion_tokens", 0)
    logger.info(
        "llm_call_success",
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )
    return content, prompt_tokens, completion_tokens


async def call_llm(
    prompt: str,
    model: str,
    *,
    agent_id: str | None = None,
    skill_id: str | None = None,
) -> str:
    sem = _get_semaphore()
    async with sem:
        if not check_token_limit(agent_id):
            raise RuntimeError(
                f"Token limit exceeded for agent={agent_id or 'global'}"
            )

        content, pt, ct = await _call_provider(
            prompt=prompt,
            model=model,
            base_url=settings.siliconflow_base_url,
            api_key=settings.siliconflow_api_key,
        )

        _track_tokens(agent_id, pt, ct)
        return content


class MockLLM:
    def __init__(self, responses: dict[str, str] | None = None):
        self.responses = responses or _default_mock_responses()

    async def call(self, prompt: str, model: str = "", *, skill_id: str | None = None) -> str:
        if skill_id and skill_id in self.responses:
            return self.responses[skill_id]
        return '{"status": "ok", "result": "mock_response"}'


def _default_mock_responses() -> dict[str, str]:
    return {
        "reply_decision": '{"will_reply": true, "reason": "这个话题与我有关", "suggested_tone": "友好"}',
        "offline_summary": '{"summary": "今天心情平静", "urge_type": null, "urge_intensity": 0.3}',
        "post_decision": '{"will_post": false, "reason": "无强烈发帖冲动", "urge_type": null}',
        "agent_registration": '{"interests": ["刷短视频", "听音乐", "追剧", "打游戏", "养宠物"], "custom_interest": null, "nickname": "测试用户", "bio": "一个普通的平陵市居民", "schedule": {"active_windows": [{"day": "weekday", "start": "18:00", "end": "22:00", "weight": 1.0}, {"day": "weekend", "start": "10:00", "end": "23:00", "weight": 0.8}], "browse_speed": "normal", "reply_impulse": 0.5, "max_flow_rounds": 5, "max_flow_per_day": 3}, "life_history": [{"age": 14, "category": "family", "event": "父亲工作调动，全家搬到平陵市，转学到了新学校", "share_willingness": 0.6, "impact_weight": 0.7}, {"age": 16, "category": "school", "event": "第一次在班级演讲比赛上获奖，发现自己在人前说话没那么紧张了", "share_willingness": 0.4, "impact_weight": 0.6}]}',
    }


def create_llm_caller(use_mock: bool | None = None) -> Callable:
    if use_mock is None:
        use_mock = not (
            bool(settings.siliconflow_api_key)
            and settings.siliconflow_api_key != "sk-xxxxxxxx"
        )
    if use_mock:
        mock = MockLLM()
        return mock.call
    return call_llm
