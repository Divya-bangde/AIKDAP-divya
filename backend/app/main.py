"""FastAPI application entrypoint.

Creates and configures the FastAPI app: middleware, lifespan hooks,
and the foundation-level routes. Feature routers are mounted under
the versioned API prefix as they are implemented in later milestones.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.llm.startup_validation import run_startup_validation
from app.core.logging.logger import configure_logging, get_logger
from app.modules.assets.router import router as assets_router
from app.modules.auth.router import router as auth_router
from app.modules.health.router import router as health_router
from app.modules.knowledge_base.router import router as knowledge_base_router
from app.modules.projects.router import router as projects_router
from app.modules.research.router import router as research_router
from app.modules.tasks.router import router as tasks_router

configure_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Manage application startup and shutdown events."""
    logger.info(
        "application_startup",
        app_name=settings.app_name,
        app_version=settings.app_version,
        app_env=settings.app_env,
    )
    # Sprint 9H: check the configured provider chain against each
    # provider's own model catalogue. Diagnostic only — logged and left
    # for `/health` to keep surfacing, never fatal to startup. See
    # `run_startup_validation`'s docstring for why: a missing optional
    # fallback or a model a provider quietly removed should be visible
    # immediately, not a reason the whole platform refuses to boot.
    await run_startup_validation()
    yield
    logger.info("application_shutdown", app_name=settings.app_name)


app = FastAPI(
    title=settings.app_name,
    description="AI Knowledge Discovery And Analytics Platform API",
    version=settings.app_version,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.backend_cors_origins or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Health is mounted without the version prefix, at the same `/health`
# path its previous inline handler used, so existing monitoring keeps
# working. Infrastructure endpoints are deliberately outside the
# versioned product API.
app.include_router(health_router)

# Feature routers are registered here under the versioned API prefix
# as they are implemented.
app.include_router(auth_router, prefix=settings.api_v1_prefix)
app.include_router(projects_router, prefix=settings.api_v1_prefix)
app.include_router(assets_router, prefix=settings.api_v1_prefix)
app.include_router(tasks_router, prefix=settings.api_v1_prefix)
app.include_router(knowledge_base_router, prefix=settings.api_v1_prefix)
app.include_router(research_router, prefix=settings.api_v1_prefix)


@app.get("/", tags=["Root"])
async def root() -> dict[str, str]:
    """Return basic API metadata."""
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "environment": settings.app_env,
    }
