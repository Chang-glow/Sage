import httpx, os, asyncio, json

PROMPT = """你是老张，42岁书店老板，性格温和但话多。
你在浏览帖子「三体到底好在哪」，作者莉莉。
帖子内容：最近看了三体，感觉世界观很宏大，但有些科学概念不太懂。
你和莉莉的关系：友好，亲密度0.5。
请决定是否回复。严格按JSON格式输出：
{"will_reply": true/false, "reason": "理由", "suggested_tone": "语气"}"""

async def test(model):
    try:
        async with httpx.AsyncClient(timeout=120) as c:
            r = await c.post(
                "https://api.siliconflow.cn/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {os.environ['SILICONFLOW_API_KEY']}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": PROMPT}],
                    "max_tokens": 200,
                    "temperature": 0.7,
                },
            )
            print(f"--- {model} ---")
            print(f"Status: {r.status_code}")
            if r.status_code == 200:
                d = r.json()
                content = d["choices"][0]["message"]["content"]
                tokens = d.get("usage", {})
                print(f"Content: {content}")
                print(f"Tokens: prompt={tokens.get('prompt_tokens','?')} completion={tokens.get('completion_tokens','?')} total={tokens.get('total_tokens','?')}")
                clean = content.strip()
                if clean.startswith("```"):
                    clean = clean.split("\n", 1)[1].rsplit("\n", 1)[0]
                try:
                    parsed = json.loads(clean)
                    print(f"Parsed OK: {parsed}")
                except Exception:
                    print("JSON parse FAILED")
            else:
                print(f"Error: {r.text[:300]}")
        print()
    except Exception as e:
        print(f"{model}: {type(e).__name__} - {e}\n")

async def main():
    for m in ["inclusionAI/Ling-mini-2.0", "zai-org/GLM-4.5-Air"]:
        await test(m)

asyncio.run(main())
