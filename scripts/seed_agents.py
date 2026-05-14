#!/usr/bin/env python3
"""种子 Agent 部署脚本：创建 5 个 Agent 用于测试。"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.engine.agent_factory import create_agent
from app.skills.llm_manager import create_llm_caller as _create_llm_caller
from app.skills.registry import registry


async def main():
    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine)

    registry.load_all()

    async with session_factory() as session:
        agents = []
        for i in range(5):
            agent = await create_agent(session, llm_caller=_create_llm_caller(use_mock=True))
            agents.append(agent)
            pv = agent.personality_vector or {}
            top = sorted(pv.items(), key=lambda x: x[1], reverse=True)[:3]
            top_str = ", ".join(f"{k}={v:.2f}" for k, v in top)
            print(f"[{i+1}/5] {agent.nickname} ({agent.age}岁 {agent.occupation}) | {top_str}")
            if agent.life_history:
                print(f"      过往经历: {len(agent.life_history)} 条")

        await session.commit()
        print(f"\n成功创建 {len(agents)} 个种子 Agent")


if __name__ == "__main__":
    asyncio.run(main())
