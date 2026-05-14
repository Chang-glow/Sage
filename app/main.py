import asyncio
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import config, validate

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    missing = validate()
    if missing:
        logger.error("config_validation_failed", missing=missing)
        raise RuntimeError(f"Missing required env vars: {', '.join(missing)}")
    logger.info("server_starting", host=config.server.host, port=config.server.port)
    # 调度引擎将在 Phase 5 中启动
    yield
    logger.info("server_stopping")


app = FastAPI(
    title="夕照雅巷 (Sunny Graceful Alley)",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[config.server.frontend_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "ok"}
