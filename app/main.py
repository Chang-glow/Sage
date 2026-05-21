import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import config, settings, validate

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.BoundLogger,
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    missing = validate()
    if missing:
        logger.warning("config_validation_missing", missing=missing)
    logger.info("server_starting", host=config.server.host, port=config.server.port)

    from app.skills.registry import registry, watch_skills_dir

    count = registry.load_all()
    logger.info("skills_loaded", count=count)

    skills_dir = Path(__file__).resolve().parent / "skills"
    watch_task = asyncio.create_task(watch_skills_dir(skills_dir))

    engine = create_async_engine(settings.database_url)
    app.state.db_session_factory = async_sessionmaker(engine, expire_on_commit=False)

    from app.jobs.scheduler import run_scheduler_loop

    stop_event = asyncio.Event()
    scheduler_task = asyncio.create_task(
        run_scheduler_loop(app.state.db_session_factory, stop_event)
    )

    yield

    stop_event.set()
    watch_task.cancel()
    scheduler_task.cancel()
    try:
        await scheduler_task
    except asyncio.CancelledError:
        pass
    try:
        await watch_task
    except asyncio.CancelledError:
        pass

    await engine.dispose()
    logger.info("server_stopping")


app = FastAPI(
    title="夕照雅巷 (Sunny Graceful Alley)",
    version="0.5.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[config.server.frontend_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


from app.api.agents import router as agents_router
from app.api.admin import router as admin_router
from app.api.features import router as features_router

app.include_router(agents_router, prefix="/api/agents", tags=["agents"])
app.include_router(admin_router, prefix="/api/admin", tags=["admin"])
app.include_router(features_router, prefix="/api", tags=["features"])


@app.get("/health")
async def health():
    return {"status": "ok"}
